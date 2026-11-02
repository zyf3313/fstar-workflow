from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional

from .evidence import EvidenceService
from .models import DomainError
from .store import TaskStore, find_project_root
from .tasks import EXTENSIONS, TaskService, source_snapshot


def _actor(args, default_role="agent") -> dict:
    return {"role": getattr(args, "actor_role", None) or default_role, "id": getattr(args, "actor", None) or default_role, "session": getattr(args, "session", None)}


def _json_file(path: Optional[str], label: str) -> dict:
    if not path:
        raise DomainError("file_required", "%s file is required" % label)
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError("invalid_json_file", "Cannot read %s file" % label, {"path": path, "reason": str(exc)})
    if not isinstance(value, dict):
        raise DomainError("invalid_json_file", "%s file must contain an object" % label)
    return value


def _confirmation(args, service: TaskService, ref: str) -> dict:
    if getattr(args, "confirmation", None):
        return _json_file(args.confirmation, "confirmation")
    if getattr(args, "confirm_user", False):
        try:
            task = service.store.read(ref)
        except DomainError as exc:
            if args.command != "archive" or not args.operation_id or exc.code != "task_not_found":
                raise
            task = service.store.read(ref, archived=True)
        return {"source_id": getattr(args, "invocation", None) or "cli", "type": "command", "at": service.clock(), "actor": _actor(args, "user"), "reference": getattr(args, "invocation", None) or "interactive-cli", "quote": "", "scope": args.command, "validates": source_snapshot(task)}
    raise DomainError("confirmation_required", "Use --confirmation FILE or --confirm-user with a traceable invocation", status=3)


def _confirmation_actor(args, confirmation) -> dict:
    declared = (confirmation or {}).get("actor")
    if isinstance(declared, dict) and declared.get("role") and declared.get("id"):
        return declared
    # The actor role must be declared, never silently assumed to be the user.
    # --confirm-user is the explicit user-command channel; otherwise the host
    # supplies --actor-role.
    return _actor(args, "user" if getattr(args, "confirm_user", False) else "agent")


def _add_target(parser):
    parser.add_argument("task", nargs="?")


def _add_confirmation(parser):
    parser.add_argument("--confirmation")
    parser.add_argument("--confirm-user", action="store_true")
    parser.add_argument("--invocation")


def register_core_commands(subparsers) -> None:
    task = subparsers.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create")
    create.add_argument("title")
    create.add_argument("--name", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--parent")
    create.add_argument("--related")
    listing = task_sub.add_parser("list")
    mode = listing.add_mutually_exclusive_group()
    mode.add_argument("--active", action="store_true")
    mode.add_argument("--archived", action="store_true")
    mode.add_argument("--all", action="store_true")
    listing.add_argument("--query")
    task_sub.add_parser("current")

    for name in ("start", "accept", "archive"):
        parser = subparsers.add_parser(name)
        _add_target(parser)
        _add_confirmation(parser)
        if name == "archive":
            parser.add_argument("--operation-id")
            parser.add_argument("--workflow", action="store_true")

    drop = subparsers.add_parser("drop")
    _add_target(drop)
    _add_confirmation(drop)
    drop.add_argument("--action", choices=("drop", "revive"), default="drop")
    drop.add_argument("--reason", required=True)
    drop.add_argument("--disposition", choices=("keep", "discard", "knowledge"), default="keep")

    state = subparsers.add_parser("state")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    _add_target(state_sub.add_parser("show"))

    continuation = subparsers.add_parser("continue")
    _add_target(continuation)
    continuation.add_argument("--action", choices=("takeover", "replan", "revise", "reopen", "unblock"))
    continuation.add_argument("--reason")
    continuation.add_argument("--workflow", action="store_true")
    _add_confirmation(continuation)

    extension = subparsers.add_parser("extension")
    extension_sub = extension.add_subparsers(dest="extension_command", required=True)
    ext_list = extension_sub.add_parser("list")
    _add_target(ext_list)
    ext_enable = extension_sub.add_parser("enable")
    ext_enable.add_argument("id", choices=sorted(EXTENSIONS))
    _add_target(ext_enable)
    ext_enable.add_argument("--scope", choices=("full", "custom"), default="full")
    ext_enable.add_argument("--include", action="append", default=[])
    ext_enable.add_argument("--exclude", action="append", default=[])
    ext_enable.add_argument("--reason", default="")
    _add_confirmation(ext_enable)
    ext_disable = extension_sub.add_parser("disable")
    ext_disable.add_argument("id", choices=sorted(EXTENSIONS))
    _add_target(ext_disable)
    _add_confirmation(ext_disable)

    review = subparsers.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_record = review_sub.add_parser("record")
    _add_target(review_record)
    review_record.add_argument("--record", required=True)
    _add_target(review_sub.add_parser("list"))

    evidence = subparsers.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    invalidate = evidence_sub.add_parser("invalidate")
    _add_target(invalidate)
    invalidate.add_argument("--file", required=True)

    acceptance = subparsers.add_parser("acceptance")
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_command", required=True)
    _add_target(acceptance_sub.add_parser("status"))


def _resolve_ref(args, store: TaskStore) -> str:
    if getattr(args, "task", None):
        return args.task
    current = store.current(getattr(args, "session", None))
    if not current:
        raise DomainError("task_required", "Specify a task or an active --session pointer")
    return current["task_id"]


def _service(args) -> TaskService:
    explicit = Path(args.project).expanduser().resolve() if args.project else None
    project = explicit or find_project_root(Path.cwd())
    if project is None:
        raise DomainError("project_not_initialized", "No initialized fstar project found; pass --project PATH")
    user_home = Path(args.user_data_root).expanduser().resolve() if args.user_data_root else None
    runtime = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else None
    return TaskService(TaskStore(project, user_home=user_home, runtime_root=runtime))


OPTIONAL_HANDLER_ATTR = "_fstar_module_handler"


def _static_clock():
    from .tasks import utc_now
    return utc_now()


def _dispatch(args):
    # Optional modules (project/runtime/tools) register their subcommands via
    # register_commands(subparsers) and attach a handler to the parsed args
    # with parser.set_defaults(<OPTIONAL_HANDLER_ATTR>=handler). Such handlers
    # run before core task-service wiring so commands like `init` work on a
    # not-yet-initialized root. Handler contract: fn(args) -> JSON-encodable
    # result, raising DomainError (or an exception exposing .code/.message)
    # on failure.
    handler = getattr(args, OPTIONAL_HANDLER_ATTR, None)
    if handler is not None:
        return handler(args)
    if args.command == "extension" and not args.project and find_project_root(Path.cwd()) is None:
        # Session-only extension authorization: no project metadata exists and
        # none may be created implicitly. Validation of scope/members still
        # runs through the service layer without touching the filesystem.
        if args.extension_command == "list":
            return {"extensions": sorted(EXTENSIONS), "persistence": "session_only", "active": []}
        if args.confirmation:
            source = _json_file(args.confirmation, "confirmation")
        elif getattr(args, "confirm_user", False):
            # Explicit user-command channel; the host invocation reference is
            # recorded so the authorization stays traceable in-session.
            source = {"source_id": args.invocation or "cli", "type": "command", "at": "session", "actor": _actor(args, "user"), "reference": args.invocation or "interactive-cli", "quote": "", "scope": "extension", "validates": "session"}
        else:
            raise DomainError("confirmation_required", "Use --confirmation FILE or --confirm-user with a traceable invocation", status=3)
        if args.extension_command == "enable":
            # Session-only authorization: validate scope/members without any
            # filesystem or project metadata.
            validator = TaskService.__new__(TaskService)
            validator.clock = _static_clock
            return validator.enable_extension(None, authorization={"id": args.id, "scope": args.scope, "included": args.include, "excluded": args.exclude, "reason": args.reason, "source": source}, actor=_actor(args, "user"))
        return {"id": args.id, "disabled": True, "persistence": "session_only", "source": source}
    service = _service(args)
    store = service.store
    evidence = service.evidence
    if args.command == "task":
        if args.task_command == "create":
            related = _json_file(args.related, "related").get("related", []) if args.related else None
            return service.create(name=args.name, title=args.title, description=args.description, actor=_actor(args), parent=args.parent, related=related, session_id=args.session)
        if args.task_command == "list":
            if args.all:
                return {"active": service.list_tasks(query=args.query), "archived": service.list_tasks(archived=True, query=args.query)}
            return service.list_tasks(archived=args.archived, query=args.query)
        return service.current(args.session)
    ref = _resolve_ref(args, store) if hasattr(args, "task") and args.command != "extension" else getattr(args, "task", None)
    if args.command == "start":
        confirmation = _confirmation(args, service, ref)
        return service.start(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, session_id=args.session)
    if args.command == "accept":
        confirmation = _confirmation(args, service, ref)
        return service.accept(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation)
    if args.command == "archive":
        confirmation = _confirmation(args, service, ref)
        return service.archive(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, operation_id=args.operation_id, workflow=args.workflow)
    if args.command == "drop":
        confirmation = _confirmation(args, service, ref)
        return service.drop(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, reason=args.reason, disposition=args.disposition, action=args.action)
    if args.command == "state":
        return service.state(ref)
    if args.command == "continue":
        confirmation = _confirmation(args, service, ref) if args.action in {"replan", "revise", "reopen"} else None
        if args.action == "unblock":
            return service.set_blocked(ref, actor=_actor(args), reason=None, workflow_recovery=args.workflow)
        return service.continue_task(ref, session_id=args.session, action=args.action, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, reason=args.reason, workflow=args.workflow)
    if args.command == "extension":
        if args.extension_command == "list":
            return {"available": sorted(EXTENSIONS), "active": store.read(ref)["extensions"] if ref else [], "persistence": "task" if ref else "session_only"}
        source = _confirmation(args, service, ref) if ref else _json_file(args.confirmation, "confirmation")
        if args.extension_command == "enable":
            return service.enable_extension(ref, authorization={"id": args.id, "scope": args.scope, "included": args.include, "excluded": args.exclude, "reason": args.reason, "source": source}, actor=_confirmation_actor(args, source))
        return service.disable_extension(ref, extension_id=args.id, authorization=source, actor=_confirmation_actor(args, source))
    if args.command == "review":
        if args.review_command == "record":
            record = _json_file(args.record, "review")
            return service.record_review(ref, record=record, actor=_confirmation_actor(args, record.get("source")))
        return service.list_reviews(ref)
    if args.command == "evidence":
        return evidence.invalidate(ref, file=args.file, actor=_actor(args))
    if args.command == "acceptance":
        return evidence.acceptance_status(ref)
    raise DomainError("unknown_command", "Unknown command")


def _register_optional(subparsers, module_name: str) -> None:
    qualified = "fstar.%s" % module_name
    try:
        spec = importlib.util.find_spec(qualified)
    except (ImportError, ValueError):
        return
    if spec is None:
        return
    module = __import__(qualified, fromlist=["register_commands"])
    register = getattr(module, "register_commands", None)
    if register:
        before = {id(sub) for sub in subparsers.choices.values()}
        register(subparsers)
        for name, sub in subparsers.choices.items():
            if id(sub) in before:
                continue
            defaults = sub._defaults.get(OPTIONAL_HANDLER_ATTR)
            if defaults is None and sub._defaults.get("_fstar_project_handler") is not None:
                # Bridge the layout module's existing convention into the
                # generic optional-handler key without editing layout files.
                sub._defaults[OPTIONAL_HANDLER_ATTR] = sub._defaults["_fstar_project_handler"]
                defaults = sub._defaults[OPTIONAL_HANDLER_ATTR]
            if defaults is None:
                raise DomainError("optional_module_invalid", "Optional module %s registered command %s without a handler" % (module_name, name))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fstar")
    parser.add_argument("--project")
    parser.add_argument("--session")
    parser.add_argument("--user-data-root")
    parser.add_argument("--runtime-root")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--actor")
    parser.add_argument("--actor-role", choices=("user", "agent", "coordinator", "implement", "check"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_core_commands(subparsers)
    for module in ("project", "runtime", "tools", "dispatch", "installer"):
        _register_optional(subparsers, module)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if args.json else _human(result))
        return 0
    except DomainError as exc:
        if args.json:
            print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        else:
            print("fstar: %s: %s" % (exc.code, exc.message), file=sys.stderr)
            if exc.details:
                print(json.dumps(exc.details, ensure_ascii=False), file=sys.stderr)
        return exc.status
    except OSError as exc:
        error = {"error": {"code": "io_error", "message": str(exc), "details": {}}}
        print(json.dumps(error) if args.json else "fstar: io_error: %s" % exc, file=sys.stderr)
        return 1
    except Exception as exc:  # optional-module errors expose code/message
        code = getattr(exc, "code", None)
        if code:
            details = {"path": str(getattr(exc, "path", ""))} if getattr(exc, "path", None) else {}
            if args.json:
                print(json.dumps({"error": {"code": str(code), "message": str(getattr(exc, "message", exc)), "details": details}}, ensure_ascii=False), file=sys.stderr)
            else:
                print("fstar: %s: %s" % (code, getattr(exc, "message", exc)), file=sys.stderr)
                if details:
                    print(json.dumps(details, ensure_ascii=False), file=sys.stderr)
            return 2
        raise


def _human(result) -> str:
    if isinstance(result, list):
        return "\n".join("%s\t%s\t%s" % (x.get("name", ""), x.get("phase", ""), x.get("title", "")) if isinstance(x, dict) else str(x) for x in result) or "No results."
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
