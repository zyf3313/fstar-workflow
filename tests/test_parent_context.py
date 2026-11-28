"""antigravity-adoption P-003: dispatch parent context inheritance (A-002).

Covers the origin-parent injection in worker_context (auto channel), the
prepare_read_context dual channel, the honest tri-state report
(loaded/partial/missing), budget deferral, and the compatibility guarantee
that tasks without origin never touch the injection path (A-006).
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fstar.dispatch import DispatchService, build_payload, build_result, prepare_read_context
from fstar.models import DomainError
from fstar.runtime import hooks, inject
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


class Clock:
    def __init__(self, value="2026-11-28T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, minutes):
        moment = datetime.fromisoformat(self.value.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        self.value = moment.isoformat().replace("+00:00", "Z")


class ParentCase(unittest.TestCase):
    def setUp(self):
        import tempfile
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
        self.dispatch = DispatchService(self.store, clock=self.clock, task_service=self.service)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref, archived=False):
        task = self.store.read(ref, archived=archived)
        return {"source_id": "s-" + task["id"], "type": "command", "at": self.clock(),
                "actor": self.user, "reference": "prompt:1", "quote": "", "scope": "task",
                "validates": source_snapshot(task)}

    def archived_parent(self, name="root", *, docs=True):
        """Drive one task through completed + archive; return its id/identity."""
        self.service.create(name=name, title=name.title(), description="D", actor=self.agent)
        parent_dir = self.store.tasks_root / name
        if docs:
            (parent_dir / "doc").mkdir(parents=True, exist_ok=True)
            (parent_dir / "doc" / "design.md").write_text("# Parent design\n\nSettled decisions.\n")
            (parent_dir / "doc" / "walkthrough.md").write_text("# Parent walkthrough\n\nWhat changed and how verified.\n")
        self.service.start(name, actor=self.user, confirmation=self.source(name))
        lease = self.service.acquire_lease(name, holder="c", role="coordinator", actor=self.agent)
        (self.project / "src.py").write_text("<!-- R-001:start -->\nvalue = 1\n<!-- R-001:end -->\n")
        with self.store.transaction():
            task = self.store.read(name)
            task["meta"]["templates"] = {"artifact_map": {"src.py": {"R-001": {
                "start_marker": "<!-- R-001:start -->", "end_marker": "<!-- R-001:end -->"}}}}
            self.store.write(self.store.resolve(name), task)
        snapshot = self.service.evidence.snapshot(name, artifact="src.py", items=["R-001"])
        delivery = self.service.evidence.delivery_snapshot(["src.py"])
        self.service.evidence.record(name, lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": sys.version.split()[0]},
            "report": None, "delivery": delivery,
            "scope": "final", "read_only": True, "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1",
                                                            "test_refs": [], "command": "true", "result": "passed",
                                                            "exit_code": 0, "log_refs": [], "duration": 1.0, "retries": 0}]})
        self.service.release_lease(name, token=lease["token"], reason="check done")
        self.service.enter_awaiting_acceptance(name, actor=self.agent)
        self.service.accept(name, actor=self.user, confirmation=self.source(name))
        parent = self.store.read(name)
        self.service.archive(name, actor=self.user, confirmation=self.source(name))
        identity = self.store.identity_path(self.store.resolve(name, archived=True))
        return parent["id"], identity

    def followup(self, task_id, identity, name="fix-1"):
        self.service.create(name=name, title="Fix", description="D", actor=self.agent,
                            origin={"task_id": task_id, "archive_path": identity, "reason": "followup fix"})
        self.service.start(name, actor=self.user, confirmation=self.source(name))
        return name

    def worker(self, role="implement", task_ref="fix-1", **kwargs):
        return hooks.worker_context({}, role=role, task_ref=task_ref, start=self.project,
                                    user_root=self.store.user_home, runtime_root=self.store.runtime_root,
                                    clock=self.clock, **kwargs)


class WorkerInjectionTests(ParentCase):
    def test_parent_docs_fully_loaded(self):
        parent_id, identity = self.archived_parent()
        self.followup(parent_id, identity)
        result = self.worker(as_json=True)
        kinds = [item["kind"] for item in result["loaded"]]
        self.assertIn("parent_design", kinds)
        self.assertIn("parent_walkthrough", kinds)
        body = "\n".join(item["text"] for item in result["loaded"])
        self.assertIn("# Parent design", body)
        self.assertIn("# Parent walkthrough", body)
        report = result["task_summary"]["parent_context"]
        self.assertEqual("loaded", report["status"])
        self.assertEqual([sorted({"kind", "path", "sha256"}) for _ in report["loaded"]],
                         [sorted(e) for e in report["loaded"]])
        self.assertEqual(sorted(["parent_design", "parent_walkthrough"]),
                         sorted(entry["kind"] for entry in report["loaded"]))
        self.assertEqual([], report["deferred"])
        self.assertEqual(parent_id, report["origin"]["task_id"])
        self.assertIn("Parent context loaded from", result["footer"])

    def test_parent_resolved_by_id_after_unarchive(self):
        parent_id, identity = self.archived_parent()
        self.followup(parent_id, identity)
        self.service.unarchive("root", actor=self.user, confirmation=self.source("root", archived=True))
        result = self.worker(as_json=True)
        self.assertIn("parent_design", [item["kind"] for item in result["loaded"]])
        self.assertEqual("loaded", result["task_summary"]["parent_context"]["status"])

    def test_missing_parent_degrades_honestly(self):
        parent_id, identity = self.archived_parent(docs=False)
        self.followup(parent_id, identity)
        # remove the parent from both trees: path and id scan both miss
        import shutil
        shutil.rmtree(self.store.resolve("fix-1").parent.parent / "archive")
        result = self.worker(as_json=True)
        report = result["task_summary"]["parent_context"]
        self.assertEqual("missing", report["status"])
        self.assertTrue(report["reason"])
        self.assertEqual([], report["loaded"])
        self.assertIn("Parent context unavailable", result["footer"])
        # dispatch itself is not blocked (A-002: degrade, do not fail)
        self.assertEqual("implement", result["role"])

    def test_parent_dir_without_docs_reports_missing(self):
        parent_id, identity = self.archived_parent(docs=False)
        self.followup(parent_id, identity)
        result = self.worker(as_json=True)
        report = result["task_summary"]["parent_context"]
        self.assertEqual("missing", report["status"])
        self.assertIn("no parent documents", report["reason"])
        self.assertEqual([], report["loaded"])

    def test_over_budget_parent_doc_deferred_partial(self):
        parent_id, identity = self.archived_parent()
        # oversized walkthrough, small design
        big = "x" * 300000
        (self.store.resolve("root", archived=True) / "doc" / "walkthrough.md").write_text(big)
        self.followup(parent_id, identity)
        from unittest import mock
        with mock.patch.object(inject, "read_budgets",
                               return_value={"max_file_bytes": 262144, "max_artifact_bytes": 262144,
                                             "max_total_bytes": 2097152}):
            result = self.worker(as_json=True)
        report = result["task_summary"]["parent_context"]
        self.assertEqual("partial", report["status"])
        deferred_kinds = sorted(entry["kind"] for entry in report["deferred"])
        self.assertEqual(["parent_walkthrough"], deferred_kinds)
        self.assertIn("exceeds_file_budget", [e["reason"] for e in report["deferred"]])
        self.assertIn("parent_design", [item["kind"] for item in result["loaded"]])
        self.assertIn("Parent context partial", result["footer"])
        # never silently truncated: the big body is not in the loaded text
        body = "\n".join(item["text"] for item in result["loaded"])
        self.assertNotIn(big[:1000], body)

    def test_no_origin_task_injection_path_untouched(self):
        # A-006 compatibility: no origin -> no parent_context key at all
        self.service.create(name="plain", title="P", description="D", actor=self.agent)
        self.service.start("plain", actor=self.user, confirmation=self.source("plain"))
        result = self.worker(task_ref="plain", as_json=True)
        self.assertNotIn("parent_context", result["task_summary"])
        self.assertNotIn("Parent context", result["footer"])
        self.assertNotIn("parent_", json.dumps([item["kind"] for item in result["loaded"]]))


class DualChannelTests(ParentCase):
    def test_prepare_read_context_reports_parent(self):
        parent_id, identity = self.archived_parent()
        self.followup(parent_id, identity)
        (self.project / "guide.md").write_text("guide\n")
        selected = prepare_read_context(self.store, {"selection_reason": "r", "entries": [
            {"root": "project", "path": "guide.md"}]}, task_ref="fix-1")
        report = selected["context_report"]["parent_context"]
        self.assertEqual("loaded", report["status"])
        self.assertEqual(parent_id, report["origin"]["task_id"])

    def test_prepare_read_context_without_task_ref_has_no_parent(self):
        selected = prepare_read_context(self.store, {"selection_reason": "r", "entries": []})
        self.assertNotIn("parent_context", selected["context_report"])

    def test_parent_context_survives_payload_validation_and_harvest(self):
        parent_id, identity = self.archived_parent()
        self.followup(parent_id, identity)
        (self.project / "src.py").write_text("v = 1\n")
        (self.store.resolve("fix-1") / "implement.jsonl").write_text(
            json.dumps({"file": "src.py", "reason": "scope"}) + "\n")
        selected = prepare_read_context(self.store, {"selection_reason": "r", "entries": []}, task_ref="fix-1")
        payload = build_payload(role="implement", task_ref="fix-1", plan_item_ids=["P-1"],
                                allowed_paths=["src.py"],
                                baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
                                read_context=selected["read_context"],
                                context_report=selected["context_report"])
        registration = self.dispatch.register(payload)
        result = build_result(dispatch_id=payload["dispatch_id"], role="implement", status="done",
                              changed_paths=[])
        outcome = self.dispatch.harvest(result, registration["payload"],
                                        lease_token=registration["lease_token"])
        self.assertTrue(outcome["recorded"])
        evidence = self.store.read("fix-1")["evidence"][-1]
        facts = [f["command"] for f in evidence.get("validation_facts", [])]
        self.assertIn("parent context inheritance (origin-resolved, hook-reported)", facts)
        recorded = [f for f in evidence["validation_facts"]
                    if f["command"].startswith("parent context inheritance")][0]["result"]
        self.assertEqual("loaded", json.loads(recorded)["status"])

    def test_invalid_parent_context_status_rejected(self):
        with self.assertRaises(DomainError) as caught:
            build_payload(role="implement", task_ref="session-only", plan_item_ids=[],
                          allowed_paths=[], baseline={},
                          context_report={"selection_reason": "r", "unloaded": [],
                                          "parent_context": {"status": "invented",
                                                             "origin": {"task_id": "t"}, "loaded": [], "deferred": []}})
        self.assertEqual("invalid_dispatch_payload", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
