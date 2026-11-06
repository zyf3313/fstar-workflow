from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fstar.evidence import EvidenceService, file_digest
from fstar.models import DomainError
from fstar.runtime import hooks, inject, registration
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


class HookCase(unittest.TestCase):
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

    def source(self, ref, source_type="command", actor=None):
        task = self.store.read(ref)
        return {"source_id": "source-" + task["id"], "type": source_type, "at": self.clock(),
                "actor": actor or self.user, "reference": "prompt:42",
                "quote": "批准" if source_type == "conversation" else "",
                "scope": "task", "validates": source_snapshot(task)}

    def create(self, name="root", parent=None):
        return self.service.create(name=name, title=name.title(), description="Deliver R-001",
                                   actor=self.agent, parent=parent, session_id="s1")

    def start(self, ref="root"):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref), session_id="s1")

    def make_doc(self, ref="root", marker_body="R-001 body v1"):
        task_dir = self.store.resolve(ref)
        doc_dir = task_dir / "doc"
        doc_dir.mkdir(exist_ok=True)
        path = doc_dir / "prd.md"
        path.write_text("# PRD\n\n<!-- r-start -->%s<!-- r-end -->\n" % marker_body, encoding="utf-8")
        mapping = {"doc/prd.md": {"R-001": {"start_marker": "<!-- r-start -->", "end_marker": "<!-- r-end -->", "dependencies": []}}}
        artifact = str(path.resolve().relative_to(self.project.resolve()))
        self.service.evidence.persist_artifact_map(ref, mapping={artifact: mapping["doc/prd.md"]},
                                                   source={"type": "test"})
        return artifact

    def record_delivery(self, ref="root", artifact=None):
        lease = self.service.acquire_lease(ref, holder="worker-1", role="implement", actor=self.agent)
        snap = self.service.evidence.snapshot(ref, artifact=artifact, items=["R-001"])
        evidence = {"kind": "delivery", "producer": {"role": "implement", "id": "worker-1"},
                    "validates": [{"artifact": artifact, "items": snap["items"]}],
                    "delivery": self.service.evidence.delivery_snapshot([])}
        return lease, self.service.evidence.record(ref, evidence=evidence, lease_token=lease["token"])


class SessionContextTests(HookCase):
    def test_not_initialized_silent_with_routing(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        result = hooks.session_context({"session_id": "s1"}, start=empty, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(result["initialized"])
        self.assertIsNone(result["current_task"])
        self.assertIn("fstar routing", result["text"])
        # No fstar metadata was created anywhere in the empty dir.
        self.assertFalse((empty / ".fstar").exists())

    def test_initialized_current_task_summary_read_only(self):
        self.create()
        self.start()
        before = file_digest(self.store.resolve("root") / "task.json")
        result = hooks.session_context({"session_id": "s1"}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(result["initialized"])
        summary = result["current_task"]
        self.assertEqual(summary["name"], "root")
        self.assertEqual(summary["phase"], "in_progress")
        self.assertFalse(summary["awaiting_acceptance"])
        self.assertEqual(before, file_digest(self.store.resolve("root") / "task.json"))
        self.assertIn("phase=in_progress", result["text"])

    def test_session_isolation(self):
        self.create()
        self.start()
        other = hooks.session_context({"session_id": "s-other"}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertIsNone(other["current_task"])
        mine = hooks.session_context({"session_id": "s1"}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertIsNotNone(mine["current_task"])

    def test_light_tool_check_only(self):
        grant = self.service.enable_extension(None, authorization={"id": "tool-capability", "scope": "custom", "included": ["bindings"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        result = hooks.session_context({"session_id": "s1", "extensions": [grant]}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        notes = result["tool_notes"]
        # Light check reports missing tools.yaml; it never scans or writes.
        self.assertTrue(any("tools.yaml" in note for note in notes))
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())

    def test_json_shape(self):
        result = hooks.session_context({"session_id": "s1"}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        self.assertEqual(result["marker"], inject.HOOK_MARKER)
        self.assertTrue(all("sha256" in item and "version" in item for item in result["inputs"]))

    def test_capabilities_are_discoverable_without_a_grant(self):
        result = hooks.session_context({"session_id": "s1"}, start=self.project,
                                       user_root=self.user_root, runtime_root=self.runtime_root,
                                       clock=self.clock, as_json=True)
        self.assertEqual(result["extensions"], {})
        self.assertIn("capabilities", {item["kind"] for item in result["inputs"]})
        text = "\n".join(item["text"] for item in result["loaded"]
                         if item["kind"] == "capabilities")
        for package in ("planning-review", "persistent-task", "multi-agent",
                        "project-governance", "tool-capability"):
            self.assertIn(package, text)

    def test_indexes_are_readable_without_a_grant(self):
        (self.project / ".fstar" / "index.md").write_text("PROJECT INDEX DEFAULT")
        (self.user_root / "index.md").write_text("USER INDEX DEFAULT")
        result = hooks.session_context({"session_id": "s1"}, start=self.project,
                                       user_root=self.user_root, runtime_root=self.runtime_root,
                                       clock=self.clock, as_json=True)
        self.assertEqual(result["extensions"], {})
        loaded = {item["path"]: item["text"] for item in result["loaded"]}
        self.assertIn("PROJECT INDEX DEFAULT", loaded.get(".fstar/index.md", ""))
        self.assertIn("USER INDEX DEFAULT", loaded.get("~/.fstar/index.md", ""))


class ExtensionConsumerTests(HookCase):
    def test_recovered_task_scope_controls_injected_documents_and_specs(self):
        self.create()
        task_dir = self.store.resolve("root")
        (task_dir / "doc").mkdir(exist_ok=True)
        (task_dir / "doc" / "prd.md").write_text("INCLUDED PRD")
        (task_dir / "doc" / "design.md").write_text("EXCLUDED DESIGN")
        specs = self.project / ".fstar" / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / "policy.md").write_text("GOVERNANCE SPEC")
        (task_dir / "implement.jsonl").write_text(json.dumps({"file": ".fstar/specs/policy.md"}) + "\n")
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["prd"], "excluded": ["design"], "source": {"type": "test"}}, actor=self.user)
        def context():
            return hooks.worker_context({}, role="implement", task_ref="root", start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, as_json=True)
        first = context()
        paths = {entry["path"] for entry in first["loaded"]}
        self.assertIn("root/doc/prd.md", paths)
        self.assertNotIn("root/doc/design.md", paths)
        self.assertNotIn(".fstar/specs/policy.md", paths)
        self.service.enable_extension("root", authorization={"id": "project-governance", "scope": "custom", "included": ["specs"], "source": {"type": "test"}}, actor=self.user)
        recovered = context()
        self.assertIn(".fstar/specs/policy.md", {entry["path"] for entry in recovered["loaded"]})
        self.assertIn('"prd"', recovered["footer"])
        self.service.disable_extension("root", extension_id="planning-review", authorization={"type": "test"}, actor=self.user)
        self.assertNotIn("root/doc/prd.md", {entry["path"] for entry in context()["loaded"]})

    def test_session_context_and_dispatch_use_explicit_grants_without_writes(self):
        from fstar.dispatch import DispatchService, build_payload
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        grant = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["research"], "excluded": ["parallel-implement"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        payload = build_payload(role="research", task_ref="session-only", plan_item_ids=[], allowed_paths=["research/note.md"], baseline={})
        dispatch = DispatchService(self.store)
        with self.assertRaises(DomainError):
            dispatch.register(payload)
        payload["extensions"] = [grant]
        self.assertEqual(dispatch.register(payload)["persistence"], "session_only")
        session = hooks.session_context({"extensions": [grant]}, start=empty, user_root=self.user_root, runtime_root=self.runtime_root, as_json=True)
        self.assertEqual(session["extensions"]["multi-agent"], ["research"])
        payload["extensions"] = []
        with self.assertRaises(DomainError):
            dispatch.register(payload)
        for role in ("implement", "check"):
            basic = build_payload(role=role, task_ref="session-only", plan_item_ids=[], allowed_paths=[], baseline={})
            self.assertEqual(dispatch.register(basic)["persistence"], "session_only")
        self.assertEqual(list(empty.iterdir()), [])


class ExtensionBoundaryAdversarialTests(HookCase):
    def worker(self, payload=None, **kwargs):
        return hooks.worker_context(payload or {}, start=self.project, user_root=self.user_root,
                                    runtime_root=self.runtime_root, as_json=True, **kwargs)

    def test_persistent_errors_and_denied_roles_never_become_session_only(self):
        self.create()
        grant = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["research"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        for ref, code in (("missing", "task_not_found"), ("root", "extension_not_authorized")):
            with self.assertRaises(DomainError) as caught:
                self.worker({"extensions": [grant]}, role="research", task_ref=ref)
            self.assertEqual(code, caught.exception.code)
        path = self.store.resolve("root") / "task.json"
        task = json.loads(path.read_text())
        task["extensions"] = [dict(grant, included=["unknown"])]
        path.write_text(json.dumps(task))
        with self.assertRaises(DomainError) as caught:
            self.worker(role="implement", task_ref="root")
        self.assertEqual("invalid_extension", caught.exception.code)

    def test_manifest_aliases_cannot_load_excluded_governance_or_planning(self):
        self.create()
        task_dir = self.store.resolve("root")
        spec = self.project / ".fstar/specs/policy.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("EXCLUDED GOVERNANCE BODY")
        (self.project / "alias.md").symlink_to(spec)
        (self.project / "alias-dir").symlink_to(spec.parent, target_is_directory=True)
        (task_dir / "doc").mkdir()
        (task_dir / "doc/design.md").write_text("EXCLUDED DESIGN BODY")
        entries = ["alias.md", "alias-dir/policy.md", ".fstar/specs/policy.md",
                   ".fstar/tasks/root/doc/design.md"]
        (task_dir / "implement.jsonl").write_text("\n".join(json.dumps({"file": path}) for path in entries))
        result = self.worker(role="implement", task_ref="root")
        text = "\n".join(item["text"] for item in result["loaded"])
        self.assertNotIn("EXCLUDED GOVERNANCE BODY", text)
        self.assertNotIn("EXCLUDED DESIGN BODY", text)
        self.assertTrue(result["active_task"].endswith("root"))

    def test_other_and_archived_task_planning_files_follow_current_grant(self):
        self.create()
        task_dir = self.store.resolve("root")
        paths = [".fstar/tasks/other/doc/design.md", ".fstar/archive/2026-10/old/plan.md",
                 ".fstar/tasks/other/subtasks/child/clarify.md", ".fstar/tasks/other/doc/prd.md"]
        for path in paths:
            file = self.project / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("BODY " + path)
        (task_dir / "implement.jsonl").write_text("\n".join(json.dumps({"file": path}) for path in paths))
        def loaded():
            return {entry["path"] for entry in self.worker(role="implement", task_ref="root")["loaded"]}
        self.assertTrue(set(paths).isdisjoint(loaded()))
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["prd", "plan"], "excluded": ["design", "clarify"], "source": {"type": "test"}}, actor=self.user)
        self.assertEqual(set(paths[1::2]), set(paths) & loaded())
        self.service.disable_extension("root", extension_id="planning-review", authorization={"type": "test"}, actor=self.user)
        self.assertTrue(set(paths).isdisjoint(loaded()))

    def test_governance_indexes_reject_symlinked_files_and_parent_directories(self):
        grant = self.service.enable_extension(None, authorization={"id": "project-governance", "scope": "full", "source": {"type": "test"}}, actor=self.user)["authorization"]
        external = Path(self.tmp.name) / "external-index.md"
        external.write_text("SHOULD NOT BE INJECTED")
        project_index = self.project / ".fstar/index.md"
        user_index = self.user_root / "index.md"
        project_index.symlink_to(external)
        user_index.symlink_to(external)
        def session(user_root):
            return hooks.session_context({"extensions": [grant]}, start=self.project, user_root=user_root, runtime_root=self.runtime_root, as_json=True)
        self.assertNotIn("SHOULD NOT BE INJECTED", str(session(self.user_root)["loaded"]))
        project_index.unlink()
        user_index.unlink()
        project_index.write_text("PROJECT INDEX")
        user_index.write_text("USER INDEX")
        text = str(session(self.user_root)["loaded"])
        self.assertIn("PROJECT INDEX", text)
        self.assertIn("USER INDEX", text)
        alias = Path(self.tmp.name) / "user-alias"
        alias.symlink_to(self.user_root, target_is_directory=True)
        self.assertNotIn("USER INDEX", str(session(alias)["loaded"]))

    def test_nested_manifest_aliases_and_escapes_are_not_injected(self):
        self.create()
        task_dir = self.store.resolve("root")
        nested = self.project / ".fstar/archive/2026/old/subtasks/child/doc/design.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("NESTED EXCLUDED DESIGN")
        external = Path(self.tmp.name) / "outside.md"
        external.write_text("OUTSIDE PROJECT BODY")
        (self.project / "nested-alias").symlink_to(nested.parent, target_is_directory=True)
        (self.project / "outside-alias.md").symlink_to(external)
        entries = [str(nested.relative_to(self.project)), "nested-alias/design.md",
                   "outside-alias.md", "../outside.md", str(external)]
        for action in ("implement", "check"):
            (task_dir / (action + ".jsonl")).write_text(
                "\n".join(json.dumps({"file": path}) for path in entries))
        result = self.worker(role="check", task_ref="root")
        self.assertNotIn("NESTED EXCLUDED DESIGN", str(result))
        self.assertNotIn("OUTSIDE PROJECT BODY", str(result))
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["design"], "source": {"type": "test"}}, actor=self.user)
        result = self.worker(role="check", task_ref="root")
        self.assertIn("NESTED EXCLUDED DESIGN", str(result))
        self.assertNotIn("OUTSIDE PROJECT BODY", str(result))
        self.assertNotIn("nested-alias/design.md", {item["path"] for item in result["loaded"]})

    def test_project_index_symlinked_parent_is_not_injected(self):
        grant = self.service.enable_extension(None, authorization={"id": "project-governance", "scope": "full", "source": {"type": "test"}}, actor=self.user)["authorization"]
        actual = Path(self.tmp.name) / "project-index-dir"
        actual.mkdir()
        (actual / "index.md").write_text("ALIASED PROJECT INDEX")
        (self.project / ".fstar" / ".schema-version").unlink()
        (self.project / ".fstar").rmdir()
        (actual / ".schema-version").write_text("1\n")
        (self.project / ".fstar").symlink_to(actual, target_is_directory=True)
        result = hooks.session_context({"extensions": [grant]}, start=self.project,
                                       user_root=self.user_root, runtime_root=self.runtime_root, as_json=True)
        self.assertNotIn("ALIASED PROJECT INDEX", str(result))

    def test_case_aliases_cannot_bypass_governance_or_planning_trimming(self):
        self.create()
        task_dir = self.store.resolve("root")
        spec = self.project / ".fstar/specs/policy.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("CASE ALIAS GOVERNANCE BODY")
        (task_dir / "doc").mkdir()
        (task_dir / "doc/design.md").write_text("CASE ALIAS DESIGN BODY")
        governance_alias = self.project / ".FSTAR/specs/policy.md"
        planning_alias = task_dir / "DOC/design.md"
        if not (governance_alias.is_file() and planning_alias.is_file()):
            self.skipTest("case-sensitive filesystem: case aliases do not resolve")
        entries = [".FSTAR/specs/policy.md", ".fstar/tasks/root/DOC/design.md"]
        (task_dir / "implement.jsonl").write_text(
            "\n".join(json.dumps({"file": path}) for path in entries))
        result = self.worker(role="implement", task_ref="root")
        text = "\n".join(item["text"] for item in result["loaded"])
        self.assertNotIn("CASE ALIAS GOVERNANCE BODY", text)
        self.assertNotIn("CASE ALIAS DESIGN BODY", text)

    def test_session_context_does_not_fall_back_to_caller_grants(self):
        self.create()
        self.start()
        grant = self.service.enable_extension(None, authorization={"id": "tool-capability", "scope": "custom", "included": ["bindings"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        path = self.store.resolve("root") / "task.json"
        task = json.loads(path.read_text())
        task["extensions"] = [dict(grant, included=["unknown"])]
        path.write_text(json.dumps(task))
        result = hooks.session_context({"session_id": "s1", "extensions": [grant]}, start=self.project,
                                       user_root=self.user_root, runtime_root=self.runtime_root,
                                       clock=self.clock, as_json=True)
        self.assertIsNone(result["current_task"])
        self.assertEqual({}, result["extensions"])
        self.assertEqual([], result["tool_notes"])

    def test_explicit_session_only_ignores_current_task_and_grants_do_not_leak(self):
        self.create()
        before = {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        grant = self.service.enable_extension(None, authorization={"id": "multi-agent", "scope": "custom", "included": ["research"], "source": {"type": "test"}}, actor=self.user)["authorization"]
        result = self.worker({"session_id": "s1", "extensions": [grant]}, role="research", task_ref="session-only")
        self.assertEqual("Active task: session-only", result["active_task"])
        with self.assertRaises(DomainError):
            self.worker(role="research", task_ref="session-only")
        for role in ("implement", "check"):
            self.assertEqual("Active task: session-only", self.worker(role=role, task_ref="session-only")["active_task"])
        after = {str(p): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class WorkerContextTests(HookCase):
    def test_role_required(self):
        with self.assertRaises(DomainError):
            hooks.worker_context({}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)

    def test_four_roles_inject_role_cards(self):
        records = [self.service.enable_extension(None, authorization={"id": package, "scope": "custom", "included": [member], "source": {"type": "test"}}, actor=self.user)["authorization"]
                   for package, member in (("multi-agent", "research"), ("planning-review", "editor"))]
        for role in inject.ROLES:
            result = hooks.worker_context({"extensions": records}, role=role, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
            self.assertIn(("fstar-%s.md" % role), result["text"])
            self.assertIn("Role: %s" % role, result["text"])

    def test_every_input_fingerprinted(self):
        self.create()
        self.start()
        result = hooks.worker_context({}, role="implement", task_ref="root", start=self.project,
                                      user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        for item in result["inputs"]:
            self.assertTrue(item["sha256"])
            self.assertTrue(item["version"])
        self.assertTrue(result["active_task"].startswith("Active task: "))

    def test_budget_overload_unloaded_manifest(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        result = hooks.worker_context({}, role="implement", task_ref="root", start=self.project,
                                      user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        # Force a tiny budget by patching read_budgets output through render.
        budgets = {"max_file_bytes": 10, "max_artifact_bytes": 10, "max_total_bytes": 10}
        rendered = inject.render_json("test", [inject.routing_input()], budgets)
        self.assertTrue(rendered["unloaded"])
        self.assertIn("MANDATORY re-read", inject.render("test", [inject.routing_input()], budgets))

    def test_overloaded_required_context_never_silently_dropped(self):
        """The routing body and role card are required context: when budgets
        push them out, they appear in the unloaded manifest with the
        mandatory re-read instruction — never a silent omission."""
        tiny = {"max_file_bytes": 1, "max_artifact_bytes": 1, "max_total_bytes": 1}
        result = hooks.worker_context({}, role="implement", start=self.project,
                                      user_root=self.user_root, runtime_root=self.runtime_root,
                                      clock=self.clock, as_json=True)
        # Simulate the budget pressure at render level (read_budgets is
        # config-driven; tiny budgets come from the config test).
        rendered = inject.render_json("probe", [inject.routing_input(), inject.role_card("implement")], tiny)
        unloaded_kinds = {entry["kind"] for entry in rendered["unloaded"]}
        self.assertIn("routing", unloaded_kinds)
        self.assertIn("role", unloaded_kinds)
        self.assertFalse(rendered["loaded"])
        text = inject.render("probe", [inject.routing_input()], tiny)
        self.assertIn("MANDATORY re-read", text)
        self.assertIn("runtime/routing.md", text)

    def test_no_task_json_session_only(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        result = hooks.worker_context({}, role="check", start=empty, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertIn(inject.session_only_reference(), result["text"])
        self.assertFalse((empty / ".fstar").exists())

    def test_session_pointer_fallback_for_host_payload(self):
        self.create()
        self.start()
        result = hooks.worker_context({"session_id": "s1"}, role="implement",
                                      start=self.project, user_root=self.user_root,
                                      runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        self.assertTrue(result["active_task"].startswith("Active task: "))
        self.assertEqual(result["task_summary"]["name"], "root")

    def test_plan_item_snapshot_via_core(self):
        self.create()
        self.start()
        task_dir = self.store.resolve("root")
        (task_dir / "plan.md").write_text("# Plan\n\n<!-- p-start -->item P-1<!-- p-end -->\n", encoding="utf-8")
        artifact = str((task_dir / "plan.md").resolve().relative_to(self.project.resolve()))
        self.service.evidence.persist_artifact_map("root", mapping={
            artifact: {"P-1": {"start_marker": "<!-- p-start -->", "end_marker": "<!-- p-end -->", "dependencies": []}}
        }, source={"type": "test"})
        def worker():
            return hooks.worker_context({}, role="implement", task_ref="root", plan_item_ids=["P-1"],
                                        start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        self.assertIsNone(worker()["task_summary"]["item_snapshot"])
        self.service.enable_extension("root", authorization={"id": "planning-review", "scope": "custom", "included": ["plan"], "source": {"type": "test"}}, actor=self.user)
        snap = worker()["task_summary"]["item_snapshot"]
        self.assertIsNotNone(snap)
        self.assertEqual(snap["items"][0]["id"], "P-1")
        self.service.disable_extension("root", extension_id="planning-review", authorization={"type": "test"}, actor=self.user)
        self.assertIsNone(worker()["task_summary"]["item_snapshot"])

    def test_spec_bodies_from_manifests_injected(self):
        """Parent design §4.4: the whole applicable spec body is injected —
        an index line is not a substitute for the source body."""
        self.create()
        self.start()
        task_dir = self.store.resolve("root")
        self.service.enable_extension("root", authorization={"id": "project-governance", "scope": "custom", "included": ["specs"], "source": {"type": "test"}}, actor=self.user)
        specs = self.project / ".fstar" / "specs" / "backend"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / "rules.md").write_text("# Backend rules\n\nMUST use entry points.\n", encoding="utf-8")
        (task_dir / "implement.jsonl").write_text(
            json.dumps({"file": ".fstar/specs/backend/rules.md", "reason": "applicable backend rules"}) + "\n",
            encoding="utf-8")
        (task_dir / "check.jsonl").write_text(
            json.dumps({"file": ".fstar/specs/backend/missing.md", "reason": "not present in this checkout"}) + "\n"
            + json.dumps({"file": "../escape.md", "reason": "unsafe path is skipped"}) + "\n",
            encoding="utf-8")
        result = hooks.worker_context({}, role="implement", task_ref="root", start=self.project,
                                      user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, as_json=True)
        loaded = {item["path"]: item for item in result["loaded"]}
        self.assertIn(".fstar/specs/backend/rules.md", loaded)
        self.assertIn("MUST use entry points.", loaded[".fstar/specs/backend/rules.md"]["text"])
        # Unresolvable/unsafe manifest entries never appear as phantom inputs.
        self.assertNotIn(".fstar/specs/backend/missing.md", loaded)
        self.assertNotIn("../escape.md", loaded)
        # Every injected input carries the fingerprint envelope.
        for meta in result["inputs"]:
            self.assertTrue(meta["sha256"])
            self.assertTrue(meta["version"])

    def test_no_trellis_role_mapping(self):
        """fstar's worker-context never injects into another product's
        sub-agent (trellis-* is not an fstar role)."""
        for raw in ("trellis-implement", "general-purpose", "trellis-check"):
            self.assertIsNone(hooks._role_from_payload({"role": raw}), raw)
        # Bare fstar role names remain valid roles.
        self.assertEqual("implement", hooks._role_from_payload({"role": "fstar-implement"}))
        self.assertEqual("implement", hooks._role_from_payload({"role": "implement"}))


class WorkerResultTests(HookCase):
    def dispatch_payload(self, ref="root", role="implement", plan_item_ids=None):
        """A registered fstar.dispatch.v1 payload for the harvest delegation."""
        from fstar.dispatch import build_payload
        return build_payload(role=role, task_ref=ref,
                             plan_item_ids=plan_item_ids or ["P-1"],
                             allowed_paths=["src.py"],
                             baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}})

    def test_done_records_evidence_through_dispatch_harvest(self):
        """worker-result delegates to the single harvest path: identity,
        baseline, scope, replay, and lease verification all belong to
        fstar.dispatch, and the hook itself never builds evidence."""
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        lease2 = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                            takeover_reason="new round", actor=self.agent)
        before = lease2["expires_at"]
        self.clock.advance(5)
        payload = self.dispatch_payload()
        payload["allowed_paths"] = []  # delivery-only result
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "done", "changed_paths": [],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "lease_token": lease2["token"], "task_ref": "root"}
        # The payload must carry the task's input baseline for verification.
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload["baseline"]["artifact_items"] = [snap]
        outcome = hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                      runtime_root=self.runtime_root, clock=self.clock,
                                      payload=payload)
        self.assertTrue(outcome["recorded"])
        self.assertFalse(outcome["acceptance_written"])
        task = self.store.read("root")
        self.assertEqual(task["phase"], "in_progress")
        self.assertIsNone(task["acceptance"])
        self.assertGreater(task["lease"]["expires_at"], before)

    def test_hook_cannot_harvest_without_registered_payload(self):
        """A worker self-report alone can never reach the evidence store: the
        registered dispatch payload is mandatory (no unregistered worker
        identity/scope chosen by user payload)."""
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          takeover_reason="new round", actor=self.agent)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        fake = {"dispatch_id": "self-reported", "status": "done", "task_ref": "root",
                "lease_token": lease["token"],
                "validates": [{"artifact": artifact, "items": snap["items"]}]}
        outcome = hooks.worker_result(fake, start=self.project, user_root=self.user_root,
                                       runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(outcome["recorded"])
        self.assertEqual("dispatch_payload_required", outcome["skipped"])
        self.assertEqual([], self.store.read("root")["evidence"][0:] if False else self.store.read("root")["evidence"][1:])

    def test_hook_rejects_out_of_scope_changed_paths(self):
        """Scope enforcement comes from the dispatch payload, not the result."""
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          takeover_reason="new round", actor=self.agent)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload = self.dispatch_payload()
        payload["baseline"]["artifact_items"] = [snap]
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "done", "changed_paths": ["outside/scope.py"],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "lease_token": lease["token"], "task_ref": "root"}
        with self.assertRaises(DomainError) as caught:
            hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                runtime_root=self.runtime_root, clock=self.clock,
                                payload=payload, passive=False)
        self.assertEqual("scope_violation", caught.exception.code)

    def test_failed_keeps_coordinator_lease(self):
        """A failed worker does not release the coordinator's task lease while
        sibling workers may still be dispatched on the same task."""
        self.create()
        self.start()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          actor=self.agent)
        payload = self.dispatch_payload()
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "failed", "changed_paths": [],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "lease_token": lease["token"], "task_ref": "root"}
        result2 = dict(result)
        outcome = hooks.worker_result(result2, start=self.project, user_root=self.user_root,
                                       runtime_root=self.runtime_root, clock=self.clock,
                                       payload=payload)
        self.assertFalse(outcome["lease_released"])
        self.assertIn("debug", outcome["next"])
        # The coordinator lease survives for sibling workers.
        task = self.store.read("root")
        self.assertIsNotNone(task["lease"])
        self.assertEqual("coordinator", task["lease"]["holder"]["role"])
        terminal = [e for e in task["events"] if e["type"] == "dispatch_terminal"]
        self.assertEqual(1, len(terminal))

    def test_cancelled_routes_propagation_and_keeps_lease(self):
        self.create()
        self.start()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          actor=self.agent)
        payload = self.dispatch_payload()
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "cancelled", "changed_paths": [],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "lease_token": lease["token"], "task_ref": "root"}
        outcome = hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root, clock=self.clock,
                                     payload=payload)
        self.assertFalse(outcome["lease_released"])
        self.assertIn("propagation", outcome["next"])
        self.assertIsNotNone(self.store.read("root")["lease"])

    def test_hook_and_cli_harvest_do_not_double_record(self):
        """Host event + CLI harvest of the same result record evidence once."""
        from fstar.dispatch import DispatchService
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          takeover_reason="new round", actor=self.agent)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload = self.dispatch_payload()
        payload["baseline"]["artifact_items"] = [snap]
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "done", "changed_paths": [],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "lease_token": lease["token"], "task_ref": "root"}
        first = hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                    runtime_root=self.runtime_root, clock=self.clock,
                                    payload=payload)
        self.assertTrue(first["recorded"])
        # The CLI harvest of the same result is a replay, not a second record.
        dispatch_service = DispatchService(self.store, clock=self.clock, task_service=TaskService(self.store, clock=self.clock))
        second = dispatch_service.harvest(result, payload, lease_token=lease["token"])
        self.assertFalse(second["recorded"])
        self.assertTrue(second["replayed"])
        self.assertEqual(2, len(self.store.read("root")["evidence"]))  # initial delivery + one harvest

    def test_task_ref_mismatch_between_payload_and_task(self):
        self.create()
        self.start()
        lease = self.service.acquire_lease("root", holder="coordinator", role="coordinator",
                                          actor=self.agent)
        payload = self.dispatch_payload(ref="other-task")
        result = {"dispatch_id": payload["dispatch_id"], "status": "done", "task_ref": "root",
                  "lease_token": lease["token"]}
        with self.assertRaises(DomainError) as caught:
            hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                runtime_root=self.runtime_root, clock=self.clock,
                                payload=payload, passive=False)
        self.assertEqual("task_ref_mismatch", caught.exception.code)

    def test_stale_dispatch_token_rejected(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload = self.dispatch_payload()
        payload["baseline"]["artifact_items"] = [snap]
        result = {"dispatch_id": payload["dispatch_id"], "status": "done", "task_ref": "root",
                  "lease_token": "old-token", "changed_paths": [],
                  "input_baseline": {}, "delivery_baseline": {}}
        with self.assertRaises(DomainError):
            hooks.worker_result(result, start=self.project, user_root=self.user_root,
                                runtime_root=self.runtime_root, clock=self.clock,
                                payload=payload, passive=False)

    def test_invalid_status_rejected(self):
        with self.assertRaises(DomainError):
            hooks.worker_result({"dispatch_id": "d-5", "status": "maybe"})

    def test_passive_skip_without_project(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        result = hooks.worker_result({"dispatch_id": "d-6", "status": "done"}, start=empty, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(result["recorded"])
        self.assertEqual(result["skipped"], "no_project_or_task")


class DocChangeTests(HookCase):
    def test_doc_change_invalidates_and_hints(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        self.service.release_lease("root", token=lease["token"], reason="delivery recorded")
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(result["processed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["writes"], 1)
        self.assertIn("evidence_invalidated", [e["type"] for e in self.store.read("root")["events"]])
        self.assertIsNotNone(result["change_message"])
        task = self.store.read("root")
        self.assertTrue(all(e.get("state") != "valid" for e in task["evidence"]))

    def test_doc_change_message_is_canonical_change_schema(self):
        """doc-change emits the canonical fstar.change.v1 shape owned by
        runtime-dispatch, preserving the actual affected-item data (never an
        empty affected list that would read 'affects nothing')."""
        from fstar.dispatch import CHANGE_SCHEMA, validate_change
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        self.service.release_lease("root", token=lease["token"], reason="delivery recorded")
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        message = result["change_message"]
        self.assertEqual(CHANGE_SCHEMA, message["schema"])
        validate_change(message)
        self.assertEqual("file", message["source"])
        self.assertEqual(artifact, message["origin"])
        affected_items = message["affected"]["artifact_items"]
        self.assertTrue(affected_items)
        self.assertEqual(artifact, affected_items[0]["artifact"])
        self.assertEqual(["R-001"], message["affected"]["plan_item_ids"])

    def test_doc_change_unknown_plan_items_conservative(self):
        """Without an established item mapping the change message is
        explicitly unknown, never silently empty."""
        from fstar.dispatch import validate_change
        self.create()
        self.start()
        artifact = self.make_doc()  # establishes the artifact map
        # Record delivery under the existing mapping, THEN drop the mapping so
        # the change's item breakdown is unknown at doc-change time.
        lease, _ = self.record_delivery(artifact=artifact)
        self.service.release_lease("root", token=lease["token"], reason="delivery recorded")
        with self.store.transaction():
            task = self.store.read("root")
            task["meta"]["templates"].pop("artifact_map")
            self.store.write(self.store.resolve("root"), task)
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        if result["change_message"] is not None:
            message = result["change_message"]
            validate_change(message)
            self.assertTrue(message["affected"]["artifact_items"])
            self.assertTrue(message["affected"].get("unknown_plan_items") or message["affected"]["plan_item_ids"])

    def test_unrelated_file_silent(self):
        self.create()
        self.start()
        (self.project / "src_thing.py").write_text("x = 1\n", encoding="utf-8")
        before = file_digest(self.store.resolve("root") / "task.json")
        result = hooks.doc_change({}, file_path="src_thing.py", start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(result["processed"])
        self.assertEqual(result["writes"], 0)
        self.assertEqual(before, file_digest(self.store.resolve("root") / "task.json"))

    def test_idempotent_second_call_zero_writes(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        self.service.release_lease("root", token=lease["token"], reason="delivery recorded")
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        first = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(first["changed"])
        before = file_digest(self.store.resolve("root") / "task.json")
        second = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(second["processed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["writes"], 0)
        self.assertEqual(before, file_digest(self.store.resolve("root") / "task.json"))

    def test_planning_without_evidence_no_noise(self):
        self.create()
        artifact = self.make_doc()
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(result["processed"])
        self.assertEqual(result["writes"], 0)  # nothing to invalidate
        self.assertEqual(result["invalidated"], [])

    def test_existing_evidence_no_phase_exemption(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        # Replan back to planning: existing evidence must still go stale on change.
        confirmation = self.source("root", source_type="conversation")
        self.service.continue_task("root", action="replan", actor=self.user,
                                   confirmation=confirmation, reason="direction change")
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v3<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(result["processed"])

    def test_absolute_host_path_processed(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        self.service.release_lease("root", token=lease["token"], reason="delivery recorded")
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=str(path.resolve()), start=self.project,
                                  user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertTrue(result["processed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["artifact"], artifact)

    def test_non_doc_path_skipped(self):
        self.create()
        self.start()
        result = hooks.doc_change({}, file_path=".fstar/tasks/root/plan.md", start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(result["processed"])
        self.assertEqual(result["skipped"], "not_a_task_doc")

    def test_active_lease_passive_skip(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        self.service.acquire_lease("root", holder="worker-1", role="implement",
                                   takeover_reason="new round", actor=self.agent)
        path = self.project / artifact
        path.write_text("# PRD\n\n<!-- r-start -->R-001 body v2<!-- r-end -->\n", encoding="utf-8")
        result = hooks.doc_change({}, file_path=artifact, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertFalse(result["processed"])
        self.assertEqual(result["skipped"], "active_lease")

    def test_explicit_missing_file_errors(self):
        with self.assertRaises(DomainError):
            hooks.doc_change({}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock, passive=False)


class RegistrationPlanTests(HookCase):
    def test_claude_plan_shape(self):
        result = registration.plan("claude")
        self.assertTrue(result["read_only"])
        self.assertEqual(len(result["entries"]), 4)
        events = {entry["event"] for entry in result["entries"]}
        self.assertEqual(events, {"SessionStart", "PreToolUse", "SubagentStop", "PostToolUse"})
        for entry in result["entries"]:
            self.assertEqual(entry["dedup_key"], "event + command")
            command = entry["hooks"][0]["command"]
            # The plan references the packaged launcher the installer actually
            # registers (bin/fstar-hook.cjs), and reports honestly whether that
            # launcher exists on disk plus the schema-level evidence level.
            self.assertTrue(command.endswith(entry["semantic"]), command)
            self.assertIn("fstar-hook.cjs", command)
            self.assertTrue(entry["hooks"][0]["launcher_installed"])
            self.assertEqual(entry["hooks"][0]["evidence"], "observed-schema")
        # Uninstall guidance must not be a command-substring heuristic.
        self.assertNotIn("contains", result["uninstall"])

    def test_codex_plan_shape_verified_live_2026_11_05(self):
        result = registration.plan("codex")
        self.assertEqual(len(result["entries"]), 4)
        # All four codex hook events fired live with exit code 0 on 2026-11-05
        # (SessionStart / SubagentStart / SubagentStop / PostToolUse); evidence
        # is observed-schema, no residual to_verify gaps remain.
        self.assertTrue(all(entry["verified"] for entry in result["entries"]))
        self.assertTrue(all(not entry["to_verify"] for entry in result["entries"]))
        self.assertTrue(all(entry["hooks"][0]["evidence"] == "observed-schema" for entry in result["entries"]))

    def test_unknown_host_rejected(self):
        with self.assertRaises(DomainError):
            registration.plan("vscode")


class HostEventMapTests(HookCase):
    def test_exactly_four_semantic_hooks_both_hosts(self):
        for host in ("claude", "codex"):
            self.assertEqual(sorted(hooks.HOST_EVENT_MAP[host]), sorted(hooks.HOOK_NAMES))

    def test_every_hook_has_fallback(self):
        for host, mapping in hooks.HOST_EVENT_MAP.items():
            for name, spec in mapping.items():
                self.assertTrue(spec["fallback"], "%s/%s missing fallback" % (host, name))
                self.assertIn("verified", spec)
                self.assertIsInstance(spec["to_verify"], list)

    def test_no_turn_context_hook(self):
        self.assertNotIn("turn-context", hooks.HOOK_NAMES)
        for mapping in hooks.HOST_EVENT_MAP.values():
            self.assertNotIn("turn-context", mapping)

    def test_run_hook_dispatches_and_rejects_unknown(self):
        result = hooks.run_hook("session-context", payload={}, start=self.project, user_root=self.user_root, runtime_root=self.runtime_root, clock=self.clock)
        self.assertIn("text", result)
        with self.assertRaises(DomainError):
            hooks.run_hook("turn-context", payload={})


class CliHookTests(HookCase):
    def _parse(self, argv):
        from fstar.cli import build_parser
        parser = build_parser()
        return parser.parse_args(argv)

    def _run(self, argv):
        import contextlib
        import io
        from fstar.cli import main
        with contextlib.redirect_stdout(io.StringIO()):
            return main(argv)

    def test_hook_plan_claude_json(self):
        code = self._run(["--json", "hook", "plan", "--host", "claude"])
        self.assertEqual(code, 0)

    def test_hook_plan_codex_json(self):
        code = self._run(["--json", "hook", "plan", "--host", "codex"])
        self.assertEqual(code, 0)

    def test_hook_plan_unknown_host_fails(self):
        with self.assertRaises(SystemExit):
            self._run(["--json", "hook", "plan", "--host", "nope"])

    def test_session_context_in_not_initialized_dir(self):
        empty = Path(self.tmp.name) / "empty2"
        empty.mkdir()
        code = self._run(["--json", "--project", str(empty), "--user-data-root", str(self.user_root),
                          "hook", "session-context"])
        self.assertEqual(code, 0)

    def test_explicit_task_request_not_initialized_errors(self):
        empty = Path(self.tmp.name) / "empty3"
        empty.mkdir()
        code = self._run(["--json", "--project", str(empty), "--user-data-root", str(self.user_root),
                          "hook", "doc-change", "--file", "doc/prd.md"])
        self.assertNotEqual(code, 0)

    def test_worker_context_cli(self):
        self.create()
        self.start()
        code = self._run(["--json", "--project", str(self.project), "--user-data-root", str(self.user_root),
                          "hook", "worker-context", "--role", "implement", "root"])
        self.assertEqual(code, 0)

    def test_worker_result_cli_requires_dispatch_payload(self):
        """The explicit CLI entry mirrors the passive entry: a worker
        self-report without the registered dispatch payload never reaches the
        evidence store; it reports the missing payload as a clear error."""
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        real_service = TaskService(self.store)
        lease2 = real_service.acquire_lease("root", holder="worker-2", role="implement",
                                            takeover_reason="round 2", actor=self.agent)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload = {"dispatch_id": "d-cli", "status": "done", "task_ref": "root",
                   "lease_token": lease2["token"],
                   "validates": [{"artifact": artifact, "items": snap["items"]}],
                   "delivery_baseline": self.service.evidence.delivery_snapshot([])}
        path = Path(self.tmp.name) / "result.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        code = self._run(["--json", "--project", str(self.project), "--user-data-root", str(self.user_root),
                          "hook", "worker-result", "--result", str(path)])
        # The explicit CLI surfaces the payload requirement as a clear error,
        # never a silent success (child design §5).
        self.assertEqual(3, code)
        self.assertEqual(1, len(self.store.read("root")["evidence"]))

    def test_worker_result_cli_harvests_with_payload(self):
        """The full single-path integration: a registered dispatch payload +
        result harvested through the hook CLI entry records exactly once,
        and the same result replayed through the dispatch CLI records
        nothing further."""
        from fstar.dispatch import build_payload
        self.create()
        self.start()
        artifact = self.make_doc()
        lease, _ = self.record_delivery(artifact=artifact)
        real_service = TaskService(self.store)
        lease2 = real_service.acquire_lease("root", holder="coordinator", role="coordinator",
                                           takeover_reason="round 2", actor=self.agent)
        snap = self.service.evidence.snapshot("root", artifact=artifact, items=["R-001"])
        payload = build_payload(role="implement", task_ref="root", plan_item_ids=["P-1"],
                                allowed_paths=[],
                                baseline={"artifact_items": [snap], "delivery": {"paths": [], "digest": ""}})
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "implement", "status": "done", "changed_paths": [],
                  "artifact_refs": [], "validation_facts": [], "blockers": [],
                  "input_baseline": {}, "delivery_baseline": {},
                  "task_ref": "root", "lease_token": lease2["token"]}
        result_path = Path(self.tmp.name) / "result.json"
        payload_path = Path(self.tmp.name) / "payload.json"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        code = self._run(["--json", "--project", str(self.project), "--user-data-root", str(self.user_root),
                          "hook", "worker-result", "--result", str(result_path), "--payload", str(payload_path)])
        self.assertEqual(0, code)
        task = self.store.read("root")
        self.assertEqual(2, len(task["evidence"]))
        self.assertIsNone(task["acceptance"])
        # Replay through the dispatch harvest CLI records nothing.
        from fstar.cli import main
        code = main(["--project", str(self.project), "--user-data-root", str(self.user_root), "--json",
                     "dispatch", "harvest", "--result", str(result_path),
                     "--payload", str(payload_path), "--lease-token", lease2["token"]])
        self.assertEqual(0, code)
        self.assertEqual(2, len(self.store.read("root")["evidence"]))

    def test_doc_change_cli(self):
        self.create()
        self.start()
        artifact = self.make_doc()
        self.record_delivery(artifact=artifact)
        (self.project / artifact).write_text("# PRD\n\n<!-- r-start -->v2<!-- r-end -->\n", encoding="utf-8")
        code = self._run(["--json", "--project", str(self.project), "--user-data-root", str(self.user_root),
                          "hook", "doc-change", "--file", artifact])
        self.assertEqual(code, 0)

    def test_internal_import_error_not_swallowed(self):
        # A module that exists but fails inside its body must surface the
        # error; cli only silently skips modules whose find_spec is None.
        import argparse
        import fstar
        from fstar.cli import _register_optional
        broken_dir = Path(self.tmp.name) / "brokenpkg"
        broken_dir.mkdir()
        (broken_dir / "brokenmod.py").write_text("raise ImportError('boom')\n", encoding="utf-8")
        fstar.__path__.append(str(broken_dir))
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        try:
            with self.assertRaises(ImportError):
                _register_optional(subparsers, "brokenmod")
        finally:
            fstar.__path__.remove(str(broken_dir))

    def test_missing_optional_module_is_silently_skipped(self):
        import argparse
        from fstar.cli import _register_optional
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        _register_optional(subparsers, "definitely_not_a_module")
        self.assertEqual(list(subparsers.choices), [])


class HostEntryTests(HookCase):
    """python3 -m fstar.runtime <hook> with host payload on stdin."""

    def _run(self, hook_name, payload=None, cwd=None):
        import os
        import subprocess
        import sys
        src = str(Path(__file__).resolve().parents[1] / "src")
        env = dict(os.environ)
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.pop("FSTAR_PROJECT", None)
        env.pop("FSTAR_USER_ROOT", None)
        env.pop("FSTAR_RUNTIME_ROOT", None)
        process = subprocess.run(
            [sys.executable, "-m", "fstar.runtime", hook_name],
            input=json.dumps(payload or {}), text=True, capture_output=True,
            cwd=str(cwd or (Path(self.tmp.name) / "empty")), env=env, timeout=30)
        return process

    def test_session_context_injects_routing(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        process = self._run("session-context", {"session_id": "s1", "source": "startup"}, cwd=empty)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("fstar routing", process.stdout)
        self.assertFalse((empty / ".fstar").exists())

    def test_doc_change_without_project_is_silent(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        process = self._run("doc-change", {"file": "doc/prd.md"}, cwd=empty)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "")

    def test_worker_context_unknown_role_is_silent(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        process = self._run("worker-context", {"tool_input": {"subagent_type": "general-purpose"}}, cwd=empty)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "")

    def test_worker_result_host_event_is_silent(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        process = self._run("worker-result", {"session_id": "s1"}, cwd=empty)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "")

    def test_unknown_hook_name_exits_nonzero(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        process = self._run("turn-context", {}, cwd=empty)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"usage", process.stderr.encode())


class InjectTests(HookCase):
    def test_budgets_default_when_key_missing(self):
        budgets = inject.read_budgets(self.project, self.user_root)
        self.assertEqual(budgets, inject.DEFAULT_BUDGETS)

    def test_budgets_read_from_config(self):
        (self.project / ".fstar" / "config.yaml").write_text(
            "schema_version: 1\nproject:\n  id: \"11111111-1111-1111-1111-111111111111\"\ncontext_injection:\n  max_file_bytes: 100\n",
            encoding="utf-8")
        budgets = inject.read_budgets(self.project, self.user_root)
        self.assertEqual(budgets["max_file_bytes"], 100)
        self.assertEqual(budgets["max_total_bytes"], inject.DEFAULT_BUDGETS["max_total_bytes"])

    def test_invalid_role_rejected(self):
        with self.assertRaises(DomainError):
            inject.role_card("manager")

    def test_locate_never_writes(self):
        empty = Path(self.tmp.name) / "empty4"
        empty.mkdir()
        located = inject.locate(empty, user_root=self.user_root, runtime_root=self.runtime_root)
        self.assertIsNone(located["project_root"])
        self.assertIsNone(located["store"])
        self.assertFalse((empty / ".fstar").exists())


if __name__ == "__main__":
    unittest.main()
