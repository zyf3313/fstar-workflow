import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService


class ToolsWorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.user = self.root / "user"
        self.runtime = self.root / "runtime"
        self.env = dict(os.environ, HOME=str(self.home), PATH="", PYTHONDONTWRITEBYTECODE="1")
        self.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        self.grant = {"id": "tool-capability", "scope": "custom", "included": ["classification"], "excluded": []}

    def scan(self, *args):
        return subprocess.run([sys.executable, "-m", "fstar", "--json", "--project", str(self.project),
                               "--user-data-root", str(self.user), "--runtime-root", str(self.runtime),
                               "tools", "scan", *args], cwd=self.project, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def result(self, process, expected):
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(expected, json.loads(process.stdout)["schema"])

    def error(self, process, expected):
        self.assertNotEqual(0, process.returncode)
        self.assertEqual(expected, json.loads(process.stderr)["error"]["code"])

    def test_session_grants_independent_and_invalid_inputs(self):
        grant = json.dumps(self.grant)
        self.result(self.scan(), "fstar.tools.scan.v1")
        self.error(self.scan("--task-ref", "session-only"), "extension_not_authorized")
        self.result(self.scan("--task-ref", "session-only", "--extension", grant), "fstar.tools.scan.v1")
        excluded = dict(self.grant, included=[], excluded=["classification"])
        self.error(self.scan("--task-ref", "session-only", "--extension", json.dumps(excluded)), "extension_not_authorized")
        self.error(self.scan("--task-ref", "session-only", "--extension", "{}"), "invalid_extension")
        for malformed in (dict(self.grant, id=[]), dict(self.grant, scope={})):
            self.error(self.scan("--task-ref", "session-only", "--extension", json.dumps(malformed)), "invalid_extension")
        self.error(self.scan("--task-ref", "session-only", "--extension", "oops"), "invalid_extension")
        self.error(self.scan("--extension", grant), "invalid_extension")
        self.assertNotEqual(0, self.scan("--task-re", "session-only").returncode)
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse(self.user.exists())
        self.assertFalse(self.runtime.exists())
        self.assertEqual([], list(self.home.iterdir()))

    def test_persistent_current_grants_and_revocation(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        self.error(self.scan("--task-ref", "task"), "extension_not_authorized")
        self.error(self.scan("--task-ref", "task", "--extension", json.dumps(self.grant)), "invalid_extension")
        service.enable_extension("task", authorization={**self.grant, "source": {"type": "test"}}, actor=actor)
        self.result(self.scan("--task-ref", "task"), "fstar.tools.scan.v1")
        other = self.root / "other"
        other.mkdir()
        wrong_root = subprocess.run([sys.executable, "-m", "fstar", "--json", "--project", str(other),
                                     "--user-data-root", str(self.user), "tools", "scan", "--task-ref", "task"],
                                    cwd=self.project, env=self.env, capture_output=True, text=True, timeout=60)
        self.error(wrong_root, "project_not_initialized")
        self.assertFalse((other / ".fstar").exists())
        service.disable_extension("task", extension_id="tool-capability", authorization={"type": "test"}, actor=actor)
        self.error(self.scan("--task-ref", "task"), "extension_not_authorized")
        self.error(self.scan("--task-ref", "task", "--extension", json.dumps(self.grant)), "invalid_extension")
        service.enable_extension("task", authorization={**self.grant, "source": {"type": "test"}}, actor=actor)
        self.result(self.scan("--task-ref", "task"), "fstar.tools.scan.v1")
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())
        self.assertFalse((self.user / "tools.yaml").exists())
