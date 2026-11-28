from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .evidence import EvidenceService, file_digest
from .models import (DomainError, STATUSES, WORK_ITEM_STATES, deliverable,
                     new_task, valid_name, work_item)
from .store import TaskStore, content_hash

LEASE_MINUTES = 30
EVENT_LIMIT = 200
# correction stays out of compaction: retro analysis quotes the user's exact
# words from these events, so they are load-bearing records, not noise.
MILESTONES = {"started", "replanned", "lease_taken_over", "review_recorded", "accepted", "dropped", "revived", "archived", "extension_enabled", "extension_changed", "correction", "awaiting_acceptance", "rework_requested", "recheck_requested", "reopened", "unified_acceptance", "evidence_invalidated", "unarchived"}
EXTENSIONS = {
    "planning-review": {"clarify", "prd", "design", "plan", "editor", "doc-check"},
    "persistent-task": {"task", "evidence", "lease", "events", "recovery", "archive"},
    "multi-agent": {"research", "parallel-implement", "version-injection", "change-propagation"},
    "project-governance": {"specs", "knowledge", "rules", "memory"},
}


def _require_workflow_member(task: dict, member: str) -> None:
    from .extensions import grants, includes
    if not includes(grants(task["extensions"]), "persistent-task", member):
        raise DomainError("extension_not_authorized", "Workflow operation requires an included extension member",
                          {"package": "persistent-task", "member": member}, status=3)


# Planning documents that a replan must revisit (S-4 K-6).
#
# The default template set moved the scenario prd/design to the software
# scenario templates, but an OLD task on disk can still carry doc/prd.md and
# doc/design.md: the template migration does not make those files vanish, and
# dropping them from this list would silently stop surfacing them for the
# very tasks that still have them. The list therefore keeps the legacy
# doc/prd.md and doc/design.md entries as COMPATIBILITY recognition
# (_docs_to_revisit only reports the files that actually exist) and adds
# criteria.md, the acceptance criteria every task now forms.
_REVISIT_DOCS = ("doc/prd.md", "doc/design.md", "doc/walkthrough.md", "plan.md", "clarify.md", "criteria.md")


def _docs_to_revisit(task_dir: Path) -> list:
    """Planning documents present at replan time, for revisit surfacing."""
    return [relative for relative in _REVISIT_DOCS if (task_dir / relative).is_file()]


def _git_output(args: list, cwd: Path) -> Optional[str]:
    """One read-only git query; None on any failure (no side effects)."""
    import subprocess
    try:
        result = subprocess.run(["git"] + list(args), cwd=str(cwd),
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _has_git_worktree(start: Path) -> bool:
    """Cheap upward probe for a .git entry (directory or worktree file)."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        if (candidate / ".git").exists():
            return True
    return False


def git_repo_info(start: Path) -> Optional[dict]:
    """Read-only snapshot of the git state at ``start`` (P-004 branch binding).

    Only read-only git plumbing runs here (rev-parse). A detached HEAD is
    reported honestly as detached with its commit — no branch name is ever
    fabricated. Returns None when the path is not inside a git worktree or
    git is unavailable.
    """
    start = Path(start)
    if not _has_git_worktree(start):
        return None
    commit = _git_output(["rev-parse", "HEAD"], start)
    if not commit:
        return None
    branch = _git_output(["rev-parse", "--abbrev-ref", "HEAD"], start)
    detached = branch in (None, "HEAD")
    toplevel = _git_output(["rev-parse", "--show-toplevel"], start)
    return {"commit": commit, "branch": "" if detached else (branch or ""),
            "detached": detached, "worktree": toplevel or ""}


def _fill_branch_info(task: dict, git_root: Path) -> Optional[dict]:
    """Fill empty branch/worktree/base fields with the ACTUAL git state.

    Never overwrites an explicitly recorded value; never fabricates a
    branch for a detached HEAD (branch stays empty and the info carries
    ``detached: true`` with the commit). Returns the recorded info when
    the task lives inside a git worktree, else None.
    """
    info = git_repo_info(git_root)
    if info is None:
        return None
    if not task.get("worktree_path"):
        task["worktree_path"] = info["worktree"]
    if not task.get("commit"):
        task["commit"] = info["commit"]
    if not task.get("branch"):
        task["branch"] = info["branch"]
    if not task.get("base_branch") and info["worktree"]:
        base = _git_output(["rev-parse", "--abbrev-ref", "origin/HEAD"],
                           Path(info["worktree"]))
        if base and base != "HEAD":
            task["base_branch"] = base
    task["meta"]["git_binding"] = {
        "detached": info["detached"], "recorded_by": "branch_binding",
    }
    return info


def _git_head_commit(task_dir: Path) -> Optional[str]:
    """Record the working-tree HEAD at replan time as a revert anchor."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=task_dir,
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = (result.stdout or "").strip()
    return commit if result.returncode == 0 and commit else None


def _plan_digest(task_dir: Path) -> Optional[str]:
    """plan.md's digest at replan time; None when the task has no plan yet."""
    path = task_dir / "plan.md"
    if not path.is_file():
        return None
    try:
        return file_digest(path)
    except OSError:
        return None


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


def _resolve_archive_origin_path(store: TaskStore, archive_path: str) -> Path:
    """Resolve an origin/related archive_path (".fstar/" prefixed identity path)."""
    candidate = Path(archive_path)
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0] == ".fstar":
        return store.fstar_root.joinpath(*parts[1:])
    return store.project_root / candidate


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

    @staticmethod
    def _lease_hint(lease: Optional[dict]) -> str:
        expires = (lease or {}).get("expires_at") or "unknown"
        return ("release via 'fstar interrupt <task> --release-lease-token <token>' or wait for expiry at %s" % expires)

    def _require_unleased(self, task: dict, operation: str) -> None:
        lease = task.get("lease")
        if lease and lease.get("expires_at", "") > self.clock():
            raise DomainError("lease_conflict", "%s cannot mutate a task with an active writer" % operation,
                              {"holder": lease.get("holder"), "expires_at": lease.get("expires_at"),
                               "hint": self._lease_hint(lease)}, status=4)

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

    def _validate_origin(self, origin: dict) -> dict:
        """Validate and normalize a create-time origin (antigravity design §1.2).

        The parent task may live in the archive tree (identity path with the
        ".fstar/" prefix, same resolution rule as meta.related_tasks) or at
        the tasks_root top level (already unarchived). The referenced
        task.json id must match origin.task_id, otherwise the link is
        refused: a wrong origin silently injects the wrong parent context
        in P-003.
        """
        if not isinstance(origin, dict):
            raise DomainError("invalid_origin", "origin must be an object", status=3)
        task_id = origin.get("task_id")
        archive_path = origin.get("archive_path")
        if not isinstance(task_id, str) or not task_id.strip():
            raise DomainError("invalid_origin", "origin requires a non-empty task_id", status=3)
        if not isinstance(archive_path, str) or not archive_path.strip():
            raise DomainError("invalid_origin", "origin requires a non-empty archive_path", status=3)
        resolved = _resolve_archive_origin_path(self.store, archive_path)
        origin_dir = resolved.parent if resolved.name == "task.json" else resolved
        parent_task = None
        try:
            origin_dir.resolve().relative_to(self.store.archive_root.resolve())
        except ValueError:
            # Not inside the archive tree: the parent may already be
            # unarchived; accept a top-level active location as well.
            if origin_dir.parent != self.store.tasks_root:
                raise DomainError("invalid_origin", "origin archive_path must point inside the archive or at a top-level active task", {"archive_path": archive_path}, status=3)
            if not (origin_dir / "task.json").is_file():
                raise DomainError("invalid_origin", "Origin parent task does not exist", {"archive_path": archive_path}, status=3)
            parent_task = self.store._read_path(origin_dir / "task.json")
        else:
            if not (origin_dir / "task.json").is_file():
                raise DomainError("invalid_origin", "Origin parent task does not exist", {"archive_path": archive_path}, status=3)
            parent_task = self.store._read_path(origin_dir / "task.json")
        if parent_task["id"] != task_id:
            raise DomainError("invalid_origin", "Origin task_id does not match the parent task.json", {"task_id": task_id, "actual": parent_task["id"]}, status=3)
        return {"task_id": task_id, "archive_path": self.store.identity_path(origin_dir), "reason": origin.get("reason", "") if isinstance(origin.get("reason"), str) else ""}

    def create(self, *, name: str, title: str, description: str, actor: dict, parent: Optional[str] = None, related: Optional[list] = None, origin: Optional[dict] = None, session_id: Optional[str] = None) -> dict:
        if actor.get("role") not in {"user", "agent"} or not actor.get("id"):
            raise DomainError("invalid_actor", "Creating a task requires a declared actor")
        if origin is not None and parent is not None:
            # origin points at a (possibly archived) parent requirement task;
            # parent expresses the same relation for an ACTIVE parent via
            # physical nesting. Carrying both would leave two competing
            # parent pointers that can drift apart.
            raise DomainError("invalid_origin", "Use parent for an active parent or origin for a possibly archived one, not both", status=3)
        if origin is not None:
            origin = self._validate_origin(origin)
        with self.store.transaction():
            now = self.clock()
            task = new_task(name, title, description, creator=actor["id"], now=now)
            task["meta"] = {"disposition": None, "templates": {}, "related_tasks": [], "reminders": {}}
            if origin:
                # Keep the original (possibly still valid) archive location
                # recorded verbatim; the normalized identity lives in
                # archive_path. Kept as provided by _validate_origin.
                task["origin"] = origin
            if related:
                for relation in related:
                    archive_path = Path(relation.get("archive_path", ""))
                    if not archive_path.is_absolute():
                        # archive_path identity keeps the ".fstar/" prefix; the
                        # archive tree itself lives under the resolved data
                        # root (which is <repo>/.fstar or the user-directory
                        # data root), so resolve it through the store.
                        rel = archive_path
                        parts = rel.parts
                        if parts and parts[0] == ".fstar":
                            archive_path = self.store.fstar_root.joinpath(*parts[1:])
                        else:
                            archive_path = self.store.project_root / rel
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
                    task["meta"]["related_tasks"].append({"id": archived["id"], "archive_path": self.store.identity_path(related_dir), "relation": relation.get("relation", "follow_up"), "reason": relation.get("reason", "")})
            self._event(task, "created", self._actor_source(actor, "task create"), {"parent": parent})
            # Branch binding (P-004): capture the actual git state of the
            # repo the task is being created in; explicit values survive.
            _fill_branch_info(task, self.store.project_root)
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

    # -- QA task location by branch (P-004 / D-006 / R-006) ------------------

    def _candidate_row(self, task: dict, archived: bool) -> dict:
        return {"task_id": task["id"], "ref": task["name"], "title": task.get("title", ""),
                "phase": task["phase"], "completed": task["phase"] == "completed",
                "archived": archived or bool(task.get("archivedAt")),
                "dropped": bool(task.get("meta", {}).get("disposition")),
                "branch": task.get("branch", ""), "worktree": task.get("worktree_path", ""),
                "path": task.get("_path", "")}

    def _branch_candidates(self, branch: Optional[str], worktree: Optional[str]) -> tuple:
        """(active_matches, archived_matches) for a branch (+optional worktree).

        The search spans this project's active and archived trees AND every
        other worktree of the same git repository (P-004: several worktrees
        of one repo may each carry a task bound to the same branch name; git
        itself refuses checking one branch out twice, but tasks keep their
        recorded binding). Sibling worktrees are discovered read-only via
        ``git worktree list``; unresolvable or un-initialized siblings are
        skipped. No match is ever mutated.
        """
        active, archived = [], []
        stores = [self.store]
        seen_roots = {str(self.store.project_root)}
        seen_data_roots = {self.store.fstar_root.resolve()}
        current_info = git_repo_info(self.store.project_root)
        if current_info and current_info["worktree"]:
            listing = _git_output(["worktree", "list", "--porcelain"],
                                  Path(current_info["worktree"]))
            if listing:
                for line in listing.splitlines():
                    if not line.startswith("worktree "):
                        continue
                    candidate = line[len("worktree "):].strip()
                    if not candidate or candidate in seen_roots:
                        continue
                    seen_roots.add(candidate)
                    try:
                        sibling = TaskStore(Path(candidate),
                                            user_home=self.store.user_home,
                                            runtime_root=self.store.runtime_root)
                        sibling.require_project()
                    except (DomainError, OSError):
                        continue
                    data_root = sibling.fstar_root.resolve()
                    if data_root in seen_data_roots:
                        continue
                    seen_data_roots.add(data_root)
                    stores.append(sibling)
        for sibling in stores:
            try:
                scanned = [(sibling.scan(archived=flag), flag) for flag in (False, True)]
            except DomainError:
                # A sibling worktree with unreadable task data must not break
                # the lookup for this project; it is skipped. The project's
                # OWN corrupt data is reported instead of being hidden.
                if sibling is self.store:
                    raise
                continue
            for tasks, scan_archived in scanned:
                for task in tasks:
                    if branch and task.get("branch") != branch:
                        continue
                    if worktree and task.get("worktree_path") != worktree:
                        continue
                    row = self._candidate_row(task, scan_archived)
                    if sibling is not self.store:
                        row["project_root"] = str(sibling.project_root)
                    (archived if scan_archived else active).append(row)
        return active, archived

    def locate(self, *, ref: Optional[str] = None, session_id: Optional[str] = None,
               branch: Optional[str] = None, worktree: Optional[str] = None) -> dict:
        """Resolve which task a branch (or session) belongs to (R-006).

        Order: explicit task ref > a valid compatible session pointer >
        a unique project/worktree/branch candidate. Multiple candidates
        (including completed and archived matches) are LISTED for
        natural-language selection — nothing is auto-selected and nothing
        is reopened. No matches is a clear negative result. Archived hits
        can only be linked to a follow-up task, never reopened or mutated.
        """
        if ref:
            try:
                task_dir = self.store.resolve(ref)
                archived = False
            except DomainError as exc:
                if exc.code != "task_not_found":
                    raise
                # A completed/archived task stays findable for QA (R-006):
                # the explicit ref resolves in the archive tree instead of
                # failing, and the hit is reported as archived — nothing is
                # reopened or mutated.
                try:
                    task_dir = self.store.resolve(ref, archived=True)
                    archived = True
                except DomainError:
                    # Neither tree holds it: report the original lookup
                    # failure, not the archive-only attempt.
                    raise exc
            task = self.store._read_path(task_dir / "task.json")
            row = self._candidate_row({**task, "_path": str(task_dir)},
                                      archived or bool(task.get("archivedAt")))
            return {"status": "found", "via": "explicit_ref", "task": row}
        if session_id:
            current = self.current(session_id)
            pointer_task = current.get("current")
            if pointer_task is not None:
                # Session pointers are keyed per project (P-001): the pointer
                # already resolves inside this project's own data, but the
                # recorded project root must still match, so a pointer left
                # by a session in a different worktree of the same project
                # does not silently win.
                pointer = self.store.current(session_id) or {}
                compatible = self.store.session_matches(pointer)
                if not branch or pointer_task.get("branch") == branch:
                    if compatible:
                        row = self._candidate_row(pointer_task, bool(pointer_task.get("archivedAt")))
                        row["path"] = current.get("path", row["path"])
                        return {"status": "found", "via": "session_pointer", "task": row}
        if not branch and not worktree:
            # A candidate search without a branch (or worktree) key matches
            # EVERY task in the project, which would report an arbitrary task
            # as "the" answer. An honest negative is better than a wrong one.
            return {"status": "no_task", "via": "no_key",
                    "message": "Nothing to locate: no task reference, no valid session pointer, and no branch given"}
        active, archived = self._branch_candidates(branch, worktree)
        candidates = active + archived
        if not candidates:
            return {"status": "no_task", "via": "branch_search",
                    "message": "No task is bound to this branch in this project"}
        if len(candidates) == 1:
            return {"status": "found", "via": "unique_candidate",
                    "task": candidates[0], "ambiguous": False}
        return {"status": "ambiguous", "via": "branch_search",
                "candidates": candidates,
                "message": "Several tasks match this branch; select one explicitly (archived matches can only be linked to a follow-up task)"}

    def current(self, session_id: Optional[str]) -> dict:
        pointer = self.store.current(session_id)
        if not pointer:
            return {"current": None, "status": "no_current"}
        if not self.store.session_matches(pointer):
            return {"current": None, "status": "stale_pointer", "details": {"reason": "project_identity_mismatch"}}
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
            # Branch binding at start time (P-004/D-006): the task records the
            # branch/worktree it actually runs on; an explicit recorded value
            # is never overwritten.
            info = _fill_branch_info(task, self.store.project_root)
            self._event(task, "started", confirmation,
                        {"snapshot": source_snapshot(task),
                         "branch": task.get("branch", ""),
                         "worktree": task.get("worktree_path", ""),
                         "detached": bool(info and info["detached"])})
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
            lease = self._acquire_lease(task, holder=holder, role=role, takeover_reason=takeover_reason, actor=actor)
            self._write(task_dir, task)
            return lease

    def _acquire_lease(self, task: dict, *, holder: str, role: str,
                       takeover_reason: Optional[str] = None, actor: Optional[dict] = None) -> dict:
        """Mutate a loaded task under the caller's transaction; do not persist."""
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

    # -- Optional collaboration fields (design §4, S-2) ---------------------
    # These fields are descriptive collaboration state, orthogonal to the
    # phase machine: they never gate lifecycle transitions and never enter
    # source_snapshot. The project lock inside transaction() still serializes
    # the write itself, so an active writer lease does not refuse them — a
    # lease holder must be able to log its own work-item progress.

    def _require_not_dropped(self, task: dict, operation: str) -> None:
        self._require_active(task, operation)

    def set_status(self, ref: str, *, actor: dict, status: str, reason: Optional[str] = None) -> dict:
        """Set the collaboration status (active/waiting_user/waiting_external/paused).

        Non-active statuses require a reason; ``status_detail.since`` records
        when the transition happened. Returning to active clears the detail
        (the reason no longer applies) but keeps the ``status`` key present.
        Every change appends one ``status_changed`` event.
        """
        if status not in STATUSES:
            raise DomainError("invalid_status", "status must be active, waiting_user, waiting_external, or paused", {"status": status})
        if status != "active" and not (isinstance(reason, str) and reason.strip()):
            raise DomainError("reason_required", "A non-active status requires a reason")
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_not_dropped(task, "set_status")
            previous = task.get("status", "active")
            if status != "active":
                task["status"] = status
                task["status_detail"] = {"reason": reason, "since": self.clock()}
            else:
                task["status"] = "active"
                task["status_detail"] = None
            self._event(task, "status_changed", self._actor_source(actor, "set_status"),
                        {"from": previous, "to": status, "reason": reason or ""})
            self._write(task_dir, task)
            return task

    def set_work_item(self, ref: str, *, actor: dict, item: dict) -> dict:
        """Upsert one work item by id (done/active/blocked/cancelled).

        The full normalized item lands in the event data so the append-only
        log carries both old and new state.
        """
        if not isinstance(item, dict):
            raise DomainError("invalid_work_items", "A work item must be an object")
        try:
            normalized = work_item(item)
        except (KeyError, TypeError):
            raise DomainError("invalid_work_items", "A work item requires an id and a valid state")
        if normalized["state"] not in WORK_ITEM_STATES:
            raise DomainError("invalid_work_items", "work item state must be done, active, blocked, or cancelled", {"id": normalized["id"], "state": normalized["state"]})
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_not_dropped(task, "set_work_item")
            items = task.setdefault("work_items", [])
            previous = next((existing for existing in items if existing.get("id") == normalized["id"]), None)
            if previous is not None:
                items[items.index(previous)] = normalized
            else:
                items.append(normalized)
            self._event(task, "work_item_updated", self._actor_source(actor, "set_work_item"),
                        {"old": previous, "new": normalized})
            self._write(task_dir, task)
            return task

    def set_next_step(self, ref: str, *, actor: dict, condition: Optional[str], action: Optional[str]) -> dict:
        """Set (or clear, with None arguments) the explicit next-step pointer."""
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_not_dropped(task, "set_next_step")
            previous = task.get("next_step")
            if condition is None and action is None:
                task["next_step"] = None
                updated = None
            else:
                if not (isinstance(condition, str) and condition.strip() and isinstance(action, str) and action.strip()):
                    raise DomainError("invalid_next_step", "next_step requires non-empty condition and action strings")
                task["next_step"] = {"condition": condition, "action": action}
                updated = task["next_step"]
            self._event(task, "next_step_changed", self._actor_source(actor, "set_next_step"),
                        {"old": previous, "new": updated})
            self._write(task_dir, task)
            return task

    def register_deliverable(self, ref: str, *, actor: dict, entry: dict) -> dict:
        """Register or update one deliverable pointer by name (design §4)."""
        if not isinstance(entry, dict):
            raise DomainError("invalid_deliverables", "A deliverable entry must be an object")
        try:
            normalized = deliverable(entry)
        except (KeyError, TypeError):
            raise DomainError("invalid_deliverables", "A deliverable requires name and path")
        if not all(isinstance(normalized[key], str) and normalized[key].strip() for key in ("name", "path")):
            raise DomainError("invalid_deliverables", "deliverables entries require non-empty name and path")
        path = normalized["path"]
        if path.strip() != path or "\x00" in path or str(Path(path)) == "mode":
            raise DomainError("unsafe_evidence_path", "Deliverable requires a safe file path", {"path": path})
        resolved = self.store.project_file(path)
        if resolved.is_dir() or not Path(path).parts:
            raise DomainError("unsafe_evidence_path", "Deliverable path must name a file", {"path": path})
        normalized["path"] = str(Path(path))
        criteria = normalized["criteria_refs"]
        if not isinstance(criteria, list) or not all(isinstance(item, str) and item.strip() for item in criteria):
            raise DomainError("invalid_deliverables", "criteria_refs must contain non-empty strings")
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_not_dropped(task, "register_deliverable")
            entries = task.setdefault("deliverables", [])
            previous = next((existing for existing in entries if existing.get("name") == normalized["name"]), None)
            if previous is not None:
                entries[entries.index(previous)] = normalized
            else:
                entries.append(normalized)
            # Bind only declared criteria (or the path itself when none were
            # declared). Empty historical maps establish no requirement ids.
            # Marker mappings remain authoritative in mixed artifact maps.
            templates = task.setdefault("meta", {}).setdefault("templates", {})
            artifact_map = dict(templates.get("artifact_map", {}) or {})
            path = normalized["path"]
            existing = artifact_map.get(path)
            if not existing or (isinstance(existing, dict) and all(
                    isinstance(spec, dict) and spec.get("mode") == "file" for spec in existing.values())):
                ids = {item for pointer in entries if pointer["path"] == path
                       for item in (pointer.get("criteria_refs") or [path])}
                artifact_map[path] = {item: {"mode": "file", "dependencies": []} for item in sorted(ids)}
                templates["artifact_map"] = artifact_map
                templates["artifact_map_sha256"] = content_hash(artifact_map)
                templates["artifact_map_source"] = self._actor_source(actor, "register_deliverable")
            self._event(task, "deliverable_updated", self._actor_source(actor, "register_deliverable"),
                        {"old": previous, "new": normalized})
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

    def enter_awaiting_acceptance(self, ref: str, *, actor: dict) -> dict:
        """Move in_progress -> awaiting_acceptance after a fresh final check.

        Explicit transition (design D-004): a successful final-check harvest
        alone never changes the phase; the coordinator calls this once the
        harvest recorded qualifying evidence. Re-validation happens here, so
        an expired/stale final check (files changed after the check, a newer
        failed final round, blocked/leased/dropped task) can never land in
        awaiting_acceptance. ``completedAt`` stays empty in this phase.
        """
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "A dropped task cannot enter awaiting_acceptance; revive it explicitly", status=3)
            if task["phase"] == "awaiting_acceptance":
                raise DomainError("phase_transition_forbidden",
                                  "Task is already in awaiting_acceptance; use `fstar accept <task>` to accept it",
                                  {"phase": task["phase"]}, status=3)
            if task["phase"] != "in_progress":
                raise DomainError("phase_transition_forbidden",
                                  "Only an in-progress task may enter awaiting_acceptance; "
                                  "planning must start first", {"phase": task["phase"]}, status=3)
            lease = task.get("lease")
            if lease and lease.get("expires_at", "") > self.clock():
                raise DomainError("lease_conflict",
                                  "Release the writer lease before entering awaiting_acceptance",
                                  {"holder": lease.get("holder"), "expires_at": lease.get("expires_at"),
                                   "hint": self._lease_hint(lease)}, status=4)
            status = self.evidence.acceptance_status(ref, task=task)
            if not status["awaiting_acceptance"]:
                raise DomainError("acceptance_blocked",
                                  "A fresh qualifying final check is required before awaiting_acceptance",
                                  status, status=3)
            if task.get("blocked"):
                raise DomainError("phase_transition_forbidden", "A blocked task cannot enter awaiting_acceptance", status=3)
            # The same independence gate accept() applies: the final check
            # producer must differ from every delivery producer, otherwise
            # the phase could be entered with evidence that can never be
            # accepted.
            qualifying = [item for item in task["evidence"] if item.get("id") in status["evidence_refs"]]
            implementers = {item.get("producer", {}).get("id") for item in task["evidence"] if item.get("kind") == "delivery"}
            for item in qualifying:
                if item.get("producer", {}).get("id") in implementers:
                    raise DomainError("check_not_independent",
                                      "The final check producer also delivered the implementation",
                                      status, status=3)
            task["phase"] = "awaiting_acceptance"
            self._event(task, "awaiting_acceptance", self._actor_source(actor, "enter_awaiting_acceptance"),
                        {"evidence_refs": status["evidence_refs"], "completedAt": None})
            self._write(task_dir, task)
            return task

    def report_problem(self, ref: str, *, actor: dict, confirmation: dict, reason: str, scope: Optional[dict] = None) -> dict:
        """User rework during awaiting_acceptance: back to planning.

        The user reports a problem with the delivered work while it sits in
        awaiting_acceptance; the task returns to planning for rework with
        evidence staled by the rework scope (S-4 K-1). Without an explicit
        ``scope`` every currently-valid evidence goes stale (the legacy
        behavior); a ``localized`` scope stales only evidence intersecting
        the declared artifacts/paths/criteria_refs. Both rework entry
        points (report_problem and continue --action rework) share
        invalidate_scope, so the two surfaces cannot diverge. No
        auto-transition follows: the normal start -> dispatch/check cycle
        re-applies. User-initiated only.
        """
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if actor.get("role") != "user":
                raise DomainError("rework_forbidden", "Only a user may report a problem on a task awaiting acceptance", status=3)
            if task["phase"] != "awaiting_acceptance":
                raise DomainError("rework_forbidden", "Rework applies to a task awaiting acceptance", {"phase": task["phase"]}, status=3)
            if not reason:
                raise DomainError("reason_required", "Reporting a problem requires a reason")
            validate_source(confirmation, task, actor=actor)
            invalidation = self.evidence.invalidate_scope(task, reason=reason, scope=scope)
            if task.get("acceptance"):
                task["acceptance"]["state"] = "stale"
            task["phase"] = "planning"
            task["lease"] = None
            task["completedAt"] = None
            self._event(task, "rework_requested", confirmation, {
                "reason": reason,
                "scope": invalidation["scope"],
                "invalidated_evidence_ids": invalidation["invalidated_evidence_ids"],
                "retained_evidence_ids": invalidation["retained_evidence_ids"],
            })
            self._write(task_dir, task)
            return task

    def request_recheck(self, ref: str, *, actor: dict, reason: str) -> dict:
        """Return an awaiting_acceptance task to in_progress for a re-check.

        The final check behind the phase went stale (the delivered files
        changed after the check), so the task can no longer be accepted.
        The coordinator asks explicitly for a fresh check; the phase moves
        back to in_progress, where the normal dispatch/check cycle re-applies.
        Nothing is auto-transitioned and no evidence is rewritten here: the
        stale evidence already says so.
        """
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task["phase"] != "awaiting_acceptance":
                raise DomainError("recheck_forbidden", "Only a task awaiting acceptance can be sent back for a re-check",
                                  {"phase": task["phase"]}, status=3)
            if task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "A dropped task cannot be re-checked; revive it explicitly", status=3)
            if not reason:
                raise DomainError("reason_required", "Requesting a re-check requires a reason")
            status = self.evidence.acceptance_status(ref, task=task)
            if status["awaiting_acceptance"]:
                raise DomainError("recheck_forbidden",
                                  "The final check is still fresh; complete the acceptance instead",
                                  status, status=3)
            task["phase"] = "in_progress"
            task["lease"] = None
            self._event(task, "recheck_requested", self._actor_source(actor, "request_recheck"),
                        {"reason": reason, "blockers": status["blockers"]})
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
        from .models import PHASE_ORDER
        order = PHASE_ORDER
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
        if task["phase"] == "awaiting_acceptance" and not acceptance["awaiting_acceptance"]:
            # The qualifying final check went stale while the task sat in
            # awaiting_acceptance (delivery files changed). A read-only
            # effective view reports the re-check requirement; the task stays
            # in awaiting_acceptance until the user reports the problem or
            # the phase is explicitly re-entered after a fresh check.
            effective = "in_progress"
        result = {"task_id": task["id"], "phase": task["phase"], "effective_phase": effective, "blocked": task["blocked"], "disposition": task.get("meta", {}).get("disposition"), "lease": task["lease"], "evidence": task["evidence"], "extensions": task["extensions"], "children": child_states, "acceptance": acceptance}
        # Optional collaboration fields (design §4): absent fields are omitted
        # rather than reported as null; status defaults to "active".
        result["status"] = task.get("status", "active")
        for field in ("status_detail", "work_items", "next_step", "deliverables"):
            value = task.get(field)
            if value is not None:
                result[field] = value
        return result

    def continue_task(self, ref: Optional[str], *, session_id: Optional[str] = None, action: Optional[str] = None, actor: Optional[dict] = None, confirmation: Optional[dict] = None, reason: Optional[str] = None, workflow: bool = False, scope: Optional[dict] = None) -> dict:
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
            active_lease = bool(lease and lease.get("expires_at", "") > self.clock())
            if state["phase"] == "awaiting_acceptance":
                # The work is delivered and waiting for the user: an expired
                # lease is not an orphan to take over here, and an active
                # one still means a writer is at work.
                state["next"] = "active_worker_do_not_redispatch" if active_lease else "accept_or_rework"
            elif lease and lease.get("expires_at", "") <= self.clock():
                state["orphaned"] = True
                state["next"] = "choose_takeover_replan_or_drop"
            elif lease:
                state["next"] = "active_worker_do_not_redispatch"
            elif state["phase"] == "planning":
                state["next"] = "start"
            elif state["acceptance"]["awaiting_acceptance"]:
                # Fresh final check recorded but the phase transition was not
                # taken yet: the next step is the explicit transition.
                state["next"] = "enter_awaiting_acceptance"
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
            if action in {"replan", "reopen", "rework"}:
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
                    # Revisit markers: documents produced before this replan
                    # are logically unconfirmed against the new direction.
                    # session-context injection surfaces them while the task
                    # is in planning, and plan source-fingerprint validation
                    # refuses to dispatch a plan that cites a since-changed
                    # document, so stale docs cannot silently flow to work.
                    task["meta"]["replan"] = {
                        "at": self.clock(),
                        "reason": reason,
                        "docs_to_revisit": _docs_to_revisit(task_dir),
                        "baseline_commit": _git_head_commit(task_dir),
                        "plan_sha256": _plan_digest(task_dir),
                    }
                    self._event(task, "replanned", confirmation or self._actor_source(actor, "continue replan"), {"reason": reason, "docs_to_revisit": task["meta"]["replan"]["docs_to_revisit"], "baseline_commit": task["meta"]["replan"]["baseline_commit"]})
                elif action == "reopen":
                    if actor.get("role") != "user" or task["phase"] != "completed":
                        raise DomainError("reopen_forbidden", "Only a user may reopen an unarchived completed task", status=3)
                    # PRD R-004: a reopened task goes back to planning for
                    # rework; the normal start -> dispatch/check cycle
                    # re-applies before it can be accepted again.
                    task["phase"] = "planning"
                    task["completedAt"] = None
                    if task.get("acceptance"):
                        task["acceptance"]["state"] = "historical"
                    # A reopen means the user found a real problem with the
                    # accepted result; the previous final check no longer
                    # qualifies as fresh acceptance evidence, so a new
                    # independent final check is required before accept.
                    for evidence in task["evidence"]:
                        if evidence.get("kind") == "check" and evidence.get("scope") == "final" and evidence.get("state") == "valid":
                            evidence["state"] = "stale"
                            evidence["stale_reasons"] = [{"type": "reopened", "reason": reason}]
                    self._event(task, "reopened", confirmation or self._actor_source(actor, "continue reopen"), {"reason": reason})
                elif action == "rework":
                    # Same transition as report_problem, reachable through
                    # the continue surface: the user reports a problem while
                    # the task awaits acceptance. Both entry points share
                    # evidence.invalidate_scope, so a localized scope cannot
                    # mean one surface locally and the other globally.
                    if actor.get("role") != "user":
                        raise DomainError("rework_forbidden", "Only a user may report a problem on a task awaiting acceptance", status=3)
                    if task["phase"] != "awaiting_acceptance":
                        raise DomainError("rework_forbidden", "Rework applies to a task awaiting acceptance", {"phase": task["phase"]}, status=3)
                    invalidation = self.evidence.invalidate_scope(task, reason=reason, scope=scope)
                    if task.get("acceptance"):
                        task["acceptance"]["state"] = "stale"
                    task["phase"] = "planning"
                    task["lease"] = None
                    task["completedAt"] = None
                    self._event(task, "rework_requested", confirmation or self._actor_source(actor, "continue rework"), {
                        "reason": reason,
                        "scope": invalidation["scope"],
                        "invalidated_evidence_ids": invalidation["invalidated_evidence_ids"],
                        "retained_evidence_ids": invalidation["retained_evidence_ids"],
                    })
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

    def _criteria_item_ids(self, task: dict) -> set:
        """Every item id known to the task's artifact map.

        The union across all mapped artifacts: a rule may cite a criteria
        item that lives in any artifact the task maps (typically
        criteria.md), not only in the first one.
        """
        mappings = task.get("meta", {}).get("templates", {}).get("artifact_map", {})
        known = set()
        for artifact, items in (mappings or {}).items():
            if artifact == "mode" or not isinstance(items, dict):
                continue
            known.update(items.keys())
        return known

    def _validate_acceptance_rule(self, task: dict, rule: Optional[dict]) -> Optional[dict]:
        """Validate a rule-driven acceptance citation (S-4 K-3).

        ``rule_ref`` and ``quote`` stay mandatory. ``criteria_refs`` (the
        criteria items the rule actually judged), ``report`` (the report
        path) and ``scope`` (the range the rule covered) are optional and
        only recorded when given, so an OLD rule file keeps working
        unchanged. A cited criteria item that the task never established is
        refused: the acceptance record must not claim coverage of an item
        nobody can audit.
        """
        if rule is None:
            return None
        for key in ("rule_ref", "quote"):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                raise DomainError("invalid_acceptance_rule", "A rule-driven acceptance requires the rule reference and the user's exact quote")
        normalized = {"rule_ref": rule["rule_ref"], "quote": rule["quote"]}
        criteria_refs = rule.get("criteria_refs")
        if criteria_refs is not None:
            if not isinstance(criteria_refs, list) or not criteria_refs or not all(isinstance(entry, str) and entry.strip() for entry in criteria_refs):
                raise DomainError("invalid_acceptance_rule", "Rule criteria_refs must be a non-empty array of criteria item ids")
            unknown = sorted(set(criteria_refs) - self._criteria_item_ids(task))
            if unknown:
                raise DomainError("invalid_acceptance_rule", "Rule criteria_refs cite items the task never established", {"unknown": unknown})
            normalized["criteria_refs"] = list(criteria_refs)
        if rule.get("report") is not None:
            if not isinstance(rule.get("report"), str) or not rule["report"].strip():
                raise DomainError("invalid_acceptance_rule", "Rule report must be a non-empty path string")
            normalized["report"] = rule["report"]
        if rule.get("scope") is not None:
            if not isinstance(rule.get("scope"), str) or not rule["scope"].strip():
                raise DomainError("invalid_acceptance_rule", "Rule scope must be a non-empty string")
            normalized["scope"] = rule["scope"]
        return normalized

    def accept(self, ref: str, *, actor: dict, confirmation: dict, rule: Optional[dict] = None) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if actor.get("role") != "user":
                raise DomainError("acceptance_forbidden", "Only a user confirmation may complete a task", status=3)
            if task["phase"] != "awaiting_acceptance":
                # Design D-004: a fresh final check moves the task into
                # awaiting_acceptance; completion only happens from there.
                # An in-progress task must call enter_awaiting_acceptance
                # once its fresh final check has been recorded.
                raise DomainError("acceptance_blocked",
                                  "Only a task in awaiting_acceptance may be accepted; "
                                  "enter awaiting acceptance after a fresh final check",
                                  {"phase": task["phase"]}, status=3)
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
            normalized_rule = self._validate_acceptance_rule(task, rule)
            acceptance = {"confirmed_at": self.clock(), "confirmed_by": "user", "source": confirmation, "evidence_refs": status["evidence_refs"], "validates": {"task": source_snapshot(task), "delivery": delivery_digests}, "state": "valid"}
            if normalized_rule is not None:
                # The acceptance record keeps the rule citation (and the
                # criteria items it judged) so the exemption is auditable
                # from the task itself, not only from the event log.
                acceptance["rule_ref"] = normalized_rule["rule_ref"]
                acceptance["criteria_refs"] = normalized_rule.get("criteria_refs", [])
            task["acceptance"] = acceptance
            task["phase"] = "completed"
            task["completedAt"] = self.clock()
            accepted_data = {"evidence_refs": status["evidence_refs"]}
            if normalized_rule is not None:
                # Rule-driven acceptance exemption: the user's recorded rule
                # delegates acceptance for this class of work. The citation
                # (rule source + exact quote) lands in the event data so the
                # exemption always traces to the user's own words.
                accepted_data["accepted_via_rule"] = normalized_rule
            self._event(task, "accepted", confirmation, accepted_data)
            self._write(task_dir, task)
            return task

    def accept_unified(self, ref: str, *, actor: dict, confirmation: dict, rule: Optional[dict] = None) -> dict:
        """Unified cross-project acceptance (PRD R-005, design D-005).

        When the master task carries cross-project child links, one explicit
        user confirmation completes the master AND every linked child that
        the confirmation message listed. Before anything is written, every
        listed child is validated: reachable project, awaiting_acceptance
        phase, fresh qualifying final check, valid evidence state. Any
        failure blocks the whole acceptance with the reason; partial
        failure never fakes full success.

        The confirmation binds the CURRENT version of every task (the
        master's ``validates`` snapshot covers phase/description/templates
        and each child's snapshot is re-checked at write time inside the
        held locks, so an old acceptance can never be reused for a new
        delivery.

        Each child's acceptance event records its source as the master's
        unified confirmation reference (confirmation source_id + master
        task id), and carries the child's own version snapshot in
        ``validates`` so the binding is auditable per task.

        All writes happen inside one ordered cross-project lock region
        (master first, then every child project); every phase/evidence
        check re-runs under the locks on freshly re-read tasks, so a
        concurrent change between validation and write cannot slip through.
        The children are completed before the master, so a write failure
        leaves the master still in awaiting_acceptance: the region is
        crash-recoverable by retrying the same confirmation (each child
        write is a small atomic task.json replace, and a child already
        completed by this confirmation source is skipped idempotently).
        """
        from .crossproject import CROSS_LINKS_KEY, cross_project_locks, unified_acceptance_children
        if actor.get("role") != "user":
            raise DomainError("acceptance_forbidden", "Only a user confirmation may complete tasks", status=3)
        children = unified_acceptance_children(self.store, ref)
        # Two children may live in the SAME target project: the lock region
        # locks each physical project once (re-locking the same file through
        # a second descriptor would self-deadlock).
        target_stores = []
        seen_locks = set()
        for _, child_store, _ in children:
            key = str(child_store.lock_path)
            if key in seen_locks:
                continue
            seen_locks.add(key)
            target_stores.append(child_store)
        with cross_project_locks(self.store, *target_stores):
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task["phase"] != "awaiting_acceptance":
                raise DomainError("acceptance_blocked", "The master task is not awaiting acceptance",
                                  {"phase": task["phase"]}, status=3)
            self._require_children_ready(task_dir, task)
            validate_source(confirmation, task, actor=actor)
            # The master itself must also hold a fresh qualifying final
            # check: a delivery change after the check invalidates its own
            # acceptance exactly as it would in plain accept().
            master_status = self.evidence.acceptance_status(ref, task=task)
            if not master_status["awaiting_acceptance"]:
                raise DomainError("acceptance_blocked",
                                  "The master task's own final check is stale",
                                  master_status, status=3)
            # Validate children BEFORE writing anything: each child must be
            # a linked cross-project child in awaiting_acceptance with a
            # fresh qualifying final check and unchanged on-disk version.
            # A child already completed by THIS SAME confirmation (a retry
            # after a partial write) is accepted as done.
            pending = []
            for project_id, child_store, child_id in children:
                child_dir = child_store.resolve(child_id)
                child_task = child_store._read_path(child_dir / "task.json")
                if child_task["phase"] == "completed" and \
                        (child_task.get("acceptance") or {}).get("source", {}).get("source_id") == confirmation.get("source_id"):
                    continue
                self._validate_unified_child(child_store, child_dir, child_task, child_id, project_id, confirmation, actor)
                pending.append((project_id, child_store, child_id))
            # Everything validated. The children are completed FIRST and the
            # master LAST: a write failure between children leaves the
            # already-written children completed and the master still in
            # awaiting_acceptance, so the same confirmation retried as a
            # whole completes exactly the missing pieces (a child already
            # completed by this confirmation is skipped idempotently).
            reference = "%s unified acceptance %s" % (task["id"], confirmation.get("source_id"))
            completed = []
            for project_id, child_store, child_id in pending:
                child_dir = child_store.resolve(child_id)
                child_task = child_store._read_path(child_dir / "task.json")
                child_confirmation = dict(confirmation)
                child_confirmation["reference"] = reference
                child_confirmation["scope"] = "unified-acceptance child of %s" % task["id"]
                # The recorded source binds the child's CURRENT version, not
                # the master's snapshot: the acceptance record of the child
                # must describe the child it accepted.
                child_confirmation["validates"] = source_snapshot(child_task)
                completed.append(self._complete_one(child_store, child_dir, child_task, child_confirmation, actor,
                                                    accepted_via={"unified_confirmation": reference}))
            completed.append(self._complete_one(self.store, task_dir, task, confirmation, actor, rule=rule,
                                                accepted_via={"unified_confirmation": reference}))
            return {"completed": [{"task_id": item["id"], "name": item["name"], "phase": "completed"} for item in completed],
                    "children": len(children), "confirmation_source_id": confirmation.get("source_id")}

    def _validate_unified_child(self, child_store: TaskStore, child_dir, child_task: dict, child_id: str,
                               project_id: str, confirmation: dict, actor: dict) -> None:
        if child_task["phase"] != "awaiting_acceptance":
            raise DomainError("unified_child_not_ready",
                              "A linked child task is not awaiting acceptance",
                              {"project_id": project_id, "task_id": child_id, "phase": child_task["phase"],
                               "reason": "child_not_awaiting_acceptance"}, status=3)
        if child_task.get("meta", {}).get("disposition"):
            raise DomainError("unified_child_not_ready",
                              "A linked child task is dropped",
                              {"project_id": project_id, "task_id": child_id, "reason": "child_dropped"}, status=3)
        if child_task.get("blocked"):
            raise DomainError("unified_child_not_ready",
                              "A linked child task is blocked",
                              {"project_id": project_id, "task_id": child_id, "reason": "child_blocked"}, status=3)
        child_service = TaskService(child_store, clock=self.clock)
        status = child_service.evidence.acceptance_status(child_id, task=child_task)
        if not status["awaiting_acceptance"]:
            raise DomainError("unified_child_not_ready",
                              "A linked child task has no fresh qualifying final check",
                              {"project_id": project_id, "task_id": child_id,
                               "reason": "child_check_stale",
                               "blockers": status["blockers"]}, status=3)
        # Same-repo grandchildren of the child must be complete too, exactly
        # as a direct accept of that child would require.
        child_service._require_children_ready(child_dir, child_task)
        child_confirmation = dict(confirmation)
        child_confirmation["reference"] = "%s unified acceptance %s" % (child_id, confirmation.get("source_id"))
        # The user's ONE confirmation covered the listed child versions; the
        # child's binding is re-derived from the CURRENT child snapshot so
        # an acceptance taken for an older child version is refused here.
        child_confirmation["validates"] = source_snapshot(child_task)
        validate_source(child_confirmation, child_task, actor=actor)

    def _complete_one(self, store: TaskStore, task_dir, task: dict, confirmation: dict, actor: dict,
                       *, rule: Optional[dict] = None, accepted_via: Optional[dict] = None) -> dict:
        """Complete ONE fully validated task inside an already-held lock region.

        All gates (user-only, fresh final check, producer independence,
        same-repo children ready) have already passed in the caller under
        the locks; this method re-derives only the acceptance evidence refs
        (a pure read over the in-hand task) so a partially completed
        multi-project acceptance stays recoverable by retry.
        """
        status = self.evidence.acceptance_status(task["id"], task=task) if store is self.store \
            else TaskService(store, clock=self.clock).evidence.acceptance_status(task["id"], task=task)
        qualifying = [item for item in task["evidence"] if item.get("id") in status["evidence_refs"]]
        implementers = {item.get("producer", {}).get("id") for item in task["evidence"] if item.get("kind") == "delivery"}
        for item in qualifying:
            if item.get("producer", {}).get("id") in implementers:
                raise DomainError("check_not_independent", "The final check producer also delivered the implementation", status, status=3)
        delivery_digests = [item.get("delivery", {}).get("digest") for item in qualifying]
        normalized_rule = self._validate_acceptance_rule(task, rule)
        acceptance = {"confirmed_at": self.clock(), "confirmed_by": "user", "source": confirmation,
                      "evidence_refs": status["evidence_refs"],
                      "validates": {"task": source_snapshot(task), "delivery": delivery_digests},
                      "state": "valid"}
        if normalized_rule is not None:
            acceptance["rule_ref"] = normalized_rule["rule_ref"]
            acceptance["criteria_refs"] = normalized_rule.get("criteria_refs", [])
        task["acceptance"] = acceptance
        task["phase"] = "completed"
        task["completedAt"] = self.clock()
        accepted_data = {"evidence_refs": status["evidence_refs"]}
        if accepted_via:
            accepted_data["accepted_via"] = accepted_via
        if normalized_rule is not None:
            accepted_data["accepted_via_rule"] = normalized_rule
        service = self if store is self.store else TaskService(store, clock=self.clock)
        service._event(task, "unified_acceptance" if accepted_via else "accepted", confirmation, accepted_data)
        service._write(task_dir, task)
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
            detail = {"id": extension_id}
            if extension_id == "tool-capability":
                detail["retired"] = "Historical tasks keep the record; the package cannot be enabled."
            raise DomainError("unknown_extension", "Unknown extension package", detail)
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

    def record_correction(self, ref: str, *, record: dict, actor: dict) -> dict:
        """Record a user correction as an append-only event. Pure capture.

        Learning-loop candidate capture. This writes ONLY an event: no
        knowledge write, no behavior change, no extension grant — the
        three-layer rule (capture automatic, write authorized) keeps this
        outside the learn pipeline. ``user_signal`` must be the user's actual
        words, never an agent summary, so a later retro can quote it verbatim.
        """
        source = record.get("source")
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            self._require_active(task, "correction record")
            validate_source(source, task, actor=actor)
            user_signal = record.get("user_signal")
            if not isinstance(user_signal, str) or not user_signal.strip():
                raise DomainError("invalid_correction", "A correction requires the user's exact words as user_signal")
            data = {"user_signal": user_signal, "target": record.get("target", ""), "note": record.get("note", "")}
            self._event(task, "correction", source, data)
            self._write(task_dir, task)
            return {"recorded": True, "type": "correction", "user_signal": user_signal}

    def list_corrections(self, ref: str) -> list:
        return [event for event in self.store.read(ref)["events"] if event.get("type") == "correction"]

    def _validate_archive_tree(self, task_dir: Path, finalizations: Optional[list] = None) -> set:
        if finalizations is None:
            finalizations = []
        task = self.store._read_path(task_dir / "task.json")
        names = self._children_consistency(task_dir, task)
        if task.get("blocked") or task.get("lease"):
            raise DomainError("archive_blocked", "Blocked or leased descendants cannot be archived", {"task": task["name"]}, status=3)
        disposition = task.get("meta", {}).get("disposition")
        if disposition:
            if disposition.get("pending_cleanup") or disposition.get("pending_knowledge"):
                # Archiving IS the cleanup: removing the tree from the active
                # root completes a discard disposition (and finalizes the
                # knowledge-extraction reminder for a knowledge disposition).
                # Collect the pending node here; the flags are cleared and the
                # event recorded only after the WHOLE tree validates, so a
                # failed archive (any other blocker) leaves them intact.
                finalizations.append((task_dir, task))
        else:
            if task["phase"] != "completed" or not task.get("acceptance") or task["acceptance"].get("state") != "valid":
                raise DomainError("archive_blocked", "Every task in the tree must be completed or dispositioned", {"task": task["name"]}, status=3)
            # Acceptance is a historical decision: it was made when the final
            # check was fresh, and later batches legitimately evolve shared
            # files. Re-validating current file fingerprints here would make
            # every completed task unarchivable after the next merge, so the
            # gate trusts the recorded acceptance state itself.
            if not task["acceptance"].get("evidence_refs"):
                raise DomainError("archive_blocked", "Acceptance has no qualifying evidence references", {"task": task["name"]}, status=3)
        ids = {task["id"]}
        for name in names:
            ids.update(self._validate_archive_tree(task_dir / "subtasks" / name, finalizations))
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
                    actual_target = self.store.identity_path(archived)
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
            finalizations = []
            tree_ids = self._validate_archive_tree(task_dir, finalizations)
            target = self.store.archive_root / month / task["name"]
            if target.exists() or target.is_symlink():
                target_task = target / "task.json"
                if target_task.is_file():
                    existing = self.store._read_path(target_task)
                    matching = any(e.get("type") == "archived" and e.get("data", {}).get("operation_id") == operation_id for e in existing["events"])
                    if existing["id"] == task["id"] and matching:
                        return {"task": existing, "path": str(target), "recovered": True}
                raise DomainError("archive_conflict", "Archive destination already exists", {"target": str(target)}, status=4)
            # Only after every fallible pre-move check has passed do we converge
            # pending drop dispositions. `transaction()` is a file lock, not a
            # rollback-capable transaction, so writing these before the
            # destination check would let a failed archive clear the pending
            # flags (and record a false finalization) on a still-active task.
            for pending_dir, pending_task in finalizations:
                # Archiving IS the cleanup: removing the tree from the active
                # root completes a discard disposition (and finalizes the
                # knowledge-extraction reminder for a knowledge disposition).
                disposition = pending_task["meta"]["disposition"]
                cleared = {"pending_cleanup": bool(disposition.get("pending_cleanup")), "pending_knowledge": bool(disposition.get("pending_knowledge"))}
                disposition["pending_cleanup"] = False
                disposition["pending_knowledge"] = False
                self._event(pending_task, "disposition_finalized", confirmation, {"finalized_by": "archive", "cleared": cleared, "actor": actor.get("id")})
                self._write(pending_dir, pending_task)
            # Re-read the root so a finalized root disposition is not
            # overwritten by the stale pre-validation copy below.
            if finalizations:
                task = self.store._read_path(task_dir / "task.json")
            pending = make_event("archive_operation", confirmation, {"operation_id": operation_id, "target": self.store.identity_path(target), "archived_at": now}, now)
            task["events"].append(pending)
            self._write(task_dir, task)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(task_dir), str(target))
            task = self.store._read_path(target / "task.json")
            task["archivedAt"] = now
            self._event(task, "archived", confirmation, {"operation_id": operation_id, "target": self.store.identity_path(target)})
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

    def _origin_followups(self, parent_id: str) -> list:
        """Top-level active tasks whose origin.task_id points at ``parent_id``."""
        found = []
        if not self.store.tasks_root.exists():
            return found
        for path in self.store.tasks_root.iterdir():
            if not path.is_dir() or path.is_symlink() or path.parent != self.store.tasks_root:
                continue
            task_file = path / "task.json"
            if not task_file.is_file():
                continue
            try:
                task = self.store._read_path(task_file)
            except DomainError:
                continue
            if (task.get("origin") or {}).get("task_id") == parent_id:
                found.append((path, task))
        return found

    def unarchive(self, ref: str, *, actor: dict, confirmation: dict, reason: Optional[str] = None) -> dict:
        """Move an archived top-level task tree back to the active root (A-001).

        Mirrors archive() in reverse: only a top-level archived task can be
        unarchived (the archive tree is an accepted snapshot; partial
        recovery would leave a month directory with a broken parent tree).
        Requires an explicit user confirmation through the same
        validate_source chain as start/reopen. The phase is untouched
        (the parent stays completed); acceptance/evidence stay exactly as
        recorded. Follow-up tasks that grew at the tasks_root top level
        with origin.task_id pointing at this parent are attached into its
        subtasks/ (children registered, origin kept for traceability).
        """
        with self.store.transaction():
            task_dir = self.store.resolve(ref, archived=True)
            try:
                task_dir.relative_to(self.store.archive_root)
            except ValueError:
                raise DomainError("not_archived", "Only an archived task can be unarchived", {"path": str(task_dir)}, status=3)
            if task_dir.parent.parent != self.store.archive_root:
                raise DomainError("unarchive_child_forbidden", "Subtasks are unarchived only with their root task", status=3)
            task = self.store._read_path(task_dir / "task.json")
            if actor.get("role") != "user":
                raise DomainError("unarchive_forbidden", "Only a user may move an archived task back to the active root", status=3)
            validate_source(confirmation, task, actor=actor)
            acceptance = task.get("acceptance")
            if acceptance is not None and acceptance.get("state") != "valid":
                # Defensive only: a non-valid acceptance should not exist in
                # the archive tree. Refuse loudly instead of silently
                # repairing (design §4).
                raise DomainError("unarchive_blocked", "Archived task does not carry a valid acceptance", {"task": task["name"]}, status=3)
            target = self.store.tasks_root / task["name"]
            if target.exists() or target.is_symlink():
                raise DomainError("archive_conflict", "Unarchive destination already exists", {"target": str(target)}, status=4)
            tree = self._scan_tree(task_dir)
            tree_ids = {item["id"] for item in tree}
            from_path = self.store.identity_path(task_dir)
            archived_at = task.get("archivedAt")
            # Move first, event after: a failed rename leaves the archive
            # tree untouched and no event is written (archive()'s convention).
            self.store.tasks_root.mkdir(parents=True, exist_ok=True)
            os.rename(str(task_dir), str(target))
            for item_path in sorted(target.rglob("task.json")):
                item = self.store._read_path(item_path)
                if item.get("archivedAt") is not None:
                    item["archivedAt"] = None
                    self._write(item_path.parent, item)
            task = self.store._read_path(target / "task.json")
            self._event(task, "unarchived", confirmation, {"from": from_path, "reason": reason or "", "archivedAt": archived_at})
            self._write(target, task)
            # Attach aggregation (design §2.4): top-level follow-up tasks
            # whose origin points at this parent migrate into its subtasks/.
            attached = []
            for followup_dir, followup in self._origin_followups(task["id"]):
                if followup["name"] in task["children"]:
                    continue
                self._children_consistency(target, task)
                destination = target / "subtasks" / followup["name"]
                if destination.exists() or destination.is_symlink():
                    raise DomainError("archive_conflict", "Attach destination already exists", {"target": str(destination)}, status=4)
                os.rename(str(followup_dir), str(destination))
                task["children"].append(followup["name"])
                # origin is kept verbatim for traceability; the physical
                # relation is now expressed through children like any other
                # nested subtask.
                self._write(target, task)
                attached.append(followup["name"])
            if attached:
                # Record the attach on the same milestone event so the
                # aggregation stays auditable without a second event type.
                task["events"][-1]["data"]["attached"] = attached
                self._write(target, task)
            self.store.clear_tree_pointers(tree_ids)
            return {"task": task, "path": str(target), "from": from_path, "attached": attached}

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

    def archive_candidates(self, *, older_than_days: int = 7) -> list:
        # Completed tasks are nagged sooner: a finished task only waits for
        # its archive confirmation, so a short window is enough. Incomplete
        # tasks keep a longer horizon below so reminders do not fire while
        # work is still active.
        threshold_completed = parse_time(self.clock()) - timedelta(days=older_than_days)
        threshold_active = parse_time(self.clock()) - timedelta(days=30)
        candidates = []
        for task in self.store.scan(archived=False):
            path = Path(task["_path"])
            if path.parent != self.store.tasks_root:
                continue
            substantial = [event["at"] for event in task["events"] if event.get("type") not in {"summary", "lease_renewed"} and event.get("at")]
            last = max(substantial + [task["createdAt"]])
            is_completed = task["phase"] == "completed" or bool(task.get("meta", {}).get("disposition"))
            if is_completed:
                if parse_time(last) > threshold_completed:
                    continue
            elif parse_time(last) > threshold_active:
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
