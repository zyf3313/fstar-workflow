"""Identity guard, knowledge resolution and diagnostics using real git worktrees."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar import knowledge, learn_bridge
from fstar.cli import build_parser
from fstar.installer import Roots, _schema_report, roots_from_args
from fstar.models import DomainError
from fstar.project import InitError, doctor_worktree_report, initialize_project
from fstar.store import POINTER_FILE, TaskStore, find_project_root
from fstar.tasks import TaskService
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODES = ("project-shared", "project-local", "user-directory")


class WorktreeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fstar-identity-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.user = self.base / "user"
        self.user.mkdir()
        self.runtime = self.base / "runtime"
        self.env = dict(os.environ, HOME=str(self.base / "home"),
                        FSTAR_USER_ROOT=str(self.user), FSTAR_RUNTIME_ROOT=str(self.runtime),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                        PYTHONDONTWRITEBYTECODE="1")

    def git(self, *args):
        subprocess.run(["git", *map(str, args)], check=True, capture_output=True,
                       text=True, env=self.env)

    def fixture(self, mode="user-directory", initialized=True):
        main = self.base / (mode + "-main")
        worktree = self.base / (mode + "-wt")
        main.mkdir()
        self.git("init", "-q", main)
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "baseline")
        if initialized:
            initialize_project(main, self.user, storage=mode)
        self.git("-C", main, "worktree", "add", "-q", "-b", "identity-test", worktree)
        return main, worktree

    def store(self, root):
        return TaskStore(root, user_home=self.user, runtime_root=self.runtime)

    def snapshot(self):
        return {str(path.relative_to(self.base)): path.read_bytes()
                for path in self.base.rglob("*") if path.is_file() and not path.is_symlink()}

    def cli(self, cwd, *args):
        return subprocess.run([sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"),
                               "cli", "--json", "--user-data-root", str(self.user),
                               "--runtime-root", str(self.runtime), *args], cwd=cwd,
                              env=self.env, capture_output=True, text=True)

    def request(self, root):
        return {"action": "prepare", "project_root": str(root), "user_root": str(self.user),
                "runtime_root": str(self.runtime), "task_ref": "session-only",
                "extensions": [{"id": "project-governance", "scope": "custom",
                                "included": ["knowledge"], "excluded": []}],
                "edits": [{"owner": "project", "path": ".fstar/knowledge/context/note.md",
                           "action": "create", "content": "# Note\nShared fact.\n"}],
                "intent": {"summary": "Record fact", "action": "create", "scope": "project",
                           "source": {"source_type": "conversation", "reference": "test request"}},
                "assessment": {}}

    def test_init_refusal_is_zero_write_and_names_both_roots(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                before = self.snapshot()
                for dry_run in (False, True):
                    with self.assertRaises(InitError) as caught:
                        initialize_project(worktree, self.user, dry_run=dry_run)
                    self.assertEqual("WORKTREE_SHARED_PROJECT", caught.exception.code)
                    self.assertIn(str(main), caught.exception.message)
                    self.assertIn(str(self.store(main).fstar_root), caught.exception.message)
                    self.assertIn("--force-separate", caught.exception.message)
                result = self.cli(worktree, "init")
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("WORKTREE_SHARED_PROJECT", json.loads(result.stderr)["error"]["code"])
                self.assertEqual(before, self.snapshot())

    def test_tracked_shared_metadata_reinit_and_separation_refusal(self):
        main = self.base / "tracked-main"
        worktree = self.base / "tracked-wt"
        main.mkdir()
        self.git("init", "-q", main)
        initialize_project(main, self.user, storage="project-shared")
        self.git("-C", main, "add", "-f", ".fstar")
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "tracked metadata")
        self.git("-C", main, "worktree", "add", "-q", "-b", "tracked-test", worktree)
        identity = self.store(main).project_id
        before = self.snapshot()
        for storage in (None, "project-shared"):
            result = initialize_project(worktree, self.user, storage=storage)
            self.assertEqual((), result.created)
            self.assertEqual(identity, self.store(worktree).project_id)
        self.assertEqual(before, self.snapshot())
        for storage in (None, "project-shared", "project-local", "user-directory"):
            for dry_run in (False, True):
                with self.subTest(storage=storage, dry_run=dry_run), self.assertRaises(InitError) as caught:
                    initialize_project(worktree, self.user, storage=storage,
                                       force_separate=True, dry_run=dry_run)
                self.assertEqual("WORKTREE_IDENTITY_EXISTS", caught.exception.code)
                self.assertEqual(before, self.snapshot())
        result = self.cli(worktree, "init", "--force-separate")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("WORKTREE_IDENTITY_EXISTS", json.loads(result.stderr)["error"]["code"])
        self.assertEqual(before, self.snapshot())

    def test_nested_init_guard_and_default_mode_opt_in(self):
        main, worktree = self.fixture()
        nested = worktree / "nested"
        nested.mkdir()
        before = self.snapshot()
        result = self.cli(nested, "init")
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(str(main), result.stderr)
        self.assertEqual(before, self.snapshot())
        result = self.cli(worktree, "init", "--force-separate")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["force_separate"])
        self.assertEqual("project-shared", self.store(worktree).storage_mode)
        self.assertNotEqual(self.store(main).project_id, self.store(worktree).project_id)

    def test_opt_in_creates_normal_separate_identity_and_records_choice(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                main_identity = self.store(main).project_id
                before = self.snapshot()
                result = self.cli(worktree, "init", "--force-separate", "--storage", "user-directory", "--dry-run")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(json.loads(result.stdout)["force_separate"])
                self.assertEqual(before, self.snapshot())
                result = self.cli(worktree, "init", "--force-separate", "--storage", "user-directory")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(json.loads(result.stdout)["force_separate"])
                self.assertEqual(worktree, find_project_root(worktree))
                self.assertNotEqual(main_identity, self.store(worktree).project_id)
                self.assertEqual(main_identity, self.store(main).project_id)
                self.assertTrue((self.store(worktree).fstar_root / ".schema-version").is_file())
                self.assertFalse((worktree / ".fstar").exists())
                self.assertEqual("split", doctor_worktree_report(worktree, worktree)["status"])

    def test_main_reinit_standalone_and_uninitialized_main_unchanged(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                main, _ = self.fixture(mode)
                identity = self.store(main).project_id
                result = initialize_project(main, self.user)
                self.assertEqual((), result.created)
                self.assertFalse(result.force_separate)
                self.assertEqual(identity, self.store(main).project_id)
        plain = self.base / "plain"
        plain.mkdir()
        initialize_project(plain, self.user)
        self.assertEqual(plain, find_project_root(plain))
        main, worktree = self.fixture("uninitialized", initialized=False)
        initialize_project(worktree, self.user)
        self.assertEqual(worktree, find_project_root(worktree))
        self.assertIsNone(find_project_root(main))

    def test_healthy_tasks_and_learn_read_prepare_apply_share_main(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                nested = worktree / "nested"
                nested.mkdir()
                store = self.store(find_project_root(nested))
                TaskService(store).create(name="shared-task", title="Shared task", description="",
                                          actor={"role": "user", "id": "test"})
                self.assertTrue((self.store(main).fstar_root / "tasks/shared-task/task.json").is_file())
                request = self.request(nested)
                # Exercise stored grants and task-store resolution as well as provider roots.
                TaskService(store).enable_extension("shared-task", authorization={
                    **request["extensions"][0], "source": {"type": "test"}},
                    actor={"role": "user", "id": "test"})
                request.update(task_ref="shared-task", extensions=[])
                before = self.snapshot()
                read = learn_bridge.run(dict(request, action="read", selection={}))
                main_read = learn_bridge.run(dict(request, action="read", project_root=str(main), selection={}))
                self.assertEqual(main_read, read)
                prepared = learn_bridge.run(request)
                self.assertEqual(prepared, learn_bridge.run(dict(request, project_root=str(main))))
                self.assertEqual(before, self.snapshot())
                proposal = prepared["proposal"]
                confirmation = {"disposition": "approved", "source_type": "conversation",
                                "source_ref": "test confirmation", "quote": "Save this",
                                "confirmed_at": "2026-11-25", "proposal_hash": prepared["proposal_hash"],
                                "scope": proposal["scope"], "owners": proposal["owners"]}
                learn_bridge.run(dict(request, action="apply", confirmation=confirmation))
                note = self.store(main).fstar_root / "knowledge/context/note.md"
                self.assertEqual("# Note\nShared fact.\n", note.read_text())
                read = learn_bridge.run(dict(request, action="read", selection={
                    "documents": ["project:.fstar/knowledge/context/note.md"]}))
                self.assertTrue(any("Shared fact." in doc["text"] for doc in read["documents"]))
                self.assertFalse((worktree / ".fstar").exists())
                self.assertFalse((worktree / POINTER_FILE).exists())

    def test_unresolvable_bridge_guidance_and_provider_root_details(self):
        main, worktree = self.fixture(initialized=False)
        for root in (main, worktree):
            for action in ("read", "prepare", "apply"):
                with self.subTest(root=root, action=action), self.assertRaises(DomainError) as caught:
                    learn_bridge.run(dict(self.request(root), action=action, selection={}))
                self.assertEqual("knowledge_invalid_schema", caught.exception.code)
                self.assertIn("Cannot resolve supplied project_root", caught.exception.message)
                self.assertIn(str(root), caught.exception.message)
                self.assertNotIn("run init", caught.exception.message)
        initialize_project(main, self.user, storage="user-directory")
        data = self.store(main).fstar_root
        (data / ".schema-version").unlink()
        with self.assertRaises(DomainError) as caught:
            knowledge._require_initialized_project(main, data_root=data)
        self.assertIn(str(main), caught.exception.message)
        self.assertIn(str(data), caught.exception.message)

    def test_stale_split_pointer_reports_both_roots_without_fallback_or_writes(self):
        main, worktree = self.fixture()
        other = self.base / "other"
        other.mkdir()
        initialize_project(other, self.user, storage="user-directory")
        (worktree / POINTER_FILE).write_bytes((other / POINTER_FILE).read_bytes())
        initialize_project(self.base, self.user)
        nested = worktree / "nested"
        nested.mkdir()
        before = self.snapshot()
        self.assertIsNone(find_project_root(nested))
        for command in (("task", "list"), ("extension", "list")):
            result = self.cli(nested, *command)
            self.assertEqual(2, result.returncode, result.stderr)
            error = json.loads(result.stderr)["error"]
            self.assertEqual("project_moved_needs_rebind", error["code"])
            self.assertEqual(str(other), error["details"]["bound_path"])
            self.assertEqual(str(worktree), error["details"]["project_root"])
        report = doctor_worktree_report(worktree, None)
        self.assertEqual("split", report["status"])
        self.assertEqual(str(worktree), report["worktree_root"])
        self.assertEqual(str(self.store(main).fstar_root), report["main_data_root"])
        self.assertEqual(str(self.store(other).fstar_root), report["worktree_data_root"])
        self.assertIn("Pointer removal or data migration requires user confirmation", report["message"])
        self.assertIn("does not merge data", report["message"])
        roots = Roots(user_root=self.user, runtime_root=self.runtime, project_root=None,
                      host_roots={}, invoke_root=worktree)
        self.assertEqual(report, _schema_report(roots)["storage"]["worktree"])
        with self.assertRaises(DomainError):
            learn_bridge.run(self.request(worktree))
        self.assertEqual(before, self.snapshot())

    def test_matching_bound_pointer_and_healthy_report_unchanged(self):
        main, worktree = self.fixture()
        healthy = {"shared": True, "main_root": str(main),
                   "message": "当前 worktree 共享自 %s" % main}
        self.assertEqual(healthy, doctor_worktree_report(worktree, main))
        pointer = json.loads((main / POINTER_FILE).read_text())
        pointer["bound_path"] = str(worktree)
        (worktree / POINTER_FILE).write_text(json.dumps(pointer))
        self.assertEqual(worktree, find_project_root(worktree))
        before = self.snapshot()
        self.assertEqual(healthy, doctor_worktree_report(worktree, worktree))
        self.assertEqual(before, self.snapshot())
        self.assertIsNone(doctor_worktree_report(main, main))

    def test_unreadable_pointer_surfaces_as_report_and_never_falls_back(self):
        main, worktree = self.fixture()
        initialize_project(self.base, self.user)
        pointer = worktree / POINTER_FILE
        for content in (b"{broken", b"\xff", b"[]"):
            with self.subTest(content=content):
                pointer.write_bytes(content)
                before = self.snapshot()
                self.assertIsNone(find_project_root(worktree))
                args = build_parser().parse_args(["--user-data-root", str(self.user), "doctor"])
                with patch("pathlib.Path.cwd", return_value=worktree):
                    roots = roots_from_args(args)
                report = _schema_report(roots)["storage"]["worktree"]
                self.assertEqual("unreadable", report["status"])
                self.assertEqual(str(self.store(main).fstar_root), report["main_data_root"])
                for command in (("task", "list"), ("extension", "list")):
                    result = self.cli(worktree, *command)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual("corrupt_pointer", json.loads(result.stderr)["error"]["code"])
                result = self.cli(worktree, "doctor")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("unreadable", json.loads(result.stdout)["schema_report"]["storage"]["worktree"]["status"])
                self.assertEqual(before, self.snapshot())
        pointer.unlink()
        pointer.symlink_to(main / POINTER_FILE)
        self.assertIsNone(find_project_root(worktree))
        self.assertEqual("unreadable", doctor_worktree_report(worktree, None)["status"])

    def test_unsafe_pointer_blocks_initialized_ancestor_and_learn(self):
        main, worktree = self.fixture()
        initialize_project(self.base, self.user)
        record = json.loads((main / POINTER_FILE).read_text())
        record["bound_path"] = str(worktree)
        record["data_root"] = "../escape"
        (worktree / POINTER_FILE).write_text(json.dumps(record))
        before = self.snapshot()
        self.assertIsNone(find_project_root(worktree))
        self.assertEqual("unreadable", doctor_worktree_report(worktree, None)["status"])
        for action in ("read", "prepare", "apply"):
            with self.assertRaises(DomainError) as caught:
                learn_bridge.run(dict(self.request(worktree), action=action, selection={}))
            self.assertEqual("corrupt_pointer", caught.exception.code)
        self.assertEqual(before, self.snapshot())
        # Outside linked worktrees the original corrupt-pointer error remains.
        plain = self.base / "plain"
        plain.mkdir()
        (plain / POINTER_FILE).write_text("{broken")
        with self.assertRaises(DomainError) as caught:
            find_project_root(plain)
        self.assertEqual("corrupt_pointer", caught.exception.code)

    def test_unreadable_main_pointer_is_reported_without_worktree_writes(self):
        main, worktree = self.fixture()
        (main / POINTER_FILE).write_text("{broken")
        before = self.snapshot()
        with self.assertRaises(DomainError) as caught:
            find_project_root(worktree)
        self.assertEqual("corrupt_pointer", caught.exception.code)
        report = doctor_worktree_report(worktree, None)
        self.assertEqual("unreadable", report["status"])
        self.assertEqual(str(main), report["main_root"])
        self.assertEqual(before, self.snapshot())

    def test_explicit_project_override_still_wins(self):
        main, worktree = self.fixture()
        other = self.base / "override"
        other.mkdir()
        initialize_project(other, self.user)
        TaskService(self.store(other)).create(name="override-task", title="Override", description="",
                                             actor={"role": "user", "id": "test"})
        (worktree / POINTER_FILE).write_text("{broken")
        before = self.snapshot()
        result = self.cli(worktree, "--project", str(other), "task", "list")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("override-task", result.stdout)
        args = build_parser().parse_args(["--project", str(other), "--user-data-root", str(self.user), "doctor"])
        with patch("pathlib.Path.cwd", return_value=worktree):
            roots = roots_from_args(args)
        self.assertEqual(other, roots.project_root)
        self.assertIsNone(roots.invoke_root)
        self.assertNotIn("worktree", _schema_report(roots)["storage"])
        self.assertIsNone(find_project_root(worktree))
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
