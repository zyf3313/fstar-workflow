import fcntl
import json
import os
import time
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fstar import tools
from fstar.project import initialize_project
from fstar.store import TaskStore
from fstar.tasks import TaskService, source_snapshot, utc_now


class ToolsBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.user = self.root / "user"
        self.runtime = self.root / "runtime"
        self.bootstrap = Path(__file__).resolve().parents[1] / "bin" / "fstar-bootstrap.py"
        self.env = dict(os.environ, HOME=str(self.root), PATH="", PYTHONDONTWRITEBYTECODE="1")
        self.grant = {"id": "tool-capability", "scope": "custom", "included": ["bindings"], "excluded": []}
        self.request = {"action": "prepare", "project_root": str(self.project), "user_root": str(self.user),
                        "runtime_root": str(self.runtime), "task_ref": "session-only", "extensions": [self.grant],
                        "target": "user", "changes": {"code-structure": None}, "reason": "user requested unbinding"}

    def call(self, request):
        proc = subprocess.run([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], input=json.dumps(request),
                              env=self.env, cwd=self.project, capture_output=True, text=True, timeout=30)
        return proc.returncode, json.loads(proc.stdout)

    def confirm(self, proposal):
        return {"source_id": "input-1", "type": "conversation", "at": "2026-10-30T00:00:00Z",
                "actor": {"role": "user", "id": "user"}, "reference": "session/input-1", "quote": "unbind",
                "scope": {k: proposal[k] for k in ("target", "path", "changes", "tools")}, "validates": proposal["digest"]}

    def test_contract_assessment_and_actual_fallback_provenance(self):
        grant = dict(self.grant, included=["contracts", "bindings", "validation", "fallback"])
        base = {**self.request, "extensions": [grant]}
        code, result = self.call({**base, "action": "contract", "capability": "code-structure"})
        self.assertEqual(0, code, result)
        self.assertIn("## Fallback", result["result"]["contract"])
        contracts_only = {**base, "extensions": [dict(grant, included=["contracts"], excluded=["fallback"])]}
        code, result = self.call({**contracts_only, "action": "contract", "capability": "code-structure"})
        self.assertEqual(0, code, result)
        self.assertNotIn("## Fallback", result["result"]["contract"])
        self.assertNotIn("Literal text search locates text only", result["result"]["contract"])
        self.assertIn("## Recording requirements", result["result"]["contract"])
        code, result = self.call({**base, "action": "assess", "observations": []})
        self.assertEqual(0, code, result)
        gaps = result["result"]["assessment"]["gaps"]
        self.assertTrue(gaps)
        self.assertIn("fallback", gaps[0])
        trimmed = {**base, "extensions": [dict(grant, included=["bindings", "validation"], excluded=["fallback", "contracts"])]}
        code, result = self.call({**trimmed, "action": "assess", "observations": []})
        self.assertEqual(0, code, result)
        self.assertNotIn("fallback", result["result"]["assessment"]["gaps"][0])
        code, result = self.call({**trimmed, "action": "contract", "capability": "code-structure"})
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        call = {"capability": "code-structure", "tool": "fixture-tool", "at": "2026-10-30T00:00:00Z",
                "call": {"id": "fixture-1", "reference": "fixture/log", "operation": "lookup", "result": "passed"}}
        code, result = self.call({**trimmed, "action": "provenance", "call_record": call})
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        code, result = self.call({**trimmed, "action": "provenance", "call_record": {**call, "fallback": False}})
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        code, result = self.call({**base, "action": "provenance", "call_record": {**call, "call": {**call["call"], "result": "failed"}}})
        self.assertEqual(0, code, result)
        self.assertEqual("failed", result["result"]["record"]["call"]["result"])
        self.assertEqual("caller", result["result"]["persistence"])
        code, result = self.call({**base, "action": "provenance", "call_record": {**call, "tool": None}})
        self.assertEqual("tools_invalid_call_record", result["error"]["code"])
        code, result = self.call({**base, "action": "provenance", "call_record": call})
        self.assertEqual(0, code, result)
        self.assertEqual("fixture-tool", result["result"]["record"]["tool"])
        self.assertTrue(result["result"]["record"]["fallback"])
        self.assertFalse(self.user.exists())
        self.assertFalse(self.runtime.exists())
        self.assertFalse((self.project / ".fstar").exists())

    def test_contract_missing_pinned_version_and_unsafe_capability(self):
        self.user.mkdir()
        (self.user / "version").write_text("missing-version\n")
        grant = dict(self.grant, included=["contracts"])
        request = {**self.request, "extensions": [grant], "action": "contract", "capability": "code-structure"}
        code, result = self.call(request)
        self.assertNotEqual(0, code)
        self.assertEqual("resource_version_unavailable", result["error"]["code"])
        code, result = self.call({**request, "capability": "../outside"})
        self.assertEqual("tools_invalid_request", result["error"]["code"])
        self.assertFalse(self.runtime.exists())
        self.assertFalse((self.project / ".fstar").exists())

    def test_persistent_read_operations_recheck_revocation(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        authorization = {**self.grant, "included": ["contracts", "bindings", "validation", "fallback"], "source": {"type": "test"}}
        service.enable_extension("task", authorization=authorization, actor=actor)
        base = {**self.request, "task_ref": "task", "extensions": []}
        for action in ("contract", "assess"):
            code, result = self.call({**base, "action": action, "capability": "code-structure"})
            self.assertEqual(0, code, result)
        service.disable_extension("task", extension_id="tool-capability", authorization={"type": "test"}, actor=actor)
        for action in ("contract", "assess"):
            code, result = self.call({**base, "action": action, "capability": "code-structure"})
            self.assertEqual("extension_not_authorized", result["error"]["code"])
        self.assertFalse(self.user.exists())
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())

    def test_persistent_provenance_rechecks_grant_under_lock(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        authorization = {**self.grant, "included": ["bindings", "validation", "fallback"], "source": {"type": "test"}}
        service.enable_extension("task", authorization=authorization, actor=actor)
        source = {"source_id": "s", "type": "command", "at": utc_now(), "actor": actor,
                  "reference": "fixture", "quote": "", "scope": "task", "validates": source_snapshot(store.read("task"))}
        service.start("task", actor=actor, confirmation=source, session_id="s")
        lease = service.acquire_lease("task", holder="worker", role="implement", actor=actor)
        call = {"capability": "code-structure", "tool": "fixture-tool", "at": "2026-10-30T00:00:00Z",
                "call": {"id": "fixture-1", "reference": "fixture/log", "operation": "lookup", "result": "failed"}}
        request = {**self.request, "action": "provenance", "task_ref": "task", "extensions": [],
                   "call_record": call, "lease_token": "wrong"}
        before = store.read("task")
        code, result = self.call(request)
        self.assertEqual("invalid_lease", result["error"]["code"])
        self.assertEqual(before, store.read("task"))
        request["lease_token"] = lease["token"]
        # Hold the same project lock and trim the grant while a real bridge process waits.
        with store.transaction():
            proc = subprocess.Popen([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.project)
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
            time.sleep(0.2)
            self.assertIsNone(proc.poll())
            task = store.read("task")
            task["extensions"][0]["included"].remove("fallback")
            task["extensions"][0]["excluded"].append("fallback")
            store.write(store.resolve("task"), task)
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        self.assertNotEqual(0, proc.wait(timeout=10), stderr)
        self.assertEqual("extension_not_authorized", json.loads(stdout)["error"]["code"])
        proc.stdout.close()
        proc.stderr.close()
        self.assertEqual([], TaskStore(self.project, user_home=self.user, runtime_root=self.runtime).read("task")["capabilities"])
        with store.transaction():
            task = store.read("task")
            task["extensions"][0]["excluded"].remove("fallback")
            task["extensions"][0]["included"].append("fallback")
            store.write(store.resolve("task"), task)
        code, result = self.call(request)
        self.assertEqual(0, code, result)
        self.assertEqual("task", result["result"]["persistence"])
        recorded = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime).read("task")["capabilities"]
        self.assertEqual("fixture-tool", recorded[0]["tool"])
        self.assertEqual("failed", recorded[0]["call"]["result"])
        self.assertTrue(recorded[0]["fallback"])
        first_id = recorded[0]["id"]
        code, result = self.call(request)
        self.assertEqual(0, code, result)
        self.assertFalse(result["result"]["idempotent"])
        recorded = store.read("task")["capabilities"]
        self.assertEqual(2, len(recorded))
        self.assertNotEqual(first_id, recorded[1]["id"])
        self.assertEqual(recorded[0]["call"], recorded[1]["call"])

    def test_session_prepare_denial_and_confirmed_apply(self):
        denied = dict(self.request, extensions=[dict(self.grant, included=[], excluded=["bindings"])])
        code, result = self.call(denied)
        self.assertNotEqual(0, code)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        self.assertFalse(self.user.exists())
        self.assertFalse(self.runtime.exists())
        code, result = self.call(self.request)
        self.assertEqual(0, code, result)
        proposal = result["result"]["proposal"]
        self.assertFalse(self.user.exists())
        apply = {**self.request, "action": "apply", "proposal": proposal}
        code, result = self.call(apply)
        self.assertEqual("tools_confirmation_required", result["error"]["code"])
        self.assertFalse(self.user.exists())
        apply["confirmation"] = self.confirm(proposal)
        code, result = self.call(apply)
        self.assertEqual(0, code, result)
        self.assertEqual("applied", result["result"]["status"])
        self.assertTrue((self.user / "tools.yaml").is_file())
        self.assertFalse((self.project / ".fstar").exists())

    def test_prepare_rejects_symlink_and_malformed_target_without_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.project / ".fstar").symlink_to(outside, target_is_directory=True)
        code, result = self.call(dict(self.request, target="project"))
        self.assertNotEqual(0, code)
        self.assertEqual("tools_unsafe_target", result["error"]["code"])
        self.assertEqual([], list(outside.iterdir()))
        self.assertFalse(self.user.exists())
        self.assertFalse(self.runtime.exists())
        code, result = self.call(dict(self.request, target=[]))
        self.assertNotEqual(0, code)
        self.assertEqual("tools_invalid_proposal", result["error"]["code"])
        self.assertFalse(self.runtime.exists())

    def test_confirmation_and_target_tampering_are_rejected(self):
        code, result = self.call(self.request)
        self.assertEqual(0, code, result)
        proposal = result["result"]["proposal"]
        confirmation = self.confirm(proposal)
        for changed in (dict(confirmation, actor={"role": "agent", "id": "x"}),
                        dict(confirmation, validates="wrong"),
                        dict(confirmation, scope={**confirmation["scope"], "target": "project"})):
            code, result = self.call({**self.request, "action": "apply", "proposal": proposal, "confirmation": changed})
            self.assertNotEqual(0, code)
            self.assertIn(result["error"]["code"], ("tools_confirmation_required", "tools_stale_confirmation", "tools_invalid_confirmation"))
            self.assertFalse(self.user.exists())
            self.assertFalse(self.runtime.exists())
        code, result = self.call({**self.request, "action": "apply", "proposal": proposal,
                                  "confirmation": confirmation, "user_root": str(self.root / "other")})
        self.assertEqual("tools_unsafe_target", result["error"]["code"])
        self.assertFalse(self.runtime.exists())

    def test_apply_holds_task_lock_while_waiting_for_tools_lock(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        service.enable_extension("task", authorization={**self.grant, "source": {"type": "test"}}, actor=actor)
        request = {**self.request, "task_ref": "task", "extensions": []}
        code, result = self.call(request)
        self.assertEqual(0, code, result)
        proposal = result["result"]["proposal"]
        apply = {**request, "action": "apply", "proposal": proposal, "confirmation": self.confirm(proposal)}
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / "tools.lock").open("a+") as tools_lock:
            fcntl.flock(tools_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.project)
            self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
            proc.stdin.write(json.dumps(apply))
            proc.stdin.close()
            deadline = time.monotonic() + 3
            with store.lock_path.open("a+") as task_lock:
                while True:
                    try:
                        fcntl.flock(task_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(task_lock, fcntl.LOCK_UN)
                    except BlockingIOError:
                        break
                    self.assertIsNone(proc.poll(), "apply exited before acquiring task lock")
                    self.assertLess(time.monotonic(), deadline, "apply did not acquire task lock")
                    time.sleep(0.01)
                fcntl.flock(tools_lock, fcntl.LOCK_UN)
                stdout = proc.stdout.read()
                stderr = proc.stderr.read()
                self.assertEqual(0, proc.wait(timeout=10), stderr)
                self.assertEqual("applied", json.loads(stdout)["result"]["status"])
                fcntl.flock(task_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(task_lock, fcntl.LOCK_UN)
            proc.stdout.close()
            proc.stderr.close()

    def test_persistent_reloads_revoked_grant_before_commit(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        request = {**self.request, "task_ref": "task", "extensions": []}
        code, result = self.call(request)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        service.enable_extension("task", authorization={**self.grant, "source": {"type": "test"}}, actor=actor)
        code, result = self.call(request)
        self.assertEqual(0, code, result)
        proposal = result["result"]["proposal"]
        service.disable_extension("task", extension_id="tool-capability", authorization={"type": "test"}, actor=actor)
        apply = {**request, "action": "apply", "proposal": proposal, "confirmation": self.confirm(proposal)}
        code, result = self.call(apply)
        self.assertEqual("extension_not_authorized", result["error"]["code"])
        self.assertFalse(self.user.exists())
        service.enable_extension("task", authorization={**self.grant, "source": {"type": "test"}}, actor=actor)
        code, result = self.call(apply)
        self.assertEqual(0, code, result)
        self.assertEqual("applied", result["result"]["status"])

    def _bound_tools_document(self, tool_id, path):
        # A valid fstar.tools.v1 layer binding one capability to a tool.
        snapshot = {
            "tool": tool_id,
            "kind": "cli",
            "version": "1.0.0",
            "capabilities": [{"id": "code-structure", "match": "strong", "basis": "user fixture",
                              "basis_source": {"kind": "registry", "reference": "fixture/registry"}}],
        }
        confirmation = {
            "source_id": "fixture-bind-1",
            "type": "conversation",
            "at": "2026-10-30T00:00:00Z",
            "actor": {"role": "user", "id": "user"},
            "reference": "fixture/input-1",
            "quote": "use the fixture tool",
            "scope": {"target": "user", "path": str(path), "changes": {"code-structure": tool_id}, "tools": {}},
            "validates": "fixture-digest",
        }
        return {
            "schema": "fstar.tools.v1",
            "detected_at": "2026-10-30T00:00:00Z",
            "tools": [snapshot],
            "bindings": {"code-structure": {"tool": tool_id, "reason": "fixture", "confirmation": confirmation}},
            "history": [],
        }

    def _apply_request(self, tool_id, snapshot):
        user_tools = self.user / "tools.yaml"
        proposal = tools.build_binding_proposal(target="user", loaded=tools.load_tools(user_tools),
                                                changes={"code-structure": tool_id},
                                                reason="race writer switches the binding",
                                                tools={tool_id: snapshot})
        confirmation = {"source_id": "input-2", "type": "conversation", "at": "2026-10-30T00:00:00Z",
                         "actor": {"role": "user", "id": "user"}, "reference": "session/input-2",
                         "quote": "switch to the other tool",
                         "scope": {k: proposal[k] for k in ("target", "path", "changes", "tools")},
                         "validates": proposal["digest"]}
        return {**self.request, "action": "apply", "task_ref": "session-only",
                "extensions": [dict(self.grant)], "proposal": proposal, "confirmation": confirmation}

    def test_persistent_provenance_waits_for_current_valid_binding(self):
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        service.enable_extension("task", authorization={**self.grant, "included": ["bindings", "validation"], "source": {"type": "test"}}, actor=actor)
        source = {"source_id": "s", "type": "command", "at": utc_now(), "actor": actor, "reference": "fixture", "quote": "", "scope": "task", "validates": source_snapshot(store.read("task"))}
        service.start("task", actor=actor, confirmation=source, session_id="s")
        lease = service.acquire_lease("task", holder="worker", role="implement", actor=actor)
        call = {"capability": "code-structure", "at": "2026-10-30T00:00:00Z", "call": {"id": "fixture", "reference": "fixture/log", "operation": "lookup", "result": "passed"}}
        request = {**self.request, "action": "provenance", "task_ref": "task", "extensions": [], "call_record": call, "lease_token": lease["token"]}
        self.user.mkdir(parents=True, exist_ok=True)
        path = self.user / "tools.yaml"
        with store.transaction():
            proc = subprocess.Popen([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.project)
            self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), "stale unbound state rejected before locking")
            with tools.tools_lock(self.runtime):
                path.write_text(tools.serialize_tools(self._bound_tools_document("fixture-tool", path)))
        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        self.assertEqual(0, proc.wait(timeout=10), stderr + stdout)
        self.assertEqual("fixture-tool", json.loads(stdout)["result"]["record"]["tool"])
        proc.stdout.close()
        proc.stderr.close()

    def test_two_process_binding_race_cannot_commit_stale_snapshot(self):
        # Real two-process race: a confirmed binding change in one bridge
        # process lands while a provenance commit in another bridge process has
        # already resolved the old bindings. The commit rebuilds the record
        # under the task lock and the cooperating tools lock, so the stored
        # record reflects the post-change binding (fallback, not a stale bound
        # call) and no deadlock occurs (task lock first, then tools lock).
        initialize_project(self.project, self.user)
        store = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime)
        service = TaskService(store)
        actor = {"role": "user", "id": "user", "session": "s"}
        service.create(name="task", title="Task", description="test", actor=actor, session_id="s")
        authorization = {**self.grant, "included": ["bindings", "validation", "fallback"], "source": {"type": "test"}}
        service.enable_extension("task", authorization=authorization, actor=actor)
        source = {"source_id": "s", "type": "command", "at": utc_now(), "actor": actor,
                  "reference": "fixture", "quote": "", "scope": "task", "validates": source_snapshot(store.read("task"))}
        service.start("task", actor=actor, confirmation=source, session_id="s")
        lease = service.acquire_lease("task", holder="worker", role="implement", actor=actor)
        # Seed a real user-layer binding to fixture-tool.
        self.user.mkdir(parents=True, exist_ok=True)
        user_tools = self.user / "tools.yaml"
        user_tools.write_text(tools.serialize_tools(self._bound_tools_document("fixture-tool", user_tools)),
                              encoding="utf-8")
        stale_digest = tools.load_tools(user_tools)["digest"]
        call = {"capability": "code-structure", "tool": "fixture-tool", "at": "2026-10-30T00:00:00Z",
                "call": {"id": "fixture-1", "reference": "fixture/log", "operation": "lookup", "result": "passed"}}
        request = {**self.request, "action": "provenance", "task_ref": "task", "extensions": [],
                   "call_record": call, "lease_token": lease["token"]}
        # Gate the committer on the task lock: it resolves bindings first, then
        # blocks acquiring the task lock inside record_provenance.
        committer = subprocess.Popen([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.project)
        committer.stdin.write(json.dumps(request))
        committer.stdin.close()
        self.addCleanup(lambda: committer.kill() if committer.poll() is None else None)
        snapshot = self._bound_tools_document("another-tool", user_tools)["tools"][0]
        writer_request = self._apply_request("another-tool", snapshot)
        with store.transaction():
            # Give the committer time to resolve the old binding and block on
            # the task lock inside record_provenance; if it is slower it
            # resolves after the write and the committed record is still the
            # new one, so the assertion below holds in every interleaving.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.assertIsNone(committer.poll(), "committer exited while the task lock was held")
                time.sleep(0.2)
                break
            # The writer is a real second bridge process; a session-only apply
            # takes only the tools lock, so it completes while the task lock is
            # held here.
            writer = subprocess.Popen([sys.executable, "-I", str(self.bootstrap), "tools_bridge"], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.project)
            writer.stdin.write(json.dumps(writer_request))
            writer.stdin.close()
            writer_stdout = writer.stdout.read()
            writer_stderr = writer.stderr.read()
            self.assertEqual(0, writer.wait(timeout=10), writer_stderr)
            self.assertEqual("applied", json.loads(writer_stdout)["result"]["status"])
            writer.stdout.close()
            writer.stderr.close()
        # Release the task lock: the committer takes it, then the tools lock,
        # rebuilds from the switched binding, and commits.
        stdout = committer.stdout.read()
        stderr = committer.stderr.read()
        self.assertEqual(0, committer.wait(timeout=10), stderr)
        result = json.loads(stdout)["result"]
        self.assertEqual("task", result["persistence"])
        self.assertTrue(result["rebuilt"])
        committer.stdout.close()
        committer.stderr.close()
        # A fresh store read: the record must not present the stale pre-race
        # binding as current. With the old binding the actual tool matched, so a
        # stale snapshot would record fallback=false with the old binding
        # digest; the rebuilt record marks the fallback instead.
        recorded = TaskStore(self.project, user_home=self.user, runtime_root=self.runtime).read("task")["capabilities"]
        self.assertEqual(1, len(recorded))
        self.assertEqual("fixture-tool", recorded[0]["tool"])
        self.assertTrue(recorded[0]["fallback"])
        self.assertEqual("user", recorded[0]["binding_origin"]["layer"])
        self.assertNotEqual(stale_digest, recorded[0]["binding_origin"]["digest"])
        self.assertEqual(tools.load_tools(user_tools)["digest"], recorded[0]["binding_origin"]["digest"])
