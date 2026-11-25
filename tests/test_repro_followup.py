"""Isolated regressions for the verified 0.11.1 follow-up.

The CLI scenario uses real subprocesses and supported commands; no task.json
repair, host services, or live project/user state is involved. Its check
producer is a protocol fixture, not an independent review of this change.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fstar.cli import main
from fstar.dispatch import DispatchService, build_payload, build_result
from fstar.evidence import file_digest
from fstar.models import DomainError
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot

REPO = Path(__file__).resolve().parents[1]


class FollowupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fstar-followup-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / ".fstar").mkdir()
        (self.project / ".fstar/.schema-version").write_text("1\n")
        self.user = self.root / "user"
        self.runtime = self.root / "runtime"
        self.store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        self.now = "2026-11-24T10:00:00Z"
        self.tasks = TaskService(self.store, clock=lambda: self.now)
        self.dispatch = DispatchService(self.store, task_service=self.tasks)
        self.actor = {"role": "user", "id": "fixture"}
        self.tasks.create(name="root", title="Root", description="Fixture", actor=self.actor)
        self.tasks.start("root", actor=self.actor, confirmation=self.confirmation())

    def confirmation(self):
        return {"source_id": "fixture", "type": "command", "at": self.now,
                "actor": self.actor, "reference": "isolated-test", "quote": "",
                "scope": "task", "validates": source_snapshot(self.store.read("root"))}

    def payload(self, **kwargs):
        return build_payload(role=kwargs.pop("role", "implement"), task_ref="root",
                             plan_item_ids=["P-1"], allowed_paths=["product.py"],
                             baseline={}, **kwargs)

    def task_bytes(self):
        return (self.store.resolve("root") / "task.json").read_bytes()

    def assert_domain(self, code, operation):
        before = self.task_bytes()
        with self.assertRaises(DomainError) as caught:
            operation()
        self.assertEqual(code, caught.exception.code)
        self.assertEqual(before, self.task_bytes())

    def cli(self, *args, stdin=None, expected=0, project=None):
        command = [sys.executable, "-m", "fstar", "--json", "--project", str(project or self.project),
                   "--user-data-root", str(self.user), "--runtime-root", str(self.runtime), *args]
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        started = time.monotonic()
        run = subprocess.run(command, input=stdin, text=True, capture_output=True,
                             cwd=self.root, env=env, timeout=20)
        self.log_run(command, run, time.monotonic() - started)
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout if run.returncode == 0 else run.stderr)

    @staticmethod
    def log_run(command, run, duration):
        if os.environ.get("FSTAR_FOLLOWUP_LOG"):
            with Path(os.environ["FSTAR_FOLLOWUP_LOG"]).open("a") as log:
                log.write(json.dumps({"command": command, "exit_code": run.returncode,
                                      "stdout": run.stdout, "stderr": run.stderr,
                                      "duration_seconds": duration}) + "\n")

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return str(path)


class SchemaEvidenceTests(FollowupCase):
    def test_cli_example_records_valid_and_detects_stale_delivery(self):
        example = self.cli("schema", "evidence")["example"]
        (self.project / "example.txt").write_bytes(b"hello\n")
        self.tasks.register_deliverable("root", actor=self.actor, entry={
            "name": "example", "path": "example.txt", "criteria_refs": ["A-001"]})
        self.assertEqual(example["validates"][0], self.tasks.evidence.snapshot(
            "root", artifact="example.txt", items=["A-001"]))
        self.assertEqual(example["delivery"], self.tasks.evidence.delivery_snapshot(["example.txt"]))
        payload = build_payload(role="check", task_ref="root", plan_item_ids=["P-001"],
                                allowed_paths=[], baseline={})
        token = self.dispatch.register(payload)["lease_token"]
        recorded = self.tasks.evidence.record("root", evidence=example, lease_token=token)
        self.assertEqual("valid", recorded["state"])
        (self.project / "example.txt").write_bytes(b"changed\n")
        self.assertIn("delivery", {reason["type"] for reason in
                                   self.tasks.evidence._validate_current(recorded, "root")})

    def test_digest_uses_sorted_raw_bytes_and_item_uses_normalized_text(self):
        import hashlib
        (self.project / "example.txt").write_bytes(b"hello\r\n")
        self.tasks.register_deliverable("root", actor=self.actor, entry={
            "name": "example", "path": "example.txt", "criteria_refs": ["A-001"]})
        snapshot = self.tasks.evidence.delivery_snapshot(["missing", "example.txt", "missing"])
        entries = [{"path": "example.txt", "exists": True,
                    "sha256": hashlib.sha256(b"hello\r\n").hexdigest()},
                   {"path": "missing", "exists": False, "sha256": None}]
        encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual({"paths": entries, "digest": hashlib.sha256(encoded).hexdigest()}, snapshot)
        item = self.tasks.evidence.snapshot("root", artifact="example.txt", items=["A-001"])
        self.assertEqual(hashlib.sha256(b"hello\n").hexdigest(), item["items"][0]["sha256"])
        self.assertNotEqual(entries[0]["sha256"], item["items"][0]["sha256"])
        from fstar.dispatch import validate_payload, validate_result
        validate_payload(self.cli("schema", "payload")["example"])
        result = self.cli("schema", "result")["example"]
        self.assertEqual({}, result["input_baseline"])
        self.assertEqual({}, result["delivery_baseline"])
        validate_result(result)


class EvidenceRegistrationTests(FollowupCase):
    def register(self, criteria=None, path="product.py", name="product"):
        return self.tasks.register_deliverable("root", actor=self.actor,
            entry={"name": name, "path": path, "criteria_refs": criteria or []})

    def test_explicit_scope_default_scope_and_unknown_items(self):
        (self.project / "product.py").write_text("value = 42\n")
        self.register(["A-1"])
        snapshot = self.tasks.evidence.snapshot("root", artifact="product.py", items=["A-1"])
        self.assertEqual("file", snapshot["granularity"])
        self.assert_domain("mapping_missing", lambda: self.tasks.evidence.snapshot(
            "root", artifact="product.py", items=["invented"]))
        self.register()
        self.assertEqual("file", self.tasks.evidence.snapshot(
            "root", artifact="product.py", items=["product.py"])["granularity"])
        self.assert_domain("mapping_missing", lambda: self.tasks.evidence.snapshot(
            "root", artifact="product.py", items=["A-1"]))

    def test_mixed_mapping_dependency_and_file_freshness(self):
        doc = self.project / "criteria.txt"
        doc.write_text("<a>first</a><b>dependency</b><c>unrelated</c>")
        mapping = {"criteria.txt": {
            "A": {"start_marker": "<a>", "end_marker": "</a>", "dependencies": ["B"]},
            "B": {"start_marker": "<b>", "end_marker": "</b>"},
            "C": {"start_marker": "<c>", "end_marker": "</c>"}}}
        self.tasks.evidence.persist_artifact_map("root", mapping=mapping, source={"type": "test"})
        (self.project / "product.py").write_text("value = 42\n")
        self.register(["D"])
        self.register(["ignored"], path="criteria.txt", name="criteria")
        evidence = {"validates": [self.tasks.evidence.snapshot("root", artifact="criteria.txt", items=["A"]),
                                   self.tasks.evidence.snapshot("root", artifact="product.py", items=["D"])]}
        self.assertEqual(["item", "file"], [v["granularity"] for v in evidence["validates"]])
        doc.write_text(doc.read_text().replace("unrelated", "unrelated changed"))
        self.assertEqual([], self.tasks.evidence._validate_current(evidence, "root"))
        doc.write_text(doc.read_text().replace("dependency", "dependency changed"))
        self.assertIn("dependency_changed", {r["type"] for r in self.tasks.evidence._validate_current(evidence, "root")})
        (self.project / "product.py").write_text("value = 43\n")
        self.assertTrue(any(r.get("artifact") == "product.py" for r in self.tasks.evidence._validate_current(evidence, "root")))

    def test_unsafe_registration_does_not_mutate(self):
        (self.root / "external").mkdir()
        (self.project / "link").symlink_to(self.root / "external", target_is_directory=True)
        for path in ("../escape", str(self.root / "absolute"), ".", "link/missing", "mode", "./mode", " x", "bad\x00path"):
            with self.subTest(path=path):
                self.assert_domain("unsafe_evidence_path", lambda: self.register(["A"], path=path))

    def test_empty_legacy_map_does_not_grant_scope(self):
        (self.project / "product.py").write_text("value = 42\n")
        self.tasks.evidence.persist_artifact_map("root", mapping={"product.py": {}}, source={})
        self.assert_domain("mapping_missing", lambda: self.tasks.evidence.snapshot(
            "root", artifact="product.py", items=["anything"]))
        self.register(["A"])
        self.assertEqual("file", self.tasks.evidence.snapshot("root", artifact="product.py", items=["A"])["granularity"])


class RegistrationReplayTests(FollowupCase):
    def test_parallel_retries_and_failed_persistence_are_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        payload = self.payload()
        before = self.task_bytes()
        with patch.object(self.store, "write", side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                self.dispatch.register(payload)
        self.assertEqual(before, self.task_bytes())
        self.assertIsNone(self.store.read("root")["lease"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: DispatchService(self.store, clock=lambda: self.now).register(payload), range(4)))
        self.assertEqual(1, sum(not reply.get("existing_registration") for reply in replies))
        self.assertEqual(1, len({reply["lease_token"] for reply in replies}))
        self.assertEqual(1, sum(e["type"] == "dispatch_registered" for e in self.store.read("root")["events"]))

    def test_legacy_registration_requires_new_id_without_rewriting_history(self):
        from fstar.tasks import make_event
        payload = self.payload()
        with self.store.transaction():
            task = self.store.read("root")
            task["events"].append(make_event("dispatch_registered", {},
                {"dispatch_id": payload["dispatch_id"]}, self.now))
            self.store.write(self.store.resolve("root"), task)
        self.assert_domain("dispatch_identity_unknown", lambda: self.dispatch.register(payload))
        self.assertTrue(self.dispatch.register(self.payload())["registered"])

    def test_four_retries_compaction_and_process_recovery(self):
        payload = self.payload()
        first = self.dispatch.register(payload)
        before = self.task_bytes()
        for _ in range(4):
            recovered = DispatchService(self.store, clock=lambda: self.now)
            reply = recovered.register(dict(reversed(list(payload.items()))))
            self.assertTrue(reply["existing_registration"])
            self.assertEqual(first["lease_token"], reply["lease_token"])
        self.assertEqual(before, self.task_bytes())
        self.assertEqual(1, sum(e["type"] == "dispatch_registered" for e in self.store.read("root")["events"]))
        for index in range(210):
            self.tasks.set_next_step("root", actor=self.actor, condition="test", action=str(index))
        self.assertFalse(any(e["type"] == "dispatch_registered" for e in self.store.read("root")["events"]))
        before = self.task_bytes()
        self.assertTrue(self.dispatch.register(payload)["existing_registration"])
        self.assertEqual(before, self.task_bytes())

    def test_entire_effective_payload_identity_and_harvest(self):
        payload = self.payload()
        token = self.dispatch.register(payload)["lease_token"]
        changes = {"allowed_paths": ["other.py"], "role": "check", "input_versions": [{"path": "x", "sha256": "y"}],
                   "item_ids": ["X"], "baseline_sha256": "other", "prior_failure": {"reason": "x", "dispatch_id": "old"},
                   "selected_skills": [{"skill": "test", "reason": "changed"}], "future_field": {"x": 1}}
        for field, value in changes.items():
            altered = dict(payload, **{field: value})
            with self.subTest(field=field):
                self.assert_domain("dispatch_id_conflict", lambda: self.dispatch.register(altered))
        altered = dict(payload, allowed_paths=["other.py"])
        result = build_result(dispatch_id=payload["dispatch_id"], role="implement", status="failed")
        self.assert_domain("dispatch_id_conflict", lambda: self.dispatch.harvest(result, altered, lease_token=token))

    def test_editor_fields_and_authoritative_extensions(self):
        self.tasks.enable_extension("root", authorization={"id": "planning-review", "scope": "custom",
            "included": ["editor"], "excluded": [], "source": {"type": "test"}}, actor=self.actor)
        payload = self.payload(role="editor", item_ids=["A"], baseline_sha256="first")
        token = self.dispatch.register(payload)["lease_token"]
        for field, value in (("item_ids", ["B"]), ("baseline_sha256", "second")):
            self.assert_domain("dispatch_id_conflict", lambda: self.dispatch.register(dict(payload, **{field: value})))
        # Caller-supplied extensions are overwritten by persisted grants.
        self.assertTrue(self.dispatch.register(dict(payload, extensions=[]))["existing_registration"])
        self.tasks.release_lease("root", token=token, reason="fixture")
        self.tasks.enable_extension("root", authorization={"id": "multi-agent", "scope": "custom",
            "included": ["research"], "excluded": [], "source": {"type": "test"}}, actor=self.actor)
        self.assert_domain("dispatch_id_conflict", lambda: self.dispatch.register(payload))

    def test_expiry_release_and_other_holder_never_reacquire_on_replay(self):
        payload = self.payload()
        token = self.dispatch.register(payload)["lease_token"]
        self.now = "2026-11-24T11:00:00Z"
        before = self.task_bytes()
        replay = self.dispatch.register(payload)
        self.assertTrue(replay["recovery_required"])
        self.assertIsNone(replay["lease_token"])
        self.assertEqual(before, self.task_bytes())
        self.tasks.release_lease("root", token=token, reason="fixture")
        before = self.task_bytes()
        self.assertIsNone(self.dispatch.register(payload)["lease_token"])
        self.assertEqual(before, self.task_bytes())
        self.tasks.acquire_lease("root", holder="other", role="coordinator")
        self.assert_domain("lease_conflict", lambda: self.dispatch.register(payload))

    def test_terminal_and_interrupted_work_stays_terminal(self):
        payload = self.payload()
        token = self.dispatch.register(payload)["lease_token"]
        self.dispatch.interrupt(payload["dispatch_id"], reason="stop", mode="checkpoint_stop",
                                task_ref="root", release_lease_token=token)
        before = self.task_bytes()
        replay = self.dispatch.register(payload)
        self.assertEqual("interrupted", replay["registration_state"])
        self.assertIsNone(replay["lease_token"])
        self.assertEqual(before, self.task_bytes())
        for status in ("failed", "cancelled", "done", "blocked"):
            with self.subTest(status=status):
                payload = self.payload()
                token = self.dispatch.register(payload)["lease_token"]
                self.dispatch.harvest(build_result(dispatch_id=payload["dispatch_id"], role="implement", status=status),
                                      payload, lease_token=token)
                before = self.task_bytes()
                replay = self.dispatch.register(payload)
                self.assertEqual("harvested", replay["registration_state"])
                self.assertIsNone(replay["lease_token"])
                self.assertEqual(before, self.task_bytes())


class CLIInputAndEvidenceTests(FollowupCase):
    def test_invalid_stdin_is_immutable_and_duplicate_consumers_preflight(self):
        before = self.task_bytes()
        for text in ("", "{", "[]", "null", "{} {}"):
            reply = self.cli("dispatch", "implement", "--payload", "-", stdin=text, expected=2)
            self.assertEqual("invalid_json_file", reply["error"]["code"])
            self.assertEqual(before, self.task_bytes())
        reply = self.cli("dispatch", "harvest", "--result", "-", "--payload", "-", "--lease-token", "x", stdin="", expected=2)
        self.assertEqual("stdin_document_reuse", reply["error"]["code"])
        self.assertEqual(before, self.task_bytes())

    def test_repeated_main_invocations_each_get_their_own_stdin(self):
        payload = build_payload(role="implement", task_ref="session-only", plan_item_ids=[], allowed_paths=[], baseline={})
        args = ["--json", "dispatch", "retry", "--payload", "-", "--reason", "fixture"]
        for _ in range(2):
            with patch("sys.stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(args))

    def test_cli_delivery_check_awaiting_and_staleness(self):
        # Create/start this scenario through the CLI; setup's root stays unrelated.
        self.cli("task", "create", "CLI flow", "--name", "cli-flow")
        task = self.store.read("cli-flow")
        confirmation = dict(self.confirmation(), validates=source_snapshot(task))
        self.cli("start", "cli-flow", "--confirmation", "-", stdin=json.dumps(confirmation))
        product = self.project / "product.py"
        product.write_text("value = 6 * 7\n")
        criteria = self.project / "criteria.txt"
        criteria.write_text("<a>value is 42</a><b>integer</b><c>unrelated</c>")
        # Supported mapping API establishes marker scope before CLI registration.
        self.tasks.evidence.persist_artifact_map("cli-flow", mapping={"criteria.txt": {
            "R-1": {"start_marker": "<a>", "end_marker": "</a>", "dependencies": ["R-2"]},
            "R-2": {"start_marker": "<b>", "end_marker": "</b>"}}}, source={"type": "test"})
        self.cli("state", "add-deliverable", "cli-flow", "--name", "product", "--path", "product.py", "--criteria", "A-1")
        evidence = self.tasks.evidence
        snapshot = evidence.snapshot("cli-flow", artifact="product.py", items=["A-1"])
        marker_snapshot = evidence.snapshot("cli-flow", artifact="criteria.txt", items=["R-1"])
        baseline = {"artifact_items": [snapshot, marker_snapshot], "delivery": evidence.delivery_snapshot(["product.py"])}
        payload = build_payload(role="implement", task_ref="cli-flow", plan_item_ids=["P-1"],
                                allowed_paths=["product.py"], baseline=baseline)
        registered = self.cli("dispatch", "implement", "--payload", "-", stdin=json.dumps(payload))
        payload_path = self.save("implement.json", payload)
        result = build_result(dispatch_id=payload["dispatch_id"], role="implement", status="done", changed_paths=["product.py"])
        self.cli("dispatch", "harvest", "--payload", payload_path, "--result", "-",
                 "--lease-token", registered["lease_token"], stdin=json.dumps(result))
        check = build_payload(role="check", task_ref="cli-flow", plan_item_ids=["P-1"], allowed_paths=[], baseline=baseline)
        registered = self.cli("dispatch", "check", "--payload", self.save("check.json", check))
        command = [sys.executable, "-c", "import runpy,sys; assert runpy.run_path(sys.argv[1])['value'] == 42; print('42 verified')", str(product)]
        started = time.monotonic()
        run = subprocess.run(command, text=True, capture_output=True, cwd=self.root, timeout=20)
        duration = time.monotonic() - started
        self.log_run(command, run, duration)
        self.assertEqual(0, run.returncode, run.stderr)
        report = self.project / "check.txt"
        report.write_text(run.stdout)
        body = {"kind": "check", "producer": {"role": "check", "id": "check-subprocess"},
                "validates": [snapshot, marker_snapshot], "run_id": check["dispatch_id"], "environment": {"python": sys.version},
                "delivery": evidence.delivery_snapshot(["product.py"]), "scope": "final", "read_only": True,
                "report": {"path": "check.txt", "sha256": file_digest(report)},
                "items": [{"requirement_ids": ["A-1", "R-1"], "plan_item": "P-1", "command": repr(command),
                           "result": "passed", "exit_code": run.returncode, "duration": duration, "retries": 0}]}
        result = build_result(dispatch_id=check["dispatch_id"], role="check", status="done")
        result_path = self.save("check-result.json", result)
        check_path = self.save("check.json", check)
        # Independence and unknown ids must fail before recording anything.
        for producer, item_id, error in (("coordinator", "A-1", "check_not_independent"),
                                          ("check-subprocess", "invented", "invalid_check_scope")):
            bad = copy.deepcopy(body)
            bad["producer"]["id"] = producer
            bad["validates"][0]["items"][0]["id"] = item_id
            bad["items"][0]["requirement_ids"] = [item_id, "R-1"]
            before = (self.store.resolve("cli-flow") / "task.json").read_bytes()
            reply = self.cli("dispatch", "harvest", "--payload", check_path, "--result", result_path,
                             "--lease-token", registered["lease_token"], "--check-evidence", self.save("bad.json", bad),
                             expected=3 if error == "check_not_independent" else 2)
            self.assertEqual(error, reply["error"]["code"])
            self.assertEqual(before, (self.store.resolve("cli-flow") / "task.json").read_bytes())
        harvested = self.cli("dispatch", "harvest", "--payload", check_path, "--result", result_path,
                            "--lease-token", registered["lease_token"], "--check-evidence", self.save("evidence.json", body))
        self.assertEqual("valid", harvested["state"])
        self.cli("interrupt", "cli-flow", "--dispatch-id", check["dispatch_id"], "--reason", "check complete",
                 "--release-lease-token", registered["lease_token"])
        awaiting = self.cli("accept", "cli-flow", "--awaiting")
        self.assertEqual("awaiting_acceptance", awaiting["phase"])
        replay = self.cli("dispatch", "check", "--payload", check_path)
        self.assertEqual("harvested", replay["registration_state"])
        criteria.write_text(criteria.read_text().replace("unrelated", "unrelated changed"))
        self.assertTrue(self.cli("acceptance", "status", "cli-flow")["awaiting_acceptance"])
        criteria.write_text(criteria.read_text().replace("integer", "decimal"))
        self.assertFalse(self.cli("acceptance", "status", "cli-flow")["awaiting_acceptance"])
        criteria.write_text(criteria.read_text().replace("decimal", "integer"))
        product.write_text("value = 43\n")
        status = self.cli("acceptance", "status", "cli-flow")
        self.assertFalse(status["awaiting_acceptance"])
        self.cli("evidence", "invalidate", "cli-flow", "--file", "product.py")
        self.assertEqual("in_progress", self.store.read("cli-flow")["phase"])

    def test_foreign_candidates_are_registry_scoped_and_read_only(self):
        self.user.mkdir(exist_ok=True)
        registry = {"schema": "fstar.projects.v1", "projects": {}}
        for index in range(3):
            project = self.root / ("foreign " + str(index))
            project.mkdir()
            (project / ".fstar").mkdir()
            (project / ".fstar/.schema-version").write_text("1\n")
            store = TaskStore(project, user_home=self.user, runtime_root=self.runtime)
            TaskService(store).create(name="foreign-task", title="Foreign", description="test", actor=self.actor)
            if index < 2:  # Third project exists but is deliberately unregistered.
                registry["projects"][str(index)] = {"path": str(project)}
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".fstar").mkdir()
        (broken / ".fstar/.schema-version").write_bytes(b"\xff")
        registry["projects"]["broken"] = {"path": str(broken)}
        registry["projects"]["00-invalid-path"] = {"path": "bad\x00path"}
        registry["projects"]["missing"] = {"path": str(self.root / "missing")}
        (self.user / "projects.json").write_text(json.dumps(registry))
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        reply = self.cli("state", "show", "foreign-task", expected=2)
        self.assertEqual("task_not_found", reply["error"]["code"])
        details = reply["error"]["details"]
        self.assertEqual(2, len(details["foreign_candidates"]))
        self.assertIn("--project", details["hint"])
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        # The advertised explicit project override reaches the selected target.
        hit = details["foreign_candidates"][0]
        self.cli("state", "show", "foreign-task", project=Path(hit["project"]))
        (self.user / "projects.json").write_text("broken")
        reply = self.cli("state", "show", "foreign-task", expected=2)
        self.assertEqual("task_not_found", reply["error"]["code"])


if __name__ == "__main__":
    unittest.main()
