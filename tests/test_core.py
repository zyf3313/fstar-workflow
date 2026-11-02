from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fstar.evidence import EvidenceService, file_digest
from fstar.models import DomainError, TASK_FIELDS, new_task, validate_task
from fstar.store import TaskStore, atomic_write_json
from fstar.tasks import TaskService, source_snapshot


def _lock_worker(project, runtime, marker, hold):
    import time
    store = TaskStore(Path(project), runtime_root=Path(runtime), lock_timeout=2.0)
    with store.transaction():
        Path(marker).write_text("locked")
        time.sleep(hold)


def _increment_worker(project, runtime, rounds):
    store = TaskStore(Path(project), runtime_root=Path(runtime), lock_timeout=5.0)
    for _ in range(rounds):
        with store.transaction():
            task = store.read("root")
            task["notes"] = str(int(task["notes"] or "0") + 1)
            store.write(store.resolve("root"), task)


class Clock:
    def __init__(self, value="2026-10-29T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, minutes):
        moment = datetime.fromisoformat(self.value.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        self.value = moment.isoformat().replace("+00:00", "Z")


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / ".fstar").mkdir()
        (self.project / ".fstar" / ".schema-version").write_text("1\n")
        self.store = TaskStore(self.project, user_home=root / "user", runtime_root=root / "runtime")
        self.clock = Clock()
        self.service = TaskService(self.store, clock=self.clock)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref, source_type="command", actor=None, archived=False):
        task = self.store.read(ref, archived=archived)
        return {"source_id": "source-" + task["id"], "type": source_type, "at": self.clock(), "actor": actor or self.user, "reference": "prompt:42", "quote": "批准" if source_type == "conversation" else "", "scope": "task", "validates": source_snapshot(task)}

    def create(self, name="root", parent=None):
        return self.service.create(name=name, title=name.title(), description="Deliver R-001", actor=self.agent, parent=parent, session_id="s1")

    def start(self, ref="root"):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref), session_id="s1")


class WorkflowRecoveryGrantTests(CoreCase):
    def test_recovery_read_and_mutation_require_current_member(self):
        self.create()
        self.start()
        recovered = TaskService(self.store, clock=self.clock)
        def authorize(included, excluded):
            return self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": included, "excluded": excluded, "source": {"type": "test"}}, actor=self.user)
        authorize(["archive"], ["recovery"])
        before = self.store.read("root")
        with self.assertRaises(DomainError) as caught:
            recovered.continue_task("root", workflow=True)
        self.assertEqual("extension_not_authorized", caught.exception.code)
        with self.assertRaises(DomainError):
            recovered.continue_task("root", action="replan", actor=self.user, confirmation=self.source("root"), reason="change", workflow=True)
        self.assertEqual(before, self.store.read("root"))
        authorize(["recovery"], ["archive"])
        self.assertEqual("in_progress", recovered.continue_task("root", workflow=True)["phase"])
        self.service.disable_extension("root", extension_id="persistent-task", authorization={"type": "test"}, actor=self.user)
        with self.assertRaises(DomainError):
            recovered.continue_task("root", action="takeover", actor=self.agent, reason="recover", workflow=True)
        # Direct core use remains available for internal dispatch bookkeeping.
        self.assertEqual("in_progress", recovered.continue_task("root")["phase"])
        authorize(["recovery"], ["archive"])
        self.assertEqual("planning", recovered.continue_task("root", action="replan", actor=self.user, confirmation=self.source("root"), reason="change", workflow=True)["phase"])


class ModelsStoreTests(CoreCase):
    def test_exact_schema_and_validation(self):
        task = new_task("safe-name", "Safe", "", creator="me", now=self.clock())
        self.assertEqual(set(TASK_FIELDS), set(task))
        self.assertEqual(26, len(task))
        for phase in ("drafting", "dropped", "archived", "done"):
            changed = dict(task)
            changed["phase"] = phase
            with self.assertRaises(DomainError):
                validate_task(changed)
        changed = dict(task)
        changed["review"] = []
        with self.assertRaises(DomainError):
            validate_task(changed)
        for field, value in (("title", 1), ("description", []), ("assignee", {}), ("completedAt", 0), ("lease", []), ("acceptance", []), ("events", ["bad"])):
            changed = dict(task)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(DomainError):
                validate_task(changed)

    def test_read_only_missing_project_creates_nothing(self):
        root = Path(self.tmp.name) / "missing"
        root.mkdir()
        runtime = Path(self.tmp.name) / "never"
        store = TaskStore(root, runtime_root=runtime)
        with self.assertRaises(DomainError):
            store.scan()
        self.assertFalse(runtime.exists())
        self.assertFalse((root / ".fstar").exists())

    def test_real_process_lock_contention(self):
        import time
        marker = Path(self.tmp.name) / "locked"
        process = multiprocessing.Process(target=_lock_worker, args=(str(self.project), str(self.store.runtime_root), str(marker), 0.35))
        process.start()
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        with self.store.transaction():
            waited = time.monotonic() - started
        process.join(2)
        self.assertEqual(0, process.exitcode)
        self.assertGreaterEqual(waited, 0.2)

    def test_session_isolation_and_corrupt_json(self):
        created = self.create()
        self.store.set_current("other", Path(created["path"]), created["task"]["id"])
        self.assertNotEqual(self.store.session_path("s1"), self.store.session_path("other"))
        self.assertIsNone(self.store.current("none"))
        Path(created["path"], "task.json").write_text("{")
        with self.assertRaisesRegex(DomainError, "repair"):
            self.store.read("root")

    def test_path_escape_and_symlink_rejected(self):
        self.create()
        with self.assertRaises(DomainError):
            self.store.resolve("../outside")
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        link = self.store.tasks_root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(DomainError):
            self.store.resolve("escape")

    def test_expected_hash_and_atomic_json(self):
        created = self.create()
        task = created["task"]
        with self.store.transaction():
            with self.assertRaises(DomainError):
                self.store.write(Path(created["path"]), task, expected_hash="old")
        parsed = json.loads(Path(created["path"], "task.json").read_text())
        self.assertEqual(task["id"], parsed["id"])

    def test_two_processes_do_not_lose_updates(self):
        self.create()
        workers = [multiprocessing.Process(target=_increment_worker, args=(str(self.project), str(self.store.runtime_root), 10)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(0, worker.exitcode)
        self.assertEqual("20", self.store.read("root")["notes"])


class LifecycleTests(CoreCase):
    def test_nested_ownership_and_completion_gate(self):
        self.create()
        self.create("child", parent="root")
        task = self.store.read("root")
        self.assertEqual(["child"], task["children"])
        self.start("root")
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertIn(caught.exception.code, {"children_incomplete", "acceptance_blocked"})

    def test_start_source_and_conversation_boundary(self):
        self.create()
        self.assertEqual("system", self.store.read("root")["events"][0]["source"]["type"])
        source = self.source("root", "conversation")
        task = self.service.start("root", actor=self.agent, confirmation=source)
        self.assertEqual("in_progress", task["phase"])
        self.assertEqual("批准", task["events"][-1]["source"]["quote"])
        self.create("bad")
        bad = self.source("bad", "conversation")
        bad["quote"] = ""
        with self.assertRaises(DomainError):
            self.service.start("bad", actor=self.agent, confirmation=bad)

    def test_lease_expiration_renewal_takeover_and_old_token(self):
        self.create()
        self.start()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        with self.assertRaises(DomainError) as blocked:
            self.service.set_blocked("root", actor={"role": "agent", "id": "other"}, reason="race")
        self.assertEqual("lease_conflict", blocked.exception.code)
        with self.assertRaises(DomainError):
            self.service.enable_extension("root", authorization={"id": "multi-agent", "scope": "full", "source": self.source("root")}, actor=self.user)
        self.clock.advance(29)
        renewed = self.service.renew_lease("root", token=lease["token"])
        self.assertEqual("2026-10-29T10:59:00Z", renewed["expires_at"])
        with self.assertRaises(DomainError):
            self.service.acquire_lease("root", holder="other", role="coordinator", actor={"role": "agent", "id": "other"})
        taken = self.service.acquire_lease("root", holder="other", role="coordinator", takeover_reason="user transfer", actor={"role": "user", "id": "user"})
        with self.assertRaises(DomainError):
            self.service.renew_lease("root", token=lease["token"])
        self.assertEqual("other", taken["holder"]["id"])
        self.clock.advance(31)
        with self.assertRaises(DomainError):
            self.service.renew_lease("root", token=taken["token"])
        status = self.service.continue_task("root")
        self.assertTrue(status["orphaned"])
        self.assertEqual("choose_takeover_replan_or_drop", status["next"])

    def test_continue_is_read_only_and_replan_stales_all(self):
        self.create()
        self.start()
        path = self.store.resolve("root") / "task.json"
        before = path.read_bytes()
        result = self.service.continue_task("root")
        self.assertEqual(before, path.read_bytes())
        self.assertEqual("implement_or_check", result["next"])
        with self.store.transaction():
            task = self.store.read("root")
            task["evidence"] = [{"id": "e1", "kind": "delivery", "producer": {}, "produced_at": self.clock(), "state": "valid", "validates": []}, {"id": "e2", "kind": "review", "producer": {}, "produced_at": self.clock(), "state": "valid", "validates": []}]
            self.store.write(self.store.resolve("root"), task)
        replanned = self.service.continue_task("root", action="replan", actor=self.agent, confirmation=self.source("root", "conversation"), reason="requirements changed")
        self.assertEqual("planning", replanned["phase"])
        self.assertTrue(all(x["state"] == "stale" for x in replanned["evidence"]))
        self.assertIsNone(replanned["lease"])

    def test_continue_actions_require_confirmation_and_phase(self):
        self.create()
        self.start()
        with self.assertRaises(DomainError) as caught:
            self.service.continue_task("root", action="replan", actor=self.agent, reason="no user decision")
        self.assertEqual("confirmation_required", caught.exception.code)

    def test_events_keep_milestones_beyond_soft_limit(self):
        self.create()
        with self.store.transaction():
            task = self.store.read("root")
            task["events"] = [{"id": str(i), "at": self.clock(), "source": {}, "type": "accepted", "data": {}} for i in range(205)]
            self.service._write(self.store.resolve("root"), task)
        task = self.store.read("root")
        self.assertEqual(205, len(task["events"]))
        self.assertTrue(all(x["type"] == "accepted" for x in task["events"]))
        with self.store.transaction():
            task["events"].extend({"id": "n%s" % i, "at": self.clock(), "source": {}, "type": "lease_renewed", "data": {}} for i in range(20))
            self.service._write(self.store.resolve("root"), task)
        task = self.store.read("root")
        self.assertEqual(205, sum(x["type"] == "accepted" for x in task["events"]))
        self.assertTrue(any(x["type"] == "summary" for x in task["events"]))

    def test_custom_planning_artifacts_control_start_gate(self):
        self.create()
        self.service.enable_extension("root", authorization={
            "id": "planning-review", "scope": "custom", "included": ["clarify"],
            "excluded": ["prd", "design"], "source": self.source("root")}, actor=self.user)
        self.assertEqual("in_progress", self.start()["phase"])

        self.create("with-prd")
        self.service.enable_extension("with-prd", authorization={
            "id": "planning-review", "scope": "custom", "included": ["prd"],
            "excluded": ["design"], "source": self.source("with-prd")}, actor=self.user)
        with self.assertRaises(DomainError) as caught:
            self.start("with-prd")
        self.assertEqual("planning_artifacts_missing", caught.exception.code)
        self.assertEqual("planning", self.store.read("with-prd")["phase"])

    def test_extensions_separate_and_session_only(self):
        result = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["research"], "excluded": ["parallel-implement"], "reason": "need research", "source": {"source_id": "u"}}, actor=self.user)
        self.assertEqual("session_only", result["persistence"])
        self.create()
        source = self.source("root")
        saved = self.service.enable_extension("root", authorization={"id": "tool-capability", "scope": "full", "included": [], "excluded": [], "reason": "tools", "source": source}, actor=self.user)
        task = self.store.read("root")
        self.assertEqual("tool-capability", saved["id"])
        self.assertEqual([], task["capabilities"])
        self.assertEqual(1, len(task["extensions"]))


class EvidenceArchiveTests(CoreCase):
    def prepare_artifacts(self, ref="root"):
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n<!-- R2:start -->\nsecond\n<!-- R2:end -->\n")
        (self.project / "src.py").write_text("value = 1\n")
        (self.project / "test.py").write_text("assert True\n")
        (self.project / "config.ini").write_text("enabled=1\n")
        (self.project / "report.md").write_text("all passed\n")
        with self.store.transaction():
            task = self.store.read(ref)
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {"R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}, "R-002": {"start_marker": "<!-- R2:start -->", "end_marker": "<!-- R2:end -->"}}}}
            self.store.write(self.store.resolve(ref), task)

    def check_record(self, lease, requirement="R-001", ref="root", producer="checker"):
        snapshot = self.service.evidence.snapshot(ref, artifact="doc/prd.md", items=[requirement])
        delivery = self.service.evidence.delivery_snapshot(["src.py", "test.py", "config.ini"])
        return self.service.evidence.record(ref, lease_token=lease["token"], evidence={"kind": "check", "producer": {"role": "check", "id": producer, "session_id": "check-1"}, "validates": [snapshot], "run_id": "run-1", "environment": {"python": sys.version.split()[0]}, "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")}, "delivery": delivery, "scope": "final", "items": [{"requirement_ids": [requirement], "plan_item": "P-1", "test_refs": ["test.py"], "command": "python test.py", "result": "passed", "exit_code": 0, "log_refs": ["report.md"], "duration": 1.0, "retries": 0}]})

    def test_item_and_delivery_freshness(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        evidence = self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="check complete")
        self.assertTrue(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])
        text = (self.project / "doc" / "prd.md").read_text().replace("second", "changed second")
        (self.project / "doc" / "prd.md").write_text(text)
        fresh = self.service.evidence.freshness("root")
        self.assertTrue(fresh["evidence"][0]["fresh"])
        (self.project / "config.ini").write_text("enabled=0\n")
        fresh = self.service.evidence.freshness("root")
        self.assertFalse(fresh["evidence"][0]["fresh"])
        invalidated = self.service.evidence.invalidate("root", file="config.ini", actor=self.agent)
        self.assertEqual([evidence["id"]], invalidated["invalidated"])

    def test_wrong_producer_and_old_result_rejected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        with self.assertRaises(DomainError):
            self.service.evidence.record("root", lease_token=lease["token"], evidence={"kind": "check", "producer": {"role": "implement", "id": "worker"}, "validates": [], "scope": "final", "run_id": "x", "environment": {}, "delivery": {}, "items": []})
        self.service.acquire_lease("root", holder="other", role="coordinator", takeover_reason="transfer", actor=self.user)
        with self.assertRaises(DomainError):
            self.check_record(lease)

    def test_file_mode_roundtrip_and_stale_on_change(self):
        self.create()
        self.start()
        (self.project / "notes.md").write_text("whole file content\n")
        (self.project / "report.md").write_text("ok\n")
        (self.project / "src.py").write_text("x = 1\n")
        persisted = self.service.evidence.persist_artifact_map("root", mapping={"mode": "file", "notes.md": {}}, source={"source_id": "content"})
        self.assertEqual("file", persisted["artifact_map"]["mode"])
        stored = self.store.read("root")["meta"]["templates"]["artifact_map"]
        self.assertEqual("file", stored["mode"])
        snapshot = self.service.evidence.snapshot("root", artifact="notes.md", items=["R-001"])
        self.assertEqual("file", snapshot["granularity"])
        self.assertEqual(1, len(snapshot["items"]))
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.service.evidence.record("root", lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run", "environment": {"python": "3.9"},
            "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
            "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [], "command": "python test.py", "result": "passed", "exit_code": 0, "log_refs": [], "duration": 0.1, "retries": 0}]})
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.assertTrue(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])
        (self.project / "notes.md").write_text("whole file content, edited\n")
        self.assertFalse(self.service.evidence.freshness("root")["evidence"][0]["fresh"])
        self.assertFalse(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])
        invalidated = self.service.evidence.invalidate("root", file="notes.md", actor=self.agent)
        self.assertEqual(1, len(invalidated["invalidated"]))

    def test_latest_failed_final_check_overrides_older_pass(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        failed = {
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "check-2"},
            "validates": [self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])],
            "run_id": "run-2", "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
            "delivery": self.service.evidence.delivery_snapshot(["src.py", "test.py", "config.ini"]),
            "scope": "final", "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["test.py"], "command": "python test.py", "result": "failed", "exit_code": 1, "log_refs": ["report.md"], "duration": 1.0, "retries": 0}],
        }
        self.service.evidence.record("root", lease_token=lease["token"], evidence=failed)
        self.service.release_lease("root", token=lease["token"], reason="failed check")
        status = self.service.evidence.acceptance_status("root")
        self.assertFalse(status["awaiting_acceptance"])
        self.assertTrue(status["checks"][0]["superseded"])

    def test_newer_stale_failed_check_does_not_restore_older_pass(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        first = self.check_record(lease)
        report = self.project / "second-report.md"
        report.write_text("failed\n")
        second = dict(first)
        second.pop("id")
        second["run_id"] = "run-2"
        second["report"] = {"path": "second-report.md", "sha256": file_digest(report)}
        second["items"] = [dict(first["items"][0], result="failed")]
        self.service.evidence.record("root", lease_token=lease["token"], evidence=second)
        self.service.release_lease("root", token=lease["token"], reason="check complete")
        report.write_text("edited\n")
        status = self.service.evidence.acceptance_status("root")
        self.assertFalse(status["awaiting_acceptance"])
        self.assertEqual([], status["evidence_refs"])
        self.assertTrue(status["checks"][0]["superseded"])
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_transitive_dependency_change_stales_check(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        with self.store.transaction():
            task = self.store.read("root")
            task["meta"]["templates"]["artifact_map"]["doc/prd.md"]["R-001"]["dependencies"] = ["R-002"]
            self.store.write(self.store.resolve("root"), task)
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        evidence = self.check_record(lease)
        self.assertTrue(any(item["id"] == "R-002" for item in evidence["validates"][0]["dependencies"]))
        path = self.project / "doc" / "prd.md"
        path.write_text(path.read_text().replace("second", "changed dependency"))
        self.assertFalse(self.service.evidence.freshness("root")["evidence"][0]["fresh"])

    def test_delivery_deletion_detected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        (self.project / "src.py").unlink()
        status = self.service.evidence.acceptance_status("root")
        self.assertFalse(status["awaiting_acceptance"])

    def test_stale_confirmation_rejected_on_accept(self):
        self.create()
        self.start()
        stale = self.source("root")
        with self.store.transaction():
            task = self.store.read("root")
            task["description"] = "changed scope"
            self.store.write(self.store.resolve("root"), task)
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=stale)
        self.assertEqual("stale_confirmation", caught.exception.code)

    def test_review_source_must_reference_approved_user_review(self):
        self.create()
        missing = self.source("root", "review")
        missing["reference"] = "missing-review"
        with self.assertRaises(DomainError) as caught:
            self.service.start("root", actor=self.user, confirmation=missing)
        self.assertEqual("invalid_confirmation", caught.exception.code)
        review = self.service.record_review("root", record={"source": self.source("root", "conversation"), "verdict": "approved", "validates": []}, actor=self.user)
        good = self.source("root", "review")
        good["reference"] = review["id"]
        self.assertEqual("in_progress", self.service.start("root", actor=self.user, confirmation=good)["phase"])

    def test_check_producer_must_differ_from_delivery_producer(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        with self.store.transaction():
            task = self.store.read("root")
            task["evidence"].append({"id": "delivery", "kind": "delivery", "producer": {"role": "implement", "id": "same"}, "produced_at": self.clock(), "state": "valid", "validates": []})
            self.store.write(self.store.resolve("root"), task)
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        with self.assertRaisesRegex(DomainError, "distinct"):
            self.service.evidence.record("root", lease_token=lease["token"], evidence={
                "kind": "check", "producer": {"role": "check", "id": "same"}, "validates": [snapshot],
                "run_id": "run", "environment": {"python": "3.9"}, "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
                "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "final",
                "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [], "command": "python test.py", "result": "passed", "exit_code": 0, "log_refs": [], "duration": 0.1, "retries": 0}],
            })

    def test_workflow_archive_member_allow_exclude_revoke_and_recovery(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        def grant(included, excluded):
            self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": included, "excluded": excluded, "source": {"type": "test"}}, actor=self.user)
        recovered = TaskService(self.store, clock=self.clock)
        grant(["recovery"], ["archive"])
        with self.assertRaises(DomainError) as caught:
            recovered.archive("root", actor=self.user, confirmation=self.source("root"), workflow=True)
        self.assertEqual("extension_not_authorized", caught.exception.code)
        grant(["archive"], ["recovery"])
        self.service.disable_extension("root", extension_id="persistent-task", authorization={"type": "test"}, actor=self.user)
        with self.assertRaises(DomainError):
            recovered.archive("root", actor=self.user, confirmation=self.source("root"), workflow=True)
        grant(["archive"], ["recovery"])
        confirmation = self.source("root")
        archived = recovered.archive("root", actor=self.user, confirmation=confirmation, operation_id="workflow-archive", workflow=True)
        self.assertTrue(Path(archived["path"]).is_dir())
        self.assertTrue(recovered.archive(archived["task"]["id"], actor=self.user, confirmation=confirmation, operation_id="workflow-archive", workflow=True)["recovered"])

    def test_full_lifecycle_and_archive_conflict(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        accepted = self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("completed", accepted["phase"])
        archive_source = self.source("root")
        archived = self.service.archive("root", actor=self.user, confirmation=archive_source, operation_id="op-1")
        self.assertIn("/.fstar/archive/2026-10/root", archived["path"])
        self.assertIsNotNone(archived["task"]["archivedAt"])
        self.assertEqual([], self.service.list_tasks())
        archived_rows = self.service.list_tasks(archived=True)
        self.assertEqual(["root"], [row["name"] for row in archived_rows])
        self.assertEqual("no_current", self.service.current("s1")["status"])
        recovered = self.service.archive(archived["task"]["id"], actor=self.user, confirmation=archive_source, operation_id="op-1")
        self.assertTrue(recovered["recovered"])

    def test_related_task_links_archived_history(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        archived = self.service.archive("root", actor=self.user, confirmation=self.source("root"))
        related = [{"id": archived["task"]["id"], "archive_path": archived["path"], "relation": "follow_up", "reason": "new scope"}]
        created = self.service.create(name="followup", title="Follow up", description="new scope", actor=self.agent, related=related)
        self.assertEqual(archived["task"]["id"], created["task"]["meta"]["related_tasks"][0]["id"])
        self.assertFalse((self.store.tasks_root / "root").exists())
        with self.assertRaises(DomainError) as caught:
            self.service.create(name="badrelated", title="Bad", description="", actor=self.agent, related=[{"id": "wrong-id", "archive_path": archived["path"]}])
        self.assertEqual("invalid_related_task", caught.exception.code)

    def test_archive_candidates_and_reminder_dedupe(self):
        self.create()
        self.create("old")
        with self.store.transaction():
            task = self.store.read("old")
            task["createdAt"] = "2026-01-01T00:00:00Z"
            task["events"] = []
            self.store.write(self.store.resolve("old"), task)
        candidates = [row for row in self.service.archive_candidates() if row["name"] == "old"]
        self.assertEqual(1, len(candidates))
        self.assertIn("not_completed_or_dropped", candidates[0]["missing"])
        first = self.service.record_reminders(candidates)
        self.assertEqual(1, len(first))
        self.assertEqual([], self.service.record_reminders(candidates))
        self.assertIn(candidates[0]["reminder_key"], self.store.read("old")["meta"]["reminders"])

    def test_archive_interruption_recovery_after_move(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        confirmation = self.source("root")
        task_dir = self.store.resolve("root")
        target = self.store.archive_root / "2026-10" / "root"
        with self.store.transaction():
            task = self.store.read("root")
            from fstar.tasks import make_event
            task["events"].append(make_event("archive_operation", confirmation, {"operation_id": "interrupted", "target": ".fstar/archive/2026-10/root", "archived_at": self.clock()}, self.clock()))
            self.store.write(task_dir, task)
            target.parent.mkdir(parents=True)
            os.rename(str(task_dir), str(target))
        forged = dict(confirmation, actor=self.agent, reference="forged")
        recovered = self.service.archive(task["id"], actor=self.agent, confirmation=forged, operation_id="interrupted", workflow=True)
        self.assertTrue(recovered["recovered"])
        self.assertEqual(self.clock(), recovered["task"]["archivedAt"])
        archived_event = next(x for x in recovered["task"]["events"] if x["type"] == "archived")
        self.assertEqual(confirmation, archived_event["source"])

    def test_archive_target_conflict_and_child_rejected(self):
        self.create()
        self.create("child", parent="root")
        with self.assertRaises(DomainError):
            self.service.archive("child", actor=self.user, confirmation=self.source("child"))
        target = self.store.archive_root / "2026-10" / "root"
        target.mkdir(parents=True)
        with self.assertRaises(DomainError):
            self.service.archive("root", actor=self.user, confirmation=self.source("root"))

    def complete_child(self, child="root/subtasks/child"):
        self.start(child)
        lease = self.service.acquire_lease(child, holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease, ref=child)
        self.service.release_lease(child, token=lease["token"], reason="done")
        self.service.accept(child, actor=self.user, confirmation=self.source(child))

    def test_accept_rejects_stale_child_acceptance(self):
        self.create()
        self.create("child", parent="root")
        self.prepare_artifacts("root/subtasks/child")
        self.prepare_artifacts("root")
        self.complete_child()
        self.start("root")
        (self.project / "config.ini").write_text("enabled=0\n")
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("children_incomplete", caught.exception.code)

    def test_archive_validates_whole_tree(self):
        self.create()
        self.create("child", parent="root")
        self.prepare_artifacts("root/subtasks/child")
        self.prepare_artifacts("root")
        self.complete_child()
        self.start("root")
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        # A child reopened after the parent acceptance makes the tree
        # non-terminal; archive must reject it.
        self.service.continue_task("root/subtasks/child", action="reopen", actor=self.user, confirmation=self.source("root/subtasks/child"), reason="rework")
        with self.assertRaises(DomainError) as caught:
            self.service.archive("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("archive_blocked", caught.exception.code)

    def test_dropped_task_blocks_ordinary_writes(self):
        self.create()
        self.start()
        self.service.drop("root", actor=self.user, confirmation=self.source("root"), reason="abandon", disposition="keep")
        with self.assertRaises(DomainError) as caught:
            self.service.set_blocked("root", actor=self.user, reason="race")
        self.assertEqual("task_dropped", caught.exception.code)
        with self.assertRaises(DomainError):
            self.service.record_review("root", record={"source": self.source("root", "conversation"), "verdict": "comment"}, actor=self.user)
        revived = self.service.drop("root", actor=self.user, confirmation=self.source("root"), reason="resume", action="revive")
        self.assertIsNone(revived["meta"]["disposition"])
        self.assertEqual("planning", revived["phase"])


class LifecycleMemberBoundaryTests(EvidenceArchiveTests):
    """Settled boundary (2026-10-31, parent implement.md progress log):

    Custom-scope trimming of the persistent-task `task`/`evidence`/`lease`/
    `events` members gates only user-facing workflow consumption entries;
    the safety machinery (evidence staleness, lease safety, archive recovery,
    event integrity) stays ALWAYS ON. These regressions pin that boundary so
    a future gating change cannot silently disable consistency guarantees.
    """

    def _trim_bookkeeping_members(self):
        """Exclude exactly the four safety-machinery members."""
        return self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["recovery", "archive"], "excluded": ["task", "evidence", "lease", "events"], "source": {"type": "test"}}, actor=self.user)

    def test_trimmed_bookkeeping_members_keep_evidence_staleness_and_invalidation(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self._trim_bookkeeping_members()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="check complete")
        # Evidence freshness/staleness machinery is member-independent.
        self.assertTrue(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])
        (self.project / "config.ini").write_text("enabled=0\n")
        self.assertFalse(self.service.evidence.freshness("root")["evidence"][0]["fresh"])
        invalidated = self.service.evidence.invalidate("root", file="config.ini", actor=self.agent)
        self.assertEqual(1, len(invalidated["invalidated"]))
        # The invalidation event itself landed (events integrity is internal).
        events = [e["type"] for e in self.store.read("root")["events"]]
        self.assertIn("evidence_invalidated", events)
        # Harvest-time evidence recording paths likewise never consult members.
        with self.assertRaises(DomainError) as caught:
            self.service.evidence.record("root", lease_token="expired-token", evidence={"kind": "check", "producer": {"role": "check", "id": "c"}, "validates": [], "scope": "final", "run_id": "x", "environment": {}, "delivery": {}, "items": []})
        self.assertEqual("invalid_lease", caught.exception.code)

    def test_trimmed_lease_member_keeps_lease_safety(self):
        self.create()
        self.start()
        self._trim_bookkeeping_members()
        # Acquisition, renewal, expiry and takeover run without any member.
        first = self.service.acquire_lease("root", holder="worker-1", role="implement", actor=self.agent)
        self.service.renew_lease("root", token=first["token"])
        with self.assertRaises(DomainError) as caught:
            self.service.acquire_lease("root", holder="worker-1b", role="implement", actor=self.agent)
        self.assertEqual("lease_conflict", caught.exception.code)
        self.clock.advance(45)
        second = self.service.acquire_lease("root", holder="worker-2", role="coordinator", takeover_reason="expired", actor=self.user)
        self.assertNotEqual(first["token"], second["token"])
        with self.assertRaises(DomainError) as caught:
            self.service.renew_lease("root", token=first["token"])
        self.assertEqual("invalid_lease", caught.exception.code)
        # An expired lease still surfaces as a read-only orphan report.
        self.clock.advance(45)
        status = self.service.continue_task("root")
        self.assertTrue(status["orphaned"])
        self.assertEqual("choose_takeover_replan_or_drop", status["next"])
        # Workflow continue/orphan consumption still requires the recovery
        # member: trimming recovery denies the workflow entry while the
        # lease-machinery itself (expiry reporting, takeover) stays on.
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["archive", "task", "evidence", "lease", "events"], "excluded": ["recovery"], "source": {"type": "test"}}, actor=self.user)
        with self.assertRaises(DomainError) as caught:
            self.service.continue_task("root", workflow=True)
        self.assertEqual("extension_not_authorized", caught.exception.code)
        # Direct (non-workflow) takeover reporting is unaffected by trimming.
        taken = self.service.acquire_lease("root", holder="worker-3", role="coordinator", takeover_reason="expired", actor=self.user)
        self.assertEqual("worker-3", taken["holder"]["id"])

    def test_archive_recovery_rejects_forged_operation_id(self):
        """The never-gated recovery branch still binds to the pending operation.

        A caller cannot fabricate an operation id to finish an archive that a
        different (or no) operation started, and cannot use the ungated branch
        to archive a tree that was never moved.
        """
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        confirmation = self.source("root")
        # Grant the archive member so the initial workflow archive is authorized.
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["archive"], "excluded": [], "source": {"type": "test"}}, actor=self.user)
        # Real interrupted archive under operation id "op-real".
        archived = self.service.archive("root", actor=self.user, confirmation=confirmation, operation_id="op-real", workflow=True)
        task = json.loads(Path(archived["path"], "task.json").read_text())
        task["archivedAt"] = None
        task["events"] = [e for e in task["events"] if e["type"] != "archived"]
        Path(archived["path"], "task.json").write_text(json.dumps(task))
        archived_task = self.store.read(archived["task"]["id"], archived=True)
        recover_confirmation = self.source(archived["task"]["id"], actor=dict(archived_task), archived=True)
        # A forged operation id must not complete someone else's pending archive.
        with self.assertRaises(DomainError) as caught:
            self.service.archive(archived["task"]["id"], actor=self.user, confirmation=recover_confirmation, operation_id="op-forged", workflow=True)
        self.assertEqual("archive_conflict", caught.exception.code)
        # The genuine operation id still recovers, even with a forged caller
        # confirmation, and the archived event keeps the ORIGINAL source.
        forged_caller = dict(recover_confirmation, source_id="forged", reference="forged")
        recovered = self.service.archive(archived["task"]["id"], actor=self.user, confirmation=forged_caller, operation_id="op-real", workflow=True)
        self.assertTrue(recovered["recovered"])
        archived_event = next(e for e in recovered["task"]["events"] if e["type"] == "archived")
        self.assertEqual(confirmation, archived_event["source"])
        # Idempotent: a second recovery adds no duplicate archived event.
        again = self.service.archive(archived["task"]["id"], actor=self.user, confirmation=forged_caller, operation_id="op-real", workflow=True)
        self.assertTrue(again["recovered"])
        self.assertEqual(1, sum(1 for e in again["task"]["events"] if e["type"] == "archived"))

    def test_trimmed_events_member_keeps_archive_recovery_and_event_integrity(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.check_record(lease)
        self.service.release_lease("root", token=lease["token"], reason="done")
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        confirmation = self.source("root")
        self._trim_bookkeeping_members()
        # The archive member stays included in this trim, so the real
        # workflow-gated archive proceeds.
        archived = self.service.archive("root", actor=self.user, confirmation=confirmation, operation_id="op-trim", workflow=True)
        self.assertTrue(Path(archived["path"]).is_dir())
        # Simulate an interrupted archive: the tree was moved but the
        # completed event never landed. Recovery must still work and must
        # carry the original confirmation even though events are trimmed.
        task = json.loads(Path(archived["path"], "task.json").read_text())
        task["archivedAt"] = None
        task["events"] = [e for e in task["events"] if e["type"] != "archived"]
        Path(archived["path"], "task.json").write_text(json.dumps(task))
        archived_task = self.store.read(archived["task"]["id"], archived=True)
        recover_confirmation = self.source(archived["task"]["id"], actor=dict(archived_task), archived=True)
        recovered = self.service.archive(archived["task"]["id"], actor=self.user, confirmation=recover_confirmation, operation_id="op-trim", workflow=True)
        self.assertTrue(recovered["recovered"])
        archived_event = next(e for e in recovered["task"]["events"] if e["type"] == "archived")
        self.assertEqual(confirmation, archived_event["source"])
        # A trim that also excludes archive blocks the workflow consumption
        # entry for a NEW archive but not the underlying recovery path. The
        # archived tree can no longer be enabled through the service, so this
        # trims the grant by a direct file edit (simulated external edit, as
        # elsewhere in fixtures).
        task = json.loads(Path(archived["path"], "task.json").read_text())
        task["archivedAt"] = None
        task["events"] = [e for e in task["events"] if e["type"] != "archived"]
        trim = next(e for e in task["extensions"] if e["id"] == "persistent-task")
        trim.update({"scope": "custom", "included": ["recovery", "task", "evidence", "lease", "events"], "excluded": ["archive"]})
        Path(archived["path"], "task.json").write_text(json.dumps(task))
        archived_task = self.store.read(archived["task"]["id"], archived=True)
        recover_confirmation = self.source(archived["task"]["id"], actor=dict(archived_task), archived=True)
        # Safety machinery first: even with `archive` trimmed, finishing the
        # interrupted original operation still succeeds (settled boundary —
        # recovery must never be stranded by a trim).
        recovered_trimmed = self.service.archive(archived["task"]["id"], actor=self.user, confirmation=recover_confirmation, operation_id="op-trim", workflow=True)
        self.assertTrue(recovered_trimmed["recovered"])
        # And the workflow consumption entry for a NEW archive is still denied
        # for a still-active tree: with `archive` trimmed, workflow mode must
        # reject a new archive before any operation starts. (The recovery
        # branch for an interrupted operation stays available above.)
        self.create("fresh-tree")
        self.start("fresh-tree")
        self.service.enable_extension("fresh-tree", authorization={"id": "persistent-task", "scope": "custom", "included": ["recovery", "task", "evidence", "lease", "events"], "excluded": ["archive"], "source": {"type": "test"}}, actor=self.user)
        with self.assertRaises(DomainError) as caught:
            self.service.archive("fresh-tree", actor=self.user, confirmation=self.source("fresh-tree"), workflow=True)
        self.assertEqual("extension_not_authorized", caught.exception.code)
        # The same task still archives through the independent entry.
        self.service.drop("fresh-tree", actor=self.user, confirmation=self.source("fresh-tree"), reason="r", disposition="keep")
        direct = TaskService(self.store, clock=self.clock)
        archived2 = direct.archive("fresh-tree", actor=self.user, confirmation=self.source("fresh-tree"))
        self.assertTrue(Path(archived2["path"]).is_dir())


class CliTests(CoreCase):
    def run_cli(self, *args, cwd=None):
        env = dict(os.environ)
        source_root = str(Path(__file__).parents[1] / "src")
        env["PYTHONPATH"] = source_root
        env["HOME"] = self.tmp.name
        env["PATH"] = ""
        return subprocess.run([sys.executable, "-m", "fstar", *args], cwd=cwd or self.project, env=env, text=True, capture_output=True)

    def test_cli_json_error_and_real_create(self):
        result = self.run_cli("--project", str(self.project), "--user-data-root", str(Path(self.tmp.name) / "u"), "--runtime-root", str(Path(self.tmp.name) / "r"), "--json", "task", "create", "CLI task", "--name", "cli")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("cli", json.loads(result.stdout)["task"]["name"])
        failure = self.run_cli("--project", str(self.project), "--json", "state", "show", "missing")
        self.assertEqual(2, failure.returncode)
        self.assertEqual("task_not_found", json.loads(failure.stderr)["error"]["code"])

    def test_cli_state_and_acceptance_json(self):
        self.create()
        self.start()
        runtime = str(Path(self.tmp.name) / "runtime")
        result = self.run_cli("--project", str(self.project), "--runtime-root", runtime, "--json", "state", "show", "root")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("in_progress", json.loads(result.stdout)["phase"])
        acceptance = self.run_cli("--project", str(self.project), "--runtime-root", runtime, "--json", "acceptance", "status", "root")
        self.assertEqual(0, acceptance.returncode, acceptance.stderr)
        self.assertFalse(json.loads(acceptance.stdout)["awaiting_acceptance"])

    def test_workflow_lifecycle_cli_reloads_grants(self):
        self.create()
        self.start()
        base = ("--project", str(self.project), "--runtime-root", str(self.store.runtime_root), "--user-data-root", str(self.store.user_home), "--json")
        def call(*args):
            return self.run_cli(*base, *args)
        def code(result):
            return json.loads(result.stderr)["error"]["code"]
        self.assertEqual("extension_not_authorized", code(call("continue", "root", "--workflow")))
        self.assertEqual("extension_not_authorized", code(call("dispatch", "orphan", "root", "--workflow")))
        self.assertEqual("extension_not_authorized", code(call("archive", "root", "--workflow", "--confirm-user", "--invocation", "test")))
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["archive"], "excluded": ["recovery"], "source": {"type": "test"}}, actor=self.user)
        self.assertEqual("extension_not_authorized", code(call("dispatch", "orphan", "root", "--workflow")))
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["recovery"], "excluded": ["archive"], "source": {"type": "test"}}, actor=self.user)
        self.assertEqual(0, call("continue", "root", "--workflow").returncode)
        before = self.store.read("root")
        report = call("dispatch", "orphan", "root", "--workflow")
        self.assertEqual(0, report.returncode, report.stderr)
        self.assertTrue(json.loads(report.stdout)["read_only"])
        self.assertEqual(before, self.store.read("root"))
        self.assertEqual("extension_not_authorized", code(call("archive", "root", "--workflow", "--confirm-user", "--invocation", "test")))
        self.service.disable_extension("root", extension_id="persistent-task", authorization={"type": "test"}, actor=self.user)
        self.assertEqual("extension_not_authorized", code(call("continue", "root", "--workflow")))
        self.assertEqual("extension_not_authorized", code(call("dispatch", "orphan", "root", "--workflow")))
        self.assertEqual(0, call("dispatch", "orphan", "root").returncode)
        self.assertEqual(0, call("continue", "root").returncode)

    def test_workflow_orphan_wrong_root_and_unsafe_ref_are_read_only(self):
        self.create()
        self.start()
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        runtime = Path(self.tmp.name) / "unused-runtime"
        base = ("--project", str(other), "--runtime-root", str(runtime), "--user-data-root", str(self.store.user_home), "--json")
        result = self.run_cli(*base, "dispatch", "orphan", "root", "--workflow")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((other / ".fstar").exists())
        self.assertFalse(runtime.exists())
        before = self.store.read("root")
        result = self.run_cli("--project", str(self.project), "--runtime-root", str(runtime), "--user-data-root", str(self.store.user_home), "--json", "dispatch", "orphan", "../outside", "--workflow")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.store.read("root"))
        self.assertFalse(runtime.exists())
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["recovery"], "excluded": [], "source": {"type": "test"}}, actor=self.user)
        before = self.store.read("root")
        result = self.run_cli("--project", str(self.project), "--runtime-root", str(runtime), "--user-data-root", str(self.store.user_home), "--json", "dispatch", "orphan", "root", "--workflow")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["read_only"])
        self.assertEqual(before, self.store.read("root"))
        self.assertFalse(runtime.exists())

    def test_cli_missing_target_is_actionable(self):
        result = self.run_cli("--project", str(self.project), "--json", "state", "show")
        self.assertEqual(2, result.returncode)
        self.assertEqual("task_required", json.loads(result.stderr)["error"]["code"])

    def test_cli_missing_project_readonly_does_not_create(self):
        other = Path(self.tmp.name) / "plain"
        other.mkdir()
        runtime = Path(self.tmp.name) / "runtime-plain"
        result = self.run_cli("--runtime-root", str(runtime), "--json", "task", "current", cwd=other)
        self.assertEqual(2, result.returncode)
        self.assertFalse((other / ".fstar").exists())
        self.assertFalse(runtime.exists())

    def test_extension_session_only_without_metadata(self):
        other = Path(self.tmp.name) / "plain"
        other.mkdir()
        result = self.run_cli("--json", "extension", "list", cwd=other)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("session_only", json.loads(result.stdout)["persistence"])
        self.assertFalse((other / ".fstar").exists())

    def test_optional_project_handler_runs_before_core_service(self):
        other = Path(self.tmp.name) / "fresh"
        other.mkdir()
        result = self.run_cli("--json", "init", str(other.resolve()), cwd=other)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(str(other.resolve()), payload["root"])
        self.assertEqual("1", (other / ".fstar" / ".schema-version").read_text().strip())


if __name__ == "__main__":
    unittest.main()
