"""fstar dispatch protocol (fstar.dispatch.v1).

Protocol layer (pure data/validation, no IO), registration layer (thin,
injectable TaskService/EvidenceService), harvest layer (verify then record
through core EvidenceService), and the CLI adapter surface registered via
``register_commands`` / ``OPTIONAL_HANDLER_ATTR``.

The CLI only prepares, validates, and registers dispatch payloads. Actual
dispatch is performed by the host-native adapter (the main agent using the
host Agent tool); every command output states ``dispatch_mode: "adapter"``.
This module never imports host-specific code, so the protocol fields are
independent of the transport (AC-01). Role text and allowed_paths are
protocol constraints, not a security sandbox.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable, Optional, Sequence

from .evidence import EvidenceService, file_digest
from .models import DomainError
from .store import TaskStore
from .tasks import TaskService, make_event, utc_now

PAYLOAD_SCHEMA = "fstar.dispatch.v1"
RESULT_SCHEMA = "fstar.dispatch.result.v1"
CHANGE_SCHEMA = "fstar.change.v1"

ROLES = ("implement", "check", "research", "editor")
# "cancelled" is the interrupted-worker terminal status produced by interrupt
# and checkpoint stops; harvest records no evidence for it (parent design §3.8
# worker-result covers done/failed/cancelled recovery semantics).
STATUSES = ("done", "blocked", "failed", "cancelled")


def _terminal_next(status: str, role: str) -> str:
    if status == "failed":
        return "route to fstar-debug (at most one automatic retry)"
    if status == "cancelled":
        return "check change propagation at the next checkpoint before redispatch"
    if status == "blocked":
        return "report the blocker to the coordinator; environment blocking is not retried"
    return "check_dispatch" if role == "implement" else "coordinator_review"
CHANGE_SOURCES = ("conversation", "file")
CHANGE_ACTIONS = ("propagate", "pause_and_redispatch")
# Host capability tiers. Actual support is measured per host and recorded as
# to-verify facts in the task research notes; the protocol never assumes the
# highest tier is available.
CAPABILITY_TIERS = ("realtime-steer", "checkpoint-stop", "process-stop")
RETRY_POLICY = {"max_auto_retries": 1}

# Roles whose allowed_paths are constrained (editor: doc tree; research:
# research scope).


def _safe_relative(path: object, label: str) -> str:
    """Reject absolute paths and ``..`` segments using core's boundary rules."""
    if not isinstance(path, str) or not path or path.strip() != path:
        raise DomainError("unsafe_dispatch_path", "%s must be a non-empty project-relative path" % label, {"path": path})
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DomainError("unsafe_dispatch_path", "%s must be project-relative without traversal" % label, {"path": path})
    if "\x00" in path:
        raise DomainError("unsafe_dispatch_path", "%s contains a null byte" % label, {"path": path})
    return path


def _require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise DomainError("invalid_dispatch_payload", "%s must be an object" % label, {"field": label})
    return value


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise DomainError("invalid_dispatch_payload", "%s must be an array" % label, {"field": label})
    return value


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DomainError("invalid_dispatch_payload", "%s must be a non-empty string" % label, {"field": label})
    return value


def build_payload(*, role: str, task_ref: str, plan_item_ids: Sequence[str],
                  allowed_paths: Sequence[str], baseline: dict,
                  input_versions: Optional[list] = None,
                  read_context: Optional[list] = None,
                  required_validations: Optional[Sequence[str]] = None,
                  return_conditions: Optional[dict] = None,
                  item_ids: Optional[Sequence[str]] = None,
                  baseline_sha256: Optional[str] = None,
                  prior_failure: Optional[dict] = None,
                  dispatch_id: Optional[str] = None,
                  extensions: Optional[list] = None) -> dict:
    """Build a ``fstar.dispatch.v1`` payload. Pure; no IO, no hashing."""
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "dispatch_id": dispatch_id or str(uuid.uuid4()),
        "task_ref": task_ref,
        "role": role,
        "plan_item_ids": list(plan_item_ids),
        "baseline": baseline,
        "input_versions": list(input_versions or []),
        "allowed_paths": list(allowed_paths),
        "read_context": list(read_context or []),
        "required_validations": list(required_validations or []),
        "return_conditions": return_conditions or {"done": "", "blocked": "", "failed": ""},
        "prompt_first_line": _prompt_first_line(task_ref),
    }
    if extensions is not None:
        payload["extensions"] = list(extensions)
    if item_ids is not None:
        payload["item_ids"] = list(item_ids)
    if baseline_sha256 is not None:
        payload["baseline_sha256"] = baseline_sha256
    if prior_failure is not None:
        payload["prior_failure"] = prior_failure
    validate_payload(payload)
    return payload


def _within_task_tree(task_ref: str, path: str) -> bool:
    """True when ``path`` lives inside the task's own tree.

    Works for nested subtask refs (``subtasks/child``) by comparing full path
    segments, not substring membership.
    """
    prefix = (".fstar", "tasks") + tuple(Path(task_ref).parts)
    parts = Path(path).parts
    return len(parts) > len(prefix) and parts[:len(prefix)] == prefix


def _editor_path_allowed(task_ref: str, path: str) -> bool:
    """Editor writes are limited to the specified doc files.

    Session-only: the authorized artifact doc root. Persistent task: the
    task's own doc tree under .fstar/tasks/<task path>/doc.
    """
    if task_ref == "session-only":
        return Path(path).parts[:1] == ("doc",)
    return _within_task_tree(task_ref, path) and Path(path).parts[-2:-1] == ("doc",)


def _research_path_allowed(task_ref: str, path: str) -> bool:
    """Research writes stay in the research scope; no production code."""
    if task_ref == "session-only":
        return Path(path).parts[:1] == ("research",)
    return _within_task_tree(task_ref, path) and "research" in Path(path).parts


def _prompt_first_line(task_ref: str) -> str:
    if task_ref == "session-only":
        return "Active task: session-only"
    return "Active task: %s" % _safe_relative(task_ref, "task_ref")


def validate_payload(payload: dict) -> dict:
    """Validate payload structure. Raises DomainError with a stable code."""
    payload = _require_dict(payload, "payload")
    if payload.get("schema") != PAYLOAD_SCHEMA:
        raise DomainError("invalid_dispatch_payload", "Unknown payload schema", {"schema": payload.get("schema")})
    missing = [key for key in ("dispatch_id", "task_ref", "role", "prompt_first_line") if not payload.get(key)]
    # baseline/allowed_paths must be PRESENT and well-typed; an empty scope
    # list or an empty baseline object is structurally valid (a research or
    # delivery-only dispatch can have nothing to write yet).
    missing.extend(key for key in ("baseline", "allowed_paths") if key not in payload)
    if missing:
        raise DomainError("invalid_dispatch_payload", "Payload is missing required fields", {"missing": missing})
    _require_str(payload["dispatch_id"], "dispatch_id")
    task_ref = _safe_relative(payload["task_ref"], "task_ref")
    if payload["role"] not in ROLES:
        raise DomainError("invalid_dispatch_payload", "Unknown dispatch role", {"role": payload["role"]})
    for key in ("plan_item_ids", "allowed_paths"):
        _require_list(payload.get(key), key)
    _require_list(payload.get("required_validations", []), "required_validations")
    for key in ("input_versions", "read_context"):
        _require_list(payload.get(key, []), key)
    for path in payload["allowed_paths"]:
        _safe_relative(path, "allowed_paths entry")
    for entry in payload.get("input_versions", []):
        entry = _require_dict(entry, "input_versions entry")
        _safe_relative(entry.get("path"), "input_versions path")
        _require_str(entry.get("sha256"), "input_versions sha256")
    for entry in payload.get("read_context", []):
        entry = _require_dict(entry, "read_context entry")
        _safe_relative(entry.get("path"), "read_context path")
        _require_str(entry.get("sha256"), "read_context sha256")
    _require_dict(payload.get("baseline"), "baseline")
    _require_dict(payload.get("return_conditions", {}), "return_conditions")
    # Prompt first line must stay consistent with task_ref: session-only must
    # not fabricate a task path, and a persistent task must state its path.
    expected = _prompt_first_line(task_ref)
    if payload["prompt_first_line"] != expected:
        raise DomainError("invalid_dispatch_payload", "prompt_first_line does not match task_ref", {"expected": expected, "actual": payload["prompt_first_line"]})
    if payload["role"] == "editor":
        item_ids = payload.get("item_ids")
        if not item_ids or not isinstance(item_ids, list):
            raise DomainError("invalid_dispatch_payload", "editor dispatch requires item_ids", {"field": "item_ids"})
        if not payload.get("baseline_sha256"):
            raise DomainError("invalid_dispatch_payload", "editor dispatch requires baseline_sha256", {"field": "baseline_sha256"})
        for path in payload["allowed_paths"]:
            if not _editor_path_allowed(task_ref, path):
                raise DomainError("invalid_dispatch_payload", "editor allowed_paths must stay inside the task doc tree", {"path": path})
    if payload["role"] == "research":
        for path in payload["allowed_paths"]:
            if not _research_path_allowed(task_ref, path):
                raise DomainError("invalid_dispatch_payload", "research allowed_paths must stay inside the research scope", {"path": path})
    if "prior_failure" in payload:
        failure = _require_dict(payload["prior_failure"], "prior_failure")
        _require_str(failure.get("reason"), "prior_failure reason")
        _require_str(failure.get("dispatch_id"), "prior_failure dispatch_id")
    return payload


def build_result(*, dispatch_id: str, role: str, status: str,
                 changed_paths: Optional[Sequence[str]] = None,
                 artifact_refs: Optional[list] = None,
                 validation_facts: Optional[list] = None,
                 blockers: Optional[list] = None,
                 input_baseline: Optional[dict] = None,
                 delivery_baseline: Optional[dict] = None) -> dict:
    result = {
        "schema": RESULT_SCHEMA,
        "dispatch_id": dispatch_id,
        "role": role,
        "status": status,
        "changed_paths": list(changed_paths or []),
        "artifact_refs": artifact_refs or [],
        "validation_facts": validation_facts or [],
        "blockers": blockers or [],
        "input_baseline": input_baseline or {},
        "delivery_baseline": delivery_baseline or {},
    }
    validate_result(result)
    return result


def validate_result(result: dict) -> dict:
    result = _require_dict(result, "result")
    if result.get("schema") != RESULT_SCHEMA:
        raise DomainError("invalid_dispatch_result", "Unknown result schema", {"schema": result.get("schema")})
    missing = [key for key in ("dispatch_id", "role", "status") if not result.get(key)]
    if missing:
        raise DomainError("invalid_dispatch_result", "Result is missing required fields", {"missing": missing})
    if result["role"] not in ROLES:
        raise DomainError("invalid_dispatch_result", "Unknown result role", {"role": result["role"]})
    if result["status"] not in STATUSES:
        raise DomainError("invalid_dispatch_result", "Unknown result status", {"status": result["status"]})
    for key in ("changed_paths", "artifact_refs", "validation_facts", "blockers"):
        _require_list(result.get(key), key)
    for path in result["changed_paths"]:
        _safe_relative(path, "changed_paths entry")
    for fact in result["validation_facts"]:
        fact = _require_dict(fact, "validation_facts entry")
        _require_str(fact.get("command"), "validation_facts command")
        _require_str(fact.get("result"), "validation_facts result")
    for key in ("input_baseline", "delivery_baseline"):
        _require_dict(result.get(key), key)
    if result.get("baseline_sha256") is not None and not isinstance(result.get("baseline_sha256"), str):
        raise DomainError("invalid_dispatch_result", "baseline_sha256 must be a string", {"field": "baseline_sha256"})
    return result


def build_change(*, source: str, origin: str, affected: Optional[dict] = None,
                 old_fingerprints: Optional[dict] = None,
                 new_fingerprints: Optional[dict] = None,
                 action: str = "pause_and_redispatch",
                 change_id: Optional[str] = None) -> dict:
    """Build a ``fstar.change.v1`` message. Pure; delivery is the adapter's job."""
    message = {
        "schema": CHANGE_SCHEMA,
        "change_id": change_id or str(uuid.uuid4()),
        "source": source,
        "origin": origin,
        "affected": affected or {"plan_item_ids": [], "artifact_items": []},
        "old_fingerprints": old_fingerprints or {},
        "new_fingerprints": new_fingerprints or {},
        "action": action,
    }
    validate_change(message)
    return message


def validate_change(message: dict) -> dict:
    message = _require_dict(message, "change message")
    if message.get("schema") != CHANGE_SCHEMA:
        raise DomainError("invalid_change_message", "Unknown change message schema", {"schema": message.get("schema")})
    for key in ("change_id", "source", "origin", "action"):
        if not message.get(key):
            raise DomainError("invalid_change_message", "Change message is missing required fields", {"missing": [key]})
    if message["source"] not in CHANGE_SOURCES:
        raise DomainError("invalid_change_message", "Unknown change source", {"source": message["source"]})
    if message["action"] not in CHANGE_ACTIONS:
        raise DomainError("invalid_change_message", "Unknown change action", {"action": message["action"]})
    _require_dict(message.get("affected"), "affected")
    _require_dict(message.get("old_fingerprints"), "old_fingerprints")
    _require_dict(message.get("new_fingerprints"), "new_fingerprints")
    return message


def propagation_decision(tier: str, change: dict) -> dict:
    """Decide the propagation action for a change message by host tier.

    The tier is a measured, to-verify fact supplied by the adapter; this
    function never assumes realtime steering is available.
    """
    validate_change(change)
    if tier not in CAPABILITY_TIERS:
        raise DomainError("unknown_capability_tier", "Unknown host capability tier", {"tier": tier})
    if tier == "realtime-steer":
        return {"tier": tier, "action": "steer", "change": change,
                "note": "Adapter must deliver the change message to the running worker and confirm acknowledgement before continuing."}
    if tier == "checkpoint-stop":
        return {"tier": tier, "action": "pause_and_redispatch", "change": change,
                "note": "Interrupt the affected scope; harvest at the checkpoint and redispatch under a new dispatch_id with the new baseline."}
    return {"tier": tier, "action": "stop_process", "change": change,
            "note": "Adapter stops the worker process; leftover artifacts are handled as read-only orphans."}


def parallel_groups(plan_items: Sequence[dict]) -> list:
    """Derive dependency- and write-safe parallel groups from plan items.

    Items in one group have their dependencies satisfied by earlier groups and
    pairwise disjoint allowed_paths/shared_resources. Priority only orders
    items inside a group; it never crosses dependencies (no scheduler).
    """
    by_id = {}
    for item in plan_items:
        item = _require_dict(item, "plan item")
        item_id = _require_str(item.get("id"), "plan item id")
        if item_id in by_id:
            raise DomainError("invalid_plan_items", "Duplicate plan item id", {"id": item_id})
        by_id[item_id] = item
    for item in by_id.values():
        for dependency in item.get("depends_on", []) or []:
            if dependency not in by_id:
                raise DomainError("invalid_plan_items", "Plan item depends on an unknown item", {"id": item["id"], "dependency": dependency})
    groups = []
    placed = set()
    remaining = sorted(by_id.values(), key=lambda x: str(x.get("priority", "P2")))
    while remaining:
        candidates = [item for item in remaining if set(item.get("depends_on", []) or []) <= placed]
        if not candidates:
            raise DomainError("invalid_plan_items", "Plan dependencies are cyclic", {"items": [item["id"] for item in remaining]})
        group = []
        claimed_paths = set()
        claimed_resources = set()
        for item in sorted(candidates, key=lambda x: str(x.get("priority", "P2"))):
            paths = {str(p) for p in item.get("allowed_paths", []) or []}
            resources = {str(r) for r in item.get("shared_resources", []) or []}
            if paths & claimed_paths or resources & claimed_resources:
                continue
            group.append(item["id"])
            claimed_paths |= paths
            claimed_resources |= resources
        groups.append(group)
        group_set = set(group)
        placed |= group_set
        remaining = [item for item in remaining if item["id"] not in group_set]
    return groups


def build_worker_prompt(payload: dict) -> str:
    """Render the worker prompt for the host adapter. Pure function.

    The first line is the mandated ``Active task:`` line; the rest injects the
    protocol fields so the worker sees scope, baseline, and return conditions.
    """
    validate_payload(payload)
    lines = [payload["prompt_first_line"]]
    lines.append("fstar dispatch %s (dispatch_id: %s)" % (payload["role"], payload["dispatch_id"]))
    lines.append("task_ref: %s" % payload["task_ref"])
    if payload.get("extensions"):
        from .extensions import grants
        context = grants(payload["extensions"])
        lines.append("Extension members in this context: %s" % json.dumps(
            {key: sorted(value) for key, value in context.items()}, sort_keys=True))
    if payload.get("plan_item_ids"):
        lines.append("plan_item_ids: %s" % ", ".join(payload["plan_item_ids"]))
    lines.append("allowed_paths (protocol constraint, not a sandbox; out-of-scope writes are rejected at harvest):")
    for path in payload["allowed_paths"]:
        lines.append("  - %s" % path)
    if payload.get("item_ids"):
        lines.append("item_ids: %s" % ", ".join(payload["item_ids"]))
    if payload.get("baseline_sha256"):
        lines.append("baseline_sha256: %s (verify before submitting; a mismatch returns to the coordinator for merge/redispatch)" % payload["baseline_sha256"])
    baseline = payload.get("baseline", {})
    if baseline.get("artifact_items"):
        lines.append("baseline artifact items (input fingerprints):")
        for group in baseline["artifact_items"]:
            for entry in group.get("items", []):
                lines.append("  - %s#%s (sha256: %s)" % (group.get("artifact"), entry.get("id"), entry.get("sha256")))
    if baseline.get("delivery", {}).get("paths"):
        lines.append("baseline delivery paths:")
        for entry in baseline["delivery"]["paths"]:
            lines.append("  - %s (sha256: %s)" % (entry.get("path"), entry.get("sha256")))
    if payload.get("read_context"):
        lines.append("read_context (must be read in full, with fingerprints):")
        for entry in payload["read_context"]:
            lines.append("  - %s (sha256: %s)" % (entry.get("path"), entry.get("sha256")))
    if payload.get("input_versions"):
        lines.append("input_versions:")
        for entry in payload["input_versions"]:
            lines.append("  - %s (sha256: %s)" % (entry.get("path"), entry.get("sha256")))
    if payload.get("required_validations"):
        lines.append("required_validations (must actually be executed; record command/result/exit_code/duration/retries):")
        for validation in payload["required_validations"]:
            lines.append("  - %s" % validation)
    conditions = payload.get("return_conditions", {})
    lines.append("return_conditions: done=%s blocked=%s failed=%s" % (conditions.get("done", ""), conditions.get("blocked", ""), conditions.get("failed", "")))
    if payload.get("prior_failure"):
        lines.append("prior_failure: %s (from dispatch %s)" % (payload["prior_failure"].get("reason"), payload["prior_failure"].get("dispatch_id")))
    lines.append("Return a fstar.dispatch.result.v1 object; done means harvest completed, not acceptance.")
    return "\n".join(lines)


def adapter_invocation_note() -> dict:
    """The adapter instructions returned by every dispatch CLI command."""
    return {
        "dispatch_mode": "adapter",
        "note": "This CLI prepared, validated, and registered the payload only. No worker was started from the shell: a shell command cannot invoke the current session's native Agent tool. The host adapter (main agent) performs the actual dispatch via the host's native Agent tool and harvests the result.",
        "steps": [
            "Render the worker prompt with fstar.dispatch.build_worker_prompt(payload).",
            "Dispatch through the host-native Agent tool with the rendered prompt.",
            "Collect the worker's fstar.dispatch.result.v1 object.",
            "Run `fstar dispatch harvest --result FILE --payload FILE` to verify and record evidence through the core services.",
        ],
    }


class DispatchService:
    """Registration and harvest layers over the injectable core services."""

    def __init__(self, store: TaskStore, *, clock: Optional[Callable[[], str]] = None,
                 task_service: Optional[TaskService] = None,
                 evidence_service: Optional[EvidenceService] = None):
        self.store = store
        self.clock = clock or (task_service.clock if task_service else utc_now)
        self.tasks = task_service or TaskService(store, clock=clock)
        self.evidence = evidence_service or self.tasks.evidence
        self._handed_off = {}

    def authorize_role(self, payload: dict) -> None:
        from .extensions import grants, includes
        task_ref = payload["task_ref"]
        records = payload.get("extensions", []) if task_ref == "session-only" else self.store.read(task_ref)["extensions"]
        context = grants(records)
        role_member = {"research": ("multi-agent", "research"), "editor": ("planning-review", "editor")}.get(payload["role"])
        if role_member and not includes(context, *role_member):
            raise DomainError("extension_not_authorized", "Dispatch role requires an included extension member", {"package": role_member[0], "member": role_member[1]}, status=3)
        # Input fingerprints are part of every dispatch protocol, including
        # the minimal implement/check loop. Enhanced version injection may be
        # authorized separately, but must not block these baseline fields.

    # -- registration -----------------------------------------------------

    def register(self, payload: dict, *, coordinator_id: str = "coordinator",
                 actor: Optional[dict] = None) -> dict:
        """Register a dispatch. Session-only payloads persist nothing."""
        validate_payload(payload)
        task_ref = payload["task_ref"]
        self.authorize_role(payload)
        if task_ref != "session-only":
            # Persisted records are authoritative even if the caller supplied
            # stale session context for the same task.
            payload = dict(payload, extensions=self.store.read(task_ref)["extensions"])
        if task_ref == "session-only":
            # Minimal loop: validate only. No fstar metadata is created.
            return {"registered": False, "persistence": "session_only",
                    "payload": payload, "adapter": adapter_invocation_note()}
        task = self.store.read(task_ref)
        if task["phase"] != "in_progress":
            raise DomainError("dispatch_not_allowed", "Dispatch registration requires an in-progress task", {"phase": task["phase"]}, status=3)
        lease = task.get("lease")
        token = None
        if lease and lease.get("expires_at", "") > self.clock():
            if lease.get("holder", {}).get("id") != coordinator_id:
                raise DomainError("lease_conflict", "Another writer holds the task lease", {"holder": lease.get("holder")}, status=4)
            token = lease.get("token")
        else:
            acquired = self.tasks.acquire_lease(task_ref, holder=coordinator_id, role="coordinator", actor=actor)
            token = acquired["token"]
        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            current = self.store._read_path(task_dir / "task.json")
            current["events"].append(make_event(
                "dispatch_registered",
                {"source_id": str(uuid.uuid4()), "type": "system", "at": self.clock(),
                 "actor": actor or {"role": "coordinator", "id": coordinator_id},
                 "reference": "dispatch %s" % payload["dispatch_id"], "quote": "",
                 "scope": "dispatch", "validates": ""},
                {"dispatch_id": payload["dispatch_id"], "role": payload["role"],
                 "plan_item_ids": payload["plan_item_ids"]},
                self.clock()))
            self.store.write(task_dir, current)
        return {"registered": True, "persistence": "task", "lease_token": token,
                "dispatch_id": payload["dispatch_id"], "payload": payload,
                "adapter": adapter_invocation_note()}

    # -- parallel reservation layer (multi-agent/parallel-implement) ----------
    _RESERVATIONS_KEY = "dispatch_reservations"

    @staticmethod
    def _paths_conflict(first: str, second: str) -> bool:
        """Exact or nested-path conflict after conservative normalization.

        Trailing/leading separators, doubled separators, and ``.`` segments are
        normalized before comparison so equivalent spellings cannot dodge the
        check. Symlink aliases cannot be resolved here (a reservation path
        need not exist on disk); a same-permission writer can still bypass the
        check through filesystem aliases, so this is scope bookkeeping, not a
        security boundary.
        """
        def normalize(path: str) -> str:
            parts = []
            for part in path.split("/"):
                if part in ("", "."):
                    continue
                parts.append(part)
            return "/".join(parts)
        first, second = normalize(first), normalize(second)
        return first == second or first.startswith(second + "/") or second.startswith(first + "/")

    def _get_reservations(self, task: dict) -> list:
        return list(task.get("meta", {}).get("templates", {}).get(self._RESERVATIONS_KEY, []))

    def _batch_safety_error(self, code: str, message: str, details: dict) -> None:
        raise DomainError(code, message, details, status=3)

    def reserve_parallel(self, payloads: Sequence[dict], *, coordinator_id: str = "coordinator",
                         actor: Optional[dict] = None, plan_items: Optional[Sequence[dict]] = None) -> dict:
        """Reserve dependency- and write-safe parallel implement dispatches.

        Requires an included ``multi-agent/parallel-implement`` member.
        Validates intra-batch dependencies, active reservation conflicts, and
        handed-off check scopes before reserving under the coordinator lease.
        Does NOT claim that host workers have started or stopped.
        """
        entries = list(payloads or [])
        if not entries:
            self._batch_safety_error("invalid_batch", "Parallel reservation requires at least one payload", {})
        for payload in entries:
            validate_payload(payload)
            if payload["role"] != "implement":
                self._batch_safety_error("invalid_batch", "Parallel reservations support implement payloads only",
                                         {"role": payload["role"]})
        task_refs = {payload["task_ref"] for payload in entries}
        if len(task_refs) != 1:
            self._batch_safety_error("invalid_batch", "Parallel batch targets exactly one task",
                                    {"task_refs": sorted(task_refs)})
        task_ref = task_refs.pop()
        if len({payload["dispatch_id"] for payload in entries}) != len(entries):
            self._batch_safety_error("invalid_batch", "Batch payloads need distinct dispatch ids", {})

        from .extensions import grants, includes
        if task_ref == "session-only":
            # Session-only grants are caller-held; the batch is one session
            # context, so the records ride on the payloads themselves. The
            # same package may appear on several payloads: keep one record.
            records = []
            for payload in entries:
                for record in payload.get("extensions", []):
                    if record not in records:
                        records.append(record)
        else:
            records = self.store.read(task_ref)["extensions"]
        if not includes(grants(records), "multi-agent", "parallel-implement"):
            raise DomainError("extension_not_authorized", "Parallel reservation requires an included extension member",
                              {"package": "multi-agent", "member": "parallel-implement"}, status=3)

        # Build plan item index. The plan is REQUIRED: without it, dependency
        # safety cannot be proven, and reservation is refused rather than
        # guessed.
        supplied_items = list(plan_items or [])
        if not supplied_items:
            self._batch_safety_error("invalid_batch",
                                     "Parallel reservation requires the plan items to prove dependency safety", {})
        items_by_id = {}
        for item in supplied_items:
            item = _require_dict(item, "plan item")
            item_id = _require_str(item.get("id"), "plan item id")
            items_by_id[item_id] = item

        # Verify plan item coverage
        for payload in entries:
            for item_id in payload["plan_item_ids"]:
                if item_id not in items_by_id:
                    self._batch_safety_error(
                        "invalid_batch",
                        "Payload references a plan item missing from the supplied plan",
                        {"plan_item_id": item_id})

        # Intra-batch dependency and path checks (pure computations)
        all_candidate_paths = []
        for idx, payload in enumerate(entries):
            p_resources = sorted({str(r) for item_id in payload["plan_item_ids"]
                                  for r in (items_by_id.get(item_id, {}).get("shared_resources", []) or [])})
            all_candidate_paths.append((payload, p_resources))

        owner_in_batch = {}
        for idx, payload in enumerate(entries):
            for item_id in payload["plan_item_ids"]:
                owner_in_batch[item_id] = idx

        for idx, payload in enumerate(entries):
            for item_id in payload["plan_item_ids"]:
                item_spec = items_by_id.get(item_id, {})
                for dep in item_spec.get("depends_on", []) or []:
                    if dep in owner_in_batch and owner_in_batch[dep] != idx:
                        self._batch_safety_error(
                            "dependency_in_batch",
                            "A payload in the batch depends on another payload in the same batch",
                            {"plan_item_id": item_id, "dependency": dep})

        for i in range(len(all_candidate_paths)):
            payload_i, res_i = all_candidate_paths[i]
            for j in range(i + 1, len(all_candidate_paths)):
                payload_j, res_j = all_candidate_paths[j]
                for p1 in payload_i["allowed_paths"]:
                    for p2 in payload_j["allowed_paths"]:
                        if self._paths_conflict(p1, p2):
                            self._batch_safety_error(
                                "path_conflict", "Batch payloads have overlapping allowed_paths (including nesting)",
                                {"first": p1, "second": p2})
                overlap = sorted(set(res_i) & set(res_j))
                if overlap:
                    self._batch_safety_error(
                        "shared_resource_conflict", "Batch payloads share a serialized resource",
                        {"shared_resources": overlap})

        note = ("Parallel dispatch reserved under coordinator lease. Host launch requires explicit confirmation or adapter dispatch. "
                "No host worker process liveness is implied by reservation.")

        if task_ref == "session-only":
            active_reservations = [r for r in self._handed_off.get("session_reservations", [])
                                  if r.get("state") in ("reserved", "launched")]
            active_res_items = {item_id for r in active_reservations for item_id in r.get("plan_item_ids", [])}
            for idx, payload in enumerate(entries):
                for item_id in payload["plan_item_ids"]:
                    item_spec = items_by_id.get(item_id, {})
                    for dep in item_spec.get("depends_on", []) or []:
                        if dep in active_res_items:
                            self._batch_safety_error(
                                "dependency_unresolved",
                                "A payload depends on a plan item with an unresolved reservation",
                                {"plan_item_id": item_id, "dependency": dep})
            for payload, res_i in all_candidate_paths:
                for active in active_reservations:
                    for p1 in payload["allowed_paths"]:
                        for p2 in active.get("allowed_paths", []):
                            if self._paths_conflict(p1, p2):
                                self._batch_safety_error(
                                    "path_conflict", "Payload conflicts with an active reservation",
                                    {"candidate": p1, "active": p2, "active_dispatch_id": active["dispatch_id"]})
                    overlap = sorted(set(res_i) & set(active.get("shared_resources", [])))
                    if overlap:
                        self._batch_safety_error(
                            "shared_resource_conflict", "Payload shares a resource with an active reservation",
                            {"shared_resources": overlap, "active_dispatch_id": active["dispatch_id"]})
            for payload in entries:
                overlap = sorted(set(payload["plan_item_ids"]) & self._handed_off_items(payload))
                if overlap:
                    raise DomainError("scope_violation", "Plan items were handed off to check", {"handed_off": overlap}, status=4)

            now = self.clock()
            new_reservations = []
            for payload, res_i in all_candidate_paths:
                new_reservations.append({
                    "dispatch_id": payload["dispatch_id"],
                    "role": payload["role"],
                    "plan_item_ids": payload["plan_item_ids"],
                    "allowed_paths": payload["allowed_paths"],
                    "shared_resources": res_i,
                    "state": "reserved",
                    "created_at": now,
                    "updated_at": now,
                })
            session_res = self._handed_off.setdefault("session_reservations", [])
            session_res.extend(new_reservations)
            return {"registered": False, "persistence": "session_only",
                    "reservations": new_reservations, "payloads": entries,
                    "adapter": adapter_invocation_note(), "note": note}

        # Persistent task: run lease acquisition and all active-reservation checks INSIDE the task transaction
        now = self.clock()
        task = self.store.read(task_ref)
        if task["phase"] != "in_progress":
            raise DomainError("dispatch_not_allowed", "Dispatch reservation requires an in-progress task", {"phase": task["phase"]}, status=3)
        lease = task.get("lease")
        token = None
        if lease and lease.get("expires_at", "") > now:
            if lease.get("holder", {}).get("id") != coordinator_id:
                raise DomainError("lease_conflict", "Another writer holds the task lease", {"holder": lease.get("holder")}, status=4)
            token = lease.get("token")
        else:
            acquired = self.tasks.acquire_lease(task_ref, holder=coordinator_id, role="coordinator", actor=actor)
            token = acquired["token"]

        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            current = self.store._read_path(task_dir / "task.json")
            # Freshly read grants inside lock
            if not includes(grants(current["extensions"]), "multi-agent", "parallel-implement"):
                raise DomainError("extension_not_authorized", "Parallel reservation requires an included extension member",
                                  {"package": "multi-agent", "member": "parallel-implement"}, status=3)

            active_reservations = [r for r in self._get_reservations(current)
                                  if r.get("state") in ("reserved", "launched")]
            active_res_items = {item_id for r in active_reservations for item_id in r.get("plan_item_ids", [])}
            for idx, payload in enumerate(entries):
                for item_id in payload["plan_item_ids"]:
                    item_spec = items_by_id.get(item_id, {})
                    for dep in item_spec.get("depends_on", []) or []:
                        if dep in active_res_items:
                            self._batch_safety_error(
                                "dependency_unresolved",
                                "A payload depends on a plan item with an unresolved reservation",
                                {"plan_item_id": item_id, "dependency": dep})

            for payload, res_i in all_candidate_paths:
                for active in active_reservations:
                    for p1 in payload["allowed_paths"]:
                        for p2 in active.get("allowed_paths", []):
                            if self._paths_conflict(p1, p2):
                                self._batch_safety_error(
                                    "path_conflict", "Payload conflicts with an active reservation",
                                    {"candidate": p1, "active": p2, "active_dispatch_id": active["dispatch_id"]})
                    overlap = sorted(set(res_i) & set(active.get("shared_resources", [])))
                    if overlap:
                        self._batch_safety_error(
                            "shared_resource_conflict", "Payload shares a resource with an active reservation",
                            {"shared_resources": overlap, "active_dispatch_id": active["dispatch_id"]})

            # Scope handoff check
            handed_off = set(current.get("meta", {}).get("templates", {}).get(self._HANDOFF_KEY, []))
            for payload in entries:
                overlap = sorted(set(payload["plan_item_ids"]) & handed_off)
                if overlap:
                    raise DomainError("scope_violation", "Plan items were handed off to check", {"handed_off": overlap}, status=4)

            new_reservations = []
            for payload, res_i in all_candidate_paths:
                new_reservations.append({
                    "dispatch_id": payload["dispatch_id"],
                    "role": payload["role"],
                    "plan_item_ids": payload["plan_item_ids"],
                    "allowed_paths": payload["allowed_paths"],
                    "shared_resources": res_i,
                    "lease_token": token,
                    "state": "reserved",
                    "created_at": now,
                    "updated_at": now,
                })

            templates = current.setdefault("meta", {}).setdefault("templates", {})
            existing = list(templates.get(self._RESERVATIONS_KEY, []))
            existing.extend(new_reservations)
            templates[self._RESERVATIONS_KEY] = existing

            for payload in entries:
                current["events"].append(make_event(
                    "dispatch_reserved",
                    {"source_id": str(uuid.uuid4()), "type": "system", "at": now,
                     "actor": actor or {"role": "coordinator", "id": coordinator_id},
                     "reference": "dispatch %s" % payload["dispatch_id"], "quote": "",
                     "scope": "dispatch", "validates": ""},
                    {"dispatch_id": payload["dispatch_id"], "role": payload["role"],
                     "plan_item_ids": payload["plan_item_ids"], "parallel": True},
                    now))
            self.store.write(task_dir, current)

        return {"registered": True, "persistence": "task", "lease_token": token,
                "reservations": new_reservations, "payloads": entries,
                "adapter": adapter_invocation_note(), "note": note}

    def confirm_launch(self, task_ref: str, dispatch_ids: Sequence[str], *, coordinator_id: str = "coordinator") -> dict:
        """Confirm host launch attempt for reserved dispatches."""
        ids = set(dispatch_ids)
        now = self.clock()
        if task_ref == "session-only":
            session_res = self._handed_off.get("session_reservations", [])
            updated = []
            for res in session_res:
                if res["dispatch_id"] in ids and res["state"] == "reserved":
                    res["state"] = "launched"
                    res["updated_at"] = now
                    updated.append(res["dispatch_id"])
            return {"confirmed": updated, "persistence": "session_only"}

        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            task = self.store._read_path(task_dir / "task.json")
            templates = task.setdefault("meta", {}).setdefault("templates", {})
            reservations = templates.get(self._RESERVATIONS_KEY, [])
            updated = []
            for res in reservations:
                if res["dispatch_id"] in ids and res["state"] == "reserved":
                    res["state"] = "launched"
                    res["updated_at"] = now
                    updated.append(res["dispatch_id"])
            self.store.write(task_dir, task)
        return {"confirmed": updated, "persistence": "task"}

    def _resolve_session_reservation(self, dispatch_id: str, state: str) -> None:
        """Resolve an in-memory session-only reservation (no metadata)."""
        for reservation in self._handed_off.get("session_reservations", []):
            if reservation.get("dispatch_id") == dispatch_id and reservation.get("state") in ("reserved", "launched"):
                reservation["state"] = state
                reservation["updated_at"] = self.clock()

    def parallel_reservation_report(self, task_ref: str) -> dict:
        """Conservative read-only report of unresolved parallel reservations.

        Used after a crash or lease takeover: the coordinator CANNOT know
        whether a reserved/launched host worker is still running, so the report
        is read-only and never auto-releases reservations. The user (or an
        explicit interrupt decision) chooses reconcile/drop per dispatch.
        """
        if task_ref == "session-only":
            active = [dict(r) for r in self._handed_off.get("session_reservations", [])
                      if r.get("state") in ("reserved", "launched")]
            return {"task_ref": task_ref, "persistence": "session_only",
                    "unresolved": active,
                    "note": "Unknown host worker state: reservations are never auto-released."}
        task = self.store.read(task_ref)
        active = [dict(r) for r in self._get_reservations(task)
                  if r.get("state") in ("reserved", "launched")]
        return {"task_ref": task_ref, "persistence": "task",
                "unresolved": active,
                "note": "Unknown host worker state: reservations are never auto-released."}

    def release_reservation(self, task_ref: str, dispatch_id: str, *, reason: str,
                            coordinator_id: str = "coordinator",
                            lease_token: Optional[str] = None) -> dict:
        """Explicitly release one unresolved reservation (conservative recovery).

        Called only after the coordinator decided the worker is gone (user
        decision or an explicit interrupt outcome). Releasing does NOT claim
        the host worker stopped; it only frees the reservation scope for new
        dispatches and records the decision.
        """
        if not reason or not reason.strip():
            raise DomainError("reason_required", "Releasing a reservation requires an explicit reason")
        now = self.clock()
        if task_ref == "session-only":
            released = []
            for reservation in self._handed_off.get("session_reservations", []):
                if reservation.get("dispatch_id") == dispatch_id and reservation.get("state") in ("reserved", "launched"):
                    reservation["state"] = "released"
                    reservation["release_reason"] = reason
                    reservation["updated_at"] = now
                    released.append(dispatch_id)
            return {"released": released, "persistence": "session_only"}
        task = self.store.read(task_ref)
        lease = task.get("lease")
        if lease and lease.get("expires_at", "") > now and lease.get("holder", {}).get("id") != coordinator_id:
            raise DomainError("lease_conflict", "Another writer holds the task lease", {"holder": lease.get("holder")}, status=4)
        if lease_token and (not lease or lease.get("token") != lease_token):
            raise DomainError("invalid_lease", "Lease token is no longer current", status=4)
        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            current = self.store._read_path(task_dir / "task.json")
            templates = current.setdefault("meta", {}).setdefault("templates", {})
            released = []
            for reservation in templates.get(self._RESERVATIONS_KEY, []):
                if reservation.get("dispatch_id") == dispatch_id and reservation.get("state") in ("reserved", "launched"):
                    reservation["state"] = "released"
                    reservation["release_reason"] = reason
                    reservation["updated_at"] = now
                    released.append(dispatch_id)
            if released:
                current["events"].append(make_event(
                    "dispatch_reservation_released",
                    {"source_id": str(uuid.uuid4()), "type": "system", "at": now,
                     "actor": {"role": "coordinator", "id": coordinator_id},
                     "reference": "dispatch %s" % dispatch_id, "quote": "", "scope": "dispatch", "validates": ""},
                    {"dispatch_id": dispatch_id, "reason": reason}, now))
            self.store.write(task_dir, current)
        return {"released": released, "persistence": "task"}

    # -- check handoff bookkeeping ---------------------------------------
    # The hand-off marker is persisted on the task (meta.templates is the
    # fixed-purpose meta sub-key surface; no new top-level fields) so harvest
    # in a different process still refuses implement writes for the handed-off
    # scope. Session-only dispatch has no task.json, so its marker stays in
    # memory for the session lifetime.

    _HANDOFF_KEY = "dispatch_check_handoff"

    def _handoff_store(self, task_ref: str):
        if task_ref == "session-only":
            return None
        task = self.store.read(task_ref)
        return task.setdefault("meta", {}).setdefault("templates", {})

    def hand_off_scope(self, task_ref: str, plan_item_ids: Sequence[str]) -> dict:
        """Mark plan items as handed off to check; implement writes stop there."""
        if task_ref == "session-only":
            for item_id in plan_item_ids:
                self._handed_off.setdefault("session-only", set()).add(item_id)
            return {"handed_off": sorted(plan_item_ids), "persistence": "session_only"}
        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            task = self.store._read_path(task_dir / "task.json")
            self._merge_handoff(task, plan_item_ids)
            task["events"].append(make_event(
                "dispatch_scope_handed_off",
                {"source_id": str(uuid.uuid4()), "type": "system", "at": self.clock(),
                 "actor": {"role": "coordinator", "id": "coordinator"},
                 "reference": "check handoff", "quote": "", "scope": "dispatch", "validates": ""},
                {"plan_item_ids": sorted(plan_item_ids)}, self.clock()))
            self.store.write(task_dir, task)
        return {"handed_off": sorted(plan_item_ids), "persistence": "task"}

    def _merge_handoff(self, task: dict, plan_item_ids: Sequence[str]) -> None:
        templates = task.setdefault("meta", {}).setdefault("templates", {})
        existing = set(templates.get(self._HANDOFF_KEY, []))
        existing |= set(plan_item_ids)
        templates[self._HANDOFF_KEY] = sorted(existing)

    def _handed_off_items(self, payload: dict) -> set:
        if payload["task_ref"] == "session-only":
            return self._handed_off.get("session-only", set())
        try:
            task = self.store.read(payload["task_ref"])
        except DomainError:
            return set()
        return set(task.get("meta", {}).get("templates", {}).get(self._HANDOFF_KEY, []))

    # -- harvested-dispatch replay guard -----------------------------------
    # Harvest bookkeeping (already-harvested dispatch ids) also lives on the
    # task so a replayed result cannot double-record evidence from another
    # process. The ids ride inside meta.templates under a fixed key; no new
    # top-level task fields exist.

    _HARVESTED_KEY = "dispatch_harvested"

    def _harvested_ids(self, task: dict) -> set:
        return set(task.get("meta", {}).get("templates", {}).get(self._HARVESTED_KEY, []))

    def _mark_harvested(self, task: dict, dispatch_id: str) -> None:
        templates = task.setdefault("meta", {}).setdefault("templates", {})
        harvested = set(templates.get(self._HARVESTED_KEY, []))
        harvested.add(dispatch_id)
        templates[self._HARVESTED_KEY] = sorted(harvested)

    # -- harvest ----------------------------------------------------------

    def _current_input_baseline(self, payload: dict) -> dict:
        """Recompute the payload's INPUT baseline through the core services.

        Only input documents are recomputed. The delivery baseline is the
        worker's expected OUTPUT (the worker is supposed to change those
        files), so it is never part of the staleness comparison.
        """
        baseline = payload["baseline"]
        artifact_items = []
        for group in baseline.get("artifact_items", []):
            artifact = group.get("artifact")
            items = [entry["id"] for entry in group.get("items", [])]
            artifact_items.append(self.evidence.snapshot(payload["task_ref"], artifact=artifact, items=items))
        return {"artifact_items": artifact_items}

    def _baseline_matches(self, recorded: dict, current: dict) -> bool:
        groups = recorded.get("artifact_items", [])
        live_groups = current["artifact_items"]
        if len(groups) != len(live_groups):
            return False
        for group, live in zip(groups, live_groups):
            if group.get("artifact") != live.get("artifact"):
                return False
            for key in ("items", "dependencies"):
                if {(i.get("id"), i.get("sha256")) for i in group.get(key, [])} != {(i.get("id"), i.get("sha256")) for i in live.get(key, [])}:
                    return False
            if group.get("granularity") != live.get("granularity"):
                return False
        return True

    def _stale_change(self, payload: dict, current: dict) -> dict:
        return build_change(
            source="file",
            origin=", ".join(sorted({group.get("artifact") for group in payload["baseline"].get("artifact_items", [])})),
            affected={"plan_item_ids": payload["plan_item_ids"], "artifact_items": payload["baseline"].get("artifact_items", [])},
            old_fingerprints={"baseline": payload["baseline"]},
            new_fingerprints={"baseline": current},
            action="pause_and_redispatch")

    def _verify_file_inputs(self, payload: dict, changed_paths: list) -> list:
        """Verify file SHA-256 inputs relative to the dispatch working root.

        A reported output may legitimately differ from its pre-edit input;
        that overlap cannot be independently verified after the edit.
        """
        from .evidence import _safe_project_file
        root = self.store.project_root
        changed = {str(Path(path)) for path in changed_paths}
        unverified = []
        for field in ("input_versions", "read_context"):
            for entry in payload.get(field, []):
                relative = entry["path"]
                if str(Path(relative)) in changed:
                    unverified.append({"field": field, "path": relative, "reason": "reported_worker_output"})
                    continue
                try:
                    path = _safe_project_file(root, relative)
                    if not path.is_file():
                        raise OSError("input is missing or not a regular file")
                    actual = file_digest(path)
                except (OSError, DomainError, ValueError, RuntimeError) as exc:
                    raise DomainError("input_unverifiable", "Cannot verify dispatch input file", {"field": field, "path": relative, "reason": str(exc)}, status=4)
                if actual != entry["sha256"]:
                    change = build_change(source="file", origin=relative,
                                          affected={"plan_item_ids": payload["plan_item_ids"], "artifact_items": []},
                                          old_fingerprints={"sha256": entry["sha256"]},
                                          new_fingerprints={"sha256": actual}, action="pause_and_redispatch")
                    raise DomainError("stale_input", "Dispatch input file changed since dispatch", {"change": change, "field": field, "path": relative}, status=4)
        return unverified

    def harvest(self, result: dict, payload: dict, *, lease_token: str,
                coordinator_id: str = "coordinator",
                check_evidence: Optional[dict] = None) -> dict:
        """Verify a worker result, then record evidence through the core.

        This is the single validated harvest path for dispatch results: the
        hooks worker-result entry delegates here, so no result can bypass the
        identity/baseline/scope/lease verification by arriving through a hook.

        Verification order: identity, baseline (input fingerprints only),
        scope, replay, lease. Any failure raises DomainError with a stable
        code and writes nothing. Failed/cancelled results record a terminal
        event but never release the coordinator's task lease while sibling
        workers may still be running; interrupt carries the explicit
        release choice.
        """
        validate_result(result)
        validate_payload(payload)
        # 1. Identity
        if result["dispatch_id"] != payload["dispatch_id"]:
            raise DomainError("identity_mismatch", "Result dispatch_id does not match the payload", {"expected": payload["dispatch_id"], "actual": result["dispatch_id"]}, status=4)
        if result["role"] != payload["role"]:
            raise DomainError("identity_mismatch", "Result role does not match the payload", {"expected": payload["role"], "actual": result["role"]}, status=4)
        task_ref = payload["task_ref"]
        # Check scope before deciding which inputs are claimed worker outputs.
        out_of_scope = sorted(set(result["changed_paths"]) - set(payload["allowed_paths"]))
        if out_of_scope:
            raise DomainError("scope_violation", "Result changed paths outside the authorized scope", {"out_of_scope": out_of_scope}, status=4)
        unverified_inputs = self._verify_file_inputs(payload, result["changed_paths"])
        # 2. Baseline: recompute the INPUT fingerprints only. The delivery
        # baseline is the worker's expected output and must differ when the
        # worker did its job; comparing it would make every legitimate harvest
        # stale.
        if task_ref != "session-only" and payload["baseline"].get("artifact_items"):
            current = self._current_input_baseline(payload)
            if not self._baseline_matches(payload["baseline"], current):
                raise DomainError("stale_input", "Input baseline changed since dispatch; the result is not recorded under the old baseline", {"change": self._stale_change(payload, current)}, status=4)
        # 3. Scope
        if payload["role"] == "implement":
            overlap = sorted(set(payload["plan_item_ids"]) & self._handed_off_items(payload))
            if overlap:
                raise DomainError("scope_violation", "Plan items were handed off to check; implement writes are paused for this scope", {"handed_off": overlap}, status=4)
        if payload["role"] == "editor":
            # The editor baseline is a pre-edit discussion anchor: the file
            # must still match it when the editor STARTED. The harvest compares
            # the result's reported baseline_sha256 (the version the editor
            # based the edit on) against the payload's; a mismatch means the
            # discussion moved underneath the editor — old draft does not
            # overwrite the newer conclusion. The file itself legitimately
            # differs after the intended write.
            reported = result.get("baseline_sha256") or payload.get("baseline_sha256")
            if reported != payload.get("baseline_sha256"):
                raise DomainError("baseline_conflict", "Editor result was based on a different baseline; return to the coordinator for merge or redispatch", {"expected": payload.get("baseline_sha256"), "actual": reported}, status=4)
        if task_ref == "session-only":
            # Minimal loop: verification passed; no evidence persistence exists.
            self._resolve_session_reservation(result["dispatch_id"], "terminal" if result["status"] in ("failed", "cancelled") else "completed")
            return {"recorded": False, "persistence": "session_only", "status": result["status"],
                    "dispatch_id": result["dispatch_id"],
                    "unverified_inputs": unverified_inputs,
                    "input_baseline_verified": not bool(payload["baseline"].get("artifact_items")),
                    "next": _terminal_next(result["status"], payload["role"])}
        # 4. Replay: the same dispatch result must not record evidence twice.
        task = self.store.read(task_ref)
        if result["dispatch_id"] in self._harvested_ids(task):
            return {"recorded": False, "replayed": True, "dispatch_id": result["dispatch_id"],
                    "note": "This dispatch result was already harvested; replay records nothing."}
        if result["status"] in ("failed", "cancelled"):
            # Terminal outcome, no evidence. The coordinator lease stays:
            # releasing it here would orphan sibling workers still dispatched
            # on the same task; interrupt --release-lease-token is the explicit
            # release path.
            with self.store.transaction():
                task_dir = self.store.resolve(task_ref)
                current = self.store._read_path(task_dir / "task.json")
                self._mark_harvested(current, result["dispatch_id"])
                self._resolve_reservation(current, result["dispatch_id"], "terminal")
                current["events"].append(make_event(
                    "dispatch_terminal",
                    {"source_id": str(uuid.uuid4()), "type": "system", "at": self.clock(),
                     "actor": {"role": "coordinator", "id": coordinator_id},
                     "reference": "dispatch %s" % result["dispatch_id"], "quote": "",
                     "scope": "dispatch", "validates": ""},
                    {"dispatch_id": result["dispatch_id"], "role": result["role"],
                     "status": result["status"], "blockers": result.get("blockers", [])},
                    self.clock()))
                self.store.write(task_dir, current)
            return {"recorded": False, "replayed": False, "status": result["status"],
                    "dispatch_id": result["dispatch_id"],
                    "lease_released": False,
                    "next": _terminal_next(result["status"], payload["role"])}
        file_inputs = [dict(path=entry["path"], sha256=entry["sha256"])
                       for field in ("input_versions", "read_context")
                       for entry in payload.get(field, [])
                       if not any(item["field"] == field and item["path"] == entry["path"]
                                  for item in unverified_inputs)]
        # 5. Lease: record through the core service, which validates the token
        # inside the lock, auto-renews +30m, and enforces the check gates.
        if payload["role"] == "check":
            if check_evidence is None:
                raise DomainError("invalid_check", "Check harvest requires the check evidence body", status=3)
            check_evidence = dict(check_evidence)
            check_evidence.setdefault("dispatch_id", result["dispatch_id"])
            check_evidence["input_files"] = file_inputs
            if unverified_inputs:
                check_evidence["state"] = "stale"
                check_evidence["stale_reasons"] = [{"type": "unverified_inputs", "inputs": unverified_inputs}]
            recorded = self.evidence.record(task_ref, evidence=check_evidence, lease_token=lease_token)
            self._record_harvested(task_ref, result["dispatch_id"])
            return {"recorded": True, "persistence": "task", "evidence_id": recorded["id"],
                    "state": recorded["state"], "dispatch_id": result["dispatch_id"],
                    "unverified_inputs": unverified_inputs, "next": "acceptance_review"}
        delivery_paths = sorted(set(result["changed_paths"]))
        producer = {"role": payload["role"], "id": coordinator_id, "session_id": coordinator_id}
        evidence = {
            "kind": "delivery",
            "producer": producer,
            "validates": payload["baseline"].get("artifact_items", []),
            # Always recompute the post-work delivery snapshot (even for an
            # empty changed set): a placeholder digest would be judged stale
            # by the core freshness check at record time.
            "delivery": self.evidence.delivery_snapshot(delivery_paths),
            "dispatch_id": payload["dispatch_id"],
            "validation_facts": result["validation_facts"],
            "input_files": file_inputs,
            "unverified_inputs": unverified_inputs,
        }
        if unverified_inputs:
            evidence["state"] = "stale"
            evidence["stale_reasons"] = [{"type": "unverified_inputs", "inputs": unverified_inputs}]
        recorded = self.evidence.record(task_ref, evidence=evidence, lease_token=lease_token)
        self._record_harvested(task_ref, result["dispatch_id"])
        return {"recorded": True, "persistence": "task", "evidence_id": recorded["id"],
                "state": recorded["state"], "dispatch_id": result["dispatch_id"],
                "unverified_inputs": unverified_inputs, "next": "check_dispatch"}

    def _record_harvested(self, task_ref: str, dispatch_id: str) -> None:
        """Persist the harvested-dispatch marker on the task."""
        with self.store.transaction():
            task_dir = self.store.resolve(task_ref)
            current = self.store._read_path(task_dir / "task.json")
            self._mark_harvested(current, dispatch_id)
            self._resolve_reservation(current, dispatch_id, "completed")
            self.store.write(task_dir, current)

    def _resolve_reservation(self, task: dict, dispatch_id: str, state: str) -> None:
        """Mark a parallel reservation terminal so its scope is freed.

        Resolving a reservation NEVER implies the host worker stopped: the
        coordinator only learns the harvest result. Unknown dispatch ids are
        ignored (regular serial dispatches have no reservation).
        """
        templates = task.setdefault("meta", {}).setdefault("templates", {})
        for reservation in templates.get(self._RESERVATIONS_KEY, []):
            if reservation.get("dispatch_id") == dispatch_id and reservation.get("state") in ("reserved", "launched"):
                reservation["state"] = state
                reservation["updated_at"] = self.clock()

    # -- retry ------------------------------------------------------------

    def retry_dispatch(self, payload: dict, *, failure_reason: str,
                       environment_blocked: bool = False) -> dict:
        """Apply the retry policy: at most one auto retry, carrying the prior failure."""
        validate_payload(payload)
        if environment_blocked:
            return {"retry": False, "status": "blocked", "reason": failure_reason,
                    "note": "Environment blocking is not retried in a loop."}
        if payload.get("prior_failure"):
            return {"retry": False, "status": "dispatch_failed_persistent",
                    "reason": failure_reason, "route": "fstar-debug",
                    "note": "The single auto retry already happened; routing enters debug."}
        retried = dict(payload)
        retried["dispatch_id"] = str(uuid.uuid4())
        retried["prior_failure"] = {"reason": failure_reason, "dispatch_id": payload["dispatch_id"]}
        validate_payload(retried)
        return {"retry": True, "payload": retried,
                "note": "One auto retry with the prior failure attached; a second failure routes to fstar-debug."}

    # -- interrupt --------------------------------------------------------

    def interrupt(self, dispatch_id: str, *, reason: str, mode: str,
                  task_ref: str = "session-only", tier: str = "checkpoint-stop",
                  release_lease_token: Optional[str] = None, extensions: Optional[list] = None) -> dict:
        """Register a stop intent and produce the propagation decision.

        This never changes the task phase; releasing the lease is the caller's
        explicit choice.
        """
        if mode not in {"change_propagation", "cancel", "checkpoint_stop"}:
            raise DomainError("invalid_interrupt_mode", "Unknown interrupt mode", {"mode": mode})
        if mode == "change_propagation":
            from .extensions import grants, includes
            records = (extensions or []) if task_ref == "session-only" else self.store.read(task_ref)["extensions"]
            if not includes(grants(records), "multi-agent", "change-propagation"):
                raise DomainError("extension_not_authorized", "Change propagation requires an included extension member", {"package": "multi-agent", "member": "change-propagation"}, status=3)
        change = build_change(source="conversation" if mode == "change_propagation" else "file",
                              origin=reason, action="pause_and_redispatch")
        decision = propagation_decision(tier, change)
        result = {"dispatch_id": dispatch_id, "reason": reason, "mode": mode,
                  "intent_registered": True, "propagation": decision}
        if task_ref != "session-only" and release_lease_token:
            self.tasks.release_lease(task_ref, token=release_lease_token, reason="interrupt: %s" % reason)
            result["lease_released"] = True
        return result

    # -- orphan recovery (read-only) ----------------------------------------

    def orphan_report(self, task_ref: str, *, workflow: bool = False) -> dict:
        """Read-only orphan report; the user decides takeover/redispatch/drop."""
        state = self.tasks.continue_task(task_ref, workflow=workflow)
        orphaned = bool(state.get("orphaned"))
        return {"status": "orphaned" if orphaned else state.get("next", "active"),
                "read_only": True,
                "next": "choose_takeover_replan_or_drop" if orphaned else state.get("next"),
                "note": "No automatic redispatch; the original worker is not assumed alive and its context is not assumed recovered.",
                "state": state}


def _load_json_file(path: Optional[str], label: str) -> dict:
    import json
    if not path:
        raise DomainError("file_required", "%s file is required" % label)
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as exc:
        raise DomainError("invalid_json_file", "Cannot read %s file" % label, {"path": path, "reason": str(exc)})
    if not isinstance(value, dict):
        raise DomainError("invalid_json_file", "%s file must contain an object" % label)
    return value


def _service_from_args(args, *, session_only: bool = False) -> DispatchService:
    if session_only:
        # The explicit project path, or otherwise the invocation working
        # directory, is the caller's file-fingerprint root. No metadata writes.
        root = Path(args.project).expanduser() if args.project else Path.cwd()
        return DispatchService(TaskStore(root))
    from .cli import _service
    tasks = _service(args)
    return DispatchService(tasks.store, task_service=tasks)


def register_commands(subparsers) -> None:
    """Register dispatch/interrupt/doc-edit on the CLI (AC-12)."""
    from .cli import OPTIONAL_HANDLER_ATTR

    dispatch = subparsers.add_parser("dispatch")
    dispatch.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_dispatch_usage})
    dispatch_sub = dispatch.add_subparsers(dest="dispatch_command", required=True)
    for role in ROLES:
        role_parser = dispatch_sub.add_parser(role)
        role_parser.add_argument("--payload")
        role_parser.add_argument("--extension", action="append", default=[])
        role_parser.add_argument("--task-ref")
        role_parser.add_argument("--plan-item", action="append", default=[])
        role_parser.add_argument("--allowed-path", action="append", default=[])
        role_parser.add_argument("--coordinator", default="coordinator")
        role_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_dispatch})
    harvest = dispatch_sub.add_parser("harvest")
    harvest.add_argument("--result", required=True)
    harvest.add_argument("--payload", required=True)
    harvest.add_argument("--lease-token", required=True)
    harvest.add_argument("--check-evidence")
    harvest.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_harvest})
    retry = dispatch_sub.add_parser("retry")
    retry.add_argument("--payload", required=True)
    retry.add_argument("--reason", required=True)
    retry.add_argument("--environment-blocked", action="store_true")
    retry.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_retry})

    # Parallel reservation surface: `dispatch` SUBcommands only, so the
    # parent command face is unchanged (no new top-level command). These are
    # the optional multi-agent/parallel-implement entries; the minimal
    # single implement/check loop never touches them.
    reserve = dispatch_sub.add_parser("reserve")
    reserve.add_argument("--payload", action="append", default=[], required=True)
    reserve.add_argument("--plan-items")
    reserve.add_argument("--coordinator", default="coordinator")
    reserve.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_reserve})

    confirm = dispatch_sub.add_parser("confirm-launch")
    confirm.add_argument("task", nargs="?")
    confirm.add_argument("--dispatch-id", action="append", default=[], required=True)
    confirm.add_argument("--coordinator", default="coordinator")
    confirm.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_confirm_launch})

    reservations = dispatch_sub.add_parser("reservations")
    reservations.add_argument("task", nargs="?")
    reservations.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_reservations})

    release = dispatch_sub.add_parser("release-reservation")
    release.add_argument("task", nargs="?")
    release.add_argument("--dispatch-id", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--coordinator", default="coordinator")
    release.add_argument("--lease-token")
    release.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_release_reservation})

    interrupt = subparsers.add_parser("interrupt")
    interrupt.add_argument("task", nargs="?")
    interrupt.add_argument("--dispatch-id", required=True)
    interrupt.add_argument("--reason", required=True)
    interrupt.add_argument("--mode", choices=("change_propagation", "cancel", "checkpoint_stop"), default="checkpoint_stop")
    interrupt.add_argument("--tier", choices=CAPABILITY_TIERS, default="checkpoint-stop")
    interrupt.add_argument("--release-lease-token")
    interrupt.add_argument("--extension", action="append", default=[])
    interrupt.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_interrupt})

    doc_edit = subparsers.add_parser("doc-edit")
    doc_edit.add_argument("task", nargs="?")
    doc_edit.add_argument("--payload")
    doc_edit.add_argument("--extension", action="append", default=[])
    doc_edit.add_argument("--file")
    doc_edit.add_argument("--item", action="append", default=[])
    doc_edit.add_argument("--baseline")
    doc_edit.add_argument("--task-ref")
    doc_edit.add_argument("--plan-item", action="append", default=[])
    doc_edit.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_doc_edit})

    # Orphan recovery is the parent command face's `continue` behavior
    # (parent design §4.1: continue reports orphans read-only and the user
    # decides takeover/redispatch/drop). There is deliberately NO standalone
    # top-level `fstar orphan` command; this subcommand only shapes the
    # read-only report for the coordinator.
    orphan = dispatch_sub.add_parser("orphan")
    orphan.add_argument("task")
    orphan.add_argument("--workflow", action="store_true")
    orphan.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_orphan})


def _handle_dispatch_usage(args):
    raise DomainError("dispatch_role_required", "Choose a dispatch role: implement|check|research|editor", status=2)


def _require_list_or_json_entry(entry: object, label: str) -> dict:
    """One shared payload extension record: explicit JSON or an env/file entry.

    Session-only callers have no shared store across CLI invocations, so the
    grant stays in the caller's session and is passed as a JSON extension
    record. An ``@path`` entry is kept explicit rather than silently defaulting
    to a local ``.extensions.json`` file, so no host writes are implied.
    """
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, str) and entry.startswith("@"):
        return _load_json_file(entry[1:], label)
    if isinstance(entry, str):
        try:
            parsed = json.loads(entry)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    raise DomainError("invalid_extension", "Extension context entry must be a JSON object or @path")




def _handle_dispatch(args):
    payload = _load_json_file(args.payload, "payload") if args.payload else None
    if payload is None:
        if not args.task_ref or not args.allowed_path:
            raise DomainError("payload_required", "Provide --payload FILE or --task-ref with --allowed-path entries; pass session grants as repeated --extension JSON records or @path entries")
        payload = build_payload(role=args.dispatch_command, task_ref=args.task_ref,
                                plan_item_ids=args.plan_item,
                                allowed_paths=args.allowed_path,
                                baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
                                extensions=[_require_list_or_json_entry(entry, "extension") for entry in (args.extension or [])])
    elif args.extension:
        payload = dict(payload, extensions=[_require_list_or_json_entry(entry, "extension") for entry in args.extension])
    service = _service_from_args(args, session_only=payload.get("task_ref") == "session-only")
    actor = {"role": "coordinator", "id": args.coordinator, "session": getattr(args, "session", None)}
    return service.register(payload, coordinator_id=args.coordinator, actor=actor)


def _handle_harvest(args):
    result = _load_json_file(args.result, "result")
    payload = _load_json_file(args.payload, "payload")
    check_evidence = _load_json_file(args.check_evidence, "check evidence") if args.check_evidence else None
    service = _service_from_args(args, session_only=payload.get("task_ref") == "session-only")
    return service.harvest(result, payload, lease_token=args.lease_token, check_evidence=check_evidence)


def _handle_retry(args):
    # Pure protocol decision; no store or project is needed, so it works in
    # any directory without touching the filesystem.
    payload = _load_json_file(args.payload, "payload")
    service = DispatchService.__new__(DispatchService)
    return service.retry_dispatch(payload, failure_reason=args.reason, environment_blocked=args.environment_blocked)


def _handle_reserve(args):
    payloads = [_load_json_file(path, "payload") for path in args.payload]
    plan_items = _load_json_file(args.plan_items, "plan items").get("items", []) if args.plan_items else []
    task_ref = payloads[0].get("task_ref")
    service = _service_from_args(args, session_only=task_ref == "session-only")
    actor = {"role": "coordinator", "id": args.coordinator, "session": getattr(args, "session", None)}
    return service.reserve_parallel(payloads, coordinator_id=args.coordinator, actor=actor,
                                     plan_items=plan_items)


def _handle_confirm_launch(args):
    task_ref = args.task or "session-only"
    service = _service_from_args(args, session_only=task_ref == "session-only")
    return service.confirm_launch(task_ref, args.dispatch_id, coordinator_id=args.coordinator)


def _handle_reservations(args):
    task_ref = args.task or "session-only"
    service = _service_from_args(args, session_only=task_ref == "session-only")
    return service.parallel_reservation_report(task_ref)


def _handle_release_reservation(args):
    task_ref = args.task or "session-only"
    service = _service_from_args(args, session_only=task_ref == "session-only")
    return service.release_reservation(task_ref, args.dispatch_id, reason=args.reason,
                                        coordinator_id=args.coordinator, lease_token=args.lease_token)


def _handle_interrupt(args):
    task_ref = args.task or "session-only"
    service = _service_from_args(args, session_only=task_ref == "session-only")
    return service.interrupt(args.dispatch_id, reason=args.reason, mode=args.mode,
                             task_ref=task_ref, tier=args.tier,
                             release_lease_token=args.release_lease_token,
                             extensions=[_require_list_or_json_entry(entry, "extension") for entry in args.extension])


def _handle_doc_edit(args):
    payload = _load_json_file(args.payload, "payload") if args.payload else None
    if payload is None:
        if not args.file or not args.item or not args.baseline:
            raise DomainError("payload_required", "Provide --payload FILE or --file with --item and --baseline")
        task_ref = args.task_ref or (args.task or "session-only")
        payload = build_payload(role="editor", task_ref=task_ref,
                                plan_item_ids=args.plan_item,
                                allowed_paths=[args.file], item_ids=args.item,
                                baseline_sha256=args.baseline,
                                baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
                                extensions=[_require_list_or_json_entry(entry, "extension") for entry in (args.extension or [])])
    elif args.extension:
        payload = dict(payload, extensions=[_require_list_or_json_entry(entry, "extension") for entry in args.extension])
    service = _service_from_args(args, session_only=payload.get("task_ref") == "session-only")
    validate_payload(payload)
    if payload["role"] != "editor":
        raise DomainError("invalid_dispatch_payload", "doc-edit requires an editor payload")
    service.authorize_role(payload)
    if payload["task_ref"] != "session-only":
        payload = dict(payload, extensions=service.store.read(payload["task_ref"])["extensions"])
    return {"payload": payload, "adapter": adapter_invocation_note()}


def _handle_orphan(args):
    # Read-only report used by the coordinator alongside `fstar continue`;
    # no standalone user-facing lifecycle command is added (parent design §4.1).
    service = _service_from_args(args)
    return service.orphan_report(args.task, workflow=args.workflow)
