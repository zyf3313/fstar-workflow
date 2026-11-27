"""Cross-project procedure scope fixtures.

The learn skill routes a procedure by its applicable scope, not by its
kind: a project procedure stays in project references, while a procedure
the user explicitly states applies across projects goes to user rules or
user memory through the normal authorized pipeline.  These tests use only
temporary HOME, user_root, project_root and runtime directories and never
touch the real ``~/.fstar`` or ``~/.claude``.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar.project import initialize_project

ROOT = Path(__file__).resolve().parents[1]


def grant(*members):
    return {"id": "project-governance", "scope": "custom", "included": list(members), "excluded": []}


RULE_PROCEDURE = (
    "---\n"
    "schema: fstar.knowledge.v1\n"
    "type: rule\n"
    "status: active\n"
    "strength: default\n"
    "---\n"
    "# Cross-project release procedure\n"
    "\n"
    "## Stage 1\n"
    "- step: run the full suite\n"
    "- evidence: full suite exits 0\n"
    "\n"
    "## Stage 2\n"
    "- step: publish\n"
    "- evidence: publish receipt\n"
    "\n"
    "APPLIES: all projects.\n"
    "SOURCE: user instruction in chat.\n"
)

PROJECT_PROCEDURE = (
    "---\n"
    "schema: fstar.knowledge.v1\n"
    "type: reference\n"
    "status: active\n"
    "---\n"
    "# Project-only procedure\n"
    "Steps with evidence fields.\n"
)


class UserProcedureScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.project, self.user = base / "project", base / "user"
        self.project.mkdir()
        self.user.mkdir()
        initialize_project(self.project, self.user)
        self.home = base / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH="",
                        PYTHONDONTWRITEBYTECODE="1",
                        FSTAR_USER_ROOT=str(self.user),
                        FSTAR_RUNTIME_ROOT=str(base / "runtime"))
        self.real_fstar = Path.home() / ".fstar"
        self.real_fstar_before = self._tree(self.real_fstar)

    def _tree(self, root):
        if not root.exists():
            return None
        return {str(p.relative_to(root)): p.stat().st_mtime for p in root.rglob("*") if p.is_file()}

    def call(self, request):
        result = subprocess.run([sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"), "learn_bridge"],
                                input=json.dumps(request), text=True, capture_output=True, env=self.env)
        return result.returncode, json.loads(result.stdout)

    def confirmed(self, prepared):
        proposal = prepared["result"]["proposal"]
        return {"disposition": "approved", "source_type": "conversation", "source_ref": "message 9",
                "quote": "Save this procedure for all projects", "confirmed_at": "2026-11-26",
                "proposal_hash": prepared["result"]["proposal_hash"],
                "scope": proposal["scope"], "owners": proposal["owners"]}

    def user_request(self, **overrides):
        request = {"action": "prepare", "project_root": str(self.project), "user_root": str(self.user),
                   "task_ref": "session-only", "extensions": [grant("rules")],
                   "edits": [{"owner": "user", "path": "rules/release-procedure.md", "action": "create",
                              "content": RULE_PROCEDURE}],
                   "intent": {"summary": "Cross-project release procedure", "action": "create",
                              "scope": "user", "source": {"source_type": "conversation", "reference": "message 9"}},
                   "assessment": {}}
        request.update(overrides)
        return request

    def user_snapshot(self):
        return {str(p.relative_to(self.user)): p.read_bytes() for p in self.user.rglob("*") if p.is_file()}

    def test_prepare_requires_the_destination_member(self):
        rc, result = self.call(self.user_request(extensions=[grant("memory")]))
        self.assertEqual(3, rc, result)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        self.assertEqual({"package": "project-governance", "member": "rules"}, result["error"]["details"])
        rc, prepared = self.call(self.user_request())
        self.assertEqual(0, rc, prepared)
        self.assertEqual(["rules"], prepared["result"]["required_members"])
        # The proposal itself includes the user index change.
        changed = [edit["relative"] for edit in prepared["result"]["proposal"]["edits"]]
        self.assertIn("index.md", changed)

    def test_apply_confirmation_gates_and_writes_user_rule(self):
        before = self.user_snapshot()
        rc, prepared = self.call(self.user_request())
        self.assertEqual(0, rc, prepared)
        apply = dict(self.user_request(), action="apply")
        rc, result = self.call(apply)
        self.assertEqual("knowledge_confirmation_required", result["error"]["code"])
        self.assertEqual(before, self.user_snapshot())
        tampered = self.confirmed(prepared)
        tampered["scope"] = "project"
        rc, result = self.call(dict(apply, confirmation=tampered))
        self.assertEqual("knowledge_confirmation_mismatch", result["error"]["code"])
        self.assertEqual(before, self.user_snapshot())
        tampered = self.confirmed(prepared)
        tampered["proposal_hash"] = "0" * 64
        rc, result = self.call(dict(apply, confirmation=tampered))
        self.assertEqual("knowledge_confirmation_mismatch", result["error"]["code"])
        self.assertEqual(before, self.user_snapshot())
        rc, result = self.call(dict(apply, confirmation=self.confirmed(prepared)))
        self.assertEqual(0, rc, result)
        target = self.user / "rules/release-procedure.md"
        self.assertEqual(RULE_PROCEDURE, target.read_text())
        index = (self.user / "index.md").read_text()
        self.assertIn("release-procedure", index)

    def test_other_project_reads_the_user_procedure_not_project_ones(self):
        rc, prepared = self.call(self.user_request())
        self.assertEqual(0, rc, prepared)
        rc, result = self.call(dict(self.user_request(), action="apply", confirmation=self.confirmed(prepared)))
        self.assertEqual(0, rc, result)
        # A project-level procedure in the first project.
        project_request = {"action": "prepare", "project_root": str(self.project), "user_root": str(self.user),
                           "task_ref": "session-only", "extensions": [grant("knowledge")],
                           "edits": [{"owner": "project", "path": ".fstar/knowledge/references/procedures/build.md",
                                      "action": "create", "content": PROJECT_PROCEDURE}],
                           "intent": {"summary": "Project build procedure", "action": "create", "scope": "project",
                                      "source": {"source_type": "conversation", "reference": "message 10"}},
                           "assessment": {}}
        rc, project_prepared = self.call(project_request)
        self.assertEqual(0, rc, project_prepared)
        confirmation = self.confirmed(project_prepared)
        confirmation["quote"] = "Save the project procedure"
        confirmation["scope"] = project_prepared["result"]["proposal"]["scope"]
        confirmation["owners"] = project_prepared["result"]["proposal"]["owners"]
        rc, result = self.call(dict(project_request, action="apply", confirmation=confirmation))
        self.assertEqual(0, rc, result)
        # A second project under the same user root reads the user procedure.
        other = Path(self.tmp.name) / "other-project"
        other.mkdir()
        initialize_project(other, self.user)
        read = {"action": "read", "project_root": str(other), "user_root": str(self.user),
                "selection": {"topics": [], "documents": [], "dependencies": [], "global_constraints": [],
                              "excluded": [], "scope": []}}
        rc, result = self.call(read)
        self.assertEqual(0, rc, result)
        bodies = "\n".join(doc["text"] for doc in result["result"]["documents"])
        self.assertIn("Cross-project release procedure", bodies)
        self.assertNotIn("Project-only procedure", bodies)
        self.assertFalse((other / ".fstar/knowledge/references/procedures/build.md").exists())

    def test_real_user_home_untouched(self):
        after = self._tree(self.real_fstar)
        self.assertEqual(self.real_fstar_before, after)


if __name__ == "__main__":
    unittest.main()
