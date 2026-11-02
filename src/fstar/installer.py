"""fstar installer (PI-I3..I8).

Owns npm-package composition, user-level resource caches with version
resolution, precise file/settings ownership with transactional
install/update/uninstall, explicit migration, doctor diagnostics, and the
entry index. Registered on the CLI through ``register_commands`` /
``OPTIONAL_HANDLER_ATTR`` (cli.py owns the one-line module-list wiring).

Honesty rules baked into this module:

- ``resolve_resources`` is read-only; it never creates a cache and never
  silently falls back to the bundled version when an explicit version is
  requested (PI-04).
- Plans are pure; ``apply_plan`` re-verifies every hash under the user-root
  lock before writing (PI-05).
- Uninstall only removes entries that still match the recorded baseline;
  user-modified and user-owned files are kept and reported (PI-03).
- ``doctor`` is read-only and reports ``observed``/``estimated``/``unknown``
  listing evidence separately (PI-06).
- ``migrate`` only supports implemented chains; a same-schema request is an
  explicit no-op and everything else is ``unsupported`` (PI-05).
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import shutil
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .config import ConfigError, load_config
from .content import ROLES, SKILLS, validate_resources
from .models import DomainError
from .runtime import registration

MANIFEST_SCHEMA = "fstar.install.v1"
ENTRY_INDEX_SCHEMA = "fstar.entries.v1"
BUNDLE_SCHEMA = "fstar.package-assets.v1"
SUPPORTED_HOSTS = ("claude", "codex")
HOOK_SEMANTICS = ("session-context", "worker-context", "worker-result", "doc-change")
CONFLICT_POLICIES = ("keep", "overwrite", "new")
# Capability/resource invariants reported by doctor (parent design §4.4).
EXPECTED_COUNTS = {
    "skills": 12,
    "roles": 4,
    "hooks": 4,
    "templates": 11,
    "capabilities": 5,
}
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(value) -> str:
    return _sha256_bytes(_canonical(value).encode("utf-8"))


@dataclass(frozen=True)
class Roots:
    """Explicitly injected roots; never a global monkeypatch."""

    user_root: Path
    runtime_root: Path
    project_root: Optional[Path] = None
    host_roots: Dict[str, Path] = field(default_factory=dict)
    bundle_root: Optional[Path] = None

    def resolved(self) -> "Roots":
        return Roots(
            user_root=self.user_root.expanduser().resolve(),
            runtime_root=self.runtime_root.expanduser().resolve(),
            project_root=self.project_root.expanduser().resolve() if self.project_root else None,
            host_roots={name: root.expanduser().resolve() for name, root in self.host_roots.items()},
            bundle_root=self.bundle_root.expanduser().resolve() if self.bundle_root else None,
        )


@dataclass(frozen=True)
class ResourceSelection:
    version: str
    root: Optional[Path]
    source: str
    manifest_digest: Optional[str]
    problems: Tuple[dict, ...] = ()


# ---------------------------------------------------------------------------
# Roots resolution


def roots_from_args(args, *, bundle_root: Optional[Path] = None) -> Roots:
    """Build the roots for one CLI invocation.

    Defaults are the product's real user-level locations (``~/.fstar`` and
    ``~/.claude``); ``--user-data-root``/``--runtime-root``/``--host-root``
    override them explicitly for fixtures and advanced targets. Every test
    and every operation in this task passes explicit temporary roots.
    """
    user = getattr(args, "user_data_root", None)
    runtime = getattr(args, "runtime_root", None)
    user_root = Path(user) if user else Path.home() / ".fstar"
    runtime_root = Path(runtime) if runtime else user_root / "runtime"
    project = getattr(args, "project", None)
    host_roots: Dict[str, Path] = {}
    for pair in getattr(args, "host_root", None) or []:
        if "=" not in pair:
            raise DomainError("invalid_host_root", "--host-root expects HOST=PATH", {"value": pair})
        name, _, value = pair.partition("=")
        if name not in SUPPORTED_HOSTS:
            raise DomainError("unknown_host", "Unknown host", {"host": name, "hosts": list(SUPPORTED_HOSTS)})
        host_roots[name] = Path(value)
    if "claude" not in host_roots:
        host_roots["claude"] = Path.home() / ".claude"
    return Roots(
        user_root=user_root,
        runtime_root=runtime_root,
        project_root=Path(project) if project else None,
        host_roots=host_roots,
        bundle_root=bundle_root,
    )


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_bundle_manifest(bundle_root: Optional[Path] = None) -> dict:
    path = (bundle_root or _package_root()) / "resources" / "package-assets.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainError("bundle_manifest_unavailable", "Cannot read package-assets.json",
                          {"path": str(path), "reason": str(exc)})
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise DomainError("bundle_manifest_unavailable", "Unsupported package-assets schema", {"path": str(path)})
    return manifest


# ---------------------------------------------------------------------------
# PI-I4 resource version resolution (read-only)


def resolve_resources(*, project_root: Optional[Path] = None, user_root: Path,
                      requested_version: Optional[str] = None,
                      bundle_root: Optional[Path] = None,
                      strict: bool = True) -> ResourceSelection:
    """Resolve the effective resources version/root. Pure read.

    Precedence (child design §5): explicit request > merged config
    ``resources.version`` (project layer wins) > user ``version`` file >
    bundled version. Only exact version ids are accepted; ``latest`` or a
    range is a hard error, never a silent latest/network resolution.

    The user cache is preferred over the bundled copy once it exists: the
    cache is what the installation actually put in place. Its content is
    checked against the recorded install baseline, so a modified or missing
    cache file is reported instead of being silently served.

    ``strict=False`` (used by doctor) returns the selection together with
    the detected problems instead of raising, so doctor can report them.
    """
    if requested_version is not None and not _valid_version(requested_version):
        raise DomainError("resource_version_invalid", "Requested resource version is not a valid version id",
                          {"version": requested_version})
    bundle = load_bundle_manifest(bundle_root)
    bundled_version = str(bundle.get("resource_version", ""))
    version = requested_version
    source = "explicit"
    problems: List[dict] = []
    if version is None:
        try:
            version, source = _config_requested_version(project_root, user_root)
        except DomainError as exc:
            if strict:
                raise
            problems.append({"code": exc.code, "message": exc.message, "details": exc.details})
            version, source = None, "config"
    if version is None:
        try:
            user_version = _read_version_file(user_root)
        except DomainError as exc:
            if strict:
                raise
            problems.append({"code": exc.code, "message": exc.message, "details": exc.details})
            user_version = None
        if user_version:
            version, source = user_version, "user"
    if version is None:
        version, source = bundled_version, "bundled"
    cache_root = user_root / "resources" / version
    cache_usable = cache_root.is_dir() and not cache_root.is_symlink()
    if not cache_usable and (cache_root.is_symlink() or cache_root.exists()):
        error = DomainError("resource_integrity", "Resource cache is not a regular directory",
                            {"version": version, "cache_root": str(cache_root)})
        if strict:
            raise error
        problems.append({"code": error.code, "message": error.message, "details": error.details})
    if cache_usable:
        root = cache_root
        baseline = _load_cache_manifest(cache_root)
        if baseline is None:
            problems.append({"code": "resource_integrity",
                             "message": "Resource cache has no baseline manifest",
                             "details": {"version": version, "cache_root": str(cache_root)}})
        else:
            problems.extend(_verify_cache(cache_root, baseline))
    elif version == bundled_version:
        root = (bundle_root or _package_root()) / "resources"
        for problem in _verify_bundle_problems(bundle, bundle_root):
            problems.append(problem)
    else:
        error = DomainError("resource_version_unavailable",
                             "Requested resource version is not installed",
                             {"version": version, "cache_root": str(cache_root)})
        if strict:
            raise error
        problems.append({"code": error.code, "message": error.message, "details": error.details})
        root = (bundle_root or _package_root()) / "resources"
    selected_manifest = _load_cache_manifest(cache_root) if root == cache_root else bundle
    selection = ResourceSelection(version=version, root=root, source=source,
                                  manifest_digest=_manifest_digest(selected_manifest or bundle))
    if strict and problems:
        first = problems[0]
        raise DomainError(first["code"], first["message"], first.get("details"))
    return _with_problems(selection, problems)


def _with_problems(selection: ResourceSelection, problems: List[dict]) -> ResourceSelection:
    if not problems:
        return selection
    return ResourceSelection(version=selection.version, root=selection.root, source=selection.source,
                             manifest_digest=selection.manifest_digest,
                             problems=tuple(problems))


def resources_root(*, project_root: Optional[Path] = None, user_root: Optional[Path],
                   requested_version: Optional[str] = None,
                   bundle_root: Optional[Path] = None) -> Path:
    """The effective resources root for content consumers. Read-only.

    Convenience wrapper over ``resolve_resources`` with identical precedence
    and integrity rules (design §5): a consumer without a user root gets the
    bundled copy; with a user root the selection is exact and honest — a
    broken, incomplete, or missing pin raises instead of silently serving the
    bundled content while claiming the pinned version. Never creates a cache.
    """
    if user_root is None:
        return (bundle_root or _package_root()) / "resources"
    return resolve_resources(project_root=project_root, user_root=user_root,
                             requested_version=requested_version,
                             bundle_root=bundle_root).root


def _valid_version(version: str) -> bool:
    if not isinstance(version, str) or not version:
        return False
    if version.lower() in ("latest", "newest", "*", "head", "main"):
        return False
    return bool(VERSION_PATTERN.fullmatch(version))


def _config_requested_version(project_root: Optional[Path], user_root: Path) -> Tuple[Optional[str], str]:
    try:
        result = load_config(project_root, user_root)
    except ConfigError as exc:
        # A malformed config is an error, not a silent fallback to a lower
        # layer: the user asked for a specific version and it cannot be read.
        raise DomainError("config_invalid", "Cannot read configuration for resource version selection",
                          {"path": str(exc.path) if exc.path else None, "reason": exc.message})
    values = result.values.get("resources")
    if not isinstance(values, dict):
        return None, "config"
    version = values.get("version")
    if version is None:
        return None, "config"
    if not _valid_version(version):
        raise DomainError("resource_version_invalid", "Config resources.version must be an exact version id",
                          {"version": version})
    return version, "config"


def _read_version_file(user_root: Path) -> Optional[str]:
    path = user_root / "version"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if not _valid_version(text):
        raise DomainError("resource_version_invalid", "User version file holds an invalid version id",
                          {"version": text})
    return text


def _manifest_digest(manifest: Mapping) -> Optional[str]:
    return _sha256_bytes(_canonical(manifest).encode("utf-8"))


def _verify_bundle_problems(bundle: Mapping, bundle_root: Optional[Path]) -> List[dict]:
    """Report bundled resource files that do not match their declared hashes.

    Only resource files are version-controlled content; program files ship
    as package content and are verified by the package manager, not by the
    resource baseline.
    """
    root = (bundle_root or _package_root()).resolve()
    problems = []
    for record in bundle.get("files", []):
        if record.get("kind") != "resource":
            continue
        relative = record.get("source", "")
        target = root / relative
        try:
            if _sha256(target) != record.get("sha256"):
                problems.append(relative)
        except OSError:
            problems.append(relative)
    if problems:
        return [{"code": "resource_integrity",
                 "message": "Bundled package files do not match package-assets.json",
                 "details": {"files": problems[:10]}}]
    return []


def _verify_bundle(bundle: Mapping, bundle_root: Optional[Path]) -> None:
    problems = _verify_bundle_problems(bundle, bundle_root)
    if problems:
        raise DomainError(problems[0]["code"], problems[0]["message"], problems[0].get("details"))


def _load_cache_manifest(cache_root: Path) -> Optional[dict]:
    path = cache_root / "manifest.json"
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(baseline, dict) or baseline.get("schema") != BUNDLE_SCHEMA:
        return None
    return baseline


def _verify_cache(cache_root: Path, baseline: Mapping) -> List[dict]:
    """Check cached files against the baseline recorded at install time."""
    problems = []
    incomplete = []
    if (baseline.get("resource_version") != cache_root.name
            or not isinstance(baseline.get("files"), list) or not baseline["files"]):
        return [{"code": "resource_integrity", "message": "Invalid cache manifest identity or file list"}]
    if 1 not in baseline.get("supported_data_schemas", [1]):
        return [{"code": "resource_incompatible", "message": "Cache does not support data schema 1"}]
    for record in baseline.get("files", []):
        if not isinstance(record, dict):
            return [{"code": "resource_integrity", "message": "Invalid cache file record"}]
        try:
            _safe_relative(record.get("source", ""), "cache file")
            _reject_symlink_ancestors(cache_root / record["source"], cache_root)
        except (DomainError, TypeError):
            return [{"code": "resource_integrity", "message": "Unsafe cache file path"}]
        relative = record.get("source", "")
        if not record.get("installed", True):
            incomplete.append(relative)
            continue
        target = cache_root / relative
        try:
            matches = _sha256(target) == record.get("sha256")
        except OSError:
            matches = False
        if not matches:
            problems.append({"code": "resource_integrity",
                             "message": "Resource cache content does not match its baseline",
                             "details": {"version": baseline.get("resource_version"),
                                         "file": relative}})
    if incomplete:
        problems.append({"code": "resource_incomplete",
                         "message": "This resource version is not fully installed",
                         "details": {"version": baseline.get("resource_version"),
                                     "files": incomplete[:10]}})
    return problems

# ---------------------------------------------------------------------------
# PI-I3 plan/apply


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_relative(relative: str, label: str) -> PurePosixPath:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part == ".." for part in pure.parts):
        raise DomainError("unsafe_path", "%s must be a safe relative path" % label, {"path": relative})
    return pure


def _shell_quote(value: str) -> str:
    """POSIX single-quote encoding for a fixed program path.

    Hosts run hook commands through a shell, so the package path must be
    encoded per platform rules. The path is a package-controlled constant;
    no user text is interpolated. Anything outside the safe set (including
    spaces) is single-quoted.
    """
    if not value:
        return "''"
    if all((char.isascii() and char.isalnum()) or char in "@%+=:,./-_" for char in value) \
            and not value.startswith("-"):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _hook_command(semantic: str) -> str:
    launcher = _package_root() / "bin" / "fstar-hook.cjs"
    return "%s %s" % (_shell_quote(str(launcher)), semantic)


def _semantic_for_shape(shape: Mapping) -> str:
    # The planner declares its semantic explicitly; the command-substring
    # scan is only a legacy fallback for shapes without the key.
    semantic = shape.get("semantic")
    if semantic in HOOK_SEMANTICS:
        return semantic
    for semantic in HOOK_SEMANTICS:
        if any(semantic in hook.get("command", "") for hook in shape.get("hooks", [])):
            return semantic
    raise DomainError("host_plan_invalid", "Host plan entry does not map to a known semantic hook",
                      {"event": shape.get("event")})


def _settings_file(host: str) -> str:
    if host == "claude":
        return "settings.json"
    # Verified live against codex-cli 0.165.0 (2026-11-01): ~/.codex/hooks.json
    # IS a real user-level hooks layer (the host warns when both it and the
    # config.toml [hooks] table exist), but first use requires an interactive
    # TUI trust review ([hooks.state] + trusted_hash), and headless codex exec
    # never runs untrusted hooks — so unattended install cannot complete it.
    raise DomainError("host_unsupported",
                      "Codex user-level hooks (~/.codex/hooks.json) require an interactive trust review that unattended install cannot complete; project .codex/hooks.json is not a user-level substitute",
                      {"host": host})


def plan_install(*, operation: str, roots: Roots, bundle_root: Optional[Path] = None,
                 hosts: Sequence[str] = (), conflict_policy: str = "keep",
                 requested_version: Optional[str] = None) -> dict:
    """Build the full action/conflict/expected-hash plan. Pure read."""
    if operation not in ("install", "update", "uninstall"):
        raise DomainError("invalid_operation", "Unknown installer operation", {"operation": operation})
    if conflict_policy not in CONFLICT_POLICIES:
        raise DomainError("invalid_conflict_policy", "Unknown conflict policy", {"policy": conflict_policy})
    resolved = roots.resolved()
    if bundle_root is None:
        bundle_root = resolved.bundle_root
    bundle = load_bundle_manifest(bundle_root)
    version = requested_version or str(bundle.get("resource_version", ""))
    if not _valid_version(version):
        raise DomainError("resource_version_invalid", "Resource version is not a valid id", {"version": version})
    manifest, manifest_problem = _load_manifest_safe(resolved.user_root)
    owned = _owned_index(manifest)
    warnings = [manifest_problem] if manifest_problem else []
    for operation_id in pending_transactions(resolved.user_root):
        warnings.append({"code": "installer_transaction_pending",
                         "message": "An earlier installer transaction did not finish; the next apply recovers it",
                         "details": {"operation_id": operation_id}})
    cache_root = resolved.user_root / "resources" / version
    files = []
    conflicts = []
    host_files = []
    for record in bundle.get("files", []):
        source = record.get("source", "")
        _safe_relative(source, "package file")
        if not source.startswith("resources/"):
            # Launchers and Python modules stay inside the npm package; the
            # installer never copies program files into the user root.
            continue
        relative = source[len("resources/"):]
        _safe_relative(relative, "resource file")
        destination = cache_root / relative
        current_hash = None
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                conflicts.append({"kind": "path", "path": str(destination),
                                  "reason": "exists and is not a regular file"})
                continue
            current_hash = _sha256(destination)
        record_owned = owned.get(source)
        if record_owned and record_owned.get("destination") != str(destination):
            record_owned = None
        action = _file_action(operation, record_owned, current_hash, record, conflict_policy)
        if action == "conflict":
            conflicts.append({"kind": "file", "path": str(destination),
                              "reason": "unowned file with different content exists"})
        elif action == "keep_modified":
            conflicts.append({"kind": "file", "path": str(destination),
                              "reason": "installer-owned file was modified; kept by default"})
        files.append({
            "source": source,
            "relative": relative,
            "destination": str(destination),
            "expected_hash": record.get("sha256"),
            "current_hash": current_hash,
            "owned": record_owned is not None,
            "bundle_root": str(bundle_root or _package_root()),
            "action": action,
        })
    if operation in ("install", "update"):
        _check_version_immutability(cache_root, version, files)
    settings_entries = []
    target_hosts = list(hosts)
    if operation in ("update", "uninstall") and not target_hosts and manifest:
        # Update re-verifies and uninstall removes the host entries this
        # installation itself owns, but only where an explicit host root is
        # known. Without one, nothing is guessed.
        owned_hosts = sorted({record.get("host") for record in manifest.get("settings_entries", [])
                              if record.get("ownership") == "owned" and record.get("host")})
        target_hosts = [host for host in owned_hosts if host in resolved.host_roots]
    for host in target_hosts:
        if host not in SUPPORTED_HOSTS:
            raise DomainError("unknown_host", "Unknown host", {"host": host, "hosts": list(SUPPORTED_HOSTS)})
        if host == "codex":
            # Live-verified against codex-cli 0.165.0 (2026-11-01):
            # ~/.codex/hooks.json is a real user-level layer, but first use
            # needs an interactive TUI trust review ([hooks.state] +
            # trusted_hash) that unattended install cannot complete, and
            # headless codex exec never runs untrusted hooks. Report; never
            # write. Project .codex/hooks.json is NOT a user-level substitute.
            conflicts.append({"kind": "host_unsupported", "path": None,
                              "reason": "Codex user-level hooks require an interactive trust review that unattended install cannot complete; install never writes Codex settings and does not substitute project .codex/hooks.json."})
            continue
        if host not in resolved.host_roots:
            conflicts.append({"kind": "host_root", "path": None,
                              "reason": "no --host-root %s=PATH provided; nothing will be written for this host" % host})
            continue
        settings_entries.extend(_plan_host_settings(host, resolved, operation, manifest))
        host_files.extend(_plan_host_files(host, resolved, operation, manifest, bundle))
    return {
        "schema": "fstar.install-plan.v1",
        "operation": operation,
        "version": version,
        "conflict_policy": conflict_policy,
        "files": files,
        "settings_entries": settings_entries,
        "host_files": host_files,
        "conflicts": conflicts,
        "warnings": warnings,
        "roots": {
            "user_root": str(resolved.user_root),
            "runtime_root": str(resolved.runtime_root),
            "project_root": str(resolved.project_root) if resolved.project_root else None,
            "host_roots": {name: str(path) for name, path in resolved.host_roots.items()},
            "bundle_root": str(bundle_root or _package_root()),
        },
    }


def _check_version_immutability(cache_root: Path, version: str, files: Sequence[Mapping]) -> None:
    """Refuse to change the content of an already-installed resource version.

    The check runs at plan time, before any write, so a conflicting package
    never leaves a half-updated cache behind.
    """
    existing = _load_cache_manifest(cache_root)
    if existing is None:
        return
    previous = {record.get("source"): record.get("sha256") for record in existing.get("files", [])}
    incoming = {record["relative"]: record["expected_hash"] for record in files}
    if previous and previous != incoming:
        raise DomainError("resource_version_conflict",
                          "This resource version already exists with different content; versions are immutable",
                          {"version": version, "cache_root": str(cache_root)})


def _owned_index(manifest: Optional[dict]) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    if not manifest:
        return index
    for record in manifest.get("files", []):
        source = record.get("source")
        if isinstance(source, str):
            index[source] = record
    return index


def _file_action(operation: str, owned: Optional[dict], current_hash: Optional[str],
                 record: Mapping, policy: str) -> str:
    """Decide what happens to one planned file.

    Ownership comes from the recorded install manifest, never from the path,
    the file name, or a content substring. An unowned path is never taken
    over: identical content is reused as-is, different content is a conflict
    the user has to resolve.
    """
    expected = record.get("sha256")
    if operation == "uninstall":
        if owned is None:
            return "keep"
        if current_hash is None:
            return "remove_missing"
        if current_hash != owned.get("installed_hash"):
            return "keep_modified"
        return "remove"
    if owned is None:
        if current_hash is None:
            return "write"
        return "keep" if current_hash == expected else "conflict"
    # The file is installer-owned.
    if current_hash is None:
        return "write"
    if current_hash == owned.get("installed_hash"):
        # Unmodified owned file: refresh it to the incoming version.
        return "noop" if current_hash == expected else "overwrite"
    # The user changed an owned file: keep by default.
    if policy == "overwrite":
        return "overwrite"
    if policy == "new":
        return "write_new"
    return "keep_modified"


def _plan_host_settings(host: str, roots: Roots, operation: str, manifest: Optional[dict]) -> List[dict]:
    entries = []
    settings_path = roots.host_roots[host] / _settings_file(host)
    document = _read_settings(settings_path) if settings_path.exists() else {}
    for shape in registration.PLANS[host]:
        semantic = _semantic_for_shape(shape)
        hook = {"type": "command", "command": _hook_command(semantic), "timeout": 30}
        # Hosts consume matcher as a single pipe-separated regex string
        # (Claude Code 2.1.316: "The matcher is a string ... pipe-separated
        # list ("Edit|Write"), or empty to match all"); the plan keeps the
        # registration list form and serializes here.
        matcher = "|".join(shape.get("matchers") or [])
        group = {"matcher": matcher, "hooks": [hook]}
        existing = _find_hook_group(document, shape["event"], group)
        owned_entry = _owned_setting(manifest, host, shape["event"], group)
        if operation == "uninstall":
            action = "remove_owned" if owned_entry is not None else "keep"
        elif existing is not None:
            # An identical hook already exists: reuse it, never duplicate and
            # never claim ownership of a pre-existing entry.
            action = "reuse_external"
        else:
            action = "append"
        entries.append({
            "host": host,
            "event": shape["event"],
            "semantic": semantic,
            "settings_path": str(settings_path),
            "group": group,
            "hook": hook,
            "canonical_hash": _canonical_hash(group),
            "action": action,
            "owned": owned_entry is not None,
            "settings_digest": _sha256(settings_path) if settings_path.exists() else None,
            "settings_file_created": bool(owned_entry and owned_entry.get("settings_file_created")),
        })
    return entries


def _owned_setting(manifest: Optional[dict], host: str, event: str, group: Mapping) -> Optional[dict]:
    if not manifest:
        return None
    for record in manifest.get("settings_entries", []):
        if record.get("host") == host and record.get("event") == event:
            if (record.get("ownership") == "owned"
                    and record.get("canonical_hash") == _canonical_hash(group)):
                return record
    return None


# Host-side skill/agent adaptation (parent design §2.3: the host user
# directory carries "skills/agents 与必要的入口适配"). The list is driven by
# the declared SKILLS/ROLES constants, never by scanning, so nothing
# undeclared can ever reach the host root. Claude only; Codex adaptation
# stays unimplemented behind its interactive trust gate.
HOST_FILE_KINDS = {
    "claude": (
        [("skill", "skills/fstar-%s/SKILL.md" % name) for name in SKILLS]
        + [("agent", "agents/fstar-%s.md" % role) for role in ROLES]
    ),
}


def _plan_host_files(host: str, roots: Roots, operation: str, manifest: Optional[dict],
                     bundle: Mapping) -> List[dict]:
    """Plan the per-file adaptation of bundled skills/agents into the host root.

    Ownership is per-file content hash from the install manifest, the same
    rule as cache files and settings entries: an unowned path is never taken
    over, identical content is reused, different content is a conflict.
    """
    entries = []
    bundle_hashes = {record.get("source"): record.get("sha256") for record in bundle.get("files", [])}
    owned = {record.get("destination"): record for record in (manifest or {}).get("host_file_entries", [])
             if record.get("ownership") == "owned"}
    for kind, relative in HOST_FILE_KINDS[host]:
        source = "resources/%s" % relative
        expected_hash = bundle_hashes.get(source)
        if expected_hash is None:
            # A missing bundle record is a package defect, not a reason to
            # guess at the host root.
            raise DomainError("host_plan_invalid", "Bundled host file is missing from package-assets.json",
                              {"source": source})
        destination = roots.host_roots[host] / relative
        current_hash = None
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                entries.append({"host": host, "kind": kind, "source": source,
                                "destination": str(destination), "expected_hash": expected_hash,
                                "current_hash": None, "action": "conflict", "owned": False,
                                "bundle_root": str(roots.bundle_root) if roots.bundle_root else str(_package_root())})
                continue
            current_hash = _sha256(destination)
        record_owned = owned.get(str(destination))
        if operation == "uninstall":
            if record_owned is None:
                action = "keep"
            elif destination.is_symlink() or not destination.is_file():
                action = "remove_missing"
            elif current_hash != record_owned.get("installed_hash"):
                action = "keep_modified"
            else:
                action = "remove_owned"
        elif current_hash == expected_hash:
            action = "reuse_owned" if record_owned is not None else "reuse_external"
        elif record_owned is not None and current_hash != record_owned.get("installed_hash"):
            action = "keep_modified"
        elif record_owned is not None:
            # Owned and unmodified, but the bundle content changed (a new
            # version of the same resource): the installer already owns the
            # path, so refresh it — same rule as cache files (_file_action
            # overwrite). An unowned path never reaches this branch.
            action = "overwrite"
        elif current_hash is not None:
            # Unowned path with different content: the file belongs to the
            # user; report a conflict instead of taking the path over.
            action = "conflict"
        else:
            action = "write"
        entries.append({
            "host": host,
            "kind": kind,
            "source": source,
            "destination": str(destination),
            "expected_hash": expected_hash,
            "current_hash": current_hash,
            "action": action,
            "owned": record_owned is not None,
            "bundle_root": str(roots.bundle_root) if roots.bundle_root else str(_package_root()),
        })
    return entries


def _find_hook_group(document: Mapping, event: str, group: Mapping) -> Optional[dict]:
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return None
    groups = hooks.get(event)
    if not isinstance(groups, list):
        return None
    for existing in groups:
        if not isinstance(existing, dict):
            continue
        if existing.get("matcher") != group.get("matcher"):
            continue
        for hook in existing.get("hooks", []):
            if isinstance(hook, Mapping) and _canonical(hook) == _canonical(group["hooks"][0]):
                return existing
    return None


# ---------------------------------------------------------------------------
# PI-I5 transactional apply


class _Lock:
    """Exclusive lock file under the user root."""

    def __init__(self, path: Path, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self.acquired = False
        self.handle = None

    def __enter__(self) -> "_Lock":
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return self
            except OSError:
                if time.time() >= deadline:
                    self.handle.close()
                    raise DomainError("installer_lock_timeout", "Another installer operation is in progress",
                                      {"lock": str(self.path)})
                time.sleep(0.05)

    def __exit__(self, *exc) -> None:
        if self.acquired and self.handle is not None:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        if self.handle is not None:
            self.handle.close()


def apply_plan(plan: dict, *, roots: Roots) -> dict:
    """Execute a plan with re-verification under the user-root lock."""
    resolved = roots.resolved()
    if plan.get("schema") != "fstar.install-plan.v1":
        raise DomainError("invalid_plan", "apply_plan expects an fstar.install-plan.v1 plan")
    operation = plan.get("operation")
    version = plan.get("version")
    _validate_plan_paths(plan, resolved)
    with _Lock(resolved.user_root / ".install.lock"):
        _recover_abandoned_transactions(resolved)
        _reverify(plan)
        operation_id = "op-%s" % uuid.uuid4().hex[:12]
        backup_root = resolved.user_root / "install-backups" / operation_id
        applied = {"files": [], "settings": [], "kept": [], "removed": [], "reused": []}
        journal = _Journal(backup_root / "journal.jsonl", resolved)
        token = _TRANSACTION.set(journal)
        try:
            for entry in plan.get("files", []):
                _apply_file(entry, resolved, backup_root, applied)
            for entry in plan.get("settings_entries", []):
                _apply_setting(entry, resolved, operation, backup_root, applied)
            for entry in plan.get("host_files", []):
                _apply_host_file(entry, resolved, backup_root, applied)
            if operation == "uninstall":
                _commit_uninstall_manifest(resolved, applied, operation_id)
            else:
                _commit_manifest(resolved, plan, applied, operation_id, version)
            _write_entry_index(resolved, plan, applied, operation_id)
        except BaseException:
            _TRANSACTION.reset(token)
            token = None
            journal.restore()
            raise
        else:
            journal.complete()
        finally:
            if token is not None:
                _TRANSACTION.reset(token)
    return {"operation": operation, "operation_id": operation_id, "applied": applied,
            "conflicts": plan.get("conflicts", []), "backup_root": str(backup_root)}


_TRANSACTION = ContextVar("installer_transaction", default=None)


class _Journal:
    """Durable write-ahead journal for one transaction.

    Each entry is flushed and fsynced before the corresponding write, so a
    hard crash leaves a replayable record. Recovery restores in reverse order
    and keeps content that changed after our write (PI-05).
    """

    def __init__(self, path: Path, roots: Roots) -> None:
        self.path = path
        self.roots = roots
        self.entries: List[dict] = []

    def _append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def record_write(self, path: Path, before: Optional[bytes], after: bytes) -> None:
        self.entries.append({"path": path, "before": before, "after": after})
        self._append({"path": str(path),
                      "before": base64.b64encode(before).decode("ascii") if before is not None else None,
                      "after_sha": _sha256_bytes(after)})

    def record_remove(self, path: Path, before: bytes) -> None:
        self.entries.append({"path": path, "before": before, "after": None})
        self._append({"path": str(path),
                      "before": base64.b64encode(before).decode("ascii"), "after_sha": None})

    def record_mkdir(self, path: Path, ancestors: Optional[Sequence[Path]] = None) -> None:
        """Remember directories this transaction created.

        Restore replays entries in reverse, so directories are stored
        outermost-first: the deepest directory is removed before its
        parent's emptiness is checked. Restore removes each recorded
        directory only if it is empty at rollback time (iterdir guard plus
        rmdir's ENOTEMPTY), so content added after our write survives.
        Duplicates are collapsed; existing directories are harmless no-op
        records.
        """
        # Callers may collect ancestors innermost-first (walking up from the
        # destination); normalize to outermost-first here.
        ordered = list(ancestors or ())
        ordered.reverse()
        ordered.append(path)
        seen = set()
        for directory in ordered:
            if directory in seen:
                continue
            seen.add(directory)
            existed = directory.is_dir()
            if not existed:
                self._append({"mkdir": str(directory)})
            self.entries.append({"mkdir": str(directory), "existed": existed})

    def restore(self) -> None:
        _restore_entries(self.entries)
        self.path.unlink(missing_ok=True)

    def complete(self) -> None:
        self.path.unlink(missing_ok=True)


def _restore_entries(entries: Sequence[Mapping]) -> None:
    """Undo recorded writes in reverse, never clobbering later user edits."""
    blocked = set()
    for item in reversed(list(entries)):
        if "mkdir" in item:
            directory = Path(item["mkdir"])
            if not item.get("existed"):
                try:
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()
                except OSError:
                    pass
            continue
        path = Path(item["path"])
        if path in blocked:
            continue
        try:
            current = path.read_bytes() if path.is_file() else None
        except OSError:
            continue
        before = item.get("before")
        if current == before:
            continue  # the journaled write never landed
        if not _matches_written_state(current, item):
            blocked.add(path)  # changed after our write: keep it
            continue
        if before is None:
            path.unlink(missing_ok=True)
        else:
            _atomic_write_bytes(path, before)


def _matches_written_state(current: Optional[bytes], item: Mapping) -> bool:
    if "after" in item:
        after = item["after"]
        return current is None if after is None else current == after
    after_sha = item.get("after_sha")
    if after_sha is None:
        return current is None
    return current is not None and _sha256_bytes(current) == after_sha


def _recover_abandoned_transactions(roots: Roots) -> None:
    """Replay journals left by a crashed install/update/uninstall."""
    backups = roots.user_root / "install-backups"
    if not backups.is_dir():
        return
    for journal in sorted(backups.glob("op-*/journal.jsonl")):
        if not re.fullmatch(r"op-[0-9a-f]{12}", journal.parent.name):
            continue
        entries = []
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
                if "mkdir" in record:
                    directory = Path(record["mkdir"])
                    if any(_within(directory.resolve(), root) for root in roots.host_roots.values()):
                        entries.append({"mkdir": str(directory), "existed": False})
                    continue
                path = Path(record["path"])
                resolved_path = path.resolve()
                if not (_within(resolved_path, roots.user_root)
                        or any(_within(resolved_path, root) for root in roots.host_roots.values())):
                    continue
                before = (base64.b64decode(record["before"])
                          if record.get("before") is not None else None)
                entries.append({"path": path, "before": before,
                                "after_sha": record.get("after_sha")})
            except (ValueError, KeyError, TypeError):
                continue  # torn tail line from the crash
        _restore_entries(entries)
        journal.unlink(missing_ok=True)


def pending_transactions(user_root: Path) -> List[str]:
    """Read-only: operation ids whose journal was never completed."""
    backups = user_root / "install-backups"
    if not backups.is_dir():
        return []
    return sorted(journal.parent.name for journal in backups.glob("op-*/journal.jsonl")
                  if re.fullmatch(r"op-[0-9a-f]{12}", journal.parent.name))


def recover_pending(roots: Roots) -> dict:
    """Explicitly replay journals left by a crashed transaction."""
    resolved = roots.resolved()
    with _Lock(resolved.user_root / ".install.lock"):
        pending = pending_transactions(resolved.user_root)
        _recover_abandoned_transactions(resolved)
    return {"recovered": pending}


def _validate_plan_paths(plan: dict, roots: Roots) -> None:
    if plan.get("operation") not in ("install", "update", "uninstall") or not _valid_version(plan.get("version")):
        raise DomainError("invalid_plan", "Invalid operation or version")
    cache = roots.user_root / "resources" / plan["version"]
    for entry in plan.get("files", []):
        relative = _safe_relative(entry["relative"], "destination")
        destination = Path(entry["destination"])
        if destination != cache / relative:
            raise DomainError("unsafe_path", "Plan destination does not match the version cache")
        _reject_symlink_ancestors(destination, roots.user_root)
        _safe_relative(entry["source"], "source")
    for entry in plan.get("settings_entries", []):
        host = entry["host"]
        if host not in roots.host_roots or Path(entry["settings_path"]) != roots.host_roots[host] / _settings_file(host):
            raise DomainError("unsafe_path", "Settings target does not match the selected host root")
        _reject_symlink_ancestors(Path(entry["settings_path"]), roots.host_roots[host])
    for entry in plan.get("host_files", []):
        host = entry["host"]
        expected_relative = None
        for kind, relative in HOST_FILE_KINDS.get(host, ()):
            if entry["source"] == "resources/%s" % relative:
                expected_relative = relative
                break
        if (host not in roots.host_roots or expected_relative is None
                or Path(entry["destination"]) != roots.host_roots[host] / expected_relative):
            raise DomainError("unsafe_path", "Host file target does not match the declared host adaptation",
                              {"destination": entry.get("destination")})
        _safe_relative(expected_relative, "host file")
        if entry.get("action") not in ("conflict", "keep", "keep_modified", "remove_missing"):
            # Entries that will never be written (a user's symlink or modified
            # file at the path) are only reported; the symlink check applies
            # to paths the transaction will actually touch.
            _reject_symlink_ancestors(Path(entry["destination"]), roots.host_roots[host])
        _safe_relative(entry["source"], "source")
    for path in (roots.user_root / ".install.lock", roots.user_root / "install-backups",
                 roots.user_root / ".install-manifest.json", roots.user_root / ".asset-hashes.json",
                 roots.user_root / "version", roots.user_root / "entry-index.json", cache / "manifest.json"):
        _reject_symlink_ancestors(path, roots.user_root)


def _reverify(plan: dict) -> None:
    """Detect concurrent edits since the plan was built (PI-05/T8)."""
    for entry in plan.get("files", []):
        path = Path(entry["destination"])
        recorded = entry.get("current_hash")
        actual = _sha256(path) if path.exists() and path.is_file() else None
        if recorded != actual:
            raise DomainError("installer_plan_stale", "Target changed after the plan was built",
                              {"path": str(path), "planned_hash": recorded, "actual_hash": actual})
    for entry in plan.get("settings_entries", []):
        path = Path(entry["settings_path"])
        actual = _sha256(path) if path.is_file() else None
        if entry.get("settings_digest") != actual:
            raise DomainError("installer_plan_stale", "Host settings changed after the plan was built",
                              {"path": str(path)})
    for entry in plan.get("host_files", []):
        path = Path(entry["destination"])
        # A non-regular target is "no hash" the same way plan time saw it:
        # a symlink planned as a conflict must not abort the transaction
        # with a stale error (is_file() follows symlinks, so the explicit
        # is_symlink() check matters). Only a real change from the planned
        # state (regular file replaced, or hash drift) is stale.
        actual = _sha256(path) if path.is_file() and not path.is_symlink() else None
        if entry.get("current_hash") != actual:
            raise DomainError("installer_plan_stale", "Host file changed after the plan was built",
                              {"path": str(path)})


def _apply_file(entry: dict, roots: Roots, backup_root: Path, applied: dict) -> None:
    action = entry["action"]
    destination = Path(entry["destination"])
    if action in ("keep", "noop", "keep_modified", "remove_missing", "conflict"):
        # A conflict is not an error: the file belongs to the user and is
        # reported as a conflict instead of being overwritten.
        applied["kept"].append({"path": str(destination), "action": action})
        return
    _reverify({"files": [entry]})
    if action == "remove":
        backup = _backup(backup_root, destination, roots.user_root)
        journal = _TRANSACTION.get()
        if journal is not None:
            journal.record_remove(destination, destination.read_bytes())
        destination.unlink()
        applied["removed"].append({"path": str(destination), "backup": backup})
        return
    if action == "write_new":
        target = destination.with_name(destination.name + ".new")
        _reject_symlink_ancestors(target.parent, roots.user_root)
        if target.exists() or target.is_symlink():
            # An existing .new belongs to someone else; never clobber it.
            applied["kept"].append({"path": str(target), "action": "existing_new_conflict"})
            return
        payload = _source_bytes(entry)
        _atomic_write_bytes(target, payload)
        applied["files"].append({"path": str(target), "action": action, "backup": None,
                                 "written_hash": _sha256_bytes(payload)})
        return
    if action in ("write", "overwrite"):
        _reject_symlink_ancestors(destination, roots.user_root)
        payload = _source_bytes(entry)
        if entry.get("expected_hash") is not None and _sha256_bytes(payload) != entry["expected_hash"]:
            raise DomainError("resource_integrity", "Source file no longer matches its planned hash",
                              {"source": entry["source"]})
        backup = None
        if destination.exists():
            backup = _backup(backup_root, destination, roots.user_root)
        _atomic_write_bytes(destination, payload)
        applied["files"].append({"path": str(destination), "action": action, "backup": backup,
                                 "written_hash": _sha256_bytes(payload)})
        return
    raise DomainError("invalid_plan_action", "Unknown planned action", {"action": action})


def _reject_symlink_ancestors(path: Path, root: Path) -> None:
    """Refuse to write through a symlinked ancestor outside the given root."""
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise DomainError("unsafe_path", "Cannot resolve target path", {"path": str(path), "reason": str(exc)})
    if not _within(resolved, root.resolve()):
        raise DomainError("unsafe_path", "Target resolves outside the managed root",
                          {"path": str(path), "resolved": str(resolved), "root": str(root)})


def _source_bytes(entry: dict) -> bytes:
    bundle_root = Path(entry["bundle_root"]).resolve() if "bundle_root" in entry else _package_root()
    target = (bundle_root / entry["source"]).resolve()
    if not _within(target, bundle_root) or not target.is_file():
        raise DomainError("unsafe_path", "Planned source is outside the bundle", {"path": str(target)})
    return target.read_bytes()


def _backup(backup_root: Path, path: Path, user_root: Path) -> Optional[str]:
    if not path.exists():
        return None
    if _within(path, user_root):
        relative = path.relative_to(user_root)
    else:
        # Settings outside the user root are backed up under a marked name so
        # restore never writes outside a known root.
        relative = Path("_external") / path.name
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(path), str(target))
    return str(target)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    journal = _TRANSACTION.get()
    if journal is not None:
        journal.record_write(path, path.read_bytes() if path.is_file() else None, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%s" % uuid.uuid4().hex[:8])
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _atomic_write_json(path: Path, payload) -> None:
    _atomic_write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _apply_setting(entry: dict, roots: Roots, operation: str, backup_root: Path, applied: dict) -> None:
    path = Path(entry["settings_path"])
    prior = next((item for item in reversed(applied["settings"]) if item["path"] == str(path)), None)
    expected = prior["written_hash"] if prior else entry.get("settings_digest")
    if (_sha256(path) if path.is_file() else None) != expected:
        raise DomainError("installer_plan_stale", "Settings changed during installation", {"path": str(path)})
    document = _read_settings(path)
    if entry["action"] == "reuse_external":
        applied["reused"].append({"path": str(path), "event": entry["event"],
                                  "semantic": entry["semantic"], "ownership": "externally_owned"})
        return
    if entry["action"] == "keep":
        applied["kept"].append({"path": str(path), "action": "keep", "event": entry["event"]})
        return
    if entry["action"] == "remove_owned":
        removed = _remove_owned_hooks(document, entry)
        if removed == 0:
            applied["kept"].append({"path": str(path), "action": "no_owned_entry", "event": entry["event"]})
            return
    else:
        removed = _append_hook(document, entry)
    if (entry["action"] == "remove_owned" and entry.get("settings_file_created")
            and not document):
        # The installer created this settings file (recorded at install time)
        # and the last owned entry is now gone: removing the file restores the
        # host root to its pre-install state instead of leaving an empty
        # document behind. Journaled like any removal.
        journal = _TRANSACTION.get()
        if journal is not None:
            journal.record_remove(path, path.read_bytes())
        path.unlink(missing_ok=True)
        applied["settings"].append({"path": str(path), "event": entry["event"],
                                    "semantic": entry["semantic"], "action": "remove_owned_file",
                                    "backup": None, "removed": removed, "written_hash": None})
        return
    backup = _backup(backup_root, path, roots.user_root) if path.exists() else None
    _atomic_write_json(path, document)
    applied["settings"].append({
        "path": str(path),
        "event": entry["event"],
        "semantic": entry["semantic"],
        "action": entry["action"],
        "backup": backup,
        "removed": removed,
        "written_hash": _sha256(path),
    })


def _apply_host_file(entry: dict, roots: Roots, backup_root: Path, applied: dict) -> None:
    """Apply one host-side skill/agent file.

    Same rules as every other managed write: journal before write, backup
    outside the user root under a marked name, never clobber a path whose
    content changed after the plan was built.
    """
    action = entry["action"]
    destination = Path(entry["destination"])
    if action in ("keep", "conflict", "keep_modified", "reuse_external", "reuse_owned",
                  "remove_missing"):
        # A conflict or a missing target is not an error: the path belongs
        # to the user (or is already gone) and is reported, never faked.
        applied["reused" if action.startswith("reuse") else "kept"].append(
            {"path": str(destination), "action": action, "host": entry["host"], "kind": entry["kind"]})
        return
    if action == "remove_owned":
        backup = _backup(backup_root, destination, roots.user_root)
        journal = _TRANSACTION.get()
        if journal is not None:
            journal.record_remove(destination, destination.read_bytes())
        destination.unlink()
        applied["removed"].append({"path": str(destination), "backup": backup,
                                   "host": entry["host"], "kind": entry["kind"]})
        _prune_empty_host_dir(destination.parent, roots)
        _prune_empty_host_dir(destination.parent.parent, roots)
        return
    if action == "write" or (action == "overwrite" and destination.exists()):
        # Host files live under the HOST root, not the user data root; the
        # symlink-ancestor boundary is the host root that owns this file.
        _reject_symlink_ancestors(destination, roots.host_roots[entry["host"]])
    if action == "overwrite" and not destination.exists():
        # Nothing to overwrite: fall through to a plain write.
        action = "write"
    if action == "write":
        payload = _source_bytes(entry)
        if entry.get("expected_hash") is not None and _sha256_bytes(payload) != entry["expected_hash"]:
            raise DomainError("resource_integrity", "Source file no longer matches its planned hash",
                              {"source": entry["source"]})
        backup = _backup(backup_root, destination, roots.user_root)
        # The journal covers the file write; every directory the write will
        # create between the host root and the file is recorded so restore
        # removes only what this install made.
        journal = _TRANSACTION.get()
        if journal is not None:
            missing = []
            current = destination.parent
            host_root = roots.host_roots[entry["host"]]
            while current != host_root and current != current.parent:
                if not current.is_dir():
                    missing.append(current)
                current = current.parent
            journal.record_mkdir(destination.parent, ancestors=missing)
        _atomic_write_bytes(destination, payload)
        applied["files"].append({"path": str(destination), "action": action, "backup": backup,
                                 "written_hash": _sha256_bytes(payload),
                                 "host": entry["host"], "kind": entry["kind"]})
        return
    raise DomainError("invalid_plan_action", "Unknown planned action", {"action": action})


def _prune_empty_host_dir(directory: Path, roots: Roots) -> None:
    """Remove a container directory only when this install emptied it.

    The candidate must be a declared adaptation container (skills/,
    skills/fstar-* or agents/ under a host root) and empty; anything with
    content is left alone. An empty directory carries no user data, so
    removing it is always a safe restore.
    """
    host_roots = {root.resolve() for root in roots.host_roots.values()}
    resolved = directory.resolve()
    if not any(_within(resolved, root) for root in host_roots):
        return
    allowed = False
    for root in host_roots:
        if _within(resolved, root):
            parts = resolved.relative_to(root).parts
            if parts == ("agents",) or parts == ("skills",) or (
                    len(parts) == 2 and parts[0] == "skills" and parts[1].startswith("fstar-")):
                allowed = True
                break
    if not allowed:
        return
    try:
        if not any(directory.iterdir()):
            directory.rmdir()
    except OSError:
        pass  # a prune failure never fails the uninstall


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainError("host_settings_unreadable", "Cannot parse host settings JSON",
                          {"path": str(path), "reason": str(exc)})
    if not isinstance(document, dict):
        raise DomainError("host_settings_unreadable", "Host settings must be a JSON object", {"path": str(path)})
    return document


def _append_hook(document: dict, entry: dict) -> int:
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise DomainError("host_settings_unreadable", "Host settings hooks must be an object",
                          {"path": entry.get("settings_path")})
    groups = hooks.setdefault(entry["event"], [])
    if not isinstance(groups, list):
        raise DomainError("host_settings_unreadable", "Host settings hook groups must be a list",
                          {"path": entry.get("settings_path"), "event": entry["event"]})
    group = {"matcher": entry["group"]["matcher"], "hooks": [dict(entry["hook"])]}
    for existing in groups:
        if not isinstance(existing, dict):
            continue
        if existing.get("matcher") == group["matcher"]:
            for hook in existing.get("hooks", []):
                if _canonical(hook) == _canonical(group["hooks"][0]):
                    return 0
            existing.setdefault("hooks", []).append(dict(group["hooks"][0]))
            return 1
    groups.append(group)
    return 1


def _remove_owned_hooks(document: dict, entry: dict) -> int:
    """Remove only the exact owned entry (full-value match)."""
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    groups = hooks.get(entry["event"], [])
    matches = [(group, hook) for group in groups if isinstance(group, dict)
               and group.get("matcher") == entry["group"]["matcher"]
               for hook in group.get("hooks", [])
               if isinstance(hook, Mapping) and _canonical(hook) == _canonical(entry["hook"])]
    # Duplicates make identity ambiguous: preserve all of them.
    if len(matches) != 1:
        return 0
    group, hook = matches[0]
    group["hooks"].remove(hook)
    if not group["hooks"] and set(group) <= {"matcher", "hooks"}:
        groups.remove(group)
    if not groups:
        hooks.pop(entry["event"], None)
    if not hooks:
        document.pop("hooks", None)
    return 1


def _commit_manifest(roots: Roots, plan: dict, applied: dict, operation_id: str, version: str) -> None:
    manifest = _load_manifest_safe(roots.user_root)[0] or {
        "schema": MANIFEST_SCHEMA,
        "install_id": "ins-%s" % uuid.uuid4().hex[:10],
        "files": [],
        "settings_entries": [],
    }
    files = {record["source"]: record for record in manifest.get("files", [])}
    for entry in plan.get("files", []):
        if entry["action"] not in ("write", "overwrite"):
            continue
        files[entry["source"]] = {
            "source": entry["source"],
            "destination": entry["destination"],
            "installed_hash": entry["expected_hash"],
            "version": version,
            "operation_id": operation_id,
        }
    for kept in applied.get("kept", []):
        for record in files.values():
            if record.get("destination") == kept.get("path"):
                record.setdefault("preserved", []).append(kept["action"])
    manifest["files"] = sorted(files.values(), key=lambda record: record["source"])
    settings = {record["key"]: record for record in manifest.get("settings_entries", [])}
    for entry in plan.get("settings_entries", []):
        key = "%s:%s" % (entry["host"], entry["event"])
        if entry["action"] == "append":
            settings[key] = {
                "key": key,
                "host": entry["host"],
                "event": entry["event"],
                "semantic": entry["semantic"],
                "settings_path": entry["settings_path"],
                "canonical_hash": entry["canonical_hash"],
                "hook": entry["hook"],
                "group_matcher": entry["group"]["matcher"],
                "version": version,
                "operation_id": operation_id,
                "ownership": "owned",
                # Whether the settings file itself was created by this
                # install (no digest at plan time). Uninstall uses it to
                # remove the file instead of leaving an empty document.
                "settings_file_created": not entry.get("settings_digest"),
            }
        elif entry["action"] == "reuse_external":
            settings.setdefault(key, {
                "key": key,
                "host": entry["host"],
                "event": entry["event"],
                "semantic": entry["semantic"],
                "settings_path": entry["settings_path"],
                "canonical_hash": entry["canonical_hash"],
                "hook": entry["hook"],
                "group_matcher": entry["group"]["matcher"],
                "version": version,
                "ownership": "externally_owned",
            })
        elif entry["action"] == "remove_owned":
            settings.pop(key, None)
    manifest["settings_entries"] = sorted(settings.values(), key=lambda record: record["key"])
    host_files = {record["destination"]: record for record in manifest.get("host_file_entries", [])}
    for entry in plan.get("host_files", []):
        if entry["action"] == "write":
            host_files[entry["destination"]] = {
                "host": entry["host"],
                "kind": entry["kind"],
                "source": entry["source"],
                "destination": entry["destination"],
                "installed_hash": entry["expected_hash"],
                "version": version,
                "operation_id": operation_id,
                "ownership": "owned",
            }
        elif entry["action"] in ("reuse_external", "reuse_owned"):
            host_files.setdefault(entry["destination"], {
                "host": entry["host"],
                "kind": entry["kind"],
                "source": entry["source"],
                "destination": entry["destination"],
                "installed_hash": entry["expected_hash"],
                "version": version,
                "ownership": "externally_owned",
            })
    manifest["host_file_entries"] = sorted(host_files.values(), key=lambda record: record["destination"])
    manifest["version"] = version
    manifest["transaction"] = {"operation_id": operation_id, "state": "committed",
                                "at": utc_now(), "operation": plan["operation"]}
    _atomic_write_json(roots.user_root / ".install-manifest.json", manifest)
    # The install baseline is a projection of the same transaction; it is
    # never rebuilt from current user content.
    baseline = {record["source"]: record["installed_hash"] for record in manifest["files"]}
    _atomic_write_json(roots.user_root / ".asset-hashes.json", {
        "schema": "fstar.asset-hashes.v1",
        "version": version,
        "operation_id": operation_id,
        "hashes": baseline,
    })
    _atomic_write_bytes(roots.user_root / "version", ("%s\n" % version).encode("utf-8"))
    _write_cache_manifest(roots, plan, version)


def _write_cache_manifest(roots: Roots, plan: dict, version: str) -> None:
    """Record the immutable cache baseline for the installed version.

    The cache is version-scoped: the same version id must always carry the
    same content, so a later install of different content under the same
    version is refused instead of polluting the history.

    Each entry records whether the installer actually wrote the file. A file
    the installer did not write (a conflict the user must resolve) stays
    visible as an incomplete version instead of being silently presented as
    the pinned content.
    """
    cache_root = roots.user_root / "resources" / version
    files = []
    for entry in plan.get("files", []):
        action = entry["action"]
        # Content that already matches the version is present even when the
        # installer did not write it; modified or conflicting content is not.
        present = action in ("write", "overwrite", "noop") or (
            action == "keep" and entry.get("current_hash") == entry.get("expected_hash"))
        files.append({
            "source": entry["relative"],
            "sha256": entry["expected_hash"],
            "installed": present,
        })
    files.sort(key=lambda record: record["source"])
    payload = {
        "schema": BUNDLE_SCHEMA,
        "resource_version": version,
        "files": files,
    }
    _atomic_write_json(cache_root / "manifest.json", payload)


def _commit_uninstall_manifest(roots: Roots, applied: dict, operation_id: str) -> None:
    manifest = _load_manifest_safe(roots.user_root)[0]
    if not manifest:
        return
    removed = {item["path"] for item in applied.get("removed", [])}
    files = [record for record in manifest.get("files", []) if record.get("destination") not in removed]
    # A settings entry stays recorded when it was not actually removed (for
    # example because the user edited it); only truly removed entries drop out.
    removed_keys = {"%s:%s" % (item.get("path"), item.get("event"))
                    for item in applied.get("settings", []) if item.get("removed")}
    settings = [record for record in manifest.get("settings_entries", [])
                if "%s:%s" % (record.get("settings_path"), record.get("event")) not in removed_keys]
    removed_host_files = {item["path"] for item in applied.get("removed", [])
                          if item.get("host")}
    host_file_entries = [record for record in manifest.get("host_file_entries", [])
                         if record.get("destination") not in removed_host_files]
    manifest["files"] = files
    manifest["settings_entries"] = settings
    manifest["host_file_entries"] = host_file_entries
    manifest["transaction"] = {"operation_id": operation_id, "state": "committed",
                                "at": utc_now(), "operation": "uninstall"}
    _atomic_write_json(roots.user_root / ".install-manifest.json", manifest)
    _atomic_write_json(roots.user_root / ".asset-hashes.json", {
        "schema": "fstar.asset-hashes.v1",
        "version": manifest.get("version"),
        "operation_id": operation_id,
        "hashes": {record["source"]: record["installed_hash"] for record in files},
    })
    # Retain cache directories and their baselines: other projects may pin
    # old versions, and directory names alone do not establish ownership.


def _write_entry_index(roots: Roots, plan: dict, applied: dict, operation_id: str) -> None:
    index = _load_entry_index(roots.user_root)
    entries = {entry["id"]: entry for entry in index.get("entries", [])}
    removed_settings = {"%s:%s" % (item["path"], item["event"])
                        for item in applied.get("settings", []) if item.get("removed")}
    for entry in plan.get("settings_entries", []):
        identifier = "%s:%s" % (entry["host"], entry["event"])
        if plan["operation"] == "uninstall":
            # Only a registration the installer actually removed leaves the
            # index; a kept (modified or externally-owned) one stays visible.
            if "%s:%s" % (entry["settings_path"], entry["event"]) in removed_settings:
                entries.pop(identifier, None)
            continue
        ownership = "owned" if entry["action"] == "append" or entry.get("owned") else "externally_owned"
        entries[identifier] = {
            "id": identifier,
            "host": entry["host"],
            "kind": "hook",
            "semantic": entry["semantic"],
            "event": entry["event"],
            "source": "package",
            "invocation": entry["hook"]["command"],
            "matcher": entry["group"]["matcher"],
            "hook": entry["hook"],
            "installed_path": entry["settings_path"],
            "ownership": ownership,
            "status": "active",
            "version": plan["version"],
            "operation_id": operation_id,
        }
    removed_host_files = {item["path"] for item in applied.get("removed", []) if item.get("host")}
    for entry in plan.get("host_files", []):
        identifier = "host-file:%s" % entry["destination"]
        if plan["operation"] == "uninstall":
            if entry["destination"] in removed_host_files:
                entries.pop(identifier, None)
            continue
        if entry["action"] not in ("write", "reuse_owned", "reuse_external"):
            continue
        entries[identifier] = {
            "id": identifier,
            "host": entry["host"],
            "kind": "skill" if entry["kind"] == "skill" else "agent",
            "source": "package",
            "installed_path": entry["destination"],
            "ownership": "owned" if entry["action"] in ("write", "reuse_owned") else "externally_owned",
            "status": "active",
            "version": plan["version"],
            "operation_id": operation_id,
        }
    index = {"schema": ENTRY_INDEX_SCHEMA,
             "entries": sorted(entries.values(), key=lambda item: item["id"])}
    _atomic_write_json(roots.user_root / "entry-index.json", index)


def _load_entry_index(user_root: Path) -> dict:
    path = user_root / "entry-index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": ENTRY_INDEX_SCHEMA, "entries": []}
    return index if isinstance(index, dict) else {"schema": ENTRY_INDEX_SCHEMA, "entries": []}


def entry_index_report(user_root: Optional[Path]) -> dict:
    """Read the entry index and verify each entry against the actual disk.

    Design §6: help must read this index and then check the real files; an
    entry whose installed file is gone is reported ``missing`` — it is never
    claimed as installed. Read-only; a missing or unreadable index is an
    explicit empty report, not an error and never a fabricated listing.
    """
    user_root = Path(user_root) if user_root is not None else None
    index = _load_entry_index(user_root) if user_root is not None \
        else {"schema": ENTRY_INDEX_SCHEMA, "entries": []}
    entries = []
    for record in index.get("entries", []):
        if not isinstance(record, dict):
            continue
        entry = dict(record)
        installed_path = record.get("installed_path")
        present = isinstance(installed_path, str) and bool(installed_path) \
            and Path(installed_path).is_file()
        if present and record.get("kind") == "hook":
            # A settings file can remain after a user removes one hook. Verify
            # the indexed event and command, not merely the containing file.
            try:
                document = _read_settings(Path(installed_path))
                groups = document.get("hooks", {}).get(record.get("event"), [])
                expected_hook = record.get("hook")
                has_full_shape = isinstance(expected_hook, dict) and "matcher" in record
                present = (isinstance(record.get("invocation"), str)
                           and bool(record["invocation"]) and isinstance(groups, list) and any(
                    isinstance(group, dict) and isinstance(group.get("hooks"), list)
                    and (not has_full_shape or group.get("matcher") == record["matcher"])
                    and any(isinstance(hook, dict) and hook.get("type") == "command"
                            and hook.get("command") == record.get("invocation")
                            and (not has_full_shape or _canonical(hook) == _canonical(expected_hook))
                            for hook in group["hooks"])
                    for group in groups))
                if present and not has_full_shape:
                    entry["note"] = "Legacy index: matcher and hook options were not recorded and cannot be verified."
            except (DomainError, AttributeError, TypeError):
                present = False
        entry["status"] = "active" if present else "missing"
        if not present:
            entry["note"] = "Indexed entry could not be verified in its installed file."
        entries.append(entry)
    return {
        "schema": ENTRY_INDEX_SCHEMA,
        "index_present": bool(user_root is not None and (user_root / "entry-index.json").is_file()),
        "entries": sorted(entries, key=lambda item: item.get("id", "")),
        "active": sorted(item["id"] for item in entries if item["status"] == "active"),
        "missing": sorted(item["id"] for item in entries if item["status"] == "missing"),
    }


def _load_manifest_safe(user_root: Path):
    """Load the manifest, reporting corruption instead of guessing.

    A corrupt manifest is never deleted or partially trusted: ownership is
    treated as unknown, so a repeat install can only add missing or
    identical content and never overwrites or removes user files.
    """
    try:
        return _load_manifest(user_root), None
    except DomainError as exc:
        return None, {"code": exc.code, "message": exc.message, "details": exc.details}


def _load_manifest(user_root: Path) -> Optional[dict]:
    path = user_root / ".install-manifest.json"
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DomainError("installer_manifest_corrupt", "Install manifest exists but is not readable JSON",
                          {"path": str(path)})
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise DomainError("installer_manifest_corrupt", "Install manifest is not fstar.install.v1",
                          {"path": str(path)})
    if (not isinstance(manifest.get("files"), list)
            or not isinstance(manifest.get("settings_entries"), list)
            or any(not isinstance(item, dict) for item in manifest["files"] + manifest["settings_entries"])
            or any(not all(key in item for key in ("source", "destination", "installed_hash")) for item in manifest["files"])
            or any(not all(key in item for key in ("key", "host", "event", "ownership")) for item in manifest["settings_entries"])):
        raise DomainError("installer_manifest_corrupt", "Malformed ownership records", {"path": str(path)})
    return manifest


# ---------------------------------------------------------------------------
# PI-I7 migration


MIGRATIONS: Dict[Tuple[int, int], object] = {}


def _data_root(target_root: Path) -> Path:
    return target_root / ".fstar"


def _snapshot(root: Path) -> Dict[str, str]:
    """Hash every regular file under root, keyed by relative path."""
    snapshot: Dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            snapshot[str(path.relative_to(root))] = _sha256(path)
    return snapshot


def migrate(*, target_root: Path, from_schema: Optional[int] = None, to_schema: int,
            transform=None, dry_run: bool = False, operation_id: Optional[str] = None) -> dict:
    """Explicit, reversible schema migration for one data root.

    Only implemented chains run. A same-schema request is an explicit no-op.
    The production registry is empty: schema 1 is current, so the only
    supported production request is 1->1 (no-op); synthetic test transforms
    are injected explicitly and are never advertised as production schema 2.

    The pre-migration bytes of the data root are snapshotted, so a failed or
    rolled-back migration restores the original content. Rollback refuses to
    overwrite content that changed after the migration completed.
    """
    marker_path = _data_root(target_root) / ".schema-version"
    if from_schema is None and marker_path.exists():
        current = marker_path.read_text(encoding="utf-8").strip()
        try:
            from_schema = int(current)
        except ValueError:
            raise DomainError("migration_unsupported", "Schema marker is not an integer",
                              {"path": str(marker_path), "value": current})
    if from_schema == to_schema:
        return {"operation": "migrate", "from_schema": from_schema, "to_schema": to_schema,
                "result": "no-op", "changed": []}
    key = (from_schema, to_schema)
    if key not in MIGRATIONS and transform is None:
        raise DomainError("migration_unsupported", "No implemented migration chain for this schema pair",
                          {"from": from_schema, "to": to_schema})
    operation = operation_id or "mig-%s" % uuid.uuid4().hex[:10]
    backup_root = target_root / "install-backups" / operation
    if dry_run:
        return {"operation": "migrate", "from_schema": from_schema, "to_schema": to_schema,
                "result": "dry-run", "operation_id": operation, "backup_root": str(backup_root)}
    data_root = _data_root(target_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    snapshot_root = backup_root / "snapshot"
    snapshot = _snapshot(data_root)
    for relative in snapshot:
        source = data_root / relative
        target = snapshot_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
    changed = []
    try:
        if transform is not None:
            changed = transform(target_root, backup_root)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(marker_path, ("%d\n" % to_schema).encode("utf-8"))
    except BaseException:
        for relative in snapshot:
            target = data_root / relative
            _atomic_write_bytes(target, (snapshot_root / relative).read_bytes())
        if from_schema is not None:
            _atomic_write_bytes(marker_path, ("%d\n" % from_schema).encode("utf-8"))
        raise
    post = _snapshot(data_root)
    _atomic_write_json(backup_root / "post.json", {"post": post, "snapshot": snapshot})
    return {"operation": "migrate", "from_schema": from_schema, "to_schema": to_schema,
            "result": "migrated", "operation_id": operation, "changed": changed,
            "backup_root": str(backup_root)}


def rollback_migration(*, target_root: Path, transaction_id: str, restore=None) -> dict:
    """Restore the original bytes recorded for one migration transaction.

    Content that changed after the migration completed is kept and reported
    as a conflict: a rollback must not destroy later user edits.
    """
    if not re.fullmatch(r"mig-[0-9a-f]{10}", transaction_id):
        raise DomainError("migration_unknown_transaction", "Invalid migration transaction id")
    backup_root = target_root / "install-backups" / transaction_id
    _reject_symlink_ancestors(backup_root, target_root)
    if not backup_root.exists():
        raise DomainError("migration_unknown_transaction", "No backup directory for this transaction id",
                          {"transaction_id": transaction_id})
    if restore is not None:
        restored = restore(backup_root)
        return {"operation": "rollback", "transaction_id": transaction_id, "restored": restored,
                "conflicts": []}
    data_root = _data_root(target_root)
    snapshot_root = backup_root / "snapshot"
    post = {}
    try:
        post = json.loads((backup_root / "post.json").read_text(encoding="utf-8")).get("post", {})
    except (OSError, ValueError):
        post = {}
    restored = []
    conflicts = []
    for path in sorted(snapshot_root.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(snapshot_root))
        target = data_root / relative
        expected_after = post.get(relative)
        if expected_after is not None and target.exists():
            try:
                if _sha256(target) != expected_after:
                    conflicts.append({"path": str(target),
                                      "reason": "content changed after the migration; kept"})
                    continue
            except OSError:
                pass
        _atomic_write_bytes(target, path.read_bytes())
        restored.append(str(target))
    return {"operation": "rollback", "transaction_id": transaction_id, "restored": restored,
            "conflicts": conflicts}


# ---------------------------------------------------------------------------
# PI-I8 doctor / version


def _doctor_host_files(resolved: Roots) -> List[dict]:
    """Diagnostics for recorded host-side skill/agent files.

    Only recorded (installed) entries are checked; a host root the installer
    never wrote to produces no diagnostics, matching the never-guess rule.
    """
    manifest, _ = _load_manifest_safe(resolved.user_root)
    if not manifest:
        return []
    diagnostics = []
    for record in manifest.get("host_file_entries", []):
        host = record.get("host")
        destination = Path(record.get("destination", ""))
        # Only entries whose recorded destination sits inside the currently
        # configured host root are checked; an entry recorded against a
        # different root is left to the entry index, not guessed here.
        if host not in resolved.host_roots or not _within(destination, resolved.host_roots[host]):
            continue
        if destination.is_symlink() or not destination.is_file():
            diagnostics.append({"code": "HOST_FILE_MISSING",
                                "path": str(destination), "line": 1,
                                "message": "Installed host file is missing on disk",
                                "details": {"host": host, "kind": record.get("kind")}})
        elif _sha256(destination) != record.get("installed_hash"):
            diagnostics.append({"code": "HOST_FILE_MODIFIED",
                                "path": str(destination), "line": 1,
                                "message": "Installed host file differs from the recorded content",
                                "details": {"host": host, "kind": record.get("kind")}})
    return diagnostics


def doctor(*, roots: Roots, host_observations: Optional[Mapping] = None) -> dict:
    """Read-only structural health report (PI-06)."""
    resolved = roots.resolved()
    selection = resolve_resources(project_root=resolved.project_root, user_root=resolved.user_root,
                                  bundle_root=resolved.bundle_root, strict=False)
    diagnostics = validate_resources(selection.root)
    counts = _resource_counts(selection.root)
    entry_index = _load_entry_index(resolved.user_root)
    entries_report = entry_index_report(resolved.user_root)
    missing_entries = [{"code": "entry_index_stale",
                        "path": "", "line": 1,
                        "message": "Indexed entry has no file on disk; it is not installed",
                        "details": {"entry_id": identifier}} for identifier in entries_report["missing"]]
    _, manifest_problem = _load_manifest_safe(resolved.user_root)
    pending = pending_transactions(resolved.user_root)
    pending_diagnostics = [{"code": "installer_transaction_pending",
                            "path": str(resolved.user_root / "install-backups" / operation_id),
                            "line": 1,
                            "message": "An installer transaction did not finish; the next install/update recovers it",
                            "details": {"operation_id": operation_id}} for operation_id in pending]
    host_file_diagnostics = _doctor_host_files(resolved)
    return {
        "schema": "fstar.doctor.v1",
        "resource_version": selection.version,
        "resource_source": selection.source,
        "resource_root": str(selection.root),
        "counts": counts,
        "expected_counts": EXPECTED_COUNTS,
        "diagnostics": ([{"code": d.code, "path": d.path, "line": d.line, "message": d.message}
                         for d in diagnostics]
                        + [{"code": p["code"], "path": "", "line": 1, "message": p["message"],
                            "details": p.get("details")} for p in selection.problems]
                        + ([{"code": manifest_problem["code"], "path": str(resolved.user_root / ".install-manifest.json"),
                             "line": 1, "message": manifest_problem["message"],
                             "details": manifest_problem.get("details")}]
                           if manifest_problem else [])
                        + missing_entries
                        + pending_diagnostics
                        + host_file_diagnostics),
        "entries": {"total": len(entry_index.get("entries", [])),
                    "by_host": _entries_by_host(entry_index),
                    "active": entries_report["active"],
                    "missing": entries_report["missing"],
                    "items": entries_report["entries"]},
        "hooks": _hook_report(host_observations),
        "listing": _listing_report(selection.root, host_observations),
        "schema_report": _schema_report(resolved),
        "auto_commit": _auto_commit_report(resolved),
        "pending_transactions": pending,
        "healthy": (not diagnostics and not selection.problems and not manifest_problem
                    and not missing_entries
                    and not pending_diagnostics
                    and not host_file_diagnostics),
        "read_only": True,
    }


def _resource_counts(root: Path) -> Dict[str, int]:
    return {
        "skills": len(list((root / "skills").glob("*/SKILL.md"))) if (root / "skills").exists() else 0,
        "roles": len(list((root / "agents").glob("fstar-*.md"))) if (root / "agents").exists() else 0,
        "templates": len(list((root / "templates").rglob("*.md"))) if (root / "templates").exists() else 0,
        "capabilities": len(list((root / "capabilities").glob("*.md"))) if (root / "capabilities").exists() else 0,
        "hooks": len(HOOK_SEMANTICS),
    }


def _entries_by_host(index: dict) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for entry in index.get("entries", []):
        host = entry.get("host", "?")
        result[host] = result.get(host, 0) + 1
    return result


def _hook_report(host_observations: Optional[Mapping]) -> List[dict]:
    report = []
    for semantic in HOOK_SEMANTICS:
        record = {"semantic": semantic, "evidence": "unknown", "hosts": {}}
        for host in SUPPORTED_HOSTS:
            planned = [shape for shape in registration.PLANS[host]
                       if _semantic_for_shape(shape) == semantic]
            observed = None
            if host_observations and host in host_observations:
                observed = host_observations[host].get(semantic)
            if observed is None:
                record["hosts"][host] = {"status": "not_verified", "evidence": "unknown",
                                         "planned": bool(planned)}
            else:
                record["hosts"][host] = {"status": "observed", "evidence": "observed-schema",
                                         "planned": bool(planned), "detail": observed}
        report.append(record)
    return report


def _listing_report(root: Path, host_observations: Optional[Mapping]) -> dict:
    descriptions = []
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        description = _frontmatter_description(text)
        descriptions.append({"skill": path.parent.name, "characters": len(description or "")})
    total = sum(item["characters"] for item in descriptions)
    observed = None
    if host_observations:
        observed = host_observations.get("listing")
    return {
        "descriptions": descriptions,
        "total_description_characters": total,
        "budget": {"per_skill_max": 200, "total_max": 2400, "unit": "characters"},
        "observed": observed if observed is not None else "unknown",
        "estimated_only": observed is None,
        "note": "Character counts are not tokens; full listing overhead (names/separators) is estimation unless a real host observation is supplied.",
    }


def _frontmatter_description(text: str) -> Optional[str]:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            for entry in lines[1:index]:
                if entry.startswith("description:"):
                    return entry[len("description:"):].strip().strip('"')
            return None
    return None


def _schema_report(roots: Roots) -> dict:
    result = {"data_schema": {"supported": [1], "current": 1}}
    if roots.project_root:
        marker = roots.project_root / ".fstar" / ".schema-version"
        result["project_marker"] = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
    result["knowledge_schema"] = {
        "status": "pending",
        "note": "The knowledge-base public schema has not been handed over; it is not validated here.",
    }
    return result


def _auto_commit_report(roots: Roots) -> dict:
    try:
        result = load_config(roots.project_root, roots.user_root)
    except (ConfigError, DomainError):
        return {"value": None, "source": "unavailable"}
    return {"value": result.values.get("auto_commit"),
            "source": result.origins.get("auto_commit", "<defaults>")}


def version_report(*, roots: Roots) -> dict:
    resolved = roots.resolved()
    bundle = load_bundle_manifest(resolved.bundle_root)
    selection = resolve_resources(project_root=resolved.project_root, user_root=resolved.user_root,
                                  bundle_root=resolved.bundle_root)
    pinned = _config_requested_version(resolved.project_root, resolved.user_root)[0]
    return {
        "schema": "fstar.version.v1",
        "cli_version": bundle.get("cli_version"),
        "resource_version": {"selected": selection.version, "source": selection.source,
                             "root": str(selection.root)},
        "data_schema": {"supported": bundle.get("supported_data_schemas"), "current": 1},
        "project_pin": pinned,
        "release_readiness": {
            # External verification results (evidence, not a release
            # decision). Verified 2026-11-01; see
            # .trellis/tasks/10-27-e2e-verify/evidence/live-host-2026-11-01.md
            "package_name_verified": True,
            "package_name": "fstar-workflow",
            "source_ref": bundle.get("source_ref"),
            "license_status": bundle.get("license_status"),
            "codex_user_level": "unsupported-for-unattended",
            "live_delivery": "claude session-context",
            "release_ready": False,
            "note": "Evidence complete (npm name available; source commit verified, upstream license pending with adaptation-only content; Codex user-level needs an interactive trust review, so unattended install stays unsupported; claude session-context delivered live). release_ready stays false until the owner decides to publish.",
        },
    }


# ---------------------------------------------------------------------------
# CLI registration


def register_commands(subparsers) -> None:
    from .cli import OPTIONAL_HANDLER_ATTR

    install = subparsers.add_parser(
        "install", help="install packaged resources and verified host entries")
    install.add_argument("--host", action="append", choices=list(SUPPORTED_HOSTS), default=[],
                         help="host to configure explicitly; repeatable, omitted writes no host settings")
    install.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    install.add_argument("--conflict", choices=list(CONFLICT_POLICIES), default="keep",
                         help="treatment for installer-owned files modified by the user")
    install.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_install})

    update = subparsers.add_parser(
        "update", help="preview and apply resource changes for an existing install")
    update.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    update.add_argument("--modified", choices=list(CONFLICT_POLICIES), default="keep",
                        help="treatment for installer-owned files modified by the user")
    update.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_update})

    uninstall = subparsers.add_parser(
        "uninstall", help="remove unmodified installer-owned entries; never removes user data")
    uninstall.add_argument("--host", action="append", choices=list(SUPPORTED_HOSTS), default=[],
                           help="restrict removal to these hosts; repeatable")
    uninstall.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    uninstall.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_uninstall})

    doctor_parser = subparsers.add_parser(
        "doctor", help="read-only install/resource/host health report")
    doctor_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_doctor})

    migrate_parser = subparsers.add_parser(
        "migrate", help="migrate a data schema with snapshot and rollback support")
    migrate_parser.add_argument("--project", help="project root to migrate")
    migrate_parser.add_argument("--user", action="store_true", help="migrate the user data root")
    migrate_parser.add_argument("--to-schema", type=int, required=True,
                                help="target data schema version (only 1 is supported)")
    migrate_parser.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    migrate_parser.add_argument("--rollback", help="roll back a previous migration transaction id")
    migrate_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_migrate})

    version_parser = subparsers.add_parser(
        "version", help="report CLI, resource, and data schema versions plus release readiness")
    version_parser.set_defaults(**{OPTIONAL_HANDLER_ATTR: _handle_version})

    for parser in (install, update, uninstall, doctor_parser, migrate_parser, version_parser):
        parser.add_argument("--host-root", action="append", default=[], metavar="HOST=PATH",
                            help="override a host root for fixtures/advanced targets; repeatable")


def _roots(args):
    return roots_from_args(args)


def _handle_install(args):
    roots = _roots(args)
    if not args.dry_run:
        # A previous crash must be repaired before planning against its
        # half-written state; dry runs stay read-only.
        recover_pending(roots)
    plan = plan_install(operation="install", roots=roots, hosts=args.host, conflict_policy=args.conflict)
    if args.dry_run:
        return {"dry_run": True, **plan}
    return {"dry_run": False, **apply_plan(plan, roots=roots), "warnings": plan["warnings"]}


def _handle_update(args):
    roots = _roots(args)
    if not args.dry_run:
        recover_pending(roots)
    plan = plan_install(operation="update", roots=roots, conflict_policy=args.modified)
    if args.dry_run:
        return {"dry_run": True, **plan}
    return {"dry_run": False, **apply_plan(plan, roots=roots), "warnings": plan["warnings"]}


def _handle_uninstall(args):
    roots = _roots(args)
    if not args.dry_run:
        recover_pending(roots)
    plan = plan_install(operation="uninstall", roots=roots, hosts=args.host)
    if args.dry_run:
        return {"dry_run": True, **plan}
    return {"dry_run": False, **apply_plan(plan, roots=roots), "warnings": plan["warnings"]}


def _handle_doctor(args):
    report = doctor(roots=_roots(args))
    if report.get("healthy", True):
        return report
    # An unhealthy doctor is a non-zero result. The CLI's shared main prints
    # only returned results, so the report is emitted here before exiting.
    import sys as _sys

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(1)


def _handle_migrate(args):
    if args.rollback:
        target = Path(args.project).expanduser().resolve() if args.project else _roots(args).user_root
        return rollback_migration(target_root=target, transaction_id=args.rollback)
    if args.user:
        target = _roots(args).user_root
    elif args.project:
        target = Path(args.project).expanduser().resolve()
    else:
        raise DomainError("migration_target_required", "Pass --project PATH or --user to select the migration root")
    return migrate(target_root=target, to_schema=args.to_schema, dry_run=args.dry_run)


def _handle_version(args):
    return version_report(roots=_roots(args))
