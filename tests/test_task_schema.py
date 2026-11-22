"""S-2 (general-workflow-redesign): optional task.json schema extension.

Design §4 adds five optional top-level fields — status / status_detail /
work_items / next_step / deliverables — all backward compatible:

- new tasks keep the minimal 26-field output (no pre-filling);
- old task.json files (none of the new fields) read and write unchanged;
- source_snapshot hashes only id/phase/description/meta.templates, so the
  new fields never touch confirmation binding;
- every status / work-item / next-step / deliverable change appends one
  event to the append-only log;
- `fstar state show` surfaces the fields (status defaults to "active").
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from fstar.models import (DomainError, TASK_FIELDS, new_task,
                          validate_task, validate_optional_fields)
from fstar.store import TaskStore, atomic_write_json
from fstar.tasks import TaskService, source_snapshot


class Clock:
    def __init__(self, value="2026-11-21T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value


class SchemaExtensionCase(unittest.TestCase):
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
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user", "session": "s1"}

    def create(self, name="root"):
        return self.service.create(name=name, title=name.title(), description="D1", actor=self.agent)

    def start(self, ref="root"):
        task = self.store.read(ref)
        confirmation = {"source_id": "src-" + task["id"], "type": "command", "at": self.clock(),
                        "actor": self.user, "reference": "prompt:1", "quote": "", "scope": "task",
                        "validates": source_snapshot(task)}
        return self.service.start(ref, actor=self.user, confirmation=confirmation)

    def read_file(self, ref="root"):
        return json.loads((self.store.resolve(ref) / "task.json").read_text())


class SchemaFieldTests(SchemaExtensionCase):
    def test_new_task_output_unchanged_minimal(self):
        task = new_task("safe-name", "Safe", "", creator="me", now=self.clock())
        self.assertEqual(set(TASK_FIELDS), set(task))
        self.assertEqual(26, len(task))
        for field in ("status", "status_detail", "work_items", "next_step", "deliverables"):
            self.assertNotIn(field, task)

    def test_optional_fields_roundtrip(self):
        self.create()
        self.start()
        with self.store.transaction():
            task = self.store.read("root")
            task["status"] = "waiting_user"
            task["status_detail"] = {"reason": "awaiting user decision", "since": self.clock()}
            task["work_items"] = [{"id": "S-1", "state": "done", "summary": "schema fields",
                                   "evidence_refs": ["ev-1"]}]
            task["next_step"] = {"condition": "user answers", "action": "resume S-2"}
            task["deliverables"] = [{"name": "schema", "path": "src/fstar/models.py",
                                     "format": "py", "criteria_refs": ["A1"], "version": "1"}]
            self.store.write(self.store.resolve("root"), task)
        reloaded = self.store.read("root")
        self.assertEqual("waiting_user", reloaded["status"])
        self.assertEqual({"reason": "awaiting user decision", "since": self.clock()}, reloaded["status_detail"])
        self.assertEqual("S-1", reloaded["work_items"][0]["id"])
        self.assertEqual({"condition": "user answers", "action": "resume S-2"}, reloaded["next_step"])
        self.assertEqual("schema", reloaded["deliverables"][0]["name"])

    def test_legacy_task_without_new_fields_reads_and_writes_unchanged(self):
        self.create()
        self.start()
        before = self.read_file()
        # Read round-trip: no error, no defaults injected.
        task = self.store.read("root")
        for field in ("status", "status_detail", "work_items", "next_step", "deliverables"):
            self.assertNotIn(field, task)
        # A write that does not touch the new fields keeps the file unchanged.
        with self.store.transaction():
            untouched = self.store.read("root")
            self.store.write(self.store.resolve("root"), untouched)
        self.assertEqual(before, self.read_file())

    def test_new_fields_do_not_change_source_snapshot(self):
        self.create()
        self.start()
        before = source_snapshot(self.store.read("root"))
        with self.store.transaction():
            task = self.store.read("root")
            task["status"] = "paused"
            task["status_detail"] = {"reason": "out of office", "since": self.clock()}
            task["work_items"] = [{"id": "S-1", "state": "active", "summary": "", "evidence_refs": []}]
            task["next_step"] = {"condition": "c", "action": "a"}
            task["deliverables"] = [{"name": "x", "path": "p", "format": "", "criteria_refs": [], "version": ""}]
            self.store.write(self.store.resolve("root"), task)
        self.assertEqual(before, source_snapshot(self.store.read("root")))

    def test_validation_rejects_malformed_optional_fields(self):
        task = new_task("safe-name", "Safe", "", creator="me", now=self.clock())
        cases = [
            {"status": "sleeping"},
            {"status_detail": {"reason": "x"}},  # missing since
            {"status_detail": {"reason": "x", "since": "not-a-time"}},
            {"status_detail": {"reason": "x", "since": "2026-11-21T10:00:00Z", "extra": 1}},
            {"work_items": "nope"},
            {"work_items": [{"id": "S-1", "state": "starting"}]},
            {"work_items": [{"id": "", "state": "done"}]},
            {"work_items": [{"id": "S-1", "state": "done"}, {"id": "S-1", "state": "active"}]},
            {"work_items": [{"id": "S-1", "state": "done", "unknown": 1}]},
            {"next_step": {"condition": "only"}},
            {"next_step": {"condition": "", "action": "a"}},
            {"deliverables": [{"name": "x"}]},  # missing path
            {"deliverables": [{"name": "x", "path": "p"}, {"name": "x", "path": "q"}]},
        ]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(DomainError) as caught:
                validate_task({**task, **extra})
            self.assertTrue(caught.exception.code.startswith("invalid_"), caught.exception.code)

    def test_validation_allows_partial_optional_fields(self):
        task = new_task("safe-name", "Safe", "", creator="me", now=self.clock())
        # Each field can appear alone; None is also valid (cleared state).
        for extra in ({"status": "active"},
                      {"status_detail": None},
                      {"work_items": []},
                      {"next_step": None},
                      {"deliverables": []},
                      {"status": "waiting_external"},
                      ):
            with self.subTest(extra=extra):
                validate_task({**task, **extra})


class StatusEventTests(SchemaExtensionCase):
    def test_set_status_records_event(self):
        self.create()
        self.start()
        updated = self.service.set_status("root", actor=self.agent, status="waiting_user", reason="awaiting user answer")
        self.assertEqual("waiting_user", updated["status"])
        self.assertEqual({"reason": "awaiting user answer", "since": self.clock()}, updated["status_detail"])
        event = self.store.read("root")["events"][-1]
        self.assertEqual("status_changed", event["type"])
        self.assertEqual({"from": "active", "to": "waiting_user", "reason": "awaiting user answer"}, event["data"])
        # Back to active: detail cleared, second event appended.
        again = self.service.set_status("root", actor=self.agent, status="active")
        stored = self.store.read("root")
        self.assertEqual("active", stored["status"])
        self.assertIsNone(stored["status_detail"])
        events = [e for e in stored["events"] if e["type"] == "status_changed"]
        self.assertEqual(2, len(events))
        self.assertEqual({"from": "waiting_user", "to": "active", "reason": ""}, events[-1]["data"])

    def test_set_status_requires_reason_when_not_active(self):
        self.create()
        self.start()
        for reason in (None, "", "   "):
            with self.subTest(reason=reason), self.assertRaises(DomainError) as caught:
                self.service.set_status("root", actor=self.agent, status="paused", reason=reason)
            self.assertEqual("reason_required", caught.exception.code)
        with self.assertRaises(DomainError) as caught:
            self.service.set_status("root", actor=self.agent, status="hibernating", reason="x")
        self.assertEqual("invalid_status", caught.exception.code)

    def test_work_item_upsert_records_event(self):
        self.create()
        self.start()
        first = self.service.set_work_item("root", actor=self.agent,
                                           item={"id": "S-1", "state": "active", "summary": "schema", "evidence_refs": []})
        self.assertEqual("S-1", first["work_items"][0]["id"])
        # Upsert same id: replaced, not duplicated.
        second = self.service.set_work_item("root", actor=self.agent,
                                            item={"id": "S-1", "state": "done", "summary": "schema done", "evidence_refs": ["ev-9"]})
        items = self.store.read("root")["work_items"]
        self.assertEqual(1, len(items))
        self.assertEqual("done", items[0]["state"])
        self.assertEqual(["ev-9"], items[0]["evidence_refs"])
        events = [e for e in self.store.read("root")["events"] if e["type"] == "work_item_updated"]
        self.assertEqual(2, len(events))
        self.assertIsNone(events[0]["data"]["old"])
        self.assertEqual("active", events[0]["data"]["new"]["state"])
        self.assertEqual("done", events[1]["data"]["new"]["state"])
        self.assertEqual("active", events[1]["data"]["old"]["state"])

    def test_next_step_set_and_clear(self):
        self.create()
        self.start()
        self.service.set_next_step("root", actor=self.agent, condition="user confirms scope", action="start S-2")
        stored = self.store.read("root")
        self.assertEqual({"condition": "user confirms scope", "action": "start S-2"}, stored["next_step"])
        cleared = self.service.set_next_step("root", actor=self.agent, condition=None, action=None)
        self.assertIsNone(cleared["next_step"])
        events = [e for e in self.store.read("root")["events"] if e["type"] == "next_step_changed"]
        self.assertEqual(2, len(events))
        self.assertIsNone(events[1]["data"]["new"])
        with self.assertRaises(DomainError) as caught:
            self.service.set_next_step("root", actor=self.agent, condition="only condition", action=None)
        self.assertEqual("invalid_next_step", caught.exception.code)

    def test_register_deliverable_upsert(self):
        self.create()
        self.start()
        self.service.register_deliverable("root", actor=self.agent,
                                          entry={"name": "schema", "path": "src/fstar/models.py", "format": "py", "criteria_refs": ["A1"], "version": "1"})
        self.service.register_deliverable("root", actor=self.agent,
                                          entry={"name": "schema", "path": "src/fstar/models.py", "format": "py", "criteria_refs": ["A1"], "version": "2"})
        entries = self.store.read("root")["deliverables"]
        self.assertEqual(1, len(entries))
        self.assertEqual("2", entries[0]["version"])
        events = [e for e in self.store.read("root")["events"] if e["type"] == "deliverable_updated"]
        self.assertEqual(2, len(events))
        with self.assertRaises(DomainError) as caught:
            self.service.register_deliverable("root", actor=self.agent, entry={"name": "x"})
        self.assertEqual("invalid_deliverables", caught.exception.code)

    def test_status_updates_work_while_leased(self):
        # Lease never refuses descriptive-state writes; the project lock in
        # transaction() serializes the write.
        self.create()
        self.start()
        lease = self.service.acquire_lease("root", holder="worker", role="implement", actor=self.agent)
        updated = self.service.set_status("root", actor=self.agent, status="waiting_external", reason="ci pipeline")
        self.assertEqual("waiting_external", updated["status"])
        self.assertEqual("worker", self.store.read("root")["lease"]["holder"]["id"])

    def test_dropped_task_refuses_status_writes(self):
        self.create()
        task = self.store.read("root")
        confirmation = {"source_id": "src-" + task["id"], "type": "command", "at": self.clock(),
                        "actor": self.user, "reference": "prompt:1", "quote": "", "scope": "task",
                        "validates": source_snapshot(task)}
        self.service.drop("root", actor=self.user, confirmation=confirmation, reason="abandon", disposition="keep")
        with self.assertRaises(DomainError) as caught:
            self.service.set_status("root", actor=self.agent, status="paused", reason="x")
        self.assertEqual("task_dropped", caught.exception.code)


class StateShowTests(SchemaExtensionCase):
    def test_state_show_reports_fields_and_defaults(self):
        self.create()
        self.start()
        before = self.service.state("root")
        self.assertEqual("active", before["status"])
        for field in ("status_detail", "work_items", "next_step", "deliverables"):
            self.assertNotIn(field, before)
        self.service.set_status("root", actor=self.agent, status="paused", reason="hold")
        self.service.set_work_item("root", actor=self.agent, item={"id": "S-1", "state": "blocked", "summary": "waiting dep", "evidence_refs": []})
        self.service.set_next_step("root", actor=self.agent, condition="dep lands", action="resume")
        after = self.service.state("root")
        self.assertEqual("paused", after["status"])
        self.assertEqual({"reason": "hold", "since": self.clock()}, after["status_detail"])
        self.assertEqual("blocked", after["work_items"][0]["state"])
        self.assertEqual({"condition": "dep lands", "action": "resume"}, after["next_step"])


class CliSurfaceTests(SchemaExtensionCase):
    def run_cli(self, *args):
        import os
        import subprocess
        import sys
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
        env["HOME"] = self.tmp.name
        env["PATH"] = ""
        return subprocess.run([sys.executable, "-m", "fstar", *args], cwd=self.project, env=env, text=True, capture_output=True)

    def base(self, *args):
        return self.run_cli("--project", str(self.project),
                            "--user-data-root", str(Path(self.tmp.name) / "u"),
                            "--runtime-root", str(Path(self.tmp.name) / "r"),
                            "--json", *args)

    def test_cli_status_and_show_roundtrip(self):
        self.create()
        self.start()
        result = self.base("state", "set-status", "root", "--status", "waiting_user", "--reason", "awaiting user answer")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("waiting_user", json.loads(result.stdout)["status"])
        shown = self.base("state", "show", "root")
        self.assertEqual(0, shown.returncode, shown.stderr)
        payload = json.loads(shown.stdout)
        self.assertEqual("waiting_user", payload["status"])
        self.assertEqual("awaiting user answer", payload["status_detail"]["reason"])
        # Non-active status without a reason is refused.
        failure = self.base("state", "set-status", "root", "--status", "paused")
        self.assertEqual(2, failure.returncode)
        self.assertEqual("reason_required", json.loads(failure.stderr)["error"]["code"])

    def test_cli_work_item_next_and_deliverable(self):
        self.create()
        self.start()
        item = self.base("state", "set-work-item", "root", "--id", "S-1", "--state", "done", "--summary", "fields", "--evidence", "ev-1")
        self.assertEqual(0, item.returncode, item.stderr)
        self.assertEqual("done", json.loads(item.stdout)["work_items"][0]["state"])
        nxt = self.base("state", "set-next", "root", "--condition", "user confirms", "--action", "start S-2")
        self.assertEqual(0, nxt.returncode, nxt.stderr)
        delivery = self.base("state", "add-deliverable", "root", "--name", "schema", "--path", "src/fstar/models.py", "--format", "py", "--criteria", "A1", "--version", "1")
        self.assertEqual(0, delivery.returncode, delivery.stderr)
        stored = self.store.read("root")
        self.assertEqual(["S-1"], [x["id"] for x in stored["work_items"]])
        self.assertEqual({"condition": "user confirms", "action": "start S-2"}, stored["next_step"])
        self.assertEqual("src/fstar/models.py", stored["deliverables"][0]["path"])
        self.assertEqual(["A1"], stored["deliverables"][0]["criteria_refs"])
        events = [e["type"] for e in stored["events"]]
        self.assertIn("work_item_updated", events)
        self.assertIn("next_step_changed", events)
        self.assertIn("deliverable_updated", events)

    def test_cli_show_omits_absent_fields(self):
        self.create()
        self.start()
        shown = self.base("state", "show", "root")
        self.assertEqual(0, shown.returncode, shown.stderr)
        payload = json.loads(shown.stdout)
        self.assertEqual("active", payload["status"])
        for field in ("status_detail", "work_items", "next_step", "deliverables"):
            self.assertNotIn(field, payload)


if __name__ == "__main__":
    unittest.main()
