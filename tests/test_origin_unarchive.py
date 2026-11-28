"""antigravity-adoption P-002: origin field, unarchive command, compatibility.

Covers criteria A-001 (reopen of archived parents with event trail and
tree-wide unarchive + attach aggregation), A-002's kernel half (origin
field with invalid_origin validation; injection itself is P-003), and
A-006 (old task.json without origin runs the full lifecycle unchanged).
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fstar.evidence import file_digest
from fstar.models import DomainError
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


class OriginCase(unittest.TestCase):
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

    def source(self, ref, actor=None):
        task = self.store.read(ref)
        return {"source_id": "src-" + task["id"], "type": "command", "at": self.clock(),
                "actor": actor or self.user, "reference": "prompt:1", "quote": "", "scope": "task",
                "validates": source_snapshot(task)}

    def archived_source(self, ref):
        task = self.store.read(ref, archived=True)
        return {"source_id": "src-" + task["id"], "type": "command", "at": self.clock(),
                "actor": self.user, "reference": "prompt:1", "quote": "", "scope": "task",
                "validates": source_snapshot(task)}

    def start(self, ref):
        return self.service.start(ref, actor=self.user, confirmation=self.source(ref))

    def prepare_artifacts(self, ref):
        (self.project / "src.py").write_text("<!-- R-001:start -->\nvalue = 1\n<!-- R-001:end -->\n")
        (self.project / "test.py").write_text("assert True\n")
        (self.project / "report.md").write_text("all passed\n")
        with self.store.transaction():
            task = self.store.read(ref)
            task["meta"]["templates"] = {"artifact_map": {"src.py": {"R-001": {"start_marker": "<!-- R-001:start -->", "end_marker": "<!-- R-001:end -->"}}}}
            self.store.write(self.store.resolve(ref), task)

    def complete(self, ref):
        """Create (if needed) and drive one task to completed."""
        try:
            self.store.read(ref)
        except DomainError as exc:
            if exc.code != "task_not_found":
                raise
            self.service.create(name=ref, title=ref.title(), description="D", actor=self.agent)
        self.start(ref)
        self.prepare_artifacts(ref)
        lease = self.service.acquire_lease(ref, holder="coordinator", role="coordinator", actor=self.agent)
        snapshot = self.service.evidence.snapshot(ref, artifact="src.py", items=["R-001"])
        delivery = self.service.evidence.delivery_snapshot(["src.py", "test.py"])
        self.service.evidence.record(ref, lease_token=lease["token"], evidence={
            "kind": "check", "producer": {"role": "check", "id": "checker", "session_id": "c1"},
            "validates": [snapshot], "run_id": "run-1",
            "environment": {"python": sys.version.split()[0]},
            "report": {"path": "report.md", "sha256": file_digest(self.project / "report.md")},
            "delivery": delivery, "scope": "final", "read_only": True,
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["test.py"],
                       "command": "python test.py", "result": "passed", "exit_code": 0,
                       "log_refs": ["report.md"], "duration": 1.0, "retries": 0}]})
        self.service.release_lease(ref, token=lease["token"], reason="check complete")
        self.service.enter_awaiting_acceptance(ref, actor=self.agent)
        return self.service.accept(ref, actor=self.user, confirmation=self.source(ref))

    def archive(self, ref):
        return self.service.archive(ref, actor=self.user, confirmation=self.source(ref))


class OriginFieldTests(OriginCase):
    def test_origin_accepted_and_rejected(self):
        parent = self.complete("root")
        self.archive("root")
        archived_dir = self.store.resolve("root", archived=True)
        origin = {"task_id": parent["id"], "archive_path": self.store.identity_path(archived_dir),
                 "reason": "followup fix"}
        self.service.create(name="fix-1", title="Fix", description="D", actor=self.agent, origin=origin)
        task = self.store.read("fix-1")
        self.assertEqual(origin["task_id"], task["origin"]["task_id"])
        self.assertEqual(origin["archive_path"], task["origin"]["archive_path"])
        self.assertEqual(origin["reason"], task["origin"]["reason"])
        with self.assertRaises(DomainError) as caught:
            self.service.create(name="fix-2", title="Fix", description="D", actor=self.agent,
                                origin={"task_id": "not-the-parent", "archive_path": origin["archive_path"], "reason": "x"})
        self.assertEqual("invalid_origin", caught.exception.code)
        # stale archive_path with the CORRECT id resolves through the id scan
        made = self.service.create(name="fix-3", title="Fix", description="D", actor=self.agent,
                                   origin={"task_id": parent["id"], "archive_path": ".fstar/archive/2026-11/no-such", "reason": "x"})
        self.assertEqual(parent["id"], self.store.read("fix-3")["origin"]["task_id"])
        # neither the path nor a scan can find this one
        with self.assertRaises(DomainError) as caught:
            self.service.create(name="fix-3b", title="Fix", description="D", actor=self.agent,
                                origin={"task_id": "00000000-0000-0000-0000-000000000000", "archive_path": ".fstar/archive/2026-11/no-such", "reason": "x"})
        self.assertEqual("invalid_origin", caught.exception.code)
        with self.assertRaises(DomainError) as caught:
            self.service.create(name="fix-4", title="Fix", description="D", actor=self.agent,
                                parent="root", origin=origin)
        self.assertEqual("invalid_origin", caught.exception.code)
        self.assertIn("fix-1", [x["name"] for x in self.service.list_tasks()])

    def test_origin_to_active_top_level_parent_allowed(self):
        self.complete("root")
        made = self.service.create(name="fix-1", title="Fix", description="D", actor=self.agent,
                                   origin={"task_id": self.store.read("root")["id"],
                                           "archive_path": self.store.identity_path(self.store.tasks_root / "root"),
                                           "reason": "r"})
        self.assertEqual(self.store.read("root")["id"], self.store.read("fix-1")["origin"]["task_id"])


class UnarchiveTests(OriginCase):
    def test_unarchive_moves_tree_attaches_followup_and_leaves_event(self):
        parent = self.complete("root")
        self.archive("root")
        archived_dir = self.store.resolve("root", archived=True)
        identity = self.store.identity_path(archived_dir)
        self.service.create(name="fix-1", title="Fix", description="D", actor=self.agent,
                            origin={"task_id": parent["id"], "archive_path": identity, "reason": "followup fix"})
        result = self.service.unarchive("root", actor=self.user,
                                        confirmation=self.archived_source("root"), reason="joint follow-up work")
        self.assertEqual(str(self.store.tasks_root / "root"), result["path"])
        # follow-up migrated into the parent subtasks and registered as a child
        self.assertEqual(["fix-1"], self.store.read("root")["children"])
        self.assertTrue((self.store.tasks_root / "root" / "subtasks" / "fix-1" / "task.json").is_file())
        self.assertFalse((self.store.tasks_root / "fix-1").exists())
        # origin kept for traceability
        self.assertEqual(parent["id"], self.store.read("fix-1")["origin"]["task_id"])
        # archivedAt cleared tree-wide, completedAt preserved, phase untouched
        self.assertIsNone(self.store.read("root")["archivedAt"])
        self.assertIsNone(self.store.read("fix-1")["archivedAt"])
        self.assertEqual("completed", self.store.read("root")["phase"])
        self.assertIsNotNone(self.store.read("root")["completedAt"])
        # acceptance untouched
        self.assertEqual("valid", self.store.read("root")["acceptance"]["state"])
        # the archive month directory no longer holds the tree
        self.assertFalse(archived_dir.exists())
        # event trail: unarchived milestone with from-path, reason, attach list
        events = self.store.read("root")["events"]
        unarchived = [e for e in events if e["type"] == "unarchived"]
        self.assertEqual(1, len(unarchived))
        self.assertEqual(identity, unarchived[0]["data"]["from"])
        self.assertEqual(["fix-1"], unarchived[0]["data"]["attached"])
        self.assertEqual("joint follow-up work", unarchived[0]["data"]["reason"])
        from fstar.tasks import MILESTONES
        self.assertIn("unarchived", MILESTONES)
        # the parent can be re-archived together with the follow-up (A-001):
        # complete the follow-up, then archive the whole tree again.
        self.complete("fix-1")
        self.archive("root")
        self.assertTrue((self.store.archive_root / "2026-11" / "root" / "subtasks" / "fix-1" / "task.json").is_file())
        # and the archived tree keeps the origin traceability (A-001 retrospection)
        self.assertEqual(parent["id"], self.store.read("fix-1", archived=True)["origin"]["task_id"])

    def test_unarchive_without_followup_leaves_tree_unchanged(self):
        self.complete("root")
        self.archive("root")
        result = self.service.unarchive("root", actor=self.user, confirmation=self.archived_source("root"))
        self.assertEqual([], result["attached"])
        self.assertEqual([], self.store.read("root")["children"])
        event = [e for e in self.store.read("root")["events"] if e["type"] == "unarchived"][0]
        self.assertNotIn("attached", event["data"])

    def test_unarchive_requires_user_confirmation(self):
        self.complete("root")
        self.archive("root")
        with self.assertRaises(DomainError) as caught:
            self.service.unarchive("root", actor=self.agent, confirmation={})
        self.assertEqual("unarchive_forbidden", caught.exception.code)
        # an agent cannot record its invocation as a direct user command;
        # the role gate fires before the confirmation is even validated
        archived = self.store.read("root", archived=True)
        confirmation = {"source_id": "s", "type": "command", "at": self.clock(),
                         "actor": self.agent, "reference": "r", "quote": "", "scope": "task",
                         "validates": source_snapshot(archived)}
        with self.assertRaises(DomainError) as caught:
            self.service.unarchive("root", actor={"role": "user", "id": "u"}, confirmation=confirmation)
        self.assertIn(caught.exception.code, {"invalid_confirmation", "unarchive_forbidden"})

    def test_unarchive_refuses_active_task(self):
        self.complete("root")
        with self.assertRaises(DomainError) as caught:
            self.service.unarchive("root", actor=self.user, confirmation=self.source("root"))
        self.assertEqual("not_archived", caught.exception.code)

    def test_unarchive_child_forbidden(self):
        self.service.create(name="parent", title="P", description="D", actor=self.agent)
        self.service.create(name="child", title="C", description="D", actor=self.agent, parent="parent")
        self.complete("child")
        self.complete("parent")
        self.archive("parent")
        archived_child = self.store.resolve("child", archived=True)
        confirmation = {"source_id": "s", "type": "command", "at": self.clock(),
                          "actor": self.user, "reference": "r", "quote": "", "scope": "task",
                          "validates": source_snapshot(self.store.read("child", archived=True))}
        with self.assertRaises(DomainError) as caught:
            self.service.unarchive("child", actor=self.user, confirmation=confirmation)
        self.assertEqual("unarchive_child_forbidden", caught.exception.code)

    def test_unarchive_destination_conflict(self):
        self.complete("root")
        self.archive("root")
        self.service.create(name="root", title="Again", description="D", actor=self.agent)
        with self.assertRaises(DomainError) as caught:
            self.service.unarchive("root", actor=self.user, confirmation=self.archived_source("root"))
        self.assertEqual("archive_conflict", caught.exception.code)


class CompatibilityTests(OriginCase):
    """A-006: a task.json WITHOUT the origin field behaves exactly as before
    through the full lifecycle (create -> start -> accept -> archive), and a
    task WITH origin works while its parent is archived or unarchived."""

    def test_full_lifecycle_without_origin_unchanged(self):
        task = self.complete("root")
        self.assertNotIn("origin", task)
        self.assertEqual("completed", task["phase"])
        result = self.archive("root")
        self.assertTrue((self.store.archive_root / "2026-11" / "root" / "task.json").is_file())
        # locate still reports the archived task read-only
        located = self.service.locate(ref="root")
        self.assertEqual("found", located["status"])
        self.assertTrue(located["task"]["archived"])
        # list still surfaces active and archived rows unchanged
        self.assertEqual([], [x for x in self.service.list_tasks() if x["name"] == "root"])
        self.assertIn("root", [x["name"] for x in self.service.list_tasks(archived=True)])
        # state read of the archive is unaffected by the new optional field
        self.assertEqual("completed", self.store.read("root", archived=True)["phase"])

    def test_origin_task_lifecycle_with_parent_archived_and_unarchived(self):
        parent = self.complete("root")
        self.archive("root")
        identity = self.store.identity_path(self.store.resolve("root", archived=True))
        # create + full lifecycle of an origin task while the parent IS archived
        self.service.create(name="fix-1", title="Fix", description="D", actor=self.agent,
                            origin={"task_id": parent["id"], "archive_path": identity, "reason": "r"})
        self.complete("fix-1")
        # unarchive the parent (attaches fix-1), then resolve again
        self.service.unarchive("root", actor=self.user, confirmation=self.archived_source("root"))
        self.assertEqual("completed", self.store.read("fix-1")["phase"])
        # create a second follow-up while the parent is ACTIVE: both resolve
        self.service.create(name="fix-2", title="Fix 2", description="D", actor=self.agent,
                            origin={"task_id": parent["id"], "archive_path": identity, "reason": "r"})
        self.complete("fix-2")


if __name__ == "__main__":
    unittest.main()
