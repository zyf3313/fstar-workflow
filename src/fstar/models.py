from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict

TASK_FIELDS = (
    "id", "name", "title", "description", "phase", "blocked", "evidence",
    "lease", "acceptance", "completedAt", "archivedAt", "children",
    "priority", "creator", "assignee", "createdAt", "branch", "base_branch",
    "worktree_path", "commit", "pr_url", "notes", "meta", "capabilities",
    "extensions", "events",
)
# Optional collaboration fields (design §4): all may be absent; absence means
# the default (status "active", no work items / next step / deliverables).
# They sit at the top level next to `phase` and never enter source_snapshot.
# `origin` (antigravity-adoption design §1) marks the parent requirement task
# a follow-up task grew from: {task_id, archive_path, reason}. Absent origin =
# pre-origin behavior, so old task.json files read and write unchanged.
OPTIONAL_TASK_FIELDS = ("status", "status_detail", "work_items", "next_step", "deliverables", "origin")
STATUSES = {"active", "waiting_user", "waiting_external", "paused"}
WORK_ITEM_STATES = {"done", "active", "blocked", "cancelled"}
PHASES = {"planning", "in_progress", "awaiting_acceptance", "completed"}
# Order of the lifecycle for effective-state reporting and guards.
PHASE_ORDER = {"planning": 0, "in_progress": 1, "awaiting_acceptance": 2, "completed": 3}
PRIORITIES = {"P0", "P1", "P2", "P3"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: Any = None, *, status: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}
        self.status = status

    def as_dict(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def valid_name(name: str) -> bool:
    return bool(isinstance(name, str) and NAME_RE.fullmatch(name) and name not in {".", ".."})


def new_task(name: str, title: str, description: str, *, creator: str, now: str) -> dict:
    if not valid_name(name):
        raise DomainError("invalid_name", "Task name must be a safe relative directory name", {"name": name})
    if not isinstance(title, str) or not title.strip():
        raise DomainError("invalid_title", "Task title must be non-empty")
    if not isinstance(creator, str) or not creator.strip():
        raise DomainError("invalid_creator", "Task creator must be non-empty")
    task = {
        "id": str(uuid.uuid4()), "name": name, "title": title.strip(),
        "description": description or "", "phase": "planning", "blocked": None,
        "evidence": [], "lease": None, "acceptance": None,
        "completedAt": None, "archivedAt": None, "children": [],
        "priority": "P2", "creator": creator, "assignee": None,
        "createdAt": now, "branch": "", "base_branch": "", "worktree_path": "",
        "commit": "", "pr_url": "", "notes": "", "meta": {},
        "capabilities": [], "extensions": [], "events": [],
    }
    validate_task(task)
    return task


def _is_iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _string_list(value: object, label: str) -> list:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise TypeError("%s must be an array of strings" % label)
    return list(value)


def work_item(item: dict) -> dict:
    """Normalized work item: id/state/summary/evidence_refs."""
    return {"id": str(item["id"]), "state": item["state"],
            "summary": item.get("summary", ""),
            "evidence_refs": _string_list(item.get("evidence_refs", []), "evidence_refs")}


def deliverable(entry: dict) -> dict:
    """Normalized deliverable registration entry (design §4)."""
    return {"name": entry["name"], "path": entry["path"],
            "format": entry.get("format", ""),
            "criteria_refs": _string_list(entry.get("criteria_refs", []), "criteria_refs"),
            "version": entry.get("version", "")}


def validate_optional_fields(data: dict) -> None:
    """Validate the optional collaboration fields; absent fields are valid."""
    status = data.get("status")
    if status is not None and status not in STATUSES:
        raise DomainError("invalid_status", "status must be active, waiting_user, waiting_external, or paused", {"status": status})
    detail = data.get("status_detail")
    if detail is not None:
        if not (isinstance(detail, dict)
                and isinstance(detail.get("reason"), str) and detail["reason"].strip()
                and _is_iso_timestamp(detail.get("since"))):
            raise DomainError("invalid_status_detail", "status_detail requires a non-empty reason and an ISO since timestamp")
        unknown = sorted(set(detail) - {"reason", "since"})
        if unknown:
            raise DomainError("invalid_status_detail", "status_detail contains unknown keys", {"unknown": unknown})
    items = data.get("work_items")
    if items is not None:
        if not isinstance(items, list):
            raise DomainError("invalid_work_items", "work_items must be an array")
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise DomainError("invalid_work_items", "work_items entries must be objects")
            if not isinstance(item.get("id"), str) or not item["id"].strip():
                raise DomainError("invalid_work_items", "work_items entries require a non-empty string id")
            if item["id"] in seen:
                raise DomainError("invalid_work_items", "work_items ids must be unique", {"id": item["id"]})
            seen.add(item["id"])
            if item.get("state") not in WORK_ITEM_STATES:
                raise DomainError("invalid_work_items", "work item state must be done, active, blocked, or cancelled", {"id": item.get("id"), "state": item.get("state")})
            if not isinstance(item.get("summary"), str):
                raise DomainError("invalid_work_items", "work item summary must be a string", {"id": item["id"]})
            refs = item.get("evidence_refs", [])
            if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
                raise DomainError("invalid_work_items", "work item evidence_refs must be an array of strings", {"id": item["id"]})
            unknown = sorted(set(item) - {"id", "state", "summary", "evidence_refs"})
            if unknown:
                raise DomainError("invalid_work_items", "work item contains unknown keys", {"id": item["id"], "unknown": unknown})
    next_step = data.get("next_step")
    if next_step is not None:
        if not (isinstance(next_step, dict)
                and isinstance(next_step.get("condition"), str) and next_step["condition"].strip()
                and isinstance(next_step.get("action"), str) and next_step["action"].strip()):
            raise DomainError("invalid_next_step", "next_step requires non-empty condition and action strings")
        unknown = sorted(set(next_step) - {"condition", "action"})
        if unknown:
            raise DomainError("invalid_next_step", "next_step contains unknown keys", {"unknown": unknown})
    entries = data.get("deliverables")
    if entries is not None:
        if not isinstance(entries, list):
            raise DomainError("invalid_deliverables", "deliverables must be an array")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise DomainError("invalid_deliverables", "deliverables entries must be objects")
            for key in ("name", "path", "format", "version"):
                if not isinstance(entry.get(key), str):
                    raise DomainError("invalid_deliverables", "deliverable %s must be a string" % key)
            if not entry["name"].strip() or not entry["path"].strip():
                raise DomainError("invalid_deliverables", "deliverables entries require non-empty name and path")
            if entry["name"] in seen:
                raise DomainError("invalid_deliverables", "deliverables names must be unique", {"name": entry["name"]})
            seen.add(entry["name"])
            refs = entry.get("criteria_refs", [])
            if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
                raise DomainError("invalid_deliverables", "deliverable criteria_refs must be an array of strings", {"name": entry["name"]})
            unknown = sorted(set(entry) - {"name", "path", "format", "criteria_refs", "version"})
            if unknown:
                raise DomainError("invalid_deliverables", "deliverable contains unknown keys", {"name": entry["name"], "unknown": unknown})


    origin = data.get("origin")
    if origin is not None:
        if not isinstance(origin, dict):
            raise DomainError("invalid_origin", "origin must be an object")
        unknown = sorted(set(origin) - {"task_id", "archive_path", "reason"})
        if unknown:
            raise DomainError("invalid_origin", "origin contains unknown keys", {"unknown": unknown})
        if not isinstance(origin.get("task_id"), str) or not origin["task_id"].strip():
            raise DomainError("invalid_origin", "origin requires a non-empty task_id")
        if not isinstance(origin.get("archive_path"), str) or not origin["archive_path"].strip():
            raise DomainError("invalid_origin", "origin requires a non-empty archive_path")
        if not isinstance(origin.get("reason"), str):
            raise DomainError("invalid_origin", "origin reason must be a string")


def validate_task(data: dict) -> None:
    if not isinstance(data, dict):
        raise DomainError("invalid_task", "task.json must contain a JSON object")
    unknown = sorted(set(data) - set(TASK_FIELDS) - set(OPTIONAL_TASK_FIELDS))
    missing = sorted(set(TASK_FIELDS) - set(data))
    if unknown or missing:
        raise DomainError("invalid_task_fields", "task.json must contain the required top-level fields", {"missing": missing, "unknown": unknown})
    if not isinstance(data["id"], str):
        raise DomainError("invalid_id", "id must be a UUID string")
    try:
        uuid.UUID(data["id"])
    except (ValueError, AttributeError):
        raise DomainError("invalid_id", "id must be a UUID string")
    if not valid_name(data["name"]):
        raise DomainError("invalid_name", "Task name is invalid", {"name": data["name"]})
    for key in ("title", "creator", "createdAt"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise DomainError("invalid_task", "%s must be a non-empty string" % key)
    for key in ("description", "branch", "base_branch", "worktree_path", "commit", "pr_url", "notes"):
        if not isinstance(data[key], str):
            raise DomainError("invalid_task", "%s must be a string" % key)
    if data["phase"] not in PHASES:
        raise DomainError("invalid_phase", "Task phase is invalid", {"phase": data["phase"]})
    if data["priority"] not in PRIORITIES:
        raise DomainError("invalid_priority", "Task priority is invalid")
    if data["assignee"] is not None and not isinstance(data["assignee"], str):
        raise DomainError("invalid_task", "assignee must be null or a string")
    for key in ("completedAt", "archivedAt"):
        if data[key] is not None and not isinstance(data[key], str):
            raise DomainError("invalid_task", "%s must be null or a timestamp string" % key)
    for key in ("evidence", "children", "capabilities", "extensions", "events"):
        if not isinstance(data[key], list):
            raise DomainError("invalid_task", "%s must be an array" % key)
    if len(set(data["children"])) != len(data["children"]) or not all(valid_name(x) for x in data["children"]):
        raise DomainError("invalid_children", "children must contain unique safe names")
    blocked = data["blocked"]
    if blocked is not None and not (isinstance(blocked, dict) and isinstance(blocked.get("reason"), str) and blocked.get("reason") and isinstance(blocked.get("since"), str) and blocked.get("since")):
        raise DomainError("invalid_blocked", "blocked must be null or contain string reason and since")
    for key in ("lease", "acceptance"):
        if data[key] is not None and not isinstance(data[key], dict):
            raise DomainError("invalid_task", "%s must be null or an object" % key)
    if not isinstance(data["meta"], dict):
        raise DomainError("invalid_meta", "meta must be an object")
    if not all(isinstance(item, dict) for item in data["evidence"] + data["capabilities"] + data["extensions"] + data["events"]):
        raise DomainError("invalid_task", "evidence, capabilities, extensions, and events entries must be objects")
    for capability in data["capabilities"]:
        if {"enabled_at", "scope", "included", "excluded"} & set(capability):
            raise DomainError("invalid_capability", "capabilities entries cannot contain extension authorization fields")
    for extension in data["extensions"]:
        required = {"id", "enabled_at", "source", "scope", "included", "excluded", "reason"}
        if set(extension) != required or extension.get("scope") not in {"full", "custom"} or not isinstance(extension.get("source"), dict) or not isinstance(extension.get("included"), list) or not isinstance(extension.get("excluded"), list):
            raise DomainError("invalid_extension", "extension entries do not match the v1 schema")
    for event in data["events"]:
        if set(event) != {"id", "at", "source", "type", "data"} or not isinstance(event.get("source"), dict) or not isinstance(event.get("data"), dict):
            raise DomainError("invalid_event", "event entries do not match the v1 envelope")
    validate_optional_fields(data)
