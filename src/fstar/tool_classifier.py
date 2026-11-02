"""Deterministic tool classifier (tool-classifier subtask).

Ownership: this module owns the L1 inventory (PATH executables, MCP server
config, host skills), the L2 classification (L2a declarative registry strong,
L2b dimension-generic probes weak-only, L2c unclassified residual), the
three-layer availability observations, and the registry data format
``fstar.tool.registry.v1``. It consumes the tool-binding public API
(``fstar.tools``) read-only and never calls ``apply_binding``.

Contract highlights (child design; parent design 3.6 / 4.2):

- ``scan_tools(*, project_root, user_root, host_snapshot=None, now=None)``
  returns ``fstar.tools.scan.v1``: proposal-only, zero writes to the project,
  user, or host roots, no network, no auto-install.
- AI never enters the classification path: every judgment is a registry
  declaration or a deterministic pattern over the tool's self-description.
- Execution safety: an external command runs only when it is a whitelisted
  read-only flag (``--version`` / ``--help``) or a registry-declared argv.
  Runs use a list argv (no shell), an empty temporary working directory, a
  restricted environment (PATH only), a timeout, and truncated output. A
  write-SQL argv is refused outright for data-access minimal calls.
- Timestamps flow exclusively from the injected ``now`` (or the real UTC clock
  when absent): ``detected_at`` and every observation ``at``.

Registry format ``fstar.tool.registry.v1`` (parsed with ``config.parse_config``;
complex values are single-line JSON flow values)::

    schema: "fstar.tool.registry.v1"
    tool: codegraph
    kind: cli
    capabilities: [{"id": "code-structure", "match": "strong", "basis": "..."}]
    version_cmd: ["--version"]
    minimal_calls: {"data-access": ["{tool}", ":memory:", "SELECT 1"]}

``version_cmd`` / ``minimal_calls`` argv tokens are literal tokens plus the
placeholders ``{tool}`` (tool identifier) and ``{path}`` (discovered absolute
executable path). A bad registry file becomes one located diagnostic and is
skipped; it never aborts the scan.

Python 3.9 standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import tools as tools_api
from .config import ConfigError, parse_config
from .models import DomainError
from .store import content_hash

REGISTRY_SCHEMA = "fstar.tool.registry.v1"
REGISTRY_KEYS = ("schema", "tool", "kind", "capabilities", "version_cmd", "minimal_calls")
MAX_OUTPUT_BYTES = 8192
PROBE_TIMEOUT_SECONDS = 5.0

WHITELIST_FLAGS = ("--version", "--help")

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")
_TOOL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION = re.compile(r"\bv?(\d+(?:\.\d+)+(?:-[0-9A-Za-z.]+)?)\b")
_WRITE_SQL = re.compile(r"\b(insert|update|delete|drop|create|alter|truncate|replace)\b", re.I)

# L2b dimension-generic probe patterns. A hit always yields match=weak with
# basis_source.kind=probe and can never promote to strong (tools.py enforces
# probe != strong at the schema level).
PROBE_PATTERNS: Dict[str, Tuple[re.Pattern, ...]] = {
    "code-structure": (
        re.compile(r"(definition|reference|callers?|impact|symbols?).{0,60}(tree|graph|lookup|index)", re.I),
        re.compile(r"(symbol|index).{0,60}(definition|reference|callers?|impact)", re.I),
    ),
    "web-research": (
        re.compile(r"search.{0,30}web", re.I),
        re.compile(r"web search", re.I),
        re.compile(r"fetch (url|page|site)", re.I),
    ),
    "knowledge-retrieval": (
        re.compile(r"search.{0,30}(knowledge|documents?|memory|notes|index)", re.I),
    ),
    "data-access": (
        re.compile(r"\bsql\b", re.I),
        re.compile(r"schema.{0,30}(query|inspect)", re.I),
        re.compile(r"database.{0,30}query", re.I),
    ),
    "test-execution": (
        re.compile(r"run tests?", re.I),
        re.compile(r"test runner", re.I),
        re.compile(r"execute tests?", re.I),
    ),
}

# Bounded PATH candidate list: registry tool IDs plus these well-known names.
# The L1 PATH inventory is driven by this list, never a full PATH walk.
PATH_CANDIDATES = (
    "codegraph", "gh", "qmd", "psql", "sqlite3", "pytest",
    "rg", "grep", "git", "jq", "curl", "node", "python3",
)

NETWORK_CAPABILITIES = ("web-research",)

# Default host locations, read-only (child design 3): the Claude Code user
# config for MCP servers and the host user skill directories. A missing
# location is not an error; it simply yields no candidates. These are host
# facts, never inside the fstar user root.
DEFAULT_MCP_CONFIG = ".claude.json"
DEFAULT_SKILL_DIRS = (".claude/skills", ".codex/skills")


def _fail(code: str, message: str, details: Optional[dict] = None) -> DomainError:
    return DomainError(code, message, details or {})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_iso(value: object) -> bool:
    if not isinstance(value, str) or not _ISO.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _resource_root(project_root: Optional[Path] = None,
                   user_root: Optional[Path] = None) -> Path:
    """The effective resources root for the package registry.

    Consumes the installer's version resolver (handoff row 2): a project/user
    pin selects the registry that pin actually installed. Without a user root
    this is the bundled copy beside the package (previous behavior); with a
    user root a broken or missing pin raises instead of silently classifying
    against the bundled registry while claiming the pinned version. Read-only.
    """
    from .installer import resources_root

    return resources_root(project_root=project_root, user_root=user_root)


def _diag(diagnostics: List[dict], code: str, message: str, **details: Any) -> None:
    diagnostics.append({"code": code, "message": message, "details": details})


# ---------------------------------------------------------------------------
# registry: fstar.tool.registry.v1
# ---------------------------------------------------------------------------

def _registry_error(message: str, path: Path, line: Optional[int]) -> DomainError:
    return _fail("tools_registry_invalid", message, {"path": str(path), "line": line})


def _validate_registry_document(document: Mapping, path: Path, reference: str) -> dict:
    keys = set(document)
    missing = sorted(set(REGISTRY_KEYS[:4]) - keys)
    unknown = sorted(keys - set(REGISTRY_KEYS))
    problems = ["missing %s" % key for key in missing] + ["unknown %s" % key for key in unknown]
    if problems:
        raise _registry_error("registry entry has %s" % ", ".join(problems), path, None)
    if document["schema"] != REGISTRY_SCHEMA:
        raise _registry_error("unsupported registry schema: %s" % document["schema"], path, None)
    tool_id = document["tool"]
    if not isinstance(tool_id, str) or not _TOOL_ID.fullmatch(tool_id):
        raise _registry_error("registry tool must be a safe non-empty identifier", path, None)
    if document["kind"] not in tools_api.TOOL_KINDS:
        raise _registry_error("registry kind must be one of %s" % "|".join(tools_api.TOOL_KINDS),
                              path, None)
    capabilities = document["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise _registry_error("registry capabilities must be a non-empty array", path, None)
    normalized: List[dict] = []
    seen = set()
    for index, entry in enumerate(capabilities):
        if not isinstance(entry, dict):
            raise _registry_error("capabilities[%d] must be an object" % index, path, None)
        required = {"id", "match", "basis"}
        if required - set(entry):
            raise _registry_error("capabilities[%d] requires id, match, basis" % index, path, None)
        capability = entry["id"]
        if capability not in tools_api.CAPABILITIES:
            raise _registry_error("capabilities[%d] has unknown capability %s"
                                  % (index, capability), path, None)
        if capability in seen:
            raise _registry_error("capabilities[%d] duplicates capability %s"
                                  % (index, capability), path, None)
        seen.add(capability)
        if entry["match"] not in tools_api.MATCH_LEVELS:
            raise _registry_error("capabilities[%d] match must be strong, weak, or none"
                                  % index, path, None)
        if not isinstance(entry["basis"], str) or not entry["basis"].strip():
            raise _registry_error("capabilities[%d] basis must be non-empty" % index, path, None)
        source = entry.get("basis_source", {"kind": "registry", "reference": reference})
        if not isinstance(source, dict) or source.get("kind") != "registry" \
                or not isinstance(source.get("reference"), str) or not source["reference"].strip():
            raise _registry_error(
                "capabilities[%d] basis_source must cite this registry file" % index, path, None)
        normalized.append({
            "id": capability,
            "match": entry["match"],
            "basis": entry["basis"],
            "basis_source": {"kind": "registry", "reference": source["reference"]},
        })
    version_cmd = document.get("version_cmd")
    if version_cmd is not None and (not isinstance(version_cmd, list)
                                    or not all(isinstance(token, str) for token in version_cmd)):
        raise _registry_error("version_cmd must be a list of strings", path, None)
    minimal_calls = document.get("minimal_calls")
    if minimal_calls is not None and not isinstance(minimal_calls, dict):
        raise _registry_error("minimal_calls must be an object", path, None)
    calls: Dict[str, List[str]] = {}
    if isinstance(minimal_calls, dict):
        for capability, argv in minimal_calls.items():
            if capability not in tools_api.CAPABILITIES:
                raise _registry_error("minimal_calls has unknown capability %s" % capability,
                                      path, None)
            if not isinstance(argv, list) or not all(isinstance(token, str) for token in argv):
                raise _registry_error("minimal_calls.%s must be a list of strings" % capability,
                                      path, None)
            calls[capability] = list(argv)
    return {
        "schema": REGISTRY_SCHEMA,
        "tool": tool_id,
        "kind": document["kind"],
        "capabilities": normalized,
        "version_cmd": list(version_cmd) if version_cmd is not None else None,
        "minimal_calls": calls,
        "reference": reference,
    }


def _load_registry_file(path: Path, reference: str) -> Tuple[Optional[dict], List[dict]]:
    """Load one registry file; failures become located diagnostics, not exceptions."""
    diagnostics: List[dict] = []
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, diagnostics
    except OSError as exc:
        _diag(diagnostics, "tools_registry_invalid", "registry file cannot be read",
              path=str(path), line=None, reason=str(exc))
        return None, diagnostics
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _diag(diagnostics, "tools_registry_invalid", "registry file must be UTF-8",
              path=str(path), line=None, reason=str(exc))
        return None, diagnostics
    try:
        document = parse_config(text, path)
    except ConfigError as exc:
        _diag(diagnostics, "tools_registry_invalid", "registry file failed to parse",
              path=str(path), line=exc.line, parser_code=exc.code, reason=exc.message)
        return None, diagnostics
    try:
        return _validate_registry_document(document, path, reference), diagnostics
    except DomainError as exc:
        _diag(diagnostics, exc.code, exc.message, **exc.details)
        return None, diagnostics


def load_registry(*, project_root: Optional[Path] = None,
                  user_root: Optional[Path] = None,
                  package_root: Optional[Path] = None) -> Tuple[Dict[str, dict], List[dict]]:
    """Load the package registry overlaid by the user registry.d, keyed by tool ID.

    A user entry with the same tool ID replaces the package entry entirely.
    Every failed file is one located diagnostic; loading never raises. The
    package registry root defaults to the resolver-selected resources root
    (project/user pin aware); an explicit ``package_root`` overrides it for
    fixtures.
    """
    user_root = Path(user_root) if user_root is not None else None
    if package_root is None:
        # Handoff row 2: the package registry follows the effective resources
        # version (project/user pin), not a hardcoded bundled path.
        package_root = _resource_root(project_root, user_root) / "registry"
    entries: Dict[str, dict] = {}
    diagnostics: List[dict] = []
    for root, reference, origin in (
        (Path(package_root), "registry/%s@v1", "package"),
        (user_root / "tools" / "registry.d" if user_root is not None else None,
         "registry.d/%s@v1", "user"),
    ):
        if root is None or not root.exists():
            continue
        try:
            paths = sorted(root.glob("*.yaml"))
        except OSError as exc:
            _diag(diagnostics, "tools_scan_source_failed", "registry directory cannot be listed",
                  source="registry", origin=origin, reason=str(exc))
            continue
        for path in paths:
            stem = path.name[:-len(".yaml")]
            entry, file_diagnostics = _load_registry_file(path, reference % stem)
            diagnostics.extend(file_diagnostics)
            if entry is not None:
                entry["origin"] = origin
                entries[entry["tool"]] = entry
    return entries, diagnostics


# ---------------------------------------------------------------------------
# safe subprocess execution
# ---------------------------------------------------------------------------

class _RunResult:
    __slots__ = ("ok", "stdout", "error", "truncated")

    def __init__(self, ok: bool, stdout: str, error: Optional[str], truncated: bool):
        self.ok = ok
        self.stdout = stdout
        self.error = error
        self.truncated = truncated


def _safe_run(argv: Sequence[str], *, timeout: float,
              cwd: Optional[Path] = None) -> _RunResult:
    """Run one argv under the execution-safety rules.

    List argv (never a shell), restricted environment (PATH only, no
    credentials), caller-supplied empty temporary cwd, timeout, truncated
    output. A timeout or non-zero exit is a failure, never a fake success.
    """
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            # Only PATH is propagated: tools installed with an
            # ``#!/usr/bin/env <interpreter>`` shebang cannot resolve their
            # interpreter without it. Nothing else (HOME, tokens, config
            # locations) leaks into the probe.
            env={"PATH": os.environ.get("PATH", "")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _RunResult(False, "", "executable not found: %s" % argv[0], False)
    except subprocess.TimeoutExpired:
        return _RunResult(False, "", "timed out after %ss" % timeout, False)
    except OSError as exc:
        return _RunResult(False, "", str(exc), False)
    truncated = len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES
    stdout = completed.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if completed.returncode != 0:
        stderr = completed.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return _RunResult(False, stdout,
                           "exit code %d: %s" % (completed.returncode, stderr.strip()), truncated)
    return _RunResult(True, stdout, None, truncated)


def _anchor_argv(argv: Sequence[str], *, tool_id: str, path: Optional[Path]) -> List[str]:
    """Anchor a declared argv on the discovered executable.

    The first token anchors the executable when it names the tool (a ``{tool}``
    or ``{path}`` placeholder, or the tool identifier itself -- the registry
    pattern documented for reuse); it is replaced by the discovered absolute
    path. When the first token is not an anchor the discovered executable is
    prepended, so a bare ``["--version"]`` declaration still runs the
    discovered binary with every declared token preserved. Any remaining
    ``{tool}``/``{path}`` placeholders in later tokens are expanded to the
    discovered path. Either way no declared token is silently dropped or
    duplicated.
    """
    if path is None or not argv:
        return list(argv)
    resolved = [str(path) if token in ("{tool}", "{path}") else token
                for token in argv]
    if resolved[0] in (tool_id, str(path)):
        resolved[0] = str(path)
        return resolved
    return [str(path)] + resolved


def _version_from_output(stdout: str) -> Optional[str]:
    match = _VERSION.search(stdout)
    if match is not None:
        return match.group(1)
    first = stdout.strip().splitlines()[0].strip() if stdout.strip() else ""
    if re.fullmatch(r"\d+(?:\.\d+)+", first):
        return first
    return None


def _is_write_sql(argv: Sequence[str]) -> bool:
    return any(_WRITE_SQL.search(token) for token in argv)


def _run_declared(argv: Sequence[str], *, tool_id: str, path: Optional[Path],
                  capability: Optional[str], diagnostics: List[dict]) -> Optional[_RunResult]:
    """Run a registry-declared argv; None when the argv is refused for safety."""
    if capability == "data-access" and _is_write_sql(argv):
        _diag(diagnostics, "tools_scan_probe_refused",
              "registry-declared minimal call contains write SQL; refused",
              tool=tool_id, capability=capability, argv=list(argv))
        return None
    with tempfile.TemporaryDirectory(prefix="fstar-probe-") as scratch:
        return _safe_run(argv, timeout=PROBE_TIMEOUT_SECONDS, cwd=Path(scratch))


def _note_probe_result(result: _RunResult, *, tool_id: str, argv: Sequence[str],
                       diagnostics: List[dict]) -> None:
    if result.truncated:
        _diag(diagnostics, "tools_scan_probe_truncated",
              "probe output truncated to %d bytes" % MAX_OUTPUT_BYTES,
              tool=tool_id, argv=list(argv))
    if not result.ok:
        _diag(diagnostics, "tools_scan_probe_failed", "probe failed",
              tool=tool_id, argv=list(argv), reason=result.error)


# ---------------------------------------------------------------------------
# L1 inventory
# ---------------------------------------------------------------------------

class _Candidate:
    __slots__ = ("tool", "kind", "path", "origin", "version", "self_description",
                 "help_ok", "help_error")

    def __init__(self, tool: str, kind: str, path: Optional[Path], origin: str,
                 self_description: str = ""):
        self.tool = tool
        self.kind = kind
        self.path = path
        self.origin = origin
        self.version: Optional[str] = None
        self.self_description = self_description
        self.help_ok: Optional[bool] = None
        self.help_error: Optional[str] = None


def _frontmatter(text: str) -> Tuple[Dict[str, str], bool]:
    """Parse simple ``key: value`` SKILL.md frontmatter; returns (fields, ok)."""
    if not text.startswith("---\n"):
        return {}, False
    fields: Dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            return fields, True
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[match.group(1)] = value
    return fields, False


def _scan_path_candidates(registry: Mapping[str, dict], diagnostics: List[dict],
                          extra_names: Optional[Sequence[str]] = None) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    seen = set()
    names = list(registry.keys()) + [name for name in PATH_CANDIDATES if name not in registry]
    for name in extra_names or ():
        if name not in names:
            names.append(name)
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        try:
            location = shutil.which(name)
        except OSError as exc:
            _diag(diagnostics, "tools_scan_source_failed", "PATH lookup failed for %s" % name,
                  source="path", reason=str(exc))
            continue
        if location is None:
            continue
        candidates.append(_Candidate(name, "cli", Path(location), "path"))
    return candidates


def _scan_mcp_candidates(host_snapshot: Optional[Mapping],
                         diagnostics: List[dict],
                         mcp_config_path: Optional[Path]) -> List[_Candidate]:
    servers: Dict[str, str] = {}
    if host_snapshot is not None and isinstance(host_snapshot.get("mcp_servers"), dict):
        origin = "mcp:host_snapshot"
        for name, entry in host_snapshot["mcp_servers"].items():
            if not isinstance(name, str) or not name or not isinstance(entry, dict):
                continue
            parts = []
            if isinstance(entry.get("description"), str):
                parts.append(entry["description"])
            tools_value = entry.get("tools")
            if isinstance(tools_value, list):
                parts.extend(item.get("description") for item in tools_value
                             if isinstance(item, dict)
                             and isinstance(item.get("description"), str))
            servers[name] = " ".join(part for part in parts if part).strip()
    elif host_snapshot is not None and host_snapshot.get("mcp_servers") is not None:
        _diag(diagnostics, "tools_scan_source_failed",
              "host_snapshot mcp_servers has an unrecognized shape; skipped",
              source="mcp", reason="unrecognized shape")
        return []
    else:
        origin = "mcp:host_config"
        config_path = mcp_config_path if mcp_config_path is not None \
            else Path.home() / DEFAULT_MCP_CONFIG
        try:
            if config_path.is_file():
                document = json.loads(config_path.read_text(encoding="utf-8"))
                mcp = document.get("mcpServers") if isinstance(document, dict) else None
                if isinstance(mcp, dict):
                    for name, entry in mcp.items():
                        if not isinstance(name, str) or not name:
                            continue
                        description = ""
                        if isinstance(entry, dict) and isinstance(entry.get("description"), str):
                            description = entry["description"]
                        servers[name] = description
                elif mcp is not None:
                    _diag(diagnostics, "tools_scan_source_failed",
                          "mcpServers has an unrecognized shape; skipped",
                          source="mcp", reason="unrecognized shape")
        except (OSError, ValueError) as exc:
            _diag(diagnostics, "tools_scan_source_failed", "MCP config could not be parsed",
                  source="mcp", reason=str(exc))
    return [
        _Candidate(name, "mcp", None, origin, self_description=description)
        for name, description in sorted(servers.items())
    ]


def _scan_skill_candidates(skill_dirs: Sequence[Path],
                          diagnostics: List[dict]) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    for root in skill_dirs:
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError as exc:
            _diag(diagnostics, "tools_scan_source_failed", "skill directory cannot be listed",
                  source="skill", reason=str(exc))
            continue
        for directory in entries:
            skill_file = directory / "SKILL.md"
            try:
                if not skill_file.is_file():
                    continue
                text = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                _diag(diagnostics, "tools_scan_source_failed", "SKILL.md cannot be read",
                      source="skill", reason=str(exc))
                continue
            fields, ok = _frontmatter(text)
            if not ok or not fields.get("name"):
                _diag(diagnostics, "tools_scan_source_failed",
                      "SKILL.md frontmatter is missing or unparsable",
                      source="skill", reason="frontmatter")
                continue
            name = fields["name"]
            if name.startswith("fstar-"):
                continue  # fstar's own 12 skills are never tool candidates
            candidates.append(_Candidate(name, "skill", None, "skill",
                                         self_description=fields.get("description", "")))
    return candidates


# ---------------------------------------------------------------------------
# L2 classification
# ---------------------------------------------------------------------------

def _probe_hits(self_description: str) -> List[str]:
    normalized = " ".join(self_description.split())
    hits = []
    for capability in tools_api.CAPABILITIES:
        for pattern in PROBE_PATTERNS[capability]:
            if pattern.search(normalized):
                hits.append(capability)
                break
    return hits


def _classify(candidate: _Candidate, registry: Mapping[str, dict]) -> Tuple[List[dict], str]:
    """Return (capabilities, tier) with tier registry | probe | unclassified."""
    entry = registry.get(candidate.tool)
    if entry is not None:
        return [dict(item) for item in entry["capabilities"]], "registry"
    hits = _probe_hits(candidate.self_description or "")
    if hits:
        return [
            {
                "id": capability,
                "match": "weak",
                "basis": "dimension probe matched the tool self-description",
                "basis_source": {"kind": "probe",
                                 "reference": "probes/%s#pattern" % capability},
            }
            for capability in hits
        ], "probe"
    excerpt = " ".join((candidate.self_description or "").split())[:200] \
        or "no self-description available"
    # Residual candidate: no claim in any dimension, listed for the user.
    return [
        {
            "id": capability,
            "match": "none",
            "basis": excerpt,
            "basis_source": {"kind": "unclassified",
                             "reference": "probes/unclassified#residual"},
        }
        for capability in tools_api.CAPABILITIES
    ], "unclassified"


# ---------------------------------------------------------------------------
# three-layer observations
# ---------------------------------------------------------------------------

def _observation(tool: str, capability: str, layer: str, status: str, at: str,
                 host: str, *, evidence_ref: Optional[str] = None,
                 reason: Optional[str] = None,
                 call_id: Optional[str] = None) -> dict:
    return {
        "tool": tool,
        "capability": capability,
        "layer": layer,
        "status": status,
        "at": at,
        "scope": {"project": None, "host": host, "session": None},
        "evidence_ref": evidence_ref,
        "reason": reason,
        "call_id": call_id,
    }


def _host_fact(host_snapshot: Optional[Mapping], tool: str, capability: str,
               layer: str, diagnostics: List[dict]) -> Optional[dict]:
    """Return a host-supplied availability fact {status, reason, ...} or None.

    Unrecognized or incomplete facts are a located diagnostic and are skipped,
    never trusted and never fatal: a verified fact must carry evidence, and a
    verified minimal call must carry the call id that proved it.
    """
    if not isinstance(host_snapshot, dict):
        return None
    observations = host_snapshot.get("observations")
    if not isinstance(observations, list):
        return None
    for item in observations:
        if not isinstance(item, dict):
            continue
        if not (item.get("tool") == tool and item.get("capability") == capability
                and item.get("layer") == layer
                and item.get("status") in tools_api.LAYER_STATUSES):
            continue
        status = item["status"]
        reason = item.get("reason") if isinstance(item.get("reason"), str) else None
        evidence_ref = item.get("evidence_ref") \
            if isinstance(item.get("evidence_ref"), str) else None
        call_id = item.get("call_id") if isinstance(item.get("call_id"), str) else None
        complete = True
        if status == "verified":
            complete = bool(evidence_ref) and (layer != "minimal_call" or bool(call_id))
        elif status == "failed":
            complete = bool(reason)
        if not complete:
            _diag(diagnostics, "tools_scan_host_fact_invalid",
                  "host-supplied availability fact is incomplete; ignored",
                  tool=tool, capability=capability, layer=layer, status=status)
            continue
        return {
            "status": status,
            "reason": reason,
            "evidence_ref": evidence_ref,
            "call_id": call_id,
        }
    return None


def _observations_for(candidate: _Candidate, capabilities: Sequence[dict], at: str,
                      host_snapshot: Optional[Mapping], registry_entry: Optional[dict],
                      diagnostics: List[dict]) -> List[dict]:
    host = candidate.origin
    host_backed = candidate.path is None  # mcp/skill candidates
    observations: List[dict] = []
    for entry in capabilities:
        capability = entry["id"]
        # discoverable: pure filesystem / host-config fact, always known here.
        # The evidence ref names the actual source: a PATH lookup, a host
        # snapshot fact, the host client config file, or a skill directory --
        # never a connection or an RPC.
        if candidate.path is not None:
            evidence = "which:%s" % candidate.tool
        else:
            prefix = {
                "mcp:host_snapshot": "host-snapshot",
                "mcp:host_config": "host-config",
                "skill": "skill-dir",
            }.get(host, "host")
            evidence = "%s:%s" % (prefix, candidate.tool)
        observations.append(_observation(candidate.tool, capability, "discoverable",
                                         "verified", at, host, evidence_ref=evidence))
        # client_loaded
        if host_backed:
            fact = _host_fact(host_snapshot, candidate.tool, capability,
                              "client_loaded", diagnostics)
            if fact is not None:
                observations.append(_observation(
                    candidate.tool, capability, "client_loaded", fact["status"], at, host,
                    evidence_ref=fact["evidence_ref"], reason=fact["reason"],
                    call_id=fact["call_id"]))
            else:
                observations.append(_observation(
                    candidate.tool, capability, "client_loaded", "unknown", at, host,
                    reason="host adapter not available"))
        elif candidate.help_ok:
            observations.append(_observation(
                candidate.tool, capability, "client_loaded", "verified", at, host,
                evidence_ref="argv:%s --help" % candidate.tool))
        else:
            observations.append(_observation(
                candidate.tool, capability, "client_loaded", "failed", at, host,
                reason=candidate.help_error or "--help did not complete successfully"))
        # minimal_call
        fact = _host_fact(host_snapshot, candidate.tool, capability,
                          "minimal_call", diagnostics)
        if fact is not None:
            observations.append(_observation(
                candidate.tool, capability, "minimal_call", fact["status"], at, host,
                evidence_ref=fact["evidence_ref"], reason=fact["reason"],
                call_id=fact["call_id"]))
            continue
        if capability in NETWORK_CAPABILITIES:
            # No network call is ever made by the scan; report honestly.
            _diag(diagnostics, "tools_scan_network_unverified",
                  "network capability is host-supplied only; reported unknown",
                  tool=candidate.tool, capability=capability)
            observations.append(_observation(
                candidate.tool, capability, "minimal_call", "unknown", at, host,
                reason="offline scan; network capability requires a host-supplied fact"))
            continue
        if host_backed:
            observations.append(_observation(
                candidate.tool, capability, "minimal_call", "unknown", at, host,
                reason="host adapter not available"))
            continue
        declared = registry_entry["minimal_calls"].get(capability) \
            if registry_entry is not None else None
        if declared:
            argv = _anchor_argv(declared, tool_id=candidate.tool, path=candidate.path)
            result = _run_declared(argv, tool_id=candidate.tool, path=candidate.path,
                                    capability=capability, diagnostics=diagnostics)
            if result is None:
                observations.append(_observation(
                    candidate.tool, capability, "minimal_call", "unknown", at, host,
                    reason="registry-declared minimal call was refused for safety"))
                continue
            _note_probe_result(result, tool_id=candidate.tool, argv=argv,
                               diagnostics=diagnostics)
            if result.ok:
                call_id = content_hash(
                    {"tool": candidate.tool, "capability": capability, "argv": argv})
                observations.append(_observation(
                    candidate.tool, capability, "minimal_call", "verified", at, host,
                    evidence_ref="argv:%s" % " ".join(argv), call_id=call_id))
            else:
                observations.append(_observation(
                    candidate.tool, capability, "minimal_call", "failed", at, host,
                    reason=result.error or "registry-declared minimal call failed"))
            continue
        observations.append(_observation(
            candidate.tool, capability, "minimal_call", "unknown", at, host,
            reason="no safe minimal call declared for this tool"))
    return observations


# ---------------------------------------------------------------------------
# proposals (strong registry matches where the target layer is unbound)
# ---------------------------------------------------------------------------

def _build_proposals(classified: Sequence[Tuple[_Candidate, List[dict], str, Optional[dict]]],
                     *, project_root: Path, user_root: Path) -> Tuple[List[dict], List[dict]]:
    proposals: List[dict] = []
    diagnostics: List[dict] = []
    project_tools = project_root / ".fstar" / "tools.yaml"
    user_tools = user_root / "tools.yaml"
    initialized = (project_root / ".fstar" / ".schema-version").is_file()
    target = "project" if initialized else "user"
    target_path = project_tools if target == "project" else user_tools
    try:
        loaded = tools_api.load_tools(target_path)
    except DomainError as exc:
        _diag(diagnostics, "tools_scan_layer_unreadable",
              "%s tools.yaml could not be read; no proposals" % target,
              target=target, path=str(target_path), reason=exc.message)
        return proposals, diagnostics
    document = loaded["document"] if loaded["state"] == "loaded" else None
    bound: Dict[str, Optional[str]] = {}
    if document is not None:
        for capability, binding in document.get("bindings", {}).items():
            bound[capability] = binding.get("tool") if isinstance(binding, dict) else None
    for candidate, capabilities, tier, _entry in classified:
        if tier != "registry":
            continue
        strong = [item for item in capabilities if item["match"] == "strong"]
        # A present key is a user decision: an explicit ``tool: null`` means
        # "unbound on purpose", so it must not be re-proposed on every scan.
        changes = {item["id"]: candidate.tool for item in strong
                   if item["id"] not in bound}
        if not changes:
            continue
        snapshot = {
            "tool": candidate.tool,
            "kind": candidate.kind,
            "version": candidate.version,
            "capabilities": [dict(item) for item in capabilities],
        }
        try:
            proposal = tools_api.build_binding_proposal(
                target=target, loaded=loaded, changes=changes,
                reason="registry-declared strong match for %s" % ", ".join(sorted(changes)),
                tools={candidate.tool: snapshot},
            )
        except DomainError as exc:
            _diag(diagnostics, "tools_scan_proposal_failed", "proposal could not be built",
                  tool=candidate.tool, reason=exc.message)
            continue
        proposals.append(proposal)
    return proposals, diagnostics


# ---------------------------------------------------------------------------
# output self-checks (public API only)
# ---------------------------------------------------------------------------

def _check_observations(observations: Sequence[dict]) -> None:
    required = {"tool", "capability", "layer", "status", "at", "scope"}
    allowed = required | {"evidence_ref", "reason", "call_id"}
    for observation in observations:
        missing = sorted(required - set(observation))
        unknown = sorted(set(observation) - allowed)
        if missing or unknown:
            raise _fail("tools_scan_invalid", "invalid observation fields",
                        {"missing": missing, "unknown": unknown})
        if observation["capability"] not in tools_api.CAPABILITIES \
                or observation["layer"] not in tools_api.LAYERS \
                or observation["status"] not in tools_api.LAYER_STATUSES:
            raise _fail("tools_scan_invalid", "invalid observation enums", {})
        if not _is_iso(observation["at"]):
            raise _fail("tools_scan_invalid", "observation.at must be ISO-8601 UTC", {})
        scope = observation["scope"]
        if not isinstance(scope, dict) or set(scope) != {"project", "host", "session"} \
                or any(value is not None and not isinstance(value, str)
                       for value in scope.values()):
            raise _fail("tools_scan_invalid", "invalid observation scope", {})
        if observation["status"] == "verified":
            if not observation.get("evidence_ref"):
                raise _fail("tools_scan_invalid", "verified requires evidence_ref", {})
            if observation["layer"] == "minimal_call" and not observation.get("call_id"):
                raise _fail("tools_scan_invalid",
                            "verified minimal_call requires call_id", {})
        if observation["status"] == "failed" and not observation.get("reason"):
            raise _fail("tools_scan_invalid", "failed requires reason", {})


# ---------------------------------------------------------------------------
# scan entry point
# ---------------------------------------------------------------------------

def scan_tools(*, project_root: Path, user_root: Path, host_snapshot: Optional[dict] = None,
               now: Optional[str] = None, skill_dirs: Optional[Sequence[Path]] = None,
               package_registry_root: Optional[Path] = None,
               mcp_config_path: Optional[Path] = None,
               path_candidates: Optional[Sequence[str]] = None) -> dict:
    """Run the deterministic three-layer scan and return ``fstar.tools.scan.v1``.

    Read-only everywhere: no binding writes, no tools.yaml creation, no index
    or install, no network call. External commands run only as whitelisted
    read-only flags (``--version`` / ``--help``) or registry-declared argv, in
    an empty temporary cwd with a restricted environment and a timeout.
    Determinism: with the same PATH snapshot, registry, host_snapshot, and an
    injected ``now``, the output is identical across runs; timestamps
    (``detected_at`` and observation ``at`` fields) follow the injected clock.
    """
    if now is not None and not _is_iso(now):
        raise _fail("tools_scan_invalid", "now must be an ISO-8601 UTC timestamp")
    detected_at = now if now is not None else _utc_now()
    project_root = Path(project_root).expanduser().resolve()
    user_root = Path(user_root).expanduser().resolve()

    diagnostics: List[dict] = []
    registry, registry_diagnostics = load_registry(
        project_root=project_root, user_root=user_root, package_root=package_registry_root)
    diagnostics.extend(registry_diagnostics)
    if not registry:
        _diag(diagnostics, "tools_registry_empty",
              "no registry entries loaded; all candidates fall to probes or residual",
              package_root=str(package_registry_root) if package_registry_root is not None else None)

    if skill_dirs is None:
        skill_dirs = tuple(Path.home() / relative for relative in DEFAULT_SKILL_DIRS)
    path_candidates_found = _scan_path_candidates(
        registry, diagnostics, extra_names=path_candidates)
    mcp_candidates = _scan_mcp_candidates(host_snapshot, diagnostics,
                                          mcp_config_path)
    skill_candidates = _scan_skill_candidates(skill_dirs, diagnostics)
    for source, found in (("path", len(path_candidates_found)), ("mcp", len(mcp_candidates)),
                          ("skill", len(skill_candidates))):
        if not found:
            _diag(diagnostics, "tools_scan_source_empty",
                  "no candidates found from %s" % source, source=source)

    # Deduplicate by tool ID across sources; conflicts become diagnostics and
    # PATH wins over MCP, which wins over skills. Candidate kinds for PATH
    # entries are "cli"; the origin field carries the source.
    priority = {"path": 0, "mcp:host_snapshot": 1, "mcp:host_config": 1, "skill": 2}
    by_id: Dict[str, _Candidate] = {}
    for candidate in path_candidates_found + mcp_candidates + skill_candidates:
        existing = by_id.get(candidate.tool)
        if existing is None:
            by_id[candidate.tool] = candidate
            continue
        if existing.origin != candidate.origin:
            _diag(diagnostics, "tools_scan_duplicate_tool",
                  "tool ID %s found in multiple sources" % candidate.tool,
                  tool=candidate.tool, sources=[existing.origin, candidate.origin])
        if priority.get(existing.origin, 2) > priority.get(candidate.origin, 2):
            by_id[candidate.tool] = candidate

    tools_list: List[dict] = []
    observations: List[dict] = []
    classified: List[Tuple[_Candidate, List[dict], str, Optional[dict]]] = []
    for candidate in sorted(by_id.values(), key=lambda item: item.tool):
        registry_entry = registry.get(candidate.tool)
        # client_loaded probe and self-description for PATH candidates: one
        # whitelisted --help run per candidate, never per capability.
        if candidate.path is not None:
            argv = [str(candidate.path), "--help"]
            result = _run_declared(argv, tool_id=candidate.tool, path=candidate.path,
                                    capability=None, diagnostics=diagnostics)
            candidate.help_ok = result.ok
            candidate.help_error = result.error
            _note_probe_result(result, tool_id=candidate.tool, argv=argv,
                               diagnostics=diagnostics)
            if result.ok and not candidate.self_description:
                candidate.self_description = result.stdout
        # Version: only via the registry-declared safe command (TC-02). The
        # declared argv anchors on the discovered executable: a leading tool
        # anchor ({tool}/{path}/tool id) is replaced by it, otherwise it is
        # prepended, so no declared token is dropped or duplicated.
        if candidate.path is not None and registry_entry is not None \
                and registry_entry["version_cmd"]:
            argv = _anchor_argv(registry_entry["version_cmd"], tool_id=candidate.tool,
                                path=candidate.path)
            result = _run_declared(argv, tool_id=candidate.tool, path=candidate.path,
                                   capability=None, diagnostics=diagnostics)
            _note_probe_result(result, tool_id=candidate.tool, argv=argv,
                               diagnostics=diagnostics)
            if result.ok:
                candidate.version = _version_from_output(result.stdout)
        capabilities, tier = _classify(candidate, registry)
        observations.extend(_observations_for(
            candidate, capabilities, detected_at, host_snapshot, registry_entry, diagnostics))
        tools_list.append({
            "tool": candidate.tool,
            "kind": candidate.kind,
            "version": candidate.version,
            "capabilities": capabilities,
        })
        classified.append((candidate, capabilities, tier, registry_entry))

    proposals, proposal_diagnostics = _build_proposals(
        classified, project_root=project_root, user_root=user_root)
    diagnostics.extend(proposal_diagnostics)

    # Self-check the emitted shapes with the delivered public validator.
    try:
        tools_api.validate_tools({
            "schema": tools_api.TOOLS_SCHEMA, "detected_at": None,
            "tools": tools_list, "bindings": {}, "history": [],
        })
    except DomainError as exc:
        raise _fail("tools_scan_invalid", "classifier produced an invalid tool snapshot",
                    {"reason": exc.message, "details": exc.details})
    _check_observations(observations)

    return {
        "schema": tools_api.SCAN_SCHEMA,
        "detected_at": detected_at,
        "tools": tools_list,
        "observations": observations,
        "proposals": proposals,
        "diagnostics": diagnostics,
    }
