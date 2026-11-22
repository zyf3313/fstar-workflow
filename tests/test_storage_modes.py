"""Regressions for the three project data-storage modes (P-001 / D-002).

Every test uses temporary user roots and temporary repositories; the real
``~/.fstar`` is never read or written.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from fstar.models import DomainError
from fstar.project import GIT_EXCLUDE_LINE, initialize_project
from fstar.store import POINTER_FILE, TaskStore, find_project_root, rebind_registered


def _git(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class StorageModeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_root = (self.base / "user" / ".fstar").resolve()
        self.user_root.mkdir(parents=True)

    def _repo(self, name="project", *, git=True):
        repo = (self.base / name).resolve()
        repo.mkdir()
        if git:
            _git(repo)
        return repo


class ProjectSharedModeTests(StorageModeCase):
    def test_data_root_stays_in_the_repository(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="project-shared")
        self.assertTrue((repo / ".fstar" / ".schema-version").is_file())
        self.assertFalse((repo / POINTER_FILE).exists())
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertEqual("project-shared", store.storage_mode)
        self.assertEqual(str((repo / ".fstar").resolve()), str(store.fstar_root))
        self.assertEqual(repo, find_project_root(repo))

    def test_default_mode_is_project_shared(self):
        repo = self._repo()
        initialize_project(repo, self.user_root)
        self.assertEqual("project-shared",
                         TaskStore(repo, user_home=self.user_root,
                                   runtime_root=self.base / "runtime").storage_mode)

    def test_legacy_project_without_pointer_still_resolves(self):
        """Legacy layout: no pointer file, .fstar inside the repo."""
        repo = self._repo()
        (repo / ".fstar").mkdir()
        (repo / ".fstar" / ".schema-version").write_text("1\n")
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertEqual("project-shared", store.storage_mode)
        self.assertFalse(store.moved_needs_rebind)
        store.require_project()
        self.assertEqual(repo, find_project_root(repo))


class ProjectLocalModeTests(StorageModeCase):
    def test_local_exclude_is_used_and_shared_gitignore_untouched(self):
        repo = self._repo()
        shared_ignore = repo / ".gitignore"
        shared_ignore.write_text("build/\n", encoding="utf-8")
        result = initialize_project(repo, self.user_root, storage="project-local")
        exclude = repo / ".git" / "info" / "exclude"
        self.assertTrue(exclude.is_file())
        self.assertIn(GIT_EXCLUDE_LINE.strip(), exclude.read_text(encoding="utf-8"))
        # The shared, tracked ignore file must not gain a .fstar rule.
        self.assertEqual("build/\n", shared_ignore.read_text(encoding="utf-8"))
        self.assertTrue((repo / ".fstar" / ".schema-version").is_file())
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertEqual("project-local", store.storage_mode)
        self.assertEqual(repo, find_project_root(repo))

    def test_non_git_project_reports_that_ignore_did_not_succeed(self):
        repo = self._repo("plain", git=False)
        result = initialize_project(repo, self.user_root, storage="project-local")
        codes = [warning.code for warning in result.warnings]
        self.assertIn("LOCAL_EXCLUDE_NOT_GIT", codes)
        self.assertFalse((repo / ".git").exists())
        # The data root still exists; only the ignore could not be applied.
        self.assertTrue((repo / ".fstar" / ".schema-version").is_file())

    def test_shared_gitignore_already_ignoring_fstar_is_reported(self):
        repo = self._repo()
        (repo / ".gitignore").write_text("/.fstar/\n", encoding="utf-8")
        result = initialize_project(repo, self.user_root, storage="project-local")
        codes = [warning.code for warning in result.warnings]
        self.assertIn("LOCAL_GITIGNORE_READONLY", codes)


class UserDirectoryModeTests(StorageModeCase):
    def test_data_root_lives_under_the_user_root(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        self.assertFalse((repo / ".fstar").exists())
        pointer = repo / POINTER_FILE
        self.assertTrue(pointer.is_file())
        record = json.loads(pointer.read_text(encoding="utf-8"))
        self.assertEqual("user-directory", record["mode"])
        self.assertEqual(str(repo), record["bound_path"])
        data_root = Path(record["data_root"])
        if not data_root.is_absolute():
            data_root = (repo / data_root).resolve()
        self.assertTrue(data_root.is_dir())
        self.assertTrue(data_root.is_relative_to(self.user_root))
        self.assertTrue((data_root / ".schema-version").is_file())
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertEqual("user-directory", store.storage_mode)
        self.assertEqual(str(data_root), str(store.fstar_root))
        self.assertEqual(repo, find_project_root(repo))

    def test_same_name_projects_get_distinct_data_roots(self):
        first = self._repo("alpha")
        second = (self.base / "other" / "alpha").resolve()
        second.mkdir(parents=True)
        _git(second)
        initialize_project(first, self.user_root, storage="user-directory")
        initialize_project(second, self.user_root, storage="user-directory")
        store_a = TaskStore(first, user_home=self.user_root, runtime_root=self.base / "runtime")
        store_b = TaskStore(second, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertNotEqual(store_a.fstar_root, store_b.fstar_root)
        self.assertNotEqual(store_a.project_id, store_b.project_id)
        self.assertTrue((store_a.fstar_root / ".schema-version").is_file())
        self.assertTrue((store_b.fstar_root / ".schema-version").is_file())
        # Neither project overwrote the other's data.
        self.assertTrue((store_a.fstar_root / "index.md").is_file())
        self.assertTrue((store_b.fstar_root / "index.md").is_file())

    def test_init_is_idempotent_and_reuses_the_data_root(self):
        repo = self._repo()
        first = initialize_project(repo, self.user_root, storage="user-directory")
        record = json.loads((repo / POINTER_FILE).read_text(encoding="utf-8"))
        second = initialize_project(repo, self.user_root, storage="user-directory")
        self.assertEqual((), second.created)
        self.assertIn(repo / POINTER_FILE, second.preserved)
        self.assertEqual(record,
                         json.loads((repo / POINTER_FILE).read_text(encoding="utf-8")))
        self.assertEqual(1, len(list((self.user_root / "projects").iterdir())))
        self.assertTrue(first.created)

    def test_bare_reinit_keeps_the_user_directory_mode(self):
        """A plain `fstar init` on an initialized project must not switch modes."""
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        result = initialize_project(repo, self.user_root)
        self.assertFalse((repo / ".fstar").exists())
        self.assertEqual(1, len(list((self.user_root / "projects").iterdir())))
        self.assertEqual((), result.created)

    def test_moved_project_requires_explicit_rebind(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        moved = (self.base / "moved").resolve()
        moved.mkdir()
        _git(moved)
        # The pointer travels with the repository, but its binding does not
        # match the new location, so the project is not auto-resolved.
        source_pointer = json.loads((repo / POINTER_FILE).read_text(encoding="utf-8"))
        (moved / POINTER_FILE).write_text(json.dumps(source_pointer), encoding="utf-8")
        self.assertIsNone(find_project_root(moved))
        store = TaskStore(moved, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertTrue(store.moved_needs_rebind)
        with self.assertRaises(DomainError) as error:
            store.require_project()
        self.assertEqual("project_moved_needs_rebind", error.exception.code)

    def test_rebind_updates_pointer_and_registry(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        moved = (self.base / "moved").resolve()
        moved.mkdir()
        _git(moved)
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        result = store.rebind(moved, confirmation={"source_id": "test", "type": "rebind"})
        self.assertTrue(result["rebound"])
        record = json.loads((moved / POINTER_FILE).read_text(encoding="utf-8"))
        self.assertEqual(str(moved), record["bound_path"])
        self.assertEqual(store.project_id, record["project_id"])
        # The new location now resolves, and the data root did not move.
        self.assertEqual(moved, find_project_root(moved))
        rebound = TaskStore(moved, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertFalse(rebound.moved_needs_rebind)
        self.assertEqual(str(store.fstar_root), str(rebound.fstar_root))
        registry = json.loads((self.user_root / "projects.json").read_text(encoding="utf-8"))
        entry = registry["projects"][store.project_id]
        self.assertEqual(str(moved), entry["path"])
        self.assertIn("rebound_at", entry)

    def test_rebind_is_refused_for_other_storage_modes(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="project-shared")
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        with self.assertRaises(DomainError) as error:
            store.rebind(self.base / "elsewhere", confirmation={"source_id": "t", "type": "rebind"})
        self.assertEqual("rebind_requires_user_directory", error.exception.code)

    def test_rebound_project_keeps_its_session_pointer_and_lock(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        from fstar.tasks import TaskService
        service = TaskService(store)
        agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        service.create(name="root", title="Root", description="d", actor=agent, session_id="s1")
        self.assertEqual(store.read("root")["id"], store.current("s1")["task_id"])
        moved = (self.base / "moved").resolve()
        moved.mkdir()
        store.rebind(moved, confirmation={"source_id": "t", "type": "rebind"})
        rebound = TaskStore(moved, user_home=self.user_root, runtime_root=self.base / "runtime")
        # The runtime slot follows the project identity, not the path.
        self.assertEqual(str(store.project_runtime), str(rebound.project_runtime))
        self.assertEqual(store.read("root")["id"], rebound.current("s1")["task_id"])


class DataRootAccessTests(StorageModeCase):
    def test_project_file_resolves_data_and_repository_paths(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        data = store.project_file(".fstar/specs/core.md")
        self.assertEqual(store.fstar_root / "specs" / "core.md", data)
        repo_file = store.project_file("src/main.py")
        self.assertEqual(repo / "src" / "main.py", repo_file)

    def test_project_file_rejects_escapes(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        with self.assertRaises(DomainError) as error:
            store.project_file("../outside.md")
        self.assertEqual("unsafe_evidence_path", error.exception.code)


class PointerFileTests(StorageModeCase):
    def test_pointer_is_kept_out_of_the_shared_gitignore(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        exclude = repo / ".git" / "info" / "exclude"
        self.assertTrue(exclude.is_file())
        self.assertIn(POINTER_FILE, exclude.read_text(encoding="utf-8"))
        # No shared .gitignore is created for the pointer.
        self.assertFalse((repo / ".gitignore").exists())

    def test_registry_records_the_project_binding(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        registry = json.loads((self.user_root / "projects.json").read_text(encoding="utf-8"))
        self.assertEqual("fstar.projects.v1", registry["schema"])
        entries = registry["projects"]
        self.assertEqual(1, len(entries))
        project_id, entry = next(iter(entries.items()))
        self.assertEqual(str(repo), entry["path"])
        self.assertEqual("user-directory", entry["storage_mode"])
        self.assertTrue(Path(entry["data_root"]).name.startswith(project_id + "-"))


class RegistryRebindTests(StorageModeCase):
    def test_rebind_through_the_registry_when_the_pointer_is_lost(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        moved = (self.base / "moved").resolve()
        moved.mkdir()
        (repo / POINTER_FILE).unlink()
        result = rebind_registered(user_home=self.user_root, source_path=repo,
                                   target_path=moved,
                                   confirmation={"source_id": "t", "type": "rebind"})
        self.assertTrue(result["rebound"])
        self.assertEqual(str(moved), result["project_root"])
        self.assertTrue((moved / POINTER_FILE).is_file())
        registry = json.loads((self.user_root / "projects.json").read_text(encoding="utf-8"))
        entry = registry["projects"][result["project_id"]]
        self.assertEqual(str(moved), entry["path"])
        self.assertIn("rebound_at", entry)

    def test_registry_rebind_refuses_an_unregistered_path(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        (repo / POINTER_FILE).unlink()
        other = (self.base / "other").resolve()
        other.mkdir()
        with self.assertRaises(DomainError) as error:
            rebind_registered(user_home=self.user_root, source_path=other,
                              target_path=other,
                              confirmation={"source_id": "t", "type": "rebind"})
        self.assertEqual("rebind_project_unregistered", error.exception.code)

    def test_symlinked_absolute_data_root_is_refused(self):
        """A pointer whose absolute data_root is a symlink must be refused."""
        import os
        from fstar.store import _read_pointer, _safe_pointer_data_root
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        record = json.loads((repo / POINTER_FILE).read_text(encoding="utf-8"))
        real = Path(record["data_root"]).resolve()
        alias = self.base / "alias-target"
        os.symlink(real, alias)
        record["data_root"] = str(alias)
        pointer = repo / POINTER_FILE
        pointer.write_text(json.dumps(record), encoding="utf-8")
        # _safe_pointer_data_root must refuse the alias ...
        with self.assertRaises(DomainError) as error:
            _safe_pointer_data_root(repo, _read_pointer(pointer))
        self.assertEqual("corrupt_pointer", error.exception.code)
        # ... and the store built through it must refuse too.
        with self.assertRaises(DomainError) as error:
            TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        self.assertEqual("corrupt_pointer", error.exception.code)

    def test_config_layers_refuse_a_symlinked_pointer_data_root(self):
        """project_config_paths must not follow a symlinked pointer data root."""
        import os
        from fstar.config import project_config_paths, load_config
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        record = json.loads((repo / POINTER_FILE).read_text(encoding="utf-8"))
        real = Path(record["data_root"]).resolve()
        alias = self.base / "alias-config"
        os.symlink(real, alias)
        record["data_root"] = str(alias)
        (repo / POINTER_FILE).write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(DomainError) as error:
            load_config(repo, self.user_root)
        self.assertEqual("corrupt_pointer", error.exception.code)


class DoctorStorageReportTests(StorageModeCase):
    def _doctor_storage(self, repo):
        from fstar.installer import Roots, _schema_report
        roots = Roots(user_root=self.user_root, runtime_root=self.base / "runtime",
                      project_root=repo, host_roots={}, bundle_root=None)
        return _schema_report(roots)["storage"]

    def test_report_names_the_mode_and_data_root_for_each_mode(self):
        shared = self._repo("shared")
        initialize_project(shared, self.user_root, storage="project-shared")
        report = self._doctor_storage(shared)
        self.assertEqual("project-shared", report["mode"])
        self.assertEqual(str((shared / ".fstar").resolve()), report["data_root"])

        local = self._repo("local")
        initialize_project(local, self.user_root, storage="project-local")
        report = self._doctor_storage(local)
        self.assertEqual("project-local", report["mode"])

        user_dir = self._repo("userdir")
        initialize_project(user_dir, self.user_root, storage="user-directory")
        report = self._doctor_storage(user_dir)
        self.assertEqual("user-directory", report["mode"])
        self.assertNotIn(str(user_dir), report["data_root"])
        checks = {check["check"]: check for check in report["checks"]}
        self.assertEqual("ok", checks["registry_entry"]["status"])


class InstallStorageFlagTests(StorageModeCase):
    """``fstar install --storage`` initializes only an uninitialized project."""

    def _install(self, repo, *extra):
        """Run fstar install in-process; return its exit code.

        main() prints the plan and returns 0, or prints the error and
        returns the DomainError status; it never raises DomainError.
        """
        import contextlib
        import io
        from fstar.cli import main
        argv = ["--json", "--user-data-root", str(self.user_root), "--project", str(repo),
                "install", *extra]
        captured, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(errors):
            code = main(argv)
        return code, captured.getvalue() + errors.getvalue()

    def test_dry_run_does_not_initialize(self):
        repo = self._repo()
        code, output = self._install(repo, "--storage", "user-directory", "--dry-run")
        self.assertEqual(0, code)
        self.assertFalse((repo / POINTER_FILE).exists())
        self.assertFalse((repo / ".fstar").exists())

    def test_install_initializes_the_requested_mode(self):
        host = self.base / "host"
        repo = self._repo()
        code, output = self._install(repo, "--storage", "user-directory",
                                     "--host-root", "claude=%s" % host)
        self.assertEqual(0, code)
        self.assertTrue((repo / POINTER_FILE).is_file())
        self.assertFalse((repo / ".fstar").exists())
        self.assertEqual(1, len(list((self.user_root / "projects").iterdir())))

    def test_install_refuses_to_change_an_initialized_mode(self):
        repo = self._repo()
        initialize_project(repo, self.user_root, storage="user-directory")
        code, output = self._install(repo, "--storage", "project-shared", "--dry-run")
        self.assertNotEqual(0, code)
        self.assertIn("storage_mode_mismatch", output)
        self.assertIn("user-directory", output)


class HooksAcrossModesTests(StorageModeCase):
    """Hook injection must find the data root in every storage mode."""

    def _setup(self, name, storage):
        repo = self._repo(name)
        initialize_project(repo, self.user_root, storage=storage)
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        from fstar.tasks import TaskService
        service = TaskService(store)
        agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        service.create(name="demo", title="Demo", description="d", actor=agent, session_id="s1")
        task_dir = store.resolve("demo")
        doc = task_dir / "doc"
        doc.mkdir(exist_ok=True)
        (doc / "prd.md").write_text("# PRD\n", encoding="utf-8")
        (doc / "design.md").write_text("# Design\n", encoding="utf-8")
        (store.fstar_root / "specs").mkdir(parents=True, exist_ok=True)
        (store.fstar_root / "specs" / "core.md").write_text("# Core\n", encoding="utf-8")
        return repo, store, service, task_dir

    def test_planning_and_governance_members_resolve_in_every_mode(self):
        from fstar.runtime import hooks
        for storage, name in (("project-shared", "shared"), ("project-local", "local"),
                              ("user-directory", "userdir")):
            with self.subTest(storage=storage):
                repo, store, service, task_dir = self._setup(name, storage)
                self.assertEqual("prd", hooks._planning_member(repo, task_dir / "doc" / "prd.md"))
                self.assertEqual("design", hooks._planning_member(repo, task_dir / "doc" / "design.md"))
                self.assertEqual("specs", hooks._governance_member(repo, store.fstar_root / "specs" / "core.md"))

    def test_doc_change_hook_resolves_task_docs_in_every_mode(self):
        from fstar.runtime import hooks
        for storage, name in (("project-shared", "shared"), ("project-local", "local"),
                              ("user-directory", "userdir")):
            with self.subTest(storage=storage):
                repo, store, service, task_dir = self._setup(name, storage)
                prd = task_dir / "doc" / "prd.md"
                result = hooks.doc_change({"tool_name": "Write",
                                           "tool_input": {"file_path": str(prd), "content": "# PRD\n"}},
                                          start=repo, user_root=self.user_root,
                                          runtime_root=self.base / "runtime")
                self.assertTrue(result["processed"])
                self.assertEqual(".fstar/tasks/demo/doc/prd.md", result["artifact"])

    def test_session_context_injects_the_project_index_in_every_mode(self):
        from fstar.runtime import hooks
        for storage, name in (("project-shared", "shared"), ("project-local", "local"),
                              ("user-directory", "userdir")):
            with self.subTest(storage=storage):
                repo, store, service, task_dir = self._setup(name, storage)
                result = hooks.session_context({"session_id": "s1"}, start=repo,
                                               user_root=self.user_root,
                                               runtime_root=self.base / "runtime")
                self.assertIn("project_index: .fstar/index.md", result["text"])


class LifecycleAcrossModesTests(StorageModeCase):
    """The full task lifecycle must behave the same in every storage mode."""

    def _service(self, repo):
        from fstar.tasks import TaskService
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        return store, TaskService(store)

    def _lifecycle(self, repo):
        """create -> start -> final check -> accept -> archive, in one mode."""
        import sys
        from fstar.evidence import file_digest
        from fstar.tasks import source_snapshot
        store, service = self._service(repo)
        agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        user = {"role": "user", "id": "user", "session": "s1"}

        def source():
            return {"source_id": "source-1", "type": "command", "at": "2026-11-19T10:00:00Z",
                    "actor": user, "reference": "prompt:1", "quote": "批准", "scope": "task",
                    "validates": source_snapshot(store.read("root"))}

        service.create(name="root", title="Root", description="Deliver R-001",
                       actor=agent, session_id="s1")
        service.start("root", actor=user, confirmation=source(), session_id="s1")
        # The task tree lives in the data root, not in the repository.
        task_dir = store.resolve("root")
        self.assertTrue(task_dir.is_dir())
        self.assertTrue(str(task_dir).startswith(str(store.fstar_root)))

        # Evidence: a fresh final check over a repository artifact.
        (repo / "doc").mkdir(exist_ok=True)
        (repo / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        (repo / "src.py").write_text("value = 1\n")
        (repo / "report.md").write_text("all passed\n")
        with store.transaction():
            task = store.read("root")
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {
                "R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}}}}
            store.write(store.resolve("root"), task)
        lease = service.acquire_lease("root", holder="coordinator", role="coordinator", actor=agent)
        snapshot = service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        delivery = service.evidence.delivery_snapshot(["src.py"])
        service.evidence.record("root", lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run", "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(repo / "report.md")},
            "delivery": delivery, "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["src.py"],
                       "command": "python src.py", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 0.1, "retries": 0}]})
        service.release_lease("root", token=lease["token"], reason="check complete")
        service.enter_awaiting_acceptance("root", actor=agent)
        service.accept("root", actor=user, confirmation=source())
        archived = service.archive("root", actor=user, confirmation=source())
        self.assertTrue(str(archived["path"]).startswith(str(store.archive_root)))
        # The archived task is found again through the archive root.
        found = store.resolve("root", archived=True)
        self.assertTrue(found.is_dir())
        return store

    def test_lifecycle_in_project_shared_mode(self):
        repo = self._repo("shared")
        initialize_project(repo, self.user_root, storage="project-shared")
        store = self._lifecycle(repo)
        self.assertTrue((store.archive_root).is_dir())
        self.assertFalse((repo / ".fstar-pointer.json").exists())

    def test_lifecycle_in_project_local_mode(self):
        repo = self._repo("local")
        initialize_project(repo, self.user_root, storage="project-local")
        store = self._lifecycle(repo)
        self.assertTrue(store.archive_root.is_dir())

    def test_lifecycle_in_user_directory_mode(self):
        repo = self._repo("userdir")
        initialize_project(repo, self.user_root, storage="user-directory")
        store = self._lifecycle(repo)
        # Nothing of the task tree leaked into the repository.
        self.assertFalse((repo / ".fstar").exists())
        self.assertTrue(store.archive_root.is_dir())
        self.assertFalse(str(store.archive_root).startswith(str(repo)))


class KnowledgeAcrossModesTests(StorageModeCase):
    """The knowledge subsystem must read and write in every storage mode."""

    SPEC = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# Core specification

Keep the core module free of feature flags.
"""

    def _seed(self, repo, storage):
        initialize_project(repo, self.user_root, storage=storage)
        store = TaskStore(repo, user_home=self.user_root, runtime_root=self.base / "runtime")
        (store.fstar_root / "specs").mkdir(parents=True, exist_ok=True)
        (store.fstar_root / "specs" / "core.md").write_text(self.SPEC, encoding="utf-8")
        return store

    def _proposal(self, repo):
        from fstar.knowledge import (ChangeIntent, KnowledgeEdit, ReviewedSource,
                                     SemanticAssessment, SourceRecord, TopicChoice,
                                     load_catalog, prepare_change)
        catalog = load_catalog(user_root=self.user_root, project_root=repo)
        reviewed = [ReviewedSource(document.key, document.digest)
                    for document in catalog.documents if document.effective]
        reviewed.extend(ReviewedSource(index.key, index.digest) for index in catalog.indexes)
        assessment = SemanticAssessment(reviewed=tuple(reviewed), conflicts=(), coverage="complete")
        intent = ChangeIntent(summary="tighten the core specification", action="correct",
                              source=SourceRecord("conversation", "chat#42", "yes please", "2026-04-01"),
                              scope="project core specification",
                              topic=TopicChoice("T-1", "核心", is_new=True,
                                                reason="the seed project has no topics yet",
                                                applies_to="src/core",
                                                read_when="修改核心时"))
        edits = [KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                               content=self.SPEC.replace("free of feature flags",
                                                        "free of feature flags and globals"))]
        return prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)

    def test_knowledge_write_lands_in_the_data_root_in_every_mode(self):
        from fstar.knowledge import apply_change
        for storage, name in (("project-shared", "shared"), ("project-local", "local"),
                              ("user-directory", "userdir")):
            with self.subTest(storage=storage):
                repo = self._repo(name)
                store = self._seed(repo, storage)
                proposal = self._proposal(repo)
                from fstar.knowledge import Confirmation
                confirmation = Confirmation(disposition="approved", source_type="conversation",
                                           source_ref="chat#42", quote="yes please",
                                           confirmed_at="2026-04-01",
                                           proposal_hash=proposal.proposal_hash,
                                           scope=proposal.scope, owners=proposal.owners)
                receipt = apply_change(proposal, confirmation, user_root=self.user_root,
                                       project_root=repo)
                # The identity stays the same in every mode ...
                self.assertIn("project:.fstar/specs/core.md", receipt.changed_paths)
                # ... and the bytes land in the resolved data root.
                body = (store.fstar_root / "specs" / "core.md").read_text(encoding="utf-8")
                self.assertIn("feature flags and globals", body)
                if storage == "user-directory":
                    self.assertFalse((repo / ".fstar").exists())


if __name__ == "__main__":
    unittest.main()
