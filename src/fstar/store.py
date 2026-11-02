from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Iterator, Optional

from .models import DomainError, validate_task

SCHEMA_VERSION = "1"


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


def find_project_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current,) + tuple(current.parents):
        marker = candidate / ".fstar" / ".schema-version"
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == SCHEMA_VERSION:
            return candidate
    return None


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


class TaskStore:
    def __init__(self, project_root: Path, *, user_home: Optional[Path] = None, runtime_root: Optional[Path] = None, lock_timeout: float = 5.0):
        self.project_root = project_root.resolve()
        self.user_home = (user_home or (Path.home() / ".fstar")).resolve()
        self.runtime_root = (runtime_root or (self.user_home / "runtime")).resolve()
        self.fstar_root = self.project_root / ".fstar"
        self.tasks_root = self.fstar_root / "tasks"
        self.archive_root = self.fstar_root / "archive"
        project_key = hashlib.sha256(str(self.project_root).encode()).hexdigest()
        self.project_runtime = self.runtime_root / "projects" / project_key
        self.lock_path = self.project_runtime / "project.lock"
        self.lock_timeout = lock_timeout

    def require_project(self) -> None:
        marker = self.fstar_root / ".schema-version"
        if not marker.is_file():
            raise DomainError("project_not_initialized", "No initialized fstar project found", {"project": str(self.project_root)})
        if marker.read_text(encoding="utf-8").strip() != SCHEMA_VERSION:
            raise DomainError("unsupported_schema", "Unsupported fstar schema version", {"path": str(marker)})

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        self.require_project()
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
