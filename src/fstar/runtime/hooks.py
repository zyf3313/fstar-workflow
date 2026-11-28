"""The four semantic hooks and their host event mapping.

Semantic hooks (exactly four; no turn-context, no fifth hook, no custom hook
entry points):

- session-context: session start/clear/compact equivalent — inject routing
  full text, project/user indexes, current-task summary (read-only).
  No archive patrol and no writes.
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

HOOK_NAMES = ("session-context", "worker-context", "worker-result", "doc-change", "prompt-context")
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
        "prompt-context": {
            "events": ["UserPromptSubmit"],
            "matchers": [],
            "payload_keys": ["session_id", "cwd", "prompt", "hook_event_name"],
            "verified": True,
            "to_verify": ["prompt field name is adapter-level; state selection only needs session_id"],
            "fallback": "fstar hook prompt-context invoked manually",
        },
    },
    "codex": {
        "session-context": {
            "events": ["SessionStart"],
            "matchers": [],
            "payload_keys": ["session_id", "cwd", "hook_event_name"],
            "verified": True,
            "to_verify": [],
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
        "prompt-context": {
            "events": ["UserPromptSubmit"],
            "matchers": [],
            "payload_keys": ["session_id", "cwd", "prompt", "hook_event_name"],
            "verified": True,
            "to_verify": [],
            "fallback": "fstar hook prompt-context invoked manually",
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

def _git_worktree_root(start: Optional[Path]) -> Optional[Path]:
    """Nearest ancestor containing ``.git`` (worktree file or directory).

    Read-only filesystem walk with no git subprocess and no depth cap issue
    beyond the filesystem root; ``.git`` is checked as dir OR file (linked
    worktrees keep a ``.git`` file pointing at the real gitdir).
    """
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


INIT_PROMPT = ("This directory is inside a git project but is not yet an initialized fstar "
               "project. Ask the user once whether to run the fstar-init flow now "
               "(explore → dimension topics → detail skeletons → fstar init --context). "
               "Do not auto-execute the init; if the user declines, do not ask again this session.")

REPLAN_HINT = ("This task was replanned and the following planning documents were produced "
               "BEFORE the replan: %s. Before any implement dispatch, reconcile them against "
               "the new clarification: update each via fstar-plan storage or "
               "re-confirm it explicitly as still valid; never dispatch on unreviewed "
               "pre-replan conclusions. The replan event records the baseline git commit.")


def _replan_revisit(service, task_ref: str) -> Optional[dict]:
    """Return the task's pending replan-revisit info, or None when absent."""
    try:
        task = service.store.read(task_ref)
    except Exception:
        return None
    replan = (task.get("meta") or {}).get("replan")
    if not isinstance(replan, dict) or not replan.get("docs_to_revisit"):
        return None
    return {"at": replan.get("at"), "reason": replan.get("reason"),
            "docs_to_revisit": replan.get("docs_to_revisit"),
            "baseline_commit": replan.get("baseline_commit")}


def _rejected_ledger_hint(project_root: Optional[Path]) -> Optional[str]:
    """One index line for the rejected-proposals ledger, or None.

    The ledger lives at .fstar/knowledge/references/rejected.md (the normal
    knowledge category for project reference material, written only through
    fstar-learn). Only the hint line is injected; the body is read on demand.
    """
    if project_root is None:
        return None
    # The ledger lives in the project data root, which is <repo>/.fstar for
    # project-shared/project-local and the pointer target for user-directory.
    data_root = inject._project_data_root(project_root)
    path = data_root / "knowledge" / "references" / "rejected.md"
    # Same alias/escape rejection as index injection: a symlinked ledger must
    # not influence the session, even though only the count is injected.
    if not inject._safe_context_path(data_root, path) or not path.is_file():
        return None
    try:
        entries = [line for line in path.read_text(encoding="utf-8").splitlines()
                   if line.startswith("## ")]
    except OSError:
        return None
    return ("Rejected proposals: %d entries at .fstar/knowledge/references/rejected.md — "
            "read it before proposing an approach; a hit means do not re-propose." % len(entries))


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
    context = {}
    persistent_context = False

    task_summary = None
    learn_hint = ("When you identify a durable learning candidate, follow the background "
                  "fstar-learn role routing; a candidate is not permission to write.")
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
                    "replan": _replan_revisit(service, task["id"]),
                }
            except DomainError:
                # A stale pointer or inconsistent tree is not session-start
                # noise; the explicit continue command reports it.
                task_summary = None
                context = {}

    if not persistent_context:
        # A-009 dual channel: payload extensions first; when the host event
        # payload carries no records, read the session grants store written
        # by `fstar extension enable --session <id>` for this session.
        session_records = payload.get("extensions")
        if not session_records and session_id and project_root is not None:
            session_records = located["store"].read_session_grants(session_id)
        context = grants(session_records or [])

    # Indexes are read-only context: inject them by default so user-level rules
    # and project knowledge stay visible without an extension grant. Writing to
    # these surfaces still requires project-governance and explicit confirmation.
    inputs.extend(inject.index_inputs(project_root, user))
    knowledge_source = None
    if project_root is not None:
        store = located["store"]
        try:
            index_path = store.project_file(".fstar/index.md")
            knowledge_source = {"path": str(index_path),
                                "kind": "checkout" if index_path.parent == project_root / ".fstar" else "shared_data"}
        except DomainError as exc:
            if exc.code != "unsafe_evidence_path":
                raise
            knowledge_source = {"path": None, "kind": "unsafe"}
    # B-10: enforced user rules load in full (index lines never substitute the
    # source body); they ride under the same budgets as every other input.
    enforced_rules = inject.enforced_rule_inputs(user)
    inputs.extend(enforced_rules)
    rejected_hint = _rejected_ledger_hint(project_root)

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
        result["learn_hint"] = learn_hint
        result["rejected_ledger"] = rejected_hint
        result["enforced_rule_count"] = len(enforced_rules)
        result["knowledge_source"] = knowledge_source
        return result
    lines = [inject.render("fstar session context", inputs, budgets, footer=grant_text)]
    if knowledge_source:
        lines.append("Project knowledge source: %s (%s)" % (knowledge_source["path"], knowledge_source["kind"]))
    if rejected_hint:
        # One index line, not the full body: the ledger grows unboundedly and
        # full-body injection would inflate every session. The routing rule
        # makes the agent read the file before proposing approaches.
        lines.append("## Rejected proposals ledger")
        lines.append("")
        lines.append(rejected_hint)
        lines.append("")
    if task_summary is not None:
        lines.append("## Current task")
        lines.append("")
        lines.append("- %s (%s): phase=%s, blocked=%s, lease=%s, awaiting_acceptance=%s" % (
            task_summary["name"], task_summary["task_id"], task_summary["phase"],
            "yes" if task_summary["blocked"] else "no",
            "yes" if task_summary["lease"] else "no",
            "yes" if task_summary["awaiting_acceptance"] else "no"))
        lines.append("")
        replan = task_summary.get("replan")
        if replan:
            lines.append(REPLAN_HINT % ", ".join(replan.get("docs_to_revisit", [])))
            lines.append("")
    elif project_root is None:
        lines.append("No initialized fstar project found; task bookkeeping skipped (this is normal outside an initialized project).")
        lines.append("")
        if _git_worktree_root(start) is not None:
            # Read-only prompt injection: the hook never runs init itself; the
            # session agent asks the user once and never nags after refusal.
            lines.append(INIT_PROMPT)
            lines.append("")
    lines.append(learn_hint)
    lines.extend(_migration_hint(located, session_id, runtime_root=runtime_root))
    return {"text": "\n".join(lines), "session_id": session_id,
            "initialized": project_root is not None, "current_task": task_summary,
            "enforced_rule_count": len(enforced_rules)}


def _migration_hint(located: dict, session_id: Optional[str], *,
                    runtime_root: Optional[Path] = None) -> List[str]:
    """Read-only global-vs-legacy resource note (D-003).

    This path performs ZERO writes: not to the project, tasks, resources, or
    the runtime root. It reads the shared inspection result and the already
    recorded reminder state (delivery/deferral) and reports what the caller
    should know.

    Showing the migration question is a separate explicit operation
    (``fstar resource-remind``): it atomically checks and records the
    delivery for (project identity, target resource version, session id) and
    returns whether the question may be shown. The hook never records a
    decision, so it never claims it saved one.
    """
    project_root = located.get("project_root")
    user = located.get("user_root")
    if project_root is None:
        return []
    if runtime_root is None:
        runtime_root = user / "runtime"
    try:
        from ..global_resources import (inspect_project, delivered_this_session,
                                        is_deferred, _project_identity)
        from ..installer import load_bundle_manifest, default_host_root
        report = inspect_project(project_root=project_root, user_root=user,
                                 host_roots={"claude": default_host_root(user)})
        target = str(load_bundle_manifest().get("resource_version", ""))
        identity = _project_identity(project_root, user)
        deferred = is_deferred(runtime_root=runtime_root, project_identity=identity,
                                target_version=target)
        already = delivered_this_session(runtime_root=runtime_root,
                                         project_identity=identity,
                                         target_version=target, session_id=session_id or "")
    except Exception:
        # The session hook must not fail because of the resource check.
        return []
    legacy = report.get("legacy", {})
    if not legacy.get("count"):
        return []
    health = report.get("global_health", {})
    lines = ["## fstar resources", ""]
    if not health.get("usable"):
        if health.get("reason") == "not_installed":
            lines.append("This project carries %d per-project fstar resource item(s), but no "
                         "fstar-owned global entry is installed for %s. Install the global "
                         "entry first (`fstar install --host claude`); migrating this project "
                         "is only safe once the shared global delivery is healthy."
                         % (legacy["count"], health.get("host_root", "the global host root")))
        else:
            lines.append("This project carries %d per-project fstar resource item(s) and the "
                         "global fstar entry is incomplete or modified (%d issue(s)); resolve "
                         "it (fstar doctor) before migrating this project."
                         % (legacy["count"], len(health.get("problems") or [])))
        lines.append("")
        return lines
    if deferred or already:
        # The user deferred this project for this target version, or the
        # question was already shown and claimed in this session: stay quiet
        # (no section at all, so nothing is injected into the session).
        return []
    lines.append("This project carries %d per-project fstar resource item(s) (copies/pin) while "
                 "the shared global delivery (version %s) is healthy. Migrating (one confirmed "
                 "`fstar resource-migrate`) backs the copies up, removes them, keeps tasks/specs/"
                 "identity, and lets one global update serve every migrated project; modified "
                 "or unowned files are kept and reported. Ask the user at most once per session: "
                 "run `fstar resource-remind` first (it decides and records whether the question "
                 "may be shown), then `fstar resource-migrate --confirmation FILE` on approval "
                 "or `fstar resource-defer` to postpone."
                 % (legacy["count"], report.get("global_target_version", "?")))
    lines.append("")
    return lines


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

    The governed members live in the project's DATA root. In project-shared
    and project-local mode that is ``<repo>/.fstar``; in user-directory mode
    it lives under the user root, so the data root is consulted too.
    """
    for root in (project_root, inject._project_data_root(project_root)):
        parts = _resolved_relative(path, root)
        if len(parts) >= 2 and parts[0].casefold() == ".fstar":
            member = parts[1].casefold()
            if member in GOVERNED_MEMBERS:
                return member
        elif root is not project_root and len(parts) >= 1 and parts[0].casefold() in GOVERNED_MEMBERS:
            # user-directory layout: the data root holds "specs", "knowledge"
            # directly, without the ".fstar" segment.
            member = parts[0].casefold()
            if member in GOVERNED_MEMBERS:
                return member
    return None


def _planning_member(project_root: Path, path: Path) -> Optional[str]:
    """Classify planning artifacts in active tasks and archived task trees.

    The task and archive trees live in the project DATA root. In
    project-shared/local mode that is ``<repo>/.fstar``, so the resolved
    parts start with ``.fstar/tasks`` or ``.fstar/archive``; in
    user-directory mode the data root holds ``tasks``/``archive`` directly.
    """
    for root in (project_root, inject._project_data_root(project_root)):
        parts = tuple(part.casefold() for part in _resolved_relative(path, root))
        if len(parts) < 4:
            continue
        if parts[:2] == (".fstar", "tasks") or parts[:2] == (".fstar", "archive"):
            tail = parts[2:]
        elif parts[0] in ("tasks", "archive"):
            # user-directory layout: the data root holds "tasks"/"archive"
            # directly, without the ".fstar" segment.
            tail = parts[1:]
        else:
            continue
        for artifact, member in PLANNING_MEMBERS.items():
            suffix = tuple(artifact.split("/"))
            if len(tail) > len(suffix) and tail[-len(suffix):] == suffix:
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
        raise DomainError("role_required", "worker-context requires a supported role", {"roles": sorted(inject.ROLES)})
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
    try:
        card = inject.role_card(role, root)
    except (OSError, UnicodeError):
        card = None
    if card is None:
        raise DomainError(
            "role_card_unavailable",
            "The selected resource version does not provide a readable role card; "
            "the worker context is unavailable. Use an installed version that provides it.",
            {"role": role, "path": str(root / "agents" / ("fstar-%s.md" % role))}, status=3)
    inputs.append(card)
    task_line = inject.session_only_reference()
    context = {}
    task_summary = None
    footer_parent_lines: List[str] = []
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
            artifact = store.identity_path(task_dir / "plan.md")
            snap = (inject.item_snapshots(service.evidence, task_ref, artifact, plan_item_ids)
                    if includes(context, "planning-review", "plan") else None)
            task_summary = {"task_id": task["id"], "name": task["name"], "phase": task["phase"],
                            "plan_item_ids": plan_item_ids, "item_snapshot": snap}
            # P-003 (antigravity-adoption design §3.2): tasks carrying an
            # origin inject the parent requirement task's design/walkthrough
            # docs. Tasks without origin skip this path entirely (A-006).
            parent_report = inject.parent_context_inputs(store, task, budgets)
            if parent_report is not None:
                inputs.extend(parent_report["inputs"])
                report = parent_report["report"]
                task_summary["parent_context"] = report
                if report["status"] == "missing":
                    footer_parent = ("Parent context unavailable: %s (origin %s)" % (
                        report["reason"], report["origin"]["task_id"]))
                elif report["status"] == "partial":
                    footer_parent = ("Parent context partial: %s deferred under the injection budget "
                                     "(see Unloaded inputs); read the parent documents yourself before executing" % (
                                         ", ".join(sorted(entry["kind"] for entry in report["deferred"]))))
                else:
                    footer_parent = ("Parent context loaded from %s (%s)" % (
                        report.get("parent_path"), ", ".join(sorted(entry["kind"] for entry in report["loaded"]))
                        or "no documents"))
                footer_parent_lines.append(footer_parent)

    if not task_ref or task_ref == "session-only":
        # A-009 dual channel: payload extensions first; the host dispatch
        # payload carries them when the host preserves the extensions
        # array. When it strips them, read the session grants store written
        # by `fstar extension enable --session <id>` (same records, payload
        # first, readback fallback).
        session_records = payload.get("extensions")
        if not session_records and session_id and project_root is not None:
            session_records = located["store"].read_session_grants(session_id)
        context = grants(session_records or [])
    role_member = {"research": ("multi-agent", "research"),
                   "editor": ("planning-review", "editor"),
                   "steward": ("multi-agent", "steward")}.get(role)
    if role_member and not includes(context, *role_member):
        raise DomainError("extension_not_authorized", "Worker role requires an included extension member",
                          {"package": role_member[0], "member": role_member[1]}, status=3)

    footer = ["%s" % task_line, "Extension members in this context: %s" % json.dumps(
        {key: sorted(value) for key, value in context.items()}, sort_keys=True)]
    footer.extend(footer_parent_lines)
    footer.append("Role: %s. Read complete applicable context; summaries do not replace source bodies." % role)
    footer.append("If any input is listed under 'Unloaded inputs', you MUST read it in full before executing.")
    # S-5: the dispatch's selected skills ride along so the worker actually
    # sees them. Optional; old payloads have none. The worker may supplement
    # from its own exposed catalog and reports usage in its result.
    selected = payload.get("selected_skills")
    if isinstance(selected, list) and selected:
        lines = []
        for entry in selected:
            if not isinstance(entry, dict) or not entry.get("skill"):
                continue
            lines.append("  - %s (source: %s; reason: %s)" % (
                entry.get("skill"), entry.get("source") or "agent-selected",
                entry.get("reason") or ""))
        if lines:
            footer.append("selected_skills (invoke the applicable ones; selection is not execution; "
                          "no recursive fstar action; report skill_usage):")
            footer.extend(lines)

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
    """Return the owning task dir for a ``.fstar/tasks/**/doc/*.md`` path.

    The task tree lives in the project's data root: inside the repository in
    project-shared/local mode, under the user root in user-directory mode.
    An absolute path is resolved against both.
    """
    candidate = Path(relative)
    roots = [project_root, inject._project_data_root(project_root)]
    if candidate.is_absolute():
        resolved = None
        for root in roots:
            try:
                resolved = candidate.resolve().relative_to(root.resolve())
                break
            except (ValueError, OSError):
                continue
        if resolved is None:
            return None
        candidate = resolved
    parts = candidate.parts
    if ".." in parts or len(parts) < 4:
        return None
    data_root = inject._project_data_root(project_root)
    if parts[0] == ".fstar":
        if len(parts) < 5 or parts[1] != "tasks":
            return None
        tail = parts[1:]
    elif parts[0] == "tasks":
        # user-directory layout: the path is already relative to the data root
        tail = parts
    else:
        return None
    if not parts[-1].endswith(".md"):
        return None
    # The path must be <task dir>/doc/<file>.md; the task dir is the parent
    # of that doc directory (works for nested subtasks too).
    if parts[-2] != "doc":
        return None
    task_dir = data_root.joinpath(*tail[:-2])
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
        resolved = None
        for root in (project_root, inject._project_data_root(project_root)):
            try:
                resolved = Path(artifact).resolve().relative_to(root.resolve())
                break
            except (ValueError, OSError):
                continue
        if resolved is None:
            return {"processed": False, "skipped": "outside_project", "writes": 0}
        artifact = str(resolved.as_posix())
        if not artifact.startswith(".fstar/"):
            # user-directory layout: the identity path keeps the ".fstar/" prefix
            artifact = ".fstar/" + artifact

    # Idempotence: compare the current file digest against what existing
    # evidence already recorded. Unchanged content means zero writes.
    try:
        current_digest = file_digest(store.project_file(artifact))
    except (OSError, DomainError):
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
# prompt-context
# ---------------------------------------------------------------------------

PROMPT_STATE_TAG = re.compile(r"\[prompt-state:(?P<tag>[a-z_]+)\](?P<body>.*?)\[/prompt-state:\1\]",
                              re.DOTALL)
PROMPT_STATE_NAMES = ("no_task", "planning", "in_progress", "awaiting_acceptance")
PROMPT_STATE_DEGRADED = ("fstar: prompt-states unavailable; make a workflow decision "
                         "before acting and refer to routing.")
# S-5: the shared lightweight skill-intent reminder. One short block for
# every state (including no_task); the per-state block above stays. When the
# reminder cannot be read it degrades to this single line, so the reminder
# never silently disappears when resources are missing.
SKILL_REMINDER_TAG = re.compile(r"^\[skill-reminder\]\s*$(?P<body>.*?)^\[/skill-reminder\]\s*$",
                                re.DOTALL | re.MULTILINE)
SKILL_REMINDER_DEGRADED = ("fstar: check the local skill catalog for an applicable skill "
                           "before acting (routing has the rules); no match is fine.")


def _prompt_state_name(service: TaskService, session_id: Optional[str]) -> str:
    """Derive the current prompt state from the session's current task."""
    current = service.current(session_id)
    task = current.get("current")
    if task is None:
        return "no_task"
    if task.get("meta", {}).get("disposition"):
        # Dropped/archived pointer: no active work in this session.
        return "no_task"
    phase = task.get("phase")
    if phase == "planning":
        return "planning"
    if phase == "in_progress":
        # The phase transition into awaiting_acceptance is explicit, so an
        # in-progress task stays "in_progress" even when a fresh final check
        # exists: the coordinator still has to make the transition.
        return "in_progress"
    if phase == "awaiting_acceptance":
        return "awaiting_acceptance"
    # completed (or any other phase) without recorded acceptance: the closest
    # actionable reminder is the acceptance boundary.
    return "awaiting_acceptance"


def _skill_reminder(root: Path) -> Optional[str]:
    """The shared skill-intent reminder from prompt-states.md, or its fixed
    degraded line when the tag/file is missing. Never a disk scan of skill
    directories; the reminder only points at routing's selection rules."""
    try:
        text = (root / "runtime" / "prompt-states.md").read_text(encoding="utf-8")
    except OSError:
        text = None
    if text is not None:
        match = SKILL_REMINDER_TAG.search(text)
        if match:
            return match.group("body").strip()
    return SKILL_REMINDER_DEGRADED


def prompt_context(payload: Optional[dict] = None, *, start: Optional[Path] = None,
                   user_root: Optional[Path] = None, runtime_root: Optional[Path] = None,
                   clock: Optional[Callable[[], str]] = None, passive: bool = True) -> dict:
    """Per-prompt breadcrumb injection (UserPromptSubmit). Read-only.

    Emits one short state-selected block from resources/runtime/prompt-states.md
    reminding the agent to make a workflow-size decision before acting. Outside
    an initialized project nothing is emitted (unlike session-context there is
    no routing full text here; the session-start hook already carried it). A
    missing resource or missing state tag degrades to one fixed line — the
    hook is never silent inside an initialized project.
    """
    payload = payload or {}
    session_id = _payload_str(payload, "session_id", "sessionId")
    located = inject.locate(start, user_root=user_root, runtime_root=runtime_root)
    project_root = located["project_root"]
    if project_root is None:
        # Outside an initialized project the previous behavior is preserved:
        # nothing is emitted (routing was injected at session start and no
        # task state exists; the skill reminder is a per-prompt project-state
        # feature). This path creates no project and writes nothing.
        return {"text": None, "initialized": False, "state": None,
                "degraded": False, "session_id": session_id}
    store = located["store"]
    service = _service_for(store, clock)
    state = _prompt_state_name(service, session_id)
    root = inject.resource_root(project_root, located["user_root"])
    body = None
    try:
        text = (root / "runtime" / "prompt-states.md").read_text(encoding="utf-8")
    except OSError:
        text = None
    if text is not None:
        for match in PROMPT_STATE_TAG.finditer(text):
            if match.group("tag") == state:
                body = match.group("body").strip()
                break
    reminder = _skill_reminder(root)
    if body is None:
        # Degraded single line, never silent (PRD acceptance condition). The
        # skill reminder still rides along in its own degraded form.
        return {"text": "\n".join([PROMPT_STATE_DEGRADED, "", reminder]),
                "initialized": True, "state": state,
                "degraded": True, "session_id": session_id,
                "skill_reminder": reminder}
    text_out = "\n".join([
        "fstar prompt state: %s" % state,
        "<prompt-state>",
        body,
        "</prompt-state>",
        "",
        "<skill-reminder>",
        reminder,
        "</skill-reminder>",
    ])
    # Task-level waiting/progress line from the optional collaboration fields
    # (design §4): the state block above carries the phase reminder; these
    # lines add why the task waits and where work stands. Read-only; absent
    # fields add nothing (old tasks stay valid).
    detail = _prompt_task_detail(service, session_id)
    if detail:
        text_out = "\n".join([text_out, "", detail])
    return {"text": text_out, "initialized": True, "state": state,
            "degraded": False, "session_id": session_id,
            "skill_reminder": reminder}


def _prompt_task_detail(service: TaskService, session_id: Optional[str]) -> Optional[str]:
    """Waiting/progress breadcrumbs from status/work_items (no tag, no file)."""
    current = service.current(session_id)
    task = current.get("current")
    if task is None or task.get("meta", {}).get("disposition"):
        return None
    lines = []
    status = task.get("status")
    if status in ("waiting_user", "waiting_external"):
        reason = (task.get("status_detail") or {}).get("reason") or ""
        if status == "waiting_user":
            lines.append("fstar: task is waiting for user input (%s); "
                         "gather the user's reply and resume work." % reason)
        else:
            lines.append("fstar: task is waiting for an external result (%s); "
                         "do not claim the result; verify timeliness when it arrives." % reason)
    active = [item for item in (task.get("work_items") or [])
              if isinstance(item, dict) and item.get("state") == "active"]
    if active:
        summary = active[0].get("summary") or active[0].get("id")
        others = len(active) - 1
        lines.append("fstar: work in progress: %s%s; update the work item "
                     "state in task.json when it settles." % (
                         summary, " (+%d more)" % others if others else ""))
    next_step = task.get("next_step")
    if isinstance(next_step, dict) and next_step.get("condition") and next_step.get("action"):
        lines.append("fstar: next step when %s: %s" % (
            next_step["condition"], next_step["action"]))
    return "\n".join(lines) or None


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


def _handle_prompt_context(args):
    start, user_root, runtime_root = _roots(args)
    payload = _json_file(args.payload, "payload") if args.payload else {}
    return prompt_context(payload, start=start, user_root=user_root, runtime_root=runtime_root)


def _handle_plan(args):
    return registration.plan(args.host)


_HANDLERS = {
    "session-context": _handle_session_context,
    "worker-context": _handle_worker_context,
    "worker-result": _handle_worker_result,
    "doc-change": _handle_doc_change,
    "prompt-context": _handle_prompt_context,
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

    prompt = hook_sub.add_parser("prompt-context")
    prompt.add_argument("--payload")

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
    if name == "prompt-context":
        return prompt_context(payload, **kwargs)
    raise DomainError("unknown_hook", "Unknown hook name", {"name": name, "hooks": list(HOOK_NAMES)})
