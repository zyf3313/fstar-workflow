from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fstar.cli import build_parser, main
from fstar.dispatch import (
    CHANGE_SCHEMA,
    PAYLOAD_SCHEMA,
    RESULT_SCHEMA,
    DispatchService,
    adapter_invocation_note,
    build_change,
    build_payload,
    build_result,
    build_worker_prompt,
    parallel_groups,
    propagation_decision,
    validate_change,
    validate_payload,
    validate_result,
)
from fstar.evidence import file_digest
from fstar.models import DomainError
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot


class Clock:
    def __init__(self, value="2026-10-29T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, minutes):
        moment = datetime.fromisoformat(self.value.replace("Z", "+00:00")) + timedelta(minutes=minutes)
        self.value = moment.isoformat().replace("+00:00", "Z")


class DispatchCase(unittest.TestCase):
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
        self.dispatch = DispatchService(self.store, clock=self.clock, task_service=self.service)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def source(self, ref):
        task = self.store.read(ref)
        return {"source_id": "source-" + task["id"], "type": "command", "at": self.clock(),
                "actor": self.user, "reference": "prompt:42", "quote": "", "scope": "task",
                "validates": source_snapshot(task)}

    def create_started(self, name="root"):
        self.service.create(name=name, title=name.title(), description="Deliver R-001", actor=self.agent, session_id="s1")
        self.service.start(name, actor=self.user, confirmation=self.source(name), session_id="s1")

    def prepare_artifacts(self, ref="root"):
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        (self.project / "src.py").write_text("value = 1\n")
        with self.store.transaction():
            task = self.store.read(ref)
            task["meta"]["templates"] = {"artifact_map": {"doc/prd.md": {"R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->", "dependencies": []}}}}
            self.store.write(self.store.resolve(ref), task)

    def payload(self, role="implement", task_ref="root", paths=None, **kwargs):
        baseline = kwargs.pop("baseline", None)
        if baseline is None:
            if task_ref != "session-only" and (self.project / "doc" / "prd.md").is_file():
                snapshot = self.service.evidence.snapshot(task_ref, artifact="doc/prd.md", items=["R-001"])
                delivery = self.service.evidence.delivery_snapshot(["src.py"])
            else:
                snapshot = {"artifact": "doc/prd.md", "items": [{"id": "R-001", "sha256": "x"}], "dependencies": [], "granularity": "item"}
                delivery = {"paths": [{"path": "src.py", "exists": True, "sha256": "y"}], "digest": "d"}
            baseline = {"artifact_items": [snapshot], "delivery": delivery}
        return build_payload(role=role, task_ref=task_ref, plan_item_ids=kwargs.pop("plan_item_ids", ["P-1"]),
                             allowed_paths=paths if paths is not None else ["src.py"], baseline=baseline, **kwargs)

    def result(self, payload, status="done", changed=None, **kwargs):
        return build_result(dispatch_id=payload["dispatch_id"], role=payload["role"], status=status,
                            changed_paths=changed if changed is not None else payload["allowed_paths"], **kwargs)


class CollaborationGrantTests(DispatchCase):
    def grant(self, included, excluded=()):
        return self.service.enable_extension("root", authorization={"id": "multi-agent", "scope": "custom", "included": list(included), "excluded": list(excluded), "source": {"type": "test"}}, actor=self.user)

    def test_persistent_version_and_change_grants_recovered_and_revoked(self):
        self.create_started()
        payload = self.payload(input_versions=[{"path": "doc/prd.md", "sha256": "abc"}])
        with self.assertRaises(DomainError) as caught:
            self.dispatch.interrupt("d", reason="changed", mode="change_propagation", task_ref="root")
        self.assertEqual("extension_not_authorized", caught.exception.code)
        self.assertTrue(self.dispatch.register(payload)["registered"])
        token = self.store.read("root")["lease"]["token"]
        self.service.release_lease("root", token=token, reason="test")
        self.grant(["version-injection"], ["change-propagation"])
        # Another service instance reads the persisted task rather than caller grants.
        recovered = DispatchService(self.store, clock=self.clock)
        self.assertTrue(recovered.register(payload)["registered"])
        with self.assertRaises(DomainError):
            recovered.interrupt("d", reason="changed", mode="change_propagation", task_ref="root")
        token = self.store.read("root")["lease"]["token"]
        self.service.release_lease("root", token=token, reason="test")
        self.grant(["change-propagation"], ["version-injection"])
        self.assertTrue(recovered.interrupt("d", reason="changed", mode="change_propagation", task_ref="root")["intent_registered"])
        self.assertTrue(recovered.register(payload)["registered"])
        self.assertTrue(recovered.register(self.payload(role="check", input_versions=[{"path": "doc/prd.md", "sha256": "abc"}]))["registered"])
        token = self.store.read("root")["lease"]["token"]
        self.service.release_lease("root", token=token, reason="test")
        self.service.disable_extension("root", extension_id="multi-agent", authorization={"type": "test"}, actor=self.user)
        with self.assertRaises(DomainError) as caught:
            recovered.interrupt("d", reason="changed", mode="change_propagation", task_ref="root")
        self.assertEqual("extension_not_authorized", caught.exception.code)
        self.assertTrue(recovered.register(self.payload(role="check", input_versions=[{"path": "doc/prd.md", "sha256": "abc"}]))["registered"])

    def test_session_grants_and_core_stop_without_metadata(self):
        grant = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["change-propagation", "version-injection"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        before = {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        payload = self.payload(task_ref="session-only", input_versions=[{"path": "doc/prd.md", "sha256": "abc"}])
        self.assertFalse(self.dispatch.register(payload)["registered"])
        check = self.payload(role="check", task_ref="session-only", input_versions=[{"path": "doc/prd.md", "sha256": "abc"}])
        self.assertFalse(self.dispatch.register(check)["registered"])
        payload["extensions"] = [grant]
        self.assertFalse(self.dispatch.register(payload)["registered"])
        self.assertTrue(self.dispatch.interrupt("d", reason="changed", mode="change_propagation", extensions=[grant])["intent_registered"])
        with self.assertRaises(DomainError):
            self.dispatch.interrupt("d", reason="changed", mode="change_propagation")
        self.assertTrue(self.dispatch.interrupt("d", reason="stop", mode="checkpoint_stop")["intent_registered"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()})


class PayloadValidationTests(DispatchCase):
    def test_valid_payload_roundtrip(self):
        payload = self.payload()
        self.assertEqual(PAYLOAD_SCHEMA, payload["schema"])
        self.assertEqual("Active task: root", payload["prompt_first_line"])
        validate_payload(payload)

    def test_missing_required_fields_rejected(self):
        for field in ("dispatch_id", "role", "baseline", "allowed_paths", "prompt_first_line"):
            broken = self.payload()
            broken.pop(field)
            with self.subTest(field=field), self.assertRaises(DomainError) as caught:
                validate_payload(broken)
            self.assertEqual("invalid_dispatch_payload", caught.exception.code)

    def test_bad_role_and_paths_rejected(self):
        broken = self.payload()
        broken["role"] = "learn"
        with self.assertRaises(DomainError):
            validate_payload(broken)
        for bad in ("/etc/passwd", "../escape.py", ""):
            broken = self.payload()
            broken["allowed_paths"] = [bad]
            with self.subTest(path=bad), self.assertRaises(DomainError) as caught:
                validate_payload(broken)
            self.assertEqual("unsafe_dispatch_path", caught.exception.code)

    def test_session_only_prompt_line_consistency(self):
        payload = self.payload(task_ref="session-only")
        self.assertEqual("Active task: session-only", payload["prompt_first_line"])
        broken = self.payload(task_ref="session-only")
        broken["prompt_first_line"] = "Active task: .fstar/tasks/fake"
        with self.assertRaises(DomainError):
            validate_payload(broken)

    def test_editor_requires_item_ids_and_baseline(self):
        # session-only editor: doc tree root
        with self.assertRaises(DomainError) as caught:
            self.payload(role="editor", task_ref="session-only", paths=["doc/prd.md"])
        self.assertEqual("item_ids", caught.exception.details.get("field"))
        with self.assertRaises(DomainError) as caught:
            self.payload(role="editor", task_ref="session-only", paths=["doc/prd.md"], item_ids=["R-001"])
        self.assertEqual("baseline_sha256", caught.exception.details.get("field"))
        payload = self.payload(role="editor", task_ref="session-only", paths=["doc/prd.md"], item_ids=["R-001"], baseline_sha256="abc")
        validate_payload(payload)
        with self.assertRaises(DomainError):
            self.payload(role="editor", task_ref="session-only", paths=["src.py"], item_ids=["R-001"], baseline_sha256="abc")

    def test_persistent_editor_limited_to_task_doc_tree(self):
        self.create_started()
        with self.assertRaises(DomainError):
            self.payload(role="editor", paths=["doc/prd.md"], item_ids=["R-001"], baseline_sha256="abc")
        payload = self.payload(role="editor", paths=[".fstar/tasks/root/doc/prd.md"], item_ids=["R-001"], baseline_sha256="abc")
        validate_payload(payload)

    def test_research_scope_restricted(self):
        with self.assertRaises(DomainError):
            self.payload(role="research", paths=["src.py"])
        validate_payload(self.payload(role="research", task_ref="session-only", paths=["research/notes.md"]))
        with self.assertRaises(DomainError):
            self.payload(role="research", paths=["research/notes.md"])


class ResultChangeTests(DispatchCase):
    def test_result_validation(self):
        validate_result(self.result(self.payload()))
        for field in ("dispatch_id", "role", "status"):
            broken = self.result(self.payload())
            broken.pop(field)
            with self.subTest(field=field), self.assertRaises(DomainError):
                validate_result(broken)
        broken = self.result(self.payload())
        broken["status"] = "accepted"
        with self.assertRaises(DomainError):
            validate_result(broken)

    def test_change_message_fields(self):
        change = build_change(source="file", origin="doc/prd.md",
                              affected={"plan_item_ids": ["P-1"], "artifact_items": []},
                              old_fingerprints={"R-001": "old"}, new_fingerprints={"R-001": "new"})
        self.assertEqual(CHANGE_SCHEMA, change["schema"])
        for key in ("change_id", "source", "origin", "affected", "old_fingerprints", "new_fingerprints", "action"):
            self.assertIn(key, change)
        validate_change(change)
        with self.assertRaises(DomainError):
            build_change(source="telepathy", origin="x")

    def test_propagation_tiers(self):
        change = build_change(source="conversation", origin="user update")
        self.assertEqual("steer", propagation_decision("realtime-steer", change)["action"])
        self.assertEqual("pause_and_redispatch", propagation_decision("checkpoint-stop", change)["action"])
        self.assertEqual("stop_process", propagation_decision("process-stop", change)["action"])
        with self.assertRaises(DomainError):
            propagation_decision("telepathy", change)


class RegisterTests(DispatchCase):
    def test_persistent_task_takes_coordinator_lease_and_event(self):
        self.create_started()
        payload = self.payload()
        registered = self.dispatch.register(payload, coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(registered["registered"])
        self.assertEqual("task", registered["persistence"])
        task = self.store.read("root")
        self.assertEqual("coordinator", task["lease"]["holder"]["role"])
        events = [e for e in task["events"] if e["type"] == "dispatch_registered"]
        self.assertEqual(1, len(events))
        self.assertEqual(payload["dispatch_id"], events[0]["data"]["dispatch_id"])
        self.assertEqual(set(events[0]), {"id", "at", "source", "type", "data"})

    def test_register_reuses_own_lease(self):
        self.create_started()
        first = self.dispatch.register(self.payload(), coordinator_id="coordinator", actor=self.agent)
        second = self.dispatch.register(self.payload(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual(first["lease_token"], second["lease_token"])

    def test_register_rejects_other_active_lease_and_wrong_phase(self):
        self.create_started()
        self.prepare_artifacts()
        self.service.acquire_lease("root", holder="someone-else", role="coordinator", actor=self.agent)
        with self.assertRaises(DomainError) as caught:
            self.dispatch.register(self.payload(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual("lease_conflict", caught.exception.code)
        self.service.release_lease("root", token=self.store.read("root")["lease"]["token"], reason="done")
        self.service.continue_task("root", action="replan", actor=self.user, confirmation=self.source("root"), reason="back")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.register(self.payload(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual("dispatch_not_allowed", caught.exception.code)

    def test_session_only_register_writes_nothing(self):
        before = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        payload = self.payload(task_ref="session-only")
        registered = self.dispatch.register(payload)
        self.assertFalse(registered["registered"])
        self.assertEqual("session_only", registered["persistence"])
        after = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        self.assertEqual(before, after)

    def test_output_states_adapter_mode(self):
        note = adapter_invocation_note()
        self.assertEqual("adapter", note["dispatch_mode"])
        self.assertIn("cannot invoke", note["note"])


class ParallelReservationTests(DispatchCase):
    """multi-agent/parallel-implement: dependency- and write-safe reservations.

    Reservation is a coordinator-side scope lock with an explicit host launch
    handshake. It never proves a host worker started or stopped.
    """

    def grant(self, included=("parallel-implement",), excluded=()):
        return self.service.enable_extension("root", authorization={"id": "multi-agent", "scope": "custom", "included": list(included), "excluded": list(excluded), "source": {"type": "test"}}, actor=self.user)

    def items(self):
        return [
            {"id": "P-1", "depends_on": [], "allowed_paths": ["src/a.py"], "shared_resources": []},
            {"id": "P-2", "depends_on": [], "allowed_paths": ["src/b.py"], "shared_resources": []},
            {"id": "P-3", "depends_on": ["P-1"], "allowed_paths": ["src/c.py"], "shared_resources": []},
        ]

    def payloads(self, paths_list=(["src/a.py"], ["src/b.py"]), plan_items=(["P-1"], ["P-2"])):
        return [self.payload(paths=paths, plan_item_ids=ids)
                for paths, ids in zip(paths_list, plan_items)]

    def run_cli(self, *argv):
        return main(list(argv))

    def test_reserve_requires_parallel_implement_grant(self):
        self.create_started()
        self.prepare_artifacts()
        payloads = self.payloads()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(payloads, plan_items=self.items())
        self.assertEqual("extension_not_authorized", caught.exception.code)
        self.assertEqual({"package": "multi-agent", "member": "parallel-implement"}, caught.exception.details)
        # No grant → no writes at all.
        task = self.store.read("root")
        self.assertEqual([], self._reservations(task))
        self.assertIsNone(task["lease"])

    def test_reserve_rejects_excluded_member_and_revoked_grant(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant(included=[], excluded=["parallel-implement"])
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items())
        self.assertEqual("extension_not_authorized", caught.exception.code)
        self.service.disable_extension("root", extension_id="multi-agent", authorization={"type": "test"}, actor=self.user)
        # Revoked: re-grant then revoke is covered by disable above; grant again then disable to prove revoke.
        self.grant()
        self.service.disable_extension("root", extension_id="multi-agent", authorization={"type": "test"}, actor=self.user)
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items())
        self.assertEqual("extension_not_authorized", caught.exception.code)
        # Single implement dispatch still works with no optional grant.
        self.assertTrue(self.dispatch.register(self.payload())["registered"])

    def test_reserve_creates_atomic_reservations_and_lease(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        payloads = self.payloads()
        result = self.dispatch.reserve_parallel(payloads, plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(result["registered"])
        self.assertEqual("task", result["persistence"])
        task = self.store.read("root")
        reservations = self._reservations(task)
        self.assertEqual(2, len(reservations))
        self.assertEqual({payloads[0]["dispatch_id"], payloads[1]["dispatch_id"]},
                         {r["dispatch_id"] for r in reservations})
        self.assertTrue(all(r["state"] == "reserved" for r in reservations))
        self.assertTrue(all(r["lease_token"] == result["lease_token"] for r in reservations))
        self.assertEqual("coordinator", task["lease"]["holder"]["role"])
        events = [e for e in task["events"] if e["type"] == "dispatch_reserved"]
        self.assertEqual(2, len(events))
        self.assertIn("No host worker process liveness", result["note"])

    def _reservations(self, task):
        return task.get("meta", {}).get("templates", {}).get("dispatch_reservations", [])

    def test_reserve_rejects_dependency_in_batch(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        payloads = self.payloads(plan_items=(["P-1"], ["P-3"]))
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(payloads, plan_items=self.items())
        self.assertEqual("dependency_in_batch", caught.exception.code)
        self.assertEqual([], self._reservations(self.store.read("root")))

    def test_reserve_rejects_dependency_on_unresolved_reservation(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(first["registered"])
        # P-3 depends on P-1 which is still unresolved.
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["src/c.py"], plan_item_ids=["P-3"])],
                                            plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual("dependency_unresolved", caught.exception.code)

    def test_reserve_dependency_allowed_after_reservation_resolved(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        token = first["lease_token"]
        payload = first["payloads"][0]
        result = self.result(payload, changed=["src/a.py"])
        self.assertTrue(self.dispatch.harvest(result, payload, lease_token=token)["recorded"])
        # P-1 is completed now; P-3 can be reserved.
        second = self.dispatch.reserve_parallel([self.payload(paths=["src/c.py"], plan_item_ids=["P-3"])],
                                                 plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(second["registered"])

    def test_reserve_rejects_path_conflicts_including_nesting(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        exact = self.payloads(paths_list=(["src/a.py"], ["src/a.py"]))
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(exact, plan_items=self.items())
        self.assertEqual("path_conflict", caught.exception.code)
        # A directory scope and a file inside it conflict (nesting).
        nested = self.payloads(paths_list=(["src"], ["src/a.py"]))
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(nested, plan_items=self.items())
        self.assertEqual("path_conflict", caught.exception.code)
        # A truly disjoint scope is accepted.
        ok = self.payloads(paths_list=(["src/a.py"], ["doc/b.md"]))
        self.assertTrue(self.dispatch.reserve_parallel(ok, plan_items=self.items())["registered"])

    def test_reserve_rejects_conflict_with_active_reservation(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(first["registered"])
        # Same path in a NEW reservation attempt (separate call, not batch).
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-2"])],
                                            plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual("path_conflict", caught.exception.code)
        self.assertIn("active_dispatch_id", caught.exception.details)
        # Nested conflict too: the active reservation holds src/a.py; a scope
        # that contains it conflicts.
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["src"], plan_item_ids=["P-2"])],
                                            plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertEqual("path_conflict", caught.exception.code)

    def test_reserve_conflict_cleared_after_harvest(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        payload = first["payloads"][0]
        result = self.result(payload, changed=["src/a.py"])
        self.assertTrue(self.dispatch.harvest(result, payload, lease_token=first["lease_token"])["recorded"])
        # Path is free again for a new reservation.
        second = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-2"])],
                                                 plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(second["registered"])

    def test_reserve_rejects_shared_resource_conflict(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        items = self.items()
        items[0]["shared_resources"] = ["db"]
        items[1]["shared_resources"] = ["db"]
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=items)
        self.assertEqual("shared_resource_conflict", caught.exception.code)
        self.assertEqual(["db"], caught.exception.details["shared_resources"])

    def test_reserve_rejects_handed_off_scope(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        self.dispatch.hand_off_scope("root", ["P-1"])
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items())
        self.assertEqual("scope_violation", caught.exception.code)

    def test_reserve_rejects_wrong_phase_and_lease_conflict(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        self.service.acquire_lease("root", holder="someone-else", role="coordinator", actor=self.agent)
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("lease_conflict", caught.exception.code)
        self.service.release_lease("root", token=self.store.read("root")["lease"]["token"], reason="done")
        self.service.continue_task("root", action="replan", actor=self.user, confirmation=self.source("root"), reason="back")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("dispatch_not_allowed", caught.exception.code)

    def test_reserve_path_conflict_normalizes_equivalent_spellings(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(first["registered"])
        # Equivalent spellings of the same scope must still conflict.
        for spelling in ("src//a.py", "./src/a.py", "src/./a.py", "src/"):
            payload = self.payload(paths=[spelling], plan_item_ids=["P-2"])
            with self.assertRaises(DomainError) as caught:
                self.dispatch.reserve_parallel([payload], plan_items=self.items(), coordinator_id="coordinator")
            self.assertEqual("path_conflict", caught.exception.code)
        # Intra-batch equivalence is also rejected.
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["src/b.py"], plan_item_ids=["P-1"]),
                                            self.payload(paths=["./src/b.py/"], plan_item_ids=["P-2"])],
                                           plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("path_conflict", caught.exception.code)
        self.assertEqual(1, len(self._reservations(self.store.read("root"))))
        # Absolute paths and traversal stay structurally rejected by payload validation.
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["/etc/passwd"], plan_item_ids=["P-2"])],
                                           plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("unsafe_dispatch_path", caught.exception.code)
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["../outside.py"], plan_item_ids=["P-2"])],
                                           plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("unsafe_dispatch_path", caught.exception.code)

    def test_reserve_rejects_mixed_tasks_and_roles(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([], plan_items=self.items())
        self.assertEqual("invalid_batch", caught.exception.code)
        mixed_roles = [self.payload(paths=["src/a.py"], plan_item_ids=["P-1"]),
                       self.payload(role="check", paths=["src/b.py"], plan_item_ids=["P-2"])]
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel(mixed_roles, plan_items=self.items())
        self.assertEqual("invalid_batch", caught.exception.code)
        session = self.payload(task_ref="session-only", paths=["src/b.py"], plan_item_ids=["P-2"])
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"]), session], plan_items=self.items())
        self.assertEqual("invalid_batch", caught.exception.code)

    def test_confirm_launch_marks_launched(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        dispatch_id = first["payloads"][0]["dispatch_id"]
        confirmed = self.dispatch.confirm_launch("root", [dispatch_id])
        self.assertEqual([dispatch_id], confirmed["confirmed"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("launched", states[dispatch_id])
        # Idempotent: already launched ids are not confirmed twice.
        again = self.dispatch.confirm_launch("root", [dispatch_id])
        self.assertEqual([], again["confirmed"])

    def test_confirm_launch_cannot_target_other_tasks_or_forged_ids(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        dispatch_id = first["payloads"][0]["dispatch_id"]
        # A reservation from another task does not exist here; confirm-launch on
        # an unknown id is a no-op, not a state change or error.
        other = self.service.create(name="other", title="Other", description="x",
                                    actor=self.agent, session_id="s1")
        confirmed = self.dispatch.confirm_launch("other", [dispatch_id])
        self.assertEqual([], confirmed["confirmed"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("reserved", states[dispatch_id])
        # An already-completed reservation cannot be re-launched.
        token = first["lease_token"]
        self.dispatch.harvest(self.result(first["payloads"][0], changed=["src/a.py"]),
                              first["payloads"][0], lease_token=token)
        confirmed = self.dispatch.confirm_launch("root", [dispatch_id])
        self.assertEqual([], confirmed["confirmed"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("completed", states[dispatch_id])

    def test_release_only_frees_matching_reservation_of_wrong_task(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        dispatch_id = first["payloads"][0]["dispatch_id"]
        self.service.create(name="other", title="Other", description="x", actor=self.agent, session_id="s1")
        released = self.dispatch.release_reservation("other", dispatch_id, reason="wrong task")
        self.assertEqual([], released["released"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("reserved", states[dispatch_id])

    def test_reservation_report_and_explicit_release(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        dispatch_id = first["payloads"][0]["dispatch_id"]
        report = self.dispatch.parallel_reservation_report("root")
        self.assertEqual(1, len(report["unresolved"]))
        self.assertEqual(dispatch_id, report["unresolved"][0]["dispatch_id"])
        self.assertIn("never auto-released", report["note"])
        # Released reservation frees the scope.
        released = self.dispatch.release_reservation("root", dispatch_id, reason="user decided worker gone",
                                                      coordinator_id="coordinator", lease_token=first["lease_token"])
        self.assertEqual([dispatch_id], released["released"])
        report = self.dispatch.parallel_reservation_report("root")
        self.assertEqual(0, len(report["unresolved"]))
        second = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-2"])],
                                                 plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(second["registered"])
        # Release requires a reason.
        with self.assertRaises(DomainError) as caught:
            self.dispatch.release_reservation("root", dispatch_id, reason="  ")
        self.assertEqual("reason_required", caught.exception.code)

    def test_release_rejects_wrong_lease(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        dispatch_id = first["payloads"][0]["dispatch_id"]
        with self.assertRaises(DomainError) as caught:
            self.dispatch.release_reservation("root", dispatch_id, reason="r", coordinator_id="coordinator", lease_token="bogus")
        self.assertEqual("invalid_lease", caught.exception.code)

    def test_harvest_resolves_reservation_state(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel(self.payloads(), plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        token = first["lease_token"]
        payload_a, payload_b = first["payloads"]
        outcome = self.dispatch.harvest(self.result(payload_a, changed=["src/a.py"]), payload_a, lease_token=token)
        self.assertTrue(outcome["recorded"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("completed", states[payload_a["dispatch_id"]])
        self.assertEqual("reserved", states[payload_b["dispatch_id"]])
        # Failed sibling → terminal, lease NOT released.
        failed = self.dispatch.harvest(self.result(payload_b, status="failed"), payload_b, lease_token=token)
        self.assertFalse(failed["lease_released"])
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("terminal", states[payload_b["dispatch_id"]])

    def test_reservation_survives_new_process_and_conflicts_cross_process(self):
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        fresh = DispatchService(self.store, clock=self.clock, task_service=TaskService(self.store, clock=self.clock))
        report = fresh.parallel_reservation_report("root")
        self.assertEqual(1, len(report["unresolved"]))
        # A fresh coordinator (new process) sees the conflict.
        with self.assertRaises(DomainError) as caught:
            fresh.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-2"])],
                                   plan_items=self.items(), coordinator_id="coordinator")
        self.assertEqual("path_conflict", caught.exception.code)

    def test_real_two_process_reservation_race(self):
        """Two real processes: one reserves a path; the other must be rejected."""
        import json
        import subprocess
        import sys
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        first = self.dispatch.reserve_parallel([self.payload(paths=["src/a.py"], plan_item_ids=["P-1"])],
                                                plan_items=self.items(), coordinator_id="coordinator", actor=self.agent)
        payload_b = self.payload(paths=["src/a.py"], plan_item_ids=["P-2"])
        plan_items = self.items()
        script = Path(self.tmp.name) / "reserve_b.py"
        script.write_text(
            "import json, sys\n"
            "sys.path.insert(0, %r)\n" % str(Path(__file__).resolve().parents[1] / "src")
            + "from pathlib import Path\n"
            "from fstar.dispatch import DispatchService\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "from fstar.models import DomainError\n"
            "store = TaskStore(Path(%r))\n" % str(self.project)
            + "service = DispatchService(store, task_service=TaskService(store))\n"
            "try:\n"
            "    service.reserve_parallel([json.loads(sys.argv[1])], plan_items=json.loads(sys.argv[2]), coordinator_id='coordinator')\n"
            "    print('RESERVED')\n"
            "except DomainError as exc:\n"
            "    print('REJECTED:' + exc.code)\n"
        )
        completed = subprocess.run([sys.executable, str(script),
                                     json.dumps(payload_b), json.dumps(plan_items)],
                                    capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("REJECTED:path_conflict", completed.stdout.strip())
        # The first reservation is intact.
        self.assertEqual(1, len(self._reservations(self.store.read("root"))))

    def test_real_two_process_simultaneous_race_allows_only_one(self):
        """Two real processes race for one path; transaction allows one winner."""
        import json
        import subprocess
        import sys
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        payload_a = self.payload(paths=["src/race.py"], plan_item_ids=["P-1"])
        payload_b = self.payload(paths=["src/race.py"], plan_item_ids=["P-2"])
        plan_items = self.items()
        script = Path(self.tmp.name) / "race_reserve.py"
        script.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, %r)\n" % str(Path(__file__).resolve().parents[1] / "src")
            + "from fstar.dispatch import DispatchService\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "from fstar.models import DomainError\n"
            "store = TaskStore(Path(%r))\n" % str(self.project)
            + "service = DispatchService(store, task_service=TaskService(store))\n"
            "try:\n"
            "    service.reserve_parallel([json.loads(sys.argv[1])], plan_items=json.loads(sys.argv[2]), coordinator_id='coordinator')\n"
            "    print('RESERVED')\n"
            "except DomainError as exc:\n"
            "    print('REJECTED:' + exc.code)\n"
        )
        command_a = [sys.executable, str(script), json.dumps(payload_a), json.dumps(plan_items)]
        command_b = [sys.executable, str(script), json.dumps(payload_b), json.dumps(plan_items)]
        proc_a = subprocess.Popen(command_a, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.tmp.name)
        proc_b = subprocess.Popen(command_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.tmp.name)
        out_a, err_a = proc_a.communicate(timeout=10)
        out_b, err_b = proc_b.communicate(timeout=10)
        self.assertEqual(0, proc_a.returncode, err_a)
        self.assertEqual(0, proc_b.returncode, err_b)
        outcomes = sorted([out_a.strip(), out_b.strip()])
        self.assertEqual("RESERVED", outcomes[1])
        self.assertIn(outcomes[0], ("REJECTED:path_conflict", "REJECTED:lease_conflict"))
        active = [r for r in self._reservations(self.store.read("root")) if r["state"] in ("reserved", "launched")]
        self.assertEqual(1, len(active))

    def test_session_only_reservation_no_metadata_and_conflicts(self):
        grant = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["parallel-implement"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        before = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        payload_a = self.payload(task_ref="session-only", paths=["src/a.py"], plan_item_ids=["P-1"])
        payload_b = self.payload(task_ref="session-only", paths=["src/b.py"], plan_item_ids=["P-2"])
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([payload_a, payload_b], plan_items=self.items())
        self.assertEqual("extension_not_authorized", caught.exception.code)
        payload_a["extensions"] = [grant]
        payload_b["extensions"] = [grant]
        result = self.dispatch.reserve_parallel([payload_a, payload_b], plan_items=self.items())
        self.assertFalse(result["registered"])
        self.assertEqual("session_only", result["persistence"])
        after = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        self.assertEqual(before, after)
        # In-memory conflict: a second conflicting reservation is rejected.
        payload_c = self.payload(task_ref="session-only", paths=["src/a.py"], plan_item_ids=["P-2"])
        payload_c["extensions"] = [grant]
        with self.assertRaises(DomainError) as caught:
            self.dispatch.reserve_parallel([payload_c], plan_items=self.items())
        self.assertEqual("path_conflict", caught.exception.code)
        # Confirm launch + harvest resolve the session reservation.
        confirmed = self.dispatch.confirm_launch("session-only", [payload_a["dispatch_id"]])
        self.assertEqual([payload_a["dispatch_id"]], confirmed["confirmed"])
        outcome = self.dispatch.harvest(self.result(payload_a, changed=["src/a.py"]), payload_a, lease_token=None)
        self.assertFalse(outcome["recorded"])
        # Now the path is free again in the session.
        result_c = self.dispatch.reserve_parallel([payload_c], plan_items=self.items())
        self.assertFalse(result_c["registered"])

    def test_parallel_cli_subcommands_no_top_level_command(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices
        self.assertNotIn("parallel", choices)
        self.assertNotIn("reserve", choices)
        dispatch_choices = choices["dispatch"]._subparsers._group_actions[0].choices
        for sub in ("reserve", "confirm-launch", "reservations", "release-reservation"):
            self.assertIn(sub, dispatch_choices)

    def test_parallel_cli_reserve_requires_grant(self):
        import contextlib
        import io
        import json
        self.create_started()
        self.prepare_artifacts()
        payloads = self.payloads()
        paths = []
        for index, payload in enumerate(payloads):
            path = Path(self.tmp.name) / ("reserve-%d.json" % index)
            path.write_text(json.dumps(payload))
            paths.append(str(path))
        plan_path = Path(self.tmp.name) / "plan.json"
        plan_path.write_text(json.dumps({"items": self.items()}))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "reserve",
                                "--payload", paths[0], "--payload", paths[1], "--plan-items", str(plan_path))
        self.assertNotEqual(0, code)
        self.assertIn("extension_not_authorized", stderr.getvalue())
        self.assertEqual([], self._reservations(self.store.read("root")))

    def test_parallel_cli_reserve_and_lifecycle_via_cli(self):
        import contextlib
        import io
        import json
        self.create_started()
        self.prepare_artifacts()
        self.grant()
        payloads = self.payloads()
        paths = []
        for index, payload in enumerate(payloads):
            path = Path(self.tmp.name) / ("cli-reserve-%d.json" % index)
            path.write_text(json.dumps(payload))
            paths.append(str(path))
        plan_path = Path(self.tmp.name) / "plan.json"
        plan_path.write_text(json.dumps({"items": self.items()}))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "reserve",
                                "--payload", paths[0], "--payload", paths[1], "--plan-items", str(plan_path))
        self.assertEqual(0, code)
        data = json.loads(stdout.getvalue())
        self.assertTrue(data["registered"])
        self.assertEqual(2, len(data["reservations"]))
        # Report shows both unresolved.
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "reservations", "root")
        self.assertEqual(0, code)
        report = json.loads(stdout.getvalue())
        self.assertEqual(2, len(report["unresolved"]))
        # Confirm launch for one.
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "confirm-launch", "root",
                                "--dispatch-id", payloads[0]["dispatch_id"])
        self.assertEqual(0, code)
        confirmed = json.loads(stdout.getvalue())
        self.assertEqual([payloads[0]["dispatch_id"]], confirmed["confirmed"])
        # Release the other with a reason.
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "release-reservation", "root",
                                "--dispatch-id", payloads[1]["dispatch_id"], "--reason", "worker gone",
                                "--lease-token", data["lease_token"])
        self.assertEqual(0, code)
        states = {r["dispatch_id"]: r["state"] for r in self._reservations(self.store.read("root"))}
        self.assertEqual("launched", states[payloads[0]["dispatch_id"]])
        self.assertEqual("released", states[payloads[1]["dispatch_id"]])

    def test_serial_single_worker_dispatch_unaffected(self):
        """No grant, no reservations: plain register/harvest work unchanged."""
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        registered = self.dispatch.register(payload, coordinator_id="coordinator", actor=self.agent)
        self.assertTrue(registered["registered"])
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent) if not self.store.read("root")["lease"] else self.store.read("root")["lease"]
        result = self.result(payload, changed=["src.py"])
        outcome = self.dispatch.harvest(result, payload, lease_token=self.store.read("root")["lease"]["token"])
        self.assertTrue(outcome["recorded"])
        task = self.store.read("root")
        self.assertEqual([], self._reservations(task))


class HarvestTests(DispatchCase):
    def lease(self, ref="root"):
        return self.service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.agent)

    def test_identity_mismatch_rejected(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        wrong = self.result(payload)
        wrong["dispatch_id"] = "other-id"
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(wrong, payload, lease_token=lease["token"])
        self.assertEqual("identity_mismatch", caught.exception.code)
        wrong_role = self.result(payload)
        wrong_role["role"] = "check"
        with self.assertRaises(DomainError):
            self.dispatch.harvest(wrong_role, payload, lease_token=lease["token"])
        self.assertEqual([], self.store.read("root")["evidence"])

    def test_stale_input_returns_change_message(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        (self.project / "doc" / "prd.md").write_text("<!-- R1:start -->\nchanged\n<!-- R1:end -->\n")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertEqual("stale_input", caught.exception.code)
        change = caught.exception.details["change"]
        self.assertEqual(CHANGE_SCHEMA, change["schema"])
        self.assertEqual([], self.store.read("root")["evidence"])

    def test_dependency_change_rejects_harvest_without_writing(self):
        self.create_started()
        self.prepare_artifacts()
        path = self.project / "doc" / "prd.md"
        path.write_text(path.read_text() + "<!-- R2:start -->\nsecond\n<!-- R2:end -->\n")
        with self.store.transaction():
            task = self.store.read("root")
            mapping = task["meta"]["templates"]["artifact_map"]["doc/prd.md"]
            mapping["R-001"]["dependencies"] = ["R-002"]
            mapping["R-002"] = {"start_marker": "<!-- R2:start -->", "end_marker": "<!-- R2:end -->", "dependencies": []}
            self.store.write(self.store.resolve("root"), task)
        payload = self.payload()
        lease = self.lease()
        before = self.store.read("root")
        path.write_text(path.read_text().replace("second", "changed dependency"))
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertEqual("stale_input", caught.exception.code)
        self.assertEqual(before, self.store.read("root"))

    def test_file_inputs_stale_missing_and_unchanged_with_delivery_change(self):
        self.create_started()
        self.prepare_artifacts()
        extra = self.project / "requirements.txt"
        extra.write_text("v1")
        payload = self.payload(input_versions=[{"path": "requirements.txt", "sha256": file_digest(extra)}],
                               read_context=[{"path": "requirements.txt", "sha256": file_digest(extra)}])
        lease = self.lease()
        before = self.store.read("root")
        extra.write_text("v2")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertEqual("stale_input", caught.exception.code)
        self.assertEqual("requirements.txt", caught.exception.details["change"]["origin"])
        self.assertEqual(before, self.store.read("root"))
        extra.unlink()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertEqual("input_unverifiable", caught.exception.code)
        extra.write_text("v1")
        (self.project / "src.py").write_text("value = 2\n")
        outcome = self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        self.assertEqual([], outcome["unverified_inputs"])
        self.assertTrue(self.service.evidence.freshness("root")["evidence"][0]["fresh"])
        extra.write_text("changed after harvest")
        freshness = self.service.evidence.freshness("root")["evidence"][0]
        self.assertFalse(freshness["fresh"])
        self.assertEqual("input_file", freshness["reasons"][0]["type"])

    def test_output_overlap_is_reported_as_unverified(self):
        self.create_started()
        self.prepare_artifacts()
        output = self.project / "src.py"
        payload = self.payload(input_versions=[{"path": "src.py", "sha256": file_digest(output)}])
        lease = self.lease()
        output.write_text("value = 2\n")
        outcome = self.dispatch.harvest(self.result(payload), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        self.assertEqual("reported_worker_output", outcome["unverified_inputs"][0]["reason"])
        self.assertEqual("stale", outcome["state"])
        self.assertFalse(self.service.evidence.freshness("root")["evidence"][0]["fresh"])

    def test_session_file_input_check_is_read_only_and_fails_closed(self):
        path = self.project / "input.txt"
        path.write_text("v1")
        payload = self.payload(task_ref="session-only", baseline={"artifact_items": []}, input_versions=[{"path": "input.txt", "sha256": file_digest(path)}])
        result = self.result(payload)
        before = {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        outcome = self.dispatch.harvest(result, payload, lease_token="none")
        self.assertEqual([], outcome["unverified_inputs"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()})
        path.write_text("changed")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token="none")
        self.assertEqual("stale_input", caught.exception.code)
        path.unlink()
        path.symlink_to(Path(self.tmp.name) / "outside")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token="none")
        self.assertEqual("input_unverifiable", caught.exception.code)
        payload["input_versions"] = []
        payload["baseline"] = {"artifact_items": [{"artifact": "input.txt", "items": []}]}
        self.assertFalse(self.dispatch.harvest(result, payload, lease_token="none")["input_baseline_verified"])

    def test_delivery_change_is_expected_output_not_stale(self):
        """The delivery baseline is the worker's expected OUTPUT: an implement
        worker that actually writes its allowed paths must not be judged stale."""
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        (self.project / "src.py").write_text("value = 2\n")  # the intended write
        outcome = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        task = self.store.read("root")
        self.assertEqual(1, len(task["evidence"]))
        # The recorded delivery evidence binds the post-write state.
        self.assertEqual("src.py", task["evidence"][0]["delivery"]["paths"][0]["path"])

    def test_replayed_result_records_nothing_twice(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        first = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertTrue(first["recorded"])
        # Replay of the same dispatch result (host event + CLI harvest):
        # exactly one evidence record may exist.
        second = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertFalse(second["recorded"])
        self.assertTrue(second["replayed"])
        task = self.store.read("root")
        self.assertEqual(1, len(task["evidence"]))

    def test_replay_guard_survives_new_process(self):
        """The harvested marker is task-persisted, not process memory."""
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        fresh = DispatchService(self.store, clock=self.clock, task_service=TaskService(self.store, clock=self.clock))
        replay = fresh.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertFalse(replay["recorded"])
        self.assertEqual(1, len(self.store.read("root")["evidence"]))

    def test_failed_and_cancelled_keep_coordinator_lease_for_siblings(self):
        """One worker failing must not orphan sibling workers: the coordinator
        lease on the shared task stays until the coordinator releases it."""
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        outcome = self.dispatch.harvest(self.result(payload, status="failed"), payload, lease_token=lease["token"])
        self.assertFalse(outcome["recorded"])
        self.assertFalse(outcome["lease_released"])
        task = self.store.read("root")
        self.assertIsNotNone(task["lease"])
        self.assertEqual("coordinator", task["lease"]["holder"]["role"])
        terminal = [e for e in task["events"] if e["type"] == "dispatch_terminal"]
        self.assertEqual(1, len(terminal))
        self.assertEqual("failed", terminal[0]["data"]["status"])
        cancelled_payload = self.payload(plan_item_ids=["P-2"])
        cancelled = self.dispatch.harvest(self.result(cancelled_payload, status="cancelled"),
                                          cancelled_payload, lease_token=lease["token"])
        self.assertFalse(cancelled["lease_released"])
        self.assertIsNotNone(self.store.read("root")["lease"])

    def test_handed_off_scope_persists_across_processes(self):
        self.create_started()
        self.prepare_artifacts()
        self.dispatch.hand_off_scope("root", ["P-1"])
        payload = self.payload()
        lease = self.lease()
        fresh = DispatchService(self.store, clock=self.clock, task_service=TaskService(self.store, clock=self.clock))
        with self.assertRaises(DomainError) as caught:
            fresh.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertEqual("scope_violation", caught.exception.code)
        self.assertEqual(["P-1"], caught.exception.details["handed_off"])
        self.assertEqual([], self.store.read("root")["evidence"])

    def test_scope_violation_rejected(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload, changed=["src.py", "doc/prd.md"]), payload, lease_token=lease["token"])
        self.assertEqual("scope_violation", caught.exception.code)
        self.assertEqual(["doc/prd.md"], caught.exception.details["out_of_scope"])
        self.assertEqual([], self.store.read("root")["evidence"])

    def test_editor_baseline_semantics(self):
        """Legitimate intended writes must not be judged stale against the
        pre-edit baseline; only a result based on a DIFFERENT discussion
        version is a conflict (old draft never overwrites a newer conclusion)."""
        self.create_started()
        self.prepare_artifacts()
        doc = self.project / ".fstar" / "tasks" / "root" / "doc" / "prd.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("<!-- R1:start -->\nfirst\n<!-- R1:end -->\n")
        baseline = file_digest(doc)
        payload = self.payload(role="editor", paths=[".fstar/tasks/root/doc/prd.md"], item_ids=["R-001"], baseline_sha256=baseline)
        lease = self.lease()
        # The editor performs its intended write: the file now differs from
        # the pre-edit baseline and the harvest must accept that.
        doc.write_text("<!-- R1:start -->\nintended edit\n<!-- R1:end -->\n")
        outcome = self.dispatch.harvest(self.result(payload, changed=[".fstar/tasks/root/doc/prd.md"]), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        # The same editor result based on a different baseline version is a
        # conflict: it must not overwrite the newer conclusion.
        divergent = self.result(payload, changed=[".fstar/tasks/root/doc/prd.md"])
        divergent["baseline_sha256"] = "stale-discussion-version"
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(divergent, payload, lease_token=lease["token"])
        self.assertEqual("baseline_conflict", caught.exception.code)

    def test_invalid_lease_rejected(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        self.lease()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload), payload, lease_token="bogus")
        self.assertEqual("invalid_lease", caught.exception.code)
        self.assertEqual([], self.store.read("root")["evidence"])

    def test_valid_implement_result_records_delivery_and_renews(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        self.clock.advance(10)
        expires_before = self.store.read("root")["lease"]["expires_at"]
        outcome = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        self.assertEqual("check_dispatch", outcome["next"])
        task = self.store.read("root")
        self.assertEqual(1, len(task["evidence"]))
        self.assertEqual("delivery", task["evidence"][0]["kind"])
        self.assertGreater(task["lease"]["expires_at"], expires_before)

    def test_done_result_without_changes_records_fresh_delivery(self):
        """A done result with no changed paths (e.g. already-satisfied work)
        must still record FRESH delivery evidence: recomputing the empty
        delivery snapshot keeps the digest self-consistent, instead of
        passing through the payload's pre-dispatch delivery digest."""
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        lease = self.lease()
        outcome = self.dispatch.harvest(self.result(payload, changed=[]), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        task = self.store.read("root")
        self.assertEqual(1, len(task["evidence"]))
        self.assertEqual("valid", task["evidence"][0]["state"])
        self.assertEqual([], task["evidence"][0]["delivery"]["paths"])
        fresh = self.service.evidence.freshness("root")
        self.assertTrue(fresh["evidence"][0]["fresh"])

    def test_check_with_overlapping_input_cannot_enable_acceptance(self):
        self.create_started()
        self.prepare_artifacts()
        output = self.project / "src.py"
        payload = self.payload(role="check", input_versions=[{"path": "src.py", "sha256": file_digest(output)}])
        lease = self.lease()
        output.write_text("value = 2\n")
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        check = {"kind": "check", "producer": {"role": "check", "id": "checker"},
                 "validates": [snapshot], "run_id": "run-1", "environment": {"python": "test"},
                 "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "final",
                 "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "command": "check", "result": "passed"}]}
        outcome = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload,
                                        lease_token=lease["token"], check_evidence=check)
        self.assertEqual("stale", outcome["state"])
        self.service.release_lease("root", token=lease["token"], reason="test")
        self.assertFalse(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])

    def test_check_result_walks_core_check_gate(self):
        self.create_started()
        self.prepare_artifacts()
        implement_payload = self.payload()
        lease = self.lease()
        self.dispatch.harvest(self.result(implement_payload, changed=["src.py"]), implement_payload, lease_token=lease["token"])
        check_payload = self.payload(role="check")
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        check_evidence = {
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c1"},
            "validates": [snapshot], "run_id": "run-1", "environment": {"python": sys.version.split()[0]},
            "delivery": self.service.evidence.delivery_snapshot(["src.py"]), "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [], "command": "python -m unittest", "result": "passed", "exit_code": 0, "log_refs": [], "duration": 0.1, "retries": 0}],
        }
        outcome = self.dispatch.harvest(self.result(check_payload, changed=[]), check_payload, lease_token=lease["token"], check_evidence=check_evidence)
        self.assertTrue(outcome["recorded"])
        task = self.store.read("root")
        self.assertEqual("check", task["evidence"][1]["kind"])
        # worker done is harvest completion, not acceptance; the lease is
        # still held by the coordinator, so acceptance stays blocked.
        status = self.service.evidence.acceptance_status("root")
        self.assertEqual(["active_lease"], status["blockers"])
        self.assertEqual([task["evidence"][1]["id"]], status["evidence_refs"])
        self.service.release_lease("root", token=lease["token"], reason="check complete")
        self.assertTrue(self.service.evidence.acceptance_status("root")["awaiting_acceptance"])
        # independence gate: a check from the same producer as a delivery is
        # refused by the core gate.
        second = self.service.acquire_lease("root", holder="coordinator", role="coordinator", actor=self.agent)
        self.service.evidence.record("root", lease_token=second["token"], evidence={
            "kind": "delivery", "producer": {"role": "implement", "id": "checker", "session_id": "i"},
            "validates": [], "delivery": self.service.evidence.delivery_snapshot(["src.py"])})
        bad = dict(check_evidence)
        bad["run_id"] = "run-2"
        bad_payload = self.payload(role="check")
        third = self.service.acquire_lease("root", holder="coordinator", role="coordinator", takeover_reason="independence probe", actor=self.agent)
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(bad_payload, changed=[]), bad_payload, lease_token=third["token"], check_evidence=bad)
        self.assertEqual("check_not_independent", caught.exception.code)

    def test_session_only_harvest_records_nothing(self):
        payload = self.payload(task_ref="session-only")
        outcome = self.dispatch.harvest(self.result(payload), payload, lease_token="none")
        self.assertFalse(outcome["recorded"])
        self.assertEqual("session_only", outcome["persistence"])

    def test_file_mode_artifact_map_baseline_roundtrip(self):
        """Whole-file mode (mode:"file") integration: the core file-mode fix
        is present, so a file-mode payload baseline recomputes correctly at
        harvest (the earlier 'upstream defect still pending' note is stale)."""
        self.create_started()
        (self.project / "doc").mkdir(exist_ok=True)
        (self.project / "doc" / "prd.md").write_text("# PRD whole file\nR-001 body\n")
        (self.project / "src.py").write_text("value = 1\n")
        with self.store.transaction():
            task = self.store.read("root")
            task["meta"]["templates"] = {
                "artifact_map": {"mode": "file",
                                 "doc/prd.md": {"R-001": {"start_marker": "<!-- a -->", "end_marker": "<!-- b -->", "dependencies": []}}}}
            self.store.write(self.store.resolve("root"), task)
        snapshot = self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])
        self.assertEqual("file", snapshot["granularity"])
        payload = self.payload(baseline={"artifact_items": [snapshot],
                                         "delivery": {"paths": [{"path": "src.py", "exists": True, "sha256": "x"}], "digest": "d"}})
        lease = self.lease()
        # Intended delivery write does not make the INPUT baseline stale.
        (self.project / "src.py").write_text("value = 2\n")
        outcome = self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])
        # Changing the input doc after dispatch IS stale_input.
        (self.project / "doc" / "prd.md").write_text("# PRD whole file changed\n")
        stale_payload = self.payload(baseline={"artifact_items": [self.service.evidence.snapshot("root", artifact="doc/prd.md", items=["R-001"])],
                                                "delivery": {"paths": [{"path": "src.py", "exists": True, "sha256": "x"}], "digest": "d"}})
        (self.project / "doc" / "prd.md").write_text("# PRD whole file changed again\n")
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(stale_payload, changed=["src.py"]), stale_payload, lease_token=lease["token"])
        self.assertEqual("stale_input", caught.exception.code)

    def test_handed_off_scope_rejects_implement(self):
        self.create_started()
        self.prepare_artifacts()
        self.dispatch.hand_off_scope("root", ["P-1"])
        payload = self.payload()
        lease = self.lease()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(self.result(payload, changed=["src.py"]), payload, lease_token=lease["token"])
        self.assertEqual("scope_violation", caught.exception.code)
        self.assertEqual(["P-1"], caught.exception.details["handed_off"])
        # outside the handed-off scope work continues
        other = self.payload(plan_item_ids=["P-2"])
        outcome = self.dispatch.harvest(self.result(other, changed=["src.py"]), other, lease_token=lease["token"])
        self.assertTrue(outcome["recorded"])

    def test_nested_subtask_editor_scope(self):
        """Editor/research scope matching works for nested subtask refs."""
        self.create_started()
        self.service.create(name="child", title="Child", description="nested", actor=self.agent, parent="root")
        self.service.start("child", actor=self.user, confirmation=self.source("child"), session_id="s1")
        nested = ".fstar/tasks/root/subtasks/child/doc/prd.md"
        payload = self.payload(role="editor", task_ref="root/subtasks/child", paths=[nested],
                              item_ids=["R-001"], baseline_sha256="abc")
        validate_payload(payload)
        # A flat-ref check must not substring-match a sibling path.
        with self.assertRaises(DomainError):
            self.payload(role="editor", task_ref="child2", paths=[".fstar/tasks/child2-extra/doc/prd.md"],
                         item_ids=["R-001"], baseline_sha256="abc")
        research = self.payload(role="research", task_ref="root/subtasks/child",
                               paths=[".fstar/tasks/root/subtasks/child/research/notes.md"])
        validate_payload(research)
        with self.assertRaises(DomainError):
            self.payload(role="research", task_ref="root/subtasks/child",
                         paths=[".fstar/tasks/root/subtasks/other/research/notes.md"])


class ParallelGroupTests(unittest.TestCase):
    def item(self, item_id, depends=None, paths=(), resources=(), priority="P2"):
        return {"id": item_id, "depends_on": list(depends or []), "allowed_paths": list(paths), "shared_resources": list(resources), "priority": priority}

    def test_dependency_chain(self):
        groups = parallel_groups([self.item("a"), self.item("b", depends=["a"]), self.item("c", depends=["b"])])
        self.assertEqual([["a"], ["b"], ["c"]], groups)

    def test_write_conflict_serializes(self):
        groups = parallel_groups([self.item("a", paths=["x.py"]), self.item("b", paths=["x.py"]), self.item("c", paths=["y.py"])])
        self.assertEqual([["a", "c"], ["b"]], groups)

    def test_shared_resource_conflict(self):
        groups = parallel_groups([self.item("a", resources=["db"]), self.item("b", resources=["db"]), self.item("c")])
        self.assertEqual([["a", "c"], ["b"]], groups)

    def test_priority_does_not_cross_dependencies(self):
        groups = parallel_groups([self.item("slow", priority="P0"), self.item("blocked", depends=["slow"], priority="P3"), self.item("quick", priority="P1")])
        self.assertEqual([["slow", "quick"], ["blocked"]], groups)

    def test_unknown_dependency_and_cycle_rejected(self):
        with self.assertRaises(DomainError):
            parallel_groups([self.item("a", depends=["ghost"])])
        with self.assertRaises(DomainError):
            parallel_groups([self.item("a", depends=["b"]), self.item("b", depends=["a"])])


class RetryTests(DispatchCase):
    def test_first_failure_retries_once_with_prior_failure(self):
        payload = self.payload()
        decision = self.dispatch.retry_dispatch(payload, failure_reason="adapter transport died")
        self.assertTrue(decision["retry"])
        self.assertNotEqual(payload["dispatch_id"], decision["payload"]["dispatch_id"])
        self.assertEqual("adapter transport died", decision["payload"]["prior_failure"]["reason"])
        self.assertEqual(payload["dispatch_id"], decision["payload"]["prior_failure"]["dispatch_id"])

    def test_second_failure_routes_to_debug(self):
        payload = self.payload()
        first = self.dispatch.retry_dispatch(payload, failure_reason="boom")
        second = self.dispatch.retry_dispatch(first["payload"], failure_reason="boom again")
        self.assertFalse(second["retry"])
        self.assertEqual("dispatch_failed_persistent", second["status"])
        self.assertEqual("fstar-debug", second["route"])

    def test_environment_block_not_retried(self):
        decision = self.dispatch.retry_dispatch(self.payload(), failure_reason="permission denied", environment_blocked=True)
        self.assertFalse(decision["retry"])
        self.assertEqual("blocked", decision["status"])


class OrphanTests(DispatchCase):
    def test_expired_lease_is_read_only_report(self):
        self.create_started()
        self.service.enable_extension("root", authorization={"id": "persistent-task", "scope": "custom", "included": ["recovery"], "excluded": [], "source": {"type": "test"}}, actor=self.user)
        self.service.acquire_lease("root", holder="worker-gone", role="coordinator", actor=self.agent)
        self.clock.advance(45)
        before = self.store.read("root")
        report = self.dispatch.orphan_report("root", workflow=True)
        self.assertEqual(before, self.store.read("root"))
        self.assertTrue(report["read_only"])
        self.assertEqual("orphaned", report["status"])
        self.assertEqual("choose_takeover_replan_or_drop", report["next"])
        # no automatic redispatch: phase and lease untouched
        task = self.store.read("root")
        self.assertEqual("in_progress", task["phase"])
        self.assertEqual("worker-gone", task["lease"]["holder"]["id"])

    def test_active_lease_reports_active_worker(self):
        self.create_started()
        self.service.acquire_lease("root", holder="worker", role="coordinator", actor=self.agent)
        report = self.dispatch.orphan_report("root")
        self.assertEqual("active_worker_do_not_redispatch", report["status"])


class PromptTests(DispatchCase):
    def test_prompt_first_line_and_fields(self):
        payload = self.payload()
        prompt = build_worker_prompt(payload)
        self.assertTrue(prompt.startswith("Active task: root\n"))
        for fragment in ("dispatch_id", "src.py", "doc/prd.md", "return_conditions"):
            self.assertIn(fragment, prompt)
        session_payload = self.payload(task_ref="session-only")
        self.assertTrue(build_worker_prompt(session_payload).startswith("Active task: session-only\n"))

    def test_prompt_includes_prior_failure(self):
        payload = self.payload()
        first = self.dispatch.retry_dispatch(payload, failure_reason="transport reset")
        prompt = build_worker_prompt(first["payload"])
        self.assertIn("prior_failure: transport reset", prompt)


class CliTests(DispatchCase):
    def run_cli(self, *argv):
        return main(list(argv))

    def test_dispatch_commands_registered(self):
        parser = build_parser()
        choices = parser._subparsers._group_actions[0].choices
        for command in ("dispatch", "interrupt", "doc-edit"):
            self.assertIn(command, choices)
        # No standalone orphan user command: recovery routes through the
        # parent command face's `continue` (parent design §4.1).
        self.assertNotIn("orphan", choices)
        dispatch_choices = choices["dispatch"]._subparsers._group_actions[0].choices
        for sub in ("implement", "check", "research", "editor", "harvest", "retry", "orphan"):
            self.assertIn(sub, dispatch_choices)

    def test_session_only_dispatch_creates_no_metadata(self):
        payload = self.payload(task_ref="session-only")
        payload_path = Path(self.tmp.name) / "payload.json"
        payload_path.write_text(__import__("json").dumps(payload))
        before = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        code = self.run_cli("--project", str(self.project), "--json", "dispatch", "implement", "--payload", str(payload_path))
        self.assertEqual(0, code)
        after = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        self.assertEqual(before, after)

    def test_persistent_dispatch_via_cli(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        payload_path = Path(self.tmp.name) / "payload.json"
        payload_path.write_text(__import__("json").dumps(payload))
        code = self.run_cli("--project", str(self.project), "--json", "dispatch", "implement", "--payload", str(payload_path))
        self.assertEqual(0, code)
        task = self.store.read("root")
        self.assertIsNotNone(task["lease"])

    def test_harvest_via_cli(self):
        self.create_started()
        self.prepare_artifacts()
        payload = self.payload()
        result = self.result(payload, changed=["src.py"])
        payload_path = Path(self.tmp.name) / "p.json"
        result_path = Path(self.tmp.name) / "r.json"
        payload_path.write_text(__import__("json").dumps(payload))
        result_path.write_text(__import__("json").dumps(result))
        # The CLI path uses the real wall clock while the fixture clock is
        # frozen in 2026, so build the service through the CLI itself and take
        # the lease under that clock.
        import contextlib, io
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "implement", "--payload", str(payload_path))
        self.assertEqual(0, code)
        token = __import__("json").loads(stdout.getvalue())["lease_token"]
        code = self.run_cli("--project", str(self.project), "--json", "dispatch", "harvest",
                            "--payload", str(payload_path), "--result", str(result_path), "--lease-token", token)
        self.assertEqual(0, code)
        self.assertEqual(1, len(self.store.read("root")["evidence"]))

    def test_interrupt_and_doc_edit_via_cli(self):
        self.create_started()
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["editor"], "source": {"type": "test"}}, actor=self.user)
        code = self.run_cli("--project", str(self.project), "--json", "interrupt", "--dispatch-id", "d1", "--reason", "user update", "--mode", "checkpoint_stop", "--tier", "checkpoint-stop")
        self.assertEqual(0, code)
        grant = self.service.store.read("root")["extensions"][0]
        grant_file = Path(self.tmp.name) / "editor.json"
        grant_file.write_text(__import__("json").dumps(grant))
        code = self.run_cli("--project", str(self.project), "--json", "doc-edit", "--file", "doc/prd.md", "--item", "R-001", "--baseline", "abc", "--extension", "@%s" % grant_file)
        self.assertEqual(0, code)

    def test_doc_edit_rejects_wrong_role_and_replaces_forged_persistent_grants(self):
        import contextlib, io, json
        self.create_started()
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["editor"], "source": {"type": "test"}}, actor=self.user)
        stored = self.store.read("root")["extensions"]
        payload = self.payload(role="editor", paths=[".fstar/tasks/root/doc/prd.md"], item_ids=["R-001"], baseline_sha256="abc")
        payload["extensions"] = [dict(stored[0], included=["editor", "design"])]
        path = Path(self.tmp.name) / "editor-payload.json"
        path.write_text(json.dumps(payload))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.run_cli("--project", str(self.project), "--json", "doc-edit", "--payload", str(path))
        self.assertEqual(0, code)
        self.assertEqual(stored, json.loads(stdout.getvalue())["payload"]["extensions"])
        # Revoking the stored grant removes the authority even though the
        # caller keeps presenting an editor record of its own.
        self.service.disable_extension("root", extension_id="planning-review", authorization={"type": "test"}, actor=self.user)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertNotEqual(0, self.run_cli("--project", str(self.project), "--json", "doc-edit", "--payload", str(path)))
        self.assertIn("extension_not_authorized", stderr.getvalue())
        payload = self.payload(task_ref="session-only")
        path.write_text(json.dumps(payload))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(0, self.run_cli("--json", "doc-edit", "--payload", str(path)))

    def test_error_shape_stable(self):
        payload = self.payload(task_ref="session-only")
        payload["role"] = "bogus"
        payload_path = Path(self.tmp.name) / "bad.json"
        payload_path.write_text(__import__("json").dumps(payload))
        import contextlib, io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.run_cli("--project", str(self.project), "--json", "dispatch", "implement", "--payload", str(payload_path))
        self.assertEqual(2, code)
        self.assertIn("invalid_dispatch_payload", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
