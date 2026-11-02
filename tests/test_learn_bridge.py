import json
import os
import time
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService

ROOT = Path(__file__).resolve().parents[1]


def grant(*members):
    return {"id": "project-governance", "scope": "custom", "included": list(members), "excluded": []}


class LearnBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project, self.user = root / "project", root / "user"
        self.project.mkdir()
        self.user.mkdir()
        initialize_project(self.project, self.user)
        self.env = dict(os.environ, HOME=str(root / "home"), PATH="", PYTHONDONTWRITEBYTECODE="1", FSTAR_USER_ROOT=str(self.user), FSTAR_RUNTIME_ROOT=str(root / "runtime"))
        self.request = {"action": "prepare", "project_root": str(self.project), "user_root": str(self.user),
                        "task_ref": "session-only", "extensions": [grant("knowledge")],
                        "edits": [{"owner": "project", "path": ".fstar/knowledge/context/note.md", "action": "create", "content": "# Note\nFact.\n"}],
                        "intent": {"summary": "Record fact", "action": "create", "scope": "project", "source": {"source_type": "conversation", "reference": "message 1"}},
                        "assessment": {}}

    def call(self, request):
        result = subprocess.run([sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"), "learn_bridge"],
                                input=json.dumps(request), text=True, capture_output=True, env=self.env)
        return result.returncode, json.loads(result.stdout)

    def confirmed(self, prepared):
        proposal = prepared["result"]["proposal"]
        return {"disposition": "approved", "source_type": "conversation", "source_ref": "message 2", "quote": "Save this", "confirmed_at": "2026-10-30", "proposal_hash": prepared["result"]["proposal_hash"], "scope": proposal["scope"], "owners": proposal["owners"]}

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}

    def test_session_confirmation_digest_grants_and_reference_closure(self):
        before = self.snapshot()
        rc, prepared = self.call(self.request)
        self.assertEqual(0, rc, prepared)
        self.assertEqual(before, self.snapshot())
        apply = dict(self.request, action="apply")
        rc, result = self.call(apply)
        self.assertEqual("knowledge_confirmation_required", result["error"]["code"])
        self.assertEqual(before, self.snapshot())
        apply["confirmation"] = self.confirmed(prepared)
        changed = dict(apply, edits=[dict(self.request["edits"][0], content="# Note\nChanged.\n")])
        rc, result = self.call(changed)
        self.assertEqual("knowledge_confirmation_mismatch", result["error"]["code"])
        excluded = dict(apply, extensions=[grant()])
        rc, result = self.call(excluded)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        bad_link = dict(self.request, edits=[dict(self.request["edits"][0], content="# Note\n[missing](missing.md)\n")])
        rc, result = self.call(bad_link)
        self.assertEqual("knowledge_reference_error", result["error"]["code"])
        self.assertEqual(before, self.snapshot())
        rc, result = self.call(apply)
        self.assertEqual(0, rc, result)
        self.assertIn("Fact.", (self.project / ".fstar/knowledge/context/note.md").read_text())
        self.assertFalse((self.project / ".fstar/tasks").exists())
        self.assertFalse((self.user / "tools.yaml").exists())
        self.assertFalse((self.project / ".fstar/tools.yaml").exists())

    def test_explicit_index_requires_both_destination_members(self):
        path = self.project / ".fstar/index.md"
        request = dict(self.request, edits=[{"owner": "project", "path": ".fstar/./index.md", "action": "replace", "content": path.read_text()}])
        rc, result = self.call(request)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        request["extensions"] = [grant("knowledge", "specs")]
        rc, result = self.call(request)
        self.assertEqual(0, rc, result)
        self.assertEqual(["knowledge", "specs"], result["result"]["required_members"])

    def test_rename_with_explicit_inbound_update_through_bridge(self):
        directory = self.project / ".fstar/knowledge/context"
        directory.mkdir(parents=True)
        old = directory / "old.md"
        inbound = directory / "inbound.md"
        old.write_text("# Old\nFact.\n")
        inbound.write_text("# Inbound\n[old](old.md)\n")
        rename = {"owner": "project", "path": ".fstar/knowledge/context/old.md", "action": "rename", "rename_to": ".fstar/knowledge/context/new.md"}
        from fstar.knowledge import load_catalog
        catalog = load_catalog(user_root=self.user, project_root=self.project)
        reviewed = [{"key": source.key, "digest": source.digest}
                    for source in list(catalog.documents) + list(catalog.indexes)]
        request = dict(self.request, edits=[rename], assessment={"reviewed": reviewed, "coverage": "complete"})
        before = self.snapshot()
        rc, result = self.call(request)
        self.assertEqual("knowledge_reference_error", result["error"]["code"])
        self.assertEqual(before, self.snapshot())
        request["edits"] = [rename, {"owner": "project", "path": ".fstar/knowledge/context/inbound.md", "action": "replace", "content": "# Inbound\n[new](new.md)\n"}]
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        rc, result = self.call(dict(request, action="apply", confirmation=self.confirmed(prepared)))
        self.assertEqual(0, rc, result)
        self.assertFalse(old.exists())
        self.assertEqual("# Old\nFact.\n", (directory / "new.md").read_text())
        self.assertIn("[new](new.md)", inbound.read_text())

    def test_roots_and_cross_category_destinations(self):
        content = "---\nschema: fstar.knowledge.v1\ntype: memory\nstatus: active\nkind: lesson\ntrust: confirmed\n---\n# Note\nFact.\n"
        source = self.user / "memory/note.md"
        source.parent.mkdir()
        source.write_text(content)
        import hashlib
        digest = hashlib.sha256(content.encode()).hexdigest()
        edit = {"owner": "user", "path": "memory/note.md", "action": "rename", "rename_to": "rules/note.md", "content": "---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\nstrength: default\n---\n# Note\nMUST test.\n"}
        request = dict(self.request, edits=[edit], extensions=[grant("memory")], assessment={"reviewed": [{"key": "user:memory/note.md", "digest": digest}]})
        rc, result = self.call(request)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        request["extensions"] = [grant("memory", "rules")]
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        self.assertEqual(["memory", "rules"], prepared["result"]["required_members"])
        other = Path(self.tmp.name) / "other-user"
        other.mkdir()
        (other / "memory").mkdir()
        (other / "memory/note.md").write_text(content)
        rc, result = self.call(dict(request, action="apply", user_root=str(other), confirmation=self.confirmed(prepared)))
        self.assertEqual("knowledge_confirmation_mismatch", result["error"]["code"])
        self.assertTrue(source.exists())
        self.assertFalse((other / "rules/note.md").exists())
        project_request = dict(self.request)
        rc, project_prepared = self.call(project_request)
        self.assertEqual(0, rc, project_prepared)
        other_project = Path(self.tmp.name) / "other-project"
        other_project.mkdir()
        initialize_project(other_project, self.user)
        rc, result = self.call(dict(project_request, action="apply", project_root=str(other_project), confirmation=self.confirmed(project_prepared)))
        self.assertEqual("knowledge_confirmation_mismatch", result["error"]["code"])
        self.assertFalse((other_project / ".fstar/knowledge/context/note.md").exists())

    def test_publication_serializes_cooperating_revocation(self):
        runtime = Path(self.tmp.name) / "runtime"
        store = TaskStore(self.project, user_home=self.user, runtime_root=runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        service.enable_extension("task", authorization={**grant("knowledge"), "source": {"type": "test"}}, actor=actor)
        request = dict(self.request, task_ref="task", extensions=[], runtime_root=str(runtime))
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        apply = dict(request, action="apply", confirmation=self.confirmed(prepared))
        # Pause at the actual provider boundary after authorization, while the
        # bridge owns the task lock. A separate revoker must wait for publication.
        ready = Path(self.tmp.name) / "ready"
        release = Path(self.tmp.name) / "release"
        code_apply = 'import sys,time; from pathlib import Path; from fstar import learn_bridge as b; original=b.k.apply_change; ready=Path(sys.argv[1]); release=Path(sys.argv[2]);\ndef paused(*a,**kw):\n ready.touch()\n while not release.exists(): time.sleep(.01)\n return original(*a,**kw)\nb.k.apply_change=paused; sys.exit(b.main())'
        env = dict(self.env, PYTHONPATH=str(ROOT / "src"))
        with self.subTest(order="publish then revoke"):
            proc = subprocess.Popen([sys.executable, "-c", code_apply, str(ready), str(release)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            proc.stdin.write(json.dumps(apply))
            proc.stdin.close()
            self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
            deadline = time.monotonic() + 4
            while not ready.exists():
                if time.monotonic() > deadline:
                    self.fail("bridge did not reach publication")
                time.sleep(0.02)
            code = 'from pathlib import Path; import sys; from fstar.store import TaskStore; from fstar.tasks import TaskService; s=TaskService(TaskStore(Path(sys.argv[1]),user_home=Path(sys.argv[2]),runtime_root=Path(sys.argv[3]))); s.disable_extension("task",extension_id="project-governance",authorization={"type":"test"},actor={"role":"user","id":"user","session":"s"})'
            env = dict(self.env, PYTHONPATH=str(ROOT / "src"))
            revoke = subprocess.Popen([sys.executable, "-c", code, str(self.project), str(self.user), str(runtime)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            self.addCleanup(lambda: revoke.kill() if revoke.poll() is None else None)
            time.sleep(0.2)
            self.assertIsNone(revoke.poll())
            self.assertFalse((self.project / ".fstar/knowledge/context/note.md").exists())
            release.touch()
            proc.stdin = None
            stdout, stderr_apply = proc.communicate(timeout=5)
            output = json.loads(stdout)
            self.assertEqual(0, proc.returncode, output)
            _, stderr = revoke.communicate(timeout=5)
            self.assertEqual(0, revoke.returncode, stderr)
        self.assertTrue((self.project / ".fstar/knowledge/context/note.md").is_file())
        self.assertEqual([], store.read("task")["extensions"])

    def test_revocation_wins_before_waiting_apply_without_knowledge_writes(self):
        runtime = Path(self.tmp.name) / "runtime"
        store = TaskStore(self.project, user_home=self.user, runtime_root=runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        service.enable_extension("task", authorization={**grant("knowledge"), "source": {"type": "test"}}, actor=actor)
        request = dict(self.request, task_ref="task", extensions=[], runtime_root=str(runtime))
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        apply = dict(request, action="apply", confirmation=self.confirmed(prepared))
        with store.transaction():
            task_dir = store.resolve("task")
            task = store._read_path(task_dir / "task.json")
            task["extensions"] = []
            proc = subprocess.Popen([sys.executable, "-I", str(ROOT / "bin/fstar-bootstrap.py"), "learn_bridge"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, env=self.env)
            self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
            proc.stdin.write(json.dumps(apply))
            proc.stdin.close()
            time.sleep(0.2)
            self.assertIsNone(proc.poll())
            store.write(task_dir, task)
        proc.stdin = None
        stdout, stderr = proc.communicate(timeout=10)
        self.assertEqual("extension_not_authorized", json.loads(stdout)["error"]["code"], stderr)
        self.assertFalse((self.project / ".fstar/knowledge/context/note.md").exists())
        self.assertFalse((self.project / ".fstar/runtime/knowledge").exists())

    def test_persistent_grants_reloaded_at_apply(self):
        store = TaskStore(self.project, user_home=self.user, runtime_root=Path(self.tmp.name) / "runtime")
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        def enable(record):
            service.enable_extension("task", authorization={**record, "source": {"type": "test"}}, actor=actor)
        request = dict(self.request, task_ref="task", extensions=[], runtime_root=str(Path(self.tmp.name) / "runtime"))
        rc, result = self.call(request)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        enable(grant("knowledge"))
        rc, prepared = self.call(request)
        self.assertEqual(0, rc, prepared)
        apply = dict(request, action="apply", confirmation=self.confirmed(prepared))
        enable(grant())
        before = self.snapshot()
        rc, result = self.call(apply)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        self.assertEqual(before, self.snapshot())
        enable(grant("knowledge"))
        rc, result = self.call(apply)
        self.assertEqual(0, rc, result)


if __name__ == "__main__":
    unittest.main()
