"""Injection assembly for the four semantic hooks.

Responsibilities (design §4.1/§4.2 and parent design §4.4):
- load full applicable context bodies (routing, role cards, task docs, specs)
- attach ``{path, sha256, version}`` to every injected input, using core's
  ``file_digest``/``EvidenceService.snapshot`` (never a local hash copy)
- enforce ``context_injection`` budgets; on overload emit index lines plus an
  ``unloaded`` manifest and an explicit mandatory re-read instruction (never
  silently truncate)
- work without a task.json / initialized project: routing + role card +
  session-only reference, skipping task bookkeeping silently

All state reads go through core APIs; this module performs no writes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from ..config import ConfigError, load_config
from ..evidence import EvidenceService, file_digest
from ..models import DomainError
from ..store import TaskStore, find_project_root

# Conservative defaults; the context_injection.* config keys are not yet
# registered in config.py's DEFAULT_CONFIG (child design §9.3). Missing keys
# fall back to these values without touching the config schema.
DEFAULT_BUDGETS = {
    "max_file_bytes": 262144,
    "max_artifact_bytes": 1048576,
    "max_total_bytes": 2097152,
}

ROLES = ("research", "implement", "check", "editor")

HOOK_MARKER = "<!-- fstar-hook-injected -->"


def resource_root(project_root: Optional[Path] = None,
                  user_root: Optional[Path] = None) -> Path:
    """Return the effective resources root for content injection.

    Delegates to the installer's version resolver (child design §5, handoff
    row 1): explicit request > project config ``resources.version`` > user
    ``version`` file > bundled. Without a user root this is exactly the
    bundled copy beside the package, so fresh projects keep the previous
    behavior. With a user root the selection is honest: a broken, incomplete,
    or missing pin raises instead of silently injecting bundled content while
    claiming the pinned version. Pure read; never creates a cache.
    """
    from ..installer import resources_root as _resources_root

    return _resources_root(project_root=project_root, user_root=user_root)


def read_budgets(project_root: Optional[Path], user_root: Path) -> dict:
    """Read context_injection budgets with conservative defaults.

    The keys may be absent (config.py does not define them yet); missing or
    invalid values fall back to DEFAULT_BUDGETS. Config errors surface as
    DomainError because an explicit CLI caller must see them, but passive
    hook callers catch them at the entry level.
    """
    budgets = dict(DEFAULT_BUDGETS)
    try:
        result = load_config(project_root, user_root)
        values = result.values.get("context_injection")
    except ConfigError:
        # A malformed config must not break passive injection; the explicit
        # CLI surfaces config problems through its own commands.
        return budgets
    if not isinstance(values, dict):
        return budgets
    for key in budgets:
        raw = values.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            continue
        budgets[key] = raw
    return budgets


class InjectedInput:
    """One injectable document with its fingerprint envelope."""

    def __init__(self, kind: str, path: Optional[str], text: str, sha256: str, version: str = "1"):
        self.kind = kind
        self.path = path
        self.text = text
        self.sha256 = sha256
        self.version = version

    def as_meta(self) -> dict:
        return {"kind": self.kind, "path": self.path, "sha256": self.sha256, "version": self.version}


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fingerprinted(kind: str, path: Path, *, relative: Optional[str] = None, version: str = "1") -> Optional[InjectedInput]:
    """Read one file and return it fingerprinted, or None when missing."""
    try:
        text = _load_text(path)
    except OSError:
        return None
    digest = file_digest(path)
    return InjectedInput(kind, relative if relative is not None else str(path), text, digest, version or digest)


def routing_input(root: Optional[Path] = None) -> Optional[InjectedInput]:
    """The package routing source, injected in full (parent design §4.4).

    ``root`` is the resolved resources root (see :func:`resource_root`); it
    defaults to the bundled copy for callers without a user root.
    """
    root = root if root is not None else resource_root()
    return _fingerprinted("routing", root / "runtime" / "routing.md", relative="runtime/routing.md")


def capabilities_input(root: Optional[Path] = None) -> Optional[InjectedInput]:
    """The optional-capability index, injected without any grant.

    Capabilities that stay off and unannounced are effectively absent, so the
    session context always carries one line per package. This is discovery
    only: consuming a package member still requires an explicit grant.
    """
    root = root if root is not None else resource_root()
    return _fingerprinted("capabilities", root / "runtime" / "capabilities.md",
                          relative="runtime/capabilities.md")


def role_card(role: str, root: Optional[Path] = None) -> Optional[InjectedInput]:
    """Full role card text for one of the four roles."""
    if role not in ROLES:
        raise DomainError("invalid_role", "Unknown dispatch role", {"role": role, "roles": sorted(ROLES)})
    root = root if root is not None else resource_root()
    return _fingerprinted("role", root / "agents" / ("fstar-%s.md" % role), relative=("agents/fstar-%s.md" % role))


def index_inputs(project_root: Optional[Path], user_root: Path) -> List[InjectedInput]:
    """Project and user indexes, read-only, each fingerprinted."""
    inputs = []
    if project_root is not None:
        path = project_root / ".fstar" / "index.md"
        found = _fingerprinted("project_index", path, relative=".fstar/index.md") if _safe_context_path(project_root, path) else None
        if found:
            inputs.append(found)
    path = user_root / "index.md"
    found = _fingerprinted("user_index", path, relative="~/.fstar/index.md") if _safe_context_path(user_root, path) else None
    if found:
        inputs.append(found)
    return inputs


def _safe_context_path(root: Path, path: Path) -> bool:
    """Reject aliases and escapes before loading project-owned context."""
    root = root.absolute()
    if root.is_symlink():
        return False
    try:
        relative = path.absolute().relative_to(root)
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError):
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def task_doc_inputs(project_root: Path, task_dir: Path, members: Optional[set] = None) -> List[InjectedInput]:
    """Task doc snapshot inputs: prd, design (when present), plan, clarify."""
    inputs = []
    for kind, relative in (("doc_prd", "doc/prd.md"), ("doc_design", "doc/design.md"),
                           ("plan", "plan.md"), ("clarify", "clarify.md")):
        member = {"doc_prd": "prd", "doc_design": "design", "plan": "plan", "clarify": "clarify"}[kind]
        if members is not None and member not in members:
            continue
        path = task_dir / relative
        if not _safe_context_path(project_root, path) or not path.is_file():
            continue
        try:
            found = _fingerprinted(kind, path, relative="%s/%s" % (task_dir.name, relative))
        except OSError:
            continue
        if found:
            inputs.append(found)
    return inputs


def manifest_entries(project_root: Path, task_dir: Path, action: str) -> List[dict]:
    """Read {file, reason} entries from implement.jsonl / check.jsonl.

    Only files that exist and stay inside the project are returned; a missing
    or empty manifest is an empty list (no error: the minimal loop has no
    manifests by design).
    """
    path = task_dir / ("%s.jsonl" % action)
    if not path.is_file():
        return []
    entries = []
    try:
        raw_lines = _load_text(path).splitlines()
    except (OSError, UnicodeError):
        return []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        file_value = entry.get("file")
        if not isinstance(file_value, str) or not file_value:
            continue
        candidate = Path(file_value)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        entries.append({"file": file_value, "reason": entry.get("reason", "")})
    return entries


def spec_body_inputs(project_root: Path, entries: List[dict]) -> List[InjectedInput]:
    """Load full bodies of spec/research files listed by a manifest.

    Parent design §4.4: applicable spec bodies must be loaded in full — an
    index line is not a substitute for the source body. Files that do not
    exist are skipped silently (manifests may reference files not present in
    every checkout).
    """
    inputs = []
    seen = set()
    for entry in entries:
        relative = entry["file"]
        if relative in seen:
            continue
        seen.add(relative)
        path = project_root / relative
        if not _safe_context_path(project_root, path) or not path.is_file():
            continue
        found = _fingerprinted("spec", path, relative=relative)
        if found:
            inputs.append(found)
    return inputs


def item_snapshots(service: EvidenceService, ref: str, artifact: str, items: List[str]) -> Optional[dict]:
    """Item-level fingerprints via core EvidenceService.snapshot.

    Uses only the entry-level artifact_map path; never relies on the
    mode:"file" whole-file round trip (core fix in flight, child design §2).
    Returns None when the artifact map or artifact is not established.
    """
    try:
        return service.snapshot(ref, artifact=artifact, items=items)
    except DomainError:
        return None


def _budgeted(inputs: List[InjectedInput], budgets: dict) -> dict:
    """Apply per-file and total budgets.

    Overloaded inputs are not truncated: they are dropped from the injected
    body and listed in ``unloaded`` with an explicit mandatory re-read
    instruction, so the worker must read the full applicable body before
    executing (parent design §4.4 volume boundary).
    """
    loaded: List[InjectedInput] = []
    unloaded = []
    total = 0
    for item in inputs:
        size = len(item.text.encode("utf-8"))
        if size > budgets["max_file_bytes"] or size > budgets["max_artifact_bytes"]:
            unloaded.append({"kind": item.kind, "path": item.path, "sha256": item.sha256,
                             "bytes": size, "reason": "exceeds_file_budget"})
            continue
        if total + size > budgets["max_total_bytes"]:
            unloaded.append({"kind": item.kind, "path": item.path, "sha256": item.sha256,
                             "bytes": size, "reason": "exceeds_total_budget"})
            continue
        total += size
        loaded.append(item)
    return {"loaded": loaded, "unloaded": unloaded, "total_bytes": total}


def render(heading: str, inputs: List[InjectedInput], budgets: dict, *, footer: str = "") -> str:
    """Render injected inputs under a marker, with fingerprints and overload manifest."""
    result = _budgeted(inputs, budgets)
    lines = [HOOK_MARKER, "# %s" % heading, ""]
    lines.append("## Inputs (path, sha256, version)")
    for item in inputs:
        lines.append("- %s: %s (sha256=%s, version=%s)" % (item.kind, item.path, item.sha256, item.version))
    lines.append("")
    for item in result["loaded"]:
        lines.append("### %s — %s" % (item.kind, item.path))
        lines.append("")
        lines.append(item.text.rstrip())
        lines.append("")
    if result["unloaded"]:
        lines.append("## Unloaded inputs (budget exceeded — MANDATORY re-read before executing)")
        lines.append("")
        lines.append("The following applicable inputs were NOT loaded because of the injection")
        lines.append("budget. You MUST read each listed file in full before performing any work;")
        lines.append("summaries or partial reads do not substitute for the source bodies.")
        lines.append("")
        for entry in result["unloaded"]:
            lines.append("- %s: %s (sha256=%s, %d bytes, %s)" % (
                entry["kind"], entry["path"], entry["sha256"], entry["bytes"], entry["reason"]))
        lines.append("")
    if footer:
        lines.append(footer.rstrip())
        lines.append("")
    return "\n".join(lines)


def render_json(heading: str, inputs: List[InjectedInput], budgets: dict, *, footer: str = "") -> dict:
    """Structured variant of render() for --json output."""
    result = _budgeted(inputs, budgets)
    return {
        "marker": HOOK_MARKER,
        "heading": heading,
        "inputs": [item.as_meta() for item in inputs],
        "loaded": [{"kind": item.kind, "path": item.path, "sha256": item.sha256,
                    "version": item.version, "text": item.text} for item in result["loaded"]],
        "unloaded": result["unloaded"],
        "total_bytes": result["total_bytes"],
        "budgets": budgets,
        "footer": footer,
    }


def session_only_reference() -> str:
    """The explicit no-persistent-task reference (parent design §3.7)."""
    return "Active task: session-only"


def active_task_reference(task_path: str) -> str:
    return "Active task: %s" % task_path


def locate(start: Optional[Path] = None, *, user_root: Optional[Path] = None,
           runtime_root: Optional[Path] = None) -> dict:
    """Locate project/user/runtime roots without creating anything.

    Returns {"project_root": Optional[Path], "user_root": Path,
    "store": Optional[TaskStore]}. Never writes; safe in non-init directories.
    The runtime_root must match the one session pointers were written with,
    otherwise current-task lookups silently miss (session isolation).
    """
    start = Path(start) if start is not None else Path.cwd()
    project = find_project_root(start)
    user = Path(user_root).expanduser() if user_root else Path.home() / ".fstar"
    runtime = Path(runtime_root).expanduser() if runtime_root else (user / "runtime")
    store = None
    if project is not None:
        store = TaskStore(project, user_home=user, runtime_root=runtime)
    return {"project_root": project, "user_root": user, "store": store}


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
