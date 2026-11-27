"""Identity guard, knowledge resolution and diagnostics using real git worktrees."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fstar import knowledge, learn_bridge
from fstar.cli import build_parser
from fstar.installer import Roots, _schema_report, roots_from_args
from fstar.models import DomainError
from fstar.project import (InitError, doctor_worktree_report, initialize_project,
                           initialize_workflow_project)
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
        result = {}
        for path in self.base.rglob("*"):
            key = str(path.relative_to(self.base))
            if path.is_symlink():
                result[key] = ("symlink", os.readlink(path))
            elif path.is_dir():
                result[key] = ("directory",)
            elif path.is_file():
                result[key] = ("file", path.read_bytes())
        return result

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

    def tracked_fixture(self):
        main = self.base / "tracked-main"
        worktree = self.base / "tracked-worktree"
        main.mkdir()
        self.git("init", "-q", main)
        initialize_project(main, self.user, storage="project-shared")
        spec = main / ".fstar/specs/core.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("main spec\n")
        archive = main / ".fstar/archive/2026-01/old/note.md"
        archive.parent.mkdir(parents=True)
        archive.write_text("historical archive\n")
        self.git("-C", main, "add", "-f", ".fstar")
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "tracked metadata")
        self.git("-C", main, "worktree", "add", "-q", "-b", "feature-branch", worktree)
        return main, worktree

    def test_tracked_worktree_shares_tasks_and_binds_checkout(self):
        main, worktree = self.tracked_fixture()
        main_store, work_store = self.store(main), self.store(worktree)
        self.assertEqual(main_store.fstar_root, work_store.fstar_root)
        self.assertEqual(main_store.lock_path, work_store.lock_path)
        result = self.cli(worktree, "task", "create", "Worktree task", "--name", "from-wt")
        self.assertEqual(0, result.returncode, result.stderr)
        task = TaskService(main_store).store.read("from-wt")
        self.assertEqual("feature-branch", task["branch"])
        self.assertEqual(str(worktree), task["worktree_path"])
        TaskService(main_store).create(name="from-main", title="Main task", description="",
                                      actor={"role": "user", "id": "test"})
        self.assertEqual({"from-main", "from-wt"},
                         {item["name"] for item in TaskService(work_store).list_tasks()})
        work_store.set_current("session-one", work_store.resolve("from-wt"), task["id"])
        self.assertEqual(task["id"], main_store.current("session-one")["task_id"])
        self.assertEqual("session_pointer", TaskService(main_store).locate(session_id="session-one")["via"])
        pointer_path = work_store.session_path("session-one")
        legacy = json.loads(pointer_path.read_text())
        legacy.pop("identity_root")
        pointer_path.write_text(json.dumps(legacy))
        self.assertEqual("session_pointer", TaskService(main_store).locate(session_id="session-one")["via"])
        self.assertIsNone(main_store.current("session-two"))

    def test_tracked_worktree_uses_checkout_specs(self):
        from fstar.runtime import inject
        main, worktree = self.tracked_fixture()
        spec = worktree / ".fstar/specs/core.md"
        spec.write_text("branch spec\n")
        self.assertEqual("branch spec\n", self.store(worktree).project_file(".fstar/specs/core.md").read_text())
        self.assertEqual("main spec\n", self.store(main).project_file(".fstar/specs/core.md").read_text())
        inputs = inject.spec_body_inputs(worktree, [{"file": ".fstar/specs/core.md"}])
        self.assertEqual(["branch spec\n"], [item.text for item in inputs])
        spec.unlink()
        self.assertFalse(self.store(worktree).project_file(".fstar/specs/core.md").exists())

    def test_tracked_worktree_refuses_independent_task_data(self):
        main, worktree = self.tracked_fixture()
        local = worktree / ".fstar/tasks/independent/task.json"
        local.parent.mkdir(parents=True)
        local.write_text('{"independent": true}\n')
        before = local.read_bytes()
        with self.assertRaises(DomainError) as caught:
            self.store(worktree)
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertEqual(before, local.read_bytes())
        report = doctor_worktree_report(worktree, worktree)
        self.assertEqual("conflict", report["status"])
        self.assertFalse((main / ".fstar/tasks/independent").exists())

    def test_local_and_user_directory_cli_share_worktree_lifecycle(self):
        from fstar.runtime import hooks
        for mode in ("project-local", "user-directory"):
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                result = self.cli(worktree, "task", "create", "From branch", "--name", "branch-task")
                self.assertEqual(0, result.returncode, result.stderr)
                result = self.cli(main, "state", "set-next", "branch-task", "--condition", "ready", "--action", "continue")
                self.assertEqual(0, result.returncode, result.stderr)
                result = self.cli(worktree, "state", "show", "branch-task")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("continue", result.stdout)
                result = self.cli(worktree, "start", "branch-task", "--confirm-user")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("in_progress", self.store(main).read("branch-task")["phase"])
                task = self.store(main).read("branch-task")
                self.assertEqual(str(worktree), task["worktree_path"])
                self.assertEqual("identity-test", task["branch"])
                main_store, work_store = self.store(main), self.store(worktree)
                self.assertEqual(main_store.lock_path, work_store.lock_path)
                import fcntl
                with main_store.transaction():
                    with work_store.lock_path.open("a+") as competing:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch("fstar.runtime.inject.resource_root", return_value=ROOT / "resources"):
                    context = hooks.session_context({}, start=worktree, user_root=self.user,
                                                    runtime_root=self.runtime, as_json=True)
                self.assertEqual("shared_data", context["knowledge_source"]["kind"])
                self.assertEqual(str(self.store(main).fstar_root / "index.md"), context["knowledge_source"]["path"])
                args = build_parser().parse_args(["--user-data-root", str(self.user), "doctor"])
                with patch("pathlib.Path.cwd", return_value=worktree):
                    roots = roots_from_args(args)
                self.assertEqual(worktree, roots.project_root)
                report = _schema_report(roots)["storage"]
                self.assertEqual(str(main_store.fstar_root), report["data_root"])
                self.assertTrue(report["worktree"]["shared"])
                self.assertFalse(any(check["check"] == "bound_path" for check in report["checks"]))

    def test_locate_deduplicates_shared_data_roots(self):
        for mode in ("project-local", "user-directory"):
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                service = TaskService(self.store(worktree))
                created = service.create(name="one", title="One", description="",
                                         actor={"role": "user", "id": "test"})
                result = TaskService(self.store(main)).locate(branch="identity-test", worktree=str(worktree))
                self.assertEqual("found", result["status"])
                self.assertEqual(created["task"]["id"], result["task"]["task_id"])
                service.create(name="two", title="Two", description="",
                               actor={"role": "user", "id": "test"})
                result = TaskService(self.store(main)).locate(branch="identity-test", worktree=str(worktree))
                self.assertEqual("ambiguous", result["status"])
                self.assertEqual(2, len(result["candidates"]))

    def test_tracked_local_skeleton_refuses_writes_but_allows_diagnostics(self):
        main = self.base / "local-skeleton-main"
        worktree = self.base / "local-skeleton-wt"
        main.mkdir()
        self.git("init", "-q", main)
        initialize_project(main, self.user, storage="project-local")
        self.git("-C", main, "add", "-f", ".fstar/.schema-version", ".fstar/config.yaml", ".fstar/index.md")
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "tracked skeleton")
        self.git("-C", main, "worktree", "add", "-q", "-b", "skeleton", worktree)
        self.assertEqual("project-shared", self.store(worktree).storage_mode)
        self.assertEqual("split", doctor_worktree_report(worktree, worktree)["status"])
        self.assertEqual([], TaskService(self.store(worktree)).list_tasks())
        request = self.request(worktree)
        main_service = TaskService(self.store(main))
        main_service.create(name="grant", title="Grant", description="",
                            actor={"role": "user", "id": "test"})
        main_service.enable_extension("grant", authorization={**request["extensions"][0],
                                      "source": {"type": "test"}},
                                      actor={"role": "user", "id": "test"})
        local_task = worktree / ".fstar/tasks/grant/task.json"
        local_task.parent.mkdir(parents=True)
        local_task.write_bytes((main / ".fstar/tasks/grant/task.json").read_bytes())
        prepared = learn_bridge.run(request)
        proposal = prepared["proposal"]
        confirmation = {"disposition": "approved", "source_type": "conversation",
                        "source_ref": "test confirmation", "quote": "Save this",
                        "confirmed_at": "2026-11-25", "proposal_hash": prepared["proposal_hash"],
                        "scope": proposal["scope"], "owners": proposal["owners"]}
        before = self.snapshot()
        result = self.cli(worktree, "task", "create", "Blocked", "--name", "blocked")
        self.assertEqual("worktree_data_conflict", json.loads(result.stderr)["error"]["code"])
        with self.assertRaises(DomainError) as caught:
            learn_bridge.run(dict(request, action="apply", confirmation=confirmation))
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertIn("doctor", caught.exception.message)
        with self.assertRaises(DomainError) as caught:
            learn_bridge.run(dict(request, action="apply", confirmation=confirmation,
                                  task_ref="grant", extensions=[]))
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertEqual("split", json.loads(self.cli(worktree, "doctor").stdout)
                         ["schema_report"]["storage"]["worktree"]["status"])
        self.assertEqual(before, self.snapshot())

    def test_split_identity_blocks_direct_write_entry_points(self):
        from fstar.crossproject import cross_project_locks
        from fstar.installer import migrate, rollback_migration
        from fstar.store import rebind_registered
        main = self.base / "split-main"
        worktree = self.base / "split-wt"
        main.mkdir()
        self.git("init", "-q", main)
        initialize_project(main, self.user, storage="project-local")
        self.git("-C", main, "add", "-f", ".fstar/.schema-version", ".fstar/config.yaml", ".fstar/index.md")
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "skeleton")
        self.git("-C", main, "worktree", "add", "-q", "-b", "split", worktree)
        main_store = self.store(main)
        task = TaskService(main_store).create(name="existing", title="Existing", description="",
                                              actor={"role": "user", "id": "test"})["task"]
        store = self.store(worktree)
        backup = worktree / "install-backups/mig-0123456789"
        backup.mkdir(parents=True)

        def cross_lock():
            with cross_project_locks(main_store, store):
                self.fail("split worktree acquired locks")

        operations = {
            "write": lambda: store.write(store.tasks_root / "new", task),
            "clear_tree_pointers": lambda: store.clear_tree_pointers({task["id"]}),
            "cross_project_locks": cross_lock,
            "migrate": lambda: migrate(target_root=worktree, from_schema=1, to_schema=2,
                                       transform=lambda *_: []),
            "rollback_migration": lambda: rollback_migration(target_root=worktree,
                                                               transaction_id="mig-0123456789"),
            "recover_changes": lambda: knowledge.recover_changes(user_root=self.user, project_root=worktree),
            "rebind_registered": lambda: rebind_registered(user_home=self.user, source_path=main,
                                                            target_path=worktree),
        }
        for name, operation in operations.items():
            with self.subTest(entry=name):
                before = self.snapshot()
                with self.assertRaises(DomainError) as caught:
                    operation()
                self.assertEqual("worktree_data_conflict", caught.exception.code)
                self.assertEqual(before, self.snapshot())

    def test_git_failure_is_unverifiable_and_does_not_write(self):
        main, worktree = self.tracked_fixture()
        before = self.snapshot()
        with patch.dict(os.environ, {"PATH": str(self.base / "no-git")}):
            with self.assertRaises(DomainError) as caught:
                TaskService(self.store(worktree)).create(name="blocked", title="Blocked", description="",
                                                         actor={"role": "user", "id": "test"})
        self.assertEqual("worktree_layout_unverifiable", caught.exception.code)
        self.assertEqual(before, self.snapshot())
        real_run = subprocess.run
        for failure in (FileNotFoundError("git missing"),
                        subprocess.CalledProcessError(2, ["git", "ls-files"])):
            with self.subTest(failure=type(failure).__name__):
                with patch("fstar.store.subprocess.run", side_effect=failure):
                    with self.assertRaises(DomainError) as caught:
                        self.store(worktree)
                self.assertEqual("worktree_layout_unverifiable", caught.exception.code)
                self.assertIn("restore Git", caught.exception.message)
                self.assertTrue(caught.exception.details["reason"])
                self.assertEqual(before, self.snapshot())
        def failed_diff(*args, **kwargs):
            if "diff" in args[0]:
                return subprocess.CompletedProcess(args[0], 128, stderr=b"fatal error")
            return real_run(*args, **kwargs)
        with patch("fstar.store.subprocess.run", side_effect=failed_diff):
            with self.assertRaises(DomainError) as caught:
                self.store(worktree)
        self.assertEqual("worktree_layout_unverifiable", caught.exception.code)
        self.assertEqual(before, self.snapshot())

    def test_rebind_checks_conflicting_target_before_writes(self):
        source = self.base / "source"
        source.mkdir()
        initialize_project(source, self.user, storage="user-directory")
        source_store = self.store(source)
        main = self.base / "target-main"
        worktree = self.base / "target-worktree"
        main.mkdir()
        self.git("init", "-q", main)
        initialize_project(main, self.user, storage="project-local")
        self.git("-C", main, "add", "-f", ".fstar/.schema-version", ".fstar/config.yaml", ".fstar/index.md")
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "skeleton")
        self.git("-C", main, "worktree", "add", "-q", "-b", "target", worktree)
        before = self.snapshot()
        with self.assertRaises(DomainError) as caught:
            source_store.rebind(worktree, confirmation={})
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertFalse((worktree / POINTER_FILE).exists())
        self.assertEqual(before, self.snapshot())

    def test_rebind_target_git_unavailable_and_clean_target(self):
        source = self.base / "source"
        source.mkdir()
        initialize_project(source, self.user, storage="user-directory")
        source_store = self.store(source)
        main, worktree = self.tracked_fixture()
        before = self.snapshot()
        with patch.dict(os.environ, {"PATH": str(self.base / "no-git")}):
            with self.assertRaises(DomainError) as caught:
                source_store.rebind(worktree, confirmation={})
        self.assertEqual("worktree_layout_unverifiable", caught.exception.code)
        self.assertFalse((worktree / POINTER_FILE).exists())
        self.assertEqual(before, self.snapshot())
        from fstar.store import rebind_registered
        for mode in ("project-local", "project-shared", "user-directory"):
            _, clean_worktree = self.fixture(mode)
            for operation in (lambda: source_store.rebind(clean_worktree, confirmation={}),
                              lambda: rebind_registered(user_home=self.user, source_path=source,
                                                        target_path=clean_worktree)):
                with self.subTest(mode=mode):
                    before = self.snapshot()
                    with self.assertRaises(DomainError) as caught:
                        operation()
                    self.assertEqual("worktree_data_conflict", caught.exception.code)
                    self.assertEqual(before, self.snapshot())

    def test_rebind_same_identity_worktree_remains_writable(self):
        main, worktree = self.fixture("user-directory")
        source_store = self.store(main)
        result = source_store.rebind(worktree, confirmation={})
        self.assertTrue(result["rebound"])
        self.assertEqual(source_store.fstar_root, self.store(worktree).fstar_root)
        TaskService(self.store(worktree)).create(name="rebound-task", title="Rebound", description="",
                                                 actor={"role": "user", "id": "test"})

    def test_rebind_refuses_existing_foreign_or_nonfile_pointer(self):
        from fstar.store import rebind_registered
        for kind in ("foreign", "directory"):
            with self.subTest(kind=kind):
                source = self.base / (kind + "-source")
                source.mkdir()
                initialize_project(source, self.user, storage="user-directory")
                store = self.store(source)
                main, target = self.fixture("project-local" if kind == "foreign" else "project-shared")
                if kind == "foreign":
                    initialize_project(target, self.user, storage="user-directory", force_separate=True)
                else:
                    (target / POINTER_FILE).mkdir()
                for operation in (lambda: store.rebind(target, confirmation={}),
                                  lambda: rebind_registered(user_home=self.user, source_path=source,
                                                            target_path=target)):
                    before = self.snapshot()
                    with self.assertRaises(DomainError):
                        operation()
                    self.assertEqual(before, self.snapshot())

    def test_rebind_registered_same_identity_worktree_remains_writable(self):
        from fstar.store import rebind_registered
        main, worktree = self.fixture("user-directory")
        source = self.store(main)
        result = rebind_registered(user_home=self.user, source_path=main, target_path=worktree)
        self.assertTrue(result["rebound"])
        self.assertEqual(source.fstar_root, self.store(worktree).fstar_root)
        TaskService(self.store(worktree)).create(name="rebound-task", title="Rebound", description="",
                                                 actor={"role": "user", "id": "test"})

    def test_rebind_rolls_back_failed_registry_write_for_both_entries(self):
        from fstar.store import atomic_write_json, rebind_registered
        main, worktree = self.fixture("user-directory")
        source = self.store(main)
        with source.transaction():
            pass
        registry = self.user / "projects.json"
        operations = (lambda: source.rebind(worktree, confirmation={}),
                      lambda: rebind_registered(user_home=self.user, source_path=main, target_path=worktree))
        for operation in operations:
            for failing_path in (worktree / POINTER_FILE, registry):
                for after_write in (False, True):
                    with self.subTest(path=failing_path, after_write=after_write):
                        def failing_write(path, payload):
                            if path == failing_path:
                                if after_write:
                                    atomic_write_json(path, payload)
                                raise OSError("injected write failure")
                            atomic_write_json(path, payload)
                        before = self.snapshot()
                        with patch("fstar.store.atomic_write_json", side_effect=failing_write):
                            with self.assertRaisesRegex(OSError, "injected write failure"):
                                operation()
                        self.assertEqual(before, self.snapshot())

    def test_rebind_rolls_back_source_pointer_when_target_write_fails(self):
        from fstar.store import atomic_write_json
        source_root = self.base / "ordinary-source"
        source_root.mkdir()
        initialize_project(source_root, self.user, storage="user-directory")
        source = self.store(source_root)
        target = self.base / "ordinary-target"
        target.mkdir()
        with source.transaction():
            pass
        def failing_write(path, payload):
            if path == target / POINTER_FILE:
                raise OSError("injected target failure")
            atomic_write_json(path, payload)
        before = self.snapshot()
        with patch("fstar.store.atomic_write_json", side_effect=failing_write):
            with self.assertRaisesRegex(OSError, "injected target failure"):
                source.rebind(target, confirmation={})
        self.assertEqual(before, self.snapshot())

    def test_rebind_reports_failed_recovery_and_preserves_external_edit(self):
        from fstar.store import atomic_write_json, rebind_registered
        main, worktree = self.fixture("user-directory")
        source = self.store(main)
        with source.transaction():
            pass
        target_pointer = worktree / POINTER_FILE
        registry = self.user / "projects.json"
        def interfering_write(path, payload):
            if path == registry:
                target_pointer.write_text("external edit\n")
                raise OSError("injected failure")
            atomic_write_json(path, payload)
        for operation in (lambda: source.rebind(worktree, confirmation={}),
                          lambda: rebind_registered(user_home=self.user, source_path=main, target_path=worktree)):
            with patch("fstar.store.atomic_write_json", side_effect=interfering_write):
                with self.assertRaises(DomainError) as caught:
                    operation()
            self.assertEqual("rebind_recovery_failed", caught.exception.code)
            self.assertIn(str(target_pointer), caught.exception.details["paths"])
            self.assertEqual("external edit\n", target_pointer.read_text())
            target_pointer.unlink()

    def test_branch_knowledge_apply_writes_current_checkout(self):
        main, worktree = self.tracked_fixture()
        request = self.request(worktree)
        prepared = learn_bridge.run(request)
        proposal = prepared["proposal"]
        confirmation = {"disposition": "approved", "source_type": "conversation",
                        "source_ref": "test confirmation", "quote": "Save this",
                        "confirmed_at": "2026-11-25", "proposal_hash": prepared["proposal_hash"],
                        "scope": proposal["scope"], "owners": proposal["owners"]}
        learn_bridge.run(dict(request, action="apply", confirmation=confirmation))
        self.assertTrue((worktree / ".fstar/knowledge/context/note.md").is_file())
        self.assertFalse((main / ".fstar/knowledge/context/note.md").exists())

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

    def test_explicit_separate_worktrees_can_write_in_all_modes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                main, worktree = self.fixture(mode)
                initialize_project(worktree, self.user, storage=mode, force_separate=True)
                store = self.store(worktree)
                task = TaskService(store).create(name="separate", title="Separate", description="",
                                                 actor={"role": "user", "id": "test"})["task"]
                store.set_current("session", store.resolve("separate"), task["id"])
                self.assertEqual(task["id"], store.current("session")["task_id"])
                request = self.request(worktree)
                prepared = learn_bridge.run(request)
                proposal = prepared["proposal"]
                confirmation = {"disposition": "approved", "source_type": "conversation",
                                "source_ref": "test confirmation", "quote": "Save this",
                                "confirmed_at": "2026-11-25", "proposal_hash": prepared["proposal_hash"],
                                "scope": proposal["scope"], "owners": proposal["owners"]}
                learn_bridge.run(dict(request, action="apply", confirmation=confirmation))
                self.assertTrue((store.fstar_root / "knowledge/context/note.md").is_file())
                self.assertFalse((self.store(main).fstar_root / "knowledge/context/note.md").exists())
                report = json.loads(self.cli(worktree, "doctor").stdout)["schema_report"]["storage"]["worktree"]
                self.assertTrue(report["explicit_separate"])

    def test_stale_shared_store_refuses_writes_after_separate_init(self):
        main, worktree = self.fixture("project-shared")
        task = TaskService(self.store(main)).create(name="existing", title="Existing", description="",
                                                    actor={"role": "user", "id": "test"})["task"]
        stale = self.store(worktree)
        self.assertEqual(self.store(main).fstar_root, stale.fstar_root)
        initialize_project(worktree, self.user, storage="project-shared", force_separate=True)
        before = self.snapshot()
        operations = (
            lambda: TaskService(stale).create(name="wrong-root", title="Wrong", description="",
                                              actor={"role": "user", "id": "test"}),
            lambda: stale.write(stale.tasks_root / "existing", task),
            lambda: stale.set_current("session", stale.tasks_root / "existing", task["id"]),
            lambda: stale.clear_tree_pointers({task["id"]}),
        )
        for operation in operations:
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertEqual("worktree_data_conflict", caught.exception.code)
            self.assertEqual(before, self.snapshot())
        self.assertFalse((main / ".fstar/tasks/wrong-root").exists())
        self.assertFalse((worktree / ".fstar/tasks/wrong-root").exists())

    def test_store_rechecks_identity_after_acquiring_lock(self):
        import fcntl
        main, worktree = self.fixture("project-shared")
        stale = self.store(worktree)
        actual_flock = fcntl.flock
        changed = []
        def transition(fd, operation):
            result = actual_flock(fd, operation)
            if operation & fcntl.LOCK_EX and not changed:
                changed.append(True)
                initialize_project(worktree, self.user, storage="project-shared", force_separate=True)
            return result
        with patch("fstar.store.fcntl.flock", side_effect=transition):
            with self.assertRaises(DomainError) as caught:
                with stale.transaction():
                    self.fail("stale store acquired an unchecked transaction")
        self.assertTrue(changed)
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertFalse((main / ".fstar/tasks").exists())
        self.assertFalse((worktree / ".fstar/tasks").exists())

    def test_copied_separation_marker_does_not_authorize_other_worktree(self):
        from fstar.store import _separate_marker_path
        main, worktree = self.fixture("project-shared")
        initialize_project(worktree, self.user, storage="project-shared", force_separate=True)
        other = self.base / "other-worktree"
        self.git("-C", main, "worktree", "add", "-q", "-b", "other-branch", other)
        shutil.copytree(worktree / ".fstar", other / ".fstar")
        shutil.copyfile(_separate_marker_path(worktree), _separate_marker_path(other))
        before = self.snapshot()
        with self.assertRaises(DomainError) as caught:
            TaskService(self.store(other)).create(name="blocked", title="Blocked", description="",
                                                actor={"role": "user", "id": "test"})
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertEqual(before, self.snapshot())

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

    def test_matching_pointer_does_not_hide_local_task_data(self):
        main, worktree = self.fixture()
        pointer = json.loads((main / POINTER_FILE).read_text())
        pointer["bound_path"] = str(worktree)
        (worktree / POINTER_FILE).write_text(json.dumps(pointer))
        self.assertEqual(self.store(main).fstar_root, self.store(worktree).fstar_root)
        self.assertTrue(doctor_worktree_report(worktree, worktree)["shared"])
        local_root = worktree / ".fstar"
        for area, kind in (("tasks", "file"), ("archive", "file"), ("tasks", "symlink")):
            with self.subTest(area=area, kind=kind):
                local_root.mkdir()
                path = local_root / area
                if kind == "symlink":
                    path.symlink_to(self.base / "missing")
                else:
                    path.mkdir()
                    (path / "independent.txt").write_text("preserve me\n")
                before = self.snapshot()
                with self.assertRaises(DomainError) as caught:
                    self.store(worktree)
                self.assertEqual("worktree_data_conflict", caught.exception.code)
                result = self.cli(worktree, "task", "create", "Blocked", "--name", "blocked")
                self.assertEqual("worktree_data_conflict", json.loads(result.stderr)["error"]["code"])
                report = doctor_worktree_report(worktree, worktree)
                self.assertEqual("conflict", report["status"])
                self.assertFalse(report["shared"])
                self.assertEqual(before, self.snapshot())
                shutil.rmtree(local_root)
        local_root.symlink_to(self.base / "missing-root")
        before = self.snapshot()
        with self.assertRaises(DomainError) as caught:
            self.store(worktree)
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertEqual("conflict", doctor_worktree_report(worktree, worktree)["status"])
        self.assertEqual(before, self.snapshot())

    def test_matching_pointer_with_different_mode_refuses_writes(self):
        main, worktree = self.fixture()
        pointer = json.loads((main / POINTER_FILE).read_text())
        pointer["bound_path"] = str(worktree)
        pointer["mode"] = "project-shared"
        (worktree / POINTER_FILE).write_text(json.dumps(pointer))
        store = self.store(worktree)
        before = self.snapshot()
        with self.assertRaises(DomainError) as caught:
            TaskService(store).create(name="blocked", title="Blocked", description="",
                                      actor={"role": "user", "id": "test"})
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        self.assertEqual(before, self.snapshot())

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


class IdentityTransitionLockTests(unittest.TestCase):
    """A/B: the separate-init conversion takes identity locks around writes."""

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

    def fixture(self, mode="project-shared"):
        main = self.base / (mode + "-main")
        worktree = self.base / (mode + "-wt")
        main.mkdir()
        self.git("init", "-q", main)
        self.git("-C", main, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "baseline")
        initialize_project(main, self.user, storage=mode)
        self.git("-C", main, "worktree", "add", "-q", "-b", "identity-test", worktree)
        return main, worktree

    def store(self, root, **kwargs):
        return TaskStore(root, user_home=self.user, runtime_root=self.runtime, **kwargs)

    def snapshot(self, worktree, main):
        roots = {}
        for root in (worktree, main):
            for path in sorted(root.rglob("*")):
                key = str(path.relative_to(root))
                if path.is_symlink():
                    roots[(str(root), key)] = ("symlink", os.readlink(path))
                elif path.is_dir():
                    roots[(str(root), key)] = ("directory",)
                else:
                    roots[(str(root), key)] = ("file", path.read_bytes())
        return roots

    def test_transition_waits_for_in_flight_shared_transaction_then_succeeds(self):
        import threading
        main, worktree = self.fixture("project-shared")
        shared = self.store(worktree)
        released = threading.Event()
        def hold_transaction():
            with shared.transaction():
                released.set()
                time.sleep(1.0)
        holder = threading.Thread(target=hold_transaction)
        holder.start()
        released.wait(timeout=5)
        # The conversion blocks on the OLD identity lock (the main-derived
        # runtime slot a shared TaskStore holds) until the transaction ends,
        # then succeeds; it never writes around the in-flight transaction.
        started = time.monotonic()
        result = initialize_project(worktree, self.user, storage="project-shared",
                                    force_separate=True, runtime_root=self.runtime)
        elapsed = time.monotonic() - started
        holder.join(timeout=5)
        self.assertTrue(result.force_separate)
        # It had to wait for the ~1s transaction, proving lock handoff.
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertNotEqual(self.store(main).project_id, self.store(worktree).project_id)

    def test_transition_lock_timeout_leaves_zero_writes(self):
        import fcntl
        import threading
        main, worktree = self.fixture("project-shared")
        shared = self.store(worktree)
        shared.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = shared.lock_path.open("a+")
        self.addCleanup(stream.close)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        before = self.snapshot(worktree, main)
        from fstar.models import DomainError
        from fstar import project as project_module
        with patch.object(project_module, "_INIT_LOCK_TIMEOUT", 0.2):
            with self.assertRaises(DomainError) as caught:
                initialize_project(worktree, self.user, storage="project-shared",
                                   force_separate=True, runtime_root=self.runtime)
        self.assertEqual("lock_timeout", caught.exception.code)
        self.assertEqual(before, self.snapshot(worktree, main))
        # Release: the same operation is recoverable.
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        result = initialize_project(worktree, self.user, storage="project-shared",
                                    force_separate=True, runtime_root=self.runtime)
        self.assertTrue(result.force_separate)

    def test_old_store_writes_refused_after_partial_transition_failure(self):
        main, worktree = self.fixture("project-shared")
        shared = self.store(worktree)
        stale = self.store(worktree)
        task = TaskService(self.store(main)).create(
            name="existing", title="Existing", description="",
            actor={"role": "user", "id": "test"})["task"]
        from fstar.store import record_explicit_separate_worktree
        def failing_marker(root):
            if root == worktree:
                raise OSError("injected marker failure")
            return record_explicit_separate_worktree(root)
        from fstar.models import DomainError
        with patch("fstar.store.record_explicit_separate_worktree", side_effect=failing_marker):
            with self.assertRaises(OSError):
                initialize_project(worktree, self.user, storage="project-shared",
                                   force_separate=True, runtime_root=self.runtime)
        # Data may exist from the partial attempt, but no marker authorizes
        # the separate identity, so every old-store write entry point is
        # refused and the main root is untouched.
        before = self.snapshot(worktree, main)
        operations = (
            lambda: TaskService(stale).create(name="wrong-root", title="Wrong", description="",
                                              actor={"role": "user", "id": "test"}),
            lambda: stale.write(stale.tasks_root / "existing", task),
            lambda: stale.set_current("session", stale.tasks_root / "existing", task["id"]),
        )
        for operation in operations:
            with self.assertRaises(DomainError) as caught:
                operation()
            self.assertIn(caught.exception.code, ("worktree_data_conflict", "lock_timeout"))
            self.assertEqual(before, self.snapshot(worktree, main))
        self.assertFalse((main / ".fstar/tasks/wrong-root").exists())

    def test_runtime_root_is_shared_between_init_and_store_locks(self):
        import fcntl
        main, worktree = self.fixture("project-shared")
        custom_runtime = self.base / "custom-runtime"
        shared = TaskStore(worktree, user_home=self.user, runtime_root=custom_runtime)
        shared.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = shared.lock_path.open("a+")
        self.addCleanup(stream.close)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        from fstar.models import DomainError
        from fstar import project as project_module
        with patch.object(project_module, "_INIT_LOCK_TIMEOUT", 0.2):
            with self.assertRaises(DomainError) as caught:
                initialize_workflow_project(worktree, self.user, task_ref="session-only",
                                            storage="project-shared", force_separate=True,
                                            runtime_root=custom_runtime)
        self.assertEqual("lock_timeout", caught.exception.code)
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        result = initialize_workflow_project(worktree, self.user, task_ref="session-only",
                                             storage="project-shared", force_separate=True,
                                             runtime_root=custom_runtime)
        self.assertTrue(result.force_separate)

    def test_user_directory_conversion_takes_registry_lock_after_project_lock(self):
        import fcntl
        main, worktree = self.fixture("user-directory")
        from fstar.store import _registry_path
        registry = _registry_path(self.user)
        registry.parent.mkdir(parents=True, exist_ok=True)
        # The OLD identity lock: the user-directory runtime slot a shared
        # TaskStore on the worktree holds (id-keyed, default runtime root).
        old_lock = TaskStore(worktree, user_home=self.user,
                             runtime_root=self.runtime).lock_path
        old_lock.parent.mkdir(parents=True, exist_ok=True)
        registry_fd = os.open(str(self.user), os.O_RDONLY)
        self.addCleanup(os.close, registry_fd)
        fcntl.flock(registry_fd, fcntl.LOCK_EX)
        results = []

        def run_init():
            results.append(initialize_project(worktree, self.user,
                                              storage="user-directory",
                                              force_separate=True,
                                              runtime_root=self.runtime))

        import threading
        import time as time_module
        thread = threading.Thread(target=run_init)
        thread.start()
        # Give the conversion a moment to reach (and hold) the project lock.
        time_module.sleep(0.3)
        # While the registry lock is held, the conversion must ALREADY hold
        # the project lock (project -> registry order, never the reverse: a
        # reversed order would deadlock against this holder).
        probe = old_lock.open("a+")
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            probe.close()
        fcntl.flock(registry_fd, fcntl.LOCK_UN)
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results and results[0].force_separate)
        self.assertNotEqual(self.store(main).project_id, self.store(worktree).project_id)
        record = json.loads(registry.read_text())
        self.assertIn(self.store(worktree).project_id, record["projects"])

if __name__ == "__main__":
    unittest.main()
