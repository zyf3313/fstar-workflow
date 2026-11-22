"""S-4 acceptance-protocol kernel tests (K-1, K-2, K-3, K-6).

Covers:
- K-1: localized rework invalidation (shared by report_problem and
  continue --action rework), full-mode zero change, empty-scope rejection,
  and the audit fields on the rework_requested event.
- K-2: the final check is read-only (read_only declaration, no changed
  paths at harvest, fresh current delivery baseline; incremental checks
  unaffected; already-stored legacy evidence stays readable).
- K-3: rule acceptance citing criteria items, unknown-item rejection, and
  the unchanged no-rule / old-rule-file paths.
- K-6: the replan revisit list (plan/clarify/criteria plus legacy
  doc/prd.md and doc/design.md when those files actually exist).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fstar.dispatch import DispatchService, build_payload, build_result
from fstar.evidence import file_digest, validate_rework_scope
from fstar.models import DomainError
from fstar.store import TaskStore
from fstar.tasks import TaskService, _REVISIT_DOCS, _docs_to_revisit, source_snapshot


class Clock:
    def __init__(self, value="2026-11-20T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, minutes):
        moment = datetime.fromisoformat(self.value.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        self.value = moment.isoformat().replace("+00:00", "Z")


class ProtocolCase(unittest.TestCase):
    """Shared fixture: one initialized temp project, service, and helpers."""

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
        self.implementer = {"role": "implement", "id": "implementer", "session": "i1"}
        self.checker = {"role": "check", "id": "checker", "session": "c1"}
        self.other_checker = {"role": "check", "id": "checker-2", "session": "c2"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    # -- setup helpers -----------------------------------------------------

    def source(self, ref="root", source_type="command", actor=None):
        task = self.store.read(ref)
        return {"source_id": "source-" + str(uuid.uuid4())[:8], "type": source_type,
                "at": self.clock(), "actor": actor or self.user, "reference": "prompt:42",
                "quote": "同意" if source_type == "conversation" else "",
                "scope": "task", "validates": source_snapshot(task)}

    def create(self, name="root"):
        return self.service.create(name=name, title=name.title(), description="Deliver R-001",
                                   actor=self.agent, session_id="s1")

    def start(self, ref="root"):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref), session_id="s1")

    def prepare_artifacts(self):
        """prd (R-001), criteria (A-001/A-002) and a delivery file."""
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        (self.project / "criteria.md").write_text(
            "<!-- fstar:item:A-001:start -->\nalpha\n<!-- fstar:item:A-001:end -->\n"
            "<!-- fstar:item:A-002:start -->\nbeta\n<!-- fstar:item:A-002:end -->\n")
        (self.project / "src.py").write_text("value = 1\n")
        (self.project / "report.md").write_text("all passed\n")
        with self.store.transaction():
            task = self.store.read("root")
            task["meta"]["templates"] = {"artifact_map": {
                "doc/prd.md": {"R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->"}},
                "criteria.md": {
                    "A-001": {"start_marker": "<!-- fstar:item:A-001:start -->", "end_marker": "<!-- fstar:item:A-001:end -->"},
                    "A-002": {"start_marker": "<!-- fstar:item:A-002:start -->", "end_marker": "<!-- fstar:item:A-002:end -->"},
                },
            }}
            self.store.write(self.store.resolve("root"), task)

    def record_delivery(self, ref="root", paths=("src.py",), producer="implementer"):
        lease = self.service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.agent)
        recorded = self.service.evidence.record(ref, lease_token=lease["token"], evidence={
            "kind": "delivery", "producer": {"role": "implement", "id": producer, "session_id": "i1"},
            "validates": [], "delivery": self.service.evidence.delivery_snapshot(list(paths)),
            "validation_facts": []})
        self.service.release_lease(ref, token=lease["token"], reason="delivery recorded")
        return recorded

    def record_check(self, ref="root", *, scope="final", read_only=True, producer=None,
                     artifact="doc/prd.md", items=("R-001",), report=True):
        producer = producer or self.checker
        lease = self.service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot(ref, artifact=artifact, items=list(items))
        delivery = self.service.evidence.delivery_snapshot([])
        evidence = {
            "kind": "check", "producer": dict(producer),
            "validates": [snapshot], "run_id": "run-" + str(uuid.uuid4())[:6],
            "environment": {"python": sys.version.split()[0]},
            "delivery": delivery, "scope": scope,
            "items": [{"requirement_ids": list(items), "plan_item": "P-1", "test_refs": [],
                       "command": "python -m unittest", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 0.1, "retries": 0}],
        }
        if read_only is not None:
            evidence["read_only"] = read_only
        if report:
            evidence["report"] = {"path": "report.md", "sha256": file_digest(self.project / "report.md")}
        try:
            recorded = self.service.evidence.record(ref, lease_token=lease["token"], evidence=evidence)
        finally:
            self.service.release_lease(ref, token=lease["token"], reason="check recorded")
        return recorded

    def to_awaiting(self, ref="root"):
        self.start(ref)
        self.prepare_artifacts()
        self.record_check(ref)
        self.service.enter_awaiting_acceptance(ref, actor=self.coordinator)


class ReworkScopeCase(ProtocolCase):
    """K-1: rework invalidation by scope."""

    def _awaiting_with_two_checks_and_delivery(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_delivery()
        criteria_check = self.record_check(artifact="criteria.md", items=("A-001", "A-002"))
        prd_check = self.record_check(artifact="doc/prd.md", items=("R-001",), producer=self.other_checker)
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        return criteria_check, prd_check

    def test_localized_criteria_scope_invalidates_only_intersecting_evidence(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        task_before = self.store.read("root")
        delivery_id = next(e["id"] for e in task_before["evidence"] if e["kind"] == "delivery")
        reworked = self.service.report_problem(
            "root", actor=self.user, confirmation=self.source("root"),
            reason="A-001 wrong", scope={"mode": "localized", "criteria_refs": ["A-001"]})
        self.assertEqual("planning", reworked["phase"])
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[criteria_check["id"]]["state"])
        self.assertEqual("valid", by_id[prd_check["id"]]["state"])
        self.assertEqual("valid", by_id[delivery_id]["state"])
        event = next(e for e in reworked["events"] if e["type"] == "rework_requested")
        self.assertEqual({"mode": "localized", "artifacts": [], "paths": [], "criteria_refs": ["A-001"]},
                         event["data"]["scope"])
        self.assertIn(criteria_check["id"], event["data"]["invalidated_evidence_ids"])
        self.assertIn(prd_check["id"], event["data"]["retained_evidence_ids"])
        self.assertIn(delivery_id, event["data"]["retained_evidence_ids"])

    def test_localized_path_scope_invalidates_delivery_evidence(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        delivery_id = next(e["id"] for e in self.store.read("root")["evidence"] if e["kind"] == "delivery")
        reworked = self.service.continue_task(
            "root", action="rework", actor=self.user, confirmation=self.source("root"),
            reason="src.py broken", scope={"mode": "localized", "paths": ["src.py"]})
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[delivery_id]["state"])
        self.assertEqual("valid", by_id[criteria_check["id"]]["state"])
        self.assertEqual("valid", by_id[prd_check["id"]]["state"])

    def test_localized_artifact_scope_invalidates_artifact_checks(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        reworked = self.service.report_problem(
            "root", actor=self.user, confirmation=self.source("root"),
            reason="prd wording", scope={"mode": "localized", "artifacts": ["doc/prd.md"]})
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[prd_check["id"]]["state"])
        self.assertEqual("valid", by_id[criteria_check["id"]]["state"])

    def test_continue_rework_uses_the_same_localized_logic(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        reworked = self.service.continue_task(
            "root", action="rework", actor=self.user, confirmation=self.source("root"),
            reason="A-002 wrong", scope={"mode": "localized", "criteria_refs": ["A-002"]})
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("stale", by_id[criteria_check["id"]]["state"])
        self.assertEqual("valid", by_id[prd_check["id"]]["state"])
        event = next(e for e in reworked["events"] if e["type"] == "rework_requested")
        self.assertEqual(["A-002"], event["data"]["scope"]["criteria_refs"])
        self.assertEqual([criteria_check["id"]], event["data"]["invalidated_evidence_ids"])

    def test_localized_rework_cannot_be_closed_without_a_new_check(self):
        # Impact-check finding: a retained final check describes the delivery
        # BEFORE the rework, so it must not re-enable acceptance on its own.
        # The evidence stays valid and auditable; only the acceptance basis
        # is retired until a NEW final check is recorded.
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        reworked = self.service.report_problem(
            "root", actor=self.user, confirmation=self.source("root"),
            reason="A-002 wrong", scope={"mode": "localized", "criteria_refs": ["A-002"]})
        by_id = {item["id"]: item for item in reworked["evidence"]}
        self.assertEqual("valid", by_id[prd_check["id"]]["state"])
        status = self.service.evidence.acceptance_status("root")
        self.assertFalse(status["awaiting_acceptance"])
        self.assertEqual([], status["evidence_refs"])
        retired = [x for x in status["checks"] if x["retired_by_rework"]]
        self.assertEqual([prd_check["id"]], [x["id"] for x in retired])
        # The rework loop cannot be closed on the pre-rework check.
        self.service.start("root", actor=self.user, confirmation=self.source("root"), session_id="s1")
        with self.assertRaises(DomainError) as caught:
            self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        self.assertEqual("acceptance_blocked", caught.exception.code)
        # A fresh final check restores the acceptance basis.
        self.record_check(artifact="doc/prd.md", items=("R-001",), producer=self.other_checker)
        self.assertTrue(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])

    def test_default_rework_still_invalidates_everything(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        delivery_id = next(e["id"] for e in self.store.read("root")["evidence"] if e["kind"] == "delivery")
        reworked = self.service.report_problem("root", actor=self.user,
                                               confirmation=self.source("root"), reason="all wrong")
        by_id = {item["id"]: item for item in reworked["evidence"]}
        for evidence_id in (criteria_check["id"], prd_check["id"], delivery_id):
            self.assertEqual("stale", by_id[evidence_id]["state"])
            self.assertEqual([{"type": "rework_requested", "reason": "all wrong"}],
                             by_id[evidence_id]["stale_reasons"])
        event = next(e for e in reworked["events"] if e["type"] == "rework_requested")
        self.assertEqual("full", event["data"]["scope"]["mode"])
        self.assertEqual([], event["data"]["retained_evidence_ids"])

    def test_empty_localized_scope_is_rejected(self):
        self.create()
        self.to_awaiting()
        for scope in ({"mode": "localized"},
                      {"mode": "localized", "artifacts": [], "paths": [], "criteria_refs": []}):
            with self.assertRaises(DomainError) as caught:
                self.service.report_problem("root", actor=self.user,
                                            confirmation=self.source("root"),
                                            reason="empty scope", scope=scope)
            self.assertEqual("invalid_rework_scope", caught.exception.code)
        self.assertEqual("awaiting_acceptance", self.store.read("root")["phase"])

    def test_malformed_scope_is_rejected(self):
        self.create()
        self.to_awaiting()
        with self.assertRaises(DomainError) as caught:
            self.service.report_problem("root", actor=self.user, confirmation=self.source("root"),
                                        reason="bad", scope={"mode": "localized", "paths": "src.py"})
        self.assertEqual("invalid_rework_scope", caught.exception.code)
        with self.assertRaises(DomainError) as caught:
            self.service.continue_task("root", action="rework", actor=self.user,
                                       confirmation=self.source("root"), reason="bad",
                                       scope={"mode": "partial", "paths": ["src.py"]})
        self.assertEqual("invalid_rework_scope", caught.exception.code)

    def test_validate_rework_scope_normalizes_defaults(self):
        self.assertEqual({"mode": "full", "artifacts": [], "paths": [], "criteria_refs": []},
                         validate_rework_scope(None))
        self.assertEqual({"mode": "full", "artifacts": [], "paths": [], "criteria_refs": []},
                         validate_rework_scope({}))

    def test_cli_scope_file_on_accept_rework_and_continue_rework(self):
        criteria_check, prd_check = self._awaiting_with_two_checks_and_delivery()
        scope_path = Path(self.tmp.name) / "scope.json"
        scope_path.write_text(json.dumps({"mode": "localized", "criteria_refs": ["A-001"]}))

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--json", "--project", str(self.project),
                             "--user-data-root", str(self.user_root),
                             "--runtime-root", str(self.runtime)] + list(argv))
            return code, out.getvalue() + err.getvalue()

        from fstar.cli import main
        code, out = run("accept", "root", "--rework", "--confirm-user", "--invocation", "cli-rework",
                        "--reason", "A-001 wrong", "--scope-file", str(scope_path))
        self.assertEqual(0, code, out)
        task = self.store.read("root")
        by_id = {item["id"]: item for item in task["evidence"]}
        self.assertEqual("stale", by_id[criteria_check["id"]]["state"])
        self.assertEqual("valid", by_id[prd_check["id"]]["state"])
        event = next(e for e in task["events"] if e["type"] == "rework_requested")
        self.assertEqual(["A-001"], event["data"]["scope"]["criteria_refs"])

        # Rebuild and exercise the continue surface with the same file.
        self.service.start("root", actor=self.user, confirmation=self.source("root"), session_id="s1")
        self.record_check(artifact="criteria.md", items=("A-001",))
        self.service.enter_awaiting_acceptance("root", actor=self.coordinator)
        continue_scope = Path(self.tmp.name) / "scope2.json"
        continue_scope.write_text(json.dumps({"mode": "localized", "artifacts": ["criteria.md"]}))
        code, out = run("continue", "root", "--action", "rework", "--confirm-user",
                        "--invocation", "cli-continue", "--reason", "criteria wrong",
                        "--scope-file", str(continue_scope))
        self.assertEqual(0, code, out)
        task = self.store.read("root")
        event = [e for e in task["events"] if e["type"] == "rework_requested"][-1]
        self.assertEqual(["criteria.md"], event["data"]["scope"]["artifacts"])


class FinalCheckReadOnlyCase(ProtocolCase):
    """K-2: the final check is read-only."""

    def test_final_check_without_read_only_is_rejected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        with self.assertRaises(DomainError) as caught:
            self.record_check(read_only=None)
        self.assertEqual("invalid_check", caught.exception.code)
        self.assertEqual("A final check must declare read_only: true", caught.exception.message)

    def test_final_check_with_read_only_false_is_rejected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        with self.assertRaises(DomainError) as caught:
            self.record_check(read_only=False)
        self.assertEqual("invalid_check", caught.exception.code)

    def test_final_check_with_read_only_true_is_accepted(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        recorded = self.record_check(read_only=True)
        self.assertEqual("valid", recorded["state"])

    def test_incremental_check_is_not_constrained(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        recorded = self.record_check(scope="incremental", read_only=None)
        self.assertEqual("valid", recorded["state"])

    def test_harvest_rejects_a_final_check_that_changed_paths(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        dispatch = DispatchService(self.store, task_service=self.service)
        payload = build_payload(role="check", task_ref="root", plan_item_ids=["P-1"],
                                allowed_paths=["src.py"],
                                baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}})
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        check_evidence = {
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": "test"},
            "delivery": self.service.evidence.delivery_snapshot([]), "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "command": "check", "result": "passed"}],
        }
        result = build_result(dispatch_id=payload["dispatch_id"], role="check", status="done",
                              changed_paths=["src.py"])
        with self.assertRaises(DomainError) as caught:
            dispatch.harvest(result, payload, lease_token=lease["token"], check_evidence=check_evidence)
        self.assertEqual("final_check_not_read_only", caught.exception.code)

    def test_harvest_incremental_check_with_changes_is_not_rejected(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        dispatch = DispatchService(self.store, task_service=self.service)
        payload = build_payload(role="check", task_ref="root", plan_item_ids=["P-1"],
                                allowed_paths=["src.py"],
                                baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}})
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        check_evidence = {
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": "test"},
            "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "incremental",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "command": "check", "result": "passed"}],
        }
        result = build_result(dispatch_id=payload["dispatch_id"], role="check", status="done",
                              changed_paths=["src.py"])
        outcome = dispatch.harvest(result, payload, lease_token=lease["token"], check_evidence=check_evidence)
        self.assertTrue(outcome["recorded"])

    def _final_check_evidence(self):
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        return {
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": "test"},
            "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "command": "python -m unittest",
                       "result": "passed"}],
        }

    def test_stale_delivery_blocks_the_final_check(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_delivery()
        (self.project / "src.py").write_text("value = 2\n")
        with self.assertRaises(DomainError) as caught:
            self.record_check()
        self.assertEqual("final_check_stale_delivery", caught.exception.code)

    def test_fresh_delivery_allows_the_final_check(self):
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_delivery()
        recorded = self.record_check()
        self.assertEqual("valid", recorded["state"])

    def test_new_delivery_supersedes_an_old_stale_delivery(self):
        # A repair after a failed check must not be permanently blocked by
        # the superseded delivery snapshot: recording a NEW delivery makes
        # the current baseline fresh again.
        self.create()
        self.start()
        self.prepare_artifacts()
        self.record_delivery()
        (self.project / "src.py").write_text("value = 2\n")
        with self.assertRaises(DomainError) as caught:
            self.record_check()
        self.assertEqual("final_check_stale_delivery", caught.exception.code)
        self.record_delivery()
        recorded = self.record_check()
        self.assertEqual("valid", recorded["state"])

    def test_partial_re_delivery_clears_only_the_repaired_path(self):
        # The effective delivery baseline is per path: re-delivering the
        # repaired file clears that path, while a path nobody re-delivered
        # still reports its drift.
        self.create()
        self.start()
        self.prepare_artifacts()
        (self.project / "other.py").write_text("other = 1\n")
        self.record_delivery(paths=("src.py", "other.py"))
        (self.project / "src.py").write_text("value = 2\n")
        (self.project / "other.py").write_text("other = 2\n")
        with self.assertRaises(DomainError) as caught:
            self.record_check()
        self.assertEqual("final_check_stale_delivery", caught.exception.code)
        self.assertEqual(["other.py", "src.py"],
                         [r["path"] for r in caught.exception.details["stale_reasons"]])
        # Re-deliver only the repaired file: that path clears, the other
        # still blocks until it is re-delivered too.
        self.record_delivery(paths=("src.py",))
        with self.assertRaises(DomainError) as caught:
            self.record_check()
        self.assertEqual("final_check_stale_delivery", caught.exception.code)
        self.assertEqual(["other.py"], [r["path"] for r in caught.exception.details["stale_reasons"]])
        self.record_delivery(paths=("other.py",))
        recorded = self.record_check()
        self.assertEqual("valid", recorded["state"])

    def test_stored_legacy_final_check_without_read_only_stays_usable(self):
        # Compatibility: evidence stored by an older protocol (recorded
        # before the read-only gate existed) is not retroactively rejected.
        # The gate lives at record time only.
        self.create()
        self.to_awaiting()
        with self.store.transaction():
            task = self.store.read("root")
            legacy = dict(next(item for item in task["evidence"] if item["kind"] == "check"))
            legacy.pop("read_only", None)
            legacy["id"] = "legacy-check"
            task["evidence"][-1] = legacy
            self.store.write(self.store.resolve("root"), task)
        status = self.service.evidence.acceptance_status("root")
        self.assertTrue(status["awaiting_acceptance"])
        self.assertEqual(["legacy-check"], status["evidence_refs"])


class RuleAcceptanceCase(ProtocolCase):
    """K-3: rule acceptance citing criteria items."""

    def test_rule_acceptance_records_criteria_refs_report_and_scope(self):
        self.create()
        self.to_awaiting()
        rule = {"rule_ref": "~/.fstar/rules/self-acceptance.md", "quote": "同意自验收",
                "criteria_refs": ["A-001", "A-002"], "report": "checks/self-acceptance.md",
                "scope": "kernel acceptance protocol"}
        accepted = self.service.accept("root", actor=self.user,
                                       confirmation=self.source("root"), rule=rule)
        self.assertEqual("completed", accepted["phase"])
        self.assertEqual("~/.fstar/rules/self-acceptance.md", accepted["acceptance"]["rule_ref"])
        self.assertEqual(["A-001", "A-002"], accepted["acceptance"]["criteria_refs"])
        event = next(e for e in accepted["events"] if e["type"] == "accepted")
        cited = event["data"]["accepted_via_rule"]
        self.assertEqual(["A-001", "A-002"], cited["criteria_refs"])
        self.assertEqual("checks/self-acceptance.md", cited["report"])
        self.assertEqual("kernel acceptance protocol", cited["scope"])
        self.assertEqual("同意自验收", cited["quote"])

    def test_unknown_criteria_ref_is_rejected_and_listed(self):
        self.create()
        self.to_awaiting()
        rule = {"rule_ref": "rule.md", "quote": "ok", "criteria_refs": ["A-001", "A-999"]}
        with self.assertRaises(DomainError) as caught:
            self.service.accept("root", actor=self.user, confirmation=self.source("root"), rule=rule)
        self.assertEqual("invalid_acceptance_rule", caught.exception.code)
        self.assertEqual(["A-999"], caught.exception.details["unknown"])
        self.assertEqual("awaiting_acceptance", self.store.read("root")["phase"])

    def test_criteria_refs_must_be_a_non_empty_string_array(self):
        self.create()
        self.to_awaiting()
        for criteria_refs in ([], "A-001", [1], [""]):
            with self.assertRaises(DomainError) as caught:
                self.service.accept("root", actor=self.user, confirmation=self.source("root"),
                                    rule={"rule_ref": "rule.md", "quote": "ok",
                                          "criteria_refs": criteria_refs})
            self.assertEqual("invalid_acceptance_rule", caught.exception.code)

    def test_rule_still_requires_reference_and_quote(self):
        self.create()
        self.to_awaiting()
        for rule in ({"quote": "ok"}, {"rule_ref": "rule.md"}, {"rule_ref": " ", "quote": "ok"}):
            with self.assertRaises(DomainError) as caught:
                self.service.accept("root", actor=self.user, confirmation=self.source("root"), rule=rule)
            self.assertEqual("invalid_acceptance_rule", caught.exception.code)

    def test_old_style_rule_file_still_works(self):
        self.create()
        self.to_awaiting()
        accepted = self.service.accept("root", actor=self.user,
                                       confirmation=self.source("root"),
                                       rule={"rule_ref": "rule.md", "quote": "ok"})
        self.assertEqual("completed", accepted["phase"])
        cited = next(e for e in accepted["events"] if e["type"] == "accepted")["data"]["accepted_via_rule"]
        self.assertEqual({"rule_ref": "rule.md", "quote": "ok"}, cited)
        self.assertEqual([], accepted["acceptance"]["criteria_refs"])

    def test_unified_acceptance_records_the_rule_citation(self):
        self.create()
        self.to_awaiting()
        rule = {"rule_ref": "rule.md", "quote": "ok", "criteria_refs": ["A-001"]}
        done = self.service.accept_unified("root", actor=self.user,
                                           confirmation=self.source("root"), rule=rule)
        self.assertEqual(0, done["children"])
        task = self.store.read("root")
        self.assertEqual("completed", task["phase"])
        self.assertEqual("rule.md", task["acceptance"]["rule_ref"])
        self.assertEqual(["A-001"], task["acceptance"]["criteria_refs"])
        event = [e for e in task["events"] if e["type"] == "unified_acceptance"][-1]
        self.assertEqual(["A-001"], event["data"]["accepted_via_rule"]["criteria_refs"])

    def test_unified_acceptance_rejects_unknown_criteria_ref(self):
        self.create()
        self.to_awaiting()
        with self.assertRaises(DomainError) as caught:
            self.service.accept_unified("root", actor=self.user, confirmation=self.source("root"),
                                        rule={"rule_ref": "rule.md", "quote": "ok",
                                              "criteria_refs": ["A-404"]})
        self.assertEqual("invalid_acceptance_rule", caught.exception.code)
        self.assertEqual("awaiting_acceptance", self.store.read("root")["phase"])

    def test_no_rule_acceptance_path_is_unchanged(self):
        self.create()
        self.to_awaiting()
        accepted = self.service.accept("root", actor=self.user, confirmation=self.source("root"))
        event = next(e for e in accepted["events"] if e["type"] == "accepted")
        self.assertNotIn("accepted_via_rule", event["data"])
        self.assertNotIn("rule_ref", accepted["acceptance"])


class RevisitDocsCase(ProtocolCase):
    """K-6: the replan revisit list."""

    def test_revisit_list_keeps_current_and_legacy_documents(self):
        self.assertIn("plan.md", _REVISIT_DOCS)
        self.assertIn("clarify.md", _REVISIT_DOCS)
        self.assertIn("criteria.md", _REVISIT_DOCS)
        # Compatibility: old tasks can still carry the migrated doc files.
        self.assertIn("doc/prd.md", _REVISIT_DOCS)
        self.assertIn("doc/design.md", _REVISIT_DOCS)

    def test_docs_to_revisit_reports_only_existing_files(self):
        task_dir = Path(self.tmp.name) / "task"
        (task_dir / "doc").mkdir(parents=True)
        (task_dir / "plan.md").write_text("# plan\n")
        (task_dir / "criteria.md").write_text("# criteria\n")
        (task_dir / "doc" / "design.md").write_text("# design\n")
        self.assertEqual(["doc/design.md", "plan.md", "criteria.md"], _docs_to_revisit(task_dir))

    def test_replan_records_criteria_and_legacy_docs(self):
        self.create()
        self.start()
        task_dir = self.store.resolve("root")
        (task_dir / "doc").mkdir(exist_ok=True)
        (task_dir / "doc" / "design.md").write_text("# design\n")
        (task_dir / "plan.md").write_text("# plan\n")
        (task_dir / "criteria.md").write_text("# criteria\n")
        replanned = self.service.continue_task("root", action="replan", actor=self.user,
                                               confirmation=self.source("root"), reason="rework")
        self.assertEqual(["doc/design.md", "plan.md", "criteria.md"],
                         replanned["meta"]["replan"]["docs_to_revisit"])
        self.assertEqual("planning", replanned["phase"])


if __name__ == "__main__":
    unittest.main()
