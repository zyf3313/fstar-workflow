"""The four semantic hooks and their host event mapping.

Semantic hooks (exactly four; no turn-context, no fifth hook, no custom hook
entry points):

- session-context: session start/clear/compact equivalent — inject routing
  full text, project/user indexes, current-task summary (read-only), light
  tool-binding checks. No archive patrol, no full tool scan, no writes.
- worker-context: before native dispatch — full role-applicable context with
  per-input fingerprints and budgets; overloaded inputs go to an unloaded
  manifest with a mandatory re-read instruction.
- worker-result: done/failed/cancelled recovery — verify dispatch identity,
  record delivery evidence via core (lease renewal +30m internal) or release
  the lease, route check/debug. Never writes acceptance.
- doc-change: after a doc/*.md edit — idempotent fingerprint comparison,
  invalidate affected evidence via core, emit one change-propagation line.
  No tests, no reports, no recursive derived-file handling.

Host event names/payloads are data-driven below. Entries marked verified were
confirmed against the installed hosts at implementation time (Claude Code
2.1.312 binary strings + local registration; codex-cli 0.165.0 generated
app-server protocol schema). Unverified payload assumptions carry to_verify
notes, and every hook has a boundary fallback: the same entry function runs
at the dispatch/recovery/command boundary when the host event is unavailable,
so logic never depends on a host event existing.

Passive vs explicit (child design §5): passive bookkeeping (host event or
fallback caller without task data) silently skips the task part — exit 0, no
files, no noise — while routing/role injection still happens. The explicit
``fstar hook <name>`` CLI requesting task data in a non-initialized directory
raises project_not_initialized instead of silently succeeding.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..evidence import file_digest
from ..extensions import grants, includes
from ..models import DomainError
from ..store import TaskStore
from ..tasks import TaskService
from . import inject, registration

HOOK_NAMES = ("session-context", "worker-context", "worker-result", "doc-change")
HOOK_MARKER = inject.HOOK_MARKER

# Data-driven host event mapping (child design §3). "verified" reflects
# implementation-time observation of the installed host binaries; payload
# assumptions that could not be observed carry to_verify entries. The
# fallback names the boundary that runs the same entry function when the
# host event is missing — no fifth hook is ever added for this.
HOST_EVENT_MAP: Dict[str, Dict[str, dict]] = {
    "claude": {
        "session-context": {
            "events": ["SessionStart"],
            "matchers": ["startup", "clear", "compact"],
            "payload_keys": ["session_id", "cwd", "source", "hook_event_name"],
            "verified": True,
            "to_verify": [],
            "fallback": "fstar hook session-context invoked manually or by the entry skill",
        },
        "worker-context": {
            "events": ["PreToolUse"],
            "matchers": ["Task", "Agent"],
            "payload_keys": ["session_id", "cwd", "tool_name", "tool_input", "hook_event_name"],
            "verified": True,
            "to_verify": ["tool_input field names for role/task arguments are adapter-level"],
            "fallback": "runtime-dispatch dispatch wrapper invokes worker_context()",
        },
        "worker-result": {
            "events": ["SubagentStop"],
            "matchers": [],
            "payload_keys": ["session_id", "transcript_path", "hook_event_name"],
            "verified": True,
            "to_verify": ["SubagentStop cannot carry the dispatch result message; recovery boundary is primary"],
            "fallback": "runtime-dispatch recovery boundary invokes worker_result()",
        },
        "doc-change": {
            "events": ["PostToolUse"],
            "matchers": ["Edit", "Write"],
            "payload_keys": ["session_id", "cwd", "tool_name", "tool_input", "hook_event_name"],
            "verified": True,
            "to_verify": ["tool_input.file_path is the observed Edit/Write payload key"],
            "fallback": "fstar evidence invalidate plus core read-boundary recalculation",
        },
    },
    "codex": {
        "session-context": {
            "events": ["SessionStart"],
            "matchers": [],
            "payload_keys": ["session_id", "cwd", "hook_event_name"],
            "verified": True,
            "to_verify": [
                "SessionStart exists in the codex HookEventName enum (sessionStart) but no live "
                "registration was observed; the hooks.json key casing and payload shape are to-verify",
            ],
            "fallback": "fstar hook session-context invoked manually or by the entry skill",
        },
        "worker-context": {
            "events": ["SubagentStart"],
            "matchers": [],
            "payload_keys": ["session_id", "agent_type", "agentType", "cwd", "hook_event_name"],
            "verified": True,
            "to_verify": ["agent_type to fstar role mapping is adapter-level"],
            "fallback": "runtime-dispatch dispatch wrapper invokes worker_context()",
        },
        "worker-result": {
            "events": ["SubagentStop"],
            "matchers": [],
            "payload_keys": ["session_id", "hook_event_name"],
            "verified": True,
            "to_verify": ["subagentStop payload shape not exposed by generated schema; cannot carry the result message"],
            "fallback": "runtime-dispatch recovery boundary invokes worker_result()",
        },
        "doc-change": {
            "events": ["PostToolUse"],
            "matchers": [],
            "payload_keys": ["session_id", "cwd", "hook_event_name"],
            "verified": False,
            "to_verify": ["postToolUse file-path payload key not exposed by generated schema"],
            "fallback": "fstar evidence invalidate plus core read-boundary recalculation",
        },
    },
}


def _clock() -> str:
    from ..tasks import utc_now
    return utc_now()


def _service_for(store: TaskStore, clock: Optional[Callable[[], str]] = None) -> TaskService:
    return TaskService(store, clock=clock or _clock)


def _payload_str(payload: dict, *keys: str) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


# ---------------------------------------------------------------------------
# session-context
# ---------------------------------------------------------------------------

def _light_tool_check(project_root: Path, user_root: Path) -> List[str]:
    """Light check only: tools.yaml existence + detected_at staleness hint.

    No full scan, no probing, no writes (parent design §3.6: the full scan is
    init/tools scan only; session-context checks existing binding presence
    and detected_at age).
    """
    notes = []
    for label, path in (("project", project_root / ".fstar" / "tools.yaml"), ("user", user_root / "tools.yaml")):
        if not path.is_file():
            notes.append("tools.yaml (%s) not present; run fstar tools scan to establish bindings" % label)
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            notes.append("tools.yaml (%s) is unreadable; run fstar tools scan" % label)
            continue
        match = re.search(r"detected_at\s*[:=]\s*\"?([^\s\"]+)\"?", body)
        if not match:
            notes.append("tools.yaml (%s) has no detected_at; run fstar tools scan" % label)
    return notes


def session_context(payload: Optional[dict] = None, *, start: Optional[Path] = None,
                    user_root: Optional[Path] = None, runtime_root: Optional[Path] = None,
                    clock: Optional[Callable[[], str]] = None,
                    as_json: bool = False, passive: bool = True) -> dict:
    """Session start/clear/compact injection. Read-only; never writes."""
    payload = payload or {}
    session_id = _payload_str(payload, "session_id", "sessionId")
    located = inject.locate(start, user_root=user_root, runtime_root=runtime_root)
    project_root = located["project_root"]
    user = located["user_root"]
    budgets = inject.read_budgets(project_root, user)
    # The routing source follows the effective resources version (handoff row
    # 1): project/user pin changes the consumed content; a broken pin raises
    # instead of silently injecting the bundled copy.
    root = inject.resource_root(project_root, user)

    inputs: List[inject.InjectedInput] = []
    routing = inject.routing_input(root)
    if routing:
        inputs.append(routing)
    # Discovery is always on: a package that stays off and unannounced is
    # effectively absent. Grants still gate every package member.
    capabilities = inject.capabilities_input(root)
    if capabilities:
        inputs.append(capabilities)
    # The resolved binding table is discovery too: reading it never authorizes
    # writing tools.yaml, so it is injected without a tool-capability grant.
    # A binding that stays invisible would be effectively unbound.
    bindings = inject.bindings_input(project_root, user)
    if bindings:
        inputs.append(bindings)
    context = {}
    persistent_context = False

    task_summary = None
    tool_notes: List[str] = []
    learn_hint = ("Learn candidates attach to existing session/result/recovery/archive "
                  "nodes; a durable convention stated by the user is a session-node "
                  "candidate. No per-turn scan and no standalone candidate ledger exists.")
    if project_root is not None:
        store = located["store"]
        service = _service_for(store, clock)
        current = service.current(session_id)
        task = current.get("current")
        if task is not None:
            persistent_context = True
            try:
                stored = store.read(task["id"])
                context = grants(stored["extensions"])
                state = service.state(task["id"])
                task_summary = {
                    "task_id": task["id"],
                    "name": task["name"],
                    "title": task["title"],
                    "phase": state["phase"],
                    "effective_phase": state["effective_phase"],
                    "blocked": state["blocked"],
                    "lease": bool(state["lease"]),
                    "awaiting_acceptance": state["acceptance"]["awaiting_acceptance"],
                    "path": current.get("path"),
                }
            except DomainError:
                # A stale pointer or inconsistent tree is not session-start
                # noise; the explicit continue command reports it.
                task_summary = None
                context = {}

    if not persistent_context:
        context = grants(payload.get("extensions", []))
    if project_root is not None and includes(context, "tool-capability", "bindings"):
        tool_notes = _light_tool_check(project_root, user)

    # Indexes are read-only context: inject them by default so user-level rules
    # and project knowledge stay visible without an extension grant. Writing to
    # these surfaces still requires project-governance and explicit confirmation.
    inputs.extend(inject.index_inputs(project_root, user))

    grant_text = "Extension members in this context: %s" % json.dumps(
        {key: sorted(value) for key, value in context.items()}, sort_keys=True)
    if as_json:
        rendered = inject.render_json("fstar session context", inputs, budgets, footer=grant_text)
        rendered["extensions"] = {key: sorted(value) for key, value in context.items()}
        result = dict(rendered)
        result["session_id"] = session_id
        result["project_root"] = str(project_root) if project_root else None
        result["initialized"] = project_root is not None
        result["current_task"] = task_summary
        result["tool_notes"] = tool_notes
        result["learn_hint"] = learn_hint
        return result
    lines = [inject.render("fstar session context", inputs, budgets, footer=grant_text)]
    if task_summary is not None:
        lines.append("## Current task")
        lines.append("")
        lines.append("- %s (%s): phase=%s, blocked=%s, lease=%s, awaiting_acceptance=%s" % (
            task_summary["name"], task_summary["task_id"], task_summary["phase"],
            "yes" if task_summary["blocked"] else "no",
            "yes" if task_summary["lease"] else "no",
            "yes" if task_summary["awaiting_acceptance"] else "no"))
        lines.append("")
    elif project_root is None:
        lines.append("No initialized fstar project found; task bookkeeping skipped (this is normal outside an initialized project).")
        lines.append("")
    for note in tool_notes:
        lines.append("- %s" % note)
    lines.append(learn_hint)
    return {"text": "\n".join(lines), "session_id": session_id,
            "initialized": project_root is not None, "current_task": task_summary}


# ---------------------------------------------------------------------------
# worker-context
# ---------------------------------------------------------------------------

def _role_from_payload(payload: dict) -> Optional[str]:
    """Role extraction from a host dispatch payload.

    Only fstar-prefixed role identifiers are recognized. A bare agent type or
    another product's agent name (e.g. trellis-*) is NOT an fstar role: fstar's
    worker-context must not inject into another product's sub-agents.
    """
    raw = _payload_str(payload, "role", "agent_type", "agentType", "subagent_type")
    if not raw:
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, dict):
            raw = _payload_str(tool_input, "role", "agent_type", "agentType", "subagent_type")
    if not raw:
        return None
    cleaned = raw.lower().replace("fstar-", "")
    return cleaned if cleaned in inject.ROLES else None


GOVERNED_MEMBERS = {"specs", "knowledge", "rules", "memory"}
PLANNING_MEMBERS = {
    "doc/prd.md": "prd",
    "doc/design.md": "design",
    "plan.md": "plan",
    "clarify.md": "clarify",
}


def _resolved_relative(path: Path, root: Path) -> tuple:
    """Resolved path parts relative to ``root``; empty when outside/unreadable."""
    try:
        return path.resolve().relative_to(root.resolve()).parts
    except (ValueError, OSError, RuntimeError):
        return ()


def _governance_member(project_root: Path, path: Path) -> Optional[str]:
    """Return the governance member owning ``path``, after path resolution.

    The comparison is casefolded on purpose: APFS/HFS+ resolve
    ``.FSTAR/specs`` to the same directory as ``.fstar/specs``, so a purely
    lexical segment check lets a case alias bypass the grant filter. On a
    case-sensitive filesystem this can only over-filter (fail closed), never
    under-filter.
    """
    parts = _resolved_relative(path, project_root)
    if len(parts) >= 2 and parts[0].casefold() == ".fstar":
        member = parts[1].casefold()
        if member in GOVERNED_MEMBERS:
            return member
    return None


def _planning_member(project_root: Path, path: Path) -> Optional[str]:
    """Classify planning artifacts in active tasks and archived task trees."""
    parts = tuple(part.casefold() for part in _resolved_relative(path, project_root))
    if len(parts) < 4 or parts[:2] not in ((".fstar", "tasks"), (".fstar", "archive")):
        return None
    for artifact, member in PLANNING_MEMBERS.items():
        suffix = tuple(artifact.split("/"))
        if len(parts) > 2 + len(suffix) and parts[-len(suffix):] == suffix:
            return member
    return None


def worker_context(payload: Optional[dict] = None, *, role: Optional[str] = None,
                   task_ref: Optional[str] = None, plan_item_ids: Optional[List[str]] = None,
                   start: Optional[Path] = None, user_root: Optional[Path] = None,
                   runtime_root: Optional[Path] = None,
                   clock: Optional[Callable[[], str]] = None, as_json: bool = False) -> dict:
    """Pre-dispatch injection: full role-applicable context with fingerprints."""
    payload = payload or {}
    role = role or _role_from_payload(payload)
    if role is None:
        raise DomainError("role_required", "worker-context requires one of the four roles", {"roles": sorted(inject.ROLES)})
    task_ref = task_ref or _payload_str(payload, "task_ref", "task", "taskRef")
    session_id = _payload_str(payload, "session_id", "sessionId")
    plan_item_ids = list(plan_item_ids or payload.get("plan_item_ids") or [])

    located = inject.locate(start, user_root=user_root, runtime_root=runtime_root)
    project_root = located["project_root"]
    user = located["user_root"]
    budgets = inject.read_budgets(project_root, user)
    # Same resolver as session-context (handoff row 1): role cards follow the
    # effective resources version; a broken pin is an honest error.
    root = inject.resource_root(project_root, user)

    inputs: List[inject.InjectedInput] = []
    routing = inject.routing_input(root)
    if routing:
        inputs.append(routing)
    card = inject.role_card(role, root)
    if card:
        inputs.append(card)
    # Same read-only binding table as session-context: the worker must see
    # which tool each capability resolves to without any grant, and reading
    # it never authorizes changing it.
    bindings = inject.bindings_input(project_root, user)
    if bindings:
        inputs.append(bindings)

    task_line = inject.session_only_reference()
    context = {}
    task_summary = None
    if task_ref and task_ref != "session-only" and project_root is None:
        raise DomainError("project_not_initialized", "Persistent worker context requires an initialized project")
    if project_root is not None:
        store = located["store"]
        service = _service_for(store, clock)
        if not task_ref and session_id:
            # Host dispatch payloads may only carry the session; resolve the
            # session-scoped pointer read-only (never write it back).
            current = service.current(session_id)
            if current.get("current"):
                task_ref = current["current"]["id"]
        if task_ref and task_ref != "session-only":
            task_dir = store.resolve(task_ref)
            task = store.read(task_ref)
            context = grants(task["extensions"])
            task_line = inject.active_task_reference(str(task_dir))
            inputs.extend(inject.task_doc_inputs(project_root, task_dir, context.get("planning-review", set())))
            # Full applicable spec/research bodies from the role's
            # manifest (parent design §4.4: complete applicable spec
            # text; index lines never replace source bodies). Both
            # manifests are loaded: implement/check share the applicable
            # specification surface, and the parent's requirement is that
            # the whole applicable context be read.
            for action in ("implement", "check"):
                entries = inject.manifest_entries(project_root, task_dir, action)
                if entries:
                    # Manifests may also contain ordinary project inputs. Only
                    # fstar's governance-owned paths require the grant, and
                    # classification uses the resolved path so case aliases
                    # cannot slip past the filter.
                    allowed = []
                    for entry in entries:
                        path = project_root / entry["file"]
                        if not inject._safe_context_path(project_root, path):
                            continue
                        governed = _governance_member(project_root, path)
                        if governed and not includes(context, "project-governance", governed):
                            continue
                        member = _planning_member(project_root, path)
                        if member and not includes(context, "planning-review", member):
                            continue
                        allowed.append(entry)
                    inputs.extend(inject.spec_body_inputs(project_root, allowed))
            # Item-level fingerprints for the plan items via core snapshot;
            # missing artifact maps are skipped, never fabricated.
            artifact = str((task_dir.relative_to(project_root) / "plan.md").as_posix())
            snap = (inject.item_snapshots(service.evidence, task_ref, artifact, plan_item_ids)
                    if includes(context, "planning-review", "plan") else None)
            task_summary = {"task_id": task["id"], "name": task["name"], "phase": task["phase"],
                            "plan_item_ids": plan_item_ids, "item_snapshot": snap}

    if not task_ref or task_ref == "session-only":
        context = grants(payload.get("extensions", []))
    role_member = {"research": ("multi-agent", "research"),
                   "editor": ("planning-review", "editor")}.get(role)
    if role_member and not includes(context, *role_member):
        raise DomainError("extension_not_authorized", "Worker role requires an included extension member",
                          {"package": role_member[0], "member": role_member[1]}, status=3)

    footer = ["%s" % task_line, "Extension members in this context: %s" % json.dumps(
        {key: sorted(value) for key, value in context.items()}, sort_keys=True)]
    footer.append("Role: %s. Read complete applicable context; summaries do not replace source bodies." % role)
    footer.append("If any input is listed under 'Unloaded inputs', you MUST read it in full before executing.")

    if as_json:
        rendered = inject.render_json("fstar worker context (%s)" % role, inputs, budgets, footer="\n".join(footer))
        result = dict(rendered)
        result["role"] = role
        result["task_ref"] = task_ref
        result["session_id"] = session_id
        result["active_task"] = task_line
        result["task_summary"] = task_summary
        return result
    return {"text": inject.render("fstar worker context (%s)" % role, inputs, budgets, footer="\n".join(footer)),
            "role": role, "active_task": task_line, "task_summary": task_summary}


# ---------------------------------------------------------------------------
# worker-result
# ---------------------------------------------------------------------------

RESULT_STATUSES = ("done", "failed", "cancelled")


def _result_ref(result: dict) -> Optional[str]:
    for key in ("task_ref", "task", "taskRef"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def worker_result(result: Optional[dict] = None, *, start: Optional[Path] = None,
                  user_root: Optional[Path] = None, runtime_root: Optional[Path] = None,
                  clock: Optional[Callable[[], str]] = None, passive: bool = True,
                  payload: Optional[dict] = None) -> dict:
    """Recovery of a dispatch result: route through the single harvest path.

    This entry never builds evidence of its own. It resolves the dispatch
    payload (host events cannot carry it; the runtime-dispatch recovery
    boundary supplies it), then delegates to
    ``fstar.dispatch.DispatchService.harvest``, which owns dispatch identity,
    input-baseline, scope, replay, and lease verification and the evidence
    record. No hook bypass of the dispatch verification is possible, and no
    result can be double-recorded across the host event and the CLI harvest
    (the harvested-dispatch marker is task-persisted).
    Never writes acceptance: worker done is harvest completion, not acceptance
    (parent design §3.7).
    """
    result = result or {}
    status = result.get("status")
    if status not in RESULT_STATUSES:
        raise DomainError("invalid_result_status", "Dispatch result status must be done/failed/cancelled", {"status": status})
    dispatch_id = result.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        raise DomainError("invalid_result", "Dispatch result requires a dispatch_id")

    from ..dispatch import validate_payload as _validate_dispatch_payload

    located = inject.locate(start, user_root=user_root, runtime_root=runtime_root)
    store = located["store"]
    if store is None:
        if passive:
            # No project: nothing to recover into.
            return {"status": status, "dispatch_id": dispatch_id, "recorded": False,
                    "skipped": "no_project_or_task", "next": None}
        raise DomainError("project_not_initialized", "No initialized fstar project found for worker-result recovery")
    service = _service_for(store, clock)
    task_ref = _result_ref(result)
    if not task_ref:
        session_id = result.get("session_id")
        current = service.current(session_id) if session_id else {"current": None}
        if current.get("current"):
            task_ref = current["current"]["id"]
    if not task_ref:
        if passive:
            return {"status": status, "dispatch_id": dispatch_id, "recorded": False,
                    "skipped": "no_project_or_task", "next": None}
        raise DomainError("task_required", "worker-result requires a task reference or an active session pointer")
    try:
        task = store.read(task_ref)
    except DomainError:
        if passive:
            return {"status": status, "dispatch_id": dispatch_id, "recorded": False,
                    "skipped": "task_not_found", "next": None}
        raise

    if payload is None:
        # The dispatch payload is required: the dispatch protocol owns
        # identity/baseline/scope verification and cannot be reconstructed
        # from a worker's self-report (the result's role/baseline are
        # user-supplied payload and must not choose an unregistered worker
        # identity or bypass scope constraints).
        if passive:
            return {"status": status, "dispatch_id": dispatch_id, "recorded": False,
                    "skipped": "dispatch_payload_required",
                    "next": "Recovery boundary must supply the registered payload (fstar dispatch harvest --result FILE --payload FILE)"}
        raise DomainError("payload_required", "worker-result recovery requires the registered dispatch payload; use fstar dispatch harvest", status=3)
    _validate_dispatch_payload(payload)
    if payload.get("task_ref") != "session-only" and payload.get("task_ref") != task.get("id") and payload.get("task_ref") != task.get("name"):
        raise DomainError("task_ref_mismatch", "Dispatch payload does not match the task this result is being recovered into", {"payload": payload.get("task_ref"), "task": task.get("id")}, status=4)
    lease_token = result.get("lease_token")
    if not lease_token:
        if passive:
            return {"status": status, "dispatch_id": dispatch_id, "recorded": False,
                    "skipped": "no_lease_token", "next": None}
        raise DomainError("invalid_lease", "Harvesting a result requires the current coordinator lease token", status=4)
    from ..dispatch import DispatchService
    dispatch_service = DispatchService(store, clock=clock or _clock, task_service=service)
    if status == "cancelled":
        # Normalize to the protocol's terminal status vocabulary; the harvest
        # path records the terminal event without releasing the coordinator
        # lease (siblings may still be running).
        result = dict(result)
        result["status"] = "cancelled"
    outcome = dispatch_service.harvest(result, payload, lease_token=lease_token)
    outcome["acceptance_written"] = False
    if outcome.get("recorded"):
        outcome["lease_renewed"] = True
        outcome["next"] = "dispatch independent check (worker done is not acceptance)"
    elif outcome.get("status") in ("failed", "cancelled"):
        outcome["lease_released"] = False
        outcome["next"] = _WORKER_RESULT_NEXT[outcome["status"]]
    return outcome


_WORKER_RESULT_NEXT = {
    "failed": "route to fstar-debug (at most one automatic retry belongs to runtime-dispatch)",
    "cancelled": "check change propagation at the next checkpoint before redispatch",
    "blocked": "report the blocker to the coordinator; environment blocking is not retried",
}


# ---------------------------------------------------------------------------
# doc-change
# ---------------------------------------------------------------------------

def _doc_relative(payload: dict, file_path: Optional[str]) -> Optional[str]:
    raw = file_path or _payload_str(payload, "file_path", "filePath", "path", "file")
    if not raw:
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, dict):
            raw = _payload_str(tool_input, "file_path", "filePath", "path", "file")
    return raw


def _is_task_doc(project_root: Path, relative: str) -> Optional[Path]:
    """Return the owning task dir for a ``.fstar/tasks/**/doc/*.md`` path."""
    candidate = Path(relative)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(project_root.resolve())
        except (ValueError, OSError):
            return None
    parts = candidate.parts
    if ".." in parts or len(parts) < 5:
        return None
    if parts[0] != ".fstar" or parts[1] != "tasks":
        return None
    if not parts[-1].endswith(".md"):
        return None
    # The path must be <task dir>/doc/<file>.md; the task dir is the parent
    # of that doc directory (works for nested subtasks too).
    if parts[-2] != "doc":
        return None
    task_dir = project_root.joinpath(*parts[:-2])
    if not (task_dir / "task.json").is_file():
        return None
    return task_dir


def doc_change(payload: Optional[dict] = None, *, file_path: Optional[str] = None,
               start: Optional[Path] = None, user_root: Optional[Path] = None,
               runtime_root: Optional[Path] = None,
               clock: Optional[Callable[[], str]] = None, passive: bool = True) -> dict:
    """Idempotent bookkeeping after a doc/*.md edit.

    Only current-task doc/*.md paths are processed; everything else is a
    silent skip. Fingerprints are recomputed via core EvidenceService and
    compared with existing evidence; unchanged content produces zero writes.
    Changed content calls core invalidate (stale evidence + event + completed
    rollback semantics live in core) and emits one change-propagation line.
    No tests, no reports, no recursive derived-file handling.
    """
    payload = payload or {}
    relative = _doc_relative(payload, file_path)
    located = inject.locate(start, user_root=user_root, runtime_root=runtime_root)
    project_root = located["project_root"]
    if relative is None or project_root is None:
        if passive:
            return {"processed": False, "skipped": "no_file_or_project", "writes": 0}
        raise DomainError("file_required", "doc-change requires a changed file path")
    normalized = str(Path(relative).as_posix()) if not Path(relative).is_absolute() else relative
    task_dir = _is_task_doc(project_root, normalized)
    if task_dir is None:
        # Unrelated file: silent skip, no output noise.
        return {"processed": False, "skipped": "not_a_task_doc", "writes": 0}
    store = located["store"]
    service = _service_for(store, clock)
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        if passive:
            return {"processed": False, "skipped": "no_task_json", "writes": 0}
        raise DomainError("task_not_found", "doc-change target has no task.json", {"path": normalized})
    try:
        task_ref = str(task_dir.relative_to(store.tasks_root))
        task = store.read(task_ref)
    except (DomainError, ValueError):
        if passive:
            return {"processed": False, "skipped": "unreadable_task", "writes": 0}
        raise

    artifact = str(Path(normalized).as_posix())
    if Path(artifact).is_absolute():
        try:
            artifact = str(Path(artifact).resolve().relative_to(project_root.resolve()).as_posix())
        except (ValueError, OSError):
            return {"processed": False, "skipped": "outside_project", "writes": 0}

    # Idempotence: compare the current file digest against what existing
    # evidence already recorded. Unchanged content means zero writes.
    try:
        current_digest = file_digest(project_root / artifact)
    except OSError:
        if passive:
            return {"processed": False, "skipped": "artifact_missing", "writes": 0}
        raise DomainError("artifact_missing", "Changed doc file does not exist", {"artifact": artifact})
    recorded_digests = set()
    for evidence in task.get("evidence", []):
        if evidence.get("state") != "valid":
            continue
        for group in evidence.get("validates", []):
            if group.get("artifact") == artifact:
                for entry in group.get("items", []):
                    if isinstance(entry.get("sha256"), str):
                        recorded_digests.add(entry["sha256"])
    if current_digest in recorded_digests:
        return {"processed": True, "changed": False, "writes": 0,
                "artifact": artifact, "sha256": current_digest,
                "change_message": None}

    # Changed (or never recorded): core invalidate handles stale evidence,
    # the event, and completed->in_progress rollback in one transaction.
    try:
        outcome = service.evidence.invalidate(task_ref, file=artifact,
                                              actor={"role": "agent", "id": "fstar-hook-doc-change", "type": "hook"})
    except DomainError as exc:
        if exc.code == "lease_conflict" and passive:
            # An active writer owns the task right now; the core
            # read/recovery boundary recalculates on their release. Not an
            # error for passive bookkeeping.
            return {"processed": False, "skipped": "active_lease", "writes": 0}
        raise
    invalidated = outcome.get("invalidated", [])
    if not invalidated:
        # Nothing valid referenced this change (already stale, or no evidence
        # at all): idempotent no-op with zero writes and no noise.
        return {"processed": True, "changed": False, "writes": 0,
                "artifact": artifact, "sha256": current_digest,
                "invalidated": [], "change_message": None}
    # Canonical fstar.change.v1 message owned by runtime-dispatch; the affected
    # artifact/plan-item data is preserved. When the plan-item mapping for the
    # artifact is not established, the affected plan items are conservatively
    # unknown rather than claimed empty (an empty list would read "affects
    # nothing").
    mappings = task.get("meta", {}).get("templates", {}).get("artifact_map", {})
    mapped_item_ids = sorted(mappings.get(artifact, {})) if isinstance(mappings.get(artifact, {}), dict) else []
    if mapped_item_ids:
        affected = {"plan_item_ids": mapped_item_ids,
                     "artifact_items": [{"artifact": artifact, "items": [{"id": item_id, "sha256": current_digest} for item_id in mapped_item_ids]}]}
        old_fingerprints = {item_id: "recorded (now stale)" for item_id in mapped_item_ids}
        new_fingerprints = {item_id: current_digest for item_id in mapped_item_ids}
    else:
        # Conservative fallback: the artifact-level change is known; the
        # per-item breakdown is explicitly unknown, never silently empty.
        affected = {"plan_item_ids": [], "artifact_items": [{"artifact": artifact, "items": [{"id": "<unknown>", "sha256": current_digest}]}],
                    "unknown_plan_items": True}
        old_fingerprints = {artifact: "recorded (now stale)"}
        new_fingerprints = {artifact: current_digest}
    change_message = {
        "schema": "fstar.change.v1",
        "change_id": "doc-change:%s:%s" % (artifact, current_digest[:12]),
        "source": "file",
        "origin": artifact,
        "affected": affected,
        "old_fingerprints": old_fingerprints,
        "new_fingerprints": new_fingerprints,
        "action": "pause_and_redispatch",
        "affected_evidence": invalidated,
    }
    return {"processed": True, "changed": True, "writes": 1,
            "artifact": artifact, "sha256": current_digest,
            "invalidated": invalidated, "change_message": change_message,
            "hint": "doc changed: %s (sha256=%s); affected evidence: %s" % (
                artifact, current_digest[:12], ", ".join(invalidated))}


# ---------------------------------------------------------------------------
# CLI registration (register_commands + _fstar_module_handler convention)
# ---------------------------------------------------------------------------

def _json_file(path: Optional[str], label: str) -> dict:
    if not path:
        raise DomainError("file_required", "%s file is required" % label)
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError("invalid_json_file", "Cannot read %s file" % label, {"path": path, "reason": str(exc)})
    if not isinstance(value, dict):
        raise DomainError("invalid_json_file", "%s file must contain an object" % label)
    return value


def _roots(args):
    start = Path(args.project).expanduser().resolve() if args.project else None
    user_root = Path(args.user_data_root).expanduser().resolve() if args.user_data_root else None
    runtime_root = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else None
    return start, user_root, runtime_root


def _handle_session_context(args):
    start, user_root, runtime_root = _roots(args)
    payload = _json_file(args.payload, "payload") if args.payload else {}
    if args.extension:
        payload = dict(payload, extensions=_extension_entries(args))
    result = session_context(payload, start=start, user_root=user_root, runtime_root=runtime_root, as_json=args.json)
    if args.json:
        return result
    return {"text": result["text"]}


def _extension_entries(args) -> list:
    from ..dispatch import _require_list_or_json_entry
    return [_require_list_or_json_entry(entry, "extension") for entry in (args.extension or [])]


def _handle_worker_context(args):
    start, user_root, runtime_root = _roots(args)
    payload = _json_file(args.payload, "payload") if args.payload else {}
    if args.extension:
        payload = dict(payload, extensions=_extension_entries(args))
    result = worker_context(payload, role=args.role, task_ref=args.task, start=start,
                            user_root=user_root, runtime_root=runtime_root, as_json=args.json)
    if args.json:
        return result
    return {"text": result["text"]}


def _handle_worker_result(args):
    start, user_root, runtime_root = _roots(args)
    result = _json_file(args.result, "result") if args.result else {}
    payload = _json_file(args.payload, "dispatch payload") if args.payload else None
    return worker_result(result, payload=payload, start=start, user_root=user_root,
                         runtime_root=runtime_root, passive=False)


def _handle_doc_change(args):
    start, user_root, runtime_root = _roots(args)
    payload = _json_file(args.payload, "payload") if args.payload else {}
    return doc_change(payload, file_path=args.file, start=start, user_root=user_root, runtime_root=runtime_root, passive=False)


def _handle_plan(args):
    return registration.plan(args.host)


_HANDLERS = {
    "session-context": _handle_session_context,
    "worker-context": _handle_worker_context,
    "worker-result": _handle_worker_result,
    "doc-change": _handle_doc_change,
    "plan": _handle_plan,
}


def _handle_hook(args):
    handler = _HANDLERS.get(getattr(args, "hook_command", None))
    if handler is None:
        raise DomainError("unknown_hook", "Unknown hook subcommand", {"command": getattr(args, "hook_command", None)})
    return handler(args)


def register_commands(subparsers) -> None:
    """Register the ``fstar hook`` command family.

    Follows the optional-module convention: the handler attaches to the
    root-level ``hook`` parser via parser.set_defaults(
    _fstar_module_handler=...) so it runs before core service wiring and
    works in not-yet-initialized directories.
    """
    hook = subparsers.add_parser("hook")
    hook.set_defaults(_fstar_module_handler=_handle_hook)
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)

    session = hook_sub.add_parser("session-context")
    session.add_argument("--payload")
    session.add_argument("--extension", action="append", default=[])

    worker = hook_sub.add_parser("worker-context")
    worker.add_argument("--role", choices=sorted(inject.ROLES))
    worker.add_argument("task", nargs="?")
    worker.add_argument("--payload")
    worker.add_argument("--extension", action="append", default=[])

    result = hook_sub.add_parser("worker-result")
    result.add_argument("--result")
    result.add_argument("--payload")

    doc = hook_sub.add_parser("doc-change")
    doc.add_argument("--file")
    doc.add_argument("--payload")

    plan = hook_sub.add_parser("plan")
    plan.add_argument("--host", choices=("claude", "codex"), required=True)


def run_hook(name: str, payload: Optional[dict] = None, **kwargs) -> dict:
    """Programmatic entry for boundary fallback callers (runtime-dispatch).

    This is the same code path the CLI handlers use; host events and boundary
    fallbacks cannot diverge.
    """
    if name == "session-context":
        return session_context(payload, **kwargs)
    if name == "worker-context":
        return worker_context(payload, **kwargs)
    if name == "worker-result":
        return worker_result(payload, **kwargs)
    if name == "doc-change":
        return doc_change(payload, **kwargs)
    raise DomainError("unknown_hook", "Unknown hook name", {"name": name, "hooks": list(HOOK_NAMES)})
