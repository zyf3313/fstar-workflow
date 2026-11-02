from __future__ import annotations

import re
import uuid
from typing import Any, Dict

TASK_FIELDS = (
    "id", "name", "title", "description", "phase", "blocked", "evidence",
    "lease", "acceptance", "completedAt", "archivedAt", "children",
    "priority", "creator", "assignee", "createdAt", "branch", "base_branch",
    "worktree_path", "commit", "pr_url", "notes", "meta", "capabilities",
    "extensions", "events",
)
PHASES = {"planning", "in_progress", "completed"}
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


def validate_task(data: dict) -> None:
    if not isinstance(data, dict):
        raise DomainError("invalid_task", "task.json must contain a JSON object")
    unknown = sorted(set(data) - set(TASK_FIELDS))
    missing = sorted(set(TASK_FIELDS) - set(data))
    if unknown or missing:
        raise DomainError("invalid_task_fields", "task.json must contain exactly 26 top-level fields", {"missing": missing, "unknown": unknown})
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
