"""Regression coverage for pointer-backed bridge writes and worktree discovery."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar.models import DomainError
from fstar.project import initialize_project
from fstar.store import POINTER_FILE, TaskStore, find_project_root
from tests.test_worktree_shared_root import WorktreeCase

ROOT = Path(__file__).resolve().parents[1]


class BridgeResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fstar-user-resolution-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / "project"
        self.user = self.base / "user"
        self.project.mkdir()
        self.user.mkdir()
        initialize_project(self.project, self.user, storage="user-directory")
        self.data = TaskStore(self.project, user_home=self.user).fstar_root
        self.env = dict(os.environ, HOME=str(self.base / "home"), PATH="",
                        PYTHONDONTWRITEBYTECODE="1", FSTAR_USER_ROOT=str(self.user),
                        FSTAR_RUNTIME_ROOT=str(self.base / "runtime"))

    def call(self, request):
        process = subprocess.run([sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"), "learn_bridge"],
                                 input=json.dumps(request), text=True, capture_output=True, env=self.env)
        return process.returncode, json.loads(process.stdout)

    def request(self, owner, path, content, member):
        return {"action": "prepare", "project_root": str(self.project), "user_root": str(self.user),
                "task_ref": "session-only", "extensions": [{"id": "project-governance", "scope": "custom",
                "included": [member], "excluded": []}],
                "edits": [{"owner": owner, "path": path, "action": "create", "content": content}],
                "intent": {"summary": "Record fact", "action": "create", "scope": owner,
                           "source": {"source_type": "conversation", "reference": "message 1"}},
                "assessment": {}}

    def test_prepare_and_apply_user_and_project_writes(self):
        cases = [
            ("user", "rules/note.md", "---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\nstrength: default\n---\n# Note\nMUST test.\n", "rules", self.user / "rules/note.md"),
            ("project", ".fstar/knowledge/context/note.md", "# Note\nFact.\n", "knowledge", self.data / "knowledge/context/note.md"),
        ]
        for owner, path, content, member, destination in cases:
            with self.subTest(owner=owner):
                request = self.request(owner, path, content, member)
                rc, prepared = self.call(request)
                self.assertEqual(0, rc, prepared)
                self.assertFalse(destination.exists())
                proposal = prepared["result"]["proposal"]
                confirmation = {"disposition": "approved", "source_type": "conversation",
                                "source_ref": "message 2", "quote": "Save this", "confirmed_at": "2026-10-30",
                                "proposal_hash": prepared["result"]["proposal_hash"],
                                "scope": proposal["scope"], "owners": proposal["owners"]}
                rc, result = self.call(dict(request, action="apply", confirmation=confirmation))
                self.assertEqual(0, rc, result)
                self.assertEqual(content, destination.read_text())

    def test_uninitialized_and_nonexistent_roots_are_refused(self):
        uninitialized = self.base / "uninitialized"
        uninitialized.mkdir()
        for root in (uninitialized, self.base / "missing"):
            for action in ("prepare", "apply"):
                with self.subTest(root=root, action=action):
                    request = self.request("project", ".fstar/knowledge/context/note.md", "# Note\n", "knowledge")
                    rc, result = self.call(dict(request, action=action, project_root=str(root)))
                    self.assertNotEqual(0, rc)
                    self.assertEqual("knowledge_invalid_schema", result["error"]["code"])
                    self.assertIn("Cannot resolve supplied project_root", result["error"]["message"])
                    self.assertIn(str(root), result["error"]["message"])
                    self.assertEqual({"project_root": str(root), "resolved_project_root": None},
                                     result["error"]["details"])
        self.assertFalse((self.base / "missing").exists())

    def test_moved_and_corrupt_pointer_refused_by_bridge(self):
        request = self.request("user", "rules/note.md", "# Note\n", "rules")
        pointer = self.project / POINTER_FILE
        record = json.loads(pointer.read_text())
        record["bound_path"] = str(self.base / "elsewhere")
        pointer.write_text(json.dumps(record))
        rc, result = self.call(request)
        self.assertNotEqual(0, rc)
        self.assertEqual("project_moved_needs_rebind", result["error"]["code"])
        pointer.write_text("{")
        rc, result = self.call(request)
        self.assertNotEqual(0, rc)
        self.assertEqual("corrupt_pointer", result["error"]["code"])


class WorktreePointerSafetyTests(WorktreeCase):
    def test_main_pointer_failure_cases_are_not_followed(self):
        main = self._main_repo(storage="user-directory")
        worktree = self._worktree(main)
        pointer = main / POINTER_FILE
        original = pointer.read_text()
        pointer.write_text("{")
        with self.assertRaises(DomainError) as caught:
            find_project_root(worktree)
        self.assertEqual("corrupt_pointer", caught.exception.code)
        record = json.loads(original)
        record["bound_path"] = str(self.base / "moved")
        pointer.write_text(json.dumps(record))
        self.assertIsNone(find_project_root(worktree))
        pointer.unlink()
        target = self.base / "pointer-target"
        target.write_text(original)
        pointer.symlink_to(target)
        self.assertIsNone(find_project_root(worktree))
        pointer.unlink()
        data_root = Path(record["data_root"])
        alias = self.base / "data-alias"
        alias.symlink_to(data_root, target_is_directory=True)
        record["bound_path"] = str(main)
        record["data_root"] = str(alias)
        pointer.write_text(json.dumps(record))
        with self.assertRaises(DomainError) as caught:
            find_project_root(worktree)
        self.assertEqual("corrupt_pointer", caught.exception.code)

    def test_worktree_pointer_precedence_and_refusal(self):
        main = self._main_repo(storage="user-directory")
        worktree = self._worktree(main)
        pointer = worktree / POINTER_FILE
        record = json.loads((main / POINTER_FILE).read_text())
        # A pointer bound to the worktree resolves it even with a valid main.
        record["bound_path"] = str(worktree)
        pointer.write_text(json.dumps(record))
        self.assertEqual(worktree, find_project_root(worktree))
        nested = worktree / "nested"
        nested.mkdir()
        record["bound_path"] = str(self.base / "previous-location")
        pointer.write_text(json.dumps(record))
        self.assertIsNone(find_project_root(worktree))
        self.assertIsNone(find_project_root(nested))
        pointer.unlink()
        pointer.symlink_to(main / POINTER_FILE)
        self.assertIsNone(find_project_root(worktree))
        self.assertIsNone(find_project_root(nested))
        pointer.unlink()
        pointer.symlink_to(self.base / "missing-pointer")
        self.assertIsNone(find_project_root(worktree))

    def test_unusable_worktree_pointer_blocks_shared_and_local_fallback(self):
        for mode in ("project-shared", "project-local"):
            with self.subTest(mode=mode):
                main = self._main_repo(name="main-" + mode, storage=mode)
                worktree = self._worktree(main, name="wt-" + mode)
                self.assertEqual(main, find_project_root(worktree))
                pointer = worktree / POINTER_FILE
                pointer.symlink_to(self.base / "missing-pointer")
                self.assertIsNone(find_project_root(worktree))
                pointer.unlink()
                self.assertEqual(main, find_project_root(worktree))

    def test_non_utf8_main_pointer_is_corrupt(self):
        main = self._main_repo(storage="user-directory")
        worktree = self._worktree(main)
        (main / POINTER_FILE).write_bytes(b"\xff\xfe")
        with self.assertRaises(DomainError) as caught:
            find_project_root(worktree)
        self.assertEqual("corrupt_pointer", caught.exception.code)
        self.assertEqual(str(main / POINTER_FILE), caught.exception.details["path"])

    def test_nested_user_worktree_resolves_main(self):
        main = self._main_repo(storage="user-directory")
        worktree = self._worktree(main)
        nested = worktree / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(main, find_project_root(nested))
        self.assertFalse((worktree / POINTER_FILE).exists())


if __name__ == "__main__":
    unittest.main()
