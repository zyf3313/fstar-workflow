from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence, Tuple

MAP_SCHEMA = "fstar.template-map.v1"
REQUIRED_SLOTS = ("artifact_type", "version", "review_state", "author", "date", "reviewer")
SKILLS = ("init", "clarify", "doc", "plan", "execute", "check", "continue", "archive", "learn", "debug", "help", "tools")
ROLES = ("research", "implement", "check", "editor")
TEMPLATES = (
    "doc/prd.md", "doc/design.md", "task/plan.md", "task/clarify.md", "task/research.md", "task/check.md",
    "knowledge/rule.md", "knowledge/memory.md", "knowledge/spec.md", "entry/user-index.md", "entry/project-index.md",
)
REFERENCES = ("knowledge-format.md", "document-checklist.md", "technical-design-profiles.md")
PLACEHOLDER = re.compile(r"\{\{([^{}\r\n]*)\}\}")
ALLOWED_PLACEHOLDERS = re.compile(r"<!--\s*Allowed placeholders:\s*(.*?)\s*-->")
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class ExtractedItem:
    id: str
    start_marker: str
    end_marker: str
    references: Tuple[str, ...]


@dataclass(frozen=True)
class Extraction:
    artifact: str
    slots: Mapping[str, str]
    items: Tuple[ExtractedItem, ...]
    granularity: str
    diagnostics: Tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics


class ContentError(Exception):
    def __init__(self, code: str, message: str, *, path: Optional[Path] = None, line: int = 1) -> None:
        super().__init__(message)
        self.code, self.path, self.line, self.message = code, path, line, message


class _DuplicateKey(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(str(key))
        result[key] = value
    return result


def load_mapping(path: Path) -> Mapping[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContentError("MAPPING_READ_ERROR", str(exc), path=path)
    try:
        value = json.loads(text, object_pairs_hook=_object,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except _DuplicateKey as exc:
        raise ContentError("MAPPING_DUPLICATE_KEY", "Duplicate mapping key: %s" % exc, path=path)
    except (json.JSONDecodeError, ValueError) as exc:
        line = exc.lineno if isinstance(exc, json.JSONDecodeError) else 1
        raise ContentError("MAPPING_UNSUPPORTED_SYNTAX", "Mapping must use JSON object syntax: %s" % exc, path=path, line=line)
    if not isinstance(value, dict):
        raise ContentError("MAPPING_NOT_OBJECT", "Mapping top level must be an object", path=path)
    if value.get("schema") != MAP_SCHEMA:
        raise ContentError("MAPPING_SCHEMA", "Unsupported mapping schema", path=path)
    if not isinstance(value.get("artifact_type"), str) or not value["artifact_type"]:
        raise ContentError("MAPPING_ARTIFACT_TYPE", "artifact_type must be a non-empty string", path=path)
    items = value.get("items")
    if not isinstance(items, dict) or items.get("mode") not in {"markers", "explicit", "file"}:
        raise ContentError("MAPPING_ITEMS", "items.mode must be markers, explicit, or file", path=path)
    references = value.get("references")
    if references is not None:
        if not isinstance(references, dict) or references.get("mode", "markers") not in {"markers", "explicit"}:
            raise ContentError("MAPPING_REFERENCES", "references.mode must be markers or explicit", path=path)
        separator = references.get("separator", "#")
        if not isinstance(separator, str) or not separator:
            raise ContentError("MAPPING_REFERENCES", "references.separator must be a non-empty string", path=path)
    return value


def _diag(code: str, artifact: str, text: str, offset: int, message: str) -> Diagnostic:
    return Diagnostic(code, artifact, text.count("\n", 0, max(offset, 0)) + 1, message)


def _literal(text: str, start: object, end: object, artifact: str, *, empty: bool = False):
    diagnostics = []
    if not isinstance(start, str) or not start or not isinstance(end, str) or not end or start == end:
        return None, [Diagnostic("INVALID_BOUNDARY", artifact, 1, "Literal start/end markers are required")]
    if text.count(start) != 1 or text.count(end) != 1:
        return None, [Diagnostic("MARKER_COUNT", artifact, 1, "Each marker must occur exactly once")]
    left = text.index(start)
    right = text.index(end)
    if right < left + len(start):
        return None, [_diag("MARKER_ORDER", artifact, text, right, "End marker precedes start marker")]
    value = text[left + len(start):right]
    if not empty and not value.strip():
        diagnostics.append(_diag("EMPTY_VALUE", artifact, text, left, "Required mapped value is empty"))
    return (value, left, right + len(end)), diagnostics


def _normalize_reference(value: str, separator: str) -> Optional[str]:
    path, found, item_id = value.partition(separator)
    if not found or not item_id or not path or "\\" in path:
        return None
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return path + "#" + item_id


def extract_artifact(text: str, mapping: Mapping[str, object], *, artifact: str) -> Extraction:
    diagnostics = []
    slots_out = {}
    slots = mapping.get("slots", {})
    artifact_type = mapping.get("artifact_type")
    if artifact_type in {"prd", "design"} and set(slots if isinstance(slots, dict) else {}) != set(REQUIRED_SLOTS):
        diagnostics.append(Diagnostic("SLOTS_REQUIRED", artifact, 1, "Document mapping must define exactly six semantic slots"))
    if isinstance(slots, dict):
        for name, spec in slots.items():
            if not isinstance(spec, dict):
                diagnostics.append(Diagnostic("SLOT_MAPPING", artifact, 1, "Slot mapping must be an object"))
                continue
            found, errors = _literal(text, spec.get("start_marker"), spec.get("end_marker"), artifact, empty=name == "reviewer")
            diagnostics.extend(errors)
            if found:
                slots_out[name] = found[0]
    else:
        diagnostics.append(Diagnostic("SLOT_MAPPING", artifact, 1, "slots must be an object"))

    item_spec = mapping.get("items", {})
    mode = item_spec.get("mode") if isinstance(item_spec, dict) else None
    if mode == "file":
        return Extraction(artifact, slots_out, (), "file", tuple(diagnostics))
    entries = []
    if mode == "explicit":
        raw_entries = item_spec.get("entries", [])
        if not isinstance(raw_entries, list):
            diagnostics.append(Diagnostic("ITEM_ENTRIES", artifact, 1, "Explicit entries must be an array"))
            raw_entries = []
        entries = raw_entries
    elif mode == "markers":
        start_template, end_template = item_spec.get("start_template"), item_spec.get("end_template")
        if not isinstance(start_template, str) or start_template.count("{id}") != 1 or not isinstance(end_template, str) or end_template.count("{id}") != 1:
            diagnostics.append(Diagnostic("ITEM_TEMPLATE", artifact, 1, "Marker templates require one literal {id} placeholder"))
        else:
            prefix, suffix = start_template.split("{id}")
            pattern = re.compile(re.escape(prefix) + r"([^\r\n\x00-\x1f]+?)" + re.escape(suffix))
            for match in pattern.finditer(text):
                item_id = match.group(1)
                entries.append({"id": item_id, "start_marker": start_template.format(id=item_id),
                                "end_marker": end_template.format(id=item_id)})
    else:
        diagnostics.append(Diagnostic("ITEM_MODE", artifact, 1, "Unsupported item extraction mode"))

    found_items = []
    ranges = []
    seen = set()
    reference_spec = mapping.get("references", {})
    separator = "#"
    if isinstance(reference_spec, dict):
        declared_separator = reference_spec.get("separator")
        if isinstance(declared_separator, str) and declared_separator:
            separator = declared_separator
    explicit_refs = {}
    if isinstance(reference_spec, dict) and reference_spec.get("mode") == "explicit":
        for relation in reference_spec.get("entries", []):
            if isinstance(relation, dict):
                explicit_refs.setdefault(relation.get("source"), []).append(relation.get("target"))
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            diagnostics.append(Diagnostic("ITEM_ID", artifact, 1, "Each item needs a non-empty string id"))
            continue
        item_id = entry["id"]
        if item_id in seen:
            diagnostics.append(Diagnostic("DUPLICATE_ID", artifact, 1, "Duplicate item id: %s" % item_id))
            continue
        seen.add(item_id)
        found, errors = _literal(text, entry.get("start_marker"), entry.get("end_marker"), artifact)
        diagnostics.extend(errors)
        if not found:
            continue
        body, left, right = found
        if any(left < old_right and right > old_left for old_left, old_right in ranges):
            diagnostics.append(_diag("ITEM_OVERLAP", artifact, text, left, "Item ranges overlap or nest"))
            continue
        ranges.append((left, right))
        refs = []
        if isinstance(reference_spec, dict) and reference_spec.get("mode", "markers") == "markers":
            prefix, suffix = reference_spec.get("prefix"), reference_spec.get("suffix")
            if isinstance(prefix, str) and isinstance(suffix, str) and prefix and suffix:
                refs = re.findall(re.escape(prefix) + r"(.*?)" + re.escape(suffix), body)
        else:
            refs = explicit_refs.get(item_id, [])
        normalized_refs = []
        for ref in refs:
            normalized = _normalize_reference(ref, separator) if isinstance(ref, str) else None
            if normalized is None:
                diagnostics.append(_diag("INVALID_REFERENCE", artifact, text, left, "Reference must be relative artifact%sid" % separator))
            else:
                normalized_refs.append(normalized)
        found_items.append(ExtractedItem(item_id, entry["start_marker"], entry["end_marker"], tuple(normalized_refs)))
    if isinstance(reference_spec, dict) and reference_spec.get("mode") == "explicit":
        extracted_ids = {item.id for item in found_items}
        for source, targets in explicit_refs.items():
            if not isinstance(source, str) or source not in extracted_ids:
                diagnostics.append(Diagnostic("UNKNOWN_REFERENCE_SOURCE", artifact, 1,
                                              "Explicit reference source is not an extracted item: %s" % (source,)))
            for target in targets:
                if not isinstance(target, str) or _normalize_reference(target, separator) is None:
                    diagnostics.append(Diagnostic("INVALID_REFERENCE", artifact, 1,
                                                  "Explicit reference target must be relative artifact%sid" % separator))
    return Extraction(artifact, slots_out, tuple(found_items), "item", tuple(diagnostics))


def build_artifact_map(extractions: Sequence[Extraction]) -> Mapping[str, object]:
    invalid = [item for item in extractions if not item.ok]
    if invalid:
        raise ContentError("EXTRACTION_INVALID", "Cannot build artifact map from invalid extraction")
    known = {(extraction.artifact, item.id) for extraction in extractions for item in extraction.items}
    output = {}
    for extraction in extractions:
        artifact_items = {}
        for item in extraction.items:
            dependencies = []
            for reference in item.references:
                target_artifact, target_id = reference.split("#", 1)
                if (target_artifact, target_id) not in known:
                    raise ContentError("REFERENCE_TARGET_MISSING", "Missing reference target: %s" % reference)
                if target_artifact != extraction.artifact:
                    raise ContentError("CROSS_ARTIFACT_DEPENDENCY_UNSUPPORTED", "Core dependencies are artifact-local: %s" % reference)
                dependencies.append(target_id)
            artifact_items[item.id] = {"start_marker": item.start_marker, "end_marker": item.end_marker,
                                       "dependencies": sorted(set(dependencies))}
        if extraction.granularity == "file":
            output.setdefault("mode", "file")
        output[extraction.artifact] = artifact_items
    return output


def _frontmatter(text: str):
    if not text.startswith("---\n"):
        return {}, 1
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, 1
    values = {}
    for number, line in enumerate(text[4:end].splitlines(), 2):
        if ":" not in line:
            return {}, number
        key, value = line.split(":", 1)
        if key.strip() in values:
            return {}, number
        values[key.strip()] = value.strip().strip('"')
    return values, 0


def validate_links(resource_root: Path, paths: Sequence[Path]) -> Sequence[Diagnostic]:
    diagnostics = []
    root = resource_root.resolve()
    pattern = re.compile(r"\[[^]]*\]\(([^)]+)\)")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            target = match.group(1).split("#", 1)[0]
            if not target or "://" in target:
                continue
            candidate = (path.parent / target).resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError:
                diagnostics.append(_diag("LINK_OUTSIDE_ROOT", str(path), text, match.start(), "Link escapes resource root"))
                continue
            if not candidate.is_file():
                diagnostics.append(_diag("LINK_MISSING", str(path), text, match.start(), "Linked resource does not exist"))
    return tuple(diagnostics)


def _placeholder_diagnostics(path: Path, text: str) -> Sequence[Diagnostic]:
    used = PLACEHOLDER.findall(text)
    if not used:
        return ()
    diagnostics = []
    for name in sorted(set(used)):
        if not SNAKE_CASE.match(name):
            diagnostics.append(Diagnostic("PLACEHOLDER_FORMAT", str(path), 1,
                                          "Placeholders must use {{snake_case_name}}: {{%s}}" % name))
    declaration = ALLOWED_PLACEHOLDERS.search(text)
    if not declaration:
        diagnostics.append(Diagnostic("PLACEHOLDER_DECLARATION", str(path), 1,
                                      "Template must declare its allowed placeholders in a leading comment"))
        return tuple(diagnostics)
    declared = set(PLACEHOLDER.findall(declaration.group(1)))
    for name in sorted(set(used) - declared):
        diagnostics.append(Diagnostic("PLACEHOLDER_UNDECLARED", str(path), 1,
                                      "Placeholder is not declared as allowed: {{%s}}" % name))
    return tuple(diagnostics)


def _mapping_diagnostics(root: Path) -> Sequence[Diagnostic]:
    diagnostics = []
    for path in sorted((root / "templates").rglob("*.mapping.yaml")):
        try:
            mapping = load_mapping(path)
        except ContentError as exc:
            diagnostics.append(Diagnostic(exc.code, str(exc.path or path), exc.line, exc.message))
            continue
        template = path.with_name(path.name[:-len(".mapping.yaml")] + ".md")
        if not template.is_file():
            continue
        extraction = extract_artifact(template.read_text(encoding="utf-8"), mapping, artifact=str(template))
        diagnostics.extend(extraction.diagnostics)
    return tuple(diagnostics)


def validate_resources(resource_root: Path) -> Sequence[Diagnostic]:
    diagnostics = []
    root = resource_root
    expected_skills = {root / "skills" / ("fstar-%s" % name) / "SKILL.md" for name in SKILLS}
    expected_roles = {root / "agents" / ("fstar-%s.md" % name) for name in ROLES}
    expected_templates = {root / "templates" / value for value in TEMPLATES}
    actual_skills = set((root / "skills").glob("*/SKILL.md")) if (root / "skills").exists() else set()
    actual_roles = set((root / "agents").glob("fstar-*.md")) if (root / "agents").exists() else set()
    actual_templates = {path for path in (root / "templates").rglob("*.md")} if (root / "templates").exists() else set()
    for path in sorted((expected_skills | expected_roles | expected_templates) - (actual_skills | actual_roles | actual_templates)):
        diagnostics.append(Diagnostic("RESOURCE_MISSING", str(path), 1, "Required resource is missing"))
    for path in sorted((actual_skills - expected_skills) | (actual_roles - expected_roles) | (actual_templates - expected_templates)):
        diagnostics.append(Diagnostic("RESOURCE_EXTRA", str(path), 1, "Unexpected resource in fixed inventory"))
    required_single = (root / "runtime" / "routing.md",) + tuple(root / "references" / name for name in REFERENCES)
    for path in required_single:
        if not path.is_file():
            diagnostics.append(Diagnostic("RESOURCE_MISSING", str(path), 1, "Required resource is missing"))
    descriptions = []
    for path in sorted(actual_skills | actual_roles):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(Diagnostic("RESOURCE_READ", str(path), 1, str(exc)))
            continue
        front, line = _frontmatter(text)
        if line or not front.get("name") or not front.get("description"):
            diagnostics.append(Diagnostic("FRONTMATTER", str(path), line or 1, "name and description simple frontmatter are required"))
            continue
        if path in actual_skills and front["name"] != path.parent.name:
            diagnostics.append(Diagnostic("NAME_MISMATCH", str(path), 2, "Skill name must match its directory"))
        if path in actual_skills:
            descriptions.append(front["description"])
            if len(front["description"]) > 200:
                diagnostics.append(Diagnostic("DESCRIPTION_LIMIT", str(path), 3, "Skill description exceeds 200 characters"))
    if sum(map(len, descriptions)) > 2400:
        diagnostics.append(Diagnostic("DESCRIPTION_TOTAL", str(root / "skills"), 1, "Skill descriptions exceed 2400 characters"))
    text_paths = sorted(path for path in root.rglob("*.md") if path.is_file())
    diagnostics.extend(validate_links(root, text_paths))
    for path in sorted(actual_templates):
        diagnostics.extend(_placeholder_diagnostics(path, path.read_text(encoding="utf-8")))
    diagnostics.extend(_mapping_diagnostics(root))
    return tuple(diagnostics)
