from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional

from .evidence import EvidenceService
from .models import DomainError
from .store import TaskStore, find_project_root, checkout_project_root
from .tasks import EXTENSIONS, TaskService, source_snapshot


def _actor(args, default_role="agent") -> dict:
    return {"role": getattr(args, "actor_role", None) or default_role, "id": getattr(args, "actor", None) or default_role, "session": getattr(args, "session", None)}


_STDIN_DOCUMENT = {"consumed": False, "value": None}


def _read_stdin_json(label: str) -> dict:
    """Read ONE JSON object from stdin for a ``-`` path argument (A-004).

    The document is read and parsed once per process. A second consumer in
    the same invocation gets a deterministic ``stdin_document_reuse`` error
    instead of blocking on an already-drained stdin or silently receiving
    another flag's document. Empty, invalid, or non-object input fails with
    the same invalid-json error shape as a bad file.
    """
    if _STDIN_DOCUMENT["consumed"]:
        raise DomainError("stdin_document_reuse",
                          "Only one JSON document may be read from stdin per invocation; "
                          "give each '-' argument its own file", {"label": label}, status=2)
    _STDIN_DOCUMENT["consumed"] = True
    try:
        text = sys.stdin.read()
        value = json.loads(text)
    except (OSError, ValueError) as exc:
        raise DomainError("invalid_json_file", "Cannot read %s document from stdin" % label,
                          {"path": "-", "reason": str(exc)})
    if not isinstance(value, dict):
        raise DomainError("invalid_json_file", "%s document must be an object" % label, {"path": "-"})
    _STDIN_DOCUMENT["value"] = value
    return value


def _json_file(path: Optional[str], label: str) -> dict:
    if not path:
        raise DomainError("file_required", "%s file is required" % label)
    if path == "-":
        return _read_stdin_json(label)
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
    locate = task_sub.add_parser("locate")
    locate.add_argument("task", nargs="?", help="explicit task ref; beats every other lookup")
    locate.add_argument("--branch", help="branch name to locate a task for")
    locate.add_argument("--worktree", help="optional worktree path to disambiguate same-named branches")
    task_sub.add_parser("current")

    for name in ("start", "accept", "archive"):
        parser = subparsers.add_parser(name)
        _add_target(parser)
        _add_confirmation(parser)
        if name == "accept":
            parser.add_argument("--rule", help="JSON file citing the user rule that delegates acceptance for this class of work")
            parser.add_argument("--awaiting", action="store_true",
                                help="move the task into awaiting_acceptance after a fresh final check (coordinator action, no user confirmation)")
            parser.add_argument("--unified", action="store_true",
                                help="unified cross-project acceptance: one user confirmation completes the master and every linked child task")
            parser.add_argument("--rework", action="store_true",
                                help="user reports a problem during awaiting_acceptance; the task returns to planning for rework")
            parser.add_argument("--scope-file",
                                help="JSON file with the rework scope: {mode: full|localized, artifacts: [], paths: [], criteria_refs: []}. "
                                     "Omitted means the legacy full invalidation.")
            parser.add_argument("--recheck", action="store_true",
                                help="the final check behind awaiting_acceptance went stale; send the task back for a fresh check")
            parser.add_argument("--reason", help="reason for the reported problem")
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
    set_status = state_sub.add_parser("set-status")
    _add_target(set_status)
    set_status.add_argument("--status", required=True, choices=("active", "waiting_user", "waiting_external", "paused"))
    set_status.add_argument("--reason", help="required for non-active statuses")
    set_work_item = state_sub.add_parser("set-work-item")
    _add_target(set_work_item)
    set_work_item.add_argument("--id", required=True)
    set_work_item.add_argument("--state", required=True, choices=("done", "active", "blocked", "cancelled"))
    set_work_item.add_argument("--summary", default="")
    set_work_item.add_argument("--evidence", action="append", default=[], help="evidence reference; repeatable")
    set_next = state_sub.add_parser("set-next")
    _add_target(set_next)
    set_next.add_argument("--condition", help="clears next_step when both condition and action are omitted")
    set_next.add_argument("--action")
    add_deliverable = state_sub.add_parser("add-deliverable")
    _add_target(add_deliverable)
    add_deliverable.add_argument("--name", required=True)
    add_deliverable.add_argument("--path", required=True)
    add_deliverable.add_argument("--format", default="")
    add_deliverable.add_argument("--criteria", action="append", default=[], help="criteria reference; repeatable")
    add_deliverable.add_argument("--version", default="")

    continuation = subparsers.add_parser("continue")
    _add_target(continuation)
    continuation.add_argument("--action", choices=("takeover", "replan", "reopen", "rework", "unblock"))
    continuation.add_argument("--reason")
    continuation.add_argument("--workflow", action="store_true")
    continuation.add_argument("--scope-file",
                              help="JSON file with the rework scope (used by --action rework): "
                                   "{mode: full|localized, artifacts: [], paths: [], criteria_refs: []}")
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

    correction = subparsers.add_parser("correction")
    correction_sub = correction.add_subparsers(dest="correction_command", required=True)
    correction_record = correction_sub.add_parser("record")
    _add_target(correction_record)
    correction_record.add_argument("--record", required=True)
    _add_target(correction_sub.add_parser("list"))

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
    project = explicit or checkout_project_root(Path.cwd(), strict_worktree_errors=True)
    if project is None:
        raise DomainError("project_not_initialized", "No initialized fstar project found; pass --project PATH")
    user_home = Path(args.user_data_root).expanduser().resolve() if args.user_data_root else None
    runtime = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else None
    return TaskService(TaskStore(project, user_home=user_home, runtime_root=runtime))


OPTIONAL_HANDLER_ATTR = "_fstar_module_handler"


def _attach_foreign_candidates(args, exc: DomainError) -> None:
    """Attach foreign-project candidate hints to a local task_not_found (A-005).

    The failure keeps its original code, message, and status: only advisory
    detail is added. Candidates come from the configured user project
    registry alone (read-only); no project is switched and no filesystem-wide
    scan happens.
    """
    if getattr(exc, "code", None) != "task_not_found":
        return
    details = exc.details if isinstance(exc.details, dict) else {}
    task_ref = details.get("task")
    if not task_ref:
        return
    try:
        store = _service(args).store
    except DomainError:
        return
    try:
        from .crossproject import foreign_task_candidates

        found = foreign_task_candidates(store, task_ref)
    except Exception:
        return
    candidates = found.get("candidates") or []
    if not candidates:
        return
    enriched = dict(details)
    enriched["foreign_candidates"] = candidates
    skipped = found.get("skipped") or []
    if skipped:
        enriched["foreign_candidates_skipped"] = skipped
    enriched["hint"] = ("Task not found in this project; use --project PATH to target "
                        "another registered project.")
    exc.details = enriched


def _static_clock():
    from .tasks import utc_now
    return utc_now()


def _dispatch(args):
    # Optional modules (project/runtime/dispatch/installer) register their
    # subcommands via register_commands(subparsers) and attach a handler to
    # the parsed args with parser.set_defaults(<OPTIONAL_HANDLER_ATTR>=handler).
    # Such handlers run before core task-service wiring so commands like `init`
    # work on a not-yet-initialized root. Handler contract: fn(args) -> JSON-encodable
    # result, raising DomainError (or an exception exposing .code/.message)
    # on failure.
    handler = getattr(args, OPTIONAL_HANDLER_ATTR, None)
    if handler is not None:
        return handler(args)
    if (args.command == "extension" and not args.project
            and find_project_root(Path.cwd(), strict_worktree_errors=True) is None):
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
        if args.task_command == "locate":
            if not (args.task or args.branch or args.session):
                raise DomainError("task_required", "Locate needs a task ref, --branch, or --session", status=2)
            return service.locate(ref=args.task, session_id=args.session,
                                  branch=args.branch, worktree=args.worktree)
        return service.current(args.session)
    ref = _resolve_ref(args, store) if hasattr(args, "task") and args.command != "extension" else getattr(args, "task", None)
    if args.command == "start":
        confirmation = _confirmation(args, service, ref)
        return service.start(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, session_id=args.session)
    if args.command == "accept":
        if getattr(args, "awaiting", False):
            if getattr(args, "rework", False) or getattr(args, "unified", False) or getattr(args, "recheck", False):
                raise DomainError("invalid_request", "--awaiting cannot be combined with --rework, --recheck, or --unified", status=2)
            return service.enter_awaiting_acceptance(ref, actor=_actor(args))
        if getattr(args, "recheck", False):
            if getattr(args, "rework", False) or getattr(args, "unified", False):
                raise DomainError("invalid_request", "--recheck cannot be combined with --rework or --unified", status=2)
            return service.request_recheck(ref, actor=_actor(args), reason=args.reason)
        if getattr(args, "rework", False):
            confirmation = _confirmation(args, service, ref)
            scope = _json_file(args.scope_file, "rework scope") if getattr(args, "scope_file", None) else None
            return service.report_problem(ref, actor=_confirmation_actor(args, confirmation),
                                         confirmation=confirmation, reason=args.reason, scope=scope)
        confirmation = _confirmation(args, service, ref)
        rule = _json_file(args.rule, "acceptance rule") if args.rule else None
        actor = _confirmation_actor(args, confirmation)
        if getattr(args, "unified", False):
            return service.accept_unified(ref, actor=actor, confirmation=confirmation, rule=rule)
        return service.accept(ref, actor=actor, confirmation=confirmation, rule=rule)
    if args.command == "archive":
        confirmation = _confirmation(args, service, ref)
        return service.archive(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, operation_id=args.operation_id, workflow=args.workflow)
    if args.command == "drop":
        confirmation = _confirmation(args, service, ref)
        return service.drop(ref, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, reason=args.reason, disposition=args.disposition, action=args.action)
    if args.command == "state":
        if args.state_command == "show":
            return service.state(ref)
        if args.state_command == "set-status":
            return service.set_status(ref, actor=_actor(args), status=args.status, reason=args.reason)
        if args.state_command == "set-work-item":
            return service.set_work_item(ref, actor=_actor(args), item={"id": args.id, "state": args.state, "summary": args.summary, "evidence_refs": args.evidence})
        if args.state_command == "set-next":
            return service.set_next_step(ref, actor=_actor(args), condition=args.condition, action=args.action)
        if args.state_command == "add-deliverable":
            return service.register_deliverable(ref, actor=_actor(args), entry={"name": args.name, "path": args.path, "format": args.format, "criteria_refs": args.criteria, "version": args.version})
        raise DomainError("unknown_command", "Unknown state command")
    if args.command == "continue":
        confirmation = _confirmation(args, service, ref) if args.action in {"replan", "reopen", "rework"} else None
        if args.action == "unblock":
            return service.set_blocked(ref, actor=_actor(args), reason=None, workflow_recovery=args.workflow)
        scope = _json_file(args.scope_file, "rework scope") if args.action == "rework" and getattr(args, "scope_file", None) else None
        return service.continue_task(ref, session_id=args.session, action=args.action, actor=_confirmation_actor(args, confirmation), confirmation=confirmation, reason=args.reason, workflow=args.workflow, scope=scope)
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
    if args.command == "correction":
        if args.correction_command == "record":
            record = _json_file(args.record, "correction record")
            return service.record_correction(ref, record=record, actor=_confirmation_actor(args, record.get("source")))
        return service.list_corrections(ref)
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
    for module in ("project", "runtime", "dispatch", "installer", "crossproject",
                   "global_resources", "magpie"):
        _register_optional(subparsers, module)
    return parser


def _version_requested(argv: Optional[list]) -> bool:
    """True when argv asks for --version as the top-level flag (B-14).

    Only a bare ``--version`` counts; occurrences after a subcommand keyword
    (or after ``--``) may belong to that subcommand's own arguments and are
    ignored, so ``--version`` values of subcommand flags never trigger it.
    """
    tokens = list(sys.argv[1:] if argv is None else argv)
    for token in tokens:
        if token == "--":
            return False
        if token.startswith("-") and token != "-":
            if token == "--version":
                return True
            continue
        # First positional token: a subcommand keyword; --version after it
        # belongs to the subcommand's own parser.
        return False
    return False


def main(argv=None) -> int:
    if _version_requested(argv):
        # B-14: `fstar --version` is an alias for `fstar version`. The flag is
        # intercepted BEFORE argparse because the subparsers are required and
        # would otherwise exit 2; argparse's action="version" has the same
        # conflict. Equivalent output to the installer's version command.
        from .installer import roots_from_args, version_report

        tokens = list(sys.argv[1:] if argv is None else argv)
        overrides = {}
        for index in range(len(tokens) - 1):
            if tokens[index] in ("--project", "--user-data-root", "--runtime-root"):
                overrides[tokens[index][2:].replace("-", "_")] = tokens[index + 1]

        class _VersionArgs:
            user_data_root = overrides.get("user_data_root")
            runtime_root = overrides.get("runtime_root")
            project = overrides.get("project")
            host_root = []
            user_level = False

        print(json.dumps(version_report(roots=roots_from_args(_VersionArgs())), ensure_ascii=False, indent=2, default=str))
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    _STDIN_DOCUMENT.update(consumed=False, value=None)
    try:
        json_fields = ("payload", "result", "confirmation", "check_evidence",
                       "record", "scope_file", "rule", "plan_items")
        consumers = sum((value.count("-") if isinstance(value, list) else value == "-")
                        for value in (getattr(args, field, None) for field in json_fields))
        if consumers > 1:
            raise DomainError("stdin_document_reuse",
                              "Only one JSON input may use '-' per invocation; use files for the others",
                              {"consumers": consumers}, status=2)
        result = _dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if args.json else _human(result))
        return 0
    except DomainError as exc:
        try:
            _attach_foreign_candidates(args, exc)
        except Exception:
            # Hint enrichment is advisory: a failure to collect candidates
            # must never change the original error code, message, or status.
            pass
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
