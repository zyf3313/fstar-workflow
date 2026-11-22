"""P-003 regressions: the awaiting_acceptance phase, rework flow, reopen,
and unified cross-project acceptance (PRD R-004/R-005, design D-004/D-005).

Phase machine (valid and invalid transitions, expired final check, lease),
evidence staleness across the phase, parent-child unified acceptance
(fresh all -> one confirmation completes all; stale child / unavailable
child repo / tampered child evidence -> blocked with reason), archive
interactions, and restart/legacy compatibility. Two REAL temporary git
repositories drive the cross-project flow; only temporary user
roots/runtimes are used, never the real host configuration.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fstar.crossproject import (CROSS_LINKS_KEY, CrossProjectService,
                                project_identity)
from fstar.evidence import file_digest
from fstar.models import DomainError, PHASES, validate_task
from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


def _git(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Clock:
    def __init__(self, value="2026-11-20T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, minutes):
        moment = datetime.fromisoformat(self.value.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        self.value = moment.isoformat().replace("+00:00", "Z")


class AcceptancePhaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / ".fstar").mkdir()
        (self.project / ".fstar" / ".schema-version").write_text("1\n")
        self.user_root = root / "user"
        self.user_root.mkdir()
        self.runtime = root / "runtime"
        self.store = TaskStore(self.project, user_home=self.user_root, runtime_root=self.runtime)
        self.clock = Clock()
        self.service = TaskService(self.store, clock=self.clock)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.coordinator = {"role": "coordinator", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref, source_type="command", actor=None):
        task = self.store.read(ref)
        return {"source_id": "source-" + str(uuid.uuid4())[:8], "type": source_type,
                "at": self.clock(), "actor": actor or self.user, "reference": "prompt:42",
                "quote": "同意" if source_type == "conversation" else "",
                "scope": "task", "validates": source_snapshot(task)}

    def create(self, name="root", parent=None):
        return self.service.create(name=name, title=name.title(), description="Deliver R-001",
                                   actor=self.agent, parent=parent, session_id="s1")

    def start(self, ref="root"):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref), session_id="s1")

    def prepare_artifacts(self, ref="root"):
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        (self.project / "src.py").write_text("value = 1\n")
        (self.project / "report.md").write_text("all passed\n")
        with self.store.transaction():
            task = self.store.read(ref)
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {
                "R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}}}}
            self.store.write(self.store.resolve(ref), task)

    def record_final_check(self, ref="root", producer="checker"):
        lease = self.service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot(ref, artifact="doc/prd.md", items=["R-001"])
        delivery = self.service.evidence.delivery_snapshot(["src.py"])
        item = self.service.evidence.record(ref, lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": producer, "session_id": "check-1"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
            "delivery": delivery, "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["src.py"],
                       "command": "python src.py", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 1.0, "retries": 0}]})
        self.service.release_lease(ref, token=lease["token"], reason="check complete")
        return item

    # -- phase machine ------------------------------------------------------

    def test_phase_set_contains_awaiting_acceptance(self):
        self.assertEqual({"planning", "in_progress", "awaiting_acceptance", "completed"}, PHASES)

    def test_planning_cannot_enter_awaiting_directly(self):
        self.create()
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("phase_transition_forbidden", caught.exception.code)
        self.assertEqual("planning", self.store.read("root")["phase"])

    def test_in_progress_without_final_check_cannot_enter_awaiting(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("acceptance_blocked", caught.exception.code)
        self.assertEqual("in_progress", self.store.read("root")["phase"])

    def test_fresh_final_check_enters_awaiting_and_keeps_completedAt_empty(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        entered = self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("awaiting_acceptance", entered["phase"])
        self.assertIsNone(entered["completedAt"])
        self.assertIsNone(entered["acceptance"])
        self.assertTrue(any(e["type"] == "awaiting_acceptance" for e in entered["events"]))
        # The milestone event survives compaction.
        from fstar.tasks import MILESTONES
        self.assertIn("awaiting_acceptance", MILESTONES)

    def test_active_lease_blocks_entering_awaiting(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.acquire_lease("root", holder="writer", role="coordinator", actor=self.agent)
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("lease_conflict", caught.exception.code)

    def test_stale_final_check_cannot_enter_awaiting(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        # Delivery changes after the check: the final check is no longer fresh.
        (self.project / "src.py").write_text("value = 2\n")
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("acceptance_blocked", caught.exception.code)
        self.assertEqual("in_progress", self.store.read("root")["phase"])

    def test_entering_awaiting_twice_is_rejected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("phase_transition_forbidden", caught.exception.code)

    def test_start_is_blocked_in_awaiting_until_rework(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        with self.assertRaises(DomainError) as caught:
            self.start()
        self.assertEqual("start_blocked", caught.exception.code)

    def test_in_progress_task_cannot_be_accepted_without_the_phase(self):
        # The explicit transition is mandatory: a fresh final check alone does
        # not entitle accept() while the task is still in_progress.
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("acceptance_blocked", caught.exception.code)
        self.assertIn("awaiting_acceptance", caught.exception.message)

    def test_planning_direct_accept_rejected(self):
        self.create()
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_expired_final_check_cannot_complete(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        # The delivery file changes while the task sits in awaiting_acceptance:
        # the final check is stale; accept must refuse and completedAt stays empty.
        (self.project / "src.py").write_text("value = 99\n")
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("acceptance_blocked", caught.exception.code)
        task = self.store.read("root")
        self.assertEqual("awaiting_acceptance", task["phase"])
        self.assertIsNone(task["completedAt"])

    def test_awaiting_state_reports_effective_in_progress_when_stale(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        state = self.service.continue_task("root")
        self.assertEqual("awaiting_acceptance", state["phase"])
        self.assertEqual("awaiting_acceptance", state["effective_phase"])
        self.assertEqual("accept_or_rework", state["next"])
        (self.project / "src.py").write_text("value = 99\n")
        state = self.service.continue_task("root")
        self.assertEqual("awaiting_acceptance", state["phase"])
        # Read-only reporting surfaces the re-check need without writing it.
        self.assertEqual("in_progress", state["effective_phase"])

    def test_invalidation_demotes_awaiting_acceptance_to_in_progress(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        # The delivered file changed after the check: the evidence goes stale
        # and the task can no longer sit in awaiting_acceptance.
        (self.project / "src.py").write_text("value = 3\n")
        invalidated = self.service.evidence.invalidate("root", file="src.py", actor=self.agent)
        self.assertTrue(invalidated["invalidated"])
        task = self.store.read("root")
        self.assertEqual("in_progress", task["phase"])
        self.assertIsNone(task["completedAt"])
        # Acceptance is refused again until a fresh check re-enters the phase.
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_awaiting_phase_survives_across_restart(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        restarted = TaskService(TaskStore(self.project, user_home=self.user_root,
                                          runtime_root=self.runtime), clock=self.clock)
        self.assertEqual("awaiting_acceptance", restarted.state("root")["phase"])
        accepted = restarted.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("completed", accepted["phase"])

    # -- rework flow --------------------------------------------------------

    def test_user_rework_returns_to_planning_and_stales_evidence(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        check = self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        reworked = self.service.report_problem("root", actor=self.user,
                                               confirmation=self.source("root"), reason="button broken")
        self.assertEqual("planning", reworked["phase"])
        self.assertIsNone(reworked["completedAt"])
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[check["id"]]["state"])
        self.assertEqual([{"type": "rework_requested", "reason": "button broken"}],
                         by_id[check["id"]]["stale_reasons"])
        event = next(e for e in reworked["events"] if e["type"] == "rework_requested")
        self.assertEqual("button broken", event["data"]["reason"])
        # The full cycle re-applies: start -> fresh check -> awaiting -> accept.
        self.start()
        self.prepare_artifacts()
        fresh = self.record_final_check(producer="checker-2")
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        accepted = self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("completed", accepted["phase"])
        self.assertIn(fresh["id"], accepted["acceptance"]["evidence_refs"])

    def test_agent_cannot_report_rework(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        with self.assertRaises(DomainError) as caught:
            self.service.report_problem("root", actor=self.agent,
                                        confirmation=self.source("root"), reason="agent rework")
        self.assertEqual("rework_forbidden", caught.exception.code)
        self.assertEqual("awaiting_acceptance", self.store.read("root")["phase"])

    def test_continue_rework_action_returns_to_planning(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        check = self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        reworked = self.service.continue_task("root", action="rework", actor=self.user,
                                              confirmation=self.source("root"), reason="wrong result")
        self.assertEqual("planning", reworked["phase"])
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[check["id"]]["state"])
        self.assertEqual([{"type": "rework_requested", "reason": "wrong result"}],
                         by_id[check["id"]]["stale_reasons"])

    def test_cli_awaiting_rework_and_unified_surface(self):
        import contextlib
        import io
        from fstar.cli import main

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--json", "--project", str(self.project),
                             "--user-data-root", str(self.user_root),
                             "--runtime-root", str(self.runtime)] + list(argv))
            return code, out.getvalue() + err.getvalue()

        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        code, out = run("--actor-role", "coordinator", "--actor", "coordinator",
                        "accept", "root", "--awaiting")
        self.assertEqual(0, code, out)
        self.assertIn("awaiting_acceptance", out)
        # The rework path needs the user's own confirmation.
        code, out = run("accept", "root", "--rework", "--reason", "not good")
        self.assertNotEqual(0, code)
        self.assertIn("confirmation_required", out)
        code, out = run("accept", "root", "--rework", "--confirm-user",
                         "--invocation", "cli-rework", "--reason", "not good")
        self.assertEqual(0, code, out)
        self.assertIn("planning", out)

    def test_stale_check_can_be_sent_back_for_a_fresh_check(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        # The delivered file changed after the check: the phase can no longer
        # be completed and the coordinator asks for a fresh check.
        (self.project / "src.py").write_text("value = 42\n")
        rechecked = self.service.request_recheck("root", actor=self.coordinator, reason="delivery changed")
        self.assertEqual("in_progress", rechecked["phase"])
        self.assertTrue(any(e["type"] == "recheck_requested" for e in rechecked["events"]))
        # A still-fresh check must not be thrown away.
        self.prepare_artifacts()
        self.record_final_check(producer="checker-2")
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        with self.assertRaises(DomainError) as caught:
            self.service.request_recheck("root", actor=self.coordinator, reason="unnecessary")
        self.assertEqual("recheck_forbidden", caught.exception.code)

    def test_phase_transition_events_survive_event_compaction(self):
        # The "correction events compacted away" defect class: a phase
        # transition event that is not a milestone would be silently folded
        # into the summary and lost.
        from fstar.tasks import MILESTONES, compact_events, make_event
        for event_type in ("awaiting_acceptance", "rework_requested", "recheck_requested",
                           "reopened", "unified_acceptance"):
            self.assertIn(event_type, MILESTONES)
        events = []
        source = {"source_id": "s", "type": "system", "at": "2026-11-20T10:00:00Z",
                  "actor": {"role": "agent", "id": "coordinator"}, "reference": "r",
                  "quote": "", "scope": "r", "validates": ""}
        for index in range(260):
            events.append(make_event("noise_%d" % index, source, {"i": index}, "2026-11-20T10:00:00Z"))
        events.append(make_event("awaiting_acceptance", source, {}, "2026-11-20T10:00:00Z"))
        events.append(make_event("rework_requested", source, {}, "2026-11-20T10:00:00Z"))
        events.append(make_event("unified_acceptance", source, {}, "2026-11-20T10:00:00Z"))
        compacted = compact_events(events)
        types = [event["type"] for event in compacted]
        self.assertIn("awaiting_acceptance", types)
        self.assertIn("rework_requested", types)
        self.assertIn("unified_acceptance", types)

    def test_rework_only_in_awaiting(self):
        self.create()
        self.start()
        with self.assertRaises(DomainError) as caught:
            self.service.report_problem("root", actor=self.user,
                                        confirmation=self.source("root"), reason="not waiting")
        self.assertEqual("rework_forbidden", caught.exception.code)

    # -- reopen / archive --------------------------------------------------

    def test_reopen_completed_goes_to_planning(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        reopened = self.service.continue_task("root", action="reopen", actor=self.user,
                                              confirmation=self.source("root"), reason="defect found")
        self.assertEqual("planning", reopened["phase"])
        self.assertIsNone(reopened["completedAt"])
        self.assertEqual("historical", reopened["acceptance"]["state"])

    def test_reopen_stales_final_check_evidence(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        check = self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        reopened = self.service.continue_task("root", action="reopen", actor=self.user,
                                              confirmation=self.source("root"), reason="defect found")
        by_id = {item["id"]: item for item in reopened["evidence"]}
        self.assertEqual("stale", by_id[check["id"]]["state"])
        self.assertEqual([{"type": "reopened", "reason": "defect found"}],
                         by_id[check["id"]]["stale_reasons"])

    def test_archived_task_cannot_be_reopened(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        self.service.archive("root", actor=self.user, confirmation=self.source("root"))
        # An archived task is immutable: reopen is refused.
        with self.assertRaises(DomainError) as caught:
            self.service.continue_task(self.store.read("root", archived=True)["id"],
                                       action="reopen", actor=self.user,
                                       confirmation=self.source("root"), reason="no")
        self.assertIn(caught.exception.code, {"reopen_forbidden", "task_not_found"})

    def test_awaiting_task_is_not_archivable(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_final_check()
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        with self.assertRaises(DomainError) as caught:
            self.service.archive("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("archive_blocked", caught.exception.code)

    # -- legacy / compatibility --------------------------------------------

    def test_legacy_task_json_still_validates(self):
        self.create()
        # A task written by an older writer has one of the old three phases;
        # all remain readable and no destructive migration happens.
        for phase in ("planning", "in_progress", "completed", "awaiting_acceptance"):
            with self.store.transaction():
                task = self.store.read("root")
                task["phase"] = phase
                self.store.write(self.store.resolve("root"), task)
            validate_task(self.store.read("root"))
        # An unknown phase is still rejected (forward-compat rule: refuse
        # transitions rather than crash, and the reader validates).
        with self.assertRaises(DomainError):
            validate_task({"phase": "drafting", **{k: v for k, v in self.store.read("root").items() if k != "phase"}})


class UnifiedAcceptanceCase(unittest.TestCase):
    """Cross-project unified acceptance over two REAL temporary git repos."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.user_root = (self.base / "user" / ".fstar").resolve()
        self.user_root.mkdir(parents=True)
        self.runtime = self.base / "runtime"
        self.actor = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.coordinator = {"role": "coordinator", "id": "coordinator", "session": "s1"}
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

    def _source(self, task, service=None):
        return {"source_id": "s-%s" % str(uuid.uuid4())[:8], "type": "command",
                "at": "2026-11-20T10:00:00Z", "actor": self.user,
                "reference": "prompt:1", "quote": "同意", "scope": "task",
                "validates": source_snapshot(task)}

    def _prepare(self, repo, service, ref):
        (repo / "doc").mkdir(exist_ok=True)
        (repo / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        (repo / "src.py").write_text("value = 1\n")
        (repo / "report.md").write_text("ok\n")
        with service.store.transaction():
            task = service.store.read(ref)
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {
                "R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}}}}
            service.store.write(service.store.resolve(ref), task)

    def _run_to_awaiting(self, repo, service, ref):
        service.start(ref, actor=self.user, confirmation=self._source(service.store.read(ref)),
                      session_id="s1")
        self._prepare(repo, service, ref)
        lease = service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.actor)
        snapshot = service.evidence.snapshot(ref, artifact="doc/prd.md", items=["R-001"])
        delivery = service.evidence.delivery_snapshot(["src.py"])
        service.evidence.record(ref, lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run", "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(repo / "report.md")},
            "delivery": delivery, "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["src.py"],
                       "command": "python src.py", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 0.1, "retries": 0}]})
        service.release_lease(ref, token=lease["token"], reason="done")
        service.enter_awaiting_acceptance(ref, actor=self.coordinator)

    def _linked_pair(self):
        master, target = self._repo("master"), self._repo("target")
        mstore, mservice = self._service(master)
        mservice.create(name="root", title="Master", description="d",
                        actor=self.actor, session_id="s1")
        cross = CrossProjectService(mstore, task_service=mservice)
        cross.create_child("root", target=str(target), name="child-a",
                           title="Child A", actor=self.actor)
        return master, target, mstore, mservice

    def test_unified_acceptance_completes_master_and_children(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        confirmation = self._source(mstore.read("root"))
        result = mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual(1, result["children"])
        completed_ids = {item["task_id"] for item in result["completed"]}
        self.assertEqual({mstore.read("root")["id"], tstore.read("child-a")["id"]}, completed_ids)
        master_task = mstore.read("root")
        child_task = tstore.read("child-a")
        self.assertEqual("completed", master_task["phase"])
        self.assertEqual("completed", child_task["phase"])
        self.assertTrue(master_task["completedAt"])
        self.assertTrue(child_task["completedAt"])
        # Each child acceptance event cites the master's unified confirmation.
        child_event = next(e for e in child_task["events"] if e["type"] == "unified_acceptance")
        self.assertEqual("unified-acceptance child of %s" % master_task["id"],
                         child_event["source"]["scope"])
        self.assertIn("unified acceptance", child_event["source"]["reference"])
        master_event = next(e for e in master_task["events"] if e["type"] == "unified_acceptance")
        self.assertEqual(confirmation["source_id"], master_event["source"]["source_id"])
        # The acceptance records bind each task's snapshot taken at completion
        # time (pre-`phase="completed"` in _complete_one, matching plain
        # accept()); the acceptance event is recorded on the written task.
        self.assertEqual(source_snapshot({**child_task, "phase": "awaiting_acceptance"}),
                         child_task["acceptance"]["validates"]["task"])
        self.assertEqual(source_snapshot({**master_task, "phase": "awaiting_acceptance"}),
                         master_task["acceptance"]["validates"]["task"])

    def test_unified_acceptance_agent_rejected(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        confirmation = self._source(mstore.read("root"))
        confirmation["actor"] = self.actor
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.actor, confirmation=confirmation)
        self.assertEqual("acceptance_forbidden", caught.exception.code)

    def test_unified_acceptance_blocked_when_child_not_awaiting(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tservice = self._service(target)[1]
        tservice.start("child-a", actor=self.user,
                       confirmation=self._source(tservice.store.read("child-a")), session_id="s1")
        confirmation = self._source(mstore.read("root"))
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("unified_child_not_ready", caught.exception.code)
        self.assertEqual("child_not_awaiting_acceptance", caught.exception.details["reason"])
        # Partial failure never fakes success: both sides stay unchanged.
        self.assertEqual("awaiting_acceptance", mstore.read("root")["phase"])
        self.assertEqual("in_progress", self._store(target).read("child-a")["phase"])
        self.assertIsNone(mstore.read("root")["completedAt"])

    def test_unified_acceptance_blocked_when_child_check_stale(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        # Tamper with the child delivery AFTER the final check.
        (target / "src.py").write_text("value = tampered\n")
        confirmation = self._source(mstore.read("root"))
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("unified_child_not_ready", caught.exception.code)
        self.assertEqual("child_check_stale", caught.exception.details["reason"])
        self.assertEqual("awaiting_acceptance", mstore.read("root")["phase"])
        self.assertEqual("awaiting_acceptance", tstore.read("child-a")["phase"])

    def test_unified_acceptance_blocked_when_child_repo_unavailable(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        import shutil
        shutil.rmtree(target)
        confirmation = self._source(mstore.read("root"))
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("unified_child_not_ready", caught.exception.code)
        self.assertEqual("child_project_unavailable", caught.exception.details["reason"])
        self.assertEqual("awaiting_acceptance", mstore.read("root")["phase"])

    def test_unified_acceptance_rejects_stale_confirmation(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        old_confirmation = self._source(mstore.read("root"))
        # The master delivery changes after the confirmation was taken: the
        # confirmation no longer binds the current version and cannot be
        # reused for the new delivery.
        (master / "src.py").write_text("value = new delivery\n")
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=old_confirmation)
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_unified_acceptance_requires_master_awaiting(self):
        master, target, mstore, mservice = self._linked_pair()
        # Master still in_progress with a fresh check but no phase transition.
        mservice.start("root", actor=self.user, confirmation=self._source(mstore.read("root")), session_id="s1")
        self._prepare(master, mservice, "root")
        lease = mservice.acquire_lease("root", holder="c", role="coordinator", actor=self.actor)
        snapshot = mservice.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        delivery = mservice.evidence.delivery_snapshot(["src.py"])
        mservice.evidence.record("root", lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run", "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(master / "report.md")},
            "delivery": delivery, "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [],
                       "command": "python src.py", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 0.1, "retries": 0}]})
        mservice.release_lease("root", token=lease["token"], reason="done")
        tservice = self._service(target)[1]
        self._run_to_awaiting(target, tservice, "child-a")
        confirmation = self._source(mstore.read("root"))
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_plain_accept_ignores_cross_project_links(self):
        # A master with cross-project links uses the UNIFIED path; the plain
        # accept path does not silently include or exclude linked children
        # (it simply completes the master after its own gates, per single-
        # project semantics; cross-project coordination is explicit).
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore = self._store(target)
        accepted = mservice.accept("root", actor=self.user,
                                    confirmation=self._source(mstore.read("root")))
        self.assertEqual("completed", accepted["phase"])
        # The child was NOT completed by the master's own acceptance.
        self.assertEqual("planning", tstore.read("child-a")["phase"])

    def test_unified_acceptance_retry_is_idempotent(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        confirmation = self._source(mstore.read("root"))
        mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        # A replay of the same confirmation against the now-completed master is
        # refused (stale snapshot), never a double completion.
        with self.assertRaises(DomainError) as caught:
            mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("acceptance_blocked", caught.exception.code)

    def test_unified_acceptance_recovers_after_a_partial_write(self):
        master, target, mstore, mservice = self._linked_pair()
        self._run_to_awaiting(master, mservice, "root")
        tstore, tservice = self._service(target)
        self._run_to_awaiting(target, tservice, "child-a")
        confirmation = self._source(mstore.read("root"))
        # The child write fails once: the master must stay in
        # awaiting_acceptance so the same confirmation can be retried.
        from fstar.store import TaskStore as RealStore
        original_write = RealStore.write
        state = {"failed": False}

        def failing_write(store, task_dir, data, **kwargs):
            if store.project_root == target and not state["failed"]:
                state["failed"] = True
                raise OSError("simulated child write failure")
            return original_write(store, task_dir, data, **kwargs)

        RealStore.write = failing_write
        try:
            with self.assertRaises(OSError):
                mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        finally:
            RealStore.write = original_write
        self.assertEqual("awaiting_acceptance", mstore.read("root")["phase"])
        self.assertIsNone(mstore.read("root")["completedAt"])
        # The retry completes the remaining pieces; the master is done too.
        result = mservice.accept_unified("root", actor=self.user, confirmation=confirmation)
        self.assertEqual("completed", mstore.read("root")["phase"])
        self.assertEqual("completed", tstore.read("child-a")["phase"])
        self.assertEqual(2, len(result["completed"]))


class PromptStatePhaseCase(unittest.TestCase):
    """The read-only hooks map the new phase correctly and never write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / ".fstar").mkdir()
        (self.project / ".fstar" / ".schema-version").write_text("1\n")
        self.store = TaskStore(self.project, user_home=root / "user", runtime_root=root / "runtime")
        self.service = TaskService(self.store)
        self.user_root = root / "user"

    def test_prompt_state_for_awaiting_acceptance_phase(self):
        from fstar.runtime import hooks
        actor = {"role": "user", "id": "user", "session": "s1"}
        self.service.create(name="root", title="R", description="", actor=actor, session_id="s1")
        with self.store.transaction():
            task = self.store.read("root")
            task["phase"] = "awaiting_acceptance"
            self.store.write(self.store.resolve("root"), task)
        before = self.store.read("root")
        result = hooks.prompt_context({"session_id": "s1"}, start=self.project,
                                      user_root=self.user_root,
                                      runtime_root=Path(self.tmp.name) / "runtime",
                                      clock=lambda: "2026-11-20T10:00:00Z")
        self.assertEqual("awaiting_acceptance", result["state"])
        # The hook only described; no task state changed.
        self.assertEqual(before, self.store.read("root"))

    def test_session_context_describes_phase_without_writing(self):
        from fstar.runtime import hooks
        actor = {"role": "user", "id": "user", "session": "s1"}
        self.service.create(name="root", title="R", description="", actor=actor, session_id="s1")
        with self.store.transaction():
            task = self.store.read("root")
            task["phase"] = "awaiting_acceptance"
            self.store.write(self.store.resolve("root"), task)
        before = self.store.read("root")
        hooks.session_context({"session_id": "s1"}, start=self.project,
                              user_root=self.user_root,
                              runtime_root=Path(self.tmp.name) / "runtime",
                              clock=lambda: "2026-11-20T10:00:00Z")
        self.assertEqual(before, self.store.read("root"))


if __name__ == "__main__":
    unittest.main()
