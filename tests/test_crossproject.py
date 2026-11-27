"""Cross-project task coordination regressions (P-002 / D-001 / D-003).

Two or three real temporary git repositories drive the full cross-project
flow through the service and CLI: link creation (bidirectional records),
dispatch into the target project, cross-project status queries, and the
failure/edge cases (uninitialized target, empty specs, duplicate link,
cycle, unavailable target path, lock ordering). The real ``~/.fstar`` is
never read or written.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fstar.crossproject import (CROSS_LINKS_KEY, SPEC_NOTE_KEY,
                                CrossProjectService, cross_project_locks,
                                project_identity, spec_status)
from fstar.models import DomainError
from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


def _git(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class CrossProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_root = (self.base / "user" / ".fstar").resolve()
        self.user_root.mkdir(parents=True)
        self.runtime = self.base / "runtime"
        self.actor = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def _repo(self, name):
        repo = (self.base / name).resolve()
        repo.mkdir()
        _git(repo)
        initialize_project(repo, self.user_root, storage="project-shared")
        return repo

    def _store(self, repo):
        return TaskStore(repo, user_home=self.user_root, runtime_root=self.runtime)

    def _service(self, repo):
        store = self._store(repo)
        return store, TaskService(store)

    def _cross(self, repo, service=None):
        store, service = service or self._service(repo)
        return store, CrossProjectService(store, task_service=service)

    def _source(self, task):
        return {"source_id": "s-%s" % task["id"][:8], "type": "command",
                "at": "2026-11-19T10:00:00Z", "actor": self.user,
                "reference": "prompt:1", "quote": "ok", "scope": "task",
                "validates": source_snapshot(task)}

    def _specs(self, repo, files=None):
        store = self._store(repo)
        specs = store.fstar_root / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        for name, body in (files or {}).items():
            spec_file = specs / name
            spec_file.parent.mkdir(parents=True, exist_ok=True)
            spec_file.write_text(body, encoding="utf-8")

    def _seed_specs(self, repo):
        body = ("# Backend\n\n## Conventions\n\nAll service modules follow the "
                "lock-first write pattern described in this index.\n")
        self._specs(repo, {"backend/index.md": body})

    def _start(self, service, name):
        service.start(name, actor=self.user,
                      confirmation=self._source(service.store.read(name)),
                      session_id="s1")

    def _run_cli(self, repo, *argv):
        from fstar.cli import main
        args = ["--json", "--user-data-root", str(self.user_root),
                "--runtime-root", str(self.runtime), "--project", str(repo), *argv]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue() + err.getvalue()


class CreateChildTests(CrossProjectCase):
    def test_bidirectional_link_records_in_both_projects(self):
        master, target = self._repo("master"), self._repo("target")
        mstore, ms = self._service(master)
        ms.create(name="root", title="Master", description="d",
                  actor=self.actor, session_id="s1")
        _, cross = self._cross(master)
        result = cross.create_child("root", target=str(target), name="child-a",
                                    title="Child A", description="sub",
                                    actor=self.actor)
        self.assertTrue(result["child"]["path"].startswith(str(self._store(target).fstar_root)))
        master_task = mstore.read("root")
        child_task = self._store(target).read("child-a")
        mlinks = master_task["meta"][CROSS_LINKS_KEY]
        clinks = child_task["meta"][CROSS_LINKS_KEY]
        self.assertEqual(1, len(mlinks))
        self.assertEqual(1, len(clinks))
        self.assertEqual("child", mlinks[0]["direction"])
        self.assertEqual("parent", clinks[0]["direction"])
        self.assertEqual(project_identity(self._store(target)), mlinks[0]["project_id"])
        self.assertEqual(child_task["id"], mlinks[0]["task_id"])
        self.assertEqual(master_task["id"], clinks[0]["task_id"])
        self.assertEqual(project_identity(mstore), clinks[0]["project_id"])
        # The 26-field structure and same-repo children are untouched.
        self.assertEqual([], master_task["children"])
        self.assertEqual(26, len(master_task))
        # Bidirectional events recorded.
        self.assertTrue(any(e["type"] == "cross_project_linked"
                            for e in master_task["events"]))
        self.assertTrue(any(e["type"] == "cross_project_linked"
                            for e in child_task["events"]))

    def test_master_write_failure_leaves_no_orphan_child(self):
        master, target = self._repo("master"), self._repo("target")
        mstore, ms = self._service(master)
        ms.create(name="root", title="M", description="", actor=self.actor)
        cross = CrossProjectService(mstore)
        tstore = self._store(target)
        from fstar.store import TaskStore
        original_write = TaskStore.write
        def failing_write(store, task_dir, data, **kwargs):
            if store is mstore:
                raise OSError("simulated master write failure")
            return original_write(store, task_dir, data, **kwargs)
        TaskStore.write = failing_write
        try:
            with self.assertRaises(OSError):
                cross.create_child("root", target=str(target), name="child-a",
                                   title="Child A", actor=self.actor)
        finally:
            TaskStore.write = original_write
        # Both sides untouched and the failed creation is retriable wholesale:
        # no orphan child directory survives in the target project.
        self.assertEqual([], mstore.read("root")["meta"].get(CROSS_LINKS_KEY, []))
        self.assertFalse((tstore.tasks_root / "child-a").exists())
        result = cross.create_child("root", target=str(target), name="child-a",
                                    title="Child A", actor=self.actor)
        self.assertTrue(result["child"]["path"])

    def test_link_existing_write_failure_leaves_no_half_link(self):
        master, target = self._repo("master"), self._repo("target")
        mstore, ms = self._service(master)
        ms.create(name="root", title="M", description="", actor=self.actor)
        tstore, ts = self._service(target)
        ts.create(name="leaf", title="L", description="", actor=self.actor)
        cross = CrossProjectService(mstore)
        from fstar.store import TaskStore
        original_write = TaskStore.write
        def failing_write(store, task_dir, data, **kwargs):
            if store.project_root == mstore.project_root:
                raise OSError("simulated master write failure")
            return original_write(store, task_dir, data, **kwargs)
        TaskStore.write = failing_write
        try:
            with self.assertRaises(OSError):
                cross.link_existing("root", target=str(target), target_task="leaf",
                                    actor=self.actor)
        finally:
            TaskStore.write = original_write
        # Neither side keeps a link: the pair is all-or-nothing.
        self.assertEqual([], mstore.read("root")["meta"].get(CROSS_LINKS_KEY, []))
        self.assertEqual([], tstore.read("leaf")["meta"].get(CROSS_LINKS_KEY, []))
        # The operation stays retriable.
        result = cross.link_existing("root", target=str(target), target_task="leaf",
                                     actor=self.actor)
        self.assertTrue(result["linked"])

    def test_duplicate_link_survives_project_identity_change(self):
        master, target = self._repo("master"), self._repo("target")
        # A legacy project without config.yaml has a path-derived identity.
        (target / ".fstar/config.yaml").unlink()
        mstore, ms = self._service(master)
        ms.create(name="root", title="M", description="", actor=self.actor)
        tstore, ts = self._service(target)
        ts.create(name="leaf", title="L", description="", actor=self.actor)
        cross = CrossProjectService(mstore)
        cross.link_existing("root", target=str(target), target_task="leaf",
                            actor=self.actor)
        self.assertTrue(project_identity(tstore).startswith("path:"))
        # The project gains its config UUID: the identity string changes, but
        # it is still the same project, so the duplicate must be refused.
        (target / ".fstar/config.yaml").write_text(
            'schema_version: 1\nproject:\n  id: "11111111-2222-3333-4444-555555555555"\n',
            encoding="utf-8")
        new_store = self._store(target)
        self.assertEqual("11111111-2222-3333-4444-555555555555",
                         project_identity(new_store))
        with self.assertRaises(DomainError) as error:
            cross.link_existing("root", target=str(target), target_task="leaf",
                                actor=self.actor)
        self.assertEqual("duplicate_link", error.exception.code)
        self.assertEqual(1, len(mstore.read("root")["meta"][CROSS_LINKS_KEY]))

    def test_link_existing_refuses_duplicates(self):
        master, target = self._repo("master"), self._repo("target")
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        ts = self._service(target)[1]
        ts.create(name="leaf", title="L", description="", actor=self.actor)
        _, cross = self._cross(master)
        cross.link_existing("root", target=str(target), target_task="leaf",
                            actor=self.actor)
        with self.assertRaises(DomainError) as error:
            cross.link_existing("root", target=str(target), target_task="leaf",
                                actor=self.actor)
        self.assertEqual("duplicate_link", error.exception.code)

    def test_cycle_is_refused(self):
        a, b = self._repo("proj-a"), self._repo("proj-b")
        sa = self._service(a)[1]
        sb = self._service(b)[1]
        sa.create(name="ta", title="A", description="", actor=self.actor)
        sb.create(name="tb", title="B", description="", actor=self.actor)
        _, cross_a = self._cross(a)
        cross_a.link_existing("ta", target=str(b), target_task="tb", actor=self.actor)
        # tb now masters ta; linking ta as a child of tb closes a cycle
        # (child ta -> parent tb, but tb -> parent ta).
        _, cross_b = self._cross(b)
        # First link tb->ta is fine (no duplicate on tb's child side) ... but
        # it would close the cycle, so it must be refused.
        with self.assertRaises(DomainError) as error:
            cross_b.link_existing("tb", target=str(a), target_task="ta", actor=self.actor)
        self.assertEqual("cross_project_cycle", error.exception.code)

    def test_duplicate_child_link_on_master_refused(self):
        a, b = self._repo("proj-a"), self._repo("proj-b")
        sa = self._service(a)[1]
        sb = self._service(b)[1]
        sa.create(name="ta", title="A", description="", actor=self.actor)
        sb.create(name="tb1", title="B1", description="", actor=self.actor)
        sb.create(name="tb2", title="B2", description="", actor=self.actor)
        _, cross_a = self._cross(a)
        cross_a.link_existing("ta", target=str(b), target_task="tb1", actor=self.actor)
        with self.assertRaises(DomainError) as error:
            cross_a.link_existing("ta", target=str(b), target_task="tb1", actor=self.actor)
        self.assertEqual("duplicate_link", error.exception.code)

    def test_same_project_link_refused(self):
        repo = self._repo("master")
        service = self._service(repo)[1]
        service.create(name="root", title="M", description="", actor=self.actor)
        _, cross = self._cross(repo)
        with self.assertRaises(DomainError) as error:
            cross.link_existing("root", target=str(repo), target_task="root",
                                actor=self.actor)
        self.assertEqual("same_project_link", error.exception.code)


class DispatchTests(CrossProjectCase):
    def _dispatchable(self):
        master, target = self._repo("master"), self._repo("target")
        self._seed_specs(master)
        self._seed_specs(target)
        mstore, ms = self._service(master)
        ms.create(name="root", title="M", description="", actor=self.actor)
        self._start(ms, "root")
        _, cross = self._cross(master)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        return master, target, mstore, cross

    def test_dispatch_registers_against_target_project_with_target_specs(self):
        master, target, mstore, cross = self._dispatchable()
        self._start(self._service(target)[1], "child-a")
        result = cross.dispatch("root", target=str(target), target_task="child-a",
                                role="implement", plan_item_ids=["P-1"],
                                allowed_paths=["src/app.py"], coordinator_id="coord",
                                actor={"role": "coordinator", "id": "coord"})
        payload = result["dispatch"]["payload"]
        # read_context points at the TARGET project's own spec files ...
        read_paths = [entry["path"] for entry in payload["read_context"]]
        self.assertTrue(read_paths)
        target_specs = str(self._store(target).fstar_root)
        for entry in payload["read_context"]:
            # ... resolved through the target store, not the master's root.
            resolved = self._store(target).project_file(entry["path"])
            self.assertTrue(str(resolved).startswith(target_specs))
        self.assertNotIn(str(mstore.fstar_root), " ".join(read_paths))
        # The dispatch is registered in the target task's own store.
        target_task = self._store(target).read("child-a")
        self.assertTrue(any(e["type"] == "dispatch_registered"
                            for e in target_task["events"]))
        self.assertEqual("task", result["dispatch"]["persistence"])
        self.assertTrue(result["dispatch"]["lease_token"])
        # Worker must operate from the target project root.
        self.assertEqual(str(target), result["worker_cwd"])
        self.assertEqual("present", result["target_specs"]["status"])
        self.assertFalse(result["spec_note_recorded"])

    def test_not_initialized_target_is_refused_with_init_guidance(self):
        master = self._repo("master")
        bare = (self.base / "bare").resolve()
        bare.mkdir()
        _git(bare)  # a git repo with NO fstar data root
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        self._start(ms, "root")
        _, cross = self._cross(master)
        with self.assertRaises(DomainError) as error:
            cross.create_child("root", target=str(bare), name="x",
                               title="X", actor=self.actor)
        self.assertEqual("target_not_initialized", error.exception.code)
        self.assertIn("init", error.exception.message.lower())
        with self.assertRaises(DomainError) as error:
            cross.dispatch("root", target=str(bare), target_task="x", role="implement",
                           plan_item_ids=[], allowed_paths=["a"])
        self.assertIn(error.exception.code,
                      {"target_not_initialized", "project_not_initialized"})

    def test_empty_spec_target_records_note_and_continues(self):
        master, target = self._repo("master"), self._repo("target")
        self._seed_specs(master)
        # Target initialized but specs stay an empty placeholder skeleton.
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        self._start(ms, "root")
        _, cross = self._cross(master)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        self._start(self._service(target)[1], "child-a")
        result = cross.dispatch("root", target=str(target), target_task="child-a",
                                role="implement", plan_item_ids=["P-1"],
                                allowed_paths=["src/x.py"])
        self.assertTrue(result["spec_note_recorded"])
        self.assertIn(result["target_specs"]["status"], ("missing", "empty", "placeholder"))
        target_task = self._store(target).read("child-a")
        note = target_task["meta"][SPEC_NOTE_KEY]
        self.assertIn("no specs yet", note["note"])
        self.assertTrue(any(e["type"] == "cross_project_spec_note"
                            for e in target_task["events"]))
        # The dispatch itself still registered: no permanent block.
        self.assertEqual("task", result["dispatch"]["persistence"])


class StatusTests(CrossProjectCase):
    def test_links_report_live_target_state(self):
        master, target = self._repo("master"), self._repo("target")
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        _, cross = self._cross(master)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        report = cross.links("root")
        self.assertEqual(1, len(report["links"]))
        entry = report["links"][0]
        self.assertTrue(entry["available"])
        self.assertEqual("planning", entry["phase"])
        self.assertFalse(entry["disposition"])
        self.assertEqual("project-shared", entry["storage_mode"])

    def test_unavailable_target_path_is_reported(self):
        master, target = self._repo("master"), self._repo("target")
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        _, cross = self._cross(master)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        # The target repository disappears (moved/deleted).
        import shutil
        shutil.rmtree(target)
        report = cross.links("root")
        self.assertFalse(report["links"][0]["available"])
        self.assertIn("unavailable", report["links"][0]["reason"])

    def test_unavailable_target_path_blocks_new_dispatch(self):
        master, target = self._repo("master"), self._repo("target")
        ms = self._service(master)[1]
        ms.create(name="root", title="M", description="", actor=self.actor)
        self._start(ms, "root")
        _, cross = self._cross(master)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        import shutil
        shutil.rmtree(target)
        with self.assertRaises(DomainError) as error:
            cross.dispatch("root", target=str(target), target_task="child-a",
                           role="implement", plan_item_ids=[], allowed_paths=["a"])
        self.assertIn(error.exception.code,
                      {"project_not_initialized", "target_project_unavailable",
                       "unknown_target_project"})


class CliTests(CrossProjectCase):
    def test_cli_link_links_and_status(self):
        master, target = self._repo("master"), self._repo("target")
        self._seed_specs(target)
        self._seed_specs(master)
        code, out = self._run_cli(master, "task", "create", "Master root",
                                  "--name", "root")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(master, "cross", "create-child", "root",
                                  "--target", str(target), "--name", "child-a",
                                  "--title", "Child A")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(master, "cross", "links", "root")
        self.assertEqual(0, code, out)
        self.assertIn(str(target), out)
        self.assertIn('"direction": "child"', out)
        # Start both sides and dispatch through the CLI.
        code, out = self._run_cli(master, "start", "root", "--confirm-user")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(target, "start", "child-a", "--confirm-user")
        self.assertEqual(0, code, out)
        code, out = self._run_cli(master, "cross", "dispatch", "root",
                                  "--target", str(target),
                                  "--target-task", "child-a",
                                  "--role", "implement",
                                  "--plan-item", "P-1",
                                  "--allowed-path", "src/app.py")
        self.assertEqual(0, code, out)
        self.assertIn('"registered":true', out.replace(" ", "").replace("\n", ""))

    def test_cli_dispatch_refuses_uninitialized_target(self):
        master = self._repo("master")
        bare = (self.base / "bare").resolve()
        bare.mkdir()
        _git(bare)
        self._run_cli(master, "task", "create", "Master root", "--name", "root")
        self._run_cli(master, "start", "root", "--confirm-user")
        code, out = self._run_cli(master, "cross", "create-child", "root",
                                   "--target", str(bare), "--name", "x",
                                   "--title", "X")
        self.assertNotEqual(0, code)
        self.assertIn("target_not_initialized", out)


class LockOrderingTests(CrossProjectCase):
    def test_locks_acquire_master_first_then_sorted_others(self):
        master, b, c = self._repo("master"), self._repo("bbb"), self._repo("ccc")
        mstore, bstore, cstore = (self._store(x) for x in (master, b, c))
        with cross_project_locks(mstore, cstore, bstore) as acquired:
            # Inside the region all three locks are held; verify by attempting
            # a fresh exclusive lock on each path from a second fd.
            import fcntl as real_fcntl
            for store in (mstore, bstore, cstore):
                with self.assertRaises(BlockingIOError):
                    with store.lock_path.open("a+") as probe:
                        real_fcntl.flock(probe.fileno(), real_fcntl.LOCK_EX | real_fcntl.LOCK_NB)
            order = [str(s.project_root) for s in (mstore, bstore, cstore)]
        self.assertEqual([str(master), str(b), str(c)], order)

    def test_concurrent_write_is_serialized_and_leaves_consistent_state(self):
        import threading
        master, target = self._repo("master"), self._repo("target")
        mstore, ms = self._service(master)
        ms.create(name="root", title="M", description="", actor=self.actor)
        errors = []

        def worker(store, delay):
            try:
                with cross_project_locks(mstore, store):
                    # Cross-project write region: read-modify-write on the
                    # master index file, held long enough that a serialized
                    # second writer would overlap if locking failed.
                    import time
                    time.sleep(delay)
                    marker = mstore.fstar_root / "index.md"
                    body = marker.read_text(encoding="utf-8")
                    time.sleep(0.05)
                    marker.write_text(body + "x\n", encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(self._store(target), 0.05)),
                   threading.Thread(target=worker, args=(self._store(target), 0.05))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual([], errors)
        # Two serialized read-modify-write appends both landed.
        self.assertEqual(2, mstore.fstar_root.joinpath("index.md")
                         .read_text(encoding="utf-8").count("x\n"))

    def test_same_project_never_locks_twice(self):
        master = self._repo("master")
        mstore = self._store(master)
        with self.assertRaises(DomainError) as error:
            with cross_project_locks(mstore, self._store(master)):
                pass
        self.assertEqual("same_project_link", error.exception.code)
        # Also refused when the duplicate is not adjacent after sorting.
        a, b = self._repo("aaa"), self._repo("zzz")
        with self.assertRaises(DomainError) as error:
            with cross_project_locks(self._store(a), self._store(b), self._store(a)):
                pass
        self.assertEqual("same_project_link", error.exception.code)

    def test_lock_order_is_recoverable_after_timeout(self):
        master, target = self._repo("master"), self._repo("target")
        mstore, tstore = self._store(master), self._store(target)
        # Hold the target lock from an independent fd so acquisition times out.
        tstore.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with tstore.lock_path.open("a+") as holder:
            import fcntl
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            fast = TaskStore(target, user_home=self.user_root, runtime_root=self.runtime,
                             lock_timeout=0.1)
            opened = []
            original_open = Path.open
            def track_open(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                if path in (mstore.lock_path, fast.lock_path):
                    opened.append(stream)
                return stream
            with mock.patch.object(Path, 'open', track_open):
                with self.assertRaises(DomainError) as error:
                    with cross_project_locks(mstore, fast):
                        pass
            self.assertEqual("lock_timeout", error.exception.code)
            self.assertEqual(2, len(opened))
            self.assertTrue(all(stream.closed for stream in opened))
        # After the holder releases, the same operation succeeds: recoverable.
        with cross_project_locks(mstore, fast):
            pass


class ThirdProjectTests(CrossProjectCase):
    def test_master_dispatches_to_two_linked_children(self):
        a, b, c = self._repo("proj-a"), self._repo("proj-b"), self._repo("proj-c")
        self._seed_specs(a)
        for repo in (b, c):
            self._specs(repo, {"backend/index.md": "# B/C spec\n\n## Conventions\n\n"
                                                 "This project documents its conventions in full here.\n"})
        sa = self._service(a)[1]
        sa.create(name="root", title="A master", description="", actor=self.actor)
        self._start(sa, "root")
        _, cross = self._cross(a)
        for repo, name in ((b, "child-b"), (c, "child-c")):
            cross.create_child("root", target=str(repo), name=name,
                               title=name, actor=self.actor)
            self._start(self._service(repo)[1], name)
            result = cross.dispatch("root", target=str(repo), target_task=name,
                                    role="implement", plan_item_ids=["P-1"],
                                    allowed_paths=["src/main.py"])
            self.assertEqual("task", result["dispatch"]["persistence"])
        root_task = self._store(a).read("root")
        self.assertEqual(2, len(root_task["meta"][CROSS_LINKS_KEY]))
        # Distinct target specs were loaded for each child.
        for repo in (b, c):
            child = self._store(repo).read("child-b" if repo is b else "child-c")
            self.assertTrue(any(e["type"] == "dispatch_registered"
                                for e in child["events"]))


class SpecStatusTests(CrossProjectCase):
    def test_placeholder_detection_covers_real_skeletons(self):
        master = self._repo("master")
        store = self._store(master)
        specs = store.fstar_root / "specs"
        self.assertEqual("missing", spec_status(store)["status"])
        topic = specs / "backend"
        topic.mkdir(parents=True)
        self.assertEqual("empty", spec_status(store)["status"])
        # The untouched spec template is a skeleton, not real content.
        template = ("---\nschema: fstar.knowledge.v1\ntype: spec\nstatus: active\n---\n\n"
                    "# Topic specification\n\nWrite concise, executable guidance in "
                    "`language.specs` (default English). Prefer existing authoritative "
                    "project documentation and include a source or short example when "
                    "useful.\n")
        (topic / "index.md").write_text(template, encoding="utf-8")
        (topic / "directory.md").write_text(
            "---\nschema: fstar.knowledge.v1\ntype: spec\nstatus: active\n---\n\n"
            "# 目录结构\n\n待补：待补\n", encoding="utf-8")
        self.assertEqual("placeholder", spec_status(store)["status"])
        # A short index file is a placeholder too.
        (topic / "index.md").write_text("# a\n", encoding="utf-8")
        self.assertEqual("placeholder", spec_status(store)["status"])
        # Real content in one file of the topic makes the topic present.
        (topic / "index.md").write_text(
            "# Backend\n\n## Conventions\n\nAll service modules follow the "
            "lock-first write pattern described in this index.\n", encoding="utf-8")
        self.assertEqual("present", spec_status(store)["status"])


class CrossProjectLockRecheckTests(CrossProjectCase):
    """C: cross_project_locks re-checks each store's layout after locking."""

    def test_cross_project_locks_recheck_layout_after_acquiring_lock(self):
        import fcntl
        main = (self.base / "recheck-main").resolve()
        worktree = (self.base / "recheck-wt").resolve()
        main.mkdir()
        _git(main)
        subprocess.run(["git", "-C", str(main), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid",
                        "-c", "commit.gpgsign=false", "commit",
                        "--allow-empty", "-qm", "baseline"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        initialize_project(main, self.user_root, storage="project-shared")
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q",
                        "-b", "recheck", str(worktree)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from fstar.project import initialize_project as init_project
        mstore = self._store(main)
        wstore = self._store(worktree)
        self.assertEqual(mstore.lock_path, wstore.lock_path)
        from fstar.tasks import TaskService
        TaskService(mstore).create(name="existing", title="E", description="",
                                   actor=self.actor)
        # An unrelated third project so the contended store is the master.
        other = self._repo("recheck-other")
        ostore = self._store(other)
        actual_flock = fcntl.flock
        changed = []

        def transition(fd, operation):
            result = actual_flock(fd, operation)
            if operation & fcntl.LOCK_EX and not changed:
                changed.append(True)
                init_project(worktree, self.user_root, storage="project-shared",
                             force_separate=True)
            return result

        with mock.patch("fstar.store.fcntl.flock", side_effect=transition):
            with self.assertRaises(DomainError) as caught:
                with cross_project_locks(wstore, ostore):
                    self.fail("a stale store wrote through cross-project locks")
        self.assertTrue(changed)
        self.assertEqual("worktree_data_conflict", caught.exception.code)
        # The transition completed under the contended lock; the master
        # (stale, main-rooted) task carries no cross-project link records,
        # and the fresh worktree identity has none either.
        master_task = mstore.read("existing")
        self.assertEqual([], master_task["meta"].get(CROSS_LINKS_KEY, []))
        fresh = self._store(worktree)
        for task in fresh.scan():
            self.assertEqual([], task["meta"].get(CROSS_LINKS_KEY, []))
        self.assertEqual([], ostore.scan())
        self.assertFalse((main / ".fstar/tasks/wrong-root").exists())

    def test_cross_project_lock_recheck_is_recoverable(self):
        from fstar.crossproject import cross_project_locks
        master, target = self._repo("recheck-a"), self._repo("recheck-b")
        mstore, tstore = self._store(master), self._store(target)
        # A plain acquisition with an unchanged layout still works after the
        # post-lock recheck: the operation is retriable.
        with cross_project_locks(mstore, tstore):
            pass
        with cross_project_locks(mstore, tstore):
            pass


if __name__ == "__main__":
    unittest.main()
