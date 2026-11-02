from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .evidence import EvidenceService
from .models import DomainError, new_task, valid_name
from .store import TaskStore, content_hash

LEASE_MINUTES = 30
EVENT_LIMIT = 200
MILESTONES = {"started", "replanned", "lease_taken_over", "review_recorded", "accepted", "dropped", "revived", "archived", "extension_enabled", "extension_changed"}
EXTENSIONS = {
    "planning-review": {"clarify", "prd", "design", "plan", "editor", "doc-check"},
    "persistent-task": {"task", "evidence", "lease", "events", "recovery", "archive"},
    "multi-agent": {"research", "parallel-implement", "version-injection", "change-propagation"},
    "project-governance": {"specs", "knowledge", "rules", "memory"},
    "tool-capability": {"contracts", "bindings", "classification", "validation", "fallback"},
}


def _require_workflow_member(task: dict, member: str) -> None:
    from .extensions import grants, includes
    if not includes(grants(task["extensions"]), "persistent-task", member):
        raise DomainError("extension_not_authorized", "Workflow operation requires an included extension member",
                          {"package": "persistent-task", "member": member}, status=3)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def plus_minutes(value: str, minutes: int) -> str:
    return (parse_time(value) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def source_snapshot(task: dict) -> str:
    return content_hash({"task_id": task["id"], "phase": task["phase"], "description": task["description"], "templates": task.get("meta", {}).get("templates", {})})


def validate_source(source: dict, task: dict, *, actor: Optional[dict] = None) -> None:
    required = {"source_id", "type", "at", "actor", "reference", "quote", "scope", "validates"}
    missing = sorted(required - set(source or {}))
    if missing:
        raise DomainError("invalid_confirmation", "Confirmation source is incomplete", {"missing": missing}, status=3)
    if source["type"] not in {"command", "conversation", "review"}:
        raise DomainError("invalid_confirmation", "Unknown confirmation source type", status=3)
    if source["type"] == "conversation" and (not source["quote"] or not source["reference"]):
        raise DomainError("invalid_confirmation", "Conversation confirmation requires the user quote and reference", status=3)
    if source["type"] == "command" and actor and actor.get("role") != "user":
        raise DomainError("invalid_confirmation", "An agent cannot record its invocation as a direct user command", status=3)
    if source["type"] == "review":
        review = next((item for item in task.get("evidence", []) if item.get("id") == source["reference"] and item.get("kind") == "review"), None)
        if not review or review.get("state") != "valid" or review.get("verdict") != "approved" or review.get("producer", {}).get("role") != "user":
            raise DomainError("invalid_confirmation", "Review confirmation must reference a current approved user review", {"reference": source.get("reference")}, status=3)
    if source["validates"] != source_snapshot(task):
        raise DomainError("stale_confirmation", "Confirmation does not bind the current task snapshot", {"expected": source_snapshot(task), "actual": source["validates"]}, status=3)


def make_event(event_type: str, source: dict, data: dict, now: str) -> dict:
    return {"id": str(uuid.uuid4()), "at": now, "source": source, "type": event_type, "data": data}


def compact_events(events: list) -> list:
    if len(events) <= EVENT_LIMIT:
        return events
    ordinary_indexes = [i for i, event in enumerate(events) if event.get("type") not in MILESTONES and event.get("type") != "summary"]
    summary_index = next((i for i, event in enumerate(events) if event.get("type") == "summary"), None)
    if summary_index is not None:
        # Fold into the existing summary so compaction never grows the summary
        # count; no replacement event is inserted.
        remove_count = len(events) - EVENT_LIMIT
        selected = ordinary_indexes[:max(remove_count, 0)]
        if not selected:
            return events
        summary = events[summary_index]
        removed = [events[i] for i in selected]
        data = summary.setdefault("data", {})
        data["count"] = data.get("count", 0) + len(removed)
        by_type = data.setdefault("by_type", {})
        for event in removed:
            name = event.get("type", "unknown")
            by_type[name] = by_type.get(name, 0) + 1
        data["last_at"] = removed[-1].get("at")
        data["last_id"] = removed[-1].get("id")
        selected_set = set(selected)
        return [event for i, event in enumerate(events) if i not in selected_set]
    remove_count = len(events) - EVENT_LIMIT + 1
    selected = ordinary_indexes[:max(remove_count, 0)]
    if not selected:
        return events
    removed = [events[i] for i in selected]
    counts = {}
    for event in removed:
        counts[event.get("type", "unknown")] = counts.get(event.get("type", "unknown"), 0) + 1
    summary = make_event("summary", {"type": "system", "reference": "event-compaction"}, {"count": len(removed), "by_type": counts, "first_at": removed[0].get("at"), "last_at": removed[-1].get("at"), "first_id": removed[0].get("id"), "last_id": removed[-1].get("id")}, removed[-1].get("at"))
    selected_set = set(selected)
    remaining = [event for i, event in enumerate(events) if i not in selected_set]
    remaining.insert(0, summary)
    return remaining


class TaskService:
    def __init__(self, store: TaskStore, *, clock: Optional[Callable[[], str]] = None):
        self.store = store
        self.clock = clock or utc_now
        self.evidence = EvidenceService(store, clock=self.clock)

    def _write(self, task_dir: Path, task: dict) -> None:
        task["events"] = compact_events(task["events"])
        self.store.write(task_dir, task)

    def _event(self, task: dict, event_type: str, source: dict, data: dict) -> None:
        task["events"].append(make_event(event_type, source, data, self.clock()))

    def _require_unleased(self, task: dict, operation: str) -> None:
        lease = task.get("lease")
        if lease and lease.get("expires_at", "") > self.clock():
            raise DomainError("lease_conflict", "%s cannot mutate a task with an active writer" % operation, {"holder": lease.get("holder")}, status=4)

    def _require_active(self, task: dict, operation: str) -> None:
        if task.get("meta", {}).get("disposition"):
            raise DomainError("task_dropped", "%s is refused while the task carries a drop disposition; revive it explicitly" % operation, status=3)

    def _actor_source(self, actor: dict, reference: str) -> dict:
        # Machine/system action envelope: never label an agent action as a
        # direct user command (design §5.3).
        return {"source_id": str(uuid.uuid4()), "type": "system", "at": self.clock(), "actor": actor, "reference": reference, "quote": "", "scope": reference, "validates": ""}

    def _children_consistency(self, task_dir: Path, task: dict) -> list:
        subtasks = task_dir / "subtasks"
        actual = sorted(p.name for p in subtasks.iterdir() if p.is_dir() and not p.is_symlink() and (p / "task.json").is_file()) if subtasks.exists() else []
        expected = sorted(task["children"])
        if actual != expected:
            raise DomainError("children_inconsistent", "children does not match nested task directories", {"expected": expected, "actual": actual}, status=3)
        return actual

    def create(self, *, name: str, title: str, description: str, actor: dict, parent: Optional[str] = None, related: Optional[list] = None, session_id: Optional[str] = None) -> dict:
        if actor.get("role") not in {"user", "agent"} or not actor.get("id"):
            raise DomainError("invalid_actor", "Creating a task requires a declared actor")
        with self.store.transaction():
            now = self.clock()
            task = new_task(name, title, description, creator=actor["id"], now=now)
            task["meta"] = {"disposition": None, "templates": {}, "related_tasks": [], "reminders": {}}
            if related:
                for relation in related:
                    archive_path = Path(relation.get("archive_path", ""))
                    if not archive_path.is_absolute():
                        archive_path = self.store.project_root / archive_path
                    try:
                        archive_path.resolve().relative_to(self.store.archive_root.resolve())
                    except ValueError:
                        raise DomainError("invalid_related_task", "Related task must point inside the archive")
                    related_dir = archive_path if archive_path.name != "task.json" else archive_path.parent
                    if not (related_dir / "task.json").is_file():
                        raise DomainError("invalid_related_task", "Related archived task does not exist")
                    archived = self.store._read_path(related_dir / "task.json")
                    if archived["id"] != relation.get("id"):
                        raise DomainError("invalid_related_task", "Related task id does not match archive path")
                    task["meta"]["related_tasks"].append({"id": archived["id"], "archive_path": str(related_dir.relative_to(self.store.project_root)), "relation": relation.get("relation", "follow_up"), "reason": relation.get("reason", "")})
            self._event(task, "created", self._actor_source(actor, "task create"), {"parent": parent})
            if parent:
                parent_dir = self.store.resolve(parent)
                parent_task = self.store._read_path(parent_dir / "task.json")
                self._children_consistency(parent_dir, parent_task)
                if name in parent_task["children"]:
                    raise DomainError("task_exists", "Child task already exists", status=4)
                task_dir = parent_dir / "subtasks" / name
            else:
                task_dir = self.store.tasks_root / name
            if task_dir.exists() or task_dir.is_symlink():
                raise DomainError("task_exists", "Task destination already exists", {"path": str(task_dir)}, status=4)
            staging = task_dir.parent / (".%s.staging-%s" % (name, uuid.uuid4().hex))
            published = False
            try:
                staging.mkdir(parents=True)
                self.store.write(staging, task)
                os.rename(str(staging), str(task_dir))
                published = True
                if parent:
                    parent_task["children"].append(name)
                    self.store.write(parent_dir, parent_task)
            except Exception:
                if staging.exists():
                    shutil.rmtree(str(staging))
                if published and task_dir.exists():
                    # The child may already be registered if the parent write
                    # partially succeeded; only remove an unregistered directory.
                    try:
                        parent_on_disk = self.store._read_path(parent_dir / "task.json")
                    except DomainError:
                        parent_on_disk = {}
                    if name not in parent_on_disk.get("children", []):
                        shutil.rmtree(str(task_dir))
                raise
            if session_id:
                self.store.set_current(session_id, task_dir, task["id"])
            return {"task": task, "path": str(task_dir)}

    def list_tasks(self, *, archived: bool = False, query: Optional[str] = None) -> list:
        rows = self.store.scan(archived=archived)
        if query:
            value = query.lower()
            rows = [row for row in rows if value in row["name"].lower() or value in row["title"].lower()]
        return rows

    def current(self, session_id: Optional[str]) -> dict:
        pointer = self.store.current(session_id)
        if not pointer:
            return {"current": None, "status": "no_current"}
        try:
            task_dir = self.store.resolve(pointer["task_id"])
            task = self.store._read_path(task_dir / "task.json")
            return {"current": task, "path": str(task_dir)}
        except DomainError as exc:
            return {"current": None, "status": "stale_pointer", "details": exc.details}

    def start(self, ref: str, *, actor: dict, confirmation: dict, session_id: Optional[str] = None) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._children_consistency(task_dir, task)
            if task["phase"] == "in_progress":
                existing = [e for e in task["events"] if e.get("type") == "started" and e.get("source", {}).get("source_id") == confirmation.get("source_id")]
                if existing:
                    return task
            if task["phase"] != "planning" or task.get("blocked") or task.get("meta", {}).get("disposition"):
                raise DomainError("start_blocked", "Task cannot be started from its current state", status=3)
            validate_source(confirmation, task, actor=actor)
            if any(ext["id"] == "planning-review" and
                   {"prd", "design"}.intersection(ext["included"])
                   for ext in task["extensions"]):
                templates = task.get("meta", {}).get("templates", {})
                if not templates.get("artifact_map"):
                    raise DomainError("planning_artifacts_missing", "Planning review requires mapped current planning artifacts", status=3)
            task["phase"] = "in_progress"
            self._event(task, "started", confirmation, {"snapshot": source_snapshot(task)})
            self._write(task_dir, task)
            if session_id:
                self.store.set_current(session_id, task_dir, task["id"])
            return task

    def acquire_lease(self, ref: str, *, holder: str, role: str, takeover_reason: Optional[str] = None, actor: Optional[dict] = None, workflow_recovery: bool = False) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if workflow_recovery:
                _require_workflow_member(task, "recovery")
            if task["phase"] != "in_progress" or task.get("meta", {}).get("disposition"):
                raise DomainError("lease_not_allowed", "A lease requires an active task", status=3)
            now = self.clock()
            old = task.get("lease")
            if old and old.get("expires_at", "") > now and not takeover_reason:
                raise DomainError("lease_conflict", "Task already has an active writer", {"holder": old.get("holder")}, status=4)
            token = str(uuid.uuid4())
            holder_data = {"id": holder, "role": role, "session": (actor or {}).get("session")}
            takeovers = list(old.get("takeovers", [])) if old else []
            event_type = "lease_acquired"
            if old:
                if not takeover_reason:
                    takeover_reason = "expired lease"
                takeovers.append({"at": now, "from": old.get("holder"), "to": holder_data, "reason": takeover_reason})
                event_type = "lease_taken_over"
            task["lease"] = {"holder": holder_data, "token": token, "acquired_at": now, "expires_at": plus_minutes(now, LEASE_MINUTES), "takeovers": takeovers}
            self._event(task, event_type, self._actor_source(actor or holder_data, "lease"), {"old_holder": old.get("holder") if old else None, "new_holder": holder_data, "reason": takeover_reason})
            self._write(task_dir, task)
            return task["lease"]

    def renew_lease(self, ref: str, *, token: str) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            lease = task.get("lease")
            now = self.clock()
            if not lease or lease.get("token") != token:
                raise DomainError("invalid_lease", "Lease token is no longer current", status=4)
            if lease["expires_at"] <= now:
                raise DomainError("expired_lease", "Expired lease cannot be renewed", status=4)
            lease["expires_at"] = plus_minutes(now, LEASE_MINUTES)
            self._event(task, "lease_renewed", lease["holder"], {"expires_at": lease["expires_at"]})
            self._write(task_dir, task)
            return lease

    def release_lease(self, ref: str, *, token: str, reason: str) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            lease = task.get("lease")
            if not lease or lease.get("token") != token:
                raise DomainError("invalid_lease", "Lease token is no longer current", status=4)
            self._event(task, "lease_released", lease["holder"], {"reason": reason})
            task["lease"] = None
            self._write(task_dir, task)
            return task

    def set_blocked(self, ref: str, *, actor: dict, reason: Optional[str], workflow_recovery: bool = False) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if workflow_recovery:
                _require_workflow_member(task, "recovery")
            self._require_active(task, "set_blocked")
            self._require_unleased(task, "set_blocked")
            previous = task.get("blocked")
            if reason:
                task["blocked"] = {"reason": reason, "since": self.clock(), "by": actor}
                event_type = "blocked"
            else:
                if previous and previous.get("by", {}).get("role") == "user" and actor.get("role") != "user":
                    raise DomainError("unblock_forbidden", "Only a user may clear a user-set block", status=3)
                if previous and previous.get("by", {}).get("id") == actor.get("id") and actor.get("role") != "user":
                    raise DomainError("unblock_forbidden", "An agent cannot clear its own block", status=3)
                task["blocked"] = None
                event_type = "unblocked"
            self._event(task, event_type, self._actor_source(actor, event_type), {"reason": reason or (previous or {}).get("reason")})
            self._write(task_dir, task)
            return task

    def state(self, ref: str) -> dict:
        task_dir = self.store.resolve(ref)
        task = self.store._read_path(task_dir / "task.json")
        children = self._children_consistency(task_dir, task)
        child_states = []
        for name in children:
            child = self.store._read_path(task_dir / "subtasks" / name / "task.json")
            child_states.append({"name": name, "phase": child["phase"], "dropped": bool(child.get("meta", {}).get("disposition"))})
        effective = task["phase"]
        order = {"planning": 0, "in_progress": 1, "completed": 2}
        active = [x["phase"] for x in child_states if not x["dropped"]]
        if active and min(order[x] for x in active) < order[effective]:
            effective = min(active, key=lambda x: order[x])
        acceptance = self.evidence.acceptance_status(ref, task=task)
        if any(not (child["dropped"] or child["phase"] == "completed") for child in child_states):
            acceptance["blockers"].append("children_incomplete")
            acceptance["awaiting_acceptance"] = False
        if task["phase"] == "completed":
            accepted = set((task.get("acceptance") or {}).get("evidence_refs", []))
            if not accepted or not accepted <= set(acceptance["evidence_refs"]):
                # The completion basis changed after acceptance; reads report
                # the derived difference without writing it.
                acceptance["stale"] = True
                acceptance["blockers"].append("acceptance_stale")
                effective = "in_progress"
        return {"task_id": task["id"], "phase": task["phase"], "effective_phase": effective, "blocked": task["blocked"], "disposition": task.get("meta", {}).get("disposition"), "lease": task["lease"], "evidence": task["evidence"], "extensions": task["extensions"], "children": child_states, "acceptance": acceptance}

    def continue_task(self, ref: Optional[str], *, session_id: Optional[str] = None, action: Optional[str] = None, actor: Optional[dict] = None, confirmation: Optional[dict] = None, reason: Optional[str] = None, workflow: bool = False) -> dict:
        if not ref:
            current = self.current(session_id)
            if not current.get("current"):
                return {"status": "no_task", "next": "select_or_create_task"}
            ref = current["current"]["id"]
        if not action:
            if workflow:
                _require_workflow_member(self.store.read(ref), "recovery")
            state = self.state(ref)
            lease = state.get("lease")
            if lease and lease.get("expires_at", "") <= self.clock():
                state["orphaned"] = True
                state["next"] = "choose_takeover_replan_or_drop"
            elif lease:
                state["next"] = "active_worker_do_not_redispatch"
            elif state["phase"] == "planning":
                state["next"] = "start"
            elif state["acceptance"]["awaiting_acceptance"]:
                state["next"] = "accept"
            else:
                state["next"] = "implement_or_check"
            return state
        if not actor:
            raise DomainError("actor_required", "A continue action requires an actor")
        if action == "takeover":
            if not reason:
                raise DomainError("reason_required", "Takeover requires a reason")
            return self.acquire_lease(ref, holder=actor["id"], role=actor.get("role", "coordinator"), takeover_reason=reason, actor=actor, workflow_recovery=workflow)
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if workflow:
                _require_workflow_member(task, "recovery")
            if action in {"replan", "reopen", "revise"}:
                if task.get("meta", {}).get("disposition"):
                    raise DomainError("task_dropped", "Revive the dropped task before changing its phase", status=3)
                if not reason:
                    raise DomainError("reason_required", "%s requires a reason" % action)
                if not confirmation:
                    raise DomainError("confirmation_required", "%s requires an explicit user decision" % action, status=3)
                validate_source(confirmation, task, actor=actor)
                if action == "replan":
                    if task["phase"] != "in_progress":
                        raise DomainError("replan_forbidden", "Replanning applies to in-progress work; reopen a completed task first", status=3)
                    for evidence in task["evidence"]:
                        if evidence.get("state") == "valid":
                            evidence["state"] = "stale"
                            evidence["stale_reasons"] = [{"type": "replanned", "reason": reason}]
                    if task.get("acceptance"):
                        task["acceptance"]["state"] = "stale"
                    task["phase"] = "planning"
                    task["completedAt"] = None
                    task["lease"] = None
                    self._event(task, "replanned", confirmation or self._actor_source(actor, "continue replan"), {"reason": reason})
                elif action == "reopen":
                    if actor.get("role") != "user" or task["phase"] != "completed":
                        raise DomainError("reopen_forbidden", "Only a user may reopen an unarchived completed task", status=3)
                    task["phase"] = "in_progress"
                    task["completedAt"] = None
                    if task.get("acceptance"):
                        task["acceptance"]["state"] = "historical"
                    self._event(task, "reopened", confirmation or self._actor_source(actor, "continue reopen"), {"reason": reason})
                elif action == "revise":
                    if task["phase"] != "in_progress":
                        raise DomainError("revise_forbidden", "Revision requires an in-progress task", status=3)
                    self._event(task, "revision_requested", confirmation or self._actor_source(actor, "continue revise"), {"reason": reason})
            elif action == "unblock":
                raise DomainError("use_service", "Unblock requires set_blocked so source rules are enforced")
            else:
                raise DomainError("invalid_action", "Unknown continue action", {"action": action})
            self._write(task_dir, task)
            return task

    def _require_children_ready(self, task_dir: Path, task: dict) -> None:
        for name in self._children_consistency(task_dir, task):
            child_dir = task_dir / "subtasks" / name
            child = self.store._read_path(child_dir / "task.json")
            disposition = child.get("meta", {}).get("disposition")
            if disposition:
                if disposition.get("pending_cleanup") or disposition.get("pending_knowledge"):
                    raise DomainError("children_incomplete", "Child drop disposition is still pending", {"child": name}, status=3)
            else:
                if child["phase"] != "completed":
                    raise DomainError("children_incomplete", "All children must be completed or dropped", {"child": name}, status=3)
                status = self.evidence.acceptance_status(child["id"], task=child)
                accepted = set((child.get("acceptance") or {}).get("evidence_refs", []))
                if not accepted or not accepted <= set(status["evidence_refs"]):
                    raise DomainError("children_incomplete", "Child acceptance evidence is stale", {"child": name}, status=3)
            self._require_children_ready(child_dir, child)

    def accept(self, ref: str, *, actor: dict, confirmation: dict) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if actor.get("role") != "user":
                raise DomainError("acceptance_forbidden", "Only a user confirmation may complete a task", status=3)
            if task["phase"] != "in_progress":
                raise DomainError("acceptance_blocked", "Only an in-progress task may be accepted", status=3)
            validate_source(confirmation, task, actor=actor)
            self._require_children_ready(task_dir, task)
            status = self.evidence.acceptance_status(ref, task=task)
            if not status["awaiting_acceptance"]:
                raise DomainError("acceptance_blocked", "Fresh independent final check evidence is required", status, status=3)
            qualifying = [item for item in task["evidence"] if item.get("id") in status["evidence_refs"]]
            # Independent-check gate: the qualifying final check's producer
            # must differ from every delivery producer on this task.
            implementers = {item.get("producer", {}).get("id") for item in task["evidence"] if item.get("kind") == "delivery"}
            for item in qualifying:
                if item.get("producer", {}).get("id") in implementers:
                    raise DomainError("check_not_independent", "The final check producer also delivered the implementation", status, status=3)
            delivery_digests = [item.get("delivery", {}).get("digest") for item in qualifying]
            task["acceptance"] = {"confirmed_at": self.clock(), "confirmed_by": "user", "source": confirmation, "evidence_refs": status["evidence_refs"], "validates": {"task": source_snapshot(task), "delivery": delivery_digests}, "state": "valid"}
            task["phase"] = "completed"
            task["completedAt"] = self.clock()
            self._event(task, "accepted", confirmation, {"evidence_refs": status["evidence_refs"]})
            self._write(task_dir, task)
            return task

    def drop(self, ref: str, *, actor: dict, confirmation: dict, reason: str, disposition: str = "keep", action: str = "drop") -> dict:
        if actor.get("role") != "user":
            raise DomainError("drop_forbidden", "Only a user may drop or revive a task", status=3)
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            validate_source(confirmation, task, actor=actor)
            if action == "revive":
                if not task.get("meta", {}).get("disposition"):
                    raise DomainError("not_dropped", "Task is not dropped", status=3)
                old = task["meta"]["disposition"]
                task["meta"]["disposition"] = None
                task["phase"] = "planning"
                self._event(task, "revived", confirmation, {"previous": old, "reason": reason})
            else:
                if disposition not in {"keep", "discard", "knowledge"} or not reason:
                    raise DomainError("invalid_disposition", "Drop requires reason and keep/discard/knowledge disposition")
                task["meta"]["disposition"] = {"at": self.clock(), "by": actor, "reason": reason, "action": disposition, "confirmation": confirmation, "pending_cleanup": disposition == "discard", "pending_knowledge": disposition == "knowledge"}
                task["lease"] = None
                self._event(task, "dropped", confirmation, {"reason": reason, "disposition": disposition})
            self._write(task_dir, task)
            return task

    def enable_extension(self, ref: Optional[str], *, authorization: dict, actor: dict) -> dict:
        extension_id = authorization.get("id")
        if extension_id not in EXTENSIONS:
            raise DomainError("unknown_extension", "Unknown extension package", {"id": extension_id})
        scope = authorization.get("scope", "full")
        included = sorted(set(authorization.get("included", [])))
        excluded = sorted(set(authorization.get("excluded", [])))
        if scope not in {"full", "custom"} or set(included) & set(excluded):
            raise DomainError("invalid_extension_scope", "Extension scope is invalid or overlaps")
        allowed = EXTENSIONS[extension_id]
        if not set(included + excluded) <= allowed:
            raise DomainError("invalid_extension_members", "Extension contains unknown capabilities", {"allowed": sorted(allowed)})
        if scope == "full":
            included, excluded = sorted(allowed), []
        source = authorization.get("source")
        if not source:
            raise DomainError("confirmation_required", "Extension authorization requires a source")
        record = {"id": extension_id, "enabled_at": self.clock(), "source": source, "scope": scope, "included": included, "excluded": excluded, "reason": authorization.get("reason", "")}
        if not ref:
            return {"authorization": record, "persistence": "session_only"}
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_active(task, "extension change")
            self._require_unleased(task, "extension change")
            existing = next((x for x in task["extensions"] if x["id"] == extension_id), None)
            event_type = "extension_changed" if existing else "extension_enabled"
            if existing:
                task["extensions"].remove(existing)
            task["extensions"].append(record)
            self._event(task, event_type, source, {"old": existing, "new": record})
            self._write(task_dir, task)
            return record

    def disable_extension(self, ref: Optional[str], *, extension_id: str, authorization: dict, actor: dict) -> dict:
        if extension_id not in EXTENSIONS:
            raise DomainError("unknown_extension", "Unknown extension package")
        if not ref:
            return {"id": extension_id, "disabled": True, "source": authorization, "persistence": "session_only"}
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_active(task, "extension change")
            self._require_unleased(task, "extension change")
            existing = next((x for x in task["extensions"] if x["id"] == extension_id), None)
            if existing:
                task["extensions"].remove(existing)
                self._event(task, "extension_changed", authorization, {"old": existing, "new": None})
                self._write(task_dir, task)
            return {"id": extension_id, "disabled": bool(existing)}

    def record_review(self, ref: str, *, record: dict, actor: dict) -> dict:
        source = record.get("source")
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_active(task, "review record")
            self._require_unleased(task, "review record")
            validate_source(source, task, actor=actor)
            if record.get("verdict") not in {"approved", "changes_requested", "comment"}:
                raise DomainError("invalid_review", "Review verdict is invalid")
            evidence = {"id": str(uuid.uuid4()), "kind": "review", "producer": {"role": "user", "id": actor.get("id"), "session_id": actor.get("session")}, "produced_at": self.clock(), "state": "valid", "validates": record.get("validates", []), "verdict": record["verdict"], "notes": record.get("notes", ""), "source": source}
            task["evidence"].append(evidence)
            self._event(task, "review_recorded", source, {"evidence_id": evidence["id"], "verdict": evidence["verdict"]})
            self._write(task_dir, task)
            return evidence

    def list_reviews(self, ref: str) -> list:
        return [item for item in self.store.read(ref)["evidence"] if item.get("kind") == "review"]

    def _validate_archive_tree(self, task_dir: Path) -> set:
        task = self.store._read_path(task_dir / "task.json")
        names = self._children_consistency(task_dir, task)
        if task.get("blocked") or task.get("lease"):
            raise DomainError("archive_blocked", "Blocked or leased descendants cannot be archived", {"task": task["name"]}, status=3)
        disposition = task.get("meta", {}).get("disposition")
        if disposition:
            if disposition.get("pending_cleanup") or disposition.get("pending_knowledge"):
                raise DomainError("archive_blocked", "Dropped descendant disposition is still pending", {"task": task["name"]}, status=3)
        else:
            if task["phase"] != "completed" or not task.get("acceptance") or task["acceptance"].get("state") != "valid":
                raise DomainError("archive_blocked", "Every task in the tree must be completed or dispositioned", {"task": task["name"]}, status=3)
            status = self.evidence.acceptance_status(task["id"], task=task)
            accepted_refs = set(task["acceptance"].get("evidence_refs", []))
            if not accepted_refs or not accepted_refs <= set(status["evidence_refs"]):
                raise DomainError("archive_blocked", "Descendant acceptance evidence is stale", {"task": task["name"]}, status=3)
        ids = {task["id"]}
        for name in names:
            ids.update(self._validate_archive_tree(task_dir / "subtasks" / name))
        return ids

    def archive(self, ref: str, *, actor: dict, confirmation: dict, operation_id: Optional[str] = None, workflow: bool = False) -> dict:
        operation_id = operation_id or str(uuid.uuid4())
        now = self.clock()
        month = now[:7]
        with self.store.transaction():
            try:
                task_dir = self.store.resolve(ref)
            except DomainError as exc:
                if exc.code == "task_not_found":
                    archived = self.store.resolve(ref, archived=True)
                    task = self.store._read_path(archived / "task.json")
                    completed = [e for e in task["events"] if e.get("type") == "archived" and e.get("data", {}).get("operation_id") == operation_id]
                    pending = [e for e in task["events"] if e.get("type") == "archive_operation" and e.get("data", {}).get("operation_id") == operation_id]
                    if not pending:
                        raise DomainError("archive_conflict", "Archived task does not match this archive operation", {"operation_id": operation_id}, status=4)
                    # Finishing an interrupted archive is safety machinery (the
                    # settled lifecycle-member boundary): the recovery branch
                    # is never member-gated, so a trimmed grant cannot strand
                    # a task in a half-moved state. The grant is only consulted
                    # before a NEW archive operation starts (see below).
                    pending_event = pending[-1]
                    actual_target = str(archived.relative_to(self.store.project_root))
                    if pending_event.get("data", {}).get("target") != actual_target or archived.parent.parent != self.store.archive_root:
                        raise DomainError("archive_conflict", "Archive operation target does not match the archived root", {"operation_id": operation_id}, status=4)
                    # A retry finishes only the original operation and carries
                    # its original confirmation, not a caller-supplied source.
                    validate_source(pending_event.get("source"), task, actor=pending_event.get("source", {}).get("actor"))
                    if completed:
                        return {"task": task, "path": str(archived), "recovered": True}
                    task["archivedAt"] = pending_event["data"]["archived_at"]
                    self._event(task, "archived", pending_event["source"], {"operation_id": operation_id, "target": actual_target, "recovered": True})
                    self._write(archived, task)
                    self.store.clear_tree_pointers({x["id"] for x in self._scan_tree(archived)})
                    return {"task": task, "path": str(archived), "recovered": True}
                raise
            try:
                task_dir.relative_to(self.store.tasks_root)
            except ValueError:
                raise DomainError("archive_invalid", "Only active top-level tasks can be archived", status=3)
            if task_dir.parent != self.store.tasks_root:
                raise DomainError("archive_child_forbidden", "Subtasks are archived only with their root task", status=3)
            task = self.store._read_path(task_dir / "task.json")
            if workflow:
                _require_workflow_member(task, "archive")
            validate_source(confirmation, task, actor=actor)
            tree_ids = self._validate_archive_tree(task_dir)
            target = self.store.archive_root / month / task["name"]
            if target.exists() or target.is_symlink():
                target_task = target / "task.json"
                if target_task.is_file():
                    existing = self.store._read_path(target_task)
                    matching = any(e.get("type") == "archived" and e.get("data", {}).get("operation_id") == operation_id for e in existing["events"])
                    if existing["id"] == task["id"] and matching:
                        return {"task": existing, "path": str(target), "recovered": True}
                raise DomainError("archive_conflict", "Archive destination already exists", {"target": str(target)}, status=4)
            pending = make_event("archive_operation", confirmation, {"operation_id": operation_id, "target": str(target.relative_to(self.store.project_root)), "archived_at": now}, now)
            task["events"].append(pending)
            self._write(task_dir, task)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(task_dir), str(target))
            task = self.store._read_path(target / "task.json")
            task["archivedAt"] = now
            self._event(task, "archived", confirmation, {"operation_id": operation_id, "target": str(target.relative_to(self.store.project_root))})
            self._write(target, task)
            self.store.clear_tree_pointers(tree_ids)
        warnings = []
        try:
            candidates = self.archive_candidates()
            reminder_updates = self.record_reminders(candidates)
        except Exception as exc:
            candidates = []
            reminder_updates = []
            warnings.append(str(exc))
        return {"task": task, "path": str(target), "operation_id": operation_id, "archive_candidates": candidates, "reminder_updates": reminder_updates, "warnings": warnings}

    def _scan_tree(self, root: Path) -> list:
        return [self.store._read_path(path) for path in root.rglob("task.json")]

    def record_reminders(self, reminders: list, *, defer_days: int = 7) -> list:
        updated = []
        with self.store.transaction():
            for reminder in reminders:
                try:
                    task_dir = self.store.resolve(reminder["id"])
                except DomainError:
                    continue
                task = self.store._read_path(task_dir / "task.json")
                ledger = task.setdefault("meta", {}).setdefault("reminders", {})
                key = reminder["reminder_key"]
                if key not in ledger:
                    ledger[key] = {"shown_at": self.clock(), "deferred_until": plus_minutes(self.clock(), defer_days * 24 * 60)}
                    self._write(task_dir, task)
                    updated.append({"id": task["id"], "reminder_key": key, "deferred_until": ledger[key]["deferred_until"]})
        return updated

    def archive_candidates(self, *, older_than_days: int = 30) -> list:
        threshold = parse_time(self.clock()) - timedelta(days=older_than_days)
        candidates = []
        for task in self.store.scan(archived=False):
            path = Path(task["_path"])
            if path.parent != self.store.tasks_root:
                continue
            substantial = [event["at"] for event in task["events"] if event.get("type") not in {"summary", "lease_renewed"} and event.get("at")]
            last = max(substantial + [task["createdAt"]])
            if parse_time(last) > threshold:
                continue
            missing = []
            if task["phase"] != "completed" and not task.get("meta", {}).get("disposition"):
                missing.append("not_completed_or_dropped")
            if task.get("blocked"):
                missing.append("blocked")
            if task.get("lease"):
                missing.append("lease")
            key = hashlib.sha256((task["id"] + "|" + task["phase"] + "|" + ",".join(missing) + "|" + last).encode()).hexdigest()
            candidates.append({"id": task["id"], "name": task["name"], "last_activity": last, "missing": missing, "reminder_key": key, "defer_days_default": 7})
        return candidates
