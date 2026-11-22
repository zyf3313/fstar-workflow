"""Internal stdin/stdout bridge for the learn skill; not a user CLI command.

The caller carries session grants and genuine user confirmation. These records
are not tamper-proof against processes with the same filesystem permissions.
"""
import json
import sys
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

from . import knowledge as k
from .extensions import grants, includes
from .models import DomainError
from .store import TaskStore


def _object(value, name):
    if not isinstance(value, dict):
        raise DomainError("knowledge_invalid_schema", name + " must be an object")
    return value


def _construct(cls, value, name):
    try:
        return cls(**_object(value, name))
    except (TypeError, ValueError) as exc:
        raise DomainError("knowledge_invalid_schema", "Invalid " + name, {"reason": str(exc)})


def _read_selection(request):
    """Build one validated ReadSelection from a JSON request.

    Strings never silently iterate as scope tags or paths, every applicability
    entry must carry an explicit state, and the production request exposes no
    clock override: ``now`` stays a unit-test-only parameter of the provider.
    """

    raw = request.get("selection")
    if raw is None:
        raise DomainError("knowledge_invalid_schema", "read requires a selection object")
    if not isinstance(raw, dict):
        raise DomainError("knowledge_invalid_schema", "selection must be an object")
    selection = {}
    for field in ("topics", "documents", "dependencies", "global_constraints", "excluded", "scope"):
        values = raw.get(field, [])
        if not isinstance(values, list):
            raise DomainError("knowledge_invalid_schema",
                              "selection.%s must be a list of strings" % field)
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise DomainError("knowledge_invalid_schema",
                                  "selection.%s must be a list of non-empty strings" % field)
        selection[field] = tuple(values)
    applicability = raw.get("applicability", {})
    if not isinstance(applicability, dict):
        raise DomainError("knowledge_invalid_schema", "selection.applicability must be an object")
    states = {}
    for key, value in applicability.items():
        if not isinstance(value, dict) or value.get("state") not in ("include", "exclude", "unknown"):
            raise DomainError("knowledge_invalid_schema",
                              "applicability entries must carry an explicit include/exclude/unknown state")
        reason = value.get("reason", "")
        if not isinstance(reason, str):
            raise DomainError("knowledge_invalid_schema", "applicability reason must be a string")
        states[key] = k.Applicability(value["state"], reason)
    selection["applicability"] = states
    snapshot = raw.get("snapshot_hash", "")
    if not isinstance(snapshot, str):
        raise DomainError("knowledge_invalid_schema", "snapshot_hash must be a string")
    selection["snapshot_hash"] = snapshot
    return k.ReadSelection(**selection)


def _read_result(catalog, bundle):
    def exclusion(item):
        return {"key": item.key, "owner": item.owner, "relative": item.relative,
                "role": item.role, "reason": item.reason}

    def unloaded(item):
        return {"key": item.key, "owner": item.owner, "relative": item.relative,
                "role": item.role, "reason": item.reason}

    return {
        "snapshot_hash": bundle.snapshot_hash,
        "complete": bundle.complete,
        "conflicts_pending": bundle.conflicts_pending,
        "documents": [{"key": document.key, "owner": document.owner,
                       "relative": document.relative, "role": document.role,
                       "digest": document.digest, "size": document.size,
                       "language": document.language, "tier": document.tier,
                       "confidence": document.confidence, "text": document.text}
                      for document in bundle.full_documents],
        "excluded": [exclusion(item) for item in bundle.excluded],
        "required_unloaded": [unloaded(item) for item in bundle.required_unloaded],
        "language": dict(bundle.language),
    }


def _read(request):
    """Read the applicable knowledge for one selection.

    Reads follow the ordinary read-only policy: no grant is required or
    consulted, nothing is written, and no write grant is implied.  The caller
    gets the injected bodies with their confidence and every exclusion with its
    reason, plus the catalog snapshot hash a later assessment must carry.
    """

    project = Path(request["project_root"]).expanduser().resolve()
    user = Path(request["user_root"]).expanduser().resolve()
    max_bytes = request.get("max_bytes")
    if max_bytes is not None and (not isinstance(max_bytes, int) or isinstance(max_bytes, bool)
                                  or max_bytes < 0):
        raise DomainError("knowledge_invalid_schema", "max_bytes must be a non-negative integer")
    # The production request exposes no clock override: expiry always follows
    # the real clock; ``now`` stays a unit-test-only provider parameter.
    if "now" in request:
        raise DomainError("knowledge_invalid_schema",
                          "read does not accept a clock override; expiry follows the real date")
    catalog = k.load_catalog(user_root=user, project_root=project)
    bundle = k.load_context(catalog, selection=_read_selection(request),
                            max_bytes=max_bytes)
    return _read_result(catalog, bundle)


def _prepare(request):
    project = Path(request["project_root"]).expanduser().resolve()
    user = Path(request["user_root"]).expanduser().resolve()
    # Governance, including personal knowledge, requires an initialized project.
    k._require_initialized_project(project)
    raw_intent = dict(_object(request.get("intent"), "intent"))
    raw_intent["source"] = _construct(k.SourceRecord, raw_intent.get("source"), "source")
    if raw_intent.get("topic") is not None:
        raw_intent["topic"] = _construct(k.TopicChoice, raw_intent["topic"], "topic")
    intent = _construct(k.ChangeIntent, raw_intent, "intent")
    raw_assessment = dict(_object(request.get("assessment"), "assessment"))
    raw_assessment["reviewed"] = tuple(_construct(k.ReviewedSource, x, "reviewed source") for x in raw_assessment.get("reviewed", []))
    raw_assessment["applicability"] = {key: _construct(k.Applicability, value, "applicability") for key, value in _object(raw_assessment.get("applicability", {}), "applicability").items()}
    raw_assessment["conflicts"] = tuple(_construct(k.ReportedConflict, x, "conflict") for x in raw_assessment.get("conflicts", []))
    assessment = _construct(k.SemanticAssessment, raw_assessment, "assessment")
    edits = request.get("edits")
    if not isinstance(edits, list):
        raise DomainError("knowledge_invalid_schema", "edits must be a list")
    edits = [_construct(k.KnowledgeEdit, edit, "edit") for edit in edits]
    proposal = k.prepare_change(k.load_catalog(user_root=user, project_root=project), edits=edits,
                                intent=intent, assessment=assessment)
    return project, user, proposal, edits


def _task_store(request, project, user):
    runtime = request.get("runtime_root")
    if runtime is not None and (not isinstance(runtime, str) or not runtime.strip()):
        raise DomainError("knowledge_invalid_schema", "runtime_root must be a non-empty path")
    return TaskStore(project, user_home=user, runtime_root=Path(runtime).expanduser() if runtime else None)


def _authorize(request, project, user, proposal, requested_edits, store=None):
    ref = request.get("task_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise DomainError("task_required", "Explicit task_ref is required")
    records = request.get("extensions", [])
    if ref != "session-only":
        if records:
            raise DomainError("invalid_extension", "Persistent tasks use stored grants")
        if store is None:
            store = _task_store(request, project, user)
        store.require_project()
        records = store.read(ref)["extensions"]
    context = grants(records)
    categories = {k.CATEGORY_RULES: "rules", k.CATEGORY_MEMORY: "memory", k.CATEGORY_SPECS: "specs",
                  k.CATEGORY_CONTEXT: "knowledge", k.CATEGORY_REFERENCES: "knowledge"}
    required = set()
    for edit in proposal.edits:
        category = k._category_for(edit.owner, edit.relative)
        if category in categories:
            required.add(categories[category])
    # An explicitly edited index has no category; do not allow it to bypass
    # permissions for navigation entries unrelated to other edited bodies.
    for edit in requested_edits:
        if k._norm_rel(edit.path) == k._index_relative(edit.owner):
            required.update(("rules", "memory") if edit.owner == "user" else ("specs", "knowledge"))
    for member in sorted(required):
        if not includes(context, "project-governance", member):
            raise DomainError("extension_not_authorized", "Knowledge change requires authorization",
                              {"package": "project-governance", "member": member}, status=3)
    return sorted(required)


def run(request):
    request = _object(request, "request")
    action = request.get("action")
    if action not in ("read", "prepare", "apply"):
        raise DomainError("knowledge_invalid_schema", "action must be read, prepare or apply")
    if action == "read":
        return _read(request)
    project, user, proposal, edits = _prepare(request)
    if action == "prepare":
        required = _authorize(request, project, user, proposal, edits)
        return {"proposal_hash": proposal.proposal_hash, "proposal": proposal.payload(), "required_members": required}
    if not isinstance(request.get("confirmation"), dict):
        raise DomainError("knowledge_confirmation_required", "Explicit user confirmation is required")
    confirmation = _construct(k.Confirmation, request["confirmation"], "confirmation")
    ref = request.get("task_ref")
    store = _task_store(request, project, user) if isinstance(ref, str) and ref.strip() and ref != "session-only" else None
    # Lock order: task project lock, then provider owner locks (project, user).
    # No provider code takes the task lock, and read() does not nest flock.
    with store.transaction() if store else nullcontext():
        required = _authorize(request, project, user, proposal, edits, store=store)
        receipt = k.apply_change(proposal, confirmation, user_root=user, project_root=project)
    return {"receipt": asdict(receipt), "required_members": required}


def main(argv=None):
    if argv:
        print(json.dumps({"ok": False, "error": {"code": "knowledge_invalid_schema", "message": "No arguments supported", "details": {}}}))
        return 2
    try:
        request = json.load(sys.stdin)
        result = run(request)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except DomainError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, ensure_ascii=False))
        return exc.status
    except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "knowledge_invalid_schema", "message": str(exc), "details": {}}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
