"""Experience-loop bridge tests: read, correction and retirement via the packaged bridge.

Everything runs against the packaged ``bin/fstar-bootstrap.py learn_bridge``
subprocess on temporary fixtures.  ``read`` follows the read-only policy
(no grant, no write), while correction and retirement reuse the authorized
``prepare``/``apply`` pipeline exactly as it exists.  No real user knowledge
or host configuration is touched.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar.project import initialize_project, initialize_user

ROOT = Path(__file__).resolve().parents[1]

MEMORY_PLAIN = """---
schema: fstar.knowledge.v1
type: memory
status: active
kind: preference
trust: confirmed
---

# Plain preference

Prefer short status updates.
"""


def grant(*members):
    return {"id": "project-governance", "scope": "custom", "included": list(members), "excluded": []}


def memory_document(title, *, status="active", kind="preference", trust="confirmed",
                    scope=None, confidence=None, source=None, expires=None,
                    conditions=None, body=None):
    lines = ["---", "schema: fstar.knowledge.v1", "type: memory",
             "status: %s" % status, "kind: %s" % kind, "trust: %s" % trust]
    for key, value in (("scope", scope), ("confidence", confidence), ("source", source),
                       ("expires", expires), ("conditions", conditions)):
        if value is not None:
            lines.append("%s: %s" % (key, value))
    lines.extend(["---", "", "# %s" % title, "", body or ("Body of %s." % title), ""])
    return "\n".join(lines)


class ExperienceBridgeTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        self.project, self.user = root / "project", root / "user"
        self.project.mkdir()
        self.user.mkdir()
        initialize_project(self.project, self.user)
        initialize_user(self.user)
        (self.user / "memory").mkdir(parents=True, exist_ok=True)
        (self.user / "memory" / "plain.md").write_text(MEMORY_PLAIN, encoding="utf-8")
        (self.user / "index.md").write_text(
            "# fstar 用户索引\n\n## Memory\n\n- [普通偏好](memory/plain.md) — kind: preference\n",
            encoding="utf-8")
        self.env = dict(os.environ, HOME=str(root / "home"), PATH="",
                        PYTHONDONTWRITEBYTECODE="1",
                        FSTAR_USER_ROOT=str(self.user),
                        FSTAR_RUNTIME_ROOT=str(root / "runtime"))

    # -- helpers ---------------------------------------------------------
    def call(self, request):
        result = subprocess.run(
            [sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"), "learn_bridge"],
            input=json.dumps(request, ensure_ascii=False), text=True, capture_output=True,
            env=self.env)
        return result.returncode, json.loads(result.stdout)

    def read(self, selection=None, max_bytes=None):
        request = {"action": "read", "project_root": str(self.project),
                   "user_root": str(self.user), "selection": selection or {}}
        if max_bytes is not None:
            request["max_bytes"] = max_bytes
        return self.call(request)

    def read_result(self, **selection):
        max_bytes = selection.pop("max_bytes", None)
        rc, payload = self.read(selection, max_bytes=max_bytes)
        self.assertEqual(0, rc, payload)
        return payload["result"]

    def write_request(self, edits, intent=None):
        return {"action": "prepare", "project_root": str(self.project),
                "user_root": str(self.user), "task_ref": "session-only",
                "extensions": [grant("memory")], "edits": edits,
                "intent": intent or {
                    "summary": "record a scoped experience", "action": "create",
                    "scope": "user experience memory",
                    "source": {"source_type": "conversation", "reference": "chat#s6"}},
                "assessment": {"reviewed": self.reviewed(), "coverage": "complete"}}

    def reviewed(self):
        from fstar.knowledge import load_catalog
        catalog = load_catalog(user_root=self.user, project_root=self.project)
        return [{"key": item.key, "digest": item.digest}
                for item in list(catalog.documents) + list(catalog.indexes)]

    def confirmed(self, prepared, quote="please remember this"):
        proposal = prepared["result"]["proposal"]
        return {"disposition": "approved", "source_type": "conversation",
                "source_ref": "chat#s6", "quote": quote, "confirmed_at": "2026-11-22",
                "proposal_hash": prepared["result"]["proposal_hash"],
                "scope": proposal["scope"], "owners": proposal["owners"]}

    def learn(self, relative, text, **intent_kwargs):
        request = self.write_request(
            [{"owner": "user", "path": relative, "action": "create", "content": text}],
            intent=intent_kwargs or None)
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        rc, applied = self.call(dict(request, action="apply",
                                     confirmation=self.confirmed(prepared)))
        self.assertEqual(0, rc, applied)
        return prepared, applied

    def user_snapshot(self):
        return {str(path.relative_to(self.user)): path.read_bytes()
                for path in self.user.rglob("*") if path.is_file()}

    # -- read action -----------------------------------------------------
    def test_read_returns_bodies_exclusions_and_confidence(self):
        self.learn("memory/payments.md",
                   memory_document("Payments lesson", scope="scenario:payments",
                                   confidence="verified", body="Payments habit."))
        result = self.read_result(topics=[], scope=["scenario:payments"])
        keys = {document["key"] for document in result["documents"]}
        self.assertIn("user:memory/plain.md", keys)
        self.assertIn("user:memory/payments.md", keys)
        by_key = {document["key"]: document for document in result["documents"]}
        self.assertEqual("verified", by_key["user:memory/payments.md"]["confidence"])
        self.assertIsNone(by_key["user:memory/plain.md"]["confidence"])
        self.assertTrue(result["complete"])
        self.assertTrue(result["snapshot_hash"])

    def test_read_filters_by_scope_and_reports_exclusion_reasons(self):
        self.learn("memory/payments.md",
                   memory_document("Payments lesson", scope="scenario:payments",
                                   confidence="verified", body="Payments habit."))
        result = self.read_result(topics=[], scope=["scenario:other"])
        keys = {document["key"] for document in result["documents"]}
        self.assertNotIn("user:memory/payments.md", keys)
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("does not match the current reading scope",
                      reasons["user:memory/payments.md"])

    def test_read_conditions_stay_unknown_until_explicitly_judged(self):
        self.learn("memory/conditional.md",
                   memory_document("Conditional lesson", scope="scenario:payments",
                                   confidence="verified",
                                   conditions="仅在旧版部署流程仍在使用时适用",
                                   body="Conditional habit."))
        result = self.read_result(topics=[], scope=["scenario:payments"])
        keys = {document["key"] for document in result["documents"]}
        self.assertNotIn("user:memory/conditional.md", keys)
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("unknown", reasons["user:memory/conditional.md"])
        # An explicit caller judgement decides it.
        result = self.read_result(
            topics=[], scope=["scenario:payments"],
            applicability={"user:memory/conditional.md":
                           {"state": "include", "reason": "user confirmed it applies"}})
        self.assertIn("user:memory/conditional.md",
                      {document["key"] for document in result["documents"]})

    def test_read_expired_memory_is_excluded_with_reason(self):
        self.learn("memory/legacy.md",
                   memory_document("Legacy lesson", scope="scenario:payments",
                                   confidence="verified", expires="2026-01-01",
                                   body="Legacy habit."))
        result = self.read_result(topics=[], scope=["scenario:payments"])
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("memory expired on 2026-01-01", reasons["user:memory/legacy.md"])

    def test_read_blocks_direct_selection_of_stopped_or_expired_entries(self):
        self.learn("memory/legacy.md",
                   memory_document("Legacy lesson", scope="scenario:payments",
                                   confidence="verified", expires="2026-01-01",
                                   body="Legacy habit."))
        result = self.read_result(topics=[], scope=["scenario:payments"],
                                  documents=["user:memory/legacy.md"],
                                  dependencies=["user:memory/legacy.md"])
        keys = {document["key"] for document in result["documents"]}
        self.assertNotIn("user:memory/legacy.md", keys)
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("memory expired on 2026-01-01", reasons["user:memory/legacy.md"])

    def test_read_creates_no_files_and_needs_no_grant(self):
        before = self.user_snapshot()
        request = {"action": "read", "project_root": str(self.project),
                   "user_root": str(self.user),
                   "selection": {"topics": [], "scope": ["scenario:payments"]}}
        request.pop("extensions", None)
        rc, payload = self.call(request)  # no extensions, no task_ref at all
        self.assertEqual(0, rc, payload)
        self.assertEqual(before, self.user_snapshot())
        self.assertFalse((self.user / "runtime").exists())
        self.assertFalse((self.project / ".fstar" / "runtime").exists())

    def test_read_rejects_malformed_selection_shapes(self):
        cases = (
            {"topics": "T-1"},
            {"scope": "scenario:payments"},
            {"scope": ["scenario:payments", 7]},
            {"scope": ["global"]},
            {"documents": ["user:memory/plain.md", ""]},
            {"applicability": ["x"]},
            {"applicability": {"user:memory/plain.md": {"reason": "no state"}}},
            {"applicability": {"user:memory/plain.md": {"state": "maybe"}}},
            {"snapshot_hash": 42},
        )
        for selection in cases:
            with self.subTest(selection=selection):
                rc, payload = self.read(selection)
                self.assertEqual("knowledge_invalid_schema", payload["error"]["code"])
        rc, payload = self.call({"action": "read", "project_root": str(self.project),
                                 "user_root": str(self.user)})
        self.assertEqual("knowledge_invalid_schema", payload["error"]["code"])
        rc, payload = self.call({"action": "read", "project_root": str(self.project),
                                 "user_root": str(self.user), "selection": {},
                                 "max_bytes": -1})
        self.assertEqual("knowledge_invalid_schema", payload["error"]["code"])
        rc, payload = self.call({"action": "read", "project_root": str(self.project),
                                 "user_root": str(self.user), "selection": {},
                                 "max_bytes": "100"})
        self.assertEqual("knowledge_invalid_schema", payload["error"]["code"])

    def test_read_exposes_no_clock_override(self):
        self.learn("memory/legacy.md",
                   memory_document("Legacy lesson", scope="scenario:payments",
                                   confidence="verified", expires="2026-01-01",
                                   body="Legacy habit."))
        rc, payload = self.call({"action": "read", "project_root": str(self.project),
                                 "user_root": str(self.user),
                                 "selection": {"topics": [], "scope": ["scenario:payments"]},
                                 "now": "2025-01-01"})
        self.assertEqual("knowledge_invalid_schema", payload["error"]["code"])

    def test_read_budget_defers_bodies_whole(self):
        result = self.read_result(max_bytes=10)
        # The user index fits (small), the plain memory body does not.
        deferred = {item["key"] for item in result["required_unloaded"]}
        self.assertIn("user:memory/plain.md", deferred)
        self.assertIn("budget of 10 bytes exceeded",
                      {item["reason"] for item in result["required_unloaded"]})
        self.assertFalse(result["complete"])
        for document in result["documents"]:
            self.assertLessEqual(document["size"], 10)

    def test_read_snapshot_hash_gates_a_stale_selection(self):
        result = self.read_result(topics=[])
        rc, payload = self.read({"topics": [], "snapshot_hash": "stale"})
        self.assertEqual("knowledge_context_incomplete", payload["error"]["code"])
        self.assertEqual(result["snapshot_hash"], payload["error"]["details"]["expected"])

    # -- correction and retirement --------------------------------------
    def test_correction_chain_preserves_the_old_record(self):
        original = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="inferred",
            source="task-payments-042", body="Use rolling deployments for payments.")
        self.learn("memory/deployment.md", original)

        superseded = original.replace("status: active", "status: superseded")
        corrected = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="verified",
            source="user-correction-chat#7", body="Use blue/green deployments for payments.")
        request = self.write_request(
            [{"owner": "user", "path": "memory/deployment.md", "action": "supersede",
              "content": superseded},
             {"owner": "user", "path": "memory/deployment-corrected.md", "action": "create",
              "content": corrected}],
            intent={"summary": "correct the deployment lesson", "action": "correct",
                    "scope": "user experience memory",
                    "source": {"source_type": "conversation", "reference": "chat#7"}})
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        # No confirmation: nothing is written.
        before = self.user_snapshot()
        rc, payload = self.call(dict(request, action="apply"))
        self.assertEqual("knowledge_confirmation_required", payload["error"]["code"])
        self.assertEqual(before, self.user_snapshot())
        rc, applied = self.call(dict(request, action="apply",
                                     confirmation=self.confirmed(prepared, quote="no, use blue/green")))
        self.assertEqual(0, rc, applied)
        self.assertIn("user:memory/deployment.md", applied["result"]["receipt"]["changed_paths"])

        old = (self.user / "memory" / "deployment.md").read_text(encoding="utf-8")
        self.assertIn("status: superseded", old)
        self.assertIn("Use rolling deployments for payments.", old)
        self.assertIn("source: task-payments-042", old)
        new = (self.user / "memory" / "deployment-corrected.md").read_text(encoding="utf-8")
        self.assertIn("confidence: verified", new)
        self.assertIn("source: user-correction-chat#7", new)
        index = (self.user / "index.md").read_text(encoding="utf-8")
        self.assertNotIn("memory/deployment.md)", index)
        self.assertIn("memory/deployment-corrected.md", index)

        result = self.read_result(topics=[], scope=["scenario:payments"])
        keys = {document["key"] for document in result["documents"]}
        self.assertNotIn("user:memory/deployment.md", keys)
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("superseded", reasons["user:memory/deployment.md"])

    def test_retirement_stops_injection_through_every_path(self):
        text = memory_document("Deployment lesson", scope="scenario:payments",
                               confidence="verified", body="Use rolling deployments.")
        self.learn("memory/deployment.md", text)
        request = self.write_request(
            [{"owner": "user", "path": "memory/deployment.md", "action": "supersede",
              "content": text.replace("status: active", "status: superseded")}],
            intent={"summary": "retire the deployment lesson", "action": "supersede",
                    "scope": "user experience memory",
                    "source": {"source_type": "conversation", "reference": "chat#8"}})
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        rc, applied = self.call(dict(request, action="apply",
                                     confirmation=self.confirmed(prepared, quote="retire it")))
        self.assertEqual(0, rc, applied)
        self.assertIn("status: superseded",
                      (self.user / "memory" / "deployment.md").read_text(encoding="utf-8"))

        result = self.read_result(topics=[], scope=["scenario:payments"],
                                  documents=["user:memory/deployment.md"],
                                  dependencies=["user:memory/deployment.md"])
        keys = {document["key"] for document in result["documents"]}
        self.assertNotIn("user:memory/deployment.md", keys)
        reasons = {item["key"]: item["reason"] for item in result["excluded"]}
        self.assertIn("superseded", reasons["user:memory/deployment.md"])

    def test_prepare_and_apply_authentication_is_unchanged(self):
        text = memory_document("Plain lesson", body="Ordinary lesson.")
        request = self.write_request(
            [{"owner": "user", "path": "memory/plain-lesson.md", "action": "create",
              "content": text}])
        revoked = dict(request, extensions=[grant()])
        rc, payload = self.call(revoked)
        self.assertEqual("extension_not_authorized", payload["error"]["code"])
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        # Foreign or denied confirmations are rejected before any write.
        foreign = self.confirmed(prepared)
        foreign["proposal_hash"] = "other"
        rc, payload = self.call(dict(request, action="apply", confirmation=foreign))
        self.assertEqual("knowledge_confirmation_mismatch", payload["error"]["code"])
        denied = self.confirmed(prepared)
        denied["disposition"] = "denied"
        rc, payload = self.call(dict(request, action="apply", confirmation=denied))
        self.assertEqual("knowledge_confirmation_required", payload["error"]["code"])
        self.assertFalse((self.user / "memory" / "plain-lesson.md").exists())
        rc, applied = self.call(dict(request, action="apply",
                                     confirmation=self.confirmed(prepared)))
        self.assertEqual(0, rc, applied)


if __name__ == "__main__":
    unittest.main()
