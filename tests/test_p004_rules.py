"""P-004 (antigravity-adoption A-013/A-009/A-005) tests.

- A-013: fstar start soft gate — a design-needing task (criteria.md carries
  the design-required marker, planning-review grant includes design) without
  a design.md is refused; simple tasks and design-backed tasks start.
- A-009: session grants store — set/read round trip, and the worker-context
  hook resolves session-only grants from the store when the host payload
  carries no extensions array.
- A-005: workflow archive requires doc/walkthrough.md.
- A-010: the steward role is recognized and gated by multi-agent/steward.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fstar.models import DomainError
from fstar.runtime import hooks
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


class Clock:
    def __init__(self, value="2026-11-28T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value


class P004Case(unittest.TestCase):
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
        self.runtime_root = root / "runtime"
        self.store = TaskStore(self.project, user_home=self.user_root, runtime_root=self.runtime_root)
        self.clock = Clock()
        self.service = TaskService(self.store, clock=self.clock)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref, actor=None):
        task = self.store.read(ref)
        return {"source_id": "source-" + task["id"], "type": "command", "at": self.clock(),
                "actor": actor or self.user, "reference": "prompt:42", "quote": "",
                "scope": "task", "validates": source_snapshot(task)}

    def create(self, name="root"):
        return self.service.create(name=name, title=name.title(), description="Deliver",
                                   actor=self.agent, session_id="s1")

    def start(self, ref="root"):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref), session_id="s1")

    def map_criteria(self, ref):
        task_dir = self.store.resolve(ref)
        (task_dir / "criteria.md").write_text("A-001 body\n", encoding="utf-8")
        self.service.evidence.persist_artifact_map(
            ref, mapping={".fstar/tasks/%s/criteria.md" % ref: {"A-001": {
                "start_marker": "A-001", "end_marker": "\n", "dependencies": []}}},
            source={"type": "test"})


class StartDesignGateTests(P004Case):
    def _design_grant(self, ref):
        self.service.enable_extension(ref, authorization={
            "id": "planning-review", "scope": "custom", "included": ["prd", "design"],
            "excluded": [], "source": self.source(ref)}, actor=self.user)

    def test_design_required_without_design_doc_blocks_start(self):
        self.create("gated")
        self._design_grant("gated")
        self.map_criteria("gated")
        (self.store.resolve("gated") / "criteria.md").write_text(
            "# criteria\n\nA-001 x\n\n判定边界：design-required\n", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            self.start("gated")
        self.assertEqual("design_doc_missing", caught.exception.code)
        self.assertEqual("planning", self.store.read("gated")["phase"])

    def test_design_doc_present_allows_start(self):
        self.create("designed")
        self._design_grant("designed")
        self.map_criteria("designed")
        (self.store.resolve("designed") / "criteria.md").write_text(
            "A-001 design-required\n", encoding="utf-8")
        (self.store.resolve("designed") / "doc").mkdir()
        (self.store.resolve("designed") / "doc" / "design.md").write_text("# design\n", encoding="utf-8")
        self.assertEqual("in_progress", self.start("designed")["phase"])

    def test_simple_task_without_marker_unaffected(self):
        self.create("simple")
        self._design_grant("simple")
        self.map_criteria("simple")
        self.assertEqual("in_progress", self.start("simple")["phase"])


class SessionGrantsStoreTests(P004Case):
    def test_set_and_read_session_grants_round_trip(self):
        record = {"id": "multi-agent", "scope": "custom",
                  "included": ["research", "steward"], "excluded": [], "enabled_at": "now",
                  "source": {"type": "test"}, "reason": ""}
        self.store.set_session_grants("s9", [record])
        self.assertEqual([record], self.store.read_session_grants("s9"))
        # A different session id reads nothing (isolation).
        self.assertEqual([], self.store.read_session_grants("other"))
        # Empty write clears.
        self.store.set_session_grants("s9", [])
        self.assertEqual([], self.store.read_session_grants("s9"))

    def test_missing_store_reads_empty(self):
        self.assertEqual([], self.store.read_session_grants("never"))
        self.assertEqual([], self.store.read_session_grants(None))

    def test_worker_context_resolves_session_grants_without_payload_extensions(self):
        # A-009 dual channel: no extensions in the host payload — the hook
        # falls back to the session grants store keyed by session_id.
        record = {"id": "planning-review", "scope": "custom",
                  "included": ["editor"], "excluded": [], "enabled_at": "now",
                  "source": {"type": "test"}, "reason": ""}
        self.store.set_session_grants("s1", [record])
        result = hooks.worker_context({"session_id": "s1", "role": "fstar-editor"},
                                      start=self.project, user_root=self.user_root,
                                      runtime_root=self.runtime_root, clock=self.clock)
        self.assertEqual("editor", result["role"])
        self.assertIn("fstar worker context (editor)", result["text"])

    def test_session_context_resolves_session_grants_without_payload_extensions(self):
        record = {"id": "project-governance", "scope": "custom",
                  "included": ["specs"], "excluded": [], "enabled_at": "now",
                  "source": {"type": "test"}, "reason": ""}
        self.store.set_session_grants("s1", [record])
        result = hooks.session_context({"session_id": "s1"}, start=self.project,
                                       user_root=self.user_root,
                                       runtime_root=self.runtime_root, as_json=True)
        self.assertEqual({"project-governance": ["specs"]}, result["extensions"])


class StewardRoleTests(P004Case):
    def test_steward_requires_multi_agent_member(self):
        with self.assertRaises(DomainError) as caught:
            hooks.worker_context({"role": "fstar-steward"}, start=self.project,
                                 user_root=self.user_root,
                                 runtime_root=self.runtime_root, clock=self.clock)
        self.assertEqual("extension_not_authorized", caught.exception.code)
        self.assertEqual("multi-agent", caught.exception.details["package"])
        self.assertEqual("steward", caught.exception.details["member"])

    def test_steward_authorized_with_member(self):
        record = {"id": "multi-agent", "scope": "custom",
                  "included": ["steward"], "excluded": [], "enabled_at": "now",
                  "source": {"type": "test"}, "reason": ""}
        result = hooks.worker_context({"role": "fstar-steward", "extensions": [record]},
                                      start=self.project, user_root=self.user_root,
                                      runtime_root=self.runtime_root, clock=self.clock)
        self.assertEqual("steward", result["role"])


class WorkflowArchiveWalkthroughGateTests(P004Case):
    def _accepted(self, name="root"):
        self.create(name)
        (self.store.resolve(name) / "doc").mkdir(exist_ok=True)
        (self.store.resolve(name) / "doc" / "walkthrough.md").write_text(
            "# walkthrough\n\n<!-- a-start -->A-1<!-- a-end -->\n", encoding="utf-8")
        self.start(name)
        artifact = ".fstar/tasks/%s/doc/walkthrough.md" % name
        self.service.evidence.persist_artifact_map(
            name, mapping={artifact: {"A-1": {
                "start_marker": "<!-- a-start -->", "end_marker": "<!-- a-end -->", "dependencies": []}}},
            source={"type": "test"})
        lease = self.service.acquire_lease(name, holder="w", role="implement", actor=self.agent)
        snapshot = self.service.evidence.snapshot(name, artifact=artifact, items=["A-1"])
        self.service.evidence.record(name, lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "c1"},
            "validates": [snapshot], "run_id": "r", "environment": {"python": "3"},
            "delivery": self.service.evidence.delivery_snapshot([]),
            "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["A-1"], "plan_item": "P-1", "test_refs": [],
                       "command": "x", "result": "passed", "exit_code": 0,
                       "log_refs": [], "duration": 0.1, "retries": 0}]})
        self.service.release_lease(name, token=lease["token"], reason="done")
        self.service.enter_awaiting_acceptance(name, actor=self.agent)
        self.service.accept(name, actor=self.user, confirmation=self.source(name))
        self.service.enable_extension(name, authorization={
            "id": "persistent-task", "scope": "custom", "included": ["archive"],
            "excluded": [], "source": {"type": "test"}}, actor=self.user)

    def test_workflow_archive_without_walkthrough_refused(self):
        self._accepted("no-walkthrough")
        (self.store.resolve("no-walkthrough") / "doc" / "walkthrough.md").unlink()
        with self.assertRaises(DomainError) as caught:
            self.service.archive("no-walkthrough", actor=self.user,
                                 confirmation=self.source("no-walkthrough"), workflow=True)
        self.assertEqual("walkthrough_missing", caught.exception.code)

    def test_workflow_archive_with_walkthrough_succeeds(self):
        self._accepted("root")
        archived = self.service.archive("root", actor=self.user,
                                        confirmation=self.source("root"), workflow=True)
        self.assertTrue(archived["path"].endswith("root"))


if __name__ == "__main__":
    unittest.main()
