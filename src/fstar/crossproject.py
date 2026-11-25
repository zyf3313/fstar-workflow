"""Cross-project task coordination (fstar.crossproject.v1, task P-002).

Master/child task links across DIFFERENT fstar projects, dispatch from a
master task into a linked child task in the target project, and read-only
status views across projects.

Storage of links (design §3 / D-001): each side records its own copy under
``task["meta"]["cross_project_links"]`` as
``{direction: child|parent, project_id, task_id, path_hint}``. The existing
26-field task.json structure, the same-repo ``children`` string semantics,
and the absence of a top-level parent field are all preserved. ``path_hint``
is a location hint only; authoritative resolution goes through the project
registry / recorded project identity, never through the hint alone.

Lock ordering for cross-project writes (scope item 5): acquire the MASTER
project lock first, then every further project lock in ascending lock-path
order. All writes happen only after every lock is held, so a timeout or
crash leaves zero partial records; a failed operation is retried wholesale.
Reciprocal operations (A masters B while B masters A concurrently) can
contend under this role-based order; the bounded lock timeout turns that
into an explicit ``lock_timeout`` error with no partial writes, and the
caller retries — never a silent half-linked state.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

from .evidence import file_digest
from .models import DomainError, new_task
from .store import TaskStore, _read_registry, _registry_path
from .tasks import TaskService, make_event, utc_now

CROSS_LINKS_KEY = "cross_project_links"
SPEC_NOTE_KEY = "cross_project_spec_note"
_PATH_ID_PREFIX = "path:"

SPEC_NOTE_TEXT = "target project has no specs yet"


def project_identity(store: TaskStore) -> str:
    """Stable identity string for a project in link records.

    Initialized projects carry a UUID in config.yaml. A legacy project
    without one falls back to a path-derived identity so links still work;
    the registry remains the authoritative resolver for user-directory
    projects.
    """
    if store.project_id:
        return store.project_id
    return _PATH_ID_PREFIX + str(store.project_root)


def _links(task: dict) -> list:
    return list(task.get("meta", {}).get(CROSS_LINKS_KEY, []))


def _add_link(task: dict, entry: dict) -> None:
    links = task.setdefault("meta", {}).setdefault(CROSS_LINKS_KEY, [])
    links.append(entry)


@contextlib.contextmanager
def cross_project_locks(master: TaskStore, *others: TaskStore) -> Iterator[None]:
    """Lock several project stores in the defined cross-project order.

    Order: the master project first, then the remaining stores sorted by
    lock path (see module docstring). The same physical project never locks
    twice (flock is per open-file-description; re-locking through a second
    fd would self-deadlock). Every write happens inside this region, so a
    ``lock_timeout`` leaves both sides untouched and the operation is
    retriable as a whole.
    """
    ordered = [master] + sorted(others, key=lambda store: str(store.lock_path))
    streams = []
    seen_locks = set()
    try:
        for store in ordered:
            lock_key = str(store.lock_path)
            if lock_key in seen_locks:
                raise DomainError("same_project_link",
                                  "Cross-project links require two different projects; "
                                  "use regular children inside one project", status=3)
            seen_locks.add(lock_key)
            store.require_project()
            store.lock_path.parent.mkdir(parents=True, exist_ok=True)
            stream = store.lock_path.open("a+")
            deadline = time.monotonic() + store.lock_timeout
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DomainError("lock_timeout",
                                          "Timed out waiting for a cross-project lock "
                                          "(no partial records were written)",
                                          {"project": str(store.project_root)}, status=4)
                    time.sleep(0.02)
            streams.append(stream)
        yield
    finally:
        for stream in reversed(streams):
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()


def spec_index_entries(store: TaskStore) -> list:
    """Fingerprinted spec index files of one project (its own specs, never
    another project's)."""
    specs = store.fstar_root / "specs"
    entries = []
    if not specs.is_dir():
        return entries
    for path in sorted(specs.rglob("index.md")):
        if path.is_symlink() or not path.is_file():
            continue
        entries.append({"path": store.identity_path(path), "sha256": file_digest(path)})
    return entries


SPEC_PLACEHOLDER_MARKERS = ("待补", "To fill", "TODO:")
SPEC_TEMPLATE_BODY = ("Write concise, executable guidance in `language.specs` "
                      "(default English). Prefer existing authoritative project "
                      "documentation and include a source or short example "
                      "when useful.")


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2] if len(parts) == 3 else text


def _spec_file_is_placeholder(path: Path) -> bool:
    """True when one spec file is still an unfilled skeleton.

    The generated skeletons are recognizable by their own markers: the
    ``待补`` placeholders the init flow writes, a ``To fill`` or ``TODO:``
    line, the untouched spec-template body, or a near-empty file. Reading
    errors are treated as placeholder (guidance, never a block).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return True
    body = _strip_frontmatter(text).strip()
    if len(body) < 50:
        return True
    if SPEC_TEMPLATE_BODY in body:
        # The untouched template sentence is still there: the file is a
        # skeleton unless real content was added around it.
        remainder = body.replace(SPEC_TEMPLATE_BODY, "").strip()
        if len(remainder) < 50:
            return True
    return any(marker in body for marker in SPEC_PLACEHOLDER_MARKERS)


def spec_status(store: TaskStore) -> dict:
    """Classify the target project's own specs (D-003).

    ``missing``    no specs directory at all
    ``empty``      directory exists but holds no index files
    ``placeholder`` every spec topic is still the generated skeleton
    ``present``    at least one topic holds real content
    A placeholder status is guidance, never a permanent block.
    """
    specs = store.fstar_root / "specs"
    if not specs.is_dir():
        return {"status": "missing", "files": []}
    index_files = [p for p in sorted(specs.rglob("index.md"))
                   if p.is_file() and not p.is_symlink()]
    if not index_files:
        return {"status": "empty", "files": []}
    all_files = [p for p in sorted(specs.rglob("*.md"))
                 if p.is_file() and not p.is_symlink()]
    # A topic counts as filled when at least one of its files (index or
    # per-dimension detail) carries real content; an all-placeholder topic
    # is still a skeleton.
    topics: dict = {}
    for path in all_files:
        topics.setdefault(path.parent, []).append(path)
    filled_topics = 0
    for topic, files in topics.items():
        if any(not _spec_file_is_placeholder(path) for path in files):
            filled_topics += 1
    status = "present" if filled_topics else "placeholder"
    return {"status": status, "files": [store.identity_path(p) for p in index_files]}


class CrossProjectService:
    def __init__(self, store: TaskStore, *, task_service: Optional[TaskService] = None,
                 clock=None):
        self.store = store
        self.clock = clock or utc_now
        self.tasks = task_service or TaskService(store, clock=self.clock)
        self.user_home = store.user_home
        self.runtime_root = store.runtime_root

    # -- target resolution ------------------------------------------------

    def _target_store_for_path(self, path: Path) -> TaskStore:
        return TaskStore(Path(path).expanduser().resolve(),
                         user_home=self.user_home, runtime_root=self.runtime_root)

    def resolve_target(self, target: str) -> TaskStore:
        """Resolve a target project by registry id or filesystem path.

        Authoritative for user-directory projects is the registry entry
        (stable project UUID); a path argument is accepted for project-shared
        and project-local targets and for explicit user overrides. A stale
        registry binding (moved/deleted repository) is a clear block with the
        recorded path as reason, never an auto-rebind.
        """
        registry = _read_registry(_registry_path(self.user_home))
        projects = registry.get("projects", {})
        if isinstance(target, str) and target in projects:
            entry = projects[target]
            recorded = Path(entry.get("path", "")).expanduser()
            if not recorded.is_dir():
                raise DomainError("target_project_unavailable",
                                  "The target project path is unavailable (moved or deleted); "
                                  "rebind it explicitly before cross-project work",
                                  {"project_id": target, "recorded_path": str(recorded)}, status=3)
            store = self._target_store_for_path(recorded)
            store.require_project()
            return store
        path = Path(target).expanduser()
        if path.exists():
            store = self._target_store_for_path(path)
            try:
                store.require_project()
            except DomainError as exc:
                if exc.code == "project_not_initialized":
                    # D-003: an uninitialized target never gains a task; the
                    # caller is directed to the init flow instead.
                    raise DomainError("target_not_initialized",
                                      "The target project has no fstar data root; "
                                      "initialize it (init flow) before cross-project work",
                                      {"target": str(path)}, status=3) from exc
                raise
            return store
        raise DomainError("unknown_target_project",
                          "Target project is neither a registered project id nor an existing path",
                          {"target": str(target)}, status=3)

    def _store_by_identity(self, project_id: str, path_hint: str) -> Optional[TaskStore]:
        """Resolve a link entry's project; None (with reason) when unavailable."""
        return self._resolve_identity(project_id, path_hint)

    def _resolve_identity(self, project_id: str, path_hint: str) -> Optional[TaskStore]:
        registry = _read_registry(_registry_path(self.user_home))
        entry = registry.get("projects", {}).get(project_id)
        if isinstance(entry, dict):
            recorded = Path(entry.get("path", "")).expanduser()
            if not recorded.is_dir():
                return None
            return self._target_store_for_path(recorded)
        candidate = project_id[len(_PATH_ID_PREFIX):] if project_id.startswith(_PATH_ID_PREFIX) \
            else (path_hint or "")
        if candidate and Path(candidate).expanduser().is_dir():
            return self._target_store_for_path(Path(candidate))
        return None

    # -- link operations ---------------------------------------------------

    def create_child(self, master_ref: str, *, target: str, name: str, title: str,
                     description: str = "", actor: Optional[dict] = None) -> dict:
        """Create a real task in the target project and link both sides.

        The child task lives in the target project's own data root; the
        master gains a ``child`` link and the child a ``parent`` link. Both
        records are written inside one ordered lock region, so the pair is
        either fully recorded or not at all.
        """
        actor = actor or {"role": "agent", "id": "coordinator"}
        target_store = self.resolve_target(target)
        if target_store.project_root == self.store.project_root:
            raise DomainError("same_project_link",
                              "Cross-project links require two different projects; "
                              "use regular children inside one project", status=3)
        with cross_project_locks(self.store, target_store):
            master_dir = self.store.resolve(master_ref)
            master_task = self.store._read_path(master_dir / "task.json")
            if master_task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "A dropped task cannot gain cross-project children", status=3)
            # Build the child task in the target project.
            child = new_task(name, title, description, creator=actor.get("id", "coordinator"),
                             now=self.clock())
            child["meta"] = {"disposition": None, "templates": {}, "related_tasks": [], "reminders": {}}
            child["events"].append(make_event(
                "created", self._source(actor),
                {"parent": None, "cross_project_master": master_task["id"]},
                self.clock()))
            child_dir = target_store.tasks_root / name
            if child_dir.exists() or child_dir.is_symlink():
                raise DomainError("task_exists", "Target task destination already exists",
                                  {"path": str(child_dir)}, status=4)
            import os
            import shutil
            staging = child_dir.parent / (".%s.staging-%s" % (name, uuid.uuid4().hex))
            created_child_dir = False
            # Both sides are written inside this one lock region and the
            # target side goes first: if the master write then fails, the
            # freshly created child task is removed again, so the pair is
            # either fully recorded on both sides or not at all.
            try:
                # Link both sides (bidirectional, each side its own copy).
                _add_link(master_task, {"direction": "child",
                                        "project_id": project_identity(target_store),
                                        "task_id": child["id"],
                                        "path_hint": str(target_store.project_root)})
                master_task["events"].append(make_event(
                    "cross_project_linked", self._source(actor),
                    {"direction": "child", "project_id": project_identity(target_store),
                     "task_id": child["id"], "path_hint": str(target_store.project_root)},
                    self.clock()))
                _add_link(child, {"direction": "parent",
                                  "project_id": project_identity(self.store),
                                  "task_id": master_task["id"],
                                  "path_hint": str(self.store.project_root)})
                child["events"].append(make_event(
                    "cross_project_linked", self._source(actor),
                    {"direction": "parent", "project_id": project_identity(self.store),
                     "task_id": master_task["id"], "path_hint": str(self.store.project_root)},
                    self.clock()))
                staging.mkdir(parents=True)
                target_store.write(staging, child)
                os.rename(str(staging), str(child_dir))
                created_child_dir = True
                self.store.write(master_dir, master_task)
            except Exception:
                if staging.exists():
                    shutil.rmtree(str(staging))
                if created_child_dir and child_dir.exists():
                    shutil.rmtree(str(child_dir))
                raise
        return {"child": {"task_id": child["id"], "name": name,
                          "project_root": str(target_store.project_root),
                          "data_root": str(target_store.fstar_root),
                          "path": str(child_dir)},
                "master": {"task_id": master_task["id"], "name": master_task["name"]}}

    def link_existing(self, master_ref: str, *, target: str, target_task: str,
                      actor: Optional[dict] = None) -> dict:
        """Link an existing target task as a cross-project child of master."""
        actor = actor or {"role": "agent", "id": "coordinator"}
        target_store = self.resolve_target(target)
        if target_store.project_root == self.store.project_root:
            raise DomainError("same_project_link",
                              "Cross-project links require two different projects", status=3)
        target_id = target_store.read(target_task)["id"]
        with cross_project_locks(self.store, target_store):
            master_dir = self.store.resolve(master_ref)
            master_task = self.store._read_path(master_dir / "task.json")
            child_dir = target_store.resolve(target_task)
            child_task = target_store._read_path(child_dir / "task.json")
            identity = project_identity(target_store)
            for link in _links(master_task):
                if link.get("direction") == "child" \
                        and self._entry_points_to(link, target_store, target_id):
                    raise DomainError("duplicate_link",
                                      "This cross-project link already exists on the master task",
                                      {"project_id": identity, "task_id": target_id}, status=4)
            if master_task["id"] == target_id and self.store.project_root == target_store.project_root:
                raise DomainError("duplicate_link", "A task cannot link to itself", status=4)
            # Cycle: the would-be child (target task) is already an ancestor
            # of the would-be parent (master) through parent links.
            for entry, store in self._parent_chain(master_dir, master_task):
                if entry.get("task_id") != target_id:
                    continue
                if entry.get("project_id") == identity or (
                        store is not None and store.project_root == target_store.project_root):
                    raise DomainError("cross_project_cycle",
                                      "Linking would create a cross-project parent-child cycle",
                                      {"project_id": identity, "task_id": target_id}, status=3)
            original_child = json.loads(json.dumps(child_task))
            _add_link(master_task, {"direction": "child", "project_id": identity,
                                    "task_id": target_id,
                                    "path_hint": str(target_store.project_root)})
            master_task["events"].append(make_event(
                "cross_project_linked", self._source(actor),
                {"direction": "child", "project_id": identity, "task_id": target_id,
                 "path_hint": str(target_store.project_root)}, self.clock()))
            _add_link(child_task, {"direction": "parent",
                                   "project_id": project_identity(self.store),
                                   "task_id": master_task["id"],
                                   "path_hint": str(self.store.project_root)})
            child_task["events"].append(make_event(
                "cross_project_linked", self._source(actor),
                {"direction": "parent", "project_id": project_identity(self.store),
                 "task_id": master_task["id"], "path_hint": str(self.store.project_root)},
                self.clock()))
            # Target side first: if the master write then fails, the target
            # side is restored, so both sides are linked or neither is.
            target_store.write(child_dir, child_task)
            try:
                self.store.write(master_dir, master_task)
            except Exception:
                try:
                    target_store.write(child_dir, original_child)
                except Exception:  # pragma: no cover - rollback best effort
                    pass
                raise
        return {"linked": True, "master": master_task["id"], "child": target_id,
                "project_id": identity}

    def _entry_points_to(self, entry: dict, store: "TaskStore", task_id: str) -> bool:
        """True when a link entry points at ``task_id`` inside ``store``.

        The recorded ``project_id`` is compared first, but a project that
        gained its config UUID after the link was recorded carries a
        different identity string for the same project. The resolved
        project root is therefore the authoritative comparison, so a link
        is still recognised (and a duplicate still refused) after such an
        identity change.
        """
        if entry.get("task_id") != task_id:
            return False
        if entry.get("project_id") == project_identity(store):
            return True
        resolved = self._store_by_identity(entry.get("project_id", ""),
                                           entry.get("path_hint", ""))
        return resolved is not None and resolved.project_root == store.project_root

    def _parent_chain(self, task_dir: Path, task: dict):
        """Yield (entry, resolved_store) ancestor parent links; loop-safe.

        The resolved store is None when the ancestor project is no longer
        reachable. Ancestors are compared by resolved project root where
        possible, so an identity change (e.g. a legacy project that gained
        its config UUID) does not hide an existing cycle.
        """
        seen = {(project_identity(self.store), task["id"])}
        queue = list(_links(task))
        while queue:
            entry = queue.pop(0)
            key = (entry.get("project_id"), entry.get("task_id"))
            if key in seen or entry.get("direction") != "parent":
                continue
            seen.add(key)
            store = self._store_by_identity(entry.get("project_id", ""),
                                            entry.get("path_hint", ""))
            yield entry, store
            if store is None:
                continue
            try:
                ancestor = store._read_path(store.resolve(entry["task_id"]) / "task.json")
            except DomainError:
                continue
            queue.extend(_links(ancestor))

    def links(self, ref: str) -> dict:
        """List a task's cross-project links with live status per entry."""
        task = self.store.read(ref)
        result = []
        for entry in _links(task):
            row = dict(entry)
            store = self._store_by_identity(entry.get("project_id", ""),
                                            entry.get("path_hint", ""))
            if store is None:
                row.update({"available": False,
                            "reason": "project path unavailable (moved or deleted)"})
                result.append(row)
                continue
            try:
                linked = store._read_path(store.resolve(entry["task_id"]) / "task.json")
            except DomainError as exc:
                row.update({"available": True, "reason": exc.code})
                result.append(row)
                continue
            row.update({"available": True, "reason": "",
                        "phase": linked["phase"],
                        "blocked": bool(linked.get("blocked")),
                        "disposition": bool(linked.get("meta", {}).get("disposition")),
                        "project_root": str(store.project_root),
                        "storage_mode": store.storage_mode})
            result.append(row)
        return {"task_id": task["id"], "links": result}

    # -- dispatch ------------------------------------------------------------

    def dispatch(self, master_ref: str, *, target: str, target_task: str, role: str,
                 plan_item_ids: list, allowed_paths: list,
                 required_validations: Optional[list] = None,
                 coordinator_id: str = "coordinator",
                 actor: Optional[dict] = None,
                 baseline: Optional[dict] = None,
                 input_versions: Optional[list] = None) -> dict:
        """Dispatch from a master task to a linked child task (D-001/D-003).

        Pre-dispatch checks run first: the target data root must resolve
        (not-initialized targets are refused with init guidance), and the
        master must hold a child link to the target task. Spec loading uses
        the TARGET project's own specs; the master project's specs are never
        substituted. Placeholder/empty specs do not block: the fact is
        recorded on the child task and the dispatch continues.
        """
        from .dispatch import DispatchService, build_payload
        actor = actor or {"role": "coordinator", "id": coordinator_id}
        master_task = self.store.read(master_ref)
        target_store = self.resolve_target(target)
        if target_store.project_root == self.store.project_root:
            raise DomainError("same_project_link",
                              "Cross-project dispatch requires a different project", status=3)
        identity = project_identity(target_store)
        target_id = target_store.read(target_task)["id"]
        linked = any(entry.get("direction") == "child"
                     and self._entry_points_to(entry, target_store, target_id)
                     for entry in _links(master_task))
        if not linked:
            raise DomainError("unknown_link",
                              "The master task has no cross-project child link to this target task",
                              {"project_id": identity, "task_id": target_id}, status=3)
        child_dir = target_store.resolve(target_task)
        child_ref = str(child_dir.relative_to(target_store.tasks_root))
        specs = spec_status(target_store)
        if specs["status"] in ("missing", "empty", "placeholder"):
            # Record-and-continue (D-003): never permanently block on
            # placeholder content. The note is meta (compaction-proof) plus
            # an event, both in the TARGET task.
            with target_store.transaction():
                current = target_store._read_path(child_dir / "task.json")
                current.setdefault("meta", {})[SPEC_NOTE_KEY] = {
                    "at": self.clock(), "project_id": identity,
                    "status": specs["status"], "note": SPEC_NOTE_TEXT}
                current["events"].append(make_event(
                    "cross_project_spec_note", self._source(actor),
                    {"project_id": identity, "status": specs["status"],
                     "note": SPEC_NOTE_TEXT}, self.clock()))
                target_store.write(child_dir, current)
        read_context = spec_index_entries(target_store)
        payload = build_payload(role=role, task_ref=child_ref,
                                plan_item_ids=plan_item_ids,
                                allowed_paths=allowed_paths,
                                baseline=baseline or {"artifact_items": [],
                                                      "delivery": {"paths": [], "digest": ""}},
                                input_versions=input_versions or [],
                                read_context=read_context,
                                required_validations=required_validations or [])
        target_service = TaskService(target_store, clock=self.clock)
        service = DispatchService(target_store, task_service=target_service)
        registration = service.register(payload, coordinator_id=coordinator_id, actor=actor)
        return {"dispatch": registration,
                "target_project": {"project_root": str(target_store.project_root),
                                   "data_root": str(target_store.fstar_root),
                                   "storage_mode": target_store.storage_mode,
                                   "project_id": identity},
                "worker_cwd": str(target_store.project_root),
                "target_specs": specs,
                "spec_note_recorded": specs["status"] in ("missing", "empty", "placeholder"),
                "master_task_id": master_task["id"]}

    def _source(self, actor: dict) -> dict:
        return {"source_id": str(uuid.uuid4()), "type": "system", "at": self.clock(),
                "actor": actor, "reference": "cross-project", "quote": "",
                "scope": "cross-project", "validates": ""}


def foreign_task_candidates(store: TaskStore, task_ref: str, *, limit: int = 5) -> dict:
    """Read-only foreign-project candidate hints for a local task_not_found (A-005).

    Reads ONLY the configured user project registry
    (``<user_home>/projects.json``); no filesystem-wide scan, no project
    switching, no writes anywhere. Every registered project other than the
    local one is probed read-only: a broken, moved, corrupt, or otherwise
    unreadable project is skipped safely and reported under ``skipped``,
    never raised as an error. Same-name matches in several projects stay
    explicit separate candidates. The result is advisory detail for the
    failure message; the local lookup semantics never change.
    """
    result = {"candidates": [], "skipped": []}
    try:
        registry = _read_registry(_registry_path(store.user_home))
    except (DomainError, OSError, ValueError):
        return result
    seen_projects = set()
    for project_id, entry in sorted(registry.get("projects", {}).items()):
        if not isinstance(entry, dict):
            continue
        recorded = entry.get("path", "")
        if not isinstance(recorded, str) or not recorded:
            continue
        try:
            target_root = Path(recorded).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            result["skipped"].append({"project_id": project_id, "path": recorded})
            continue
        # The registry may name the project we are already in: its tasks
        # were already searched by the failing local lookup.
        if target_root == store.project_root:
            continue
        if target_root in seen_projects:
            continue
        seen_projects.add(target_root)
        try:
            probe = TaskStore(target_root, user_home=store.user_home,
                              runtime_root=store.runtime_root)
            probe.require_project()
        except (DomainError, OSError, RuntimeError, ValueError, TypeError):
            # Unavailable/corrupt unrelated project: never break the local
            # lookup; record it as skipped for honest reporting.
            result["skipped"].append({"project_id": project_id, "path": recorded})
            continue
        for archived_flag in (False, True):
            try:
                hits = probe.scan(archived=archived_flag)
            except (DomainError, OSError, ValueError, TypeError, RuntimeError):
                result["skipped"].append({"project_id": project_id, "path": recorded})
                continue
            for task in hits:
                root = probe.archive_root if archived_flag else probe.tasks_root
                relative = str(Path(task["_path"]).relative_to(root))
                if task_ref not in (task.get("id"), task.get("name"), relative):
                    continue
                result["candidates"].append({
                    "project_id": project_id,
                    "project": str(target_root),
                    "task_id": task.get("id"),
                    "name": task.get("name"),
                    "phase": task.get("phase"),
                    "archived": archived_flag,
                    "path": task.get("_path", ""),
                })
                if len(result["candidates"]) >= limit:
                    return result
    return result


def unified_acceptance_children(store: TaskStore, ref: str) -> list:
    """Resolve the master task's cross-project child links for unified acceptance.

    Returns [(project_id, child_store, child_task_id)] for every linked
    child. A link whose project is unreachable or whose task cannot be read
    raises a clear blocker (never silently skipped, never a partial list).
    Duplicates are de-duplicated by (resolved project root, task id).
    """
    master = store.read(ref)
    seen = set()
    result = []
    # The exact store is needed per link; use a throwaway service instance
    # bound to the master store for its resolver.
    probe = CrossProjectService(store)
    for entry in _links(master):
        if entry.get("direction") != "child":
            continue
        project_id = entry.get("project_id", "")
        child_id = entry.get("task_id", "")
        child_store = probe._store_by_identity(project_id, entry.get("path_hint", ""))
        if child_store is None:
            raise DomainError("unified_child_not_ready",
                              "A linked child project is unreachable",
                              {"project_id": project_id, "task_id": child_id,
                               "reason": "child_project_unavailable"}, status=3)
        key = (str(child_store.project_root), child_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            child_store.read(child_id)
        except DomainError as exc:
            raise DomainError("unified_child_not_ready",
                              "A linked child task cannot be read",
                              {"project_id": project_id, "task_id": child_id,
                               "reason": exc.code}, status=3) from exc
        result.append((project_id, child_store, child_id))
    return result


# -- CLI surface -------------------------------------------------------------

def register_commands(subparsers) -> None:
    from .cli import OPTIONAL_HANDLER_ATTR

    cross = subparsers.add_parser("cross")
    cross_sub = cross.add_subparsers(dest="cross_command", required=True)
    cross.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_cross_usage})
    create_child = cross_sub.add_parser("create-child")
    _add_target(create_child)
    create_child.add_argument("--target", required=True,
                              help="target project path or registered project id")
    create_child.add_argument("--name", required=True)
    create_child.add_argument("--title", required=True)
    create_child.add_argument("--description", default="")
    create_child.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_create_child})
    link = cross_sub.add_parser("link")
    _add_target(link)
    link.add_argument("--target", required=True)
    link.add_argument("--target-task", required=True)
    link.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_link})
    links = cross_sub.add_parser("links")
    _add_target(links)
    links.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_links})
    dispatch = cross_sub.add_parser("dispatch")
    _add_target(dispatch)
    dispatch.add_argument("--target", required=True)
    dispatch.add_argument("--target-task", required=True)
    dispatch.add_argument("--role", required=True)
    dispatch.add_argument("--plan-item", action="append", default=[])
    dispatch.add_argument("--allowed-path", action="append", required=True)
    dispatch.add_argument("--validation", action="append", default=[])
    dispatch.add_argument("--coordinator", default="coordinator")
    dispatch.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_dispatch})


def _handle_cross_usage(args):
    raise DomainError("cross_command_required",
                      "Choose a cross-project command: create-child|link|links|dispatch", status=2)


def _add_target(parser):
    parser.add_argument("task", nargs="?")


def _service(args):
    from .cli import _actor, _resolve_ref, _service as core_service
    service = core_service(args)
    store = service.store
    ref = _resolve_ref(args, store) if hasattr(args, "task") else None
    cross = CrossProjectService(store, task_service=service)
    return cross, _actor(args), ref


def _handle_create_child(args):
    cross, actor, ref = _service(args)
    return cross.create_child(ref, target=args.target, name=args.name,
                              title=args.title, description=args.description, actor=actor)


def _handle_link(args):
    cross, actor, ref = _service(args)
    return cross.link_existing(ref, target=args.target, target_task=args.target_task, actor=actor)


def _handle_links(args):
    cross, actor, ref = _service(args)
    return cross.links(ref)


def _handle_dispatch(args):
    cross, actor, ref = _service(args)
    return cross.dispatch(ref, target=args.target, target_task=args.target_task,
                          role=args.role, plan_item_ids=args.plan_item,
                          allowed_paths=args.allowed_path,
                          required_validations=args.validation,
                          coordinator_id=args.coordinator, actor=actor)
