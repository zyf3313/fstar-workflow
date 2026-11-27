from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence, Tuple

from .config import ConfigError, parse_config


@dataclass(frozen=True)
class TopicReference:
    id: str
    title: str
    applies_to: str
    read_when: str
    path: str


@dataclass(frozen=True)
class DocumentReference:
    title: str
    path: str


@dataclass(frozen=True)
class ProjectContext:
    project_summary: str
    topics: Sequence[TopicReference] = ()
    authority_refs: Sequence[DocumentReference] = ()
    knowledge_refs: Sequence[DocumentReference] = ()


@dataclass(frozen=True)
class InitWarning:
    code: str
    path: Path
    message: str


@dataclass(frozen=True)
class InitResult:
    root: Path
    created: Tuple[Path, ...]
    preserved: Tuple[Path, ...]
    warnings: Tuple[InitWarning, ...]
    context_complete: bool
    dry_run: bool
    force_separate: bool = False


class InitError(Exception):
    def __init__(self, code: str, message: str, *, path: Path,
                 created: Sequence[Path] = ()) -> None:
        super().__init__(message)
        self.code, self.path, self.message, self.created = code, path, message, tuple(created)

    def as_dict(self):
        return {"error": {"code": self.code, "message": self.message,
                          "details": {"path": str(self.path),
                                      "created": [str(value) for value in self.created]}}}


_PROJECT_IGNORE = "/runtime/\n/*.local.yaml\n/.identity\n/identity\n"
_USER_IGNORE = "/runtime/\n/config.local.yaml\n/.identity\n/identity\n"
STORAGE_MODES = ("project-shared", "project-local", "user-directory")
GIT_EXCLUDE_LINE = "/.fstar/\n"
STORAGE_MARKER_FILE = "storage-mode"
_LOCAL_GITIGNORE_WARNING = ("LOCAL_GITIGNORE_READONLY",
                            "A shared .gitignore already ignores .fstar locally; "
                            "its ignored=true line cannot be rewritten by fstar. "
                            "Remove the local ignore to let the git exclude file handle it.")


def _controlled(root: Path, relative: str) -> Path:
    value = root / relative
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InitError("SYMLINK_NOT_ALLOWED", "Controlled paths may not be symbolic links", path=cursor)
    return value


def _reference(root: Path, raw: str) -> str:
    if "\x00" in raw:
        raise InitError("INVALID_REFERENCE", "Reference contains NUL", path=root)
    file_part, separator, fragment = raw.partition("#")
    pure = PurePosixPath(file_part)
    if pure.is_absolute() or ".." in pure.parts or not file_part:
        raise InitError("INVALID_REFERENCE", "Reference must stay within the project", path=root / file_part)
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InitError("REFERENCE_MISSING", "Referenced file is unavailable: %s" % exc, path=candidate)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise InitError("REFERENCE_OUTSIDE_PROJECT", "Reference resolves outside project", path=candidate)
    if not resolved.is_file():
        raise InitError("REFERENCE_NOT_FILE", "Reference must name a file", path=candidate)
    return file_part + (("#" + fragment) if separator else "")


def _project_index(root: Path, context: Optional[ProjectContext]) -> Tuple[str, bool]:
    if context is None or not context.project_summary.strip():
        return ("# 项目索引\n\n## 概况\n\n待补：项目目标、结构与已有权威资料。\n\n"
                "## 导航\n\n待补：适用主题与长期知识入口。\n"), False
    lines = ["# 项目索引", "", "## 概况", "", context.project_summary.strip(), "",
             "已有权威文档优先于 fstar 派生规范。", ""]
    if context.authority_refs:
        lines.extend(["## 已有权威文档", ""])
        for ref in context.authority_refs:
            lines.append("- [%s](%s)" % (ref.title, _reference(root, ref.path)))
        lines.append("")
    if context.topics:
        lines.extend(["## 主题", ""])
        for topic in context.topics:
            lines.extend(["### %s — %s" % (topic.id, topic.title),
                          "- Applies to: %s" % topic.applies_to,
                          "- Read when: %s" % topic.read_when,
                          "- Authority: [%s](%s)" % (topic.path, _reference(root, topic.path)), ""])
    if context.knowledge_refs:
        lines.extend(["## 长期知识", ""])
        for ref in context.knowledge_refs:
            lines.append("- [%s](%s)" % (ref.title, _reference(root, ref.path)))
        lines.append("")
    complete = bool(context.topics or context.authority_refs or context.knowledge_refs)
    if not complete:
        lines.extend(["## 导航", "", "待补：主题与知识导航。", ""])
    return "\n".join(lines), complete


def _user_index(root: Path) -> str:
    entries = []
    for label, relative, explanation in (
        ("Rules", "rules", "规则含 strength；仅在目录存在时链接。"),
        ("Memory", "memory", "记忆含 kind/trust；仅在目录存在时链接。"),
        ("Local customization", "templates", "本地模板与工作流定制入口。"),
    ):
        if (root / relative).exists():
            entries.append("- [%s](%s/) — %s" % (label, relative, explanation))
        else:
            entries.append("- %s（尚未创建）— %s" % (label, explanation))
    return "# fstar 用户索引\n\n" + "\n".join(entries) + "\n"


def _read_text(path: Path, code: str, message: str, *, created: Sequence[Path] = ()) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InitError(code, "%s: %s" % (message, exc), path=path, created=created)


def _check_existing_project(root: Path, data_subdir: str = ".fstar") -> None:
    marker = root / data_subdir / ".schema-version"
    config = root / data_subdir / "config.yaml"
    marker_value = None
    if marker.exists():
        if not marker.is_file():
            raise InitError("PATH_CONFLICT", "Schema marker is not a file", path=marker)
        marker_value = _read_text(marker, "SCHEMA_READ_ERROR", "Cannot read schema marker").strip()
        if marker_value != "1":
            raise InitError("INCOMPATIBLE_SCHEMA", "Only schema version 1 is supported", path=marker)
    if config.exists():
        if not config.is_file():
            raise InitError("PATH_CONFLICT", "Configuration is not a file", path=config)
        try:
            values = parse_config(_read_text(config, "INVALID_CONFIG", "Cannot read existing config"), config)
        except ConfigError as exc:
            raise InitError("INVALID_CONFIG", str(exc), path=config)
        schema = values.get("schema_version")
        if isinstance(schema, bool) or schema != 1:
            raise InitError("INCOMPATIBLE_SCHEMA", "Existing config must explicitly use schema version 1", path=config)
        project = values.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("id"), str):
            raise InitError("PROJECT_ID_MISSING", "Existing project config must preserve project.id", path=config)
        try:
            uuid.UUID(project["id"])
        except ValueError:
            raise InitError("PROJECT_ID_INVALID", "Existing project.id is not a UUID", path=config)
        if marker_value is not None and marker_value != str(schema):
            raise InitError("SCHEMA_MISMATCH", "Schema marker and config disagree", path=marker)


def _check_existing_user(root: Path) -> None:
    config = root / "config.yaml"
    if not config.exists():
        return
    if config.is_symlink() or not config.is_file():
        raise InitError("PATH_CONFLICT", "Configuration is not a regular file", path=config)
    try:
        values = parse_config(_read_text(config, "INVALID_CONFIG", "Cannot read existing config"), config)
    except ConfigError as exc:
        raise InitError("INVALID_CONFIG", str(exc), path=config)
    schema = values.get("schema_version")
    if isinstance(schema, bool) or schema != 1:
        raise InitError("INCOMPATIBLE_SCHEMA", "Existing config must explicitly use schema version 1", path=config)


def _exclusive_write(path: Path, content: str, created: list, preserved: list) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o644)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise InitError("PATH_CONFLICT", "Target is not a regular file", path=path, created=created)
        preserved.append(path)
        return
    try:
        data = content.encode("utf-8")
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)
        created.append(path)


def _backfill_index(path: Path, content: str, *, dry_run: bool) -> bool:
    """Replace only the exact generated skeleton, preserving edited indexes."""
    placeholder, _ = _project_index(path.parent.parent, None)
    if path.is_symlink() or _read_text(path, "IO_ERROR", "Cannot read existing index") != placeholder:
        return False
    if dry_run:
        return True
    temporary = None
    mode = stat.S_IMODE(path.stat().st_mode)
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        # Recheck after staging so an edit made during preparation is preserved.
        if path.is_symlink() or _read_text(path, "IO_ERROR", "Cannot read existing index") != placeholder:
            return False
        os.replace(temporary, path)
    except OSError as exc:
        raise InitError("IO_ERROR", str(exc), path=path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _initialize(root: Path, files, *, dry_run: bool, context_complete: bool,
                project: bool, index_context: bool = False, data_subdir: str = ".fstar") -> InitResult:
    created, preserved, warnings = [], [], []
    directory = root / data_subdir if project else root
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise InitError("PATH_CONFLICT", "Data root is not a safe directory", path=directory)
    if project:
        _check_existing_project(root, data_subdir)
    else:
        _check_existing_user(root)
    for relative, content in files:
        target = _controlled(directory, relative)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise InitError("PATH_CONFLICT", "Target is not a regular file", path=target, created=created)
            preserved.append(target)
            if relative == ".gitignore":
                existing = _read_text(target, "IO_ERROR", "Cannot read existing ignore file", created=created)
                required = _PROJECT_IGNORE if project else _USER_IGNORE
                missing = [line for line in required.splitlines() if line not in existing.splitlines()]
                if missing:
                    warnings.append(InitWarning("IGNORE_RULES_MISSING", target,
                                                "Existing ignore file is missing: %s" % ", ".join(missing)))
            continue
        created.append(target) if dry_run else None
    if not dry_run:
        if not directory.exists():
            try:
                directory.mkdir(mode=0o755, parents=True)
            except FileExistsError:
                if directory.is_symlink() or not directory.is_dir():
                    raise InitError("PATH_CONFLICT", "Data root is not a safe directory", path=directory, created=created)
            except OSError as exc:
                raise InitError("IO_ERROR", str(exc), path=directory, created=created)
        if directory.is_symlink() or not directory.is_dir():
            raise InitError("PATH_CONFLICT", "Data root is not a safe directory", path=directory, created=created)
        created = []
        preserved = []
        for relative, content in files:
            target = _controlled(directory, relative)
            try:
                _exclusive_write(target, content, created, preserved)
            except InitError:
                raise
            except OSError as exc:
                raise InitError("IO_ERROR", str(exc), path=target, created=created)
    if project and not context_complete:
        warnings.append(InitWarning("CONTEXT_REQUIRED", directory / "index.md",
                                    "Project facts and navigation still need completion"))
    if project and (directory / "index.md") in preserved and index_context:
        index = directory / "index.md"
        try:
            backfilled = _backfill_index(index, dict(files)["index.md"], dry_run=dry_run)
        except InitError as exc:
            raise InitError(exc.code, exc.message, path=exc.path, created=created)
        if backfilled:
            preserved.remove(index)
            warnings.append(InitWarning("INDEX_BACKFILLED", index,
                                        "Generated placeholder index %s supplied context" %
                                        ("would be backfilled with" if dry_run else "was backfilled with")))
        else:
            warnings.append(InitWarning("INDEX_PRESERVED", index,
                                        "Existing index was preserved; supplied context was not applied"))
            context_complete = False
    return InitResult(root, tuple(created), tuple(preserved), tuple(warnings), context_complete, dry_run)


def _git_repo_root(root: Path) -> Optional[Path]:
    """Nearest enclosing .git directory or worktree file; None when absent."""
    current = root
    while True:
        candidate = current / ".git"
        if candidate.is_dir():
            return current
        if candidate.is_file():
            return current  # linked worktree: exclude lives in the commondir git dir
        if current.parent == current:
            return None
        current = current.parent


def doctor_worktree_report(invoke_root: Optional[Path],
                           project_root: Optional[Path]) -> Optional[dict]:
    """Report sharing, split pointers, and unreadable worktree identities.

    Read-only: recovery always needs user confirmation. Explicit --project
    overrides supply no invoke_root, preserving their existing behavior.
    """
    if invoke_root is None:
        return None
    from .store import (DomainError, POINTER_FILE, _initialized_at,
                        _pointer_path_matches, _read_pointer, _resolve_data_root, _resolve_project_layout,
                        _safe_pointer_data_root, _shared_worktree_layout, worktree_shared_main_root)
    worktree_root = _git_repo_root(Path(invoke_root).resolve())
    main_root = worktree_shared_main_root(Path(invoke_root))
    if main_root is None or worktree_root is None:
        return None
    shared = {"shared": True, "main_root": str(main_root),
              "message": "当前 worktree 共享自 %s" % main_root}
    report = {"shared": False, "main_root": str(main_root),
              "worktree_root": str(worktree_root), "main_data_root": None,
              "worktree_data_root": None}
    recovery = ("Inspect and preserve both data roots. Pointer removal or data migration "
                "requires user confirmation. Rebinding the intended identity does not merge data. "
                "Doctor does not change files.")
    try:
        main_data_root = _resolve_data_root(main_root)
        report["main_data_root"] = str(main_data_root)
        main_initialized = _initialized_at(main_root)
        pointer = worktree_root / POINTER_FILE
        if pointer.exists() or pointer.is_symlink():
            if pointer.is_symlink():
                raise DomainError("corrupt_pointer", "Worktree pointer is a symbolic link")
            record = _read_pointer(pointer)
            # Use the recorded binding as the anchor, as the layout resolver
            # does for a moved pointer. Never follow an unsafe data root.
            matches = _pointer_path_matches(worktree_root, record)
            anchor = Path(record["bound_path"]) if not matches else worktree_root
            report["worktree_data_root"] = record["data_root"]
            data_root = _safe_pointer_data_root(anchor, record)
            report["worktree_data_root"] = str(data_root)
            main_id = _resolve_project_layout(main_root)[2]
            if data_root != main_data_root or record["project_id"] != main_id:
                report.update(status="split", message=(
                    "Worktree %s has a split project identity: main data root %s; "
                    "worktree recorded data root %s. %s" %
                    (worktree_root, main_data_root, data_root, recovery)))
                return report
            if main_initialized and matches and _initialized_at(worktree_root):
                try:
                    layout = _shared_worktree_layout(worktree_root)
                    if layout is None:
                        report.update(status="conflict", message="Worktree data cannot be safely shared. " + recovery)
                        return report
                except DomainError as exc:
                    if exc.code != "worktree_data_conflict":
                        raise
                    report.update(status="conflict", message="Worktree data cannot be safely shared: %s. %s" % (exc, recovery))
                    return report
                return shared
            report.update(status="pointer_needs_rebind", message=(
                "Worktree %s pointer does not resolve to an initialized project. %s" %
                (worktree_root, recovery)))
            return report
    except (DomainError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        report.update(status="unreadable", message=(
            "Worktree %s project pointer or data root is unreadable: %s. %s" %
            (worktree_root, exc, recovery)))
        return report
    if main_initialized:
        try:
            layout = _shared_worktree_layout(worktree_root)
            if layout is not None:
                return shared
            local_data = _resolve_data_root(worktree_root)
            report.update(status="split", worktree_data_root=str(local_data), message=(
                "Worktree %s has an independent project identity; main data root %s; "
                "worktree data root %s. %s" % (worktree_root, main_data_root, local_data, recovery)))
            return report
        except (DomainError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
            report.update(status="conflict", message="Worktree data cannot be safely shared: %s. %s" % (exc, recovery))
            return report
    if project_root is not None and Path(project_root).resolve(strict=False) == main_root:
        return shared
    if project_root is None and not main_initialized:
        return {"shared": False, "main_root": str(main_root),
                "message": uninitialized_init_hint(main_root)}
    return None


def uninitialized_init_hint(path: Path) -> str:
    """Guidance line for an uninitialized project (worktree or main tree).

    The hint always names ``fstar init``; it is used by reporting surfaces
    only, never to write anything.
    """
    return ("未在 %s 找到已初始化的 fstar 数据根；在主工作树内运行 fstar init 后，"
            "linked worktree 将自动共享该数据根" % path)


def _apply_local_exclude(root: Path, created: list, warnings: list, *, dry_run: bool) -> None:
    """Ignore machine-local fstar files through the LOCAL git exclude file.

    Never the shared .gitignore: rewriting the user's tracked file would be
    a silent out-of-scope write. Non-git projects are reported, not pretended
    ignored. A pre-existing shared .gitignore rule is reported too.
    """
    from .store import DomainError

    repo = _git_repo_root(root)
    if repo is None:
        warnings.append(InitWarning("LOCAL_EXCLUDE_NOT_GIT", root,
                                    "project-local storage uses the local git exclude file, "
                                    "but this project is not a git repository; .fstar is NOT ignored"))
        return
    git_dir = repo / ".git"
    if git_dir.is_file():  # linked worktree pointer: gitdir: <path>
        try:
            text = git_dir.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            warnings.append(InitWarning("LOCAL_EXCLUDE_UNREADABLE", git_dir,
                                        "Cannot read the worktree .git pointer; exclude not verified"))
            return
        target = Path(text.partition("gitdir:")[2].strip()) if "gitdir:" in text else None
        if target is None or not target.is_dir():
            warnings.append(InitWarning("LOCAL_EXCLUDE_UNREADABLE", git_dir,
                                        "The worktree .git pointer does not name a git directory"))
            return
        git_dir = target.resolve()
    shared_ignore = repo / ".gitignore"
    if shared_ignore.is_file():
        try:
            ignored = any(line.strip() in ("/.fstar/", "/.fstar", ".fstar/")
                          for line in shared_ignore.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError):
            ignored = False
        if ignored:
            warnings.append(InitWarning(*_LOCAL_GITIGNORE_WARNING[:1], shared_ignore,
                                        *_LOCAL_GITIGNORE_WARNING[1:]))
            return
    exclude = git_dir / "info" / "exclude"
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    except (OSError, UnicodeError):
        warnings.append(InitWarning("LOCAL_EXCLUDE_UNREADABLE", exclude,
                                    "Cannot read the local git exclude file"))
        return
    # splitlines() strips the newline, so the constant (which carries one)
    # is compared in its stripped form.
    if any(line.strip() in ("/.fstar", ".fstar/", "/.fstar/")
           for line in existing.splitlines()):
        return
    if dry_run:
        created.append(exclude)
        return
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write(separator + "# fstar local storage (machine-local; not shared)\n" + GIT_EXCLUDE_LINE)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise InitError("IO_ERROR", str(exc), path=exclude)
    created.append(exclude)


def _apply_local_pointer_exclude(root: Path, created: list) -> None:
    """Keep the pointer file machine-local (it records an absolute data root).

    The pointer is a locator for one machine's data root, so it is added to
    the LOCAL git exclude file. The shared .gitignore is never touched.
    """
    from .store import POINTER_FILE

    repo = _git_repo_root(root)
    if repo is None:
        return
    git_dir = repo / ".git"
    if git_dir.is_file():
        try:
            text = git_dir.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return
        target = Path(text.partition("gitdir:")[2].strip()) if "gitdir:" in text else None
        if target is None or not target.is_dir():
            return
        git_dir = target.resolve()
    exclude = git_dir / "info" / "exclude"
    line = "/%s\n" % POINTER_FILE
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    except (OSError, UnicodeError):
        return
    if line.strip() in [entry.strip() for entry in existing.splitlines()]:
        return
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write(separator + "# fstar pointer file (machine-local)\n" + line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        return
    created.append(exclude)


def _resolve_storage_mode(mode: Optional[str]) -> str:
    if mode is None:
        return "project-shared"
    if mode not in STORAGE_MODES:
        from .models import DomainError
        raise DomainError("invalid_storage_mode", "Unknown storage mode",
                          {"mode": mode, "modes": list(STORAGE_MODES)})
    return mode


def _layout_conflicts(worktree: Path, main: Path) -> list:
    from .store import _resolve_project_layout
    worktree_layout = _resolve_project_layout(worktree, _tolerate_mismatch=True)
    main_layout = _resolve_project_layout(main, _tolerate_mismatch=True)
    return [worktree_layout[0], main_layout[0]]


@contextlib.contextmanager
def _transition_locks(paths: Sequence[Path], timeout: float) -> Iterator[None]:
    """Non-blocking flock over a deduplicated, path-sorted set of lock files.

    The same physical lock file must never be opened twice in one process
    (flock on a second fd of the same file self-deadlocks to timeout), so
    entries are deduplicated by path string and taken in sorted order, the
    same convention as cross_project_locks. A conflict raises ``lock_timeout``
    instead of blocking indefinitely.
    """
    from .models import DomainError
    ordered = sorted({str(Path(path)) for path in paths})
    streams = []
    try:
        for path in ordered:
            lock_file = Path(path)
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            stream = lock_file.open("a+")
            try:
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise DomainError("lock_timeout",
                                              "Timed out waiting for an identity "
                                              "transition lock (nothing was written)",
                                              {"lock": str(lock_file)}, status=4)
                        time.sleep(0.02)
                streams.append(stream)
            except BaseException:
                stream.close()
                raise
        yield
    finally:
        for stream in reversed(streams):
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()


# Identity-transition lock timeout; matches the TaskStore default so a
# blocked conversion surfaces as lock_timeout like a blocked transaction.
_INIT_LOCK_TIMEOUT = 5.0


def _shared_layout(root: Path, main: Path) -> bool:
    """True when the worktree currently shares the initialized main identity."""
    from .store import _initialized_at, _shared_worktree_layout
    if not _initialized_at(main):
        return False
    try:
        return _shared_worktree_layout(root) is not None
    except (DomainError, OSError, RuntimeError, ValueError):
        return False


def _separate_worktree_lock_paths(worktree: Path, main: Path, user_root: Path,
                                  runtime_root: Optional[Path], mode: str) -> list:
    """Old and new identity lock paths for a separate conversion (A).

    The old lock is the one a TaskStore on the worktree holds today (the
    main identity's runtime slot). The new lock is the runtime slot the
    future separate identity will own: path-keyed for project-shared /
    project-local modes. In user-directory mode the new identity is a fresh
    UUID nobody can hold yet, so no new lock is needed.
    """
    from .store import TaskStore
    old_store = TaskStore(worktree, user_home=Path(user_root).expanduser(),
                          runtime_root=runtime_root)
    lock_paths = [old_store.lock_path]
    if mode in ("project-shared", "project-local"):
        runtime = (Path(runtime_root).expanduser() if runtime_root is not None
                   else Path(user_root).expanduser() / "runtime").resolve()
        new_key = hashlib.sha256(str(worktree).encode()).hexdigest()
        lock_paths.append(runtime / "projects" / new_key / "project.lock")
    return lock_paths


def _initialize_separate_worktree(worktree: Path, main: Path, user_root: Path, *,
                                  context: Optional[ProjectContext],
                                  storage: Optional[str],
                                  runtime_root: Optional[Path],
                                  lock_timeout: float) -> InitResult:
    """Real (non dry-run) ``--force-separate`` on a currently shared worktree.

    Acquires the identity-transition lock set, re-verifies every precondition
    INSIDE the locks, then performs data creation, registration and marker
    write as one group. B (registry ordering) applies in user-directory mode:
    the project lock is taken first (it is part of this lock set), and the
    registry lock is acquired inside the region via _rebind_registry_lock
    immediately before register_user_directory_project, matching
    TaskStore.rebind's project-lock-before-registry-lock order.
    """
    from .models import DomainError
    from .store import (POINTER_FILE, TaskStore, _initialized_at,
                        _rebind_registry_lock, _shared_worktree_layout)

    mode = _resolve_storage_mode(storage)
    before = _layout_conflicts(worktree, main)
    lock_paths = _separate_worktree_lock_paths(worktree, main, user_root,
                                               runtime_root, mode)
    with _transition_locks(lock_paths, lock_timeout):
        # Re-verify every precondition under the locks.
        current = _layout_conflicts(worktree, main)
        if current != before:
            raise DomainError("worktree_data_conflict",
                              "Project layout changed while the transition lock "
                              "was acquired; inspect both data roots and retry",
                              {"worktree": str(worktree), "main_root": str(main)}, status=4)
        for candidate in (worktree / ".fstar", worktree / POINTER_FILE):
            if candidate.exists() or candidate.is_symlink():
                raise DomainError("worktree_data_conflict",
                                  "Worktree metadata appeared during the transition",
                                  {"path": str(candidate)}, status=4)
        if _initialized_at(worktree):
            raise DomainError("worktree_data_conflict",
                              "Worktree gained its own identity during the transition",
                              {"worktree": str(worktree)}, status=4)
        try:
            shared = _shared_worktree_layout(worktree)
        except (DomainError, OSError, RuntimeError, ValueError) as exc:
            raise DomainError("worktree_data_conflict",
                              "Worktree layout became unverifiable during the "
                              "transition: %s" % exc,
                              {"worktree": str(worktree)}, status=4)
        if shared is None:
            raise DomainError("worktree_data_conflict",
                              "Worktree stopped sharing the main identity during "
                              "the transition", {"worktree": str(worktree)}, status=4)
        # Perform the conversion: data creation, registration and marker.
        if mode == "user-directory":
            # B: the project (identity) lock is already held above; take the
            # registry lock only now, inside the region, immediately before
            # registration — project lock first, registry lock second, the
            # same order as TaskStore.rebind. Never the reverse.
            with _rebind_registry_lock(Path(user_root).expanduser()):
                return _init_separate_direct(worktree, user_root, context=context,
                                             storage=storage, mode=mode)
        return _init_separate_direct(worktree, user_root, context=context,
                                     storage=storage, mode=mode)


def _init_separate_direct(worktree: Path, user_root: Path, *, context, storage,
                          mode: str) -> InitResult:
    """Run the mode-specific init flow inside a held transition lock.

    The shared-worktree guards in initialize_project are bypassed because the
    caller holds the transition locks and has re-verified the preconditions;
    the remaining validations (schema, path conflicts, registry) still run.
    """
    if mode == "user-directory":
        result = _initialize_user_directory(worktree, Path(user_root).expanduser(),
                                            context=context, dry_run=False)
        from .store import record_explicit_separate_worktree
        record_explicit_separate_worktree(worktree)
        return replace(result, force_separate=True)
    index, complete = _project_index(worktree, context)
    project_id = str(uuid.uuid4())
    files = [("index.md", index),
             ("config.yaml", "schema_version: 1\nproject:\n  id: \"%s\"\n" % project_id),
             (".gitignore", _PROJECT_IGNORE), (".schema-version", "1\n")]
    if mode == "project-local":
        files.append((STORAGE_MARKER_FILE, mode + "\n"))
    files = tuple(files)
    result = _initialize(worktree, files, dry_run=False, context_complete=complete,
                         project=True,
                         index_context=context is not None and bool(context.project_summary.strip()))
    if mode == "project-local":
        created, warnings = list(result.created), list(result.warnings)
        _apply_local_exclude(worktree, created, warnings, dry_run=False)
        result = replace(result, created=tuple(created), warnings=tuple(warnings))
    from .store import record_explicit_separate_worktree
    record_explicit_separate_worktree(worktree)
    return replace(result, force_separate=True)


def initialize_project(path: Path, user_root: Path, *, context: Optional[ProjectContext] = None,
                       dry_run: bool = False, storage: Optional[str] = None,
                       force_separate: bool = False,
                       runtime_root: Optional[Path] = None) -> InitResult:
    from .store import (POINTER_FILE, _initialized_at, _linked_worktree_main_root,
                        _resolve_data_root, _resolve_project_layout)

    mode = _resolve_storage_mode(storage)
    root = path.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise InitError("PROJECT_ROOT_INVALID", "Project root must be an existing directory", path=root)
    from .store import ensure_writable_layout
    ensure_writable_layout(_git_repo_root(root) or root)
    main_root = _linked_worktree_main_root(_git_repo_root(root) or root)
    # A real (non dry-run) separate conversion runs only when the worktree
    # currently shares the main identity WITHOUT local project metadata
    # (checked-out tracked metadata is an existing identity and is refused
    # as WORKTREE_IDENTITY_EXISTS, preserving prior semantics). The shared
    # guard is re-verified under the transition locks (A).
    metadata = (root / ".fstar", root / POINTER_FILE)
    if main_root is not None and force_separate and not dry_run \
            and not any(p.exists() or p.is_symlink() for p in metadata) \
            and _shared_layout(root, main_root):
        return _initialize_separate_worktree(root, main_root, Path(user_root).expanduser(),
                                             context=context, storage=storage,
                                             runtime_root=runtime_root,
                                             lock_timeout=_INIT_LOCK_TIMEOUT)
    if main_root is not None:
        if force_separate:
            if any(p.exists() or p.is_symlink() for p in metadata):
                raise InitError("WORKTREE_IDENTITY_EXISTS",
                                "Cannot create a separate identity while local project metadata exists; "
                                "existing data was left unchanged.", path=root)
        if _initialized_at(root):
            existing_mode = _resolve_project_layout(root)[1]
            if storage is not None and mode != existing_mode:
                raise InitError("WORKTREE_IDENTITY_EXISTS",
                                "Cannot change the storage of an existing worktree identity during init.",
                                path=root)
            mode = existing_mode
        elif not force_separate and _initialized_at(main_root):
            raise InitError(
                "WORKTREE_SHARED_PROJECT",
                "Linked worktree shares the initialized main project %s (data root: %s). "
                "Use that shared project, or pass --force-separate to explicitly initialize "
                "a separate project identity in this worktree." % (main_root, _resolve_data_root(main_root)),
                path=root)
    if storage is None and (root / POINTER_FILE).is_file():
        # Re-initializing an existing user-directory project: its mode comes
        # from the pointer, so a bare `fstar init` never creates a second
        # (in-repo) data root.
        mode = "user-directory"
    if mode == "user-directory":
        result = _initialize_user_directory(root, Path(user_root).expanduser(),
                                            context=context, dry_run=dry_run)
        if force_separate and main_root is not None and not dry_run:
            from .store import record_explicit_separate_worktree
            record_explicit_separate_worktree(root)
        return replace(result, force_separate=force_separate)
    index, complete = _project_index(root, context)
    project_id = str(uuid.uuid4())
    files = [("index.md", index),
             ("config.yaml", "schema_version: 1\nproject:\n  id: \"%s\"\n" % project_id),
             (".gitignore", _PROJECT_IGNORE), (".schema-version", "1\n")]
    if mode == "project-local":
        # The mode must be discoverable from the data root: this mode has no
        # pointer file, so the marker is what distinguishes it from the
        # legacy project-shared layout.
        files.append((STORAGE_MARKER_FILE, mode + "\n"))
    files = tuple(files)
    result = _initialize(root, files, dry_run=dry_run, context_complete=complete, project=True,
                         index_context=context is not None and bool(context.project_summary.strip()))
    if mode == "project-local" and not dry_run:
        created, warnings = list(result.created), list(result.warnings)
        _apply_local_exclude(root, created, warnings, dry_run=False)
        result = replace(result, created=tuple(created), warnings=tuple(warnings))
    if force_separate and main_root is not None and not dry_run:
        from .store import record_explicit_separate_worktree
        record_explicit_separate_worktree(root)
    return replace(result, force_separate=force_separate)


def _initialize_user_directory(root: Path, user_root: Path, *, context: Optional[ProjectContext],
                               dry_run: bool) -> InitResult:
    """user-directory mode: data lives under the user root, repo stays clean.

    A minimal pointer file (``.fstar-pointer.json``) is written inside the
    project so find_project_root keeps working; no ``.fstar/`` directory is
    created inside the repo. The pointer carries the project UUID and the
    pointer-relative data-root path, so identity is stable across moves.
    """
    from .store import (POINTER_FILE, POINTER_SCHEMA, _read_pointer, _safe_pointer_data_root,
                         register_user_directory_project, user_directory_root)

    name = _readable_name(root)
    pointer = root / POINTER_FILE
    existing_pointer = None
    if pointer.exists():
        if not pointer.is_file():
            raise InitError("PATH_CONFLICT", "Pointer path is not a regular file", path=pointer)
        try:
            existing_pointer = _read_pointer(pointer)
        except DomainError as exc:
            raise InitError("INVALID_POINTER", exc.message, path=pointer)
    if existing_pointer is not None:
        # Re-running init on an initialized project must not create a second
        # data root: the existing identity and location are reused.
        project_id = existing_pointer["project_id"]
        data_root = _safe_pointer_data_root(root, existing_pointer)
        pointer_record = dict(existing_pointer)
        pointer_record.setdefault("mode", "user-directory")
        pointer_record["bound_path"] = str(root)
    else:
        project_id = str(uuid.uuid4())
        data_root = user_directory_root(user_root.expanduser(), project_id, name)
        pointer_relative = os.path.relpath(data_root, root).replace(os.sep, "/")
        if pointer_relative.startswith(".."):
            # Data root lives outside the repo (typical user-directory layout):
            # store the resolved absolute path; traversal rules live in the reader.
            pointer_relative = str(data_root)
        pointer_record = {"schema": POINTER_SCHEMA, "project_id": project_id,
                          "data_root": pointer_relative, "bound_path": str(root),
                          "mode": "user-directory"}
    index, complete = _project_index(root, context)
    files = (("index.md", index),
             ("config.yaml", "schema_version: 1\nproject:\n  id: \"%s\"\n  storage: user-directory\n" % project_id),
             (".gitignore", _PROJECT_IGNORE), (".schema-version", "1\n"))
    if existing_pointer is None and (data_root / ".schema-version").is_file():
        # Same-name second project: a fresh UUID gives a fresh folder, so an
        # existing folder with a marker means this data root already belongs
        # to someone (or the pointer file was lost).
        raise InitError("PATH_CONFLICT", "This user-directory data root already exists",
                        path=data_root)
    created, preserved, warnings = [], [], []
    # data_root IS the project data folder; schema marker sits at its top level.
    preview = _initialize(data_root, files, dry_run=dry_run, context_complete=complete,
                         project=True, index_context=context is not None and bool(context.project_summary.strip()),
                         data_subdir=".")
    if not dry_run:
        if existing_pointer is not None:
            preserved.append(pointer)
            if pointer_record != existing_pointer:
                # The binding may have moved; refresh the pointer in place.
                _exclusive_write(pointer, json.dumps(pointer_record, ensure_ascii=False, indent=2) + "\n",
                                 created, preserved)
        else:
            _exclusive_write(pointer, json.dumps(pointer_record, ensure_ascii=False, indent=2) + "\n",
                             created, preserved)
        _apply_local_pointer_exclude(root, created)
        register_user_directory_project(user_home=user_root.expanduser(), project_id=project_id,
                                        name=name, data_root=data_root, project_path=root)
    return InitResult(root, tuple(created) + tuple(preview.created),
                      tuple(preserved) + tuple(preview.preserved),
                      tuple(warnings) + tuple(preview.warnings), complete, dry_run)


def _readable_name(root: Path) -> str:
    return root.name or root.resolve().name or "project"


def initialize_workflow_project(path: Path, user_root: Path, *, task_ref: str,
                                extensions: Optional[list] = None,
                                context: Optional[ProjectContext] = None,
                                dry_run: bool = False,
                                storage: Optional[str] = None,
                                force_separate: bool = False,
                                runtime_root: Optional[Path] = None) -> InitResult:
    """Initialize both roots, validating and repairing a partial user layout."""
    from .extensions import grants
    from .store import TaskStore

    root = Path(path).expanduser().resolve()
    if task_ref == "session-only":
        records = extensions if extensions is not None else []
    else:
        store = TaskStore(root, user_home=Path(user_root), runtime_root=runtime_root)
        store.require_project()
        records = store.read(task_ref)["extensions"]
    grants(records)  # Validate any supplied context; initialization needs no governance grant.
    # Validate project inputs before creating either root. User initialization
    # also validates an existing config and repairs files missing beside it.
    preview = initialize_project(root, user_root, context=context, dry_run=True, storage=storage,
                                 force_separate=force_separate, runtime_root=runtime_root)
    user_result = initialize_user(user_root, dry_run=dry_run)
    try:
        result = preview if dry_run else initialize_project(root, user_root, context=context,
                                                            storage=storage, force_separate=force_separate,
                                                            runtime_root=runtime_root)
    except InitError as exc:
        raise InitError(exc.code, exc.message, path=exc.path,
                        created=user_result.created + exc.created)
    warnings = user_result.warnings
    if user_result.created:
        warnings += (InitWarning("USER_ROOT_CREATED", user_result.root,
                                 "User root files %s" %
                                 ("would be created or repaired" if dry_run else "were created or repaired")),)
    return replace(result, created=user_result.created + result.created,
                   preserved=user_result.preserved + result.preserved,
                   warnings=warnings + result.warnings)


def initialize_user(user_root: Path, *, dry_run: bool = False) -> InitResult:
    root = user_root.expanduser().resolve()
    if not root.exists() and not root.parent.exists():
        raise InitError("USER_ROOT_PARENT_MISSING", "User root parent must exist", path=root.parent)
    files = (("index.md", _user_index(root)), ("config.yaml", "schema_version: 1\n"),
             (".gitignore", _USER_IGNORE))
    return _initialize(root, files, dry_run=dry_run, context_complete=True, project=False)


def register_commands(subparsers) -> None:
    from .store import STORAGE_MODES

    parser = subparsers.add_parser("init")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--user", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-separate", action="store_true",
                        help="explicitly initialize a separate project in a linked worktree")
    parser.add_argument("--storage", choices=list(STORAGE_MODES), default=None,
                        help="where project data lives: project-shared (default), "
                             "project-local (local git exclude), or user-directory")
    parser.add_argument("--context", metavar="JSON_FILE", help="Project context collected for initialization")
    parser.set_defaults(_fstar_project_handler=_handle_init)
    rebind = subparsers.add_parser("rebind")
    rebind.add_argument("path", help="new project root path after a move")
    # The old/current project root comes from the global --project option (or
    # cwd discovery); a second --project here would shadow the global one.
    rebind.set_defaults(_fstar_project_handler=_handle_rebind)


def _handle_rebind(args):
    from .models import DomainError
    from .store import (POINTER_FILE, TaskStore, find_rebind_source, rebind_registered)

    args.command = "rebind"
    target = Path(args.path).expanduser().resolve()
    explicit = Path(args.project).expanduser().resolve() if getattr(args, "project", None) else None
    user_home = Path(args.user_data_root).expanduser() if getattr(args, "user_data_root", None) else None
    runtime = Path(args.runtime_root).expanduser() if getattr(args, "runtime_root", None) else None
    # The source project may have moved: the pointer travels with the
    # repository but its recorded binding points at the old path, so a moved
    # project must stay discoverable for an explicit rebind.
    source = explicit or find_rebind_source(Path.cwd())
    if source is None:
        raise DomainError("project_not_initialized",
                          "No fstar project found at this path; pass --project PATH",
                          {"hint": "run rebind from inside the moved project, or pass "
                                   "--project with its recorded root"})
    pointer = source / POINTER_FILE
    if pointer.is_file() and not pointer.is_symlink():
        store = TaskStore(source, user_home=user_home, runtime_root=runtime)
        return store.rebind(target, confirmation={"source_id": "cli", "type": "rebind"})
    # No pointer at the source path (the repository moved without it): the
    # user-level registry still names the project, so the binding is
    # re-established explicitly from there.
    if user_home is None:
        raise DomainError("rebind_needs_user_root",
                          "Rebinding without a pointer needs the user-level registry; "
                          "pass --user-data-root",
                          {"path": str(source)})
    return rebind_registered(user_home=user_home, source_path=source,
                             target_path=target,
                             confirmation={"source_id": "cli", "type": "rebind"})


def _context_file(path: str) -> ProjectContext:
    from .models import DomainError
    try:
        with Path(path).open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or set(data) - {"project_summary", "topics", "authority_refs", "knowledge_refs"}:
            raise ValueError("Expected a project context object with recognized fields")
        summary = data.get("project_summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("project_summary must be a nonempty string")
        def entries(key, cls, fields):
            values = data.get(key, [])
            if not isinstance(values, list):
                raise ValueError("%s must be an array" % key)
            if any(not isinstance(item, dict) or set(item) != set(fields)
                   or any(not isinstance(item[field], str) or not item[field].strip() for field in fields)
                   for item in values):
                raise ValueError("%s entries must contain nonempty string fields: %s" % (key, ", ".join(fields)))
            return tuple(cls(**item) for item in values)
        return ProjectContext(summary, entries("topics", TopicReference, ("id", "title", "applies_to", "read_when", "path")),
                              entries("authority_refs", DocumentReference, ("title", "path")),
                              entries("knowledge_refs", DocumentReference, ("title", "path")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise DomainError("invalid_project_context", "Cannot read project context", {"path": path, "reason": str(exc)})


def _handle_init(args):
    from .models import DomainError
    user_root = Path(args.user_data_root).expanduser() if args.user_data_root else Path.home() / ".fstar"
    if args.user and args.context:
        raise DomainError("invalid_project_context", "Project context cannot be used with --user")
    context = _context_file(args.context) if args.context else None
    runtime_root = (Path(args.runtime_root).expanduser()
                    if getattr(args, "runtime_root", None) else None)
    result = initialize_user(user_root, dry_run=args.dry_run) if args.user else initialize_workflow_project(
        Path(args.path), user_root, task_ref="session-only", context=context, dry_run=args.dry_run,
        storage=getattr(args, "storage", None), force_separate=getattr(args, "force_separate", False),
        runtime_root=runtime_root)
    if not args.user and getattr(args, "storage", None):
        value = asdict(result)
        value["storage_mode"] = getattr(args, "storage", None)
        value["root"] = str(result.root)
        value["created"] = [str(path) for path in result.created]
        value["preserved"] = [str(path) for path in result.preserved]
        value["warnings"] = [{"code": item.code, "path": str(item.path), "message": item.message}
                             for item in result.warnings]
        return value
    value = asdict(result)
    value["root"] = str(result.root)
    value["created"] = [str(path) for path in result.created]
    value["preserved"] = [str(path) for path in result.preserved]
    value["warnings"] = [{"code": item.code, "path": str(item.path), "message": item.message}
                         for item in result.warnings]
    return value
