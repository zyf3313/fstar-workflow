"""Shared knowledge API for fstar.

This module owns one strict knowledge format (``fstar.knowledge.v1``), a
read-only catalog snapshot, complete applicable reading, precedence
resolution, authorized change proposals and recoverable group transactions.

It is an internal library.  It registers no CLI command, keeps no candidate
or history ledger and implements no search engine.

Ownership
---------
``<user_root>/rules``                      user constraints (type ``rule``)
``<user_root>/memory``                     user preferences/lessons (``memory``)
``<user_root>/index.md``                   user navigation
``<project_root>/.fstar/specs``            project practices (type ``spec``)
``<project_root>/.fstar/knowledge/context``      project facts and terms
``<project_root>/.fstar/knowledge/references``   external material
``<project_root>/.fstar/index.md``         project navigation

Guarantees
----------
* Individual file replacements are atomic; simultaneous multi-file filesystem
  visibility is **not** promised.
* Cooperating writers are serialized per owner root; readers observe
  complete before/after snapshots through this API.
* Recovery is durable and never overwrites a later external edit.
* Structural validation cannot prove natural-language meaning, language
  correctness or semantic consistency; those need human or agent review.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .config import ConfigError, load_config, parse_config
from .models import DomainError
from .project import DocumentReference, TopicReference
from .store import atomic_write_json, canonical_json, content_hash

try:  # pragma: no cover - platform guard
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None  # type: ignore[assignment]


KNOWLEDGE_SCHEMA = "fstar.knowledge.v1"
DOCUMENT_TYPES = ("rule", "memory", "spec")
STATUS_VALUES = ("active", "superseded")
STRENGTH_VALUES = ("enforced", "default")
KIND_VALUES = ("preference", "lesson")
TRUST_VALUES = ("confirmed", "unreviewed")

OWNER_USER = "user"
OWNER_PROJECT = "project"
OWNERS = (OWNER_USER, OWNER_PROJECT)

CATEGORY_RULES = "user_rules"
CATEGORY_MEMORY = "user_memory"
CATEGORY_SPECS = "project_specs"
CATEGORY_CONTEXT = "project_context"
CATEGORY_REFERENCES = "project_references"
CATEGORY_AUTHORITY = "project_authority"

CATEGORY_DIRS = {
    OWNER_USER: {
        CATEGORY_RULES: "rules",
        CATEGORY_MEMORY: "memory",
    },
    OWNER_PROJECT: {
        CATEGORY_SPECS: ".fstar/specs",
        CATEGORY_CONTEXT: ".fstar/knowledge/context",
        CATEGORY_REFERENCES: ".fstar/knowledge/references",
    },
}
CATEGORY_TYPES = {
    CATEGORY_RULES: "rule",
    CATEGORY_MEMORY: "memory",
    CATEGORY_SPECS: "spec",
}
CATEGORY_LANGUAGE_ROLE = {
    CATEGORY_RULES: "rule",
    CATEGORY_MEMORY: "memory",
    CATEGORY_SPECS: "spec",
    CATEGORY_CONTEXT: "context",
    CATEGORY_REFERENCES: "reference",
}

ROLE_OVERVIEW = "overview"
ROLE_INDEX = "index"
ROLE_GLOBAL_CONSTRAINT = "global_constraint"
ROLE_RULE = "rule"
ROLE_MEMORY = "memory"
ROLE_AUTHORITY = "authority"
ROLE_TOPIC = "topic"
ROLE_DEPENDENCY = "dependency"
ROLE_CONTEXT = "context"
ROLE_REFERENCE = "reference"

TIER_ENFORCED_RULE = 0
TIER_PROJECT = 1
TIER_DEFAULT_RULE = 2
TIER_CONFIRMED_MEMORY = 3

TIER_NAMES = {
    TIER_ENFORCED_RULE: "enforced rule",
    TIER_PROJECT: "project guidance",
    TIER_DEFAULT_RULE: "default rule",
    TIER_CONFIRMED_MEMORY: "confirmed memory",
}

APPLICABILITY_INCLUDE = "include"
APPLICABILITY_EXCLUDE = "exclude"
APPLICABILITY_UNKNOWN = "unknown"

EDIT_ACTIONS = ("create", "replace", "supersede", "delete", "rename")
INTENT_ACTIONS = ("create", "correct", "replace", "supersede", "delete", "rename", "promote")
SOURCE_TYPES = ("command", "conversation", "review")
DISPOSITIONS = ("approved", "denied", "deferred")

DEFAULT_LOCK_TIMEOUT = 5.0
READ_RETRIES = 3

__all__ = [
    "KnowledgeDocument",
    "Catalog",
    "CatalogDocument",
    "IndexDocument",
    "Diagnostic",
    "Applicability",
    "ReadSelection",
    "ContextDocument",
    "ContextBundle",
    "Exclusion",
    "RequiredUnloaded",
    "ReviewedSource",
    "ReportedConflict",
    "SemanticAssessment",
    "Resolution",
    "ResolvedSource",
    "ConflictOutcome",
    "KnowledgeEdit",
    "ChangeIntent",
    "TopicChoice",
    "SourceRecord",
    "KnowledgeProposal",
    "PlannedEdit",
    "Confirmation",
    "ChangeReceipt",
    "RecoveryOutcome",
    "RecoveryReport",
    "parse_knowledge",
    "load_catalog",
    "load_context",
    "resolve_context",
    "prepare_change",
    "apply_change",
    "recover_changes",
    "assessment_hash",
]


# ---------------------------------------------------------------------------
# errors and small helpers
# ---------------------------------------------------------------------------


def _fail(code: str, message: str, details: Optional[Mapping[str, object]] = None,
          *, status: int = 2) -> DomainError:
    return DomainError(code, message, dict(details or {}), status=status)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _normalize_owner(owner: object) -> str:
    if not isinstance(owner, str) or owner not in OWNERS:
        raise _fail("knowledge_invalid_schema", "Owner must be exactly 'user' or 'project'",
                    {"field": "owner", "expected": list(OWNERS), "actual": owner})
    return owner


def _owner_order(owners: Iterable[str]) -> Tuple[str, ...]:
    """Canonical lock order.  Every caller must use the same order."""

    return tuple(sorted(set(owners)))


def _key(owner: str, relative: str) -> str:
    return "%s:%s" % (owner, relative)


def _split_key(value: str) -> Tuple[str, str]:
    owner, _, relative = value.partition(":")
    return owner, relative


def _norm_rel(raw: object) -> str:
    """Validate an owner-relative POSIX path."""

    if not isinstance(raw, str) or not raw.strip():
        raise _fail("knowledge_unsafe_path", "Path must be a non-empty string", {"path": raw})
    if "\x00" in raw:
        raise _fail("knowledge_unsafe_path", "Path must not contain NUL", {"path": raw})
    if raw.startswith("/") or "\\" in raw:
        raise _fail("knowledge_unsafe_path", "Path must be a relative POSIX path", {"path": raw})
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise _fail("knowledge_unsafe_path", "Path traversal is not allowed", {"path": raw})
    if not parts:
        raise _fail("knowledge_unsafe_path", "Path must name a file", {"path": raw})
    return "/".join(parts)


def _reject_symlink_components(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise _fail("knowledge_unsafe_path", "Symbolic links are not allowed in managed knowledge paths",
                        {"path": str(current)})
        if current == stop or current.parent == current:
            break
        current = current.parent


def _safe_target(root: Path, relative: str) -> Path:
    rel = _norm_rel(relative)
    target = root.joinpath(*rel.split("/"))
    _reject_symlink_components(target, root)
    return target


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        if path.is_symlink():
            raise _fail("knowledge_unsafe_path", "Symbolic links are not allowed in managed knowledge paths",
                        {"path": str(path)})
        if not path.exists():
            return None
        if not path.is_file():
            raise _fail("knowledge_unsafe_path", "Target is not a regular file", {"path": str(path)})
        return path.read_bytes()
    except DomainError:
        raise
    except OSError as exc:
        raise _fail("knowledge_read_error", "File cannot be read", {"path": str(path), "reason": str(exc)})


def _decode(data: bytes, path: Path) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("knowledge_read_error", "File must be UTF-8 encoded",
                    {"path": str(path), "reason": str(exc), "expected": "utf-8"})


def _walk_files(base: Path) -> Tuple[List[Path], List[Path]]:
    """Return regular files below ``base`` and symlinks found on the way."""

    files: List[Path] = []
    links: List[Path] = []
    if not base.exists():
        return files, links
    if base.is_symlink():
        return files, [base]
    stack = [base]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(str(current)), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                links.append(path)
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                if path.suffix.lower() == ".md":
                    files.append(path)
    files.sort()
    links.sort()
    return files, links


# ---------------------------------------------------------------------------
# strict knowledge format
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeDocument:
    """A strictly decoded knowledge document.  No field is defaulted."""

    metadata: Mapping[str, str]
    body: str
    path: Path
    digest: str

    @property
    def type(self) -> str:
        return self.metadata.get("type", "")

    @property
    def status(self) -> str:
        return self.metadata.get("status", "")

    @property
    def strength(self) -> Optional[str]:
        return self.metadata.get("strength")

    @property
    def kind(self) -> Optional[str]:
        return self.metadata.get("kind")

    @property
    def trust(self) -> Optional[str]:
        return self.metadata.get("trust")


_ALLOWED_KEYS = {
    "rule": {"schema", "type", "status", "strength"},
    "memory": {"schema", "type", "status", "kind", "trust"},
    "spec": {"schema", "type", "status"},
}
_REQUIRED_KEYS = {
    "rule": {"schema", "type", "status", "strength"},
    "memory": {"schema", "type", "status", "kind", "trust"},
    "spec": {"schema", "type", "status"},
}
_TYPE_SPECIFIC = ("strength", "kind", "trust")


def _split_frontmatter(text: str, path: Path) -> Tuple[str, str, int]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0] != "---":
        raise _fail("knowledge_invalid_schema", "Frontmatter must open with a standalone --- line",
                    {"path": str(path), "line": 1, "expected": "---"})
    for index in range(1, len(lines)):
        if lines[index] == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1:])
            return frontmatter, body, index + 2
    raise _fail("knowledge_invalid_schema", "Frontmatter is not terminated by a standalone --- line",
                {"path": str(path), "line": 1, "expected": "closing ---"})


def parse_knowledge(text: str, *, path, expected_type: Optional[str] = None) -> KnowledgeDocument:
    """Strictly decode one ``fstar.knowledge.v1`` document.

    The function is pure: it performs no filesystem access, applies no
    default and filters nothing.  Inactive (``superseded``) documents are
    decoded and validated exactly like active ones so that invalid inactive
    data is reported instead of silently ignored.
    """

    target = Path(path)
    if not isinstance(text, str):
        raise _fail("knowledge_invalid_schema", "Knowledge text must be a string", {"path": str(target)})
    if expected_type is not None and expected_type not in DOCUMENT_TYPES:
        raise _fail("knowledge_invalid_schema", "Expected type is not a knowledge type",
                    {"path": str(target), "field": "expected_type", "expected": list(DOCUMENT_TYPES),
                     "actual": expected_type})
    frontmatter, body, body_line = _split_frontmatter(text, target)
    try:
        metadata = parse_config(frontmatter, target)
    except ConfigError as exc:
        raise _fail("knowledge_invalid_schema", "Frontmatter is invalid: %s" % exc.message,
                    {"path": str(target), "line": exc.line, "field": exc.key, "reason": exc.code})

    for field_name in ("schema", "type", "status"):
        if field_name not in metadata:
            raise _fail("knowledge_invalid_schema", "Required frontmatter field is missing",
                        {"path": str(target), "line": 1, "field": field_name,
                         "expected": sorted(_REQUIRED_KEYS["rule"])})
    for field_name, value in sorted(metadata.items()):
        if not isinstance(value, str):
            raise _fail("knowledge_invalid_schema", "Frontmatter values must be scalar strings",
                        {"path": str(target), "line": 1, "field": field_name,
                         "expected": "string", "actual": type(value).__name__})
    unknown = sorted(set(metadata) - {"schema", "type", "status"} - set(_TYPE_SPECIFIC))
    if unknown:
        raise _fail("knowledge_invalid_schema", "Unknown frontmatter field",
                    {"path": str(target), "line": 1, "field": unknown[0], "actual": unknown})
    document_type = metadata["type"]
    if document_type not in DOCUMENT_TYPES:
        raise _fail("knowledge_invalid_schema", "Unknown knowledge type",
                    {"path": str(target), "line": 1, "field": "type",
                     "expected": list(DOCUMENT_TYPES), "actual": document_type})
    allowed = _ALLOWED_KEYS[document_type]
    for extra in _TYPE_SPECIFIC:
        if extra in metadata and extra not in allowed:
            raise _fail("knowledge_invalid_schema", "Field does not apply to this knowledge type",
                        {"path": str(target), "line": 1, "field": extra, "actual": document_type})
    extra_unknown = sorted(set(metadata) - allowed)
    if extra_unknown:
        raise _fail("knowledge_invalid_schema", "Unknown frontmatter field",
                    {"path": str(target), "line": 1, "field": extra_unknown[0], "actual": extra_unknown})
    for field_name in sorted(_REQUIRED_KEYS[document_type] - set(metadata)):
        raise _fail("knowledge_invalid_schema", "Required frontmatter field is missing",
                    {"path": str(target), "line": 1, "field": field_name,
                     "expected": sorted(_REQUIRED_KEYS[document_type])})
    if metadata["schema"] != KNOWLEDGE_SCHEMA:
        raise _fail("knowledge_invalid_schema", "Unsupported knowledge schema",
                    {"path": str(target), "line": 1, "field": "schema",
                     "expected": KNOWLEDGE_SCHEMA, "actual": metadata["schema"]})
    if metadata["status"] not in STATUS_VALUES:
        raise _fail("knowledge_invalid_schema", "Unknown knowledge status",
                    {"path": str(target), "line": 1, "field": "status",
                     "expected": list(STATUS_VALUES), "actual": metadata["status"]})
    if document_type == "rule" and metadata["strength"] not in STRENGTH_VALUES:
        raise _fail("knowledge_invalid_schema", "Unknown rule strength",
                    {"path": str(target), "line": 1, "field": "strength",
                     "expected": list(STRENGTH_VALUES), "actual": metadata["strength"]})
    if document_type == "memory":
        if metadata["kind"] not in KIND_VALUES:
            raise _fail("knowledge_invalid_schema", "Unknown memory kind",
                        {"path": str(target), "line": 1, "field": "kind",
                         "expected": list(KIND_VALUES), "actual": metadata["kind"]})
        if metadata["trust"] not in TRUST_VALUES:
            raise _fail("knowledge_invalid_schema", "Unknown memory trust",
                        {"path": str(target), "line": 1, "field": "trust",
                         "expected": list(TRUST_VALUES), "actual": metadata["trust"]})
    if expected_type is not None and document_type != expected_type:
        raise _fail("knowledge_invalid_schema", "Document type does not match its category",
                    {"path": str(target), "line": 1, "field": "type",
                     "expected": expected_type, "actual": document_type})
    if not body.strip():
        raise _fail("knowledge_invalid_schema", "Knowledge body must not be empty",
                    {"path": str(target), "line": body_line, "expected": "non-empty body"})
    return KnowledgeDocument(metadata=dict(metadata), body=body.strip("\n"), path=target,
                             digest=_sha256_text(text))


# ---------------------------------------------------------------------------
# link scanning
# ---------------------------------------------------------------------------

_FENCE_MARKERS = ("```", "~~~")
_INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_LINK_DEFINITION = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(\S+)\s*$")
_WIKI_LINK = re.compile(r"\[\[[^\]\n]+\]\]")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_EXTERNAL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class ScannedLink:
    line: int
    target: str
    kind: str  # "inline" | "definition"


def _outside_fences(text: str) -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []
    fence: Optional[str] = None
    for index, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if fence is None:
            if stripped.startswith(_FENCE_MARKERS):
                fence = stripped[:3]
                continue
            result.append((index + 1, line))
        elif stripped.startswith(fence):
            fence = None
    return result


def scan_links(text: str) -> Tuple[ScannedLink, ...]:
    """Collect local Markdown links.  Fenced code blocks are ignored."""

    found: List[ScannedLink] = []
    for number, line in _outside_fences(text):
        definition = _LINK_DEFINITION.match(line)
        if definition:
            found.append(ScannedLink(number, definition.group(1), "definition"))
            continue
        for match in _INLINE_LINK.finditer(line):
            found.append(ScannedLink(number, match.group(1), "inline"))
    return tuple(found)


def has_unsupported_link_syntax(text: str) -> bool:
    """Wiki style links cannot be rewritten safely by this provider."""

    for _, line in _outside_fences(text):
        if _WIKI_LINK.search(line):
            return True
    return False


def heading_anchors(text: str) -> Tuple[str, ...]:
    anchors: List[str] = []
    for match in _HEADING.finditer(text):
        title = match.group(1).strip().lower()
        slug = re.sub(r"[^a-z0-9一-鿿\- ]+", "", title).strip().replace(" ", "-")
        anchors.append(slug)
    for match in re.finditer(r"<a\s+id=\"([^\"]+)\"", text):
        anchors.append(match.group(1))
    return tuple(anchors)


def split_fragment(target: str) -> Tuple[str, str]:
    file_part, _, fragment = target.partition("#")
    return file_part, fragment


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: Optional[Path] = None
    line: Optional[int] = None
    details: Mapping[str, object] = field(default_factory=dict)
    blocking: bool = False


@dataclass(frozen=True)
class CatalogDocument:
    owner: str
    category: str
    relative: str
    path: Path
    role: str
    metadata: Mapping[str, str]
    body: str
    digest: str
    active: bool
    effective: bool
    language: str
    key: str = ""

    @property
    def type(self) -> str:
        return self.metadata.get("type", "")

    @property
    def status(self) -> str:
        return self.metadata.get("status", "")

    @property
    def strength(self) -> Optional[str]:
        return self.metadata.get("strength")

    @property
    def kind(self) -> Optional[str]:
        return self.metadata.get("kind")

    @property
    def trust(self) -> Optional[str]:
        return self.metadata.get("trust")


@dataclass(frozen=True)
class IndexDocument:
    owner: str
    relative: str
    path: Path
    text: str
    digest: str
    key: str = ""


@dataclass(frozen=True)
class Catalog:
    """A read-only snapshot of the current knowledge corpus."""

    user_root: Path
    project_root: Optional[Path]
    documents: Tuple[CatalogDocument, ...]
    indexes: Tuple[IndexDocument, ...]
    authority_refs: Tuple[DocumentReference, ...]
    knowledge_refs: Tuple[DocumentReference, ...]
    topic_refs: Tuple[TopicReference, ...]
    diagnostics: Tuple[Diagnostic, ...]
    snapshot_hash: str
    language: Mapping[str, str]
    _raw: Mapping[str, bytes] = field(default_factory=dict, repr=False, compare=False)

    def by_key(self, key: str) -> Optional[CatalogDocument]:
        for document in self.documents:
            if document.key == key:
                return document
        return None

    def index_by_owner(self, owner: str) -> Optional[IndexDocument]:
        for index in self.indexes:
            if index.owner == owner:
                return index
        return None

    def source_paths(self) -> Tuple[Path, ...]:
        """Read-only view of the managed source paths for read-only consumers."""

        return tuple(sorted(document.path for document in self.documents))

    def source_bytes(self, key: str) -> Optional[bytes]:
        """Read-only access to the exact bytes behind one catalog entry."""

        return self._raw.get(key)

    @property
    def blocking_diagnostics(self) -> Tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.blocking)


def _language_policy(project_root: Optional[Path], user_root: Path) -> Dict[str, str]:
    try:
        config = load_config(project_root, user_root)
    except ConfigError as exc:
        raise _fail("knowledge_read_error", "Configuration cannot be loaded: %s" % exc.message,
                    {"path": str(exc.path) if exc.path else None, "reason": exc.code})
    language = config.values.get("language")
    if not isinstance(language, dict):
        language = {}
    artifacts = language.get("artifacts", "zh-CN")
    specs = language.get("specs", "en")
    return {
        "rule": "en",
        "memory": "en",
        "spec": specs if isinstance(specs, str) and specs else "en",
        "context": artifacts if isinstance(artifacts, str) and artifacts else "zh-CN",
        "reference": artifacts if isinstance(artifacts, str) and artifacts else "zh-CN",
        "index": artifacts if isinstance(artifacts, str) and artifacts else "zh-CN",
    }


def _category_for(owner: str, relative: str) -> Optional[str]:
    for category, directory in CATEGORY_DIRS[owner].items():
        prefix = directory + "/"
        if relative.startswith(prefix) and len(relative) > len(prefix):
            return category
    return None


def _index_relative(owner: str) -> str:
    return "index.md" if owner == OWNER_USER else ".fstar/index.md"


def _parse_project_index(text: str, path: Path) -> Tuple[Tuple[TopicReference, ...],
                                                         Tuple[DocumentReference, ...],
                                                         Tuple[DocumentReference, ...],
                                                         Tuple[Diagnostic, ...]]:
    topics: List[TopicReference] = []
    authority: List[DocumentReference] = []
    knowledge: List[DocumentReference] = []
    diagnostics: List[Diagnostic] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    sections: Dict[str, List[Tuple[int, str]]] = {}
    current: Optional[str] = None
    for number, line in enumerate(lines, 1):
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append((number, line))

    topic_lines = sections.get("主题")
    if topic_lines is None:
        diagnostics.append(Diagnostic("knowledge_navigation_unsupported",
                                      "Project index has no '## 主题' section; explicit topic selection is required",
                                      path=path, line=1))
    else:
        block: List[Tuple[int, str]] = []
        blocks: List[List[Tuple[int, str]]] = []
        for number, line in topic_lines:
            if line.startswith("### "):
                if block:
                    blocks.append(block)
                block = []
                continue
            if line.strip():
                block.append((number, line))
        if block:
            blocks.append(block)
        headings = [(number, line[4:].strip()) for number, line in topic_lines if line.startswith("### ")]
        if len(headings) != len(blocks):
            diagnostics.append(Diagnostic("knowledge_navigation_unsupported",
                                          "Project index topic headings and bodies do not match",
                                          path=path, line=1))
        for index, heading in enumerate(headings):
            number, title = heading
            identifier = title
            display = ""
            for separator in (" — ", " – ", " - ", ": ", "|"):
                if separator in title:
                    identifier, _, display = title.partition(separator)
                    break
            identifier = identifier.strip()
            display = display.strip() or identifier
            applies_to = ""
            read_when = ""
            topic_path = ""
            for body_number, body_line in blocks[index] if index < len(blocks) else []:
                stripped = body_line.strip()
                if stripped.lower().startswith("- applies to:"):
                    applies_to = stripped.split(":", 1)[1].strip()
                elif stripped.lower().startswith("- read when:"):
                    read_when = stripped.split(":", 1)[1].strip()
                elif stripped.lower().startswith("- authority:"):
                    target = _extract_link_target(stripped)
                    if target:
                        topic_path = target
            if not (identifier and applies_to and read_when and topic_path):
                diagnostics.append(Diagnostic("knowledge_navigation_unsupported",
                                              "Topic entry is missing id, Applies to, Read when or Authority",
                                              path=path, line=number,
                                              details={"topic": identifier}))
                continue
            topics.append(TopicReference(identifier, display, applies_to, read_when, topic_path))

    for section, bucket in (("已有权威文档", authority), ("长期知识", knowledge)):
        for number, line in sections.get(section, []):
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            target = _extract_link_target(stripped)
            if not target:
                continue
            label = _extract_link_label(stripped) or target
            bucket.append(DocumentReference(label, target))
    if "已有权威文档" not in sections:
        diagnostics.append(Diagnostic("knowledge_navigation_unsupported",
                                      "Project index has no '## 已有权威文档' section",
                                      path=path, line=1))
    return tuple(topics), tuple(authority), tuple(knowledge), tuple(diagnostics)


def _extract_link_target(line: str) -> str:
    match = re.search(r"\[[^\]\n]*\]\(\s*([^)\s]+)", line)
    if match:
        return match.group(1)
    return ""


def _extract_link_label(line: str) -> str:
    match = re.search(r"\[([^\]\n]*)\]", line)
    if match:
        return match.group(1)
    return ""


def _authority_key(project_root: Path, reference: str) -> Optional[str]:
    file_part, _ = split_fragment(reference)
    if not file_part:
        return None
    pure = Path(file_part)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    candidate = project_root.joinpath(*pure.parts)
    if not candidate.is_file():
        return None
    return _key(OWNER_PROJECT, "/".join(pure.parts))


def load_catalog(*, user_root, project_root=None) -> Catalog:
    """Take a read-only snapshot of the current knowledge corpus.

    The call never creates a directory, a lock file, a configuration entry or
    a project layout.  Invalid documents are reported as blocking
    diagnostics; they are never silently absent.  Cooperating readers take
    the shared owner lock when one already exists and retry when a writer
    appears during the read.
    """

    user = Path(user_root).expanduser().resolve()
    project = Path(project_root).expanduser().resolve() if project_root is not None else None
    lock_paths = _lock_paths(user, project)
    for _ in range(READ_RETRIES):
        existing = [path for path in lock_paths if path.exists()]
        locks: List[_FileLock] = []
        try:
            for path in existing:
                lock = _FileLock(path, DEFAULT_LOCK_TIMEOUT)
                lock.acquire(exclusive=False, create=False)
                if lock.stream is not None:
                    locks.append(lock)
            owner_roots = {OWNER_USER: user}
            if project is not None:
                owner_roots[OWNER_PROJECT] = project
            pending = _pending_operations(owner_roots)
            if pending:
                raise _fail("knowledge_recovery_required",
                            "A pending knowledge operation must be recovered before reading",
                            {"operations": sorted(pending)})
            catalog = _load_catalog_once(user_root=user, project_root=project)
        finally:
            for lock in locks:
                lock.release()
        if len([path for path in lock_paths if path.exists()]) > len(existing):
            continue
        return catalog
    raise _fail("knowledge_write_conflict", "A knowledge writer appeared while reading; retry the read",
                {"path": str(user)}, status=4)


def _load_catalog_once(*, user_root, project_root=None) -> Catalog:
    user = Path(user_root).expanduser().resolve()
    project = Path(project_root).expanduser().resolve() if project_root is not None else None
    if not user.exists() or not user.is_dir():
        raise _fail("knowledge_read_error", "User root must be an existing directory", {"path": str(user)})
    if project is not None and (not project.exists() or not project.is_dir()):
        raise _fail("knowledge_read_error", "Project root must be an existing directory", {"path": str(project)})

    language = _language_policy(project, user)
    diagnostics: List[Diagnostic] = []
    documents: List[CatalogDocument] = []
    indexes: List[IndexDocument] = []
    raw: Dict[str, bytes] = {}

    def add_index(owner: str, relative: str, root: Path) -> Optional[IndexDocument]:
        path = root.joinpath(*relative.split("/"))
        data = _read_bytes(path)
        if data is None:
            return None
        text = _decode(data, path)
        raw[_key(owner, relative)] = data
        document = IndexDocument(owner, relative, path, text, _sha256_bytes(data), _key(owner, relative))
        indexes.append(document)
        return document

    def add_knowledge(owner: str, category: str, root: Path, path: Path) -> None:
        relative = "/".join(path.relative_to(root).parts)
        data = _read_bytes(path)
        if data is None:
            return
        try:
            text = _decode(data, path)
        except DomainError as exc:
            diagnostics.append(Diagnostic(exc.code, exc.message, exc.details.get("path"), None,
                                          exc.details, blocking=True))
            return
        expected_type = CATEGORY_TYPES[category]
        try:
            document = parse_knowledge(text, path=path, expected_type=expected_type)
        except DomainError as exc:
            diagnostics.append(Diagnostic(exc.code, exc.message, path, exc.details.get("line"),
                                          exc.details, blocking=True))
            return
        raw[_key(owner, relative)] = data
        active = document.status == "active"
        effective = active and (document.type != "memory" or document.trust == "confirmed")
        documents.append(CatalogDocument(
            owner=owner, category=category, relative=relative, path=path,
            role=document.type, metadata=dict(document.metadata), body=document.body,
            digest=document.digest, active=active, effective=effective,
            language=language[CATEGORY_LANGUAGE_ROLE[category]], key=_key(owner, relative)))

    def add_plain(owner: str, category: str, root: Path, path: Path) -> None:
        relative = "/".join(path.relative_to(root).parts)
        data = _read_bytes(path)
        if data is None:
            return
        text = _decode(data, path)
        if _declares_knowledge_schema(text):
            diagnostics.append(Diagnostic("knowledge_invalid_schema",
                                          "Context and reference documents must not use the knowledge frontmatter",
                                          path=path, line=1, blocking=True))
            return
        raw[_key(owner, relative)] = data
        documents.append(CatalogDocument(
            owner=owner, category=category, relative=relative, path=path,
            role=CATEGORY_LANGUAGE_ROLE[category], metadata={}, body=text,
            digest=_sha256_bytes(data), active=True, effective=True,
            language=language[CATEGORY_LANGUAGE_ROLE[category]], key=_key(owner, relative)))

    user_index = add_index(OWNER_USER, _index_relative(OWNER_USER), user)
    for category, directory in sorted(CATEGORY_DIRS[OWNER_USER].items()):
        base = user.joinpath(*directory.split("/"))
        files, links = _walk_files(base)
        for link in links:
            diagnostics.append(Diagnostic("knowledge_unsafe_path",
                                          "Symbolic links are not allowed in managed knowledge directories",
                                          path=link, blocking=True))
        for path in files:
            add_knowledge(OWNER_USER, category, user, path)

    project_index: Optional[IndexDocument] = None
    topics: Tuple[TopicReference, ...] = ()
    authority_refs: Tuple[DocumentReference, ...] = ()
    knowledge_refs: Tuple[DocumentReference, ...] = ()
    if project is not None:
        project_index = add_index(OWNER_PROJECT, _index_relative(OWNER_PROJECT), project)
        for category, directory in sorted(CATEGORY_DIRS[OWNER_PROJECT].items()):
            base = project.joinpath(*directory.split("/"))
            files, links = _walk_files(base)
            for link in links:
                diagnostics.append(Diagnostic("knowledge_unsafe_path",
                                              "Symbolic links are not allowed in managed knowledge directories",
                                              path=link, blocking=True))
            for path in files:
                if category in CATEGORY_TYPES:
                    add_knowledge(OWNER_PROJECT, category, project, path)
                else:
                    add_plain(OWNER_PROJECT, category, project, path)
        if project_index is not None:
            topics, authority_refs, knowledge_refs, index_diagnostics = _parse_project_index(
                project_index.text, project_index.path)
            diagnostics.extend(index_diagnostics)

    # existing authoritative project documents (read only, outside .fstar)
    for reference in authority_refs:
        key = _authority_key(project, reference.path) if project is not None else None
        if key is None:
            diagnostics.append(Diagnostic("knowledge_reference_error",
                                          "Authoritative document is missing or outside the project",
                                          path=project / reference.path if project else None))
            continue
        path = project.joinpath(*key.split(":", 1)[1].split("/"))
        data = _read_bytes(path)
        if data is None:
            continue
        text = _decode(data, path)
        raw[key] = data
        documents.append(CatalogDocument(
            owner=OWNER_PROJECT, category=CATEGORY_AUTHORITY, relative=key.split(":", 1)[1], path=path,
            role=ROLE_AUTHORITY, metadata={}, body=text, digest=_sha256_bytes(data),
            active=True, effective=True, language=language["context"], key=key))

    indexed = _indexed_keys(indexes, topics, authority_refs, knowledge_refs)
    for document in documents:
        if document.category in CATEGORY_TYPES and document.key not in indexed:
            diagnostics.append(Diagnostic("knowledge_unindexed",
                                          "Knowledge document is not reachable from any index",
                                          path=document.path))

    snapshot = content_hash({
        "documents": {key: _sha256_bytes(data) for key, data in sorted(raw.items())},
    })
    return Catalog(user_root=user, project_root=project, documents=tuple(documents),
                   indexes=tuple(indexes), authority_refs=authority_refs,
                   knowledge_refs=knowledge_refs, topic_refs=topics,
                   diagnostics=tuple(diagnostics), snapshot_hash=snapshot,
                   language=dict(language), _raw=dict(raw))


def _declares_knowledge_schema(text: str) -> bool:
    try:
        frontmatter, _, _ = _split_frontmatter(text, Path("<memory>"))
    except DomainError:
        return False
    try:
        values = parse_config(frontmatter, Path("<memory>"))
    except ConfigError:
        return False
    return values.get("schema") == KNOWLEDGE_SCHEMA


def _indexed_keys(indexes: Tuple[IndexDocument, ...], topics: Tuple[TopicReference, ...],
                  authority: Tuple[DocumentReference, ...],
                  knowledge: Tuple[DocumentReference, ...]) -> set:
    keys = set()
    for index in indexes:
        for link in scan_links(index.text):
            file_part, _ = split_fragment(link.target)
            if not file_part:
                continue
            keys.add(_key(index.owner, _norm_rel(file_part)))
    for topic in topics:
        file_part, _ = split_fragment(topic.path)
        if file_part:
            try:
                keys.add(_key(OWNER_PROJECT, _norm_rel(file_part)))
            except DomainError:
                continue
    for reference in list(authority) + list(knowledge):
        file_part, _ = split_fragment(reference.path)
        if not file_part:
            continue
        try:
            keys.add(_key(OWNER_PROJECT, _norm_rel(file_part)))
        except DomainError:
            continue
    return keys


# ---------------------------------------------------------------------------
# selection, reading and resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Applicability:
    """Applicability of one document.  ``unknown`` broadens the reading."""

    state: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state not in (APPLICABILITY_INCLUDE, APPLICABILITY_EXCLUDE, APPLICABILITY_UNKNOWN):
            raise _fail("knowledge_invalid_schema", "Unknown applicability state",
                        {"field": "applicability.state", "expected":
                         [APPLICABILITY_INCLUDE, APPLICABILITY_EXCLUDE, APPLICABILITY_UNKNOWN],
                         "actual": self.state})


@dataclass(frozen=True)
class ReadSelection:
    """What the caller wants to read.  Paths use the ``owner:relative`` form."""

    topics: Tuple[str, ...] = ()
    documents: Tuple[str, ...] = ()
    dependencies: Tuple[str, ...] = ()
    global_constraints: Tuple[str, ...] = ()
    excluded: Tuple[str, ...] = ()
    applicability: Mapping[str, Applicability] = field(default_factory=dict)
    snapshot_hash: str = ""


@dataclass(frozen=True)
class ContextDocument:
    owner: str
    relative: str
    path: Path
    role: str
    digest: str
    size: int
    text: str
    language: str
    tier: Optional[int]
    rank: int
    key: str


@dataclass(frozen=True)
class Exclusion:
    key: str
    owner: str
    relative: str
    path: Optional[Path]
    role: str
    reason: str


@dataclass(frozen=True)
class RequiredUnloaded:
    key: str
    owner: str
    relative: str
    path: Optional[Path]
    role: str
    reason: str
    digest: Optional[str] = None


@dataclass(frozen=True)
class ContextBundle:
    """Complete applicable reading.  ``complete`` is structural only."""

    full_documents: Tuple[ContextDocument, ...]
    excluded: Tuple[Exclusion, ...]
    required_unloaded: Tuple[RequiredUnloaded, ...]
    conflicts_pending: bool
    complete: bool
    snapshot_hash: str
    language: Mapping[str, str] = field(default_factory=dict)


def _resolve_link(owner: str, source_relative: str, target: str, *, from_index: bool) -> Optional[str]:
    file_part, _ = split_fragment(target)
    if not file_part or _EXTERNAL.match(file_part):
        return None
    try:
        if from_index:
            relative = _norm_rel(file_part)
        else:
            if file_part.startswith("/") or "\\" in file_part or "\x00" in file_part:
                return None
            parts = list(PurePosixPath(source_relative).parent.parts)
            for part in file_part.split("/"):
                if part in ("", "."):
                    continue
                if part == "..":
                    if not parts:
                        return None
                    parts.pop()
                else:
                    parts.append(part)
            relative = _norm_rel("/".join(parts))
    except DomainError:
        return None
    return _key(owner, relative)


def _tier_for(document: CatalogDocument) -> Tuple[Optional[int], int]:
    if document.role == ROLE_AUTHORITY:
        return TIER_PROJECT, 0
    if document.category == CATEGORY_RULES:
        if document.strength == "enforced":
            return TIER_ENFORCED_RULE, 0
        return TIER_DEFAULT_RULE, 0
    if document.category == CATEGORY_MEMORY:
        return TIER_CONFIRMED_MEMORY, 0
    if document.category == CATEGORY_SPECS:
        return TIER_PROJECT, 1
    return None, 0


def load_context(catalog: Catalog, *, selection: ReadSelection,
                 max_bytes: Optional[int] = None) -> ContextBundle:
    """Read the complete applicable knowledge for one selection.

    The reading order is overview, complete indexes, global constraints and
    existing authority first, then the scoped topic bodies and their
    upstream/downstream/shared contracts.  Bodies are never sliced or
    summarised: a body that does not fit the budget is deferred whole and
    itemized, and the bundle then reports ``complete=False``.
    """

    if not isinstance(selection, ReadSelection):
        raise _fail("knowledge_invalid_schema", "selection must be a ReadSelection",
                    {"expected": "ReadSelection", "actual": type(selection).__name__})
    if selection.snapshot_hash and selection.snapshot_hash != catalog.snapshot_hash:
        raise _fail("knowledge_context_incomplete", "Selection was made against another knowledge snapshot",
                    {"expected": catalog.snapshot_hash, "actual": selection.snapshot_hash})
    if max_bytes is not None and (not isinstance(max_bytes, int) or max_bytes < 0):
        raise _fail("knowledge_invalid_schema", "max_bytes must be a non-negative integer",
                    {"field": "max_bytes", "actual": max_bytes})

    documents = {document.key: document for document in catalog.documents}
    effective = {key: document for key, document in documents.items() if document.effective}
    excluded: List[Exclusion] = []
    unloaded: List[RequiredUnloaded] = []
    ordered: List[Tuple[str, str]] = []
    seen: set = set()

    def push(key: str, role: str) -> None:
        if key in seen:
            return
        seen.add(key)
        ordered.append((key, role))

    project_index = catalog.index_by_owner(OWNER_PROJECT)
    user_index = catalog.index_by_owner(OWNER_USER)
    if project_index is not None:
        push(project_index.key, ROLE_OVERVIEW)
    if user_index is not None:
        push(user_index.key, ROLE_INDEX)

    user_guidance = sorted(
        (document for document in effective.values()
         if document.category in (CATEGORY_RULES, CATEGORY_MEMORY)),
        key=lambda document: (_tier_for(document)[0] or 0, document.key))
    for document in user_guidance:
        if document.strength == "enforced":
            push(document.key, ROLE_GLOBAL_CONSTRAINT)
        elif document.category == CATEGORY_RULES:
            push(document.key, ROLE_RULE)
        else:
            push(document.key, ROLE_MEMORY)

    for document in sorted(effective.values(), key=lambda item: item.key):
        if document.category == CATEGORY_AUTHORITY:
            push(document.key, ROLE_AUTHORITY)

    topic_ids = list(selection.topics)
    known_topics = {topic.id: topic for topic in catalog.topic_refs}
    broadened = any(topic_id not in known_topics for topic_id in topic_ids)
    if broadened:
        topic_ids = sorted(known_topics)
    selected_topics = [known_topics[topic_id] for topic_id in topic_ids if topic_id in known_topics]

    topic_keys: List[str] = []
    for topic in selected_topics:
        file_part, _ = split_fragment(topic.path)
        if not file_part:
            unloaded.append(RequiredUnloaded(_key(OWNER_PROJECT, topic.id), OWNER_PROJECT, topic.path,
                                             None, ROLE_TOPIC, "topic authority path is missing"))
            continue
        try:
            relative = _norm_rel(file_part)
        except DomainError:
            unloaded.append(RequiredUnloaded(_key(OWNER_PROJECT, topic.id), OWNER_PROJECT, topic.path,
                                             None, ROLE_TOPIC, "topic authority path is not a safe relative path"))
            continue
        key = _key(OWNER_PROJECT, relative)
        topic_keys.append(key)
        if key not in documents:
            unloaded.append(RequiredUnloaded(key, OWNER_PROJECT, relative, None, ROLE_TOPIC,
                                             "topic body is missing"))
            continue
        if key in effective:
            push(key, ROLE_TOPIC)

    for key in selection.documents:
        owner, relative = _split_key(key)
        if owner not in OWNERS:
            unloaded.append(RequiredUnloaded(key, owner, relative, None, ROLE_TOPIC,
                                             "selected document has an unknown owner"))
            continue
        if key not in documents:
            unloaded.append(RequiredUnloaded(key, owner, relative, None, ROLE_TOPIC,
                                             "selected document is missing"))
            continue
        push(key, ROLE_TOPIC)

    for key in selection.global_constraints:
        owner, relative = _split_key(key)
        if key not in documents:
            unloaded.append(RequiredUnloaded(key, owner, relative, None, ROLE_GLOBAL_CONSTRAINT,
                                             "global constraint is missing"))
            continue
        push(key, ROLE_GLOBAL_CONSTRAINT)

    dependency_queue: List[str] = []
    for key in selection.dependencies:
        dependency_queue.append(key)
    for key in topic_keys:
        if key in documents:
            dependency_queue.append(key)
    for key in selection.documents:
        if key in documents:
            dependency_queue.append(key)
    visited: set = set()
    while dependency_queue:
        key = dependency_queue.pop(0)
        if key in visited:
            continue
        visited.add(key)
        document = documents.get(key)
        if document is None:
            owner, relative = _split_key(key)
            unloaded.append(RequiredUnloaded(key, owner, relative, None, ROLE_DEPENDENCY,
                                             "dependency body is missing"))
            continue
        push(key, ROLE_DEPENDENCY)
        for link in scan_links(document.body):
            target = _resolve_link(document.owner, document.relative, link.target, from_index=False)
            if target is None or target in visited:
                continue
            target_document = documents.get(target)
            if target_document is None:
                continue
            if target_document.category not in (CATEGORY_SPECS, CATEGORY_AUTHORITY):
                continue
            dependency_queue.append(target)

    for document in sorted(effective.values(), key=lambda item: item.key):
        if document.category == CATEGORY_CONTEXT:
            push(document.key, ROLE_CONTEXT)
        elif document.category == CATEGORY_REFERENCES:
            push(document.key, ROLE_REFERENCE)

    excluded_keys = set(selection.excluded)
    unknown_applicability = False
    applicable: List[Tuple[str, str]] = []
    for key, role in ordered:
        if key in excluded_keys:
            excluded.append(Exclusion(key, *_split_key(key), None, role, "excluded by the caller selection"))
            continue
        state = selection.applicability.get(key)
        if state is not None and state.state == APPLICABILITY_EXCLUDE:
            excluded.append(Exclusion(key, *_split_key(key), None, role,
                                      "applicability excluded: %s" % (state.reason or "no reason given")))
            continue
        if state is not None and state.state == APPLICABILITY_UNKNOWN:
            unknown_applicability = True
        applicable.append((key, role))

    for document in sorted(documents.values(), key=lambda item: item.key):
        if document.key in seen:
            continue
        if not document.active:
            reason = "document is superseded"
        elif document.category == CATEGORY_MEMORY and document.trust != "confirmed":
            reason = "memory trust is not confirmed"
        elif document.category == CATEGORY_SPECS and document.key not in topic_keys:
            reason = "specification is not referenced by a selected topic"
        else:
            reason = "not selected"
        excluded.append(Exclusion(document.key, document.owner, document.relative, document.path,
                                  document.role, reason))

    full: List[ContextDocument] = []
    used = 0
    for key, role in applicable:
        document = documents.get(key)
        if document is not None:
            text = document.body
            digest = document.digest
            size = len(text.encode("utf-8"))
            path = document.path
            language = document.language
        else:
            index = catalog.index_by_owner(_split_key(key)[0])
            if index is None:
                unloaded.append(RequiredUnloaded(key, *_split_key(key), None, role, "document is missing"))
                continue
            text = index.text
            digest = index.digest
            size = len(text.encode("utf-8"))
            path = index.path
            language = catalog.language.get("index", "en")
        if max_bytes is not None and used + size > max_bytes:
            unloaded.append(RequiredUnloaded(key, *_split_key(key), path, role,
                                             "budget of %d bytes exceeded" % max_bytes, digest))
            continue
        used += size
        tier, rank = (None, 0)
        if document is not None:
            tier, rank = _tier_for(document)
        full.append(ContextDocument(owner=_split_key(key)[0], relative=_split_key(key)[1], path=path,
                                    role=role, digest=digest, size=size, text=text, language=language,
                                    tier=tier, rank=rank, key=key))

    complete = not unloaded and not catalog.blocking_diagnostics
    conflicts_pending = (not complete) or unknown_applicability or broadened or bool(catalog.blocking_diagnostics)
    return ContextBundle(full_documents=tuple(full), excluded=tuple(excluded),
                         required_unloaded=tuple(unloaded), conflicts_pending=conflicts_pending,
                         complete=complete, snapshot_hash=catalog.snapshot_hash,
                         language=dict(catalog.language))


@dataclass(frozen=True)
class ReviewedSource:
    key: str
    digest: str
    role: str = ""


@dataclass(frozen=True)
class ReportedConflict:
    sources: Tuple[str, ...]
    sections: Tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class SemanticAssessment:
    """A reviewed, source-bound semantic assessment.

    It carries the reviewed source hashes, applicability decisions, the
    incompatible source/section pairs a reviewer found, the semantic coverage
    and the language review status.  It cannot prove that a reviewer missed
    nothing; a missing review keeps the resolution incomplete.
    """

    reviewed: Tuple[ReviewedSource, ...] = ()
    applicability: Mapping[str, Applicability] = field(default_factory=dict)
    conflicts: Tuple[ReportedConflict, ...] = ()
    coverage: str = "complete"
    language_reviewed: Tuple[str, ...] = ()
    assessment_hash: str = ""

    def payload(self) -> dict:
        return {
            "reviewed": [{"key": item.key, "digest": item.digest, "role": item.role}
                         for item in self.reviewed],
            "applicability": {key: {"state": value.state, "reason": value.reason}
                              for key, value in sorted(self.applicability.items())},
            "conflicts": [{"sources": list(item.sources), "sections": list(item.sections),
                           "rationale": item.rationale} for item in self.conflicts],
            "coverage": self.coverage,
            "language_reviewed": list(self.language_reviewed),
        }


def assessment_hash(assessment: SemanticAssessment) -> str:
    """Deterministic hash of the reviewable content of an assessment."""

    return content_hash(assessment.payload())


@dataclass(frozen=True)
class ResolvedSource:
    key: str
    owner: str
    relative: str
    role: str
    tier: int
    tier_name: str
    rank: int
    digest: str
    text: str


@dataclass(frozen=True)
class ConflictOutcome:
    sources: Tuple[str, ...]
    sections: Tuple[str, ...]
    status: str  # resolved | unresolved | moot
    winner: Optional[str]
    reason: str
    rationale: str = ""


@dataclass(frozen=True)
class Resolution:
    ordered_sources: Tuple[ResolvedSource, ...]
    conflicts: Tuple[ConflictOutcome, ...]
    unresolved: Tuple[ConflictOutcome, ...]
    complete: bool
    conflicts_pending: bool
    stale_sources: Tuple[str, ...] = ()
    unreviewed_sources: Tuple[str, ...] = ()


def resolve_context(bundle: ContextBundle, *, assessment: Optional[SemanticAssessment]) -> Resolution:
    """Apply the fixed precedence order to a reviewed conflict list.

    enforced rule > explicit project spec > default rule > confirmed memory.
    Inside the project tier an existing authoritative project document
    outranks derived fstar guidance.  Equal tier conflicts stay unresolved.
    """

    if not isinstance(bundle, ContextBundle):
        raise _fail("knowledge_invalid_schema", "bundle must be a ContextBundle",
                    {"expected": "ContextBundle", "actual": type(bundle).__name__})
    by_key = {document.key: document for document in bundle.full_documents}
    ordered_sources: List[ResolvedSource] = []
    for document in bundle.full_documents:
        if document.tier is None:
            continue
        ordered_sources.append(ResolvedSource(key=document.key, owner=document.owner,
                                              relative=document.relative, role=document.role,
                                              tier=document.tier, tier_name=TIER_NAMES.get(document.tier, "unknown"),
                                              rank=document.rank, digest=document.digest, text=document.text))
    ordered_sources.sort(key=lambda item: (item.tier, item.rank, item.key))

    conflicts: List[ConflictOutcome] = []
    unresolved: List[ConflictOutcome] = []
    stale: List[str] = []
    unreviewed: List[str] = []

    if assessment is None:
        for source in ordered_sources:
            unreviewed.append(source.key)
        return Resolution(ordered_sources=tuple(ordered_sources), conflicts=(), unresolved=(),
                           complete=False, conflicts_pending=True,
                           stale_sources=(), unreviewed_sources=tuple(unreviewed))
    if not isinstance(assessment, SemanticAssessment):
        raise _fail("knowledge_invalid_schema", "assessment must be a SemanticAssessment",
                    {"expected": "SemanticAssessment", "actual": type(assessment).__name__})
    computed = assessment_hash(assessment)
    if assessment.assessment_hash and assessment.assessment_hash != computed:
        raise _fail("knowledge_invalid_schema", "Assessment hash does not match the assessment content",
                    {"field": "assessment.assessment_hash", "expected": computed,
                     "actual": assessment.assessment_hash})

    reviewed = {item.key: item for item in assessment.reviewed}
    for key, item in sorted(reviewed.items()):
        document = by_key.get(key)
        if document is None:
            stale.append(key)
        elif document.digest != item.digest:
            stale.append(key)
    for source in ordered_sources:
        if source.key not in reviewed:
            unreviewed.append(source.key)

    for reported in assessment.conflicts:
        sources = tuple(reported.sources)
        participants = []
        ineffective = []
        for source_key in sources:
            document = by_key.get(source_key)
            if document is None or document.tier is None:
                ineffective.append(source_key)
            else:
                participants.append(document)
        if len(participants) < 2:
            conflicts.append(ConflictOutcome(
                sources=sources, sections=tuple(reported.sections), status="moot", winner=None,
                reason="fewer than two effective sources take part in this conflict"
                       + ("; not effective: %s" % ", ".join(ineffective) if ineffective else ""),
                rationale=reported.rationale))
            continue
        best = min((document.tier, document.rank) for document in participants)
        winners = [document for document in participants if (document.tier, document.rank) == best]
        losers = [document for document in participants if document not in winners]
        if len(winners) > 1:
            outcome = ConflictOutcome(
                sources=sources, sections=tuple(reported.sections), status="unresolved", winner=None,
                reason="sources share precedence tier %d (%s); the conflict stays unresolved"
                       % (best[0], TIER_NAMES.get(best[0], "unknown")),
                rationale=reported.rationale)
            conflicts.append(outcome)
            unresolved.append(outcome)
            continue
        winner = winners[0]
        loser_best = min((document.tier, document.rank) for document in losers)
        if best[0] != loser_best[0]:
            reason = "precedence: tier %d (%s) outranks tier %d (%s)" % (
                best[0], TIER_NAMES.get(best[0], "unknown"),
                loser_best[0], TIER_NAMES.get(loser_best[0], "unknown"))
        else:
            reason = ("existing authoritative project documentation outranks derived fstar guidance "
                      "inside the project tier")
        conflicts.append(ConflictOutcome(
            sources=sources, sections=tuple(reported.sections), status="resolved", winner=winner.key,
            reason=reason, rationale=reported.rationale))

    complete = (bundle.complete and assessment.coverage == "complete" and not unresolved
                and not stale and not unreviewed)
    conflicts_pending = (not complete) or bool(unresolved) or bool(stale) or bool(unreviewed)
    return Resolution(ordered_sources=tuple(ordered_sources), conflicts=tuple(conflicts),
                       unresolved=tuple(unresolved), complete=complete,
                       conflicts_pending=conflicts_pending, stale_sources=tuple(sorted(stale)),
                       unreviewed_sources=tuple(sorted(unreviewed)))


# ---------------------------------------------------------------------------
# proposals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeEdit:
    """One requested change.  ``content`` carries the exact resulting bytes."""

    path: str
    owner: str
    action: str
    content: Optional[str] = None
    rename_to: Optional[str] = None


@dataclass(frozen=True)
class TopicChoice:
    topic_id: str
    title: str = ""
    is_new: bool = False
    reason: str = ""
    applies_to: str = ""
    read_when: str = ""


@dataclass(frozen=True)
class SourceRecord:
    source_type: str
    reference: str
    quote: str = ""
    at: str = ""


@dataclass(frozen=True)
class ChangeIntent:
    summary: str
    action: str
    source: SourceRecord
    scope: str
    topic: Optional[TopicChoice] = None
    language: Optional[str] = None
    consent: str = ""
    extra_reference_files: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedEdit:
    owner: str
    relative: str
    action: str  # create | replace | delete
    before_hash: Optional[str]
    before_absent: bool
    after_text: Optional[str]
    after_hash: Optional[str]
    mode: Optional[int]
    key: str


@dataclass(frozen=True)
class IndexEntry:
    key: str
    path: Path
    before_hash: Optional[str]
    after_hash: Optional[str]
    before_text: Optional[str]
    after_text: Optional[str]


@dataclass(frozen=True)
class ReferenceEntry:
    source_key: str
    source_path: Path
    target_key: str
    kind: str
    line: int
    status: str  # ok | review


@dataclass(frozen=True)
class ScannedFile:
    key: str
    path: Path
    digest: str


@dataclass(frozen=True)
class KnowledgeProposal:
    operation_id: str
    action: str
    owner_roots: Mapping[str, Path]
    owners: Tuple[str, ...]
    edits: Tuple[PlannedEdit, ...]
    sources: Tuple[SourceRecord, ...]
    topic: Optional[TopicChoice]
    language: str
    scope: str
    index_inventory: Tuple[IndexEntry, ...]
    reference_inventory: Tuple[ReferenceEntry, ...]
    scanned_files: Tuple[ScannedFile, ...]
    assessment_hash: str
    proposal_hash: str
    catalog_snapshot: str = ""
    consent: str = ""
    summary: str = ""

    def payload(self) -> dict:
        return {
            "action": self.action,
            "assessment_hash": self.assessment_hash,
            "catalog_snapshot": self.catalog_snapshot,
            "consent": self.consent,
            "edits": [{"owner": edit.owner, "relative": edit.relative, "action": edit.action,
                       "before_hash": edit.before_hash, "before_absent": edit.before_absent,
                       "after_text": edit.after_text, "after_hash": edit.after_hash}
                      for edit in self.edits],
            "index_inventory": [{"key": entry.key, "before_hash": entry.before_hash,
                                 "after_hash": entry.after_hash, "after_text": entry.after_text}
                                for entry in self.index_inventory],
            "language": self.language,
            "owners": list(self.owners),
            "owner_roots": {owner: str(root) for owner, root in sorted(self.owner_roots.items())},
            "reference_inventory": [{"source_key": entry.source_key, "target_key": entry.target_key,
                                     "kind": entry.kind, "line": entry.line, "status": entry.status}
                                    for entry in self.reference_inventory],
            "scanned_files": [{"key": item.key, "digest": item.digest} for item in self.scanned_files],
            "scope": self.scope,
            "sources": [{"source_type": item.source_type, "reference": item.reference,
                         "quote": item.quote, "at": item.at} for item in self.sources],
            "summary": self.summary,
            "topic": ({"topic_id": self.topic.topic_id, "title": self.topic.title,
                       "is_new": self.topic.is_new, "reason": self.topic.reason,
                       "applies_to": self.topic.applies_to, "read_when": self.topic.read_when}
                      if self.topic else None),
        }


@dataclass(frozen=True)
class Confirmation:
    """A user confirmation bound to one exact proposal."""

    disposition: str
    source_type: str
    source_ref: str
    user_ref: str = ""
    quote: str = ""
    confirmed_at: str = ""
    proposal_hash: str = ""
    scope: str = ""
    owners: Tuple[str, ...] = ()
    consent: str = ""


@dataclass(frozen=True)
class ChangeReceipt:
    operation_id: str
    proposal_hash: str
    changed_paths: Tuple[str, ...]
    before_hashes: Mapping[str, Optional[str]]
    after_hashes: Mapping[str, Optional[str]]
    recovery: str
    already_applied: bool


def _document_title(text: str, fallback: str) -> str:
    match = _HEADING.search(text)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    return fallback


def _section_bounds(lines: List[str], heading: str) -> Tuple[Optional[int], Optional[int]]:
    target = heading if heading.startswith("## ") else "## " + heading
    start = None
    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index + 1
            break
    if start is None:
        return None, None
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def _upsert_entry(lines: List[str], heading: str, entry: str, marker: str) -> List[str]:
    start, end = _section_bounds(lines, heading)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", "## %s" % heading, "", entry, ""])
        return lines
    for index in range(start, end):
        if marker in lines[index]:
            lines[index] = entry
            return lines
    insert_at = end
    for index in range(end - 1, start - 1, -1):
        if lines[index].strip():
            insert_at = index + 1
            break
    lines.insert(insert_at, entry)
    return lines


def _remove_entry(lines: List[str], heading: str, marker: str) -> List[str]:
    start, end = _section_bounds(lines, heading)
    if start is None:
        return lines
    for index in range(start, end):
        if marker in lines[index]:
            del lines[index]
            break
    return lines


def _topic_block(lines: List[str], topic_id: str) -> Tuple[Optional[int], Optional[int]]:
    start, end = _section_bounds(lines, "主题")
    if start is None:
        return None, None
    for index in range(start, end):
        stripped = lines[index].strip()
        if not stripped.startswith("### "):
            continue
        heading = stripped[4:].strip()
        identifier = heading
        for separator in (" — ", " – ", " - ", ": ", "|"):
            if separator in heading:
                identifier = heading.partition(separator)[0]
                break
        if identifier.strip() == topic_id:
            block_end = end
            for cursor in range(index + 1, end):
                if lines[cursor].strip().startswith("### "):
                    block_end = cursor
                    break
            return index, block_end
    return None, None


def _upsert_topic(lines: List[str], topic: TopicChoice, authority: str) -> List[str]:
    start, end = _section_bounds(lines, "主题")
    block_start, block_end = _topic_block(lines, topic.topic_id)
    if block_start is None:
        if start is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend(["", "## 主题", "",
                          "### %s — %s" % (topic.topic_id, topic.title or topic.topic_id),
                          "- Applies to: %s" % (topic.applies_to or topic.reason),
                          "- Read when: %s" % (topic.read_when or topic.reason),
                          "- Authority: [%s](%s)" % (authority, authority), ""])
            return lines
        insert_at = end
        for index in range(end - 1, start - 1, -1):
            if lines[index].strip():
                insert_at = index + 1
                break
        block = ["### %s — %s" % (topic.topic_id, topic.title or topic.topic_id),
                 "- Applies to: %s" % (topic.applies_to or topic.reason),
                 "- Read when: %s" % (topic.read_when or topic.reason),
                 "- Authority: [%s](%s)" % (authority, authority)]
        for offset, line in enumerate(block):
            lines.insert(insert_at + offset, line)
        return lines
    authority_line = "- Authority: [%s](%s)" % (authority, authority)
    for index in range(block_start + 1, block_end):
        if lines[index].strip().lower().startswith("- authority:"):
            if lines[index].strip() != authority_line:
                lines[index] = authority_line
            return lines
    lines.insert(block_end, authority_line)
    return lines


def _remove_topic(lines: List[str], topic_id: str, authority: str) -> List[str]:
    block_start, block_end = _topic_block(lines, topic_id)
    if block_start is None:
        return lines
    for index in range(block_start + 1, block_end):
        if lines[index].strip().lower().startswith("- authority:"):
            if authority not in lines[index]:
                return lines
            del lines[index]
            remaining = range(block_start + 1, block_end - 1)
            if not any(lines[cursor].strip().lower().startswith("- authority:") for cursor in remaining):
                del lines[block_start:block_end]
            return lines
    return lines


def _is_subsequence(needle: List[str], haystack: List[str]) -> bool:
    iterator = iter(haystack)
    return all(any(item == candidate for item in iterator) for candidate in needle)


def _prose_preserved(before: str, after: str, markers: Sequence[str]) -> bool:
    kept = [line for line in before.split("\n")
            if line.strip() and not any(marker in line for marker in markers)]
    return _is_subsequence(kept, [line for line in after.split("\n") if line.strip()])


def _require_initialized_project(project_root: Path) -> None:
    marker = project_root / ".fstar" / ".schema-version"
    if not marker.is_file():
        raise _fail("knowledge_invalid_schema", "Project writes require an initialized project (schema 1)",
                    {"path": str(marker), "expected": "1", "actual": None})
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise _fail("knowledge_read_error", "Schema marker cannot be read",
                    {"path": str(marker), "reason": str(exc)})
    if value != "1":
        raise _fail("knowledge_invalid_schema", "Project writes require an initialized project (schema 1)",
                    {"path": str(marker), "expected": "1", "actual": value})


def prepare_change(catalog: Catalog, *, edits: Sequence[KnowledgeEdit], intent: ChangeIntent,
                   assessment: SemanticAssessment) -> KnowledgeProposal:
    """Build an exact-byte proposal.  Nothing is written and no candidate is kept."""

    if not isinstance(catalog, Catalog):
        raise _fail("knowledge_invalid_schema", "catalog must be a Catalog",
                    {"expected": "Catalog", "actual": type(catalog).__name__})
    if not isinstance(intent, ChangeIntent):
        raise _fail("knowledge_invalid_schema", "intent must be a ChangeIntent",
                    {"expected": "ChangeIntent", "actual": type(intent).__name__})
    if assessment is None:
        raise _fail("knowledge_invalid_schema", "A semantic assessment is required to prepare a change",
                    {"field": "assessment"})
    if not isinstance(assessment, SemanticAssessment):
        raise _fail("knowledge_invalid_schema", "assessment must be a SemanticAssessment",
                    {"expected": "SemanticAssessment", "actual": type(assessment).__name__})
    if intent.action not in INTENT_ACTIONS:
        raise _fail("knowledge_invalid_schema", "Unknown change intent",
                    {"field": "intent.action", "expected": list(INTENT_ACTIONS), "actual": intent.action})
    if not intent.summary.strip():
        raise _fail("knowledge_invalid_schema", "A change needs a summary",
                    {"field": "intent.summary"})
    if not intent.scope.strip():
        raise _fail("knowledge_invalid_schema", "A change needs an explicit authorization scope",
                    {"field": "intent.scope"})
    if intent.source.source_type not in SOURCE_TYPES:
        raise _fail("knowledge_invalid_schema", "Unknown source type",
                    {"field": "intent.source.source_type", "expected": list(SOURCE_TYPES),
                     "actual": intent.source.source_type})
    if not intent.source.reference.strip():
        raise _fail("knowledge_invalid_schema", "A change needs a traceable source",
                    {"field": "intent.source.reference"})
    if intent.action == "promote" and not intent.consent.strip():
        raise _fail("knowledge_confirmation_required",
                    "Promoting a memory to a rule needs its own explicit consent",
                    {"field": "intent.consent"})
    computed_assessment = assessment_hash(assessment)
    if assessment.assessment_hash and assessment.assessment_hash != computed_assessment:
        raise _fail("knowledge_invalid_schema", "Assessment hash does not match the assessment content",
                    {"field": "assessment.assessment_hash", "expected": computed_assessment,
                     "actual": assessment.assessment_hash})
    if not isinstance(edits, (list, tuple)) or not edits:
        raise _fail("knowledge_invalid_schema", "edits must be a non-empty sequence",
                    {"field": "edits", "actual": type(edits).__name__})

    owner_roots: Dict[str, Path] = {}
    for edit in edits:
        if not isinstance(edit, KnowledgeEdit):
            raise _fail("knowledge_invalid_schema", "Each edit must be a KnowledgeEdit",
                        {"expected": "KnowledgeEdit", "actual": type(edit).__name__})
        owner = _normalize_owner(edit.owner)
        if edit.action not in EDIT_ACTIONS:
            raise _fail("knowledge_invalid_schema", "Unknown edit action",
                        {"field": "edit.action", "expected": list(EDIT_ACTIONS), "actual": edit.action})
        if owner == OWNER_PROJECT:
            if catalog.project_root is None:
                raise _fail("knowledge_unsafe_path", "The catalog has no project root",
                            {"field": "edit.owner", "actual": owner})
            _require_initialized_project(catalog.project_root)
        owner_roots.setdefault(owner, catalog.user_root if owner == OWNER_USER else catalog.project_root)

    topic = intent.topic
    known_topics = {item.id for item in catalog.topic_refs}
    if topic is not None:
        if not isinstance(topic, TopicChoice):
            raise _fail("knowledge_invalid_schema", "topic must be a TopicChoice",
                        {"expected": "TopicChoice", "actual": type(topic).__name__})
        if topic.is_new:
            if not topic.reason.strip():
                raise _fail("knowledge_invalid_schema", "A new topic needs a reason",
                            {"field": "topic.reason"})
        else:
            if not topic.topic_id.strip():
                raise _fail("knowledge_invalid_schema", "A topic id is required",
                            {"field": "topic.topic_id"})
            if topic.topic_id not in known_topics:
                raise _fail("knowledge_reference_error",
                            "Topic is not in the project index; explain why a new topic is needed",
                            {"field": "topic.topic_id", "expected": sorted(known_topics),
                             "actual": topic.topic_id})

    documents = {document.key: document for document in catalog.documents}
    topic_authority = next((split_fragment(item.path)[0] for item in catalog.topic_refs
                            if topic is not None and item.id == topic.topic_id), None)
    planned: List[PlannedEdit] = []
    index_changes: Dict[str, List[Tuple]] = {}
    affected_keys: set = set()
    required_review: List[Tuple[str, str]] = []
    supplied_index: Dict[str, str] = {}
    touched_documents: List[Tuple[str, CatalogDocument, Optional[str]]] = []

    def record_index(owner: str, kind: str, *arguments) -> None:
        index_changes.setdefault(owner, []).append((kind,) + arguments)

    for edit in edits:
        owner = _normalize_owner(edit.owner)
        root = owner_roots[owner]
        relative = _norm_rel(edit.path)
        target = _safe_target(root, relative)
        category = _category_for(owner, relative)
        if category is None and relative != _index_relative(owner):
            raise _fail("knowledge_unsafe_path", "Path is outside the managed knowledge categories",
                        {"path": relative, "owner": owner})
        if relative == _index_relative(owner) and edit.content is not None:
            supplied_index[owner] = edit.content
        current = _read_bytes(target)
        if edit.action == "create":
            if current is not None:
                raise _fail("knowledge_write_conflict", "Target already exists",
                            {"path": relative, "owner": owner, "expected": "absent"})
            if edit.content is None:
                raise _fail("knowledge_invalid_schema", "A create needs the exact resulting content",
                            {"field": "edit.content", "path": relative})
            after_text = edit.content
            before_hash = None
            before_absent = True
            action = "create"
        elif edit.action in ("replace", "supersede"):
            if current is None:
                raise _fail("knowledge_write_conflict", "Target does not exist",
                            {"path": relative, "owner": owner, "expected": "present"})
            if edit.content is None:
                raise _fail("knowledge_invalid_schema", "A replacement needs the exact resulting content",
                            {"field": "edit.content", "path": relative})
            after_text = edit.content
            before_hash = _sha256_bytes(current)
            before_absent = False
            action = "replace"
        elif edit.action == "delete":
            if current is None:
                raise _fail("knowledge_write_conflict", "Target does not exist",
                            {"path": relative, "owner": owner, "expected": "present"})
            after_text = None
            before_hash = _sha256_bytes(current)
            before_absent = False
            action = "delete"
        elif edit.action == "rename":
            if current is None:
                raise _fail("knowledge_write_conflict", "Rename target does not exist",
                            {"path": relative, "owner": owner, "expected": "present"})
            if not edit.rename_to:
                raise _fail("knowledge_invalid_schema", "A rename needs the new path",
                            {"field": "edit.rename_to", "path": relative})
            new_relative = _norm_rel(edit.rename_to)
            new_target = _safe_target(root, new_relative)
            if _category_for(owner, new_relative) is None:
                raise _fail("knowledge_unsafe_path", "Rename target is outside the managed knowledge categories",
                            {"path": new_relative, "owner": owner})
            if _read_bytes(new_target) is not None:
                raise _fail("knowledge_write_conflict", "Rename target already exists",
                            {"path": new_relative, "owner": owner, "expected": "absent"})
            after_text = edit.content if edit.content is not None else current.decode("utf-8")
            new_category = _category_for(owner, new_relative)
            _validate_document_content(owner, new_category, new_relative, after_text)
            current_hash = _sha256_bytes(current)
            document = documents.get(_key(owner, relative))
            if document is not None and document.digest != current_hash:
                raise _fail("knowledge_write_conflict", "Document changed since the catalog snapshot",
                            {"path": relative, "owner": owner,
                             "expected": document.digest, "actual": current_hash})
            if _category_for(owner, relative) in CATEGORY_TYPES:
                required_review.append((_key(owner, relative), current_hash))
            planned.append(PlannedEdit(owner=owner, relative=new_relative, action="create",
                                        before_hash=None, before_absent=True, after_text=after_text,
                                        after_hash=_sha256_text(after_text), mode=None,
                                        key=_key(owner, new_relative)))
            planned.append(PlannedEdit(owner=owner, relative=relative, action="delete",
                                        before_hash=_sha256_bytes(current), before_absent=False,
                                        after_text=None, after_hash=None, mode=None,
                                        key=_key(owner, relative)))
            affected_keys.add(_key(owner, relative))
            affected_keys.add(_key(owner, new_relative))
            required_review.append((_key(owner, relative), _sha256_bytes(current)))
            document = documents.get(_key(owner, relative))
            if document is not None:
                touched_documents.append((_key(owner, new_relative), document, after_text))
            if new_category != CATEGORY_SPECS or topic is None or topic.is_new or relative == topic_authority:
                _plan_index_entry(record_index, owner, new_category, new_relative, after_text,
                                  document, delete_old=True, old_relative=relative, topic=topic,
                                  action="rename")
            continue
        else:  # pragma: no cover - guarded above
            raise _fail("knowledge_invalid_schema", "Unknown edit action", {"field": "edit.action"})

        if category is not None and category in CATEGORY_TYPES:
            _validate_document_content(owner, category, relative, after_text)
            document = documents.get(_key(owner, relative))
            if document is not None and document.digest != _sha256_bytes(current or b""):
                raise _fail("knowledge_write_conflict", "Document changed since the catalog snapshot",
                            {"path": relative, "owner": owner,
                             "expected": document.digest, "actual": _sha256_bytes(current or b"")})
            if current is not None:
                required_review.append((_key(owner, relative), _sha256_bytes(current)))
            else:  # pragma: no cover - guarded by the existence checks above
                required_review.append((_key(owner, relative), None))
        planned.append(PlannedEdit(owner=owner, relative=relative, action=action,
                                    before_hash=before_hash, before_absent=before_absent,
                                    after_text=after_text,
                                    after_hash=_sha256_text(after_text) if after_text is not None else None,
                                    mode=None, key=_key(owner, relative)))
        affected_keys.add(_key(owner, relative))
        document = documents.get(_key(owner, relative))
        if document is not None:
            touched_documents.append((_key(owner, relative), document, after_text))
        if category != CATEGORY_SPECS or topic is None or topic.is_new or relative == topic_authority:
            _plan_index_entry(record_index, owner, category, relative, after_text, document,
                              delete_old=False, old_relative=None, topic=topic, action=edit.action)

    reviewed = {item.key: item.digest for item in assessment.reviewed}
    for key, digest in required_review:
        if reviewed.get(key) != digest:
            raise _fail("knowledge_context_incomplete",
                        "The assessment does not cover the affected document",
                        {"path": key, "expected": digest, "actual": reviewed.get(key)})

    index_inventory: List[IndexEntry] = []
    for owner in sorted(set(index_changes) | set(supplied_index)):
        root = owner_roots[owner]
        index_relative = _index_relative(owner)
        index_path = root.joinpath(*index_relative.split("/"))
        current = _read_bytes(index_path)
        before_text = current.decode("utf-8") if current is not None else None
        if before_text is None:
            if owner == OWNER_PROJECT:
                raise _fail("knowledge_reference_error", "The project index is missing",
                            {"path": str(index_path)})
            before_text = "# fstar User Index\n"
        supplied = supplied_index.get(owner)
        if supplied is not None:
            markers = sorted(_split_key(key)[1] for key in affected_keys
                             if _split_key(key)[0] == owner)
            if not _prose_preserved(before_text, supplied, markers):
                raise _fail("knowledge_invalid_schema",
                            "A supplied index edit must preserve unrelated prose",
                            {"path": index_relative, "owner": owner})
            index_inventory.append(IndexEntry(
                key=_key(owner, index_relative), path=index_path,
                before_hash=_sha256_bytes(current) if current is not None else None,
                after_hash=_sha256_text(supplied), before_text=before_text, after_text=supplied))
            continue
        lines = before_text.split("\n")
        for change in index_changes.get(owner, ()):
            kind = change[0]
            if kind == "entry":
                lines = _upsert_entry(lines, change[1], change[2], change[3])
            elif kind == "remove_entry":
                lines = _remove_entry(lines, change[1], change[2])
            elif kind == "topic":
                lines = _upsert_topic(lines, change[1], change[2])
            elif kind == "topic_remove":
                lines = _remove_topic(lines, change[1], change[2])
        after_text = "\n".join(lines)
        index_inventory.append(IndexEntry(key=_key(owner, index_relative), path=index_path,
                                         before_hash=_sha256_bytes(current) if current is not None else None,
                                         after_hash=_sha256_text(after_text),
                                         before_text=before_text, after_text=after_text))

    planned_keys = {edit.key for edit in planned}
    planned.extend(PlannedEdit(owner=entry.key.split(":", 1)[0],
                                relative=entry.key.split(":", 1)[1], action="replace",
                                before_hash=entry.before_hash,
                                before_absent=entry.before_hash is None,
                                after_text=entry.after_text, after_hash=entry.after_hash,
                                mode=None, key=entry.key)
                     for entry in index_inventory if entry.key not in planned_keys)

    reference_inventory, scanned_files = _reference_inventory(catalog, owner_roots, planned,
                                                               affected_keys, intent)

    language = intent.language or _language_for_edits(catalog, planned)
    payload = {
        "action": intent.action,
        "assessment_hash": computed_assessment,
        "catalog_snapshot": catalog.snapshot_hash,
        "consent": intent.consent,
        "edits": [{"owner": edit.owner, "relative": edit.relative, "action": edit.action,
                   "before_hash": edit.before_hash, "before_absent": edit.before_absent,
                   "after_text": edit.after_text, "after_hash": edit.after_hash}
                  for edit in planned],
        "index_inventory": [{"key": entry.key, "before_hash": entry.before_hash,
                             "after_hash": entry.after_hash, "after_text": entry.after_text}
                            for entry in index_inventory],
        "language": language,
        "owners": sorted(owner_roots),
        "owner_roots": {owner: str(root) for owner, root in sorted(owner_roots.items())},
        "reference_inventory": [{"source_key": entry.source_key, "target_key": entry.target_key,
                                 "kind": entry.kind, "line": entry.line, "status": entry.status}
                                for entry in reference_inventory],
        "scanned_files": [{"key": item.key, "digest": item.digest} for item in scanned_files],
        "scope": intent.scope,
        "sources": [{"source_type": intent.source.source_type, "reference": intent.source.reference,
                     "quote": intent.source.quote, "at": intent.source.at}],
        "summary": intent.summary,
        "topic": ({"topic_id": topic.topic_id, "title": topic.title, "is_new": topic.is_new,
                   "reason": topic.reason, "applies_to": topic.applies_to, "read_when": topic.read_when}
                  if topic else None),
    }
    proposal_hash = content_hash(payload)
    return KnowledgeProposal(operation_id=str(uuid.uuid4()), action=intent.action,
                             owner_roots=dict(owner_roots), owners=tuple(sorted(owner_roots)),
                             edits=tuple(planned), sources=(intent.source,), topic=topic,
                             language=language, scope=intent.scope, index_inventory=tuple(index_inventory),
                             reference_inventory=tuple(reference_inventory),
                             scanned_files=tuple(scanned_files), assessment_hash=computed_assessment,
                             proposal_hash=proposal_hash, catalog_snapshot=catalog.snapshot_hash,
                             consent=intent.consent, summary=intent.summary)


def _language_for_edits(catalog: Catalog, planned: Sequence[PlannedEdit]) -> str:
    for edit in planned:
        category = _category_for(edit.owner, edit.relative)
        if category in CATEGORY_TYPES:
            return catalog.language.get(CATEGORY_LANGUAGE_ROLE[category], "en")
    return catalog.language.get("index", "en")


def _validate_document_content(owner: str, category: Optional[str], relative: str,
                               text: Optional[str]) -> None:
    if text is None or category is None:
        return
    if category in CATEGORY_TYPES:
        try:
            parse_knowledge(text, path=relative, expected_type=CATEGORY_TYPES[category])
        except DomainError as exc:
            raise _fail("knowledge_invalid_schema", exc.message, exc.details)
    elif _declares_knowledge_schema(text):
        raise _fail("knowledge_invalid_schema",
                    "Context and reference documents must not use the knowledge frontmatter",
                    {"path": relative, "owner": owner})


def _plan_index_entry(record_index, owner: str, category: Optional[str], relative: str,
                      after_text: Optional[str], document: Optional[CatalogDocument],
                      *, delete_old: bool, old_relative: Optional[str],
                      topic: Optional[TopicChoice], action: str) -> None:
    if category is None:
        return
    navigation_target = old_relative or relative
    retired = after_text is None or action == "supersede"
    if old_relative and old_relative != relative:
        if owner == OWNER_USER:
            record_index(owner, "remove_entry",
                         "Rules" if category == CATEGORY_RULES else "Memory", old_relative)
        elif category not in CATEGORY_TYPES:
            record_index(owner, "remove_entry", "长期知识", old_relative)
    if owner == OWNER_USER:
        heading = "Rules" if category == CATEGORY_RULES else "Memory"
        if retired:
            record_index(owner, "remove_entry", heading, navigation_target)
            return
        title = _document_title(after_text, Path(relative).stem)
        if category == CATEGORY_RULES:
            strength = "default"
            for line in after_text.split("\n"):
                if line.strip().startswith("strength:"):
                    strength = line.split(":", 1)[1].strip()
            entry = "- [%s](%s) — strength: %s" % (title, relative, strength)
        else:
            kind = "preference"
            for line in after_text.split("\n"):
                if line.strip().startswith("kind:"):
                    kind = line.split(":", 1)[1].strip()
            entry = "- [%s](%s) — kind: %s" % (title, relative, kind)
        record_index(owner, "entry", heading, entry, relative)
        return
    if category == CATEGORY_SPECS:
        if retired:
            if topic is not None:
                record_index(owner, "topic_remove", topic.topic_id, navigation_target)
            return
        if topic is None:
            raise _fail("knowledge_invalid_schema",
                        "A project specification change needs a topic choice",
                        {"field": "intent.topic", "path": relative})
        record_index(owner, "topic", topic, relative)
        return
    if retired:
        record_index(owner, "remove_entry", "长期知识", navigation_target)
        return
    title = _document_title(after_text, Path(relative).stem)
    entry = "- [%s](%s)" % (title, relative)
    record_index(owner, "entry", "长期知识", entry, relative)


def _reference_inventory(catalog: Catalog, owner_roots: Mapping[str, Path],
                          planned: Sequence[PlannedEdit], affected: set,
                          intent: ChangeIntent) -> Tuple[Tuple[ReferenceEntry, ...], Tuple[ScannedFile, ...]]:
    """Scan the corpus for inbound references and close the reference graph."""

    corpus: Dict[str, Tuple[Path, str, str]] = {}
    for document in catalog.documents:
        corpus[document.key] = (document.path, document.body, document.digest)
    for index in catalog.indexes:
        corpus[index.key] = (index.path, index.text, index.digest)
    for relative in intent.extra_reference_files:
        if catalog.project_root is None:
            raise _fail("knowledge_unsafe_path", "Extra reference files need a project root",
                        {"path": relative})
        candidate = _safe_target(catalog.project_root, relative)
        data = _read_bytes(candidate)
        if data is None:
            raise _fail("knowledge_reference_error", "Extra reference file is missing",
                        {"path": str(candidate)})
        key = _key(OWNER_PROJECT, _norm_rel(relative))
        corpus[key] = (candidate, data.decode("utf-8"), _sha256_bytes(data))

    final: Dict[str, Optional[str]] = {}
    for key, (_, text, _) in corpus.items():
        final[key] = text
    for edit in planned:
        if edit.after_text is None:
            final[edit.key] = None
        else:
            final[edit.key] = edit.after_text

    scanned: List[ScannedFile] = []
    entries: List[ReferenceEntry] = []
    broken: List[dict] = []
    unsupported: List[dict] = []
    for key in sorted(final):
        if key in corpus:
            path, text, digest = corpus[key]
            scanned.append(ScannedFile(key=key, path=path, digest=digest))
        else:
            owner, relative = _split_key(key)
            path = owner_roots[owner].joinpath(*relative.split("/"))
        final_text = final.get(key)
        if final_text is None:
            continue
        owner, relative = _split_key(key)
        from_index = key in {index.key for index in catalog.indexes}
        if has_unsupported_link_syntax(final_text) and (key in affected or key in
                                                       {edit.key for edit in planned}):
            unsupported.append({"source": key, "reason": "wiki style links cannot be rewritten safely"})
        for link in scan_links(final_text):
            target = _resolve_link(owner, relative, link.target, from_index=from_index)
            if target is None:
                file_part, _ = split_fragment(link.target)
                if file_part and not _EXTERNAL.match(file_part) and key in affected:
                    broken.append({"source": key, "line": link.line, "target": link.target,
                                   "reason": "local target is unsafe or outside its owner root"})
                continue
            relevant = target in affected or key in affected
            try:
                exists = _target_exists(target, final, corpus, owner_roots)
            except DomainError:
                if relevant:
                    broken.append({"source": key, "line": link.line, "target": target,
                                   "reason": "target contains a symbolic link"})
                continue
            if link.kind == "definition" and target in affected:
                unsupported.append({"source": key, "line": link.line, "target": target,
                                    "reason": "reference style links must be reviewed by hand"})
                entries.append(ReferenceEntry(key, path, target, link.kind, link.line, "review"))
                continue
            if not exists:
                if relevant:
                    broken.append({"source": key, "line": link.line, "target": target})
                entries.append(ReferenceEntry(key, path, target, link.kind, link.line, "review"))
                continue
            target_text = final.get(target)
            if target_text is not None:
                _, fragment = split_fragment(link.target)
                if fragment and fragment not in heading_anchors(target_text):
                    if relevant:
                        broken.append({"source": key, "line": link.line, "target": target,
                                       "reason": "heading anchor does not exist"})
                    entries.append(ReferenceEntry(key, path, target, link.kind, link.line, "review"))
                    continue
            entries.append(ReferenceEntry(key, path, target, link.kind, link.line, "ok"))
    if broken:
        raise _fail("knowledge_reference_error",
                    "References do not close against the proposed result",
                    {"broken": broken, "files": sorted({item["source"] for item in broken})})
    if unsupported:
        raise _fail("knowledge_reference_error",
                    "Relevant references need manual review before publication",
                    {"unsupported": unsupported, "files": sorted({item["source"] for item in unsupported})})
    return tuple(entries), tuple(scanned)


def _target_exists(target: str, final: Mapping[str, Optional[str]],
                   corpus: Mapping[str, Tuple[Path, str, str]],
                   owner_roots: Mapping[str, Path]) -> bool:
    owner, relative = _split_key(target)
    root = owner_roots.get(owner)
    if root is None:
        return False
    candidate = _safe_target(root, relative)
    if target in final:
        return final[target] is not None
    if target in corpus:
        return True
    return candidate.is_file()


# ---------------------------------------------------------------------------
# locking, transactions and recovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryOutcome:
    operation_id: str
    status: str  # rolled_back | cleaned | conflict
    restored: Tuple[str, ...]
    conflicts: Tuple[str, ...]


@dataclass(frozen=True)
class RecoveryReport:
    outcomes: Tuple[RecoveryOutcome, ...]
    complete: bool


_FAILURE_HOOK = None


def set_failure_hook(hook) -> None:
    """Install a callable invoked at each publication checkpoint.

    This is a test seam: the callable receives the checkpoint name and may
    raise to simulate a failure or a process interruption.
    """

    global _FAILURE_HOOK
    _FAILURE_HOOK = hook


def _inject(point: str) -> None:
    hook = _FAILURE_HOOK
    if hook is not None:
        hook(point)


def _runtime_root(owner: str, root: Path) -> Path:
    if owner == OWNER_USER:
        return root / "runtime" / "knowledge"
    return root / ".fstar" / "runtime" / "knowledge"


class _FileLock:
    def __init__(self, path: Path, timeout: float) -> None:
        self.path = path
        self.timeout = timeout
        self.stream = None

    def acquire(self, *, exclusive: bool, create: bool) -> None:
        if fcntl is None:
            raise _fail("knowledge_unsupported_platform",
                        "POSIX file locking is not available on this platform",
                        {"path": str(self.path)})
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.stream = self.path.open("a+")
            except OSError as exc:
                raise _fail("knowledge_lock_timeout",
                            "The knowledge lock cannot be taken: %s" % exc,
                            {"path": str(self.path)}, status=4)
        else:
            if not self.path.exists():
                return
            try:
                self.stream = self.path.open("r")
            except OSError:
                return
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.stream.fileno(), mode | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._close()
                    raise _fail("knowledge_lock_timeout", "Timed out waiting for the knowledge lock",
                                {"path": str(self.path)}, status=4)
                time.sleep(0.02)
            except OSError as exc:
                self._close()
                raise _fail("knowledge_lock_timeout", "The knowledge lock cannot be taken: %s" % exc,
                            {"path": str(self.path)}, status=4)

    def _close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.close()
            finally:
                self.stream = None

    def release(self) -> None:
        if self.stream is None:
            return
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._close()


def _acquire_owner_locks(owner_roots: Mapping[str, Path], owners: Sequence[str], timeout: float,
                         *, exclusive: bool) -> List[_FileLock]:
    locks: List[_FileLock] = []
    try:
        for owner in _owner_order(owners):
            root = owner_roots.get(owner)
            if root is None:
                continue
            lock = _FileLock(_runtime_root(owner, root) / "lock", timeout)
            lock.acquire(exclusive=exclusive, create=exclusive)
            if lock.stream is not None:
                locks.append(lock)
    except BaseException:
        for lock in locks:
            lock.release()
        raise
    return locks


def _operation_records(owner_roots: Mapping[str, Path]) -> Dict[str, dict]:
    records: Dict[str, dict] = {}
    for owner, root in sorted(owner_roots.items()):
        base = _runtime_root(owner, root) / "operations"
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            record = records.setdefault(entry.name, {"owners": [], "coordinator": None,
                                                     "state": "pending", "root": None})
            participant = entry / "participant.json"
            coordinator = entry / "coordinator.json"
            if participant.is_file():
                record["owners"].append(owner)
                record["root"] = str(_runtime_root(owner, root))
            if coordinator.is_file():
                record["coordinator"] = coordinator
                try:
                    data = json.loads(coordinator.read_text(encoding="utf-8"))
                    record["state"] = data.get("state", "pending")
                except (OSError, ValueError):
                    record["state"] = "corrupt"
    return records


def _pending_operations(owner_roots: Mapping[str, Path]) -> Dict[str, dict]:
    return {operation: record for operation, record in _operation_records(owner_roots).items()
            if record["state"] != "committed"}


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_durable(path: Path, data: bytes) -> None:
    with open(str(path), "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".fstar-tmp",
                                             dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        temporary = None
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    _fsync_dir(path.parent)


def _validate_confirmation(proposal: KnowledgeProposal, confirmation: Confirmation) -> None:
    if confirmation.disposition not in DISPOSITIONS:
        raise _fail("knowledge_confirmation_required", "Unknown confirmation disposition",
                    {"expected": list(DISPOSITIONS), "actual": confirmation.disposition})
    if confirmation.disposition != "approved":
        raise _fail("knowledge_confirmation_required",
                    "The proposal was not approved; no knowledge is written",
                    {"disposition": confirmation.disposition, "proposal": proposal.proposal_hash})
    if confirmation.source_type not in SOURCE_TYPES:
        raise _fail("knowledge_confirmation_required", "Unknown confirmation source type",
                    {"expected": list(SOURCE_TYPES), "actual": confirmation.source_type})
    if not confirmation.source_ref.strip():
        raise _fail("knowledge_confirmation_required", "The confirmation needs a source reference",
                    {"field": "confirmation.source_ref"})
    if not confirmation.quote.strip():
        raise _fail("knowledge_confirmation_required", "The confirmation needs the user quote",
                    {"field": "confirmation.quote"})
    if not confirmation.confirmed_at.strip():
        raise _fail("knowledge_confirmation_required", "The confirmation needs a timestamp",
                    {"field": "confirmation.confirmed_at"})
    if confirmation.source_type == "review" and not confirmation.user_ref.strip():
        raise _fail("knowledge_confirmation_required",
                    "A review source must link the user confirmation",
                    {"field": "confirmation.user_ref"})
    if confirmation.proposal_hash != proposal.proposal_hash:
        raise _fail("knowledge_confirmation_mismatch", "The confirmation does not match this proposal",
                    {"expected": proposal.proposal_hash, "actual": confirmation.proposal_hash})
    if confirmation.scope != proposal.scope:
        raise _fail("knowledge_confirmation_mismatch", "The confirmation scope does not match the proposal",
                    {"expected": proposal.scope, "actual": confirmation.scope})
    if set(confirmation.owners) != set(proposal.owners):
        raise _fail("knowledge_confirmation_mismatch", "The confirmed ownership does not match the proposal",
                    {"expected": sorted(proposal.owners), "actual": sorted(confirmation.owners)})
    if proposal.action == "promote":
        if not proposal.consent.strip() or confirmation.consent != proposal.consent:
            raise _fail("knowledge_confirmation_required",
                        "Promoting a memory into a rule needs its own explicit consent",
                        {"expected": proposal.consent, "actual": confirmation.consent})


def _state_of(path: Path) -> Tuple[bool, Optional[str]]:
    data = _read_bytes(path)
    if data is None:
        return False, None
    return True, _sha256_bytes(data)


def apply_change(proposal: KnowledgeProposal, confirmation: Confirmation, *, user_root,
                 project_root=None) -> ChangeReceipt:
    """Apply one authorized proposal as a recoverable group update."""

    if not isinstance(proposal, KnowledgeProposal):
        raise _fail("knowledge_invalid_schema", "proposal must be a KnowledgeProposal",
                    {"expected": "KnowledgeProposal", "actual": type(proposal).__name__})
    if not isinstance(confirmation, Confirmation):
        raise _fail("knowledge_confirmation_required", "confirmation must be a Confirmation",
                    {"expected": "Confirmation", "actual": type(confirmation).__name__})
    _validate_confirmation(proposal, confirmation)

    user = Path(user_root).expanduser().resolve()
    project = Path(project_root).expanduser().resolve() if project_root is not None else None
    owner_roots = dict(proposal.owner_roots)
    if OWNER_USER in owner_roots and owner_roots[OWNER_USER] != user:
        raise _fail("knowledge_confirmation_mismatch", "The proposal was prepared for another user root",
                    {"expected": str(owner_roots[OWNER_USER]), "actual": str(user)})
    if OWNER_PROJECT in owner_roots:
        if project is None:
            raise _fail("knowledge_confirmation_mismatch", "The proposal needs a project root",
                        {"expected": str(owner_roots[OWNER_PROJECT]), "actual": None})
        if owner_roots[OWNER_PROJECT] != project:
            raise _fail("knowledge_confirmation_mismatch", "The proposal was prepared for another project root",
                        {"expected": str(owner_roots[OWNER_PROJECT]), "actual": str(project)})

    locks = _acquire_owner_locks(owner_roots, proposal.owners, DEFAULT_LOCK_TIMEOUT, exclusive=True)
    try:
        pending = _pending_operations(owner_roots)
        if pending:
            raise _fail("knowledge_recovery_required",
                        "A pending knowledge operation must be recovered before writing",
                        {"operations": sorted(pending)})
        return _apply_locked(proposal, owner_roots)
    finally:
        for lock in locks:
            lock.release()


def _apply_locked(proposal: KnowledgeProposal, owner_roots: Mapping[str, Path]) -> ChangeReceipt:
    before_hashes: Dict[str, Optional[str]] = {}
    after_hashes: Dict[str, Optional[str]] = {}
    for edit in proposal.edits:
        before_hashes[edit.key] = edit.before_hash
        after_hashes[edit.key] = edit.after_hash

    if _already_applied(proposal, owner_roots):
        return ChangeReceipt(operation_id=proposal.operation_id, proposal_hash=proposal.proposal_hash,
                             changed_paths=tuple(edit.key for edit in proposal.edits),
                             before_hashes=before_hashes, after_hashes=after_hashes,
                             recovery="none", already_applied=True)

    for edit in proposal.edits:
        root = owner_roots[edit.owner]
        path = root.joinpath(*edit.relative.split("/"))
        exists, current_hash = _state_of(path)
        if edit.before_absent:
            if exists:
                raise _fail("knowledge_write_conflict", "The target appeared after the proposal was prepared",
                            {"path": edit.key, "expected": "absent", "actual": current_hash})
        else:
            if not exists or current_hash != edit.before_hash:
                raise _fail("knowledge_write_conflict", "The target changed after the proposal was prepared",
                            {"path": edit.key, "expected": edit.before_hash, "actual": current_hash})

    for scanned in proposal.scanned_files:
        owner, relative = _split_key(scanned.key)
        root = owner_roots.get(owner)
        if root is None:
            continue
        path = root.joinpath(*relative.split("/"))
        exists, current_hash = _state_of(path)
        if not exists or current_hash != scanned.digest:
            raise _fail("knowledge_write_conflict",
                        "A referenced file changed after the proposal was prepared",
                        {"path": scanned.key, "expected": scanned.digest, "actual": current_hash})

    operation_id = proposal.operation_id
    coordinator_owner = proposal.owners[0]
    files: List[dict] = []
    created_directories: List[Path] = []
    published: List[dict] = []
    try:
        files = _stage_operation(proposal, owner_roots)
        _inject("stage")
        for owner in _owner_order(proposal.owners):
            runtime = _runtime_root(owner, owner_roots[owner])
            operation_dir = runtime / "operations" / operation_id
            operation_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(operation_dir / "participant.json", {
                "operation_id": operation_id,
                "owner": owner,
                "root": str(owner_roots[owner]),
                "proposal_hash": proposal.proposal_hash,
                "coordinator": str(_runtime_root(coordinator_owner, owner_roots[coordinator_owner])
                                   / "operations" / operation_id / "coordinator.json"),
                "files": [entry for entry in files if entry["owner"] == owner],
            })
        coordinator_dir = (_runtime_root(coordinator_owner, owner_roots[coordinator_owner])
                           / "operations" / operation_id)
        coordinator_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(coordinator_dir / "coordinator.json", {
            "operation_id": operation_id,
            "state": "pending",
            "proposal_hash": proposal.proposal_hash,
            "participants": [{"owner": owner, "root": str(owner_roots[owner])}
                             for owner in _owner_order(proposal.owners)],
            "files": files,
        })
        _inject("coordinator")
        for edit in proposal.edits:
            root = owner_roots[edit.owner]
            path = root.joinpath(*edit.relative.split("/"))
            missing = _missing_directories(path.parent, root)
            created_directories.extend(missing)
            _inject("publish:%s" % edit.key)
            if edit.action == "delete":
                if path.exists():
                    path.unlink()
                    _fsync_dir(path.parent)
            else:
                _publish_bytes(path, edit.after_text.encode("utf-8"))
            published.append({"key": edit.key, "path": str(path), "owner": edit.owner,
                              "relative": edit.relative})
        _inject("validate")
        _validate_published(proposal, owner_roots)
        _inject("commit")
        atomic_write_json(coordinator_dir / "coordinator.json", {
            "operation_id": operation_id,
            "state": "committed",
            "proposal_hash": proposal.proposal_hash,
            "participants": [{"owner": owner, "root": str(owner_roots[owner])}
                             for owner in _owner_order(proposal.owners)],
            "files": files,
        })
    except Exception as exc:
        restored, conflicts = _rollback_files(files, published)
        if conflicts:
            raise _fail("knowledge_recovery_conflict",
                        "The operation failed and an external edit blocks the rollback",
                        {"conflicts": conflicts, "restored": restored,
                         "reason": str(exc), "operation": operation_id}) from exc
        _cleanup_operation(operation_id, owner_roots, proposal.owners)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        if isinstance(exc, DomainError):
            raise
        raise _fail("knowledge_write_conflict", "The knowledge update failed and was rolled back: %s" % exc,
                    {"operation": operation_id, "reason": str(exc)}, status=4) from exc

    cleanup_pending = False
    try:
        _inject("cleanup")
        _cleanup_operation(operation_id, owner_roots, proposal.owners)
    except Exception:
        cleanup_pending = True

    return ChangeReceipt(operation_id=operation_id, proposal_hash=proposal.proposal_hash,
                         changed_paths=tuple(edit.key for edit in proposal.edits),
                         before_hashes=before_hashes, after_hashes=after_hashes,
                         recovery="cleanup_pending" if cleanup_pending else "none",
                         already_applied=False)


def _already_applied(proposal: KnowledgeProposal, owner_roots: Mapping[str, Path]) -> bool:
    for edit in proposal.edits:
        root = owner_roots[edit.owner]
        path = root.joinpath(*edit.relative.split("/"))
        exists, current_hash = _state_of(path)
        if edit.after_hash is None:
            if exists:
                return False
            continue
        if not exists or current_hash != edit.after_hash:
            return False
    return True


def _missing_directories(path: Path, root: Path) -> List[Path]:
    missing: List[Path] = []
    current = path
    while current != root and root in current.parents:
        if current.exists():
            break
        missing.append(current)
        current = current.parent
    return list(reversed(missing))


def _stage_operation(proposal: KnowledgeProposal, owner_roots: Mapping[str, Path]) -> List[dict]:
    files: List[dict] = []
    counters: Dict[str, int] = {}
    for edit in proposal.edits:
        owner = edit.owner
        root = owner_roots[owner]
        path = root.joinpath(*edit.relative.split("/"))
        runtime = _runtime_root(owner, root)
        staging = runtime / "staging" / proposal.operation_id
        staging.mkdir(parents=True, exist_ok=True)
        index = counters.get(owner, 0)
        counters[owner] = index + 1
        before_image = None
        after_image = None
        current = _read_bytes(path)
        if current is not None:
            before_image = staging / ("%d.before" % index)
            _write_durable(before_image, current)
        if edit.after_text is not None:
            after_image = staging / ("%d.after" % index)
            _write_durable(after_image, edit.after_text.encode("utf-8"))
        _fsync_dir(staging)
        files.append({
            "key": edit.key,
            "owner": owner,
            "relative": edit.relative,
            "path": str(path),
            "action": edit.action,
            "before_hash": edit.before_hash,
            "before_absent": edit.before_absent,
            "after_hash": edit.after_hash,
            "after_absent": edit.after_text is None,
            "before_image": str(before_image) if before_image else None,
            "after_image": str(after_image) if after_image else None,
        })
    return files


def _validate_published(proposal: KnowledgeProposal, owner_roots: Mapping[str, Path]) -> None:
    for edit in proposal.edits:
        root = owner_roots[edit.owner]
        path = root.joinpath(*edit.relative.split("/"))
        exists, current_hash = _state_of(path)
        if edit.after_hash is None:
            if exists:
                raise _fail("knowledge_write_conflict", "A deleted document is still present",
                            {"path": edit.key})
            continue
        if not exists or current_hash != edit.after_hash:
            raise _fail("knowledge_write_conflict", "A published document does not match the proposal",
                        {"path": edit.key, "expected": edit.after_hash, "actual": current_hash})


def _rollback_files(files: Sequence[dict], published: Sequence[dict]) -> Tuple[List[str], List[str]]:
    restored: List[str] = []
    conflicts: List[str] = []
    del published
    for entry in reversed(list(files)):
        path = Path(entry["path"])
        exists, current_hash = _state_of(path)
        if current_hash == entry["before_hash"]:
            continue
        if current_hash != entry["after_hash"]:
            conflicts.append(entry.get("key", entry.get("path", "")))
            continue
        if entry["before_absent"]:
            if exists:
                path.unlink()
                _fsync_dir(path.parent)
        elif entry["before_image"]:
            _publish_bytes(path, Path(entry["before_image"]).read_bytes())
        restored.append(entry["relative"])
    return restored, conflicts


def _cleanup_operation(operation_id: str, owner_roots: Mapping[str, Path], owners: Sequence[str]) -> None:
    for owner in _owner_order(owners):
        root = owner_roots.get(owner)
        if root is None:
            continue
        runtime = _runtime_root(owner, root)
        staging = runtime / "staging" / operation_id
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        operation_dir = runtime / "operations" / operation_id
        participant = operation_dir / "participant.json"
        if participant.exists():
            participant.unlink()
        coordinator = operation_dir / "coordinator.json"
        if coordinator.exists():
            coordinator.unlink()
        if operation_dir.exists() and not any(operation_dir.iterdir()):
            try:
                operation_dir.rmdir()
            except OSError:
                pass


def recover_changes(*, user_root, project_root=None) -> RecoveryReport:
    """Explicitly recover pending knowledge operations.

    The call is idempotent, takes the same owner locks as a writer and never
    overwrites an external edit: an unexpected value is reported as a
    recovery conflict and the backups are kept.
    """

    user = Path(user_root).expanduser().resolve()
    project = Path(project_root).expanduser().resolve() if project_root is not None else None
    owner_roots: Dict[str, Path] = {OWNER_USER: user}
    if project is not None:
        owner_roots[OWNER_PROJECT] = project
    locks = _acquire_owner_locks(owner_roots, list(owner_roots), DEFAULT_LOCK_TIMEOUT, exclusive=True)
    try:
        records = _operation_records(owner_roots)
        outcomes: List[RecoveryOutcome] = []
        conflicts: List[str] = []
        for operation_id in sorted(records):
            record = records[operation_id]
            if record["state"] == "committed":
                _cleanup_operation(operation_id, owner_roots, list(owner_roots))
                outcomes.append(RecoveryOutcome(operation_id, "cleaned", (), ()))
                continue
            files = _collect_operation_files(record)
            restored, blocked = _rollback_files(files, [])
            if blocked:
                conflicts.extend(blocked)
                outcomes.append(RecoveryOutcome(operation_id, "conflict", tuple(restored), tuple(blocked)))
                continue
            _cleanup_operation(operation_id, owner_roots, list(owner_roots))
            outcomes.append(RecoveryOutcome(operation_id, "rolled_back", tuple(restored), ()))
        if conflicts:
            raise _fail("knowledge_recovery_conflict",
                        "Recovery found external edits that must not be overwritten",
                        {"conflicts": conflicts,
                         "outcomes": [{"operation": item.operation_id, "status": item.status,
                                       "restored": list(item.restored),
                                       "conflicts": list(item.conflicts)} for item in outcomes]})
        return RecoveryReport(tuple(outcomes), not conflicts)
    finally:
        for lock in locks:
            lock.release()


def _collect_operation_files(record: Mapping[str, object]) -> List[dict]:
    files: List[dict] = []
    coordinator = record.get("coordinator")
    if coordinator is not None:
        try:
            data = json.loads(Path(str(coordinator)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for entry in data.get("files", []):
            files.append(entry)
    return files


# ---------------------------------------------------------------------------
# read side locking
# ---------------------------------------------------------------------------


def _lock_paths(user_root: Path, project_root: Optional[Path]) -> List[Path]:
    paths = [_runtime_root(OWNER_USER, user_root) / "lock"]
    if project_root is not None:
        paths.append(_runtime_root(OWNER_PROJECT, project_root) / "lock")
    return paths



