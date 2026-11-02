from __future__ import annotations

import argparse
import json
import os
import stat
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
    tool_proposals: Optional[dict] = None


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


def _check_existing_project(root: Path) -> None:
    marker = root / ".fstar" / ".schema-version"
    config = root / ".fstar" / "config.yaml"
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


def _initialize(root: Path, files, *, dry_run: bool, context_complete: bool,
                project: bool) -> InitResult:
    created, preserved, warnings = [], [], []
    directory = root / ".fstar" if project else root
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise InitError("PATH_CONFLICT", "Data root is not a safe directory", path=directory)
    if project:
        _check_existing_project(root)
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
                directory.mkdir(mode=0o755)
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
    if project and (directory / "index.md") in preserved and context_complete:
        warnings.append(InitWarning("INDEX_PRESERVED", directory / "index.md",
                                    "Existing index was preserved; supplied context was not applied"))
        context_complete = False
    return InitResult(root, tuple(created), tuple(preserved), tuple(warnings), context_complete, dry_run)


def initialize_project(path: Path, user_root: Path, *, context: Optional[ProjectContext] = None,
                       dry_run: bool = False) -> InitResult:
    del user_root
    root = path.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise InitError("PROJECT_ROOT_INVALID", "Project root must be an existing directory", path=root)
    index, complete = _project_index(root, context)
    project_id = str(uuid.uuid4())
    files = (("index.md", index),
             ("config.yaml", "schema_version: 1\nproject:\n  id: \"%s\"\n" % project_id),
             (".gitignore", _PROJECT_IGNORE), (".schema-version", "1\n"))
    return _initialize(root, files, dry_run=dry_run, context_complete=complete, project=True)


def initialize_workflow_project(path: Path, user_root: Path, *, task_ref: str,
                                extensions: Optional[list] = None,
                                context: Optional[ProjectContext] = None,
                                dry_run: bool = False) -> InitResult:
    """Initialize a project and, when granted, propose initial tool bindings."""
    from .extensions import grants
    from .store import TaskStore

    root = Path(path).expanduser().resolve()
    if task_ref == "session-only":
        records = extensions if extensions is not None else []
    else:
        store = TaskStore(root, user_home=Path(user_root))
        store.require_project()
        records = store.read(task_ref)["extensions"]
    grants(records)  # Validate any supplied context; initialization needs no governance grant.
    result = initialize_project(root, user_root, context=context, dry_run=dry_run)
    if not dry_run:
        from .tools import _classifier_scan, _validate_scan_result
        try:
            proposals = _validate_scan_result(_classifier_scan()(
                project_root=root, user_root=Path(user_root).expanduser().resolve(), host_snapshot=None))
            result = replace(result, tool_proposals=proposals)
        except Exception as exc:
            warning = InitWarning("TOOL_SCAN_FAILED", root / ".fstar",
                                  "Project initialization completed, but the initial tool proposal scan failed: %s" % exc)
            result = replace(result, warnings=result.warnings + (warning,))
    return result


def initialize_user(user_root: Path, *, dry_run: bool = False) -> InitResult:
    root = user_root.expanduser().resolve()
    if not root.exists() and not root.parent.exists():
        raise InitError("USER_ROOT_PARENT_MISSING", "User root parent must exist", path=root.parent)
    files = (("index.md", _user_index(root)), ("config.yaml", "schema_version: 1\n"),
             (".gitignore", _USER_IGNORE))
    return _initialize(root, files, dry_run=dry_run, context_complete=True, project=False)


def register_commands(subparsers) -> None:
    parser = subparsers.add_parser("init")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--user", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--context", metavar="JSON_FILE", help="Project context collected for initialization")
    parser.set_defaults(_fstar_project_handler=_handle_init)


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
    result = initialize_user(user_root, dry_run=args.dry_run) if args.user else initialize_workflow_project(
        Path(args.path), user_root, task_ref="session-only", context=context, dry_run=args.dry_run)
    value = asdict(result)
    value["root"] = str(result.root)
    value["created"] = [str(path) for path in result.created]
    value["preserved"] = [str(path) for path in result.preserved]
    value["warnings"] = [{"code": item.code, "path": str(item.path), "message": item.message}
                         for item in result.warnings]
    return value
