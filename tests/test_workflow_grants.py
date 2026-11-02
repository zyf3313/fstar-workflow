import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fstar.models import DomainError
from fstar.project import initialize_project, initialize_workflow_project
from fstar.store import TaskStore
from fstar.tasks import TaskService
from fstar.tools import workflow_scan


def grant(package, included, excluded=()):
    return {"id": package, "scope": "custom", "included": list(included), "excluded": list(excluded)}


class WorkflowGrantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.user = root / "user"
        self.runtime = root / "runtime"
        self.gov = grant("project-governance", ["specs"])
        self.classify = grant("tool-capability", ["classification"])

    def scan(self, ref, extensions=None):
        return workflow_scan(project_root=self.project, user_root=self.user,
                             task_ref=ref, extensions=extensions)

    def assert_denied(self, fn):
        with self.assertRaises(DomainError) as caught:
            fn()
        self.assertEqual("extension_not_authorized", caught.exception.code)

    def test_session_init_and_scan_derive_grants_and_leave_no_bindings(self):
        with mock.patch.dict("os.environ", {"PATH": "", "HOME": self.tmp.name}):
            basic = initialize_workflow_project(self.project, self.user, task_ref="session-only",
                                                extensions=[])
            self.assertEqual("fstar.tools.scan.v1", basic.tool_proposals["schema"])
            result = initialize_workflow_project(self.project, self.user, task_ref="session-only",
                                                 extensions=[self.gov, self.classify])
            self.assertEqual("fstar.tools.scan.v1", result.tool_proposals["schema"])
            self.assertFalse((self.user / "tools.yaml").exists())
            self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())
            self.assert_denied(lambda: self.scan("session-only", [grant("tool-capability", [], ["classification"])]))
            self.assert_denied(lambda: self.scan("session-only", []))
            self.assertEqual("fstar.tools.scan.v1", self.scan("session-only", [self.classify])["schema"])

    def test_initial_scan_failure_reports_created_skeleton(self):
        with mock.patch("fstar.tools._classifier_scan", side_effect=RuntimeError("scanner failed")):
            result = initialize_workflow_project(self.project, self.user, task_ref="session-only")
        self.assertTrue((self.project / ".fstar" / ".schema-version").is_file())
        self.assertIsNone(result.tool_proposals)
        self.assertTrue(any(w.code == "TOOL_SCAN_FAILED" and "scanner failed" in w.message for w in result.warnings))
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())

    def test_no_project_scan_and_standalone_init(self):
        with mock.patch.dict("os.environ", {"PATH": "", "HOME": self.tmp.name}):
            self.assertEqual("fstar.tools.scan.v1", self.scan("session-only", [self.classify])["schema"])
            self.assertFalse((self.project / ".fstar").exists())
            self.assert_denied(lambda: self.scan("session-only", []))
            initialize_project(self.project, self.user)
            self.assertTrue((self.project / ".fstar" / ".schema-version").exists())

    def test_persistent_reload_exclusion_revoke_and_recovery(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        def enable(included, excluded=()):
            service.enable_extension("task", authorization={**grant("tool-capability", included, excluded),
                                    "source": {"type": "test"}}, actor=actor)
        with mock.patch.dict("os.environ", {"PATH": "", "HOME": self.tmp.name}):
            self.assert_denied(lambda: self.scan("task", [self.classify]))
            enable(["classification"])
            self.assertEqual("fstar.tools.scan.v1", self.scan("task")["schema"])
            enable([], ["classification"])
            self.assert_denied(lambda: self.scan("task", [self.classify]))
            enable(["classification"])
            self.assertEqual("fstar.tools.scan.v1", self.scan("task")["schema"])
            service.disable_extension("task", extension_id="tool-capability", authorization={"type": "test"}, actor=actor)
            self.assert_denied(lambda: self.scan("task", [self.classify]))
