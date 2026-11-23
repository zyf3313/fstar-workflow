from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Iterator, Optional
from uuid import UUID

from .models import DomainError, validate_task

SCHEMA_VERSION = "1"
POINTER_SCHEMA = "fstar.pointer.v1"
POINTER_FILE = ".fstar-pointer.json"
STORAGE_MODES = ("project-shared", "project-local", "user-directory")


def canonical_json(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(data: object) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _initialized_at(candidate: Path) -> bool:
    marker = candidate / ".fstar" / ".schema-version"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == SCHEMA_VERSION:
        return True
    pointer = candidate / POINTER_FILE
    if pointer.is_file() and not pointer.is_symlink():
        record = _read_pointer(pointer)
        if _pointer_path_matches(candidate, record):
            marker = _safe_pointer_data_root(candidate, record) / ".schema-version"
            return marker.is_file() and marker.read_text(encoding="utf-8").strip() == SCHEMA_VERSION
    return False


def find_project_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        if _initialized_at(candidate):
            return candidate
        # A linked worktree shares the main tree's initialized data root.
        main_root = _linked_worktree_main_root(candidate)
        if main_root is not None:
            pointer = candidate / POINTER_FILE
            # A worktree's own unusable pointer must not silently switch it
            # to the main project, or to an initialized ancestor.
            if pointer.is_file() or pointer.is_symlink():
                return None
            if _initialized_at(main_root):
                return main_root
    return None


def _linked_worktree_main_root(candidate: Path) -> Optional[Path]:
    """Main worktree root for a linked git worktree, or None.

    A linked worktree carries a ``.git`` FILE whose content is
    ``gitdir: <main>/.git/worktrees/<name>``; that gitdir holds a
    ``commondir`` file naming the main gitdir (usually relative, e.g.
    ``../..``). The main worktree root is the parent of the realpath-
    normalized main gitdir. Any read or format failure returns None so
    callers keep their current resolution unchanged; a normal ``.git``
    directory never matches (only the FILE form is inspected).
    """
    git_file = candidate / ".git"
    if not git_file.is_file():
        return None
    try:
        text = git_file.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            return None
        worktree_gitdir = Path(text[len("gitdir:"):].strip())
        if not worktree_gitdir.is_absolute():
            worktree_gitdir = candidate / worktree_gitdir
        worktree_gitdir = Path(os.path.realpath(str(worktree_gitdir)))
        commondir = Path((worktree_gitdir / "commondir")
                         .read_text(encoding="utf-8").strip())
        if not str(commondir):
            return None
        if not commondir.is_absolute():
            commondir = worktree_gitdir / commondir
        main_gitdir = Path(os.path.realpath(str(commondir)))
        if not main_gitdir.is_dir():
            return None
        main_root = main_gitdir.parent
        if main_root == candidate:
            # Not a linked worktree relative to a distinct main tree.
            return None
        return main_root
    except (OSError, ValueError):
        return None


def worktree_shared_main_root(start: Path) -> Optional[Path]:
    """Main worktree root when ``start`` sits inside a linked worktree.

    Walks upward to the nearest linked-worktree ``.git`` file and resolves
    its main worktree root; None when ``start`` is not inside a linked
    worktree. Pure resolution helper for reporting surfaces (doctor); it
    never reads or writes any fstar data.
    """
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        main_root = _linked_worktree_main_root(candidate)
        if main_root is not None:
            return main_root
    return None


def _pointer_path_matches(project_root: Path, record: dict) -> bool:
    """A pointer only resolves at the path it was bound to.

    A moved project requires an explicit rebind; the pointer never silently
    follows the repo to a new location. ``bound_path`` is the recorded
    project root at init/rebind time.
    """
    bound = record.get("bound_path")
    if not isinstance(bound, str) or not bound:
        return True
    # Compare resolved paths: a project root reached through a symlinked
    # parent (e.g. macOS /tmp) must still match its recorded binding.
    return Path(bound).resolve(strict=False) == Path(project_root).resolve(strict=False)


def _read_pointer(path: Path) -> Optional[dict]:
    """Read a pointer file; a corrupt pointer is reported, never followed."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            record = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("corrupt_pointer", "Project pointer file is corrupt; repair or remove it",
                          {"path": str(path), "reason": str(exc)})
    if not isinstance(record, dict) or record.get("schema") != POINTER_SCHEMA \
            or not isinstance(record.get("project_id"), str) \
            or not isinstance(record.get("data_root"), str):
        raise DomainError("corrupt_pointer", "Project pointer file is invalid",
                          {"path": str(path)})
    try:
        UUID(record["project_id"])
    except ValueError:
        raise DomainError("corrupt_pointer", "Project pointer id is not a UUID", {"path": str(path)})
    data_root = record["data_root"]
    if not data_root:
        raise DomainError("corrupt_pointer", "Pointer data_root must be a non-empty path",
                          {"path": str(path)})
    if Path(data_root).is_absolute():
        record = dict(record, data_root_abs=data_root)
    elif ".." in Path(data_root).parts:
        raise DomainError("corrupt_pointer", "Relative pointer data_root may not traverse upward",
                          {"path": str(path), "data_root": data_root})
    if record.get("mode") is not None and record["mode"] not in STORAGE_MODES:
        raise DomainError("corrupt_pointer", "Pointer declares an unknown storage mode",
                          {"path": str(path), "mode": record.get("mode")})
    return record


def _safe_pointer_data_root(project_root: Path, record: dict) -> Path:
    """Resolve the pointer's data root, refusing aliases and escapes."""
    relative = record["data_root"]
    if record.get("data_root_abs") is not None:
        absolute = Path(record["data_root_abs"])
        # A symlinked absolute data root is an alias, not a location: the
        # relative branch rejects it below, so the absolute branch must too.
        if absolute.is_symlink():
            raise DomainError("corrupt_pointer", "Pointer data_root may not be a symbolic link",
                              {"path": str(project_root / POINTER_FILE), "data_root": str(absolute)})
        resolved = absolute.resolve(strict=False)
        if not resolved.is_absolute():
            raise DomainError("corrupt_pointer", "Pointer data_root_abs must be absolute",
                              {"path": str(project_root / POINTER_FILE)})
        return resolved
    if ".." in Path(relative).parts or Path(relative).is_absolute():
        raise DomainError("corrupt_pointer", "Pointer data_root escapes the project",
                          {"path": str(project_root / POINTER_FILE), "data_root": relative})
    candidate = project_root.joinpath(*Path(relative).parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        raise DomainError("corrupt_pointer", "Pointer data_root escapes the project",
                          {"path": str(project_root / POINTER_FILE), "data_root": relative})
    if candidate.is_symlink():
        raise DomainError("corrupt_pointer", "Pointer data_root may not be a symbolic link",
                          {"path": str(candidate)})
    return resolved


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlinks(path: Path, stop: Path) -> None:
    current = path
    while _inside(current, stop):
        if current.is_symlink():
            raise DomainError("unsafe_path", "Symbolic links are not allowed in task storage", {"path": str(current)})
        if current == stop:
            break
        current = current.parent


def _pointer_data_root_payload(data_root: Path, project_root: Path) -> str:
    """Pointer data_root payload: relative when inside the project, else absolute."""
    relative = os.path.relpath(data_root.resolve(), project_root.resolve()).replace(os.sep, "/")
    if relative.startswith(".."):
        return str(data_root.resolve())
    return relative


def _resolve_data_root(project_root: Path) -> Path:
    """The data root for this project; project-local for every mode."""
    return _resolve_project_layout(project_root)[0]


REBIND_PENDING = object()


STORAGE_MARKER_FILE = "storage-mode"


def _config_project_id(data_root: Path) -> Optional[str]:
    """Project UUID declared by the project's own config.yaml, if any."""
    config = data_root / "config.yaml"
    if not config.is_file():
        return None
    try:
        from .config import parse_config
        values = parse_config(config.read_text(encoding="utf-8"), config)
        project = values.get("project")
        if isinstance(project, dict) and isinstance(project.get("id"), str):
            return project["id"]
    except Exception:
        return None
    return None


def _storage_identity(project_root: Path, data_root: Path) -> tuple:
    """(storage_mode, project_id) for a resolved data root; legacy defaults."""
    pointer = project_root / POINTER_FILE
    if pointer.is_file() and not pointer.is_symlink():
        record = _read_pointer(pointer)
        mode = record.get("mode") or "user-directory"
        return mode, record["project_id"]
    marker = data_root / STORAGE_MARKER_FILE
    if marker.is_file() and not marker.is_symlink():
        try:
            mode = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            mode = ""
        if mode in STORAGE_MODES:
            return mode, _config_project_id(data_root)
    config = data_root / "config.yaml"
    project_id = None
    if config.is_file():
        try:
            from .config import parse_config
            values = parse_config(config.read_text(encoding="utf-8"), config)
            project = values.get("project")
            if isinstance(project, dict) and isinstance(project.get("id"), str):
                project_id = project["id"]
        except Exception:
            project_id = None
    return "project-shared", project_id


def _resolve_project_layout(project_root: Path, *, _tolerate_mismatch: bool = False) -> tuple:
    """Resolve (data_root, storage_mode, project_id) for one project root.

    Resolution order, matching find_project_root: an in-repo schema marker
    first (legacy and project-shared/local), then a pointer file (user-directory).
    Symlinked or escaping pointer data roots are refused, not followed.
    """
    project_root = project_root.resolve()
    marker = project_root / ".fstar" / ".schema-version"
    if marker.is_file():
        mode, project_id = _storage_identity(project_root, project_root / ".fstar")
        return project_root / ".fstar", mode, project_id, False
    pointer = project_root / POINTER_FILE
    if pointer.is_file() and not pointer.is_symlink():
        record = _read_pointer(pointer)
        matches = _pointer_path_matches(project_root, record)
        if not matches and not _tolerate_mismatch:
            raise DomainError("project_moved_needs_rebind",
                              "This project was initialized at another path; run the rebind "
                              "command to bind it to the current path",
                              {"project_root": str(project_root),
                               "bound_path": record.get("bound_path"),
                               "project_id": record.get("project_id")})
        anchor = Path(record["bound_path"]) if (record.get("bound_path") and not matches) else project_root
        data_root = _safe_pointer_data_root(anchor, record)
        mode = record.get("mode") or "user-directory"
        return data_root, mode, record["project_id"], not matches
    # Uninitialized: default legacy layout so errors and init previews read naturally.
    return project_root / ".fstar", "project-shared", None, False


def _registry_path(user_home: Path) -> Path:
    return user_home / "projects.json"


def _read_registry(registry: Path) -> dict:
    if not registry.is_file():
        return {"schema": "fstar.projects.v1", "projects": {}}
    if registry.is_symlink():
        raise DomainError("corrupt_registry", "Project registry may not be a symbolic link",
                          {"path": str(registry)})
    try:
        with registry.open("r", encoding="utf-8") as stream:
            record = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError("corrupt_registry", "Project registry is corrupt",
                          {"path": str(registry), "reason": str(exc)})
    if not isinstance(record, dict) or record.get("schema") != "fstar.projects.v1" \
            or not isinstance(record.get("projects"), dict):
        raise DomainError("corrupt_registry", "Project registry is invalid", {"path": str(registry)})
    return record


def _slugify(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in name.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return (cleaned or "project")[:40]


def register_user_directory_project(*, user_home: Path, project_id: str, name: str,
                                    data_root: Path, project_path: Path,
                                    confirmation: Optional[dict] = None,
                                    explicit: bool = True) -> dict:
    """Register a user-directory project under the user-level registry.

    Idempotent for the same id+path; refuses a colliding id bound to a
    different path instead of merging. A corrupted registry is an error, so
    one bad file can never silently orphan every project.
    """
    del confirmation  # registration is machine bookkeeping; init owns user intent
    registry = _registry_path(Path(user_home))
    if registry.exists() and registry.is_symlink():
        raise DomainError("corrupt_registry", "Project registry may not be a symbolic link",
                          {"path": str(registry)})
    registry.parent.mkdir(parents=True, exist_ok=True)
    record = _read_registry(registry)
    projects = dict(record.get("projects", {}))
    existing = projects.get(project_id)
    entry = {"path": str(project_path), "name": name, "data_root": str(data_root),
             "storage_mode": "user-directory"}
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("path") != str(project_path):
            raise DomainError("project_id_conflict",
                              "This project id is already bound to another path; "
                              "rebind explicitly instead of re-registering",
                              {"project_id": project_id,
                               "registered_path": existing.get("path") if isinstance(existing, dict) else None,
                               "requested_path": str(project_path)}, status=4)
        return {"project_id": project_id, "data_root": str(data_root), "path": str(project_path),
                "registered": True, "rebound": False}
    projects[project_id] = entry
    payload = {"schema": "fstar.projects.v1", "projects": projects}
    atomic_write_json(registry, payload)
    return {"project_id": project_id, "data_root": str(data_root), "path": str(project_path),
            "registered": True, "rebound": False}


def user_directory_root(user_home: Path, project_id: str, name: str) -> Path:
    """Per-project data folder under the user root: ``projects/<uuid>-<name>``.

    The stable UUID disambiguates same-name projects; the readable name is
    only decoration and never participates in identity.
    """
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", project_id):
        raise DomainError("invalid_project_id", "Project id must be a UUID", {"project_id": project_id})
    return Path(user_home).resolve() / "projects" / ("%s-%s" % (project_id, _slugify(name)))


def find_rebind_source(start: Path) -> Optional[Path]:
    """Find a project root that can be rebound, starting at ``start``.

    Unlike :func:`find_project_root` this also accepts a pointer file whose
    ``bound_path`` no longer matches the current location, which is exactly
    the state of a project whose directory was moved: the pointer travelled
    with the repository but the recorded binding did not.
    """
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        pointer = candidate / POINTER_FILE
        if pointer.is_file() and not pointer.is_symlink():
            return candidate
        marker = candidate / ".fstar" / ".schema-version"
        if marker.is_file():
            return candidate
    return None


def rebind_registered(*, user_home: Path, source_path: Path, target_path: Path,
                      confirmation: Optional[dict] = None) -> dict:
    """Rebind a user-directory project identified by its registered path.

    Used when the recorded project root no longer carries a pointer (the
    repository was moved or the pointer was lost): the user-level registry
    still names the project, so the binding can be re-established explicitly.
    Only an exact path match selects the project; nothing is merged by name
    or by remote URL.
    """
    del confirmation  # rebinding is an explicit command; the command is the consent
    target = Path(target_path).expanduser().resolve()
    source = Path(source_path).expanduser().resolve()
    if not target.is_dir():
        raise DomainError("rebind_target_invalid", "Rebind target must be an existing directory",
                          {"path": str(target)})
    registry = _registry_path(Path(user_home))
    record = _read_registry(registry)
    matches = [pid for pid, entry in sorted(record.get("projects", {}).items())
               if isinstance(entry, dict) and isinstance(entry.get("path"), str)
               and Path(entry["path"]).resolve(strict=False) == source]
    if not matches:
        raise DomainError("rebind_project_unregistered",
                          "No user-directory project is registered for this path",
                          {"path": str(source)})
    if len(matches) > 1:
        raise DomainError("rebind_ambiguous_project",
                          "Several projects are registered for this path; pass --project explicitly",
                          {"path": str(source), "project_ids": matches})
    project_id = matches[0]
    entry = dict(record["projects"][project_id])
    data_root = Path(entry.get("data_root", "")).expanduser()
    marker = data_root / ".schema-version"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != SCHEMA_VERSION:
        raise DomainError("rebind_data_root_missing",
                          "The registered data root is missing or unreadable",
                          {"project_id": project_id, "data_root": str(data_root)})
    pointer_record = {"schema": POINTER_SCHEMA, "project_id": project_id,
                      "data_root": _pointer_data_root_payload(data_root, target),
                      "bound_path": str(target),
                      "mode": "user-directory"}
    entry["path"] = str(target)
    entry["rebound_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    projects = dict(record.get("projects", {}))
    projects[project_id] = entry
    atomic_write_json(registry, {"schema": "fstar.projects.v1", "projects": projects})
    new_pointer = target / POINTER_FILE
    _reject_symlinks(new_pointer.parent, target)
    atomic_write_json(new_pointer, pointer_record)
    return {"rebound": True, "project_root": str(target), "project_id": project_id,
            "data_root": str(data_root)}


def locate_project(start: Path, user_home: Optional[Path] = None) -> dict:
    """Resolve a project by pointer or registry from any starting path.

    Returns {found, project_root, data_root, storage_mode, project_id,
    via}. Pointer resolution requires the data root to exist and match
    schema 1; registry entries whose recorded path no longer exists are
    reported as missing, never auto-rebound.
    """
    start = Path(start).resolve()
    if start.is_file():
        start = start.parent
    user = (user_home or (Path.home() / ".fstar")).resolve()
    for candidate in (start,) + tuple(start.parents):
        pointer = candidate / POINTER_FILE
        if pointer.is_file() and not pointer.is_symlink():
            record = _read_pointer(pointer)
            data_root = _safe_pointer_data_root(candidate, record)
            marker = data_root / ".schema-version"
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == SCHEMA_VERSION:
                return {"found": True, "project_root": candidate, "data_root": data_root,
                        "storage_mode": record.get("mode") or "user-directory",
                        "project_id": record["project_id"], "via": "pointer"}
    registry = _read_registry(_registry_path(user))
    for project_id, entry in sorted(registry.get("projects", {}).items()):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        data_root = entry.get("data_root")
        if not isinstance(path, str) or not isinstance(data_root, str):
            continue
        if not Path(path).is_dir():
            continue
        marker = Path(data_root) / ".schema-version"
        if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != SCHEMA_VERSION:
            continue
        return {"found": True, "project_root": Path(path), "data_root": Path(data_root),
                "storage_mode": entry.get("storage_mode") or "user-directory",
                "project_id": project_id, "via": "registry"}
    return {"found": False, "project_root": None, "data_root": None,
            "storage_mode": None, "project_id": None, "via": None}


class TaskStore:
    def __init__(self, project_root: Path, *, user_home: Optional[Path] = None, runtime_root: Optional[Path] = None, lock_timeout: float = 5.0):
        self.project_root = project_root.resolve()
        self.user_home = (user_home or (Path.home() / ".fstar")).resolve()
        self.runtime_root = (runtime_root or (self.user_home / "runtime")).resolve()
        layout = _resolve_project_layout(self.project_root, _tolerate_mismatch=True)
        self.fstar_root, self.storage_mode, self.project_id = layout[0], layout[1], layout[2]
        self.moved_needs_rebind = len(layout) > 3 and bool(layout[3])
        self.storage_mode, self.project_id = _storage_identity(self.project_root, self.fstar_root)
        self.tasks_root = self.fstar_root / "tasks"
        self.archive_root = self.fstar_root / "archive"
        # In user-directory mode the runtime slot is keyed by the stable
        # project id, so a moved project keeps its session pointers and its
        # lock after an explicit rebind. Other modes keep the path-derived
        # key: their data root travels with the repository, and a copy of a
        # repository must not share a session slot with the original.
        if self.storage_mode == "user-directory" and self.project_id:
            project_key = "id-" + hashlib.sha256(self.project_id.encode()).hexdigest()
        else:
            project_key = hashlib.sha256(str(self.project_root).encode()).hexdigest()
        self.project_runtime = self.runtime_root / "projects" / project_key
        self.lock_path = self.project_runtime / "project.lock"
        self.lock_timeout = lock_timeout

    def worktree_shared_from(self) -> Optional[Path]:
        """Main worktree root when this project root is a linked worktree.

        Pure resolution for reporting surfaces (doctor): shares nothing,
        writes nothing; None when not inside a linked worktree.
        """
        return worktree_shared_main_root(self.project_root)

    def project_file(self, relative: str) -> Path:
        """Resolve a project-relative artifact path to a real file.

        Paths that start with the legacy ``.fstar/`` prefix address the
        project's own data (specs, task docs); everything else addresses the
        repository. In user-directory mode the data root lives outside the
        repository, so the prefix decides the root instead of the layout.
        """
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise DomainError("unsafe_evidence_path", "Evidence path must be project-relative",
                              {"path": relative})
        if candidate.parts and candidate.parts[0] == ".fstar":
            root = self.fstar_root
            parts = candidate.parts[1:]
        else:
            root = self.project_root
            parts = candidate.parts
        path = root.joinpath(*parts)
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            raise DomainError("unsafe_evidence_path", "Evidence path escapes the project",
                              {"path": relative})
        if path.is_symlink() or (path.exists() and resolved != path.absolute()):
            raise DomainError("unsafe_evidence_path", "Evidence cannot follow a symbolic link",
                              {"path": relative})
        return path

    def storage_info(self) -> dict:
        """Reportable storage identity for doctor/init surfaces."""
        return {"storage_mode": self.storage_mode, "project_id": self.project_id,
                "data_root": str(self.fstar_root),
                "project_root": str(self.project_root)}

    def identity_path(self, path: Path) -> str:
        """Stable identity string for a path inside this project.

        Data-root paths keep the ``.fstar/`` prefix so an identity is the
        same in every storage mode (the prefix is part of the name, not of
        the location); repository paths stay project-relative. The path
        itself may live outside the repository (user-directory mode).
        """
        resolved = Path(path).resolve(strict=False)
        try:
            return str(Path(".fstar") / resolved.relative_to(self.fstar_root.resolve()))
        except ValueError:
            pass
        try:
            return str(resolved.relative_to(self.project_root.resolve()))
        except ValueError:
            return str(resolved)

    def rebind(self, new_path: Path, *, confirmation: dict) -> dict:
        """Explicitly rebind a user-directory project to a moved path.

        Never moves or merges data: the pointer at the old path is preserved
        (the old path may no longer exist) and a pointer at the new path is
        created atomically; the registry binding is updated under the
        project lock. No auto-merge by name or remote URL ever happens.
        """
        if self.storage_mode != "user-directory":
            raise DomainError("rebind_requires_user_directory",
                              "Only user-directory storage supports rebind",
                              {"storage_mode": self.storage_mode})
        target = Path(new_path).expanduser().resolve()
        old_pointer_record = None
        pointer = self.project_root / POINTER_FILE
        if pointer.is_file() and not pointer.is_symlink():
            old_pointer_record = _read_pointer(pointer)
        if target == self.project_root and (old_pointer_record is None
                                             or _pointer_path_matches(target, old_pointer_record)):
            return {"rebound": False, "project_root": str(target),
                    "project_id": self.project_id, "data_root": str(self.fstar_root),
                    "reason": "unchanged"}
        if not target.is_dir():
            raise DomainError("rebind_target_invalid", "Rebind target must be an existing directory",
                              {"path": str(target)})
        pointer_record = {"schema": POINTER_SCHEMA, "project_id": self.project_id,
                          "data_root": _pointer_data_root_payload(self.fstar_root, target),
                          "bound_path": str(target),
                          "mode": "user-directory"}
        with self.transaction(moved_ok=True):
            registry = _registry_path(self.user_home)
            record = _read_registry(registry)
            existing = record.get("projects", {}).get(self.project_id)
            if existing is None:
                raise DomainError("rebind_project_unregistered",
                                  "This project is not registered for user-directory storage",
                                  {"project_id": self.project_id})
            existing = dict(existing)
            existing["path"] = str(target)
            existing["rebound_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            projects = dict(record.get("projects", {}))
            projects[self.project_id] = existing
            payload = {"schema": "fstar.projects.v1", "projects": projects}
            atomic_write_json(registry, payload)
            # Pointers are written at the OLD path (if it still exists, for the
            # unchanged case) and at the NEW path, both carrying the new
            # binding; the new location is the one that resolves afterwards.
            for location in {self.project_root, target}:
                if not location.is_dir():
                    continue
                new_pointer = location / POINTER_FILE
                _reject_symlinks(new_pointer.parent, location)
                atomic_write_json(new_pointer, pointer_record)
        return {"rebound": True, "project_root": str(target), "project_id": self.project_id,
                "data_root": str(self.fstar_root)}

    def require_project(self, *, moved_ok: bool = False) -> None:
        if getattr(self, "moved_needs_rebind", False) and not moved_ok:
            raise DomainError("project_moved_needs_rebind",
                              "This project was initialized at another path; run the rebind "
                              "command to bind it to the current path",
                              {"project_root": str(self.project_root), "project_id": self.project_id})
        marker = self.fstar_root / ".schema-version"
        if not marker.is_file():
            raise DomainError("project_not_initialized", "No initialized fstar project found", {"project": str(self.project_root)})
        if marker.read_text(encoding="utf-8").strip() != SCHEMA_VERSION:
            raise DomainError("unsupported_schema", "Unsupported fstar schema version", {"path": str(marker)})

    @contextlib.contextmanager
    def transaction(self, *, moved_ok: bool = False) -> Iterator[None]:
        self.require_project(moved_ok=moved_ok)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as stream:
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DomainError("lock_timeout", "Timed out waiting for the project lock", status=4)
                    time.sleep(0.02)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _roots(self, archived: bool) -> tuple:
        if archived:
            if not self.archive_root.exists():
                return tuple()
            return tuple(p for month in self.archive_root.iterdir() if month.is_dir() and not month.is_symlink() for p in month.rglob("task.json"))
        if not self.tasks_root.exists():
            return tuple()
        return tuple(self.tasks_root.rglob("task.json"))

    def resolve(self, task_ref: str, *, archived: bool = False) -> Path:
        self.require_project()
        if not task_ref or Path(task_ref).is_absolute() or ".." in Path(task_ref).parts:
            raise DomainError("invalid_task_ref", "Task reference must be a safe relative path or UUID", {"task": task_ref})
        candidates = []
        roots = self._roots(archived)
        for task_file in roots:
            task_dir = task_file.parent
            _reject_symlinks(task_dir, self.fstar_root)
            try:
                data = self._read_path(task_file)
            except DomainError:
                raise
            relative = str(task_dir.relative_to(self.archive_root if archived else self.tasks_root))
            if task_ref in {data.get("id"), data.get("name"), relative}:
                candidates.append(task_dir)
        if not candidates:
            raise DomainError("task_not_found", "Task was not found", {"task": task_ref, "archived": archived})
        if len(candidates) > 1:
            raise DomainError("ambiguous_task", "Task reference is ambiguous", {"task": task_ref, "candidates": [str(x) for x in candidates]})
        return candidates[0]

    def _read_path(self, path: Path) -> dict:
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise DomainError("corrupt_task", "Cannot read task.json; repair the file before continuing", {"path": str(path), "reason": str(exc)})
        validate_task(data)
        return data

    def read(self, task_ref: str, *, archived: bool = False) -> dict:
        return self._read_path(self.resolve(task_ref, archived=archived) / "task.json")

    def write(self, task_dir: Path, data: dict, *, expected_hash: Optional[str] = None) -> None:
        validate_task(data)
        resolved_parent = task_dir.parent.resolve()
        if not _inside(resolved_parent, self.fstar_root.resolve()):
            raise DomainError("unsafe_path", "Task path escapes project storage")
        _reject_symlinks(task_dir, self.fstar_root)
        path = task_dir / "task.json"
        if expected_hash is not None and path.exists():
            current = self._read_path(path)
            if content_hash(current) != expected_hash:
                raise DomainError("write_conflict", "Task changed since it was read", status=4)
        atomic_write_json(path, data)

    def scan(self, *, archived: bool = False) -> list:
        self.require_project()
        result = []
        for task_file in self._roots(archived):
            data = self._read_path(task_file)
            data = dict(data)
            data["_path"] = str(task_file.parent)
            result.append(data)
        return result

    def session_path(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode()).hexdigest()
        return self.project_runtime / "sessions" / (digest + ".json")

    def set_current(self, session_id: str, task_dir: Path, task_id: str) -> None:
        if not session_id:
            return
        atomic_write_json(self.session_path(session_id), {"project": str(self.project_root), "task_id": task_id, "task_path": str(task_dir)})

    def current(self, session_id: Optional[str]) -> Optional[dict]:
        if not session_id:
            return None
        path = self.session_path(session_id)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise DomainError("corrupt_current", "Current-task pointer is corrupt", {"path": str(path), "reason": str(exc)})

    def clear_tree_pointers(self, task_ids: set) -> None:
        sessions = self.project_runtime / "sessions"
        if not sessions.exists():
            return
        for path in sessions.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as stream:
                    data = json.load(stream)
                if data.get("task_id") in task_ids:
                    path.unlink()
            except (OSError, json.JSONDecodeError):
                continue
