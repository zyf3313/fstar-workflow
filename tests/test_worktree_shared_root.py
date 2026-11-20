"""Linked git worktree shares the main worktree's fstar data root (P-001..P-003).

Every test builds REAL temporary git repositories with ``git init`` and
``git worktree add`` under an isolated TMPDIR; this repository's working
tree, the real ``~/.claude``/``~/.codex``/``~/.fstar``, and Magpie state
are never touched.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from fstar.models import DomainError
from fstar.project import (doctor_worktree_report, initialize_project,
                           uninitialized_init_hint)
from fstar.store import (POINTER_FILE, TaskStore, find_project_root,
                         worktree_shared_main_root)


def _git(*argv, cwd=None):
    subprocess.run(["git", *argv], check=True, cwd=str(cwd) if cwd else None,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull})


class WorktreeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fstar-worktree-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_root = (self.base / "user" / ".fstar").resolve()
        self.user_root.mkdir(parents=True)
        self.runtime = self.base / "runtime"

    def _main_repo(self, name="main", *, initialized=True, storage="project-local"):
        main = (self.base / name).resolve()
        main.mkdir()
        _git("init", "-q", str(main))
        if initialized:
            initialize_project(main, self.user_root, storage=storage)
        return main

    def _worktree(self, main: Path, name="wt") -> Path:
        worktree = (self.base / name).resolve()
        _git("worktree", "add", "-q", str(worktree), "-b", name, cwd=main)
        return worktree

    def _store(self, root: Path) -> TaskStore:
        return TaskStore(root, user_home=self.user_root, runtime_root=self.runtime)


class FindProjectRootWorktreeTests(WorktreeCase):
    def test_linked_worktree_resolves_to_main_root(self):
        main = self._main_repo()
        worktree = self._worktree(main)
        self.assertEqual(main, find_project_root(worktree))
        nested = worktree / "some" / "nested"
        nested.mkdir(parents=True)
        self.assertEqual(main, find_project_root(nested))

    def test_shared_store_identity_matches_main_tree(self):
        main = self._main_repo()
        worktree = self._worktree(main)
        # CLI flow: project root is discovered by find_project_root first.
        main_store = self._store(find_project_root(main))
        worktree_store = self._store(find_project_root(worktree))
        self.assertEqual(main_store.fstar_root, worktree_store.fstar_root)
        self.assertEqual(main_store.project_id, worktree_store.project_id)
        self.assertEqual(main_store.storage_mode, worktree_store.storage_mode)

    def test_tasks_created_in_worktree_are_visible_from_main_tree(self):
        from fstar.tasks import TaskService
        main = self._main_repo()
        worktree = self._worktree(main)
        service = TaskService(self._store(find_project_root(worktree)))
        service.create(name="task-from-worktree", title="from worktree",
                       description="", actor={"role": "user", "id": "tester"})
        main_service = TaskService(self._store(find_project_root(main)))
        listing = main_service.list_tasks()
        self.assertIn("task-from-worktree", [task["name"] for task in listing])

    def test_uninitialized_main_tree_keeps_uninitialized_behavior(self):
        main = self._main_repo(initialized=False)
        worktree = self._worktree(main)
        self.assertIsNone(find_project_root(worktree))
        # No implicit write anywhere: neither tree gained fstar data.
        self.assertFalse((worktree / ".fstar").exists())
        self.assertFalse((worktree / POINTER_FILE).exists())

    def test_uninitialized_worktree_task_commands_raise_with_guidance(self):
        main = self._main_repo(initialized=False)
        worktree = self._worktree(main)
        store = self._store(worktree)
        with self.assertRaises(DomainError) as caught:
            store.require_project()
        self.assertEqual("project_not_initialized", caught.exception.code)

    def test_non_worktree_project_behavior_unchanged(self):
        main = self._main_repo()
        self.assertEqual(main, find_project_root(main))
        # A plain directory without git is still not a project.
        plain = (self.base / "plain").resolve()
        plain.mkdir()
        (plain / ".fstar").mkdir()
        (plain / ".fstar" / ".schema-version").write_text("1\n", encoding="utf-8")
        self.assertEqual(plain, find_project_root(plain))

    def test_git_directory_repo_is_not_treated_as_linked_worktree(self):
        main = self._main_repo(initialized=False)
        # A normal .git DIRECTORY must not resolve through commondir logic;
        # with no .fstar marker the project stays uninitialized.
        self.assertIsNone(find_project_root(main))
        self.assertIsNone(worktree_shared_main_root(main))

    def test_corrupt_commondir_falls_back_to_current_resolution(self):
        main = self._main_repo(initialized=False)
        worktree = self._worktree(main)
        git_file = worktree / ".git"
        gitdir = Path(git_file.read_text(encoding="utf-8").strip()[len("gitdir: "):])
        (gitdir / "commondir").write_text("", encoding="utf-8")
        self.assertIsNone(find_project_root(worktree))
        # Malformed .git file content: resolution unchanged (None), no raise.
        git_file.write_text("garbage\n", encoding="utf-8")
        self.assertIsNone(find_project_root(worktree))

    def test_pointer_bound_path_semantics_unchanged_in_worktree(self):
        """A pointer found in a linked worktree still binds to its own path."""
        import json
        import uuid
        main = self._main_repo(initialized=False)
        worktree = self._worktree(main)
        data_root = self.base / "data" / "proj"
        data_root.mkdir(parents=True)
        (data_root / ".schema-version").write_text("1\n", encoding="utf-8")
        record = {"schema": "fstar.pointer.v1", "project_id": str(uuid.uuid4()),
                  "data_root": str(data_root), "bound_path": str(worktree),
                  "mode": "user-directory"}
        (worktree / POINTER_FILE).write_text(json.dumps(record), encoding="utf-8")
        # The pointer at the worktree path resolves the worktree itself;
        # bound_path semantics are untouched by worktree sharing.
        self.assertEqual(worktree, find_project_root(worktree))

    def test_worktree_shared_main_root_helper(self):
        main = self._main_repo()
        worktree = self._worktree(main)
        self.assertEqual(main, worktree_shared_main_root(worktree))
        self.assertIsNone(worktree_shared_main_root(main))


class DoctorWorktreeReportTests(WorktreeCase):
    def _schema_storage(self, cwd: Path):
        from fstar.installer import Roots, _schema_report
        roots = Roots(user_root=self.user_root, runtime_root=self.runtime,
                      project_root=find_project_root(cwd), host_roots={},
                      bundle_root=None, invoke_root=cwd)
        return _schema_report(roots).get("storage")

    def test_doctor_reports_sharing_source_in_worktree(self):
        main = self._main_repo()
        worktree = self._worktree(main)
        storage = self._schema_storage(worktree)
        self.assertEqual(main, Path(storage["worktree"]["main_root"]))
        self.assertTrue(storage["worktree"]["shared"])
        self.assertIn("当前 worktree 共享自", storage["worktree"]["message"])
        # The data root itself is the MAIN tree's .fstar.
        self.assertEqual(str(main / ".fstar"), storage["data_root"])

    def test_doctor_main_tree_output_unchanged(self):
        main = self._main_repo()
        storage = self._schema_storage(main)
        self.assertNotIn("worktree", storage)

    def test_doctor_uninitialized_worktree_guides_init(self):
        main = self._main_repo(initialized=False)
        worktree = self._worktree(main)
        storage = self._schema_storage(worktree)
        self.assertFalse(storage["worktree"]["shared"])
        self.assertIn("fstar init", storage["worktree"]["message"])

    def test_doctor_non_worktree_directory_has_no_worktree_entry(self):
        plain = (self.base / "plain").resolve()
        plain.mkdir()
        self.assertIsNone(self._schema_storage(plain))

    def test_doctor_report_helper_directly(self):
        main = self._main_repo()
        worktree = self._worktree(main)
        self.assertIsNone(doctor_worktree_report(None, main))
        self.assertIsNone(doctor_worktree_report(main, main))
        shared = doctor_worktree_report(worktree, main)
        self.assertTrue(shared["shared"])
        hint = uninitialized_init_hint(main)
        self.assertIn("fstar init", hint)


class ModeRegressionTests(WorktreeCase):
    def test_user_directory_mode_unaffected_by_worktrees(self):
        import json
        main = self._main_repo(storage="user-directory")
        worktree = self._worktree(main)
        # user-directory mode: the pointer lives in the MAIN tree and binds
        # to it; the linked worktree has no pointer of its own, so its own
        # find_project_root walk does not resolve through the pointer.
        self.assertTrue((main / POINTER_FILE).is_file())
        main_store = self._store(main)
        self.assertEqual("user-directory", main_store.storage_mode)
        self.assertEqual(main, find_project_root(main))
        # The worktree resolves through the shared main .fstar data root
        # only when the main tree carries an in-repo marker; user-directory
        # mode keeps the pointer as the single source, so the worktree stays
        # uninitialized rather than gaining a phantom binding.
        self.assertIsNone(find_project_root(worktree))

    def test_tracked_project_shared_mode_worktree_shares(self):
        """This repo's own pattern: tracked .fstar (project-shared)."""
        main = self._main_repo(storage="project-shared")
        worktree = self._worktree(main)
        self.assertEqual(main, find_project_root(worktree))
        self.assertEqual("project-shared", self._store(worktree).storage_mode)

    def test_pointer_data_root_unchanged_outside_worktrees(self):
        from fstar.store import _read_pointer, _safe_pointer_data_root
        main = self._main_repo(storage="user-directory")
        record = _read_pointer(main / POINTER_FILE)
        data = _safe_pointer_data_root(main, record)
        self.assertTrue(data.is_dir())


if __name__ == "__main__":
    unittest.main()
