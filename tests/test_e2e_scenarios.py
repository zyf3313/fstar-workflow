"""End-to-end scenario suite for fstar (child task e2e-verify, design §4).

Every scenario drives the REAL CLI and the REAL runtime hook entrypoints as
subprocesses (``python3 -m fstar ...`` / ``python3 -m fstar.runtime <hook>``
with ``PYTHONPATH=src`` and explicit temporary roots), never in-process API
shortcuts. The only exceptions are steps the child design explicitly labels
"internal-API setup" (persist_artifact_map, record_provenance,
resolve_bindings/apply_binding, knowledge load/prepare/apply), each marked
``setup=internal-api`` in the evidence ledger, because no CLI command exists
for them.

Isolation profile (design §5): four TemporaryDirectory roots (project / user /
runtime / host). No network. No real ``~/.fstar`` / ``~/.claude`` / host
settings are ever read or written: every command receives explicit roots, and
scenario S6 snapshots the real home locations to prove they were untouched.

Evidence ledger: when ``FSTAR_E2E_EVIDENCE_DIR`` is set, every step appends a
record (command, exit code, expected, actual, verdict) to
``e2e-run-<YYYY-MM-DD>.md`` in that directory. The same code is the regression
suite (unset → assert only). FAIL records are written and then fail the test;
nothing is silently dropped.

Python 3.9 standard library only.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import shlex
import time
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
EVIDENCE_DIR = os.environ.get("FSTAR_E2E_EVIDENCE_DIR")
RUN_DATE = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

# Real home locations that must never be touched (S6-5). Snapshot before/after.
REAL_HOME_PATHS = [Path.home() / ".fstar", Path.home() / ".claude" / "settings.json"]


# ---------------------------------------------------------------------------
# Evidence ledger
# ---------------------------------------------------------------------------

def _ledger_path() -> Path:
    return Path(EVIDENCE_DIR) / ("e2e-run-%s.md" % RUN_DATE)


_LEDGER_HEADER = {
    "written": False,
}


def record_step(scenario: str, step: str, command: str, exit_code, expected: str,
                actual: str, verdict: str, *, setup: str = "") -> None:
    """Append full evidence; a failed ledger write fails the run."""
    if not EVIDENCE_DIR:
        return
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n### %s %s — %s\n\n" % (scenario, step, verdict.upper()))
        stream.write("```json\n" + json.dumps({
            "command": command, "exit_code": exit_code, "expected": expected,
            "actual": actual, "verdict": verdict, "setup": setup,
            "evidence_level": "fixture-test", "live_delivery": 0,
        }, ensure_ascii=False, indent=2) + "\n```\n")


def retain_process_log(step: str, command, process, duration: float) -> list:
    """Persist actual subprocess output only when evidence recording is requested."""
    if not EVIDENCE_DIR:
        return []
    directory = Path(EVIDENCE_DIR).resolve() / "process-logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%s-%s.json" % (step, uuid.uuid4().hex))
    entry = {"command": command, "cwd": "isolated project fixture (removed after run)",
             "exit_code": process.returncode, "stdout": process.stdout,
             "stderr": process.stderr, "duration_seconds": duration,
             "python": sys.version, "evidence_level": "fixture-test"}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(entry, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with path.open(encoding="utf-8") as stream:
        assert json.load(stream) == entry
    return [str(path)]


def record_note(scenario: str, note: str) -> None:
    if not EVIDENCE_DIR:
        return
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n**%s note**: %s\n" % (scenario, note))


# ---------------------------------------------------------------------------
# Harness base
# ---------------------------------------------------------------------------

class ScenarioCase(unittest.TestCase):
    """Four temporary roots; real subprocess CLI; evidence recording."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="fstar-e2e-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.user_root = self.root / "user" / ".fstar"
        self.user_root.mkdir(parents=True)
        self.runtime_root = self.root / "runtime"
        self.host_root = self.root / "hosts"
        self.scenario = "S?"
        self._last_stdout = ""
        self._explicit_hook_env = set()
        # Real-home snapshot for the isolation assertion (S6-5, checked in
        # tearDown of every scenario so a leak anywhere fails loudly).
        self._home_before = _snapshot_paths(REAL_HOME_PATHS)

    def _callTestMethod(self, method):
        try:
            return super()._callTestMethod(method)
        except Exception as exc:
            process = getattr(self, "_process", None)
            record_step(self.scenario, "scenario-exception", getattr(self, "_command", "fixture setup"),
                        process.returncode if process else None, "scenario completes all assertions",
                        repr(exc), "fail")
            raise

    def tearDown(self) -> None:
        after = _snapshot_paths(REAL_HOME_PATHS)
        if after != self._home_before:
            self.fail("Isolation breach: real home paths changed during %s" % self.scenario)

    def run_process(self, command, **kwargs):
        env = kwargs.get("env", {})
        # Never inherit another task's runtime/project pointers.
        for key in ("FSTAR_PROJECT", "FSTAR_USER_ROOT", "FSTAR_RUNTIME_ROOT"):
            if key not in self._explicit_hook_env:
                env.pop(key, None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        started = time.monotonic()
        process = subprocess.run(command, **kwargs)
        self._command = shlex.join(command)
        self._process = process
        record_note(self.scenario, "Subprocess execution (assertions recorded separately):\n```json\n" +
                    json.dumps({"argv": command, "cwd": kwargs.get("cwd"),
                                "environment": {k: env[k] for k in ("HOME", "PYTHONPATH", "PATH", "FSTAR_PROJECT", "FSTAR_USER_ROOT", "FSTAR_RUNTIME_ROOT") if k in env},
                                "stdin": kwargs.get("input"), "exit_code": process.returncode,
                                "stdout": process.stdout, "stderr": process.stderr,
                                "duration_seconds": time.monotonic() - started}, indent=2) + "\n```")
        return process

    def require(self, condition, detail):
        self.assertTrue(condition, detail)
        return detail

    # -- subprocess runners ------------------------------------------------

    def cli(self, args, *, stdin=None, cwd=None, env_extra=None):
        """Run the real CLI: python3 -m fstar <args> with PYTHONPATH=src."""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["HOME"] = str(self.root / "fake-home")
        env["PATH"] = ""
        (self.root / "fake-home").mkdir(exist_ok=True)
        env.update(env_extra or {})
        process = self.run_process(
            [sys.executable, "-m", "fstar"] + ["--json"] + args,
            input=stdin, text=True, capture_output=True, env=env,
            cwd=str(cwd or self.root), timeout=120)
        return process

    def cli_project(self, args, **kwargs):
        """CLI invocation bound to the fixture project/user/runtime roots."""
        return self.cli(["--project", str(self.project),
                         "--user-data-root", str(self.user_root),
                         "--runtime-root", str(self.runtime_root)] + args, **kwargs)

    def cli_user_only(self, args, **kwargs):
        """CLI invocation with user/runtime roots but NO project (session-only paths)."""
        return self.cli(["--user-data-root", str(self.user_root),
                         "--runtime-root", str(self.runtime_root)] + args, **kwargs)

    def step_user(self, step_id, args, *, expected, check, cwd=None, setup: str = ""):
        """Run one session-only CLI step (no --project) and record it."""
        process = self.cli_user_only(args, cwd=cwd)
        self._last_stdout = process.stdout
        command = self._command
        try:
            detail = check(process)
            verdict = "pass"
        except Exception:
            verdict = "fail"
            record_step(self.scenario, step_id, command, process.returncode,
                        expected, _actual_of(process), verdict, setup=setup)
            raise
        record_step(self.scenario, step_id, command, process.returncode,
                    expected, _actual_of(process) + "\nassertion: " + str(detail), verdict, setup=setup)
        return process

    def hook(self, name, payload, *, cwd=None, project=None):
        """Run the real runtime hook entrypoint with a JSON payload on stdin."""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["HOME"] = str(self.root / "fake-home")
        (self.root / "fake-home").mkdir(exist_ok=True)
        env["FSTAR_USER_ROOT"] = str(self.user_root)
        env["FSTAR_RUNTIME_ROOT"] = str(self.runtime_root)
        env.pop("FSTAR_PROJECT", None)
        self._explicit_hook_env = {"FSTAR_USER_ROOT", "FSTAR_RUNTIME_ROOT", "FSTAR_PROJECT"}
        if project is not None:
            env["FSTAR_PROJECT"] = str(project)
        process = self.run_process(
            [sys.executable, "-m", "fstar.runtime", name],
            input=json.dumps(payload), text=True, capture_output=True, env=env,
            cwd=str(cwd or self.root), timeout=120)
        self._explicit_hook_env = set()
        return process

    # -- evidence-aware assertion helpers ----------------------------------

    def step(self, step_id: str, args, *, expected: str, check, stdin=None,
             cwd=None, env_extra=None, setup: str = ""):
        """Run one CLI step, record it, and assert the check callback."""
        process = self.cli_project(args, stdin=stdin, cwd=cwd, env_extra=env_extra)
        self._last_stdout = process.stdout
        command = self._command
        try:
            detail = check(process)
            verdict = "pass"
        except Exception:
            verdict = "fail"
            record_step(self.scenario, step_id, command, process.returncode,
                        expected, _actual_of(process), verdict, setup=setup)
            raise
        record_step(self.scenario, step_id, command, process.returncode,
                    expected, _actual_of(process) + "\nassertion: " + str(detail), verdict, setup=setup)
        return process

    def step_hook(self, step_id: str, hook_name, payload, *, expected: str, check,
                  cwd=None, project=None, setup: str = ""):
        process = self.hook(hook_name, payload, cwd=cwd, project=project)
        command = self._command + " stdin=" + json.dumps(payload)
        try:
            detail = check(process)
            verdict = "pass"
        except Exception:
            verdict = "fail"
            record_step(self.scenario, step_id, command, process.returncode,
                        expected, _actual_of(process), verdict, setup=setup)
            raise
        record_step(self.scenario, step_id, command, process.returncode,
                    expected, _actual_of(process) + "\nassertion: " + str(detail), verdict, setup=setup)
        return process

    def record_blocked(self, step_id: str, what: str, needs: str) -> None:
        record_step(self.scenario, step_id, "(not executed)", "—",
                    what, "blocked: %s" % needs, "blocked")

    def record_skipped(self, step_id: str, what: str) -> None:
        record_step(self.scenario, step_id, "(not executed)", "—",
                    what, "skipped by design", "skipped")

    # -- fixture helpers ----------------------------------------------------

    def json_of(self, process):
        self.assertEqual(0, process.returncode, process.stderr)
        return json.loads(process.stdout)

    def error_code_of(self, process):
        payload = json.loads(process.stderr) if process.stderr.strip() else {}
        return payload.get("error", {}).get("code", "")

    def expect_error(self, code, status=None):
        def check(process):
            self.assertNotEqual(0, process.returncode,
                                "expected error %s, got rc=0: %s" % (code, process.stdout[:300]))
            actual = self.error_code_of(process)
            self.assertEqual(code, actual,
                             "expected error %s, got %s (stderr=%s)" % (code, actual, process.stderr[:300]))
            if status is not None:
                self.assertEqual(status, process.returncode)
            return "rc=%d code=%s" % (process.returncode, actual)
        return check

    def expect_ok(self, predicate=None):
        def check(process):
            self.assertEqual(0, process.returncode, process.stderr[:500])
            payload = json.loads(process.stdout)
            if predicate:
                detail = predicate(payload)
                self.assertTrue(detail is None or detail is True or isinstance(detail, str),
                                "predicate must return None/True/str")
                return detail
            return ""
        return check

    @property
    def last_stdout(self):
        return self._last_stdout

    def tree_snapshot(self, *roots):
        return _snapshot_paths([Path(root) for root in roots])

    def write_json(self, name, payload):
        path = self.root / ("fixtures-%s" % uuid.uuid4().hex[:8]) / name
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def session_grant(self, step_id, package, included, excluded, scope="custom"):
        process = self.step_user(step_id, ["extension", "enable", package,
                                           "--scope", scope, "--confirm-user",
                                           "--invocation", "e2e-%s" % step_id]
                                          + [arg for value in included for arg in ("--include", value)]
                                          + [arg for value in excluded for arg in ("--exclude", value)],
                                 expected="session-only authorization validated without project writes",
                                 check=self.expect_ok(lambda p: self.require(p.get("persistence") == "session_only", "persistence=%s" % p["persistence"])),
                                 cwd=self.empty)
        return self.json_of(process)["authorization"]

    def task_path(self, ref):
        matches = list((self.project / ".fstar" / "tasks").rglob(ref + "/task.json"))
        self.assertEqual(1, len(matches), ref)
        return matches[0].parent

    def task_json(self, ref):
        path = self.task_path(ref) / "task.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def write_task_json(self, ref, data):
        path = self.task_path(ref) / "task.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")

    def internal_api(self, function, *args, **kwargs):
        """Run an internal-API setup step in a fresh interpreter (design §5).

        Used only where the design labels a step "internal-API setup" because
        no CLI command exists. The step runs as a real subprocess too, so no
        in-process state leaks between steps.
        """
        code = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "store = TaskStore(Path(%r), user_home=Path(%r), runtime_root=Path(%r))\n"
            "service = TaskService(store)\n"
            "function, args, kwargs = %r, %r, %r\n"
            "if function == 'persist_artifact_map':\n"
            "    from fstar.content import extract_artifact, build_artifact_map, REQUIRED_SLOTS\n"
            "    artifact = next(iter(kwargs['mapping']))\n"
            "    template = {'artifact_type': 'prd', 'slots': {name: {'start_marker': '<!-- '+name+':start -->', 'end_marker': '<!-- '+name+':end -->'} for name in REQUIRED_SLOTS}, 'items': {'mode': 'explicit', 'entries': [{'id': 'R-001', 'start_marker': '<!-- R1:start -->', 'end_marker': '<!-- R1:end -->'}]}}\n"
            "    extracted = extract_artifact((store.project_root / artifact).read_text(), template, artifact=artifact)\n"
            "    assert extracted.ok, extracted.diagnostics\n"
            "    kwargs['mapping'] = build_artifact_map([extracted])\n"
            "result = getattr(service.evidence, function)(*args, **kwargs)\n"
            "print(json.dumps(result, ensure_ascii=False, default=str))\n"
            % (str(SRC), str(self.project), str(self.user_root), str(self.runtime_root),
               function, args, kwargs))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        return process


def _actual_of(process) -> str:
    if process.returncode != 0:
        return (process.stderr or process.stdout).strip()
    return (process.stdout or "").strip()


def _snapshot_paths(paths):
    snapshot = {}
    for path in paths:
        if not path.exists():
            snapshot[str(path)] = None
            continue
        if path.is_file():
            snapshot[str(path)] = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            digest = hashlib.sha256()
            for item in sorted(path.rglob("*")):
                digest.update(str(item).encode())
                if item.is_file():
                    digest.update(item.read_bytes())
                    digest.update(str(item.stat().st_mtime_ns).encode())
            snapshot[str(path)] = digest.hexdigest()
    return snapshot


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Shared S1 fixture: initialized project + main task + child task
# ---------------------------------------------------------------------------

PRD_BODY = "# PRD\n\n<!-- R1:start -->\nR-001: deliver the counter module.\n<!-- R1:end -->\n"
PRD_BODY = "".join("<!-- %s:start -->%s<!-- %s:end -->\n" % (slot, value, slot)
                   for slot, value in (("artifact_type", "prd"), ("version", "1"),
                                       ("review_state", "approved"), ("author", "fixture"),
                                       ("date", "2026-10-30"), ("reviewer", "user"))) + PRD_BODY
PLAN_BODY = "# Plan\n\n<!-- P1:start -->\nP-1: implement counter.\n<!-- P1:end -->\n"


class PersistentLifecycleCase(ScenarioCase):
    """S1/S2/S3 share the initialized-project + task fixture helpers."""

    def init_project(self):
        self.step("setup-init", ["init", str(self.project)],
                  expected="project init creates .fstar skeleton",
                  check=self.expect_ok(lambda payload: "created=%d" % len(payload.get("created", []))))
        self.step("setup-init-user", ["init", "--user", str(self.user_root)],
                  expected="user init creates user index/config",
                  check=self.expect_ok())

    def create_main_task(self, name="main-task"):
        self.step("create-main", ["task", "create", "Deliver counter", "--name", name,
                                  "--description", "Deliver R-001"],
                  expected="task create returns planning task",
                  check=self.expect_ok(lambda p: self.require(not (p["task"]["phase"] != "planning"), "phase=planning")))

    def create_child_task(self, parent, name="child-task"):
        self.step("create-child", ["task", "create", "Child deliverable", "--name", name,
                                   "--description", "Deliver R-001", "--parent", parent],
                  expected="child created under subtasks/",
                  check=self.expect_ok(
                      lambda p: self.require(not ("subtasks" not in p["path"]), "path=%s" % p["path"])))

    def enable_extension(self, step_id, task, extension, extra=()):
        self.step(step_id, ["extension", "enable", extension, task,
                            "--confirm-user", "--invocation", "e2e-%s" % step_id] + list(extra),
                  expected="extension enabled with source/scope recorded",
                  check=self.expect_ok(lambda p: self.require(not ("scope" not in p), "scope=%s" % p["scope"])))

    def write_docs(self, ref="main-task"):
        task_dir = self.task_path(ref)
        (task_dir / "doc").mkdir(parents=True, exist_ok=True)
        (task_dir / "doc" / "prd.md").write_text(PRD_BODY, encoding="utf-8")
        (task_dir / "plan.md").write_text(PLAN_BODY, encoding="utf-8")
        (task_dir / "implement.jsonl").write_text(
            json.dumps({"file": "doc/prd.md", "reason": "requirements"}) + "\n", encoding="utf-8")

    def persist_map(self, step_id, ref="main-task"):
        """Internal-API setup (no CLI): extract + persist the artifact map."""
        mapping = {str((self.task_path(ref) / "doc/prd.md").relative_to(self.project)): {
            "R-001": {"start_marker": "<!-- R1:start -->", "end_marker": "<!-- R1:end -->",
                      "dependencies": []}}}
        process = self.internal_api("persist_artifact_map", ref, mapping=mapping,
                                    source={"type": "e2e-setup", "reference": step_id})
        command = "internal-api: TaskService.evidence.persist_artifact_map(ref=%r)" % ref
        try:
            self.assertEqual(0, process.returncode, process.stderr)
            payload = json.loads(process.stdout)
            self.assertIn("artifact_map", payload)
            verdict = "pass"
        except Exception:
            record_step(self.scenario, step_id, command, process.returncode,
                        "artifact map persisted in meta.templates", _actual_of(process), "fail",
                        setup="internal-api")
            raise
        record_step(self.scenario, step_id, command, process.returncode,
                    "artifact map persisted in meta.templates",
                    "sha256=%s" % payload.get("sha256", "")[:12], "pass", setup="internal-api")
        return payload

    def snapshot_item(self, ref, artifact, items):
        """Internal-API read used to build dispatch baselines."""
        code = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "store = TaskStore(Path(%r), user_home=Path(%r), runtime_root=Path(%r))\n"
            "service = TaskService(store)\n"
            "print(json.dumps(service.evidence.snapshot(%r, artifact=%r, items=%r), ensure_ascii=False))\n"
            % (str(SRC), str(self.project), str(self.user_root), str(self.runtime_root),
               ref, artifact, items))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)

    def delivery_snapshot(self, paths):
        code = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "store = TaskStore(Path(%r), user_home=Path(%r), runtime_root=Path(%r))\n"
            "service = TaskService(store)\n"
            "print(json.dumps(service.evidence.delivery_snapshot(%r), ensure_ascii=False))\n"
            % (str(SRC), str(self.project), str(self.user_root), str(self.runtime_root), paths))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)

    def dispatch(self, step_id, role, task_ref, payload_file, coordinator="coordinator"):
        self.step(step_id, ["dispatch", role, "--payload", str(payload_file),
                            "--coordinator", coordinator],
                  expected="dispatch registered with lease token",
                  check=self.expect_ok(lambda p: self.require(not ("lease_token" not in p), "registered dispatch=%s" % p["dispatch_id"])))

    def build_dispatch_payload(self, role, task_ref, plan_items, allowed_paths, baseline):
        payload = {
            "schema": "fstar.dispatch.v1",
            "dispatch_id": str(uuid.uuid4()),
            "task_ref": task_ref,
            "role": role,
            "plan_item_ids": plan_items,
            "baseline": baseline,
            "input_versions": [],
            "allowed_paths": allowed_paths,
            "read_context": [],
            "required_validations": [],
            "return_conditions": {"done": "", "blocked": "", "failed": ""},
            "prompt_first_line": "Active task: session-only" if task_ref == "session-only"
            else "Active task: %s" % task_ref,
        }
        return payload

    def register_dispatch(self, step_id, payload, coordinator="coordinator", extensions=()):
        """Register a dispatch through the real CLI and return (token, payload)."""
        if payload["role"] in {"research", "editor"} and not extensions:
            # Optional dispatch roles require the caller to name its session
            # grant; the fixture helper refuses to invent one silently.
            raise AssertionError("fixture %s needs an extension grant for role %s" % (step_id, payload["role"]))
        payload_file = self.write_json("payload-%s.json" % payload["dispatch_id"][:8], payload)
        command = ["dispatch", payload["role"], "--payload", str(payload_file), "--coordinator", coordinator]
        for record in extensions:
            command += ["--extension", record]
        process = self.step(step_id, command,
                            expected="registered=true with lease_token",
                            check=self.expect_ok(lambda p: self.require(not (not p.get("registered")), "lease=%s" % p.get("lease_token", "")[:8])))
        result = json.loads(process.stdout)
        return result["lease_token"], result["payload"]


# ===========================================================================
# S1 — persistent lifecycle full loop (15 steps)
# ===========================================================================

class S1PersistentLifecycle(PersistentLifecycleCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S1"

    def test_s1_full_lifecycle(self):
        # S1-1 init (project + user), repeat init preserves
        self.init_project()
        before = self.tree_snapshot(self.project / ".fstar")
        self.step("S1-1b", ["init", str(self.project)],
                  expected="repeat init preserves existing files",
                  check=self.expect_ok(lambda p: self.require(not (not p.get("preserved")), "preserved=%d" % len(p["preserved"]))))
        self.assertEqual(before, self.tree_snapshot(self.project / ".fstar"))

        # S1-2 task create + extensions
        self.create_main_task()
        self.create_child_task("main-task")
        self.enable_extension("S1-2c", "main-task", "persistent-task")
        self.enable_extension("S1-2d", "main-task", "planning-review")
        task = self.task_json("main-task")
        self.assertTrue(any(e["id"] == "persistent-task" for e in task["extensions"]))
        self.assertTrue(any(e["type"] == "extension_enabled" for e in task["events"]))

        # S1-3 docs + artifact map (internal-API setup)
        self.write_docs("main-task")
        self.persist_map("S1-3", "main-task")

        # S1-4 review gate: start without confirmation rejected
        self.step("S1-4", ["start", "main-task"],
                  expected="rc!=0 confirmation_required",
                  check=self.expect_error("confirmation_required", 3))

        # S1-5 start with user confirmation
        self.step("S1-5", ["start", "main-task", "--confirm-user",
                           "--invocation", "e2e-S1-5"],
                  expected="planning -> in_progress; started event binds snapshot",
                  check=self.expect_ok(lambda p: self.require(not (p["phase"] != "in_progress"), "phase=in_progress")))
        task = self.task_json("main-task")
        started = [e for e in task["events"] if e["type"] == "started"]
        self.assertTrue(started and started[-1]["data"].get("snapshot"))

        # S1-6 dispatch implement -> worker edits delivery file -> harvest
        (self.project / "src.py").write_text("value = 1\n", encoding="utf-8")
        (self.project / "test_delivery.py").write_text(
            "import unittest\nimport src\n\n"
            "class DeliveryTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(4, src.value)\n", encoding="utf-8")
        artifact = ".fstar/tasks/main-task/doc/prd.md"
        snap = self.snapshot_item("main-task", artifact, ["R-001"])
        delivery = self.delivery_snapshot(["src.py"])
        payload = self.build_dispatch_payload("implement", "main-task", ["P-1"], ["src.py"],
                                              {"artifact_items": [snap], "delivery": delivery})
        token, registered = self.register_dispatch("S1-6a", payload)
        # Simulated worker: edit the delivery file (allowed path).
        (self.project / "src.py").write_text("value = 2\n", encoding="utf-8")
        result_body = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["src.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-6b", ["dispatch", "harvest",
                            "--result", str(self.write_json("r.json", result_body)),
                            "--payload", str(self.write_json("p.json", registered)),
                            "--lease-token", token],
                  expected="delivery evidence recorded; lease renewed +30m",
                  check=self.expect_ok(lambda p: self.require(not (not p.get("recorded")), "evidence=%s next=%s" % (p.get("evidence_id", "")[:8], p.get("next")))))
        task = self.task_json("main-task")
        self.assertTrue(any(e["kind"] == "delivery" and e["state"] == "valid" for e in task["evidence"]))

        # S1-7 illegal-transition battery
        self.step("S1-7a", ["accept", "child-task", "--confirm-user", "--invocation", "x"],
                  expected="accept on planning task rejected (acceptance_blocked)",
                  check=self.expect_error("acceptance_blocked", 3))
        self.step("S1-7b", ["accept", "main-task", "--confirm-user", "--invocation", "x"],
                  expected="parent acceptance checks unfinished children before evidence",
                  check=self.expect_error("children_incomplete", 3))
        confirmation = {
            "source_id": "agent-fake", "type": "command", "at": _utc_now(),
            "actor": {"role": "agent", "id": "agent-1"}, "reference": "cli",
            "quote": "", "scope": "accept", "validates": "",
        }
        self.step("S1-7c", ["accept", "main-task", "--confirmation",
                            str(self.write_json("conf.json", confirmation))],
                  expected="agent-role accept source rejected",
                  check=lambda process: self.expect_error("acceptance_forbidden", 3)(process))
        self.step("S1-7d", ["archive", "child-task", "--confirm-user", "--invocation", "x"],
                  expected="archiving a child alone rejected (archive_child_forbidden)",
                  check=self.expect_error("archive_child_forbidden", 3))
        self.step("S1-7e", ["--actor-role", "agent", "--actor", "agent-1", "drop", "child-task", "--reason", "agent tries drop", "--confirm-user", "--invocation", "e2e-agent-drop"],
                  expected="non-user drop rejected (drop_forbidden)",
                  check=self.expect_error("drop_forbidden", 3))

        # S1-8 dispatch check with one failed item -> harvest -> acceptance status
        check_snap = self.snapshot_item("main-task", artifact, ["R-001"])
        check_delivery = self.delivery_snapshot(["src.py", "test_delivery.py"])
        check_payload = self.build_dispatch_payload("check", "main-task", ["P-1"], [],
                                                    {"artifact_items": [check_snap], "delivery": check_delivery})
        check_token, check_registered = self.register_dispatch("S1-8a", check_payload)
        command = [sys.executable, "-B", "-m", "unittest", "test_delivery"]
        started_at = time.monotonic()
        failure = subprocess.run(command, cwd=self.project, capture_output=True, text=True)
        failed_duration = time.monotonic() - started_at
        failure_logs = retain_process_log("S1-failure", command, failure, failed_duration)
        record_step(self.scenario, "S1-executed-failure", shlex.join(command), failure.returncode,
                    "fixture delivery test fails", "log_refs=%s\n%s%s" % (failure_logs, failure.stdout, failure.stderr),
                    "pass" if failure.returncode != 0 else "fail", setup="fixture subprocess")
        self.assertNotEqual(0, failure.returncode)
        self.assertIn("FAIL: test_value", failure.stderr)
        self.assertIn("AssertionError: 4 != 2", failure.stderr)
        self.assertIn("Ran 1 test", failure.stderr)
        failed_check = {
            "kind": "check", "producer": {"role": "check", "id": "checker-1", "session_id": "c1"},
            "validates": [check_snap], "run_id": "run-fail-1",
            "environment": {"python": sys.version.split()[0]},
            "delivery": check_delivery, "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [],
                       "command": shlex.join(command), "result": "failed", "exit_code": failure.returncode,
                       "log_refs": failure_logs, "duration": failed_duration, "retries": 0}],
        }
        # The sibling status rows are REAL executed checks, not synthetic
        # projection inputs: each row records an actual `python -B -m
        # unittest` subprocess against a fixture module whose outcome is that
        # state, with the real exit code, stdout/stderr and retained log path.
        executed_states = self.execute_remaining_check_states(command, failed_check["items"][0])
        failed_check["items"].extend(executed_states)
        check_result = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": check_payload["dispatch_id"],
            "role": "check", "status": "done", "changed_paths": [],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-8b", ["dispatch", "harvest",
                            "--result", str(self.write_json("cr.json", check_result)),
                            "--payload", str(self.write_json("cp.json", check_registered)),
                            "--lease-token", check_token,
                            "--check-evidence", str(self.write_json("ce.json", failed_check))],
                  expected="failed check recorded; awaiting_acceptance=false",
                  check=self.expect_ok())
        self.step("S1-8c", ["acceptance", "status", "main-task"],
                  expected="blockers contain unresolved_check; five-state item visible",
                  check=self.expect_ok(lambda p: (
                      self.require(not ("unresolved_check" not in p["blockers"]), "blockers=%s results=%s" % (p["blockers"], p["checks"][-1]["results"])))))

        status = json.loads(self.last_stdout)
        self.assertFalse(status["awaiting_acceptance"])
        self.assertEqual({"passed", "failed", "blocked", "skipped", "not_run"},
                         set(status["checks"][-1]["results"]))
        with self.subTest(contract="acceptance status includes check provenance"):
            self.step("S1-8-status-provenance", ["acceptance", "status", "main-task"],
                      expected="design §2 promises run_id/environment/delivery on each check",
                      check=self.expect_ok(lambda value: self.require(
                          value["checks"][-1]["run_id"] == failed_check["run_id"]
                          and value["checks"][-1]["environment"] == failed_check["environment"]
                          and value["checks"][-1]["delivery"] == failed_check["delivery"]
                          and value["checks"][-1]["items"] == failed_check["items"],
                          "acceptance status exposes recorded provenance and item coverage")))

        # S1-9 fix, final check all passed, accept
        fix_snap = self.snapshot_item("main-task", artifact, ["R-001"])
        fix_delivery = self.delivery_snapshot(["src.py"])
        fix_payload = self.build_dispatch_payload("implement", "main-task", ["P-1"], ["src.py"],
                                                  {"artifact_items": [fix_snap], "delivery": fix_delivery})
        fix_token, fix_registered = self.register_dispatch("S1-9a", fix_payload)
        (self.project / "src.py").write_text("value = 4  # fixed\n", encoding="utf-8")
        fix_result = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": fix_payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["src.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-9b", ["dispatch", "harvest",
                            "--result", str(self.write_json("fr.json", fix_result)),
                            "--payload", str(self.write_json("fp.json", fix_registered)),
                            "--lease-token", fix_token],
                  expected="fix delivery recorded",
                  check=self.expect_ok())
        final_snap = self.snapshot_item("main-task", artifact, ["R-001"])
        final_delivery = self.delivery_snapshot(["src.py", "test_delivery.py"])
        final_payload = self.build_dispatch_payload("check", "main-task", ["P-1"], [],
                                                    {"artifact_items": [final_snap], "delivery": final_delivery})
        final_token, final_registered = self.register_dispatch("S1-9c", final_payload)
        unrelated = {"id": "unrelated-fixture-evidence", "kind": "review",
                     "producer": {"role": "user", "id": "fixture-reviewer"}, "validates": []}
        unrelated_process = self.internal_api("record", "main-task", evidence=unrelated, lease_token=final_token)
        record_step(self.scenario, "S1-unrelated-setup", self._command, unrelated_process.returncode,
                    "record independent review evidence through evidence API",
                    _actual_of(unrelated_process), "pass" if unrelated_process.returncode == 0 else "fail", setup="internal-api")
        self.assertEqual(0, unrelated_process.returncode, unrelated_process.stderr)
        started_at = time.monotonic()
        rerun = subprocess.run(command, cwd=self.project, capture_output=True, text=True)
        rerun_duration = time.monotonic() - started_at
        rerun_logs = retain_process_log("S1-rerun", command, rerun, rerun_duration)
        record_step(self.scenario, "S1-executed-rerun", shlex.join(command), rerun.returncode,
                    "repaired fixture delivery test passes", "log_refs=%s\n%s%s" % (rerun_logs, rerun.stdout, rerun.stderr),
                    "pass" if rerun.returncode == 0 else "fail", setup="fixture subprocess")
        self.assertEqual(0, rerun.returncode, rerun.stderr)
        self.assertIn("Ran 1 test", rerun.stderr)
        self.assertIn("OK", rerun.stderr)
        self.assertNotEqual(check_delivery["digest"], final_delivery["digest"])
        self.assertEqual(final_delivery, self.delivery_snapshot(["src.py", "test_delivery.py"]))
        passed_check = {
            "kind": "check", "producer": {"role": "check", "id": "checker-2", "session_id": "c2"},
            "validates": [final_snap], "run_id": "run-pass-1",
            "environment": {"python": sys.version.split()[0]},
            "delivery": final_delivery, "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": ["test_delivery.DeliveryTest.test_value"],
                       "command": shlex.join(command), "result": "passed", "exit_code": rerun.returncode,
                       "log_refs": rerun_logs, "duration": rerun_duration, "retries": 1}],
        }
        final_result = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": final_payload["dispatch_id"],
            "role": "check", "status": "done", "changed_paths": [],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-9d", ["dispatch", "harvest",
                            "--result", str(self.write_json("nr.json", final_result)),
                            "--payload", str(self.write_json("np.json", final_registered)),
                            "--lease-token", final_token,
                            "--check-evidence", str(self.write_json("nce.json", passed_check))],
                  expected="final check recorded",
                  check=self.expect_ok())
        recorded_checks = [e for e in self.task_json("main-task")["evidence"] if e["kind"] == "check"]
        self.assertEqual("failed", recorded_checks[-2]["items"][0]["result"])
        self.assertEqual(failure_logs, recorded_checks[-2]["items"][0]["log_refs"])
        self.assertEqual("passed", recorded_checks[-1]["items"][0]["result"])
        self.assertEqual(rerun_logs, recorded_checks[-1]["items"][0]["log_refs"])
        if EVIDENCE_DIR:
            for refs, process in ((failure_logs, failure), (rerun_logs, rerun)):
                self.assertEqual(1, len(refs))
                with Path(refs[0]).open(encoding="utf-8") as stream:
                    retained = json.load(stream)
                self.assertEqual(process.returncode, retained["exit_code"])
                self.assertEqual(process.stdout, retained["stdout"])
                self.assertEqual(process.stderr, retained["stderr"])
        self.assertEqual(final_delivery, recorded_checks[-1]["delivery"])
        self.assertEqual(final_snap, recorded_checks[-1]["validates"][0])
        # Release the coordinator lease so acceptance is not blocked by it.
        self.release_lease_internal("S1-9e", "main-task", final_token)
        self.step("S1-9f", ["acceptance", "status", "main-task"],
                  expected="awaiting_acceptance=true (children_incomplete still blocks parent accept)",
                  check=self.expect_ok(lambda p: self.require(not (not p["awaiting_acceptance"]), "awaiting; blockers=%s" % p["blockers"])))

        # S1-10 child completes the same chain, then archive the whole tree
        self.complete_child("child-task")
        self.step("S1-10a", ["accept", "main-task", "--confirm-user",
                             "--invocation", "e2e-S1-10"],
                  expected="accept writes completed/completedAt/acceptance",
                  check=self.expect_ok(lambda p: self.require(not (p["phase"] != "completed"), "phase=completed")))
        task = self.task_json("main-task")
        self.assertEqual(26, len(task))
        self.assertNotIn("review", task)
        self.assertFalse((self.task_path("main-task") / "doc/review-log.md").exists())
        self.assertTrue(task["completedAt"] and task["acceptance"]["state"] == "valid")
        # Completed parent invalidation must not touch independently validated child evidence.
        parent_before = self.task_json("main-task")
        child_before = self.task_json("child-task")
        changed_prd = self.task_path("main-task") / "doc/prd.md"
        changed_prd.write_text(PRD_BODY.replace("R-001: deliver", "R-001: revised deliver"), encoding="utf-8")
        def completed_change_check(process):
            self.assertEqual(0, process.returncode, process.stderr)
            parent_after = self.task_json("main-task")
            child_after = self.task_json("child-task")
            self.assertEqual("in_progress", parent_after["phase"])
            self.assertIsNone(parent_after["completedAt"])
            self.assertEqual("stale", parent_after["acceptance"]["state"])
            self.assertTrue(any(e["state"] == "stale" for e in parent_after["evidence"]))
            unrelated_before = next(e for e in parent_before["evidence"] if e["id"] == "unrelated-fixture-evidence")
            unrelated_after = next(e for e in parent_after["evidence"] if e["id"] == "unrelated-fixture-evidence")
            self.assertEqual("valid", unrelated_before["state"])
            self.assertEqual(unrelated_before, unrelated_after)
            self.assertEqual(child_before["evidence"], child_after["evidence"])
            self.assertEqual("completed", child_after["phase"])
            return "parent rolled back and child evidence unchanged"
        self.step_hook("S1-completed-change", "doc-change", {"file_path": str(changed_prd), "cwd": str(self.project)},
                       expected="completed parent returns to in_progress with stale acceptance and unrelated child evidence intact",
                       check=completed_change_check, project=str(self.project))
        # Recreate fresh delivery and independent check for the updated parent before archive.
        self.record_delivery_for("main-task", "S1-recheck-delivery")
        self.check_and_accept_existing("main-task", "S1-recheck")
        self.step("S1-10b", ["archive", "main-task", "--confirm-user",
                             "--invocation", "e2e-S1-10b"],
                  expected="whole tree moved to archive/<YYYY-MM>/; archivedAt set; candidates+reminders output",
                  check=self.expect_ok(lambda p: self.require(not ("archive" not in p["path"]), "path=%s" % p["path"])))
        month = _utc_now()[:7]
        archived = self.project / ".fstar" / "archive" / month / "main-task"
        self.assertTrue((archived / "task.json").is_file())
        self.assertTrue((archived / "subtasks" / "child-task" / "task.json").is_file())
        self.assertFalse((self.project / ".fstar" / "tasks" / "main-task").exists())

        self.step("S1-archived-state", ["state", "show", "main-task"],
                  expected="active-only state lookup rejects archived task", check=self.expect_error("task_not_found"))
        self.step("S1-archived-status", ["acceptance", "status", "main-task"],
                  expected="active-only acceptance lookup rejects archived task", check=self.expect_error("task_not_found"))
        archived_record = json.loads((archived / "task.json").read_text(encoding="utf-8"))
        self.assertEqual("completed", archived_record["phase"])
        self.assertTrue(archived_record["archivedAt"])
        record_step(self.scenario, "S1-archived-record", "read archived task.json", 0,
                    "archivedAt and completed phase persist", json.dumps({"phase": archived_record["phase"], "archivedAt": archived_record["archivedAt"]}), "pass", setup="fixture-read")

        # S1-11 archive reminders: 30-day-old unarchived task, defer + dedupe
        stale = self.make_old_task("old-task")
        self.step("S1-11a", ["task", "create", "Second deliverable", "--name", "second-task",
                             "--description", "Deliver R-001"],
                  expected="second task created for archive",
                  check=self.expect_ok())
        self.complete_task_minimal("second-task")
        archive2 = self.step("S1-11b", ["archive", "second-task", "--confirm-user",
                                        "--invocation", "e2e-S1-11"],
                             expected="archive output lists old-task candidate with time basis and missing steps",
                             check=self.expect_ok(lambda p: (
                                 self.require(not (not any(c["name"] == "old-task" for c in p["archive_candidates"])), "candidates=%s" % [c["name"] for c in p["archive_candidates"]]))))
        payload2 = json.loads(archive2.stdout)
        candidate = next(c for c in payload2["archive_candidates"] if c["name"] == "old-task")
        self.assertTrue(candidate["last_activity"])
        old_task = self.task_json("old-task")
        self.assertTrue(old_task["meta"]["reminders"])
        reminder = old_task["meta"]["reminders"][candidate["reminder_key"]]
        shown = datetime.datetime.fromisoformat(reminder["shown_at"].replace("Z", "+00:00"))
        deferred = datetime.datetime.fromisoformat(reminder["deferred_until"].replace("Z", "+00:00"))
        self.assertGreaterEqual(deferred - shown, datetime.timedelta(days=7))
        self.assertLess(deferred - shown, datetime.timedelta(days=7, seconds=1))
        record_step(self.scenario, "S1-reminder-deferral", "read reminder ledger from fixture task.json", 0,
                    "default seven-day deferral", json.dumps(reminder), "pass", setup="fixture-read")
        # Dedupe: archiving again (retry) must not re-remind the same key.
        month2 = _utc_now()[:7]
        # old-task is still active; archive a third task to re-trigger patrol.
        self.step("S1-11c", ["task", "create", "Third deliverable", "--name", "third-task",
                             "--description", "Deliver R-001"],
                  expected="third task created",
                  check=self.expect_ok())
        self.complete_task_minimal("third-task")
        archive3 = self.step("S1-11d", ["archive", "third-task", "--confirm-user",
                                        "--invocation", "e2e-S1-11d"],
                             expected="reminder deduped: old-task listed as candidate but reminder_updates empty for it",
                             check=self.expect_ok(lambda p: "updates=%s" % [u["id"] for u in p["reminder_updates"]]))
        payload3 = json.loads(archive3.stdout)
        self.assertFalse(any(u["id"] == old_task["id"] for u in payload3["reminder_updates"]))
        self.assertEqual(reminder, self.task_json("old-task")["meta"]["reminders"][candidate["reminder_key"]])
        # No auto-archive of siblings.
        self.assertTrue((self.project / ".fstar" / "tasks" / "old-task" / "task.json").is_file())

        # S1-12 doc-change invalidation: edit prd -> runtime doc-change hook
        prd_path = self.project / ".fstar" / "tasks" / "old-task" / "doc" / "prd.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)
        prd_path.write_text(PRD_BODY, encoding="utf-8")
        self.persist_map("S1-12a", "old-task")
        self.step("S1-12b", ["start", "old-task", "--confirm-user", "--invocation", "e2e-S1-12"],
                  expected="old-task started",
                  check=self.expect_ok())
        old_token = self.record_delivery_for("old-task", "S1-12c")
        self.release_lease_internal("S1-12-release", "old-task", old_token)
        prd_path.write_text(PRD_BODY.replace("R-001: deliver", "R-001: DELIVER"), encoding="utf-8")
        self.step_hook("S1-12d", "doc-change",
                       {"file_path": str(prd_path), "cwd": str(self.project)},
                       expected="hook invalidates evidence, emits one propagation line",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertIn("doc changed", process.stdout),
                           "hint=%s" % process.stdout.strip()[:120])[2],
                       project=str(self.project))
        task = self.task_json("old-task")
        self.assertTrue(any(e["state"] == "stale" for e in task["evidence"]))
        self.assertTrue(any(e["type"] == "evidence_invalidated" for e in task["events"]))

        # S1-13 replan: all evidence stale, acceptance invalidated, lease released
        self.step("S1-13", ["continue", "old-task", "--action", "replan",
                            "--confirm-user", "--invocation", "e2e-S1-13",
                            "--reason", "requirements fundamentally changed"],
                  expected="back to planning; all evidence stale; lease released",
                  check=self.expect_ok(lambda p: self.require(not (p["phase"] != "planning"), "phase=planning")))
        task = self.task_json("old-task")
        self.assertTrue(all(e["state"] == "stale" for e in task["evidence"]))
        self.assertIsNone(task["lease"])
        self.assertTrue(any(e["type"] == "replanned" for e in task["events"]))

        # S1-14 orphan lease: read-only report, no auto-redispatch
        self.step("S1-14a", ["start", "old-task", "--confirm-user", "--invocation", "e2e-S1-14"],
                  expected="old-task restarted",
                  check=self.expect_ok())
        self.record_delivery_for("old-task", "S1-14-lease")
        self.expire_lease("old-task")
        self.step("S1-14b", ["continue", "old-task"],
                  expected="read-only orphaned report with choose_takeover_replan_or_drop",
                  check=self.expect_ok(lambda p: (
                      self.require(not (p.get("next") != "choose_takeover_replan_or_drop"), "next=%s" % p["next"]))))
        self.step("S1-14c", ["dispatch", "orphan", "old-task"],
                  expected="orphan report is read-only and does not redispatch",
                  check=self.expect_ok(lambda p: (
                      self.require(not (not p.get("read_only")), "status=%s read_only" % p["status"]))))

        # S1-15 post-archive views
        self.step("S1-15a", ["task", "list", "--all"],
                  expected="archived tasks only under archived view; active view has no residue",
                  check=self.expect_ok(lambda p: "views=%s/%s" % (len(p["active"]), len(p["archived"]))))
        listing = json.loads(self.last_stdout)
        active_names = [t["name"] for t in listing["active"]]
        self.assertNotIn("main-task", active_names)
        self.assertIn("old-task", active_names)
        self.step("S1-15b", ["task", "list", "--archived"],
                  expected="archived listing contains main-task",
                  check=self.expect_ok(lambda p: "archived=%s" % [t["name"] for t in p]))
        self.assertIn("main-task", [t["name"] for t in json.loads(self.last_stdout)])

    # -- S1 helpers ---------------------------------------------------------

    # Fixture check modules exercising the five-state contract for real:
    # each body produces exactly one of passed/failed/blocked/skipped/not_run
    # under the REAL interpreter, so the sibling status rows are actual
    # executed outcomes with genuine exit codes and retained logs.
    STATE_FIXTURES = {
        "passed": "import unittest\n\n\nclass PassedTest(unittest.TestCase):\n"
                  "    def test_value(self):\n        self.assertEqual(4, 4)\n",
        "blocked": "import unittest\n\n\nraise RuntimeError(\"environment blocked: fixture dependency unavailable\")\n\n\n"
                   "class BlockedTest(unittest.TestCase):\n"
                   "    def test_value(self):\n        self.assertEqual(4, 4)\n",
        "skipped": "import unittest\n\n\n@unittest.skip(\"fixture: requirement deferred by user\")\n"
                  "class SkippedTest(unittest.TestCase):\n"
                  "    def test_value(self):\n        self.assertEqual(4, 4)\n",
        "not_run": "import unittest\n\n\n# Fixture check module: the harness never executes this run.\n\n\n"
                   "class NotRunTest(unittest.TestCase):\n"
                   "    def test_value(self):\n        self.assertEqual(4, 4)\n",
    }

    def execute_remaining_check_states(self, command, template_item):
        """Execute the four sibling check rows through the real interpreter.

        For `passed`, `blocked`, and `skipped` this runs an actual
        `python -B -m unittest <module>` subprocess per row and records the
        real exit code, measured duration, retained process log, and the
        actual stdout/stderr markers in the ledger. `not_run` is the one
        honest exception: an unexecuted run has no process to run — running
        it would make it "executed". Its row carries the command line the
        checker would have used, no exit code, and no log, exactly as the
        five-state contract requires ("not_run" never fabricates evidence).
        """
        rows = []
        for state in ("passed", "blocked", "skipped", "not_run"):
            module = "test_check_%s" % state
            (self.project / ("%s.py" % module)).write_text(self.STATE_FIXTURES[state], encoding="utf-8")
            state_command = [sys.executable, "-B", "-m", "unittest", module]
            step_id = "S1-executed-%s" % state
            if state == "not_run":
                record_step(self.scenario, step_id, shlex.join(state_command), None,
                            "row deliberately not executed; no exit code, no log",
                            "not executed by design (running it would make it 'executed')",
                            "pass", setup="fixture subprocess (skipped)")
                rows.append({**template_item, "test_refs": [],
                             "command": shlex.join(state_command), "result": "not_run",
                             "exit_code": None, "log_refs": [], "duration": None, "retries": 0})
                continue
            started_at = time.monotonic()
            process = subprocess.run(state_command, cwd=self.project, capture_output=True, text=True)
            duration = time.monotonic() - started_at
            logs = retain_process_log(step_id, state_command, process, duration)
            markers = {
                "passed": ("OK", 0, "Ran 1 test"),
                "blocked": ("RuntimeError: environment blocked", 1, ""),
                "skipped": ("OK (skipped=1)", 0, "Ran 1 test"),
            }[state]
            verdict = "pass"
            try:
                self.assertEqual(markers[1], process.returncode,
                                 "%s row must exit %d, got %d\n%s%s"
                                 % (state, markers[1], process.returncode, process.stdout, process.stderr))
                self.assertIn(markers[0], process.stderr + process.stdout,
                              "%s row output must contain %r" % (state, markers[0]))
                self.assertIn(markers[2], process.stderr,
                              "%s row must report one executed test" % state)
                if state == "skipped":
                    self.assertIn("skipped=1", process.stderr)
                if state == "blocked":
                    self.assertIn("Traceback", process.stderr)
            except Exception:
                verdict = "fail"
                raise
            finally:
                record_step(self.scenario, step_id, shlex.join(state_command), process.returncode,
                            "real `%s` check row exits %d with %r in output" % (state, markers[1], markers[0]),
                            "log_refs=%s\n%s%s" % (logs, process.stdout, process.stderr),
                            verdict, setup="fixture subprocess")
            rows.append({**template_item, "test_refs": ["%s.%s" % (module, ("PassedTest" if state == "passed"
                                                                           else "BlockedTest" if state == "blocked"
                                                                           else "SkippedTest"))],
                         "command": shlex.join(state_command), "result": state,
                         "exit_code": process.returncode, "log_refs": logs,
                         "duration": duration, "retries": 0})
            if EVIDENCE_DIR:
                self.assertEqual(1, len(logs))
                with Path(logs[0]).open(encoding="utf-8") as stream:
                    retained = json.load(stream)
                self.assertEqual(process.returncode, retained["exit_code"])
                self.assertEqual(process.stdout, retained["stdout"])
                self.assertEqual(process.stderr, retained["stderr"])
        return rows

    def release_lease_internal(self, step_id, ref, token):
        task = self.task_json(ref)
        dispatch_id = next(event["data"]["dispatch_id"] for event in reversed(task["events"])
                           if "dispatch_id" in event.get("data", {}))
        self.step(step_id, ["interrupt", ref, "--dispatch-id", dispatch_id,
                           "--reason", "fixture handoff complete", "--release-lease-token", token],
                  expected="lease explicitly released via CLI", check=self.expect_ok())

    def complete_child(self, ref):
        """Run the child through implement -> check -> accept (S1-10 preconditions)."""
        self.write_docs(ref)
        self.persist_map("S1-10-child-map", ref)
        self.step("S1-10-child-start", ["start", ref, "--confirm-user",
                                        "--invocation", "e2e-child-start"],
                  expected="child started", check=self.expect_ok())
        self.step("S1-7-leaf-no-check", ["accept", ref, "--confirm-user", "--invocation", "leaf-no-check"],
                  expected="in_progress leaf without fresh check cannot be accepted",
                  check=self.expect_error("acceptance_blocked", 3))
        (self.project / "child.py").write_text("child = 1\n", encoding="utf-8")
        artifact = str((self.task_path(ref) / "doc/prd.md").relative_to(self.project))
        snap = self.snapshot_item(ref, artifact, ["R-001"])
        delivery = self.delivery_snapshot(["child.py"])
        payload = self.build_dispatch_payload("implement", ref, ["P-1"], ["child.py"],
                                              {"artifact_items": [snap], "delivery": delivery})
        token, registered = self.register_dispatch("S1-10-child-impl", payload)
        (self.project / "child.py").write_text("child = 2\n", encoding="utf-8")
        result_body = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["child.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-10-child-harvest", ["dispatch", "harvest",
                                          "--result", str(self.write_json("cr.json", result_body)),
                                          "--payload", str(self.write_json("cp.json", registered)),
                                          "--lease-token", token],
                  expected="child delivery recorded", check=self.expect_ok())
        check_snap = self.snapshot_item(ref, artifact, ["R-001"])
        check_delivery = self.delivery_snapshot(["child.py"])
        check_payload = self.build_dispatch_payload("check", ref, ["P-1"], [],
                                                    {"artifact_items": [check_snap], "delivery": check_delivery})
        check_token, check_registered = self.register_dispatch("S1-10-child-check", check_payload)
        check_evidence = {
            "kind": "check", "producer": {"role": "check", "id": "checker-child", "session_id": "cc"},
            "validates": [check_snap], "run_id": "run-child",
            "environment": {"python": sys.version.split()[0]},
            "delivery": check_delivery, "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [],
                       "review_method": "synthetic fixture outcome for acceptance-gate exercise", "result": "passed", "exit_code": 0,
                       "log_refs": [], "duration": 0, "retries": 0}],
        }
        check_result = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": check_payload["dispatch_id"],
            "role": "check", "status": "done", "changed_paths": [],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-10-child-check-harvest", ["dispatch", "harvest",
                                                "--result", str(self.write_json("cr2.json", check_result)),
                                                "--payload", str(self.write_json("cp2.json", check_registered)),
                                                "--lease-token", check_token,
                                                "--check-evidence", str(self.write_json("ce2.json", check_evidence))],
                  expected="child final check recorded", check=self.expect_ok())
        self.release_lease_internal("S1-10-child-release", ref, check_token)
        self.step("S1-10-child-accept", ["accept", ref, "--confirm-user",
                                         "--invocation", "e2e-child-accept"],
                  expected="child completed", check=self.expect_ok())

    def complete_task_minimal(self, ref):
        """Complete a top-level task quickly (docs, map, start, impl, check, accept)."""
        self.write_docs(ref)
        self.persist_map("S1-min-map-%s" % ref, ref)
        self.step("S1-min-start-%s" % ref, ["start", ref, "--confirm-user",
                                            "--invocation", "e2e-min-%s" % ref],
                  expected="task started", check=self.expect_ok())
        self.record_delivery_for(ref, "S1-min-impl-%s" % ref)
        self.check_and_accept_existing(ref, "S1-min")

    def check_and_accept_existing(self, ref, label):
        artifact = str((self.task_path(ref) / "doc/prd.md").relative_to(self.project))
        snap = self.snapshot_item(ref, artifact, ["R-001"])
        delivery = self.delivery_snapshot(["src.py"])
        check_payload = self.build_dispatch_payload("check", ref, ["P-1"], [],
                                                    {"artifact_items": [snap], "delivery": delivery})
        check_token, check_registered = self.register_dispatch("S1-min-check-%s" % ref, check_payload)
        check_evidence = {
            "kind": "check", "producer": {"role": "check", "id": "checker-%s" % ref, "session_id": "cs"},
            "validates": [snap], "run_id": "run-%s" % ref,
            "environment": {"python": sys.version.split()[0]},
            "delivery": delivery, "scope": "final",
            "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [],
                       "review_method": "synthetic fixture outcome for acceptance-gate exercise", "result": "passed", "exit_code": 0,
                       "log_refs": [], "duration": 0, "retries": 0}],
        }
        check_result = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": check_payload["dispatch_id"],
            "role": "check", "status": "done", "changed_paths": [],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S1-min-check-harvest-%s" % ref,
                  ["dispatch", "harvest",
                   "--result", str(self.write_json("mr.json", check_result)),
                   "--payload", str(self.write_json("mp.json", check_registered)),
                   "--lease-token", check_token,
                   "--check-evidence", str(self.write_json("me.json", check_evidence))],
                  expected="final check recorded", check=self.expect_ok())
        self.release_lease_internal("S1-min-release-%s" % ref, ref, check_token)
        self.step("S1-min-accept-%s" % ref, ["accept", ref, "--confirm-user",
                                             "--invocation", "e2e-min-accept-%s" % ref],
                  expected="task completed", check=self.expect_ok())

    def record_delivery_for(self, ref, step_id):
        """Implement dispatch + harvest for a task (delivery evidence)."""
        (self.project / "src.py").write_text("value = 1\n", encoding="utf-8")
        artifact = str((self.task_path(ref) / "doc/prd.md").relative_to(self.project))
        snap = self.snapshot_item(ref, artifact, ["R-001"])
        delivery = self.delivery_snapshot(["src.py"])
        payload = self.build_dispatch_payload("implement", ref, ["P-1"], ["src.py"],
                                              {"artifact_items": [snap], "delivery": delivery})
        token, registered = self.register_dispatch(step_id + "-impl", payload)
        (self.project / "src.py").write_text("value = 2\n", encoding="utf-8")
        result_body = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["src.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step(step_id + "-harvest", ["dispatch", "harvest",
                                         "--result", str(self.write_json("dr.json", result_body)),
                                         "--payload", str(self.write_json("dp.json", registered)),
                                         "--lease-token", token],
                  expected="delivery recorded", check=self.expect_ok())
        return token

    def make_old_task(self, name):
        """Create a task whose last activity is 40 days old (setup: direct file edit)."""
        self.step("S1-11-setup-create", ["task", "create", "Old deliverable", "--name", name,
                                         "--description", "Deliver R-001"],
                  expected="old task created", check=self.expect_ok())
        task = self.task_json(name)
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(days=40)).isoformat().replace("+00:00", "Z")
        task["createdAt"] = old
        for event in task["events"]:
            event["at"] = old
        self.write_task_json(name, task)
        record_step(self.scenario, "S1-11-setup-age", "direct file edit: task.json timestamps -> 40 days ago",
                    0, "simulated external edit makes the task 40 days old", "edited", "pass",
                    setup="direct-file-edit")
        return name

    def expire_lease(self, ref):
        """Set lease.expires_at into the past (setup: direct file edit)."""
        task = self.task_json(ref)
        past = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        task["lease"]["expires_at"] = past
        self.write_task_json(ref, task)
        record_step(self.scenario, "S1-14-setup-expire", "direct file edit: lease.expires_at -> past",
                    0, "simulated orphan lease", "edited", "pass", setup="direct-file-edit")


# ===========================================================================
# S2 — nonpersistent minimal loop + extension negotiation (8 steps)
# ===========================================================================

class S2MinimalLoop(ScenarioCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S2"
        self.empty = self.root / "empty"
        self.empty.mkdir()

    def test_s2_minimal_loop(self):
        # S2-1 session-context in an uninitialized dir: routing injected, zero writes
        before = self.tree_snapshot(self.empty, self.project, self.user_root, self.runtime_root, self.host_root)
        all_before = before
        self.step_hook("S2-1", "session-context",
                       {"session_id": "s1", "cwd": str(self.empty)},
                       expected="routing full text + 'No initialized fstar project found'; rc 0; zero .fstar writes",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertIn("fstar routing", process.stdout),
                           self.assertIn("No initialized fstar project found", process.stdout),
                           "routing injected, %d bytes" % len(process.stdout))[3],
                       cwd=self.empty)
        after = self.tree_snapshot(self.empty, self.project, self.user_root, self.runtime_root, self.host_root)
        self.assertEqual(before, after, "session-context must not write anything")

        # S2-2 worker-context: fstar role injected; non-fstar role silent
        self.step_hook("S2-2a", "worker-context",
                       {"session_id": "s1", "cwd": str(self.empty),
                        "tool_input": {"subagent_type": "fstar-implement"}},
                       expected="role card injected + 'Active task: session-only'",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertIn("Active task: session-only", process.stdout),
                           self.assertIn("fstar-implement", process.stdout),
                           "role card + session-only line")[3],
                       cwd=self.empty)
        self.step_hook("S2-2b", "worker-context",
                       {"session_id": "s1", "cwd": str(self.empty),
                        "tool_input": {"subagent_type": "trellis-implement"}},
                       expected="non-fstar role: no output, rc 0",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertEqual("", process.stdout),
                           "silent")[2],
                       cwd=self.empty)

        # S2-2c research without a session grant is rejected; an explicit grant authorizes it.
        research_payload = {
            "schema": "fstar.dispatch.v1", "dispatch_id": __import__("uuid").uuid4().hex,
            "task_ref": "session-only", "role": "research", "plan_item_ids": [],
            "baseline": {"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
            "input_versions": [], "allowed_paths": ["research/notes.md"], "read_context": [],
            "required_validations": [],
            "return_conditions": {"done": "", "blocked": "", "failed": ""},
            "prompt_first_line": "Active task: session-only",
            "extensions": [],
        }
        self.step_user("S2-2c-denied", ["dispatch", "research",
                                        "--payload", str(self.write_json("research-denied.json", research_payload))],
                       expected="optional session dispatch without included research is rejected",
                       check=self.expect_error("extension_not_authorized", 3), cwd=self.empty)
        research_grant = self.session_grant("S2-2c-enable", "multi-agent", ["research"], ["parallel-implement"])
        research_payload["extensions"] = [research_grant]
        self.step_user("S2-2c-allowed", ["dispatch", "research",
                                         "--payload", str(self.write_json("research-allowed.json", research_payload)),
                                         "--extension", "@%s" % self.write_json("research-grant.json", research_grant)],
                       expected="explicit extension context authorizes optional session dispatch",
                       check=self.expect_ok(lambda p: self.require(p.get("persistence") == "session_only", "persistence=%s" % p["persistence"])), cwd=self.empty)

        # S2-3 session-only dispatch + harvest: zero persistence
        before = self.tree_snapshot(self.empty, self.user_root, self.runtime_root)
        payload = {
            "schema": "fstar.dispatch.v1", "dispatch_id": str(uuid.uuid4()),
            "task_ref": "session-only", "role": "implement", "plan_item_ids": ["P-1"],
            "baseline": {"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
            "input_versions": [], "allowed_paths": ["src.py"], "read_context": [],
            "required_validations": [],
            "return_conditions": {"done": "", "blocked": "", "failed": ""},
            "prompt_first_line": "Active task: session-only",
        }
        with self.subTest(contract="no-project session-only dispatch"):
            self.step_user("S2-3a", ["dispatch", "implement",
                                     "--payload", str(self.write_json("sp.json", payload))],
                           expected="registered:false persistence:session_only",
                           check=self.expect_ok(lambda p: (
                               self.require(not (p.get("registered")), "persistence=%s" % p["persistence"]))),
                           cwd=self.empty)
        self.step("S2-3a-explicit-root", ["dispatch", "implement",
                                 "--payload", str(self.write_json("sp.json", payload))],
                       expected="registered:false persistence:session_only",
                       check=self.expect_ok(lambda p: (
                           self.require(not (p.get("registered")), "persistence=%s" % p["persistence"]))),
                       cwd=self.empty)
        result_body = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["src.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step_user("S2-3b", ["dispatch", "harvest",
                                 "--result", str(self.write_json("sr.json", result_body)),
                                 "--payload", str(self.write_json("sp2.json", payload)),
                                 "--lease-token", "none"],
                       expected="recorded:false persistence:session_only; next=check_dispatch",
                       check=self.expect_ok(lambda p: (
                           self.require(not p.get("recorded") and p.get("next") == "check_dispatch",
                                        "recorded=false next=%s" % p.get("next")))),
                       cwd=self.empty)
        bad_result = dict(result_body, dispatch_id="different")
        self.step_user("S2-3c", ["dispatch", "harvest",
                                  "--result", str(self.write_json("bad-result.json", bad_result)),
                                  "--payload", str(self.write_json("session-payload.json", payload)),
                                  "--lease-token", "none"],
                       expected="session-only identity mismatch is rejected",
                       check=self.expect_error("identity_mismatch", 4), cwd=self.empty)
        persistent_payload = dict(payload, task_ref="missing-task", prompt_first_line="Active task: missing-task")
        self.step_user("S2-3d", ["dispatch", "implement", "--payload",
                                  str(self.write_json("persistent-payload.json", persistent_payload))],
                       expected="persistent dispatch without a project is rejected",
                       check=self.expect_error("project_not_initialized", 2), cwd=self.empty)
        self.step_user("S2-interrupt", ["interrupt", "--dispatch-id", payload["dispatch_id"],
                                        "--reason", "fixture change"],
                       expected="session-only interrupt works without an initialized project",
                       check=self.expect_ok(lambda p: self.require(p["intent_registered"], "intent registered")),
                       cwd=self.empty)
        editor_grant = self.session_grant("S2-editor-enable", "planning-review", ["editor"], ["design"])
        editor_grant_file = self.write_json("editor-grant.json", editor_grant)
        self.step_user("S2-doc-edit", ["doc-edit", "--file", "doc/prd.md", "--item", "R-001",
                                       "--baseline", "fixture-baseline", "--extension", "@%s" % editor_grant_file],
                       expected="session-only editor payload works without an initialized project",
                       check=self.expect_ok(lambda p: self.require(p["payload"]["task_ref"] == "session-only", "session-only payload")
                                             and self.require(p["payload"]["extensions"][0]["id"] == "planning-review", "editor grant attached")),
                       cwd=self.empty)
        self.step_user("S2-doc-edit-denied", ["doc-edit", "--file", "doc/prd.md", "--item", "R-001",
                                              "--baseline", "fixture-baseline"],
                       expected="session-only editor without the extension context is rejected",
                       check=self.expect_error("extension_not_authorized", 3), cwd=self.empty)
        self.assertEqual(before, self.tree_snapshot(self.empty, self.user_root, self.runtime_root),
                         "session-only dispatch/harvest must not write fstar metadata")

        self.step_hook("S2-worker-result", "worker-result", {"cwd": str(self.empty)},
                       expected="host worker-result lacks dispatch payload: silent no-op",
                       check=lambda p: (self.assertEqual(0, p.returncode), self.assertEqual("", p.stdout)),
                       cwd=self.empty)

        # S2-4 doc-change on an unrelated file: silent skip
        self.step_hook("S2-4", "doc-change",
                       {"file_path": "notes/todo.md", "cwd": str(self.empty)},
                       expected="silent skip, rc 0, no output noise",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertEqual("", process.stdout),
                           "silent")[2],
                       cwd=self.empty)

        # S2-5 session-level extension enable/disable in an uninitialized dir
        self.step_user("S2-5a", ["extension", "list"],
                       expected="session_only persistence listing of five packages",
                       check=self.expect_ok(lambda p: "persistence=%s n=%d" % (p["persistence"], len(p["extensions"]))),
                       cwd=self.empty)
        self.step_user("S2-5b", ["extension", "enable", "tool-capability",
                                 "--confirm-user", "--invocation", "e2e-S2-5b"],
                       expected="session-only authorization validated, zero writes",
                       check=self.expect_ok(lambda p: "persistence=%s" % p["persistence"]),
                       cwd=self.empty)
        self.step_user("S2-5c", ["extension", "disable", "tool-capability",
                                 "--confirm-user", "--invocation", "e2e-S2-5c"],
                       expected="session-only disable",
                       check=self.expect_ok(lambda p: "disabled=%s" % p["disabled"]),
                       cwd=self.empty)
        self.assertEqual(before, self.tree_snapshot(self.empty, self.user_root, self.runtime_root))
        self.assertFalse((self.empty / ".fstar").exists())

        # S2-6 routing negotiation rules are really injected (static source of truth)
        routing = self.hook("session-context", {"cwd": str(self.empty)}, cwd=self.empty).stdout
        for fragment in ("planning-review", "persistent-task", "multi-agent",
                         "project-governance", "tool-capability",
                         "recommend only one highest-value package",
                         "do not ask again unless new facts",
                         # Settled lifecycle-member boundary (2026-10-31):
                         # the safety-machinery clause is part of the injected
                         # routing body, not only a source-file statement.
                         "Safety machinery always on"):
            self.assertIn(fragment, routing)
            self.assertIn(fragment, routing)
        record_step(self.scenario, "S2-6", self._command,
                    0, "five package IDs + one-package + no-re-ask rules present",
                    "all fragments present", "pass")

        self.assertEqual(all_before, self.tree_snapshot(self.empty, self.project, self.user_root, self.runtime_root, self.host_root))
        record_step(self.scenario, "S2-zero-writes-complete", "compare complete nonpersistent fixture roots before/after hooks and CLI", 0,
                    "all directory names, file bytes and file mtimes unchanged", "all five fixture roots unchanged", "pass", setup="fixture-snapshot")

        # S2-7 mid-loop extension load does not stale existing evidence
        self.init_for_s2_7()
        token = self.record_delivery_s27()
        task_before = self.task_json("s27-task")
        S1PersistentLifecycle.release_lease_internal(self, "S2-7-release", "s27-task", token)
        self.enable_extension("S2-7b", "s27-task", "multi-agent")
        task_after = self.task_json("s27-task")
        valid_before = [e["id"] for e in task_before["evidence"] if e["state"] == "valid"]
        valid_after = [e["id"] for e in task_after["evidence"] if e["state"] == "valid"]
        self.assertEqual(valid_before, valid_after, "enabling an extension must not stale evidence")
        self.assertEqual(task_before["phase"], task_after["phase"])
        record_step(self.scenario, "S2-7c", "compare task.json before/after extension enable",
                    0, "evidence still valid, phase unchanged",
                    "valid=%s phase=%s" % (valid_after, task_after["phase"]), "pass")

        # Machine-side gates only: the session-only response does not maintain
        # a state machine, so failed-check/acceptance checks use the S2-7 fixture.
        snap = self.snapshot_item("s27-task", ".fstar/tasks/s27-task/doc/prd.md", ["R-001"])
        delivery = self.delivery_snapshot(["src.py"])
        payload = self.build_dispatch_payload("check", "s27-task", ["P-1"], [],
                                              {"artifact_items": [snap], "delivery": delivery})
        token, registered = self.register_dispatch("S2-8-check", payload)
        result = {"schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
                  "role": "check", "status": "done", "changed_paths": [], "artifact_refs": [],
                  "validation_facts": [], "blockers": [], "input_baseline": {}, "delivery_baseline": {}}
        evidence = {"kind": "check", "producer": {"role": "check", "id": "fixture-checker"},
                    "validates": [snap], "run_id": "s2-synthetic-failure", "environment": {"fixture": True},
                    "delivery": delivery, "scope": "final",
                    "items": [{"requirement_ids": ["R-001"], "plan_item": "P-1", "test_refs": [],
                               "review_method": "synthetic failure for gate assertion", "result": "failed",
                               "log_refs": []}]}
        self.step("S2-8-failed-check", ["dispatch", "harvest", "--result", str(self.write_json("s28-result.json", result)),
                  "--payload", str(self.write_json("s28-payload.json", registered)), "--lease-token", token,
                  "--check-evidence", str(self.write_json("s28-check.json", evidence))],
                  expected="synthetic failed check recorded", check=self.expect_ok())
        S1PersistentLifecycle.release_lease_internal(self, "S2-8-release", "s27-task", token)
        self.step("S2-8-failure-gate", ["acceptance", "status", "s27-task"],
                  expected="failed check blocks awaiting acceptance",
                  check=self.expect_ok(lambda p: self.require(not p["awaiting_acceptance"] and
                                                              "unresolved_check" in p["blockers"],
                                                              "failed check blocks acceptance")))
        confirmation = {"source_id": "s2-agent", "type": "command", "at": _utc_now(),
                        "actor": {"role": "agent", "id": "fixture"}, "reference": "cli", "quote": "",
                        "scope": "accept", "validates": ""}
        self.step("S2-8-agent-gate", ["accept", "s27-task", "--confirmation", str(self.write_json("s28-confirmation.json", confirmation))],
                  expected="agent source rejected", check=self.expect_error("acceptance_forbidden", 3))
        record_step(self.scenario, "S2-8", "S2-3b and S2-8 fixture gate assertions", 0,
                    "harvest routes to check; failed check blocks acceptance; agent confirmation rejected",
                    "asserted; failed check and actor are simulated; native separation and repair not observed", "pass", setup="fixture")

    def init_for_s2_7(self):
        self.step("S2-7-setup-init", ["init", str(self.project)],
                  expected="project initialized for the S2-7 sub-scenario",
                  check=self.expect_ok())
        self.step("S2-7-setup-create", ["task", "create", "S27 deliverable", "--name", "s27-task",
                                        "--description", "Deliver R-001"],
                  expected="task created", check=self.expect_ok())
        self.write_docs("s27-task")
        self.persist_map("S2-7-setup-map", "s27-task")
        self.step("S2-7-setup-start", ["start", "s27-task", "--confirm-user",
                                       "--invocation", "e2e-S2-7"],
                  expected="task started", check=self.expect_ok())

    def record_delivery_s27(self):
        (self.project / "src.py").write_text("value = 1\n", encoding="utf-8")
        artifact = ".fstar/tasks/s27-task/doc/prd.md"
        snap = self.snapshot_item("s27-task", artifact, ["R-001"])
        delivery = self.delivery_snapshot(["src.py"])
        payload = self.build_dispatch_payload("implement", "s27-task", ["P-1"], ["src.py"],
                                              {"artifact_items": [snap], "delivery": delivery})
        token, registered = self.register_dispatch("S2-7a-impl", payload)
        (self.project / "src.py").write_text("value = 2\n", encoding="utf-8")
        result_body = {
            "schema": "fstar.dispatch.result.v1", "dispatch_id": payload["dispatch_id"],
            "role": "implement", "status": "done", "changed_paths": ["src.py"],
            "artifact_refs": [], "validation_facts": [], "blockers": [],
            "input_baseline": {}, "delivery_baseline": {},
        }
        self.step("S2-7a-harvest", ["dispatch", "harvest",
                                    "--result", str(self.write_json("s27r.json", result_body)),
                                    "--payload", str(self.write_json("s27p.json", registered)),
                                    "--lease-token", token],
                  expected="delivery recorded before extension load",
                  check=self.expect_ok())
        return token

    # reuse the persistent-case helpers
    init_project = PersistentLifecycleCase.init_project
    write_docs = PersistentLifecycleCase.write_docs
    persist_map = PersistentLifecycleCase.persist_map
    snapshot_item = PersistentLifecycleCase.snapshot_item
    delivery_snapshot = PersistentLifecycleCase.delivery_snapshot
    build_dispatch_payload = PersistentLifecycleCase.build_dispatch_payload
    register_dispatch = PersistentLifecycleCase.register_dispatch
    enable_extension = PersistentLifecycleCase.enable_extension


# ===========================================================================
# S3 — extensions[] / capabilities[] separation (4 steps)
# ===========================================================================

class S3ExtensionRecords(PersistentLifecycleCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S3"
        self.init_project()
        self.create_main_task("ext-task")
        self.enable_extension("S3-0", "ext-task", "tool-capability")

    def test_s3_extension_capability_separation(self):
        # S3-1 custom scope: included/excluded effective; overlap/unknown rejected; full completes
        self.step("S3-1a", ["extension", "enable", "multi-agent", "ext-task",
                            "--scope", "custom", "--include", "research",
                            "--exclude", "parallel-implement",
                            "--confirm-user", "--invocation", "e2e-S3-1a"],
                  expected="custom scope recorded with included/excluded",
                  check=self.expect_ok(lambda p: "included=%s excluded=%s" % (p["included"], p["excluded"])))
        self.step("S3-1b", ["extension", "enable", "multi-agent", "ext-task",
                            "--scope", "custom", "--include", "research",
                            "--exclude", "research",
                            "--confirm-user", "--invocation", "e2e-S3-1b"],
                  expected="overlapping include/exclude rejected (invalid_extension_scope)",
                  check=self.expect_error("invalid_extension_scope"))
        self.step("S3-1c", ["extension", "enable", "multi-agent", "ext-task",
                            "--scope", "custom", "--include", "not-a-capability",
                            "--confirm-user", "--invocation", "e2e-S3-1c"],
                  expected="unknown member rejected (invalid_extension_members)",
                  check=self.expect_error("invalid_extension_members"))
        self.step("S3-1d", ["extension", "enable", "multi-agent", "ext-task",
                            "--scope", "full",
                            "--confirm-user", "--invocation", "e2e-S3-1d"],
                  expected="full scope completes the whole package",
                  check=self.expect_ok(lambda p: "included=%d excluded=%d" % (len(p["included"]), len(p["excluded"]))))

        # S3-2 disable, then a NEW process reads back current state + events history
        self.step("S3-2a", ["extension", "disable", "multi-agent", "ext-task",
                            "--confirm-user", "--invocation", "e2e-S3-2a"],
                  expected="extension disabled",
                  check=self.expect_ok(lambda p: "disabled=%s" % p["disabled"]))
        self.step("S3-2b", ["extension", "list", "ext-task"],
                  expected="new process reads back extensions[] current state",
                  check=self.expect_ok(lambda p: "active=%s" % [e["id"] for e in p["active"]]))
        listing = json.loads(self.last_stdout)
        self.assertIn("tool-capability", [e["id"] for e in listing["active"]])
        self.assertNotIn("multi-agent", [e["id"] for e in listing["active"]])
        self.step("S3-2c", ["state", "show", "ext-task"],
                  expected="state show exposes extensions and events history",
                  check=self.expect_ok(lambda p: "extensions=%d" % len(p["extensions"])))
        task = self.task_json("ext-task")
        history = [e["type"] for e in task["events"]]
        self.assertIn("extension_enabled", history)
        self.assertIn("extension_changed", history)

        # S3-3 write-entry separation: cross shapes rejected on both sides
        self.start_task_for_capabilities()
        extension_shape = {
            "id": "multi-agent", "enabled_at": _utc_now(),
            "source": {"type": "command"}, "scope": "full",
            "included": [], "excluded": [], "reason": "",
        }
        process = self.provenance_api("S3-3a", extension_shape)
        command = "internal-api: tools.record_provenance(extension-shaped record)"
        self.assertNotEqual(0, process.returncode,
                            "record_provenance must reject an extension-shaped record")
        record_step(self.scenario, "S3-3a", command, process.returncode,
                    "extension record into capabilities[] rejected",
                    _actual_of(process), "pass", setup="internal-api")
        capability_shape = self.capability_record()
        process = self.enable_extension_api("S3-3b", capability_shape)
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual("unknown_extension", result["code"])
        record_step(self.scenario, "S3-3b", self._command, process.returncode,
                    "actual capability record rejected by extension write entry with unknown_extension",
                    process.stdout, "pass", setup="internal-api")
        # And the legitimate provenance write lands in capabilities[] only.
        good = self.capability_record()
        process = self.provenance_api("S3-3c", good)
        self.assertEqual(0, process.returncode, process.stderr)
        record_step(self.scenario, "S3-3c", "internal-api: tools.record_provenance(valid record)",
                    process.returncode, "provenance lands in capabilities[]",
                    "recorded", "pass", setup="internal-api")
        task = self.task_json("ext-task")
        self.assertTrue(task["capabilities"])
        self.assertTrue(all("capability" in c and "id" in c["call"] for c in task["capabilities"]))
        self.assertFalse(any(set(c) == {"id", "enabled_at", "source", "scope", "included", "excluded", "reason"}
                             for c in task["capabilities"]))

        # S3-4 direct edits cannot mix extension authorization into provenance.
        task = self.task_json("ext-task")
        task["capabilities"].append(dict(extension_shape))
        self.write_task_json("ext-task", task)
        self.step("S3-4", ["state", "show", "ext-task"],
                  expected="extension-shaped capability rejected on read",
                  check=self.expect_error("invalid_capability"))

    # -- S3 helpers ---------------------------------------------------------

    def start_task_for_capabilities(self):
        self.write_docs("ext-task")
        self.persist_map("S3-start-map", "ext-task")
        self.step("S3-start", ["start", "ext-task", "--confirm-user",
                               "--invocation", "e2e-S3-start"],
                  expected="task in_progress for provenance writes",
                  check=self.expect_ok())
        # provenance requires an active writer lease: acquire one via a dispatch
        payload = self.build_dispatch_payload("implement", "ext-task", ["P-1"], ["src.py"],
                                              {"artifact_items": [], "delivery": {"paths": [], "digest": ""}})
        token, _ = self.register_dispatch("S3-lease", payload)
        self._s3_token = token

    def capability_record(self):
        return {
            "schema": "fstar.tool-use.v1", "id": str(uuid.uuid4()),
            "capability": "code-structure", "tool": "fixture-tool", "kind": "cli",
            "version": "1.0", "at": _utc_now(),
            "binding_origin": None, "binding_digest": None,
            "match": "weak", "basis": "e2e fixture",
            "call": {"id": "call-1", "reference": "e2e", "operation": "lookup", "result": "passed"},
            "availability": None, "fallback": False,
        }

    def provenance_api(self, step_id, record):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.store import TaskStore\n"
            "from fstar import tools\n"
            "from pathlib import Path\n"
            "store = TaskStore(Path(%r), user_home=Path(%r), runtime_root=Path(%r))\n"
            "tools.record_provenance(store, %r, %r, lease_token=%r, clock=lambda: %r)\n"
            % (str(SRC), str(self.project), str(self.user_root), str(self.runtime_root),
               "ext-task", record, getattr(self, "_s3_token", "x"), _utc_now()))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        return self.run_process([sys.executable, "-c", code], capture_output=True,
                              text=True, env=env, cwd=str(self.root), timeout=120)

    def enable_extension_api(self, step_id, record):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.store import TaskStore\n"
            "from fstar.tasks import TaskService\n"
            "from pathlib import Path\n"
            "store = TaskStore(Path(%r), user_home=Path(%r), runtime_root=Path(%r))\n"
            "service = TaskService(store)\n"
            "from fstar.models import DomainError\n"
            "try:\n"
            "    service.enable_extension('ext-task', authorization=%r, actor={'role': 'user', 'id': 'u'})\n"
            "except DomainError as error:\n"
            "    print(json.dumps({'code': error.code}))\n"
            "else:\n"
            "    raise AssertionError('capability accepted as extension')\n"
            % (str(SRC), str(self.project), str(self.user_root), str(self.runtime_root),
               record))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        return self.run_process([sys.executable, "-c", code], capture_output=True,
                              text=True, env=env, cwd=str(self.root), timeout=120)


# ===========================================================================
# S4 — tool binding and degradation (4 steps)
# ===========================================================================

class S4ToolBinding(ScenarioCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S4"
        self.bin = self.root / "fixture-bin"
        self.bin.mkdir()
        self.registry = self.user_root / "tools" / "registry.d"
        self.registry.mkdir(parents=True)

    def _stub(self, name, version="1.2.3"):
        path = self.bin / name
        path.write_text(
            "#!/bin/sh\n"
            "exec 2>/dev/null\n"
            'if [ "$1" = "--version" ]; then echo "%s v%s"; exit 0; fi\n'
            'if [ "$1" = "--help" ]; then echo "%s symbol lookup graph"; exit 0; fi\n'
            "exit 0\n" % (name, version, name), encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_s4_tool_binding_degradation(self):
        self._stub("codegraph")
        (self.registry / "codegraph.yaml").write_text(
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\n'
            'kind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "symbol lookup"}]\n'
            'version_cmd: ["--version"]\n', encoding="utf-8")
        # A weak-probe tool: present on PATH but not in the registry.
        self._stub("node")
        residual = self.bin / "curl"
        residual.write_text("#!/bin/sh\nprintf 'ordinary helper\\n'\n", encoding="utf-8")
        residual.chmod(0o755)
        env_extra = {"PATH": str(self.bin)}

        # S4-1 tools scan: registry strong, probe weak, unclassified manual candidates
        self.step("S4-1", ["tools", "scan"],
                  expected="scan returns fstar.tools.scan.v1 with strong/weak/manual candidates; no tools.yaml written",
                  check=self.expect_ok(lambda p: (
                      "schema=%s tools=%s" % (p["schema"], [t["tool"] for t in p["tools"]]))),
                  env_extra=env_extra)
        scan = json.loads(self.last_stdout)
        by_tool = {t["tool"]: t for t in scan["tools"]}
        self.assertEqual("strong", by_tool["codegraph"]["capabilities"][0]["match"])
        self.assertEqual("weak", by_tool["node"]["capabilities"][0]["match"])
        self.assertTrue(scan["observations"])
        self.assertTrue(scan["proposals"])
        self.assertEqual(5, len(by_tool["curl"]["capabilities"]))
        self.assertTrue(all(c["match"] == "none" and c["basis_source"]["kind"] == "unclassified"
                            for c in by_tool["curl"]["capabilities"]))
        self.assertFalse(any(p.get("tool") == "curl" for p in scan["proposals"]))
        record_step(self.scenario, "S4-manual-candidate", self._command, 0,
                    "unclassified PATH candidate has five none matches and no automatic binding proposal",
                    json.dumps(by_tool["curl"]), "pass")
        self.assertFalse((self.user_root / "tools.yaml").exists())
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())

        # S4-2 resolve (project > user > default) + confirmed apply; explicit null unbind
        self.step("S4-init", ["init", str(self.project)], expected="initialize project before project binding", check=self.expect_ok())
        self.s4_resolve_and_apply()

        # S4-3 unbound capability: gap report + FALLBACKS degradation text
        self.s4_gap_report()

        # S4-4 three availability layers + provenance
        self.s4_availability_provenance()

    def s4_resolve_and_apply(self):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "user = tools.load_tools(Path(%r))\n"
            "project = tools.load_tools(Path(%r))\n"
            "resolution = tools.resolve_bindings(project=project, user=user)\n"
            "print(json.dumps(resolution, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root / "tools.yaml"),
               str(self.project / ".fstar" / "tools.yaml")))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        resolution = json.loads(process.stdout)
        code_struct = next(c for c in resolution["capabilities"] if c["capability"] == "code-structure")
        self.assertEqual("recommended", code_struct["state"])
        record_step(self.scenario, "S4-2a", "internal-api: tools.resolve_bindings(project, user)",
                    process.returncode, "project > user > defaults; unbound items fall to recommendation",
                    "code-structure state=%s origin=%s" % (code_struct["state"], code_struct["origin"]["layer"]),
                    "pass", setup="internal-api")

        # Confirmed apply writes the binding; unconfirmed writes nothing.
        code_apply = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "user_root = Path(%r)\n"
            "loaded = tools.load_tools(user_root / 'tools.yaml')\n"
            "snapshot = {'tool': 'codegraph', 'kind': 'cli', 'version': '1.2.3',\n"
            "            'capabilities': [{'id': 'code-structure', 'match': 'strong',\n"
            "                              'basis': 'e2e scan',\n"
            "                              'basis_source': {'kind': 'registry', 'reference': 'e2e'}}]}\n"
            "proposal = tools.build_binding_proposal(\n"
            "    target='user', loaded=loaded, changes={'code-structure': 'codegraph'},\n"
            "    reason='user confirmed the scanned tool', tools={'codegraph': snapshot})\n"
            "print(json.dumps(proposal, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root)))
        process = self.run_process([sys.executable, "-c", code_apply], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        proposal = json.loads(process.stdout)
        record_step(self.scenario, "S4-2b", "internal-api: tools.build_binding_proposal(user layer)",
                    process.returncode, "exact proposal with digest; nothing written yet",
                    "digest=%s" % proposal["digest"][:12], "pass", setup="internal-api")
        self.assertFalse((self.user_root / "tools.yaml").exists())

        confirmation = {
            "source_id": "e2e-S4-2", "type": "conversation", "at": _utc_now(),
            "actor": {"role": "user", "id": "user-1"}, "reference": "e2e/session/input-1",
            "quote": "bind codegraph for structure",
            "scope": {"target": "user", "path": proposal["path"],
                      "changes": proposal["changes"], "tools": proposal["tools"]},
            "validates": proposal["digest"],
        }
        code_confirm = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "proposal = json.loads(sys.stdin.read())\n"
            "confirmation = json.loads(sys.argv[1])\n"
            "tools.apply_binding(proposal, confirmation,\n"
            "                    user_root=Path(%r), project_root=Path(%r),\n"
            "                    runtime_root=Path(%r), clock=lambda: %r)\n"
            "print('applied')\n"
            % (str(SRC), str(self.user_root), str(self.project), str(self.runtime_root), _utc_now()))
        process = self.run_process([sys.executable, "-c", code_confirm, json.dumps(confirmation)],
                                 input=json.dumps(proposal), capture_output=True, text=True,
                                 env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue((self.user_root / "tools.yaml").is_file())
        record_step(self.scenario, "S4-2c", "internal-api: tools.apply_binding(proposal, confirmation)",
                    process.returncode, "confirmed binding written to user tools.yaml",
                    "tools.yaml written", "pass", setup="internal-api")

        # Unconfirmed apply is rejected and writes nothing more.
        bad_confirmation = dict(confirmation, validates="wrong-digest")
        before = _sha256_file(self.user_root / "tools.yaml")
        process = self.run_process([sys.executable, "-c", code_confirm, json.dumps(bad_confirmation)],
                                 input=json.dumps(proposal), capture_output=True, text=True,
                                 env=env, cwd=str(self.root), timeout=120)
        self.assertNotEqual(0, process.returncode, "stale confirmation must be rejected")
        self.assertEqual(before, _sha256_file(self.user_root / "tools.yaml"))
        record_step(self.scenario, "S4-2d", "internal-api: apply_binding with stale confirmation",
                    process.returncode, "rejected (tools_stale_confirmation), file untouched",
                    _actual_of(process), "pass", setup="internal-api")

        # Explicit tool: null stops fallback (project layer overrides user).
        code_null = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "project_root = Path(%r)\n"
            "loaded = tools.load_tools(project_root / '.fstar' / 'tools.yaml')\n"
            "proposal = tools.build_binding_proposal(\n"
            "    target='project', loaded=loaded, changes={'code-structure': None},\n"
            "    reason='user explicitly unbound this capability here')\n"
            "print(json.dumps(proposal, ensure_ascii=False))\n"
            % (str(SRC), str(self.project)))
        process = self.run_process([sys.executable, "-c", code_null], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        null_proposal = json.loads(process.stdout)
        null_confirmation = {
            "source_id": "e2e-S4-2e", "type": "conversation", "at": _utc_now(),
            "actor": {"role": "user", "id": "user-1"}, "reference": "e2e/session/input-2",
            "quote": "do not bind this capability in this project",
            "scope": {"target": "project", "path": null_proposal["path"],
                      "changes": null_proposal["changes"], "tools": {}},
            "validates": null_proposal["digest"],
        }
        code_null_apply = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "proposal = json.loads(sys.stdin.read())\n"
            "confirmation = json.loads(sys.argv[1])\n"
            "tools.apply_binding(proposal, confirmation,\n"
            "                    user_root=Path(%r), project_root=Path(%r),\n"
            "                    runtime_root=Path(%r), clock=lambda: %r)\n"
            "print('applied')\n"
            % (str(SRC), str(self.user_root), str(self.project), str(self.runtime_root), _utc_now()))
        process = self.run_process([sys.executable, "-c", code_null_apply, json.dumps(null_confirmation)],
                                 input=json.dumps(null_proposal), capture_output=True, text=True,
                                 env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        record_step(self.scenario, "S4-2e", "internal-api: project-layer explicit null binding",
                    process.returncode, "tool:null stops fallback to the user layer",
                    "project tools.yaml written with null binding", "pass", setup="internal-api")
        code_resolve = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "user = tools.load_tools(Path(%r))\n"
            "project = tools.load_tools(Path(%r))\n"
            "resolution = tools.resolve_bindings(project=project, user=user)\n"
            "print(json.dumps(resolution, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root / "tools.yaml"),
               str(self.project / ".fstar" / "tools.yaml")))
        process = self.run_process([sys.executable, "-c", code_resolve], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        resolution = json.loads(process.stdout)
        entry = next(c for c in resolution["capabilities"] if c["capability"] == "code-structure")
        self.assertEqual("unbound", entry["state"])
        record_step(self.scenario, "S4-2f", "internal-api: resolve after null binding",
                    process.returncode, "project null shadows the user binding -> unbound",
                    "state=%s origin=%s" % (entry["state"], entry["origin"]["layer"]), "pass",
                    setup="internal-api")

    def s4_gap_report(self):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "user = tools.load_tools(Path(%r))\n"
            "project = tools.load_tools(Path(%r))\n"
            "resolution = tools.resolve_bindings(project=project, user=user)\n"
            "availability = tools.assess_availability(resolution, [])\n"
            "print(json.dumps(availability, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root / "tools.yaml"),
               str(self.project / ".fstar" / "tools.yaml")))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        availability = json.loads(process.stdout)
        self.assertTrue(availability["gaps"])
        gap = next(g for g in availability["gaps"] if g["capability"] == "code-structure")
        self.assertEqual(["discoverable", "client_loaded", "minimal_call"], gap["missing_layers"])
        self.assertIn("State the gap explicitly", gap["fallback"])
        record_step(self.scenario, "S4-3", "internal-api: assess_availability(resolution, [])",
                    process.returncode,
                    "unbound capability -> gap report with actual missing layers + FALLBACKS text; no auto-install",
                    "gaps=%s fallback=%s..." % ([g["capability"] for g in availability["gaps"]],
                                                gap["fallback"][:40]),
                    "pass", setup="internal-api")

    def s4_availability_provenance(self):
        now = _utc_now()
        scope = {"project": str(self.project), "host": "fixture", "session": "e2e"}
        observations = [
            {"tool": "codegraph", "capability": "code-structure", "layer": "discoverable",
             "status": "verified", "at": now, "scope": scope, "evidence_ref": "e2e-path-scan"},
            {"tool": "codegraph", "capability": "code-structure", "layer": "client_loaded",
             "status": "failed", "at": now, "scope": scope, "reason": "client not running"},
            {"tool": "codegraph", "capability": "code-structure", "layer": "minimal_call",
             "status": "unknown", "at": now, "scope": scope},
        ]
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from fstar import tools\n"
            "user = tools.load_tools(Path(%r))\n"
            "project = tools.load_tools(Path(%r))\n"
            "resolution = tools.resolve_bindings(user=user)\n"
            "observations = json.loads(sys.stdin.read())\n"
            "availability = tools.assess_availability(resolution, observations, now=%r)\n"
            "record = tools.build_provenance(resolution, {\n"
            "    'capability': 'code-structure', 'tool': 'codegraph', 'at': %r,\n"
            "    'call': {'id': 'call-e2e-1', 'reference': 'e2e fixture call',\n"
            "             'operation': 'symbol lookup', 'result': 'passed'},\n"
            "    'result': 'passed'}, availability)\n"
            "print(json.dumps({'availability': availability, 'record': record}, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root / "tools.yaml"),
               str(self.project / ".fstar" / "tools.yaml"), now, now))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], input=json.dumps(observations),
                                 capture_output=True, text=True, env=env, cwd=str(self.root),
                                 timeout=120)
        self.assertEqual(0, process.returncode, process.stderr)
        payload = json.loads(process.stdout)
        entry = next(c for c in payload["availability"]["capabilities"]
                     if c["capability"] == "code-structure")
        self.assertEqual("verified", entry["layers"]["discoverable"]["status"])
        self.assertEqual("failed", entry["layers"]["client_loaded"]["status"])
        self.assertEqual("unknown", entry["layers"]["minimal_call"]["status"])
        self.assertEqual("fstar.tool-use.v1", payload["record"]["schema"])
        record_step(self.scenario, "S4-4",
                    "internal-api: assess_availability(3 layers) + build_provenance",
                    process.returncode,
                    "three layers reported independently; provenance fstar.tool-use.v1 with real call id",
                    "layers=%s record=%s" % ({k: v["status"] for k, v in entry["layers"].items()},
                                             payload["record"]["schema"]),
                    "pass", setup="internal-api")


# ===========================================================================
# S5 — knowledge chain (3 steps)
# ===========================================================================

S5_RULE = """---
schema: fstar.knowledge.v1
type: rule
status: active
strength: enforced
---

# E2E rule

MUST run tests before done.
APPLIES: every task.
NOT: docs.
SOURCE: e2e fixture.
"""

S5_SPEC = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# E2E spec

The counter module owns value semantics.
"""

S5_SPEC_V2 = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# E2E spec

The counter module owns value semantics and globals are forbidden.
"""


class S5KnowledgeChain(PersistentLifecycleCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S5"

    def test_s5_knowledge_chain(self):
        # S5-1 catalog/context/resolve with fixture rules/memory/specs
        self.build_knowledge_fixture()
        payload = self.knowledge_api("S5-1", (
            "from fstar.knowledge import load_catalog, load_context, ReadSelection, resolve_context, SemanticAssessment, ReviewedSource, ReportedConflict\n"
            "catalog = load_catalog(user_root=%r, project_root=%r)\n"
            "bundle = load_context(catalog, selection=ReadSelection(topics=('T-e2e',)))\n"
            "reviewed = tuple(ReviewedSource(d.key, d.digest) for d in bundle.full_documents) + tuple(ReviewedSource(i.key, i.digest) for i in catalog.indexes)\n"
            "assessment = SemanticAssessment(reviewed=reviewed, conflicts=(ReportedConflict(sources=('user:rules/e2e-rule.md', 'project:.fstar/specs/e2e-spec.md')),), coverage='complete')\n"
            "resolution = resolve_context(bundle, assessment=assessment)\n"
            "tiers = {source.key: source.tier for source in resolution.ordered_sources}\n"
            "assert tiers['user:rules/e2e-rule.md'] == 0, tiers\n"
            "assert tiers['project:.fstar/specs/e2e-spec.md'] == 1, tiers\n"
            "assert tiers['user:rules/e2e-default.md'] == 2, tiers\n"
            "assert tiers['user:memory/e2e-confirmed.md'] == 3, tiers\n"
            "assert resolution.conflicts[0].winner == 'user:rules/e2e-rule.md'\n"
            "print(json.dumps({'tiers': tiers, 'snapshot': catalog.snapshot_hash,\n"
            "                  'documents': [d.key for d in bundle.full_documents],\n"
            "                  'complete': bundle.complete}, ensure_ascii=False))\n"
            % (str(self.user_root), str(self.project))))
        self.assertEqual(0, payload[0], payload[2])
        result = json.loads(payload[1])
        keys = result["documents"]
        self.assertIn("user:rules/e2e-rule.md", keys)
        self.assertIn("project:.fstar/specs/e2e-spec.md", keys)
        # superseded/unreviewed are not loaded
        self.assertNotIn("user:rules/e2e-old.md", keys)
        self.assertNotIn("user:memory/e2e-lesson.md", keys)
        record_step(self.scenario, "S5-1", "internal-api: load_catalog + load_context + resolve",
                    0, "strict fstar.knowledge.v1; superseded/unreviewed not loaded; four-tier priority",
                    "documents=%s" % keys, "pass", setup="internal-api")

        # S5-2 prepare -> denied apply (zero writes) -> approved apply (group update)
        before = self.tree_snapshot(self.project / ".fstar", self.user_root)
        proposal = self.knowledge_proposal()
        denied = self.knowledge_apply("S5-2a", proposal, disposition="denied")
        self.assertNotEqual(0, denied[0], "denied confirmation must be rejected")
        self.assertEqual(before, self.tree_snapshot(self.project / ".fstar", self.user_root))
        record_step(self.scenario, "S5-2a", "internal-api: apply_change(denied)",
                    denied[0], "zero writes on denial", _actual_of_of(denied), "pass",
                    setup="internal-api")
        approved = self.knowledge_apply("S5-2b", proposal, disposition="approved")
        self.assertEqual(0, approved[0], approved[2])
        body = (self.project / ".fstar" / "specs" / "e2e-spec.md").read_text(encoding="utf-8")
        self.assertIn("globals are forbidden", body)
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertIn("T-e2e", index)
        record_step(self.scenario, "S5-2b", "internal-api: apply_change(approved)",
                    approved[0], "proposal-bound approval updates the spec and preserves its indexed topic",
                    "spec body changed; topic remains indexed; index/reference mutation not established", "pass", setup="internal-api")

        self.knowledge_group_update()

        # S5-3 spec body consumed by worker-context injection with {path, sha256, version}
        self.init_project_cli()
        self.create_main_task("know-task")
        self.enable_extension("S5-3-setup", "know-task", "project-governance")
        self.write_docs("know-task")
        task_dir = self.project / ".fstar" / "tasks" / "know-task"
        (task_dir / "implement.jsonl").write_text(
            json.dumps({"file": ".fstar/specs/e2e-spec.md", "reason": "counter spec"}) + "\n",
            encoding="utf-8")
        self.persist_map("S5-3-map", "know-task")
        self.step("S5-3a", ["start", "know-task", "--confirm-user",
                            "--invocation", "e2e-S5-3"],
                  expected="task started", check=self.expect_ok())
        self.step_hook("S5-3b", "worker-context",
                       {"session_id": "s5", "cwd": str(self.project),
                        "role": "fstar-implement", "task_ref": "know-task",
                        "plan_item_ids": ["P-1"]},
                       expected="spec body injected in full with path/sha256/version envelope",
                       check=lambda process: (
                           self.assertEqual(0, process.returncode, process.stderr),
                           self.assertIn("counter module owns value semantics", process.stdout),
                           self.assertIn(".fstar/specs/e2e-spec.md", process.stdout),
                           self.assertIn("sha256=", process.stdout),
                           "spec body + fingerprint envelope injected")[3],
                       project=str(self.project))

    def knowledge_group_update(self):
        code = (
            "from fstar.knowledge import (load_catalog, ReviewedSource, SemanticAssessment, KnowledgeEdit, ChangeIntent, SourceRecord, TopicChoice, prepare_change, Confirmation, apply_change)\n"
            "catalog = load_catalog(user_root=%r, project_root=%r)\n"
            "reviewed = tuple([ReviewedSource(d.key, d.digest) for d in catalog.documents if d.effective] + [ReviewedSource(i.key, i.digest) for i in catalog.indexes])\n"
            "assessment = SemanticAssessment(reviewed=reviewed, conflicts=(), coverage='complete')\n"
            "body = %r\n"
            "intent = ChangeIntent(summary='add indexed linked spec', action='create', source=SourceRecord('conversation', 'fixture#group', 'yes', '2026-10-30'), scope='new linked spec', topic=TopicChoice('T-linked', 'Linked spec', is_new=True, reason='new topic', applies_to='src/linked', read_when='linked work'))\n"
            "proposal = prepare_change(catalog, edits=[KnowledgeEdit(path='.fstar/specs/linked.md', owner='project', action='create', content=body)], intent=intent, assessment=assessment)\n"
            "confirmation = Confirmation(disposition='approved', source_type='conversation', source_ref='fixture#group', quote='yes', confirmed_at='2026-10-30', proposal_hash=proposal.proposal_hash, scope=proposal.scope, owners=proposal.owners)\n"
            "receipt = apply_change(proposal, confirmation, user_root=%r, project_root=%r)\n"
            "print(json.dumps({'changed': receipt.changed_paths, 'hash': proposal.proposal_hash}))\n"
            % (str(self.user_root), str(self.project), S5_SPEC + "\nSee [counter spec](e2e-spec.md).\n", str(self.user_root), str(self.project)))
        index = self.project / ".fstar/index.md"
        before = index.read_text(encoding="utf-8")
        rc, stdout, stderr = self.knowledge_api("S5-group-update", code)
        try:
            self.assertEqual(0, rc, stderr)
            body = (self.project / ".fstar/specs/linked.md").read_text(encoding="utf-8")
            after = index.read_text(encoding="utf-8")
            self.assertNotEqual(before, after)
            self.assertIn("T-linked", after)
            self.assertIn(".fstar/specs/linked.md", after)
            self.assertIn("[counter spec](e2e-spec.md)", body)
            self.assertTrue((self.project / ".fstar/specs/e2e-spec.md").is_file())
        except Exception:
            record_step(self.scenario, "S5-group-update", self._command, rc, "approved grouped creation, index update and resolvable reference", stderr or stdout, "fail", setup="internal-api")
            raise
        record_step(self.scenario, "S5-group-update", self._command, rc, "approved grouped creation, index update and resolvable reference", stdout, "pass", setup="internal-api")

    # -- S5 helpers ---------------------------------------------------------

    def init_project_cli(self):
        self.step("S5-init", ["init", str(self.project)],
                  expected="project initialized", check=self.expect_ok())

    def build_knowledge_fixture(self):
        specs = self.project / ".fstar" / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / "e2e-spec.md").write_text(S5_SPEC, encoding="utf-8")
        rules = self.user_root / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        (rules / "e2e-rule.md").write_text(S5_RULE, encoding="utf-8")
        (rules / "e2e-old.md").write_text(
            S5_RULE.replace("status: active", "status: superseded").replace("E2E rule", "Old rule"),
            encoding="utf-8")
        memory = self.user_root / "memory"
        memory.mkdir(parents=True, exist_ok=True)
        (memory / "e2e-lesson.md").write_text(
            "---\nschema: fstar.knowledge.v1\ntype: memory\nstatus: active\n"
            "kind: lesson\ntrust: unreviewed\n---\n\n# Lesson\n\nMaybe tabs.\n",
            encoding="utf-8")
        (rules / "e2e-default.md").write_text(S5_RULE.replace("strength: enforced", "strength: default"), encoding="utf-8")
        (memory / "e2e-confirmed.md").write_text(
            "---\nschema: fstar.knowledge.v1\ntype: memory\nstatus: active\nkind: preference\ntrust: confirmed\n---\n\n# Preference\n\nUse short updates.\nAPPLIES: all tasks.\nNOT: nothing.\nSOURCE: fixture.\n",
            encoding="utf-8")
        # Project index must list the topic so the spec is applicable.
        (self.project / ".fstar" / "index.md").write_text(
            "# fstar 项目索引\n\n概况：e2e fixture project。\n\n## 主题\n\n"
            "### T-e2e — 计数器\n- Applies to: src\n- Read when: 修改计数器时\n"
            "- Authority: [.fstar/specs/e2e-spec.md](.fstar/specs/e2e-spec.md)\n",
            encoding="utf-8")
        (self.project / ".fstar" / "config.yaml").write_text(
            'schema_version: 1\nproject:\n  id: "%s"\n' % uuid.uuid4(), encoding="utf-8")
        (self.project / ".fstar" / ".schema-version").write_text("1\n", encoding="utf-8")
        (self.user_root / "index.md").write_text(
            "# fstar 用户索引\n\n## Rules\n\n- [E2E rule](rules/e2e-rule.md) — strength: enforced\n",
            encoding="utf-8")

    def knowledge_api(self, step_id, code_body):
        code = "import sys, json\nsys.path.insert(0, %r)\n%s" % (str(SRC), code_body)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env["HOME"] = str(self.root / "fake-home")
        process = self.run_process([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env, cwd=str(self.root), timeout=120)
        return process.returncode, process.stdout, process.stderr

    def knowledge_proposal(self):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.knowledge import (load_catalog, load_context, ReadSelection,\n"
            "    ReviewedSource, SemanticAssessment, KnowledgeEdit, ChangeIntent,\n"
            "    SourceRecord, TopicChoice, prepare_change)\n"
            "catalog = load_catalog(user_root=%r, project_root=%r)\n"
            "bundle = load_context(catalog, selection=ReadSelection(topics=('T-e2e',)))\n"
            "reviewed = [ReviewedSource(d.key, d.digest) for d in catalog.documents if d.effective]\n"
            "reviewed += [ReviewedSource(i.key, i.digest) for i in catalog.indexes]\n"
            "assessment = SemanticAssessment(reviewed=tuple(reviewed), conflicts=(), coverage='complete')\n"
            "edits = [KnowledgeEdit(path='.fstar/specs/e2e-spec.md', owner='project',\n"
            "                       action='replace', content=%r)]\n"
            "intent = ChangeIntent(summary='tighten spec', action='correct',\n"
            "                      source=SourceRecord('conversation', 'e2e#1', 'yes', '2026-10-30'),\n"
            "                      scope='counter spec', topic=TopicChoice('T-e2e', '计数器'))\n"
            "proposal = prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)\n"
            "print(json.dumps({'payload': proposal.payload(), 'hash': proposal.proposal_hash}, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root), str(self.project), S5_SPEC_V2))
        returncode, stdout, stderr = self.knowledge_api("S5-2-setup", code)
        assert returncode == 0, stderr
        return json.loads(stdout)

    def knowledge_apply(self, step_id, proposal_payload, disposition):
        code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "from fstar.knowledge import (Confirmation, apply_change, load_catalog,\n"
            "    load_context, ReadSelection, ReviewedSource, SemanticAssessment,\n"
            "    KnowledgeEdit, ChangeIntent, SourceRecord, TopicChoice, prepare_change)\n"
            "catalog = load_catalog(user_root=%r, project_root=%r)\n"
            "bundle = load_context(catalog, selection=ReadSelection(topics=('T-e2e',)))\n"
            "reviewed = [ReviewedSource(d.key, d.digest) for d in catalog.documents if d.effective]\n"
            "reviewed += [ReviewedSource(i.key, i.digest) for i in catalog.indexes]\n"
            "assessment = SemanticAssessment(reviewed=tuple(reviewed), conflicts=(), coverage='complete')\n"
            "edits = [KnowledgeEdit(path='.fstar/specs/e2e-spec.md', owner='project',\n"
            "                       action='replace', content=%r)]\n"
            "intent = ChangeIntent(summary='tighten spec', action='correct',\n"
            "                      source=SourceRecord('conversation', 'e2e#1', 'yes', '2026-10-30'),\n"
            "                      scope='counter spec', topic=TopicChoice('T-e2e', '计数器'))\n"
            "proposal = prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)\n"
            "assert proposal.proposal_hash == %r, 'proposal changed before confirmation'\n"
            "confirmation = Confirmation(disposition=%r, source_type='conversation',\n"
            "    source_ref='e2e#1', quote='yes', confirmed_at='2026-10-30',\n"
            "    proposal_hash=proposal.proposal_hash, scope=proposal.scope,\n"
            "    owners=proposal.owners)\n"
            "receipt = apply_change(proposal, confirmation, user_root=%r, project_root=%r)\n"
            "print(json.dumps({'changed': receipt.changed_paths}, ensure_ascii=False))\n"
            % (str(SRC), str(self.user_root), str(self.project), S5_SPEC_V2, proposal_payload["hash"], disposition,
               str(self.user_root), str(self.project)))
        return self.knowledge_api(step_id, code)


def _actual_of_of(triple):
    return (triple[2] or triple[1]).strip()[:400]


# ===========================================================================
# S6 — two-host fixture evidence (5 steps + blocked live-host item)
# ===========================================================================

class S6TwoHost(ScenarioCase):

    def setUp(self) -> None:
        super().setUp()
        self.scenario = "S6"
        self.claude_root = self.host_root / "claude"
        self.codex_root = self.host_root / "codex"
        self.claude_root.mkdir(parents=True)
        self.codex_root.mkdir(parents=True)

    def host_args(self):
        return ["--host-root", "claude=%s" % self.claude_root,
                "--host-root", "codex=%s" % self.codex_root]

    def test_s6_two_host_fixture(self):
        # S6-1 hook plan for both hosts (read-only, honest evidence levels)
        for host in ("claude", "codex"):
            self.step("S6-1-%s" % host, ["hook", "plan", "--host", host],
                      expected="4 entries with exact command, launcher_installed per disk, evidence observed/unverified-schema",
                      check=self.expect_ok(lambda p, h=host: (
                          "entries=%d evidence=%s" % (len(p["entries"]),
                                                      [e["hooks"][0]["evidence"] for e in p["entries"]]))))
            plan = json.loads(self.last_stdout)
            self.assertEqual(4, len(plan["entries"]))
            self.assertTrue(plan["read_only"])
            for entry in plan["entries"]:
                self.assertIn("command", entry["hooks"][0])
                self.assertIn("launcher_installed", entry["hooks"][0])
                self.assertIn(entry["hooks"][0]["evidence"],
                              ("observed-schema", "unverified-schema"))
        # No host settings were written by the plan.
        self.assertFalse((self.claude_root / "settings.json").exists())

        # S6-2 install into temp host roots only
        user_content = self.user_root / "personal-note.md"
        user_content.write_text("user-owned content\n", encoding="utf-8")
        self.step("S6-2", ["install", "--host", "claude", "--host", "codex"] + self.host_args(),
                  expected="install writes only temp roots; append/dedup; user entries preserved",
                  check=self.expect_ok())
        claude_settings = self.claude_root / "settings.json"
        self.assertTrue(claude_settings.is_file())
        document = json.loads(claude_settings.read_text(encoding="utf-8"))
        self.assertIn("hooks", document)
        # Pre-existing user entry survives: add one and reinstall (dedup).
        document["hooks"]["SessionStart"].append(
            {"matcher": "user", "hooks": [{"type": "command", "command": "echo user-owned"}]})
        claude_settings.write_text(json.dumps(document), encoding="utf-8")
        self.step("S6-2b", ["install", "--host", "claude"] + self.host_args(),
                  expected="reinstall dedups fstar entries and preserves the user entry",
                  check=self.expect_ok())
        document = json.loads(claude_settings.read_text(encoding="utf-8"))
        user_entries = [h for h in document["hooks"]["SessionStart"]
                        if h.get("matcher") == "user"]
        self.assertEqual(1, len(user_entries))
        fstar_commands = [h["command"] for groups in document["hooks"].values() for group in groups
                          for h in group["hooks"] if "fstar" in h["command"]]
        self.assertEqual(4, len(fstar_commands), "dedup must keep exactly 4 fstar hooks")

        # S6-3 doctor: disk-verified entries; indexed-but-uninstalled -> stale
        self.step("S6-3", ["doctor"] + self.host_args(),
                  expected="12/4/4/11/5 counts healthy; entries disk-verified",
                  check=self.expect_ok(lambda p: (
                      "counts=%s healthy=%s" % (p["counts"], p["healthy"]))))
        report = json.loads(self.last_stdout)
        self.assertEqual({"skills": 12, "roles": 4, "templates": 11,
                          "capabilities": 5, "hooks": 4}, report["counts"])
        self.assertTrue(report["healthy"])
        # Stale entry index: remove an installed entry file, doctor must flag it.
        entries = report["entries"]["items"]
        self.assertTrue(entries)
        victim = Path(entries[0]["installed_path"])
        victim_bytes = victim.read_bytes()
        if victim.is_file():
            victim.unlink()
            self.step("S6-3b", ["doctor"] + self.host_args(),
                      expected="entry_index_stale diagnostic and healthy=false",
                      check=lambda process: (
                          self.assertNotEqual(0, process.returncode),
                          payload := json.loads(process.stdout),
                          self.assertFalse(payload["healthy"]),
                          self.assertTrue(any(d["code"] == "entry_index_stale"
                                              for d in payload["diagnostics"])),
                          "entry_index_stale flagged")[4])

        victim.write_bytes(victim_bytes)

        # S6-4 uninstall: precise removal of own 4 hooks + owned files
        self.step("S6-4", ["uninstall", "--host", "claude", "--host", "codex"] + self.host_args(),
                  expected="only fstar's own 4 hooks and installer-owned files removed; user content kept",
                  check=self.expect_ok())
        if claude_settings.exists():
            document = json.loads(claude_settings.read_text(encoding="utf-8"))
            remaining = [h["command"] for groups in document.get("hooks", {}).values() for group in groups
                         for h in group.get("hooks", []) if "fstar" in h.get("command", "")]
            self.assertEqual([], remaining, "uninstall must remove all fstar hooks")
            user_entries = [h for groups in document.get("hooks", {}).values() for group in groups
                            for h in group.get("hooks", []) if "user-owned" in h.get("command", "")]
            self.assertEqual(1, len(user_entries), "user entry must survive")
        # User data root content (index/config) survives.
        self.assertEqual("user-owned content\n", user_content.read_text(encoding="utf-8"))

        # S6-5 real HOME untouched — asserted by tearDown on every scenario; here
        # we additionally record the explicit snapshot comparison.
        after = _snapshot_paths(REAL_HOME_PATHS)
        self.assertEqual(self._home_before, after)
        record_step(self.scenario, "S6-5", "snapshot compare of real ~/.fstar and ~/.claude",
                    0, "real home paths byte-identical before/after the whole scenario",
                    "unchanged", "pass")

        # S6-6 live-host check stays BLOCKED (never write real settings).
        record_note("S6", "Hook plans report observed-schema or unverified-schema; fixture installation is not live delivery. live-delivery=0.")
        self.record_blocked(
            "S6-6",
            "Real Claude/Codex session hook delivery (SessionStart/PreToolUse/PostToolUse/SubagentStop actually firing)",
            "user authorization to register hooks in real host settings and observe a real session; "
            "this scenario never writes real settings")


if __name__ == "__main__":
    unittest.main()
