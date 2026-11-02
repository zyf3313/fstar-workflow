"""Capability contracts, tools.yaml bindings, availability, and provenance.

Ownership (tool-binding subtask): this module owns the five capability
identifiers, the ``fstar.tools.v1`` document schema and its YAML subset, the
per-item binding resolution, the confirmed mutation API, the three-layer
availability assessment, the ``fstar.tool-use.v1`` provenance record, and the
single ``fstar tools scan`` command registration.

The deterministic classifier (``fstar.tool_classifier``) is a separate later
subtask. This module only shells out to its ``scan_tools`` callback; a missing
classifier is reported as unwired, never faked as an empty successful scan.
No installation, indexing, probing, or binding change happens without an
explicit confirmation bound to the exact proposal.

Design boundaries (parent design §3.4-3.6, §4.1-4.5):
- Bindings are configuration; availability is observed fact and is never
  written into ``tools.yaml``.
- ``match`` (classification) and the three availability layers are separate;
  neither promotes the other.
- Only ``tools scan`` is a user command; bind/status/validate/install remain
  internal APIs.
- Python 3.9 standard library only.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .config import ConfigError, parse_config
from .models import DomainError
from .store import content_hash, find_project_root
from .tasks import compact_events, make_event

TOOLS_SCHEMA = "fstar.tools.v1"
PROPOSAL_SCHEMA = "fstar.tools.proposal.v1"
RESOLUTION_SCHEMA = "fstar.tools.resolution.v1"
AVAILABILITY_SCHEMA = "fstar.tools.availability.v1"
TOOL_USE_SCHEMA = "fstar.tool-use.v1"
SCAN_SCHEMA = "fstar.tools.scan.v1"

CAPABILITIES = (
    "code-structure",
    "web-research",
    "knowledge-retrieval",
    "data-access",
    "test-execution",
)
TOOL_KINDS = ("cli", "mcp", "skill", "builtin")
MATCH_LEVELS = ("strong", "weak", "none")
BASIS_KINDS = ("registry", "probe", "user", "unclassified")
LAYERS = ("discoverable", "client_loaded", "minimal_call")
LAYER_STATUSES = ("verified", "failed", "unknown")
CONFIRMATION_TYPES = ("command", "conversation", "review")
CALL_RESULTS = ("passed", "failed", "blocked")
TARGETS = ("user", "project")

TOP_LEVEL_KEYS = ("schema", "detected_at", "tools", "bindings", "history")
TOOL_KEYS = ("tool", "kind", "version", "capabilities")
MATCH_KEYS = ("id", "match", "basis", "basis_source")
BASIS_SOURCE_KEYS = ("kind", "reference", "confirmation")
BINDING_KEYS = ("tool", "reason", "confirmation")
CONFIRMATION_KEYS = (
    "source_id", "type", "at", "actor", "reference", "quote", "scope", "validates",
)
HISTORY_KEYS = ("id", "at", "kind", "changes", "source", "before_digest")
PROPOSAL_KEYS = (
    "schema", "target", "path", "old_digest", "changes", "tools", "reason", "digest",
)
CALL_KEYS = ("id", "reference", "operation", "result")

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")

# A review confirmation must link back to a real user confirmation record; a
# bare approval marker ("approved", "ok", "lgtm") is never that record.
_APPROVAL_MARKER = re.compile(r"^(?:approved?|approves|ok|okay|lgtm|yes|y|done|✓|✔)$", re.IGNORECASE)

# Degradation path per capability (parent design §5). These texts are also the
# contractual fallback reported in gap output; see resources/capabilities/*.md.
FALLBACKS = {
    "code-structure": (
        "Literal text search locates text only; it cannot claim a verified call "
        "graph or impact set. State the gap explicitly instead of presenting text "
        "matches as structural results."
    ),
    "web-research": (
        "Use local material or an existing cache with explicit dates; state that "
        "the latest upstream version or original source could not be verified."
    ),
    "knowledge-retrieval": (
        "Fall back to index or text queries and itemize the missing semantic route "
        "or the unverified freshness per source."
    ),
    "data-access": (
        "Use a read-only export or schema documentation and mark it non-realtime; "
        "never execute write SQL as a probe."
    ),
    "test-execution": (
        "Use static checks with an explicit not-run marker; never report "
        "unexecuted tests as passing."
    ),
}

# Bundled default recommendations ("安装包默认推荐"). They are recommendations
# only: resolution marks them ``recommended`` and they never become authorized
# bindings. Complex values stay plain dicts so the default document can pass the
# same schema validation as a user file.
DEFAULT_RECOMMENDATIONS: Dict[str, Dict[str, str]] = {
    "code-structure": {
        "tool": "codegraph",
        "reason": "Bundled recommendation for symbol-level definition, reference, and impact lookup",
    },
    "web-research": {
        "tool": "websearch",
        "reason": "Bundled recommendation for host web search over original sources",
    },
    "knowledge-retrieval": {
        "tool": "project-index",
        "reason": "Bundled recommendation for indexed project knowledge lookup",
    },
    "data-access": {
        "tool": "dbhub",
        "reason": "Bundled recommendation for read-only database schema and query access",
    },
    "test-execution": {
        "tool": "project-runner",
        "reason": "Bundled recommendation for the project's own reproducible test runner",
    },
}

_DEFAULT_TOOL_SNAPSHOTS: List[Dict[str, Any]] = [
    {
        "tool": "codegraph",
        "kind": "mcp",
        "version": None,
        "capabilities": [{
            "id": "code-structure",
            "match": "strong",
            "basis": "Symbol-level definition, reference, and impact queries",
            "basis_source": {"kind": "registry", "reference": "bundled/defaults#code-structure"},
        }],
    },
    {
        "tool": "websearch",
        "kind": "builtin",
        "version": None,
        "capabilities": [{
            "id": "web-research",
            "match": "strong",
            "basis": "Host web search over original sources with traceable provenance",
            "basis_source": {"kind": "registry", "reference": "bundled/defaults#web-research"},
        }],
    },
    {
        "tool": "project-index",
        "kind": "builtin",
        "version": None,
        "capabilities": [{
            "id": "knowledge-retrieval",
            "match": "strong",
            "basis": "Project knowledge index with keyword and semantic routes",
            "basis_source": {"kind": "registry", "reference": "bundled/defaults#knowledge-retrieval"},
        }],
    },
    {
        "tool": "dbhub",
        "kind": "mcp",
        "version": None,
        "capabilities": [{
            "id": "data-access",
            "match": "strong",
            "basis": "Read-only database schema and query access",
            "basis_source": {"kind": "registry", "reference": "bundled/defaults#data-access"},
        }],
    },
    {
        "tool": "project-runner",
        "kind": "builtin",
        "version": None,
        "capabilities": [{
            "id": "test-execution",
            "match": "strong",
            "basis": "Project test runner with reproducible command, exit code, and failure output",
            "basis_source": {"kind": "registry", "reference": "bundled/defaults#test-execution"},
        }],
    },
]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _fail(code: str, message: str, details: Optional[dict] = None, *, status: int = 2) -> DomainError:
    return DomainError(code, message, details or {}, status=status)


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_iso(value: object) -> bool:
    if not isinstance(value, str) or not _ISO.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check_keys(value: Mapping, required: Sequence[str], allowed: Sequence[str], field: str) -> None:
    if not isinstance(value, dict):
        raise _fail("tools_invalid_schema", "%s must be an object" % field, {"field": field})
    missing = sorted(set(required) - set(value))
    unknown = sorted(set(value) - set(allowed))
    if missing or unknown:
        raise _fail("tools_invalid_schema", "%s has missing or unknown fields" % field,
                    {"field": field, "missing": missing, "unknown": unknown})


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso_older_than(value: str, now: str, max_age_seconds: int) -> bool:
    try:
        moment = _parse_iso(value)
        current = _parse_iso(now)
    except ValueError:
        return False
    return (current - moment) > timedelta(seconds=max_age_seconds)


# ---------------------------------------------------------------------------
# validation: fstar.tools.v1
# ---------------------------------------------------------------------------

def _validate_scope(scope: object, field: str) -> None:
    _check_keys(scope, ("target", "path", "changes"), ("target", "path", "changes", "tools"), field)
    if scope["target"] not in TARGETS:
        raise _fail("tools_invalid_schema", "scope.target must be user or project",
                    {"field": field + ".target", "value": scope["target"]})
    if not _is_nonempty_str(scope["path"]):
        raise _fail("tools_invalid_schema", "scope.path must be a non-empty string",
                    {"field": field + ".path"})
    changes = scope["changes"]
    if not isinstance(changes, dict):
        raise _fail("tools_invalid_schema", "scope.changes must be an object", {"field": field + ".changes"})
    for key, value in changes.items():
        if key not in CAPABILITIES:
            raise _fail("tools_invalid_schema", "scope.changes contains an unknown capability",
                        {"field": field + ".changes", "key": key})
        if value is not None and not _is_nonempty_str(value):
            raise _fail("tools_invalid_schema", "scope.changes values must be strings or null",
                        {"field": field + ".changes", "key": key})
    if "tools" in scope:
        tool_changes = scope["tools"]
        if not isinstance(tool_changes, dict):
            raise _fail("tools_invalid_schema", "scope.tools must be an object", {"field": field + ".tools"})
        for tool_id, snapshot in tool_changes.items():
            if not _is_nonempty_str(tool_id):
                raise _fail("tools_invalid_schema", "scope.tools keys must be tool identifiers",
                            {"field": field + ".tools"})
            if snapshot is not None:
                _validate_tool(snapshot, field + ".tools." + tool_id)


def _validate_confirmation(confirmation: object, field: str = "confirmation") -> None:
    _check_keys(confirmation, CONFIRMATION_KEYS, CONFIRMATION_KEYS, field)
    if not _is_nonempty_str(confirmation["source_id"]):
        raise _fail("tools_invalid_schema", "confirmation.source_id must be non-empty",
                    {"field": field + ".source_id"})
    if confirmation["type"] not in CONFIRMATION_TYPES:
        raise _fail("tools_invalid_schema", "confirmation.type is not a supported source type",
                    {"field": field + ".type", "value": confirmation["type"]})
    if not _is_iso(confirmation["at"]):
        raise _fail("tools_invalid_schema", "confirmation.at must be an ISO-8601 UTC timestamp",
                    {"field": field + ".at"})
    actor = confirmation["actor"]
    _check_keys(actor, ("role", "id"), ("role", "id"), field + ".actor")
    if actor["role"] != "user":
        raise _fail("tools_invalid_schema", "confirmation.actor.role must be user",
                    {"field": field + ".actor.role", "value": actor["role"]})
    if not _is_nonempty_str(actor["id"]):
        raise _fail("tools_invalid_schema", "confirmation.actor.id must be non-empty",
                    {"field": field + ".actor.id"})
    if not _is_nonempty_str(confirmation["reference"]):
        raise _fail("tools_invalid_schema", "confirmation.reference must locate the user input",
                    {"field": field + ".reference"})
    if not isinstance(confirmation["quote"], str):
        raise _fail("tools_invalid_schema", "confirmation.quote must be a string",
                    {"field": field + ".quote"})
    if confirmation["type"] == "conversation" and not confirmation["quote"].strip():
        raise _fail("tools_invalid_schema", "Conversation confirmation requires the user quote",
                    {"field": field + ".quote"})
    if confirmation["type"] == "review":
        if not confirmation["quote"].strip():
            raise _fail("tools_invalid_schema", "Review confirmation requires a traceable user record",
                        {"field": field + ".quote"})
        if _APPROVAL_MARKER.fullmatch(confirmation["quote"].strip()):
            # A bare approval marker is not the user confirmation record a
            # review must link back to (parent design: source trust boundary).
            raise _fail("tools_invalid_schema",
                        "A bare approval marker is not a review confirmation; cite the user confirmation record",
                        {"field": field + ".quote", "quote": confirmation["quote"]})
    _validate_scope(confirmation["scope"], field + ".scope")
    if not _is_nonempty_str(confirmation["validates"]):
        raise _fail("tools_invalid_schema", "confirmation.validates must bind a proposal digest",
                    {"field": field + ".validates"})


def _validate_tool(tool: object, field: str = "tool") -> None:
    _check_keys(tool, TOOL_KEYS, TOOL_KEYS, field)
    if not _is_nonempty_str(tool["tool"]):
        raise _fail("tools_invalid_schema", "tool.tool must be a non-empty stable identifier",
                    {"field": field + ".tool"})
    if tool["kind"] not in TOOL_KINDS:
        raise _fail("tools_invalid_schema", "tool.kind is not a supported kind",
                    {"field": field + ".kind", "value": tool["kind"]})
    if tool["version"] is not None and not isinstance(tool["version"], str):
        raise _fail("tools_invalid_schema", "tool.version must be a string or null; unknown is null",
                    {"field": field + ".version"})
    capabilities = tool["capabilities"]
    if not isinstance(capabilities, list):
        raise _fail("tools_invalid_schema", "tool.capabilities must be an array",
                    {"field": field + ".capabilities"})
    seen = set()
    for index, entry in enumerate(capabilities):
        where = "%s.capabilities[%d]" % (field, index)
        _check_keys(entry, MATCH_KEYS, MATCH_KEYS, where)
        capability = entry["id"]
        if capability not in CAPABILITIES:
            raise _fail("tools_invalid_schema", "Unknown capability identifier",
                        {"field": where + ".id", "value": capability})
        if capability in seen:
            raise _fail("tools_invalid_schema", "Duplicate capability entry inside one tool",
                        {"field": where + ".id", "value": capability})
        seen.add(capability)
        if entry["match"] not in MATCH_LEVELS:
            raise _fail("tools_invalid_schema", "match is not strong, weak, or none",
                        {"field": where + ".match", "value": entry["match"]})
        if not _is_nonempty_str(entry["basis"]):
            raise _fail("tools_invalid_schema", "match basis must explain the judgment",
                        {"field": where + ".basis"})
        source = entry["basis_source"]
        _check_keys(source, ("kind", "reference"), BASIS_SOURCE_KEYS, where + ".basis_source")
        if source["kind"] not in BASIS_KINDS:
            raise _fail("tools_invalid_schema", "basis_source.kind is not supported",
                        {"field": where + ".basis_source.kind", "value": source["kind"]})
        if not _is_nonempty_str(source["reference"]):
            raise _fail("tools_invalid_schema", "basis_source.reference must cite the basis",
                        {"field": where + ".basis_source.reference"})
        if "confirmation" in source:
            _validate_confirmation(source["confirmation"], where + ".basis_source.confirmation")
            changes = source["confirmation"]["scope"]["changes"]
            if capability not in changes:
                raise _fail("tools_invalid_schema",
                            "A confirmed user classification must explicitly include the capability judgment",
                            {"field": where + ".basis_source.confirmation.scope.changes",
                             "capability": capability})
        kind = source["kind"]
        if kind == "probe" and entry["match"] != "weak":
            raise _fail("tools_invalid_schema", "A generic probe can only produce a weak match",
                        {"field": where + ".match", "value": entry["match"]})
        if kind == "unclassified" and entry["match"] != "none":
            raise _fail("tools_invalid_schema", "An unclassified tool has no match",
                        {"field": where + ".match", "value": entry["match"]})
        if entry["match"] == "strong":
            if kind not in {"registry", "user"}:
                raise _fail("tools_invalid_schema",
                            "A strong match requires a registry basis or a confirmed user judgment",
                            {"field": where + ".basis_source.kind", "value": kind})
            if kind == "user" and "confirmation" not in source:
                raise _fail("tools_invalid_schema", "A user strong match requires its own classification confirmation",
                            {"field": where + ".basis_source"})


def _validate_binding(binding: object, tool_ids: set, where: str) -> None:
    _check_keys(binding, BINDING_KEYS, BINDING_KEYS, where)
    tool_id = binding["tool"]
    if tool_id is not None:
        if not _is_nonempty_str(tool_id):
            raise _fail("tools_invalid_schema", "binding.tool must be a tool identifier or null",
                        {"field": where + ".tool"})
        if tool_id not in tool_ids:
            raise _fail("tools_invalid_schema", "Binding references a tool absent from this file",
                        {"field": where + ".tool", "tool": tool_id})
    if not _is_nonempty_str(binding["reason"]):
        raise _fail("tools_invalid_schema", "binding.reason must be non-empty",
                    {"field": where + ".reason"})
    _validate_confirmation(binding["confirmation"], where + ".confirmation")


def _validate_history_entry(entry: object, where: str) -> None:
    _check_keys(entry, HISTORY_KEYS, HISTORY_KEYS, where)
    if not _is_nonempty_str(entry["id"]):
        raise _fail("tools_invalid_schema", "history.id must be non-empty", {"field": where + ".id"})
    if not _is_iso(entry["at"]):
        raise _fail("tools_invalid_schema", "history.at must be ISO-8601 UTC", {"field": where + ".at"})
    if entry["kind"] != "binding_changed":
        raise _fail("tools_invalid_schema", "Only committed binding changes are recorded in history",
                    {"field": where + ".kind", "value": entry["kind"]})
    changes = entry["changes"]
    _check_keys(changes, ("bindings", "tools"), ("bindings", "tools"), where + ".changes")
    bindings = changes["bindings"]
    if not isinstance(bindings, dict) or not all(
            key in CAPABILITIES and (value is None or _is_nonempty_str(value))
            for key, value in bindings.items()):
        raise _fail("tools_invalid_schema", "history changes.bindings is invalid",
                    {"field": where + ".changes.bindings"})
    tools = changes["tools"]
    if not isinstance(tools, dict):
        raise _fail("tools_invalid_schema", "history changes.tools must be an object",
                    {"field": where + ".changes.tools"})
    for tool_id, snapshot in tools.items():
        if not _is_nonempty_str(tool_id):
            raise _fail("tools_invalid_schema", "history tool change keys must be identifiers",
                        {"field": where + ".changes.tools"})
        if snapshot is not None:
            _validate_tool(snapshot, where + ".changes.tools." + tool_id)
    _validate_confirmation(entry["source"], where + ".source")
    if entry["before_digest"] is not None and not _is_nonempty_str(entry["before_digest"]):
        raise _fail("tools_invalid_schema", "history.before_digest must be a digest or null",
                    {"field": where + ".before_digest"})


def validate_tools(document: dict) -> dict:
    """Validate an ``fstar.tools.v1`` document and return a normalized copy.

    Pure function: never mutates the caller's data and performs no I/O. Any
    missing, unknown, or inconsistent field is an explicit error.
    """
    _check_keys(document, TOP_LEVEL_KEYS, TOP_LEVEL_KEYS, "document")
    if document["schema"] != TOOLS_SCHEMA:
        raise _fail("tools_invalid_schema", "Unsupported tools schema; expected %s" % TOOLS_SCHEMA,
                    {"field": "schema", "value": document["schema"]})
    detected_at = document["detected_at"]
    if detected_at is not None and not _is_iso(detected_at):
        raise _fail("tools_invalid_schema", "detected_at must be an ISO-8601 UTC timestamp or null",
                    {"field": "detected_at"})
    tools = document["tools"]
    if not isinstance(tools, list):
        raise _fail("tools_invalid_schema", "tools must be an array", {"field": "tools"})
    tool_ids = set()
    for index, tool in enumerate(tools):
        _validate_tool(tool, "tools[%d]" % index)
        if tool["tool"] in tool_ids:
            raise _fail("tools_invalid_schema", "Duplicate tool identifier",
                        {"field": "tools[%d].tool" % index, "value": tool["tool"]})
        tool_ids.add(tool["tool"])
    bindings = document["bindings"]
    if not isinstance(bindings, dict):
        raise _fail("tools_invalid_schema", "bindings must be an object", {"field": "bindings"})
    for capability, binding in bindings.items():
        if capability not in CAPABILITIES:
            raise _fail("tools_invalid_schema", "bindings contains an unknown capability",
                        {"field": "bindings", "key": capability})
        _validate_binding(binding, tool_ids, "bindings." + capability)
    history = document["history"]
    if not isinstance(history, list):
        raise _fail("tools_invalid_schema", "history must be an array", {"field": "history"})
    seen_history = set()
    for index, entry in enumerate(history):
        _validate_history_entry(entry, "history[%d]" % index)
        if entry["id"] in seen_history:
            raise _fail("tools_invalid_schema", "Duplicate history identifier",
                        {"field": "history[%d].id" % index, "value": entry["id"]})
        seen_history.add(entry["id"])
    return copy.deepcopy(document)


# ---------------------------------------------------------------------------
# loading and serialization
# ---------------------------------------------------------------------------

def _migration_hint(text: str, error: ConfigError) -> Optional[str]:
    if error.code != "CONFIG_UNSUPPORTED_SYNTAX" or not error.line:
        return None
    lines = text.splitlines()
    if error.line > len(lines):
        return None
    body = lines[error.line - 1].strip()
    if body.startswith("- ") and ": " in body:
        return ("Block mapping sequences are not supported; write each item as a "
                "single-line JSON flow object, e.g. - {\"tool\": \"codegraph\", ...}")
    return None


def load_tools(path: Path) -> dict:
    """Load and validate one ``tools.yaml`` layer.

    Returns ``{state: missing|loaded, path, document, digest}``. A missing file
    is a normal state; an existing empty, unreadable, wrongly encoded, or
    invalid file raises ``DomainError``. The digest is the SHA-256 of the raw
    bytes (null when missing).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"state": "missing", "path": str(path), "document": None, "digest": None}
    except OSError as exc:
        raise _fail("tools_read_error", "tools.yaml cannot be read",
                    {"path": str(path), "reason": str(exc)})
    digest = _sha256(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("tools_encoding_error", "tools.yaml must be UTF-8",
                    {"path": str(path), "reason": str(exc)})
    try:
        document = parse_config(text, path)
    except ConfigError as exc:
        details = {
            "path": str(exc.path or path),
            "line": exc.line,
            "key": exc.key,
            "parser_code": exc.code,
        }
        hint = _migration_hint(text, exc)
        if hint:
            details["hint"] = hint
        raise _fail("tools_invalid_schema", exc.message, details)
    return {"state": "loaded", "path": str(path), "document": validate_tools(document), "digest": digest}


def load_defaults() -> dict:
    """Return the bundled default recommendation layer.

    The result has the same shape as :func:`load_tools` plus ``recommendations``.
    It carries no confirmations and never counts as an authorized binding.
    """
    document = {
        "schema": TOOLS_SCHEMA,
        "detected_at": None,
        "tools": copy.deepcopy(_DEFAULT_TOOL_SNAPSHOTS),
        "bindings": {},
        "history": [],
    }
    return {
        "state": "defaults",
        "path": None,
        "digest": None,
        "document": validate_tools(document),
        "recommendations": copy.deepcopy(DEFAULT_RECOMMENDATIONS),
    }


def serialize_tools(document: dict) -> str:
    """Serialize exactly ``fstar.tools.v1``: one top-level key per line.

    Complex values use a single-line JSON flow value, the part of the
    ``config.parse_config`` subset this schema is designed for. The result must
    round-trip through :func:`load_tools`; callers re-parse before committing.
    """
    document = validate_tools(document)
    lines = [
        "%s: %s" % (key, json.dumps(document[key], ensure_ascii=False, sort_keys=True))
        for key in TOP_LEVEL_KEYS
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# resolution (no I/O)
# ---------------------------------------------------------------------------

def _empty_document() -> dict:
    return {"schema": TOOLS_SCHEMA, "detected_at": None, "tools": [], "bindings": {}, "history": []}


def _layer(scope: str, loaded: object) -> Optional[dict]:
    if loaded is None:
        return None
    if not isinstance(loaded, dict) or loaded.get("state") not in {"missing", "loaded", "defaults"}:
        raise _fail("tools_invalid_schema", "Binding layers must be load_tools results",
                    {"layer": scope})
    if loaded.get("state") != "loaded":
        return None
    return {
        "layer": scope,
        "path": loaded.get("path"),
        "digest": loaded.get("digest"),
        "document": validate_tools(loaded.get("document")),
    }


def _default_layer(defaults: object) -> dict:
    if defaults is None:
        defaults = load_defaults()
    if isinstance(defaults, dict) and "document" in defaults:
        document = validate_tools(defaults["document"])
        recommendations = defaults.get("recommendations", DEFAULT_RECOMMENDATIONS)
    else:
        document = validate_tools(defaults)
        recommendations = DEFAULT_RECOMMENDATIONS
    return {"document": document, "recommendations": copy.deepcopy(recommendations)}


def resolve_bindings(*, project: object = None, user: object = None, defaults: object = None) -> dict:
    """Resolve the five capabilities item by item: project > user > defaults.

    Each of ``project`` and ``user`` is a :func:`load_tools` result. A missing
    key inherits from the next layer; an explicit ``tool: null`` binding stops
    fallback. The selected binding and the selected tool snapshot always come
    from the same layer, so versions and confirmations are never spliced across
    files. The default layer is recommendation-only.
    """
    layers = [layer for layer in (_layer("project", project), _layer("user", user)) if layer]
    default = _default_layer(defaults)
    capabilities = [
        _resolve_capability(capability, layers, default) for capability in CAPABILITIES
    ]
    return {"schema": RESOLUTION_SCHEMA, "capabilities": capabilities}


def _resolve_capability(capability: str, layers: list, default: dict) -> dict:
    recommendation = copy.deepcopy(default["recommendations"].get(capability))
    for layer in layers:
        binding = layer["document"]["bindings"].get(capability)
        if binding is None:
            continue
        snapshot = None
        match = None
        if binding["tool"] is not None:
            snapshot = next(tool for tool in layer["document"]["tools"] if tool["tool"] == binding["tool"])
            match = next((entry for entry in snapshot["capabilities"] if entry["id"] == capability), None)
        return {
            "capability": capability,
            "state": "unbound" if binding["tool"] is None else "bound",
            "tool": copy.deepcopy(snapshot),
            "kind": snapshot["kind"] if snapshot else None,
            "version": snapshot["version"] if snapshot else None,
            "match": copy.deepcopy(match),
            "origin": {"layer": layer["layer"], "path": layer["path"], "digest": layer["digest"]},
            "binding_digest": content_hash(binding),
            "confirmation": copy.deepcopy(binding["confirmation"]),
            "recommendation": recommendation,
        }
    snapshot = next(
        (tool for tool in default["document"]["tools"]
         if recommendation and tool["tool"] == recommendation.get("tool")),
        None,
    )
    match = None
    if snapshot:
        match = next((entry for entry in snapshot["capabilities"] if entry["id"] == capability), None)
    return {
        "capability": capability,
        "state": "recommended" if snapshot else "unbound",
        "tool": copy.deepcopy(snapshot),
        "kind": snapshot["kind"] if snapshot else None,
        "version": snapshot["version"] if snapshot else None,
        "match": copy.deepcopy(match),
        "origin": {"layer": "defaults", "path": None, "digest": None},
        "binding_digest": None,
        "confirmation": None,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# proposals and confirmed mutation
# ---------------------------------------------------------------------------

def _validate_changes(changes: object, field: str) -> Dict[str, Optional[str]]:
    if not isinstance(changes, dict) or not changes:
        raise _fail("tools_invalid_proposal", "changes must be a non-empty capability map",
                    {"field": field})
    result = {}
    for capability, tool_id in changes.items():
        if capability not in CAPABILITIES:
            raise _fail("tools_invalid_proposal", "changes contains an unknown capability",
                        {"field": field, "key": capability})
        if tool_id is not None and not _is_nonempty_str(tool_id):
            raise _fail("tools_invalid_proposal", "changes values must be tool identifiers or null",
                        {"field": field, "key": capability})
        result[capability] = tool_id
    return result


def _validate_tool_changes(tools: object, field: str) -> Dict[str, Optional[dict]]:
    if tools is None:
        return {}
    if not isinstance(tools, dict):
        raise _fail("tools_invalid_proposal", "tool changes must be an object", {"field": field})
    result = {}
    for tool_id, snapshot in tools.items():
        if not _is_nonempty_str(tool_id):
            raise _fail("tools_invalid_proposal", "tool change keys must be identifiers",
                        {"field": field})
        if snapshot is not None:
            _validate_tool(snapshot, field + "." + tool_id)
            if snapshot["tool"] != tool_id:
                raise _fail("tools_invalid_proposal", "Tool snapshot identifier must match its key",
                            {"field": field, "key": tool_id})
        result[tool_id] = copy.deepcopy(snapshot)
    return result


def _proposal_payload(proposal: Mapping[str, Any]) -> dict:
    return {key: proposal[key] for key in PROPOSAL_KEYS if key != "digest"}


def _proposal_digest(proposal: Mapping[str, Any]) -> str:
    return content_hash(_proposal_payload(proposal))


def build_binding_proposal(*, target: str, loaded: dict, changes: dict, reason: str,
                           tools: Optional[dict] = None) -> dict:
    """Build an exact, unpersisted binding proposal for one target layer.

    ``loaded`` is the :func:`load_tools` result of that layer's ``tools.yaml``.
    ``changes`` maps a capability to a tool identifier or ``null`` (explicit
    unbind). ``tools`` carries tool metadata snapshots (or ``null`` removals)
    that change classification/version, so the confirmation scope covers the
    complete diff, not only the selected tool identifier.
    """
    if target not in TARGETS:
        raise _fail("tools_invalid_proposal", "target must be user or project", {"target": target})
    if not isinstance(loaded, dict) or loaded.get("state") not in {"missing", "loaded"}:
        raise _fail("tools_invalid_proposal", "loaded must be a load_tools result", {"target": target})
    path = loaded.get("path")
    if not _is_nonempty_str(path) or not Path(path).is_absolute():
        raise _fail("tools_invalid_proposal", "loaded.path must be an absolute tools.yaml path",
                    {"path": path})
    validated_changes = _validate_changes(changes, "changes")
    if not _is_nonempty_str(reason):
        raise _fail("tools_invalid_proposal", "reason must explain the requested binding change")
    tool_changes = _validate_tool_changes(tools, "tools")
    existing = set()
    document = loaded.get("document")
    if isinstance(document, dict):
        existing = {tool["tool"] for tool in document.get("tools", [])}
    for capability, tool_id in validated_changes.items():
        if tool_id is not None and tool_id not in existing and tool_id not in tool_changes:
            raise _fail("tools_invalid_proposal",
                        "Binding references a tool absent from the target file and no snapshot was proposed",
                        {"capability": capability, "tool": tool_id})
    proposal = {
        "schema": PROPOSAL_SCHEMA,
        "target": target,
        "path": str(path),
        "old_digest": loaded.get("digest"),
        "changes": validated_changes,
        "tools": {key: tool_changes[key] for key in sorted(tool_changes)},
        "reason": reason,
    }
    proposal["digest"] = _proposal_digest(proposal)
    return proposal


def _validate_proposal(proposal: object) -> dict:
    _check_keys(proposal, PROPOSAL_KEYS, PROPOSAL_KEYS, "proposal")
    if proposal["schema"] != PROPOSAL_SCHEMA:
        raise _fail("tools_invalid_proposal", "Unsupported proposal schema", {"field": "schema"})
    if proposal["target"] not in TARGETS:
        raise _fail("tools_invalid_proposal", "proposal.target must be user or project",
                    {"field": "target"})
    if not _is_nonempty_str(proposal["path"]) or not Path(proposal["path"]).is_absolute():
        raise _fail("tools_invalid_proposal", "proposal.path must be absolute", {"field": "path"})
    if proposal["old_digest"] is not None and not _is_nonempty_str(proposal["old_digest"]):
        raise _fail("tools_invalid_proposal", "proposal.old_digest must be a digest or null",
                    {"field": "old_digest"})
    _validate_changes(proposal["changes"], "changes")
    _validate_tool_changes(proposal["tools"], "tools")
    if not _is_nonempty_str(proposal["reason"]):
        raise _fail("tools_invalid_proposal", "proposal.reason must be non-empty")
    if not _is_nonempty_str(proposal["digest"]):
        raise _fail("tools_invalid_proposal", "proposal.digest must be non-empty")
    if _proposal_digest(proposal) != proposal["digest"]:
        raise _fail("tools_invalid_proposal", "Proposal digest does not match its content",
                    {"field": "digest"})
    return copy.deepcopy(proposal)


def _confirmation_scope(proposal: Mapping[str, Any]) -> dict:
    return {
        "target": proposal["target"],
        "path": proposal["path"],
        "changes": proposal["changes"],
        "tools": proposal["tools"],
    }


def _validate_confirmation_for(confirmation: object, proposal: Mapping[str, Any]) -> dict:
    if confirmation is None:
        raise _fail("tools_confirmation_required", "A binding change requires an explicit user confirmation",
                    {"proposal_digest": proposal["digest"]}, status=3)
    if not isinstance(confirmation, dict):
        raise _fail("tools_confirmation_required", "Confirmation must be an object", status=3)
    try:
        _validate_confirmation(confirmation)
    except DomainError as exc:
        raise _fail("tools_confirmation_required", "Confirmation is incomplete or invalid",
                    {"reason": exc.message, "details": exc.details}, status=3)
    expected = _confirmation_scope(proposal)
    actual = {
        "target": confirmation["scope"]["target"],
        "path": confirmation["scope"]["path"],
        "changes": confirmation["scope"]["changes"],
        "tools": confirmation["scope"].get("tools", {}),
    }
    if actual != expected:
        raise _fail("tools_invalid_confirmation",
                    "Confirmation scope must match the exact target and complete diff",
                    {"expected": expected, "actual": actual}, status=3)
    if confirmation["validates"] != proposal["digest"]:
        raise _fail("tools_stale_confirmation", "Confirmation does not bind the current proposal digest",
                    {"expected": proposal["digest"], "actual": confirmation["validates"]}, status=3)
    return copy.deepcopy(confirmation)


def _target_path(target: str, *, user_root: Path, project_root: Path) -> Path:
    if target == "user":
        return (Path(user_root).expanduser().resolve() / "tools.yaml")
    return (Path(project_root).expanduser().resolve() / ".fstar" / "tools.yaml")


def _root_for(target: str, *, user_root: Path, project_root: Path) -> Path:
    root = Path(user_root if target == "user" else project_root).expanduser().resolve()
    return root


def _reject_symlinks(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise _fail("tools_unsafe_target", "Symbolic links are not allowed for tools.yaml",
                        {"path": str(current)}, status=3)
        if current == stop or current.parent == current:
            break
        current = current.parent


def _lock(stream, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise _fail("tools_lock_timeout", "Timed out waiting for the tools lock", status=4)
            time.sleep(0.02)


@contextmanager
def tools_lock(runtime_root: Path, timeout: float = 5.0):
    """Hold the cooperating-writer ``tools.lock`` for ``tools.yaml`` reads/writes.

    Cooperating writers (``apply_binding``, provenance commits) serialize
    through this advisory lock at ``<runtime_root>/tools.lock``. The only
    supported nesting order is task lock first, then this lock (matching
    ``apply_binding``); acquiring the task lock while holding this lock can
    deadlock. The lock coordinates only processes sharing this runtime root;
    noncooperating writers and different runtime roots are outside its scope.
    """
    runtime = Path(runtime_root).expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stream = (runtime / "tools.lock").open("a+")
    try:
        _lock(stream, timeout)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def _read_target(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _fail("tools_read_error", "tools.yaml cannot be read",
                    {"path": str(path), "reason": str(exc)})


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".tools-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        temporary = None
        try:
            directory = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    except OSError as exc:
        raise _fail("tools_write_failed", "tools.yaml could not be written atomically",
                    {"path": str(path), "reason": str(exc)}, status=4)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _document_from_bytes(raw: Optional[bytes], path: Path) -> dict:
    if raw is None:
        return _empty_document()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("tools_encoding_error", "tools.yaml must be UTF-8",
                    {"path": str(path), "reason": str(exc)})
    try:
        return validate_tools(parse_config(text, path))
    except ConfigError as exc:
        raise _fail("tools_invalid_schema", "The current tools.yaml is invalid; repair it first",
                    {"path": str(path), "line": exc.line, "key": exc.key, "parser_code": exc.code})


def _full_changes(proposal: Mapping[str, Any]) -> dict:
    return {"bindings": copy.deepcopy(proposal["changes"]), "tools": copy.deepcopy(proposal["tools"])}


def _already_applied(document: dict, proposal: Mapping[str, Any], confirmation: dict) -> Optional[dict]:
    diff = _full_changes(proposal)
    for entry in document["history"]:
        if entry["source"]["source_id"] != confirmation["source_id"]:
            continue
        if entry["changes"] != diff:
            raise _fail("tools_binding_conflict",
                        "This confirmation source was already used for a different change",
                        {"source_id": confirmation["source_id"]}, status=4)
        for capability, tool_id in proposal["changes"].items():
            current = document["bindings"].get(capability)
            if not current or current.get("tool") != tool_id:
                raise _fail("tools_binding_conflict",
                            "Bindings changed after this authorization; build a new proposal",
                            {"capability": capability}, status=4)
        return {
            "status": "already_applied",
            "target": proposal["target"],
            "path": proposal["path"],
            "digest": proposal["old_digest"],
            "changes": diff,
            "history_id": entry["id"],
        }
    return None


def _applied_document(document: dict, proposal: Mapping[str, Any], confirmation: dict, clock) -> tuple:
    updated = copy.deepcopy(document)
    tools_by_id = {tool["tool"]: tool for tool in updated["tools"]}
    order = [tool["tool"] for tool in updated["tools"]]
    for tool_id, snapshot in proposal["tools"].items():
        if snapshot is None:
            if tool_id not in tools_by_id:
                raise _fail("tools_invalid_proposal", "Cannot remove a tool absent from the target file",
                            {"tool": tool_id})
            tools_by_id.pop(tool_id)
            order.remove(tool_id)
        else:
            tools_by_id[tool_id] = copy.deepcopy(snapshot)
            if tool_id not in order:
                order.append(tool_id)
    updated["tools"] = [tools_by_id[tool_id] for tool_id in order]
    for capability, tool_id in proposal["changes"].items():
        updated["bindings"][capability] = {
            "tool": tool_id,
            "reason": proposal["reason"],
            "confirmation": copy.deepcopy(confirmation),
        }
    entry = {
        "id": str(uuid.uuid4()),
        "at": clock(),
        "kind": "binding_changed",
        "changes": _full_changes(proposal),
        "source": copy.deepcopy(confirmation),
        "before_digest": proposal["old_digest"],
    }
    updated["history"].append(entry)
    return updated, entry


def apply_binding(proposal: dict, confirmation: dict, *, clock: Callable[[], str],
                  user_root: Path, project_root: Path, runtime_root: Path,
                  lock_timeout: float = 5.0) -> dict:
    """Commit a confirmed binding proposal atomically to one target layer.

    ``user_root``/``project_root`` are the caller's explicit allowed roots and
    ``runtime_root`` holds the POSIX advisory lock (design §4). The target must
    be exactly ``<root>/tools.yaml`` (user) or ``<root>/.fstar/tools.yaml``
    (project); symlinks are rejected. The confirmation must bind the complete
    diff (bindings and tool metadata) and the proposal digest. Nothing is
    written when the confirmation, target, or the re-read file digest does not
    match; a successful commit appends the matching history entry in the same
    atomic write.
    """
    proposal = _validate_proposal(proposal)
    confirmation = _validate_confirmation_for(confirmation, proposal)
    expected_path = _target_path(proposal["target"], user_root=user_root, project_root=project_root)
    if Path(proposal["path"]).resolve() != expected_path:
        raise _fail("tools_unsafe_target", "Proposal target is outside the allowed roots",
                    {"path": proposal["path"], "expected": str(expected_path)}, status=3)
    if proposal["target"] == "project":
        marker = expected_path.parent / ".schema-version"
        if not marker.is_file():
            raise _fail("project_not_initialized",
                        "A project binding requires an initialized project", {"path": str(marker)})
    stop = _root_for(proposal["target"], user_root=user_root, project_root=project_root)
    runtime = Path(runtime_root).expanduser().resolve()
    # Confirmation is already validated: only now may the lock/runtime directory
    # and the target directory come into existence (design §4).
    with tools_lock(runtime, lock_timeout):
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlinks(expected_path, stop)
        raw = _read_target(expected_path)
        current_digest = _sha256(raw) if raw is not None else None
        document = _document_from_bytes(raw, expected_path)
        # Reusing an existing authorization is not a new approval: an exact
        # replay of an already committed change is a no-op even though the
        # file digest has moved on.
        applied = _already_applied(document, proposal, confirmation)
        if applied is not None:
            return applied
        if current_digest != proposal["old_digest"]:
            raise _fail("tools_binding_conflict",
                        "tools.yaml changed since the proposal was built",
                        {"expected": proposal["old_digest"], "actual": current_digest}, status=4)
        known = {tool["tool"] for tool in document["tools"]}
        known.update(key for key, snapshot in proposal["tools"].items() if snapshot is not None)
        for capability, tool_id in proposal["changes"].items():
            if tool_id is not None and tool_id not in known:
                raise _fail("tools_invalid_proposal",
                            "Binding references a tool absent from the target document",
                            {"capability": capability, "tool": tool_id})
        updated, entry = _applied_document(document, proposal, confirmation, clock)
        text = serialize_tools(updated)
        reparsed = validate_tools(parse_config(text, expected_path))
        if content_hash(reparsed) != content_hash(updated):
            raise _fail("tools_write_failed", "Serialized tools.yaml does not round-trip",
                        {"path": str(expected_path)}, status=4)
        _reject_symlinks(expected_path, stop)
        data = text.encode("utf-8")
        _atomic_write(expected_path, data)
        return {
            "status": "applied",
            "target": proposal["target"],
            "path": str(expected_path),
            "digest": _sha256(data),
            "changes": _full_changes(proposal),
            "history_id": entry["id"],
        }


# ---------------------------------------------------------------------------
# availability and gaps
# ---------------------------------------------------------------------------

def _observation_summary(observation: dict) -> dict:
    return {
        "layer": observation["layer"],
        "status": observation["status"],
        "at": observation["at"],
        "scope": copy.deepcopy(observation["scope"]),
        "evidence_ref": observation.get("evidence_ref"),
        "reason": observation.get("reason"),
        "call_id": observation.get("call_id"),
    }


def _unknown_layer(reason: str) -> dict:
    return {
        "layer": None,
        "status": "unknown",
        "at": None,
        "scope": None,
        "evidence_ref": None,
        "reason": reason,
        "call_id": None,
        "stale": False,
    }


def _validate_observations(observations: object) -> List[dict]:
    if not isinstance(observations, list):
        raise _fail("tools_invalid_observation", "observations must be an array")
    required = {"tool", "capability", "layer", "status", "at", "scope"}
    allowed = required | {"evidence_ref", "reason", "call_id"}
    for index, observation in enumerate(observations):
        where = "observations[%d]" % index
        if not isinstance(observation, dict):
            raise _fail("tools_invalid_observation", "%s must be an object" % where)
        missing = sorted(required - set(observation))
        unknown = sorted(set(observation) - allowed)
        if missing or unknown:
            raise _fail("tools_invalid_observation", "%s has missing or unknown fields" % where,
                        {"field": where, "missing": missing, "unknown": unknown})
        if not _is_nonempty_str(observation["tool"]):
            raise _fail("tools_invalid_observation", "observation.tool must be non-empty",
                        {"field": where + ".tool"})
        if observation["capability"] not in CAPABILITIES:
            raise _fail("tools_invalid_observation", "observation.capability is unknown",
                        {"field": where + ".capability", "value": observation["capability"]})
        if observation["layer"] not in LAYERS:
            raise _fail("tools_invalid_observation", "observation.layer is not a verification layer",
                        {"field": where + ".layer", "value": observation["layer"]})
        if observation["status"] not in LAYER_STATUSES:
            raise _fail("tools_invalid_observation", "observation.status is invalid",
                        {"field": where + ".status", "value": observation["status"]})
        if not _is_iso(observation["at"]):
            raise _fail("tools_invalid_observation", "observation.at must be ISO-8601 UTC",
                        {"field": where + ".at"})
        scope = observation["scope"]
        if not isinstance(scope, dict) or set(scope) != {"project", "host", "session"}:
            raise _fail("tools_invalid_observation",
                        "observation.scope must contain project, host, and session",
                        {"field": where + ".scope"})
        for key, value in scope.items():
            if value is not None and not isinstance(value, str):
                raise _fail("tools_invalid_observation", "observation.scope values must be strings or null",
                            {"field": where + ".scope." + key})
        if observation["status"] == "verified":
            if not _is_nonempty_str(observation.get("evidence_ref")):
                raise _fail("tools_invalid_observation", "A verified observation requires evidence_ref",
                            {"field": where + ".evidence_ref"})
            if observation["layer"] == "minimal_call" and not _is_nonempty_str(observation.get("call_id")):
                raise _fail("tools_invalid_observation",
                            "A verified minimal_call requires the real call_id",
                            {"field": where + ".call_id"})
        if observation["status"] == "failed" and not _is_nonempty_str(observation.get("reason")):
            raise _fail("tools_invalid_observation", "A failed observation requires its reason",
                        {"field": where + ".reason"})
    return [copy.deepcopy(item) for item in observations]


def _assess_capability(entry: dict, observations: List[dict], now: Optional[str],
                       max_age_seconds: Optional[int]) -> dict:
    capability = entry["capability"]
    tool = entry.get("tool")
    tool_id = tool["tool"] if tool else None
    layers = {}
    for layer in LAYERS:
        candidates = [
            item for item in observations
            if item["capability"] == capability and item["layer"] == layer
            and tool_id is not None and item["tool"] == tool_id
        ]
        if not candidates:
            layers[layer] = dict(_unknown_layer("not_observed"), layer=layer)
            continue
        # Select the most recent observation for this layer by parsed time, not
        # by raw string order: fractional and non-fractional seconds would
        # otherwise compare incorrectly.
        observation = max(candidates, key=lambda item: _parse_iso(item["at"]))
        summary = _observation_summary(observation)
        summary["stale"] = bool(
            now is not None and max_age_seconds is not None
            and _iso_older_than(observation["at"], now, max_age_seconds)
        )
        if summary["stale"]:
            summary["status"] = "unknown"
            summary["reason"] = "stale_observation"
        layers[layer] = summary
    verified = [layer for layer in LAYERS if layers[layer]["status"] == "verified"]
    signatures = {
        json.dumps(layers[layer]["scope"], sort_keys=True) for layer in verified
    }
    if len(signatures) > 1:
        # Discovered in one project/host/session and called in another is not a
        # current verification for either: report every verified layer unknown.
        for layer in verified:
            layers[layer] = dict(layers[layer])
            layers[layer]["status"] = "unknown"
            layers[layer]["reason"] = "scope_mismatch"
            layers[layer]["previous_status"] = "verified"
        verified = []
    missing = [layer for layer in LAYERS if layers[layer]["status"] != "verified"]
    reasons = [
        {"layer": layer, "status": layers[layer]["status"], "reason": layers[layer]["reason"] or "not_verified"}
        for layer in missing
    ]
    match = entry.get("match")
    match_level = match["match"] if match else None
    gap = None
    if entry["state"] != "bound" or missing or match_level != "strong":
        gap = {
            "capability": capability,
            "tool": tool_id,
            "origin": copy.deepcopy(entry["origin"]),
            "match": match_level,
            "missing_layers": missing,
            "reasons": reasons,
            "recommendations": {"source": "capabilities/%s.md" % capability},
            "fallback": FALLBACKS[capability],
        }
    return {
        "capability": capability,
        "tool": tool_id,
        "state": entry["state"],
        "version": tool["version"] if tool else None,
        "match": match_level,
        "layers": layers,
        "missing_layers": missing,
        "reasons": reasons,
        "gap": gap,
    }


def assess_availability(resolution: dict, observations: list, *, now: Optional[str] = None,
                        max_age_seconds: Optional[int] = None) -> dict:
    """Assess the three availability layers per capability (pure, no host calls).

    ``observations`` are host-adapter facts. Existence is not client loading and
    client loading is not a call: each layer is reported independently and a
    missing fact stays ``unknown``. Freshness is explicit caller input (``now``
    plus ``max_age_seconds``); the function never silently refreshes facts, and
    a failed result is never reported as verified.
    """
    if not isinstance(resolution, dict) or resolution.get("schema") != RESOLUTION_SCHEMA:
        raise _fail("tools_invalid_schema", "assess_availability expects a resolution result")
    if now is not None and not _is_iso(now):
        raise _fail("tools_invalid_observation", "now must be an ISO-8601 UTC timestamp")
    if max_age_seconds is not None and (not isinstance(max_age_seconds, int) or max_age_seconds < 0):
        raise _fail("tools_invalid_observation", "max_age_seconds must be a non-negative integer")
    validated = _validate_observations(observations)
    capabilities = [
        _assess_capability(entry, validated, now, max_age_seconds)
        for entry in resolution["capabilities"]
    ]
    return {
        "schema": AVAILABILITY_SCHEMA,
        "capabilities": capabilities,
        "gaps": [item["gap"] for item in capabilities if item["gap"]],
    }


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def _availability_snapshot(availability: object, capability: str) -> Optional[dict]:
    if availability is None:
        return None
    if not isinstance(availability, dict):
        raise _fail("tools_invalid_observation", "availability must be an assessment result")
    if availability.get("schema") == AVAILABILITY_SCHEMA:
        entry = next(
            (item for item in availability.get("capabilities", [])
             if item.get("capability") == capability), None,
        )
        if entry is None:
            return None
        return {
            "state": entry["state"],
            "missing_layers": list(entry["missing_layers"]),
            "layers": {layer: detail["status"] for layer, detail in entry["layers"].items()},
        }
    return None


def build_provenance(resolution: dict, call_record: dict, availability: object = None) -> dict:
    """Build an ``fstar.tool-use.v1`` record from an actual call.

    A scan result or a binding proposal is not a call: the record must carry a
    real call identifier and a traceable source reference. Failed and blocked
    calls are recorded honestly; nothing here claims that a call passed a check
    or that the user accepted the result. Only the listed fields are copied, so
    credentials, raw SQL data, and raw responses never enter the record.

    ``tool`` records the tool that was actually used. When the call took the
    fallback path (the capability is unbound, or a different tool than the
    bound one served the call), the caller names that actual tool in
    ``call_record.tool``; the binding fields keep the bound selection so the
    degraded path stays visible next to what was authorized.
    """
    if not isinstance(resolution, dict) or resolution.get("schema") != RESOLUTION_SCHEMA:
        raise _fail("tools_invalid_schema", "build_provenance expects a resolution result")
    if not isinstance(call_record, dict):
        raise _fail("tools_invalid_call_record", "A real call record is required")
    capability = call_record.get("capability")
    if capability not in CAPABILITIES:
        raise _fail("tools_invalid_call_record", "call_record.capability is unknown",
                    {"capability": capability})
    call = call_record.get("call")
    if not isinstance(call, dict):
        raise _fail("tools_invalid_call_record",
                    "A provenance record requires a real call identity, not a scan or proposal")
    call_id = call.get("id")
    reference = call.get("reference")
    operation = call.get("operation")
    if not _is_nonempty_str(call_id) or not _is_nonempty_str(reference):
        raise _fail("tools_invalid_call_record",
                    "A provenance record requires the real call id and its source reference")
    if not _is_nonempty_str(operation):
        raise _fail("tools_invalid_call_record", "A provenance record requires a sanitized operation summary")
    result = call.get("result", call_record.get("result"))
    if result not in CALL_RESULTS:
        raise _fail("tools_invalid_call_record", "call result must be passed, failed, or blocked",
                    {"result": result})
    if not _is_iso(call_record.get("at")):
        raise _fail("tools_invalid_call_record", "call_record.at must be an ISO-8601 UTC timestamp")
    entry = next(
        (item for item in resolution["capabilities"] if item["capability"] == capability), None,
    )
    if entry is None:
        raise _fail("tools_invalid_call_record", "The capability is absent from the resolution")
    bound_tool = entry.get("tool")
    match = entry.get("match")
    bound = entry["state"] == "bound"
    bound_id = bound_tool["tool"] if bound_tool else None
    # The tool actually used: the bound selection unless the caller names the
    # degraded-path tool explicitly. Misnaming the bound tool as the actual
    # one would hide a fallback call as a bound call.
    actual_tool = call_record.get("tool", bound_id)
    if actual_tool is not None and not _is_nonempty_str(actual_tool):
        raise _fail("tools_invalid_call_record", "call_record.tool must be a tool identifier or null")
    if actual_tool is None:
        raise _fail("tools_invalid_call_record",
                    "A provenance record requires the tool actually used; an unbound capability "
                    "must name its degraded-path tool",
                    {"capability": capability})
    fallback = bool(call_record.get("fallback", not bound or actual_tool != bound_id))
    return {
        "schema": TOOL_USE_SCHEMA,
        "id": str(uuid.uuid4()),
        "capability": capability,
        "tool": actual_tool,
        "kind": bound_tool["kind"] if (bound_tool and actual_tool == bound_id) else None,
        "version": bound_tool["version"] if (bound_tool and actual_tool == bound_id) else None,
        "at": call_record["at"],
        "binding_origin": entry["origin"] if bound else None,
        "binding_digest": entry.get("binding_digest") if bound else None,
        "match": match["match"] if match else None,
        "basis": match["basis"] if match else None,
        "call": {
            "id": call_id,
            "reference": reference,
            "operation": operation,
            "result": result,
        },
        "availability": _availability_snapshot(availability, capability),
        "fallback": fallback,
    }


def _validate_record(record: object) -> dict:
    keys = (
        "schema", "id", "capability", "tool", "kind", "version", "at",
        "binding_origin", "binding_digest", "match", "basis", "call",
        "availability", "fallback",
    )
    _check_keys(record, keys, keys, "record")
    if record["schema"] != TOOL_USE_SCHEMA:
        raise _fail("tools_invalid_record", "Unsupported provenance schema; expected %s" % TOOL_USE_SCHEMA,
                    {"field": "schema"})
    if not _is_nonempty_str(record["id"]):
        raise _fail("tools_invalid_record", "record.id must be non-empty", {"field": "id"})
    if record["capability"] not in CAPABILITIES:
        raise _fail("tools_invalid_record", "record.capability is unknown", {"field": "capability"})
    if not _is_nonempty_str(record["tool"]):
        raise _fail("tools_invalid_record", "record.tool must identify the actual tool used",
                    {"field": "tool"})
    if not _is_iso(record["at"]):
        raise _fail("tools_invalid_record", "record.at must be ISO-8601 UTC", {"field": "at"})
    _check_keys(record["call"], CALL_KEYS, CALL_KEYS, "record.call")
    if not _is_nonempty_str(record["call"]["id"]) or not _is_nonempty_str(record["call"]["reference"]):
        raise _fail("tools_invalid_record", "record.call requires id and reference")
    if record["call"]["result"] not in CALL_RESULTS:
        raise _fail("tools_invalid_record", "record.call.result is invalid")
    return copy.deepcopy(record)


def record_provenance(store, ref: Optional[str], record: dict, *, lease_token: Optional[str],
                      clock: Callable[[], str], authorize: Optional[Callable[[dict], None]] = None,
                      rebuild: Optional[Callable[[dict], dict]] = None,
                      runtime_root: Optional[Path] = None) -> dict:
    """Persist a provenance record through the core TaskStore transaction.

    ``ref=None`` is a session-only record: no transaction is opened and no
    workflow metadata is created. A persistent task requires an active,
    in-progress, non-dropped task with a valid unexpired writer lease. Replaying
    the same record id with identical content is idempotent; different content
    under the same id is a conflict. Only ``capabilities[]`` and the unified
    event envelope change; the lease is deliberately not renewed by a tool log.

    ``rebuild`` lets a caller that resolved bindings outside the transaction
    re-derive the record from freshly read configuration under both locks.
    When ``rebuild`` is given, ``runtime_root`` must be the same cooperating
    runtime root binding writers use; the task lock is taken first, then the
    ``tools.lock`` (the only supported order, matching ``apply_binding``), and
    the rebuild callback runs inside that critical section. This serializes the
    commit with cooperating ``tools.yaml`` writers, so a binding change cannot
    land between resolution and commit. Noncooperating writers and differing
    runtime roots remain outside this guarantee; without ``rebuild`` the
    caller-provided snapshot is written as given.
    """
    if record is not None or rebuild is None:
        record = _validate_record(record)
    if ref is None:
        if rebuild is not None:
            raise _fail("tools_invalid_record",
                        "A session-only record is caller-held and cannot be rebuilt under lock")
        return {"persistence": "session_only", "record": record}
    if (rebuild is None) != (runtime_root is None):
        raise _fail("tools_invalid_record",
                    "rebuild and runtime_root must be provided together")
    with store.transaction():
        task_dir = store.resolve(ref)
        task = store.read(ref)
        if authorize is not None:
            authorize(task)
        if task.get("meta", {}).get("disposition"):
            raise _fail("tools_task_dropped", "Provenance cannot be recorded for a dropped task", status=3)
        if task.get("phase") != "in_progress":
            raise _fail("tools_task_not_active", "Provenance requires an in-progress task",
                        {"phase": task.get("phase")}, status=3)
        lease = task.get("lease")
        if not lease or lease.get("token") != lease_token:
            raise _fail("invalid_lease", "Provenance requires the current writer lease", status=4)
        if lease.get("expires_at", "") <= clock():
            raise _fail("expired_lease", "Lease expired before provenance was recorded", status=4)
        if rebuild is not None:
            # Task lock is already held; take the tools lock in the only
            # supported order (task -> tools, as apply_binding does) so a
            # cooperating binding writer cannot change tools.yaml between the
            # rebuild and the task commit below.
            with tools_lock(runtime_root):
                if lease.get("expires_at", "") <= clock():
                    raise _fail("expired_lease", "Lease expired before provenance was recorded", status=4)
                fresh = _validate_record(rebuild(task))
                if lease.get("expires_at", "") <= clock():
                    raise _fail("expired_lease", "Lease expired before provenance was recorded", status=4)
                existing = next((item for item in task["capabilities"]
                                 if item.get("id") == fresh["id"]), None)
                if existing is not None:
                    if content_hash(existing) == content_hash(fresh):
                        return {"persistence": "task", "task_id": task["id"],
                                "record": existing, "idempotent": True}
                    raise _fail("tools_provenance_conflict",
                                "A provenance record with this id already exists with different content",
                                {"record_id": fresh["id"]}, status=4)
                event = make_event(
                    "capability_recorded",
                    {"type": "system", "reference": fresh["call"]["reference"], "source_id": fresh["id"]},
                    {"record_id": fresh["id"], "capability": fresh["capability"], "tool": fresh["tool"]},
                    clock(),
                )
                task["capabilities"].append(fresh)
                task["events"].append(event)
                task["events"] = compact_events(task["events"])
                store.write(task_dir, task)
                return {
                    "persistence": "task",
                    "task_id": task["id"],
                    "record": fresh,
                    "event_id": event["id"],
                    "idempotent": False,
                    "rebuilt": True,
                }
        existing = next((item for item in task["capabilities"] if item.get("id") == record["id"]), None)
        if existing is not None:
            if content_hash(existing) == content_hash(record):
                return {"persistence": "task", "task_id": task["id"], "record": existing, "idempotent": True}
            raise _fail("tools_provenance_conflict",
                        "A provenance record with this id already exists with different content",
                        {"record_id": record["id"]}, status=4)
        event = make_event(
            "capability_recorded",
            {"type": "system", "reference": record["call"]["reference"], "source_id": record["id"]},
            {"record_id": record["id"], "capability": record["capability"], "tool": record["tool"]},
            clock(),
        )
        task["capabilities"].append(record)
        task["events"].append(event)
        task["events"] = compact_events(task["events"])
        store.write(task_dir, task)
        return {
            "persistence": "task",
            "task_id": task["id"],
            "record": record,
            "event_id": event["id"],
            "idempotent": False,
        }


# ---------------------------------------------------------------------------
# CLI: the single `fstar tools scan` command
# ---------------------------------------------------------------------------

def _classifier_scan():
    try:
        module = importlib.import_module("fstar.tool_classifier")
    except ModuleNotFoundError as exc:
        if exc.name == "fstar.tool_classifier":
            raise _fail("tools_classifier_unavailable",
                        "The tool classifier is not delivered yet; `fstar tools scan` cannot run",
                        {"module": "fstar.tool_classifier"})
        # The module exists but its own imports failed: never swallow this as
        # an empty successful scan.
        raise _fail("tools_classifier_import_failed",
                    "The tool classifier failed to import: %s" % exc,
                    {"module": "fstar.tool_classifier", "reason": str(exc)})
    except ImportError as exc:
        raise _fail("tools_classifier_import_failed",
                    "The tool classifier failed to import: %s" % exc,
                    {"module": "fstar.tool_classifier", "reason": str(exc)})
    scan = getattr(module, "scan_tools", None)
    if not callable(scan):
        raise _fail("tools_classifier_unavailable",
                    "The tool classifier does not expose scan_tools",
                    {"module": "fstar.tool_classifier"})
    return scan


def workflow_scan(*, project_root: Path, user_root: Path, task_ref: str,
                  extensions: Optional[list] = None) -> dict:
    """Run the tools skill's classification operation with current grants.

    Session grants belong to the caller; persistent grants are always reloaded
    from the referenced task. The independent tools scan command remains usable.
    """
    from .extensions import grants, includes
    from .store import TaskStore

    root = Path(project_root).expanduser().resolve()
    if task_ref == "session-only":
        records = extensions if extensions is not None else []
    else:
        store = TaskStore(root, user_home=Path(user_root))
        store.require_project()
        records = store.read(task_ref)["extensions"]
    if not includes(grants(records), "tool-capability", "classification"):
        raise DomainError("extension_not_authorized", "Tool scan requires classification authorization",
                          {"package": "tool-capability", "member": "classification"}, status=3)
    result = _classifier_scan()(project_root=root, user_root=Path(user_root).expanduser().resolve(),
                                host_snapshot=None)
    return _validate_scan_result(result)


def _validate_scan_result(result) -> dict:
    if not isinstance(result, dict) or result.get("schema") != SCAN_SCHEMA:
        raise _fail("tools_scan_invalid", "The classifier must return %s" % SCAN_SCHEMA,
                    {"result_type": type(result).__name__})
    missing = sorted({"detected_at", "tools", "observations", "proposals", "diagnostics"} - set(result))
    if missing:
        raise _fail("tools_scan_invalid", "The classifier result is incomplete", {"missing": missing})
    return result


def _handle_tools_scan(args) -> dict:
    project_argument = getattr(args, "project", None)
    if project_argument:
        project_root = Path(project_argument).expanduser().resolve()
    else:
        project_root = find_project_root(Path.cwd()) or Path.cwd().resolve()
    if getattr(args, "user_data_root", None):
        user_root = Path(args.user_data_root).expanduser().resolve()
    else:
        user_root = Path.home() / ".fstar"
    task_ref = getattr(args, "task_ref", None)
    entries = getattr(args, "extension", None) or []
    if task_ref is None:
        if entries:
            raise _fail("invalid_extension", "--extension requires --task-ref session-only")
    else:
        if not task_ref.strip():
            raise _fail("task_required", "--task-ref must name a task or session-only")
        if task_ref != "session-only" and entries:
            raise _fail("invalid_extension", "Persistent tasks use stored grants; omit --extension")
        from .dispatch import _require_list_or_json_entry
        records = [_require_list_or_json_entry(entry, "extension") for entry in entries]
        return workflow_scan(project_root=project_root, user_root=user_root,
                             task_ref=task_ref, extensions=records)
    scan_tools = _classifier_scan()
    result = scan_tools(project_root=project_root, user_root=user_root, host_snapshot=None)
    return _validate_scan_result(result)


def _handle_tools(args) -> dict:
    if getattr(args, "tools_command", None) != "scan":
        raise _fail("tools_command_required", "Choose a tools command: scan", status=2)
    return _handle_tools_scan(args)


def register_commands(subparsers) -> None:
    """Register the only approved user command: ``fstar tools scan``.

    The handler is attached to the ``tools`` parent parser (inherited by the
    ``scan`` child) and runs before core project/service discovery, so a scan
    can report unavailability on a not-yet-initialized project.
    """
    from .cli import OPTIONAL_HANDLER_ATTR

    tools = subparsers.add_parser("tools")
    tools.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_tools})
    tools_sub = tools.add_subparsers(dest="tools_command")
    scan = tools_sub.add_parser("scan", allow_abbrev=False)
    scan.add_argument("--task-ref", help="Workflow task reference, or session-only; omit for independent scan")
    scan.add_argument("--extension", action="append", default=[], metavar="JSON_OR_@FILE",
                      help="Session-only extension record; repeat for each grant")
    scan.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_tools})
