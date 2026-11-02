from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

DEFAULT_CONFIG = {
    "schema_version": 1,
    "auto_commit": False,
    "language": {"interaction": "zh-CN", "artifacts": "zh-CN", "specs": "en"},
}
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
_LANGUAGE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")


@dataclass(frozen=True)
class ConfigWarning:
    code: str
    path: Optional[Path]
    message: str


@dataclass(frozen=True)
class ConfigResult:
    values: Dict[str, object]
    sources: Tuple[Path, ...]
    origins: Dict[str, str]
    warnings: Tuple[ConfigWarning, ...] = ()


class ConfigError(Exception):
    def __init__(self, code: str, message: str, *, path: Optional[Path] = None,
                 line: Optional[int] = None, key: Optional[str] = None) -> None:
        super().__init__(message)
        self.code, self.path, self.line, self.key, self.message = code, path, line, key, message

    def as_dict(self) -> Dict[str, object]:
        return {"error": {"code": self.code, "message": self.message,
                          "details": {"path": str(self.path) if self.path else None,
                                      "line": self.line, "key": self.key}}}


def _error(message: str, path: Path, line: int, code: str = "CONFIG_UNSUPPORTED_SYNTAX") -> ConfigError:
    return ConfigError(code, message, path=path, line=line)


def _strip_comment(text: str, path: Path, line: int) -> str:
    quote = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    escaped = not escaped
                    continue
                if escaped:
                    escaped = False
                    continue
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise _error("Unmatched flow delimiter", path, line)
        elif char == "#" and depth == 0 and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip()
    if quote or depth:
        raise _error("Unclosed quote or flow collection", path, line)
    return text.rstrip()


class _DuplicateKey(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate key %s" % key)
        if not isinstance(key, str) or not _KEY.match(key):
            raise ValueError("invalid key")
        result[key] = value
    return result


def _reject_nonfinite(value: object, path: Path, line: int) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _error("Non-finite number", path, line)
    if isinstance(value, dict):
        for child in value.values():
            _reject_nonfinite(child, path, line)
    elif isinstance(value, list):
        for child in value:
            _reject_nonfinite(child, path, line)


def _scalar(text: str, path: Path, line: int) -> object:
    if not text:
        raise _error("Empty scalar", path, line)
    if text in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[text]
    if text.startswith(("[", "{")):
        try:
            value = json.loads(text, object_pairs_hook=_pairs,
                               parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)))
            _reject_nonfinite(value, path, line)
            return value
        except _DuplicateKey as exc:
            raise ConfigError("CONFIG_DUPLICATE_KEY", str(exc), path=path, line=line)
        except (ValueError, json.JSONDecodeError) as exc:
            raise _error("Invalid JSON flow collection: %s" % exc, path, line)
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _error("Invalid double-quoted string: %s" % exc.msg, path, line)
        if not isinstance(value, str):
            raise _error("Quoted scalar must be a string", path, line)
        return value
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise _error("Unclosed single-quoted string", path, line)
        return text[1:-1].replace("''", "'")
    if _NUMBER.match(text):
        value = float(text) if any(char in text for char in ".eE") else int(text)
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("Non-finite number", path, line)
        return value
    if text.lower() in (".inf", ".nan", "inf", "infinity", "nan", "+inf", "-inf", "+infinity", "-infinity"):
        raise _error("Invalid number", path, line)
    if (re.match(r"^[+-]?(?:0[0-9]+|[0-9][0-9_]*_[0-9_]*|\.[0-9]+)$", text) or
            re.match(r"^\+[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$", text)):
        raise _error("Invalid number", path, line)
    if text.startswith(("-", "?", ":", "!", "&", "*", "|", ">", "@", "`", "%")):
        raise _error("Unsupported scalar indicator", path, line)
    if ": " in text or any(ord(char) < 32 for char in text):
        raise _error("Plain string requires quoting", path, line)
    return text


def parse_config(text: str, path: Path) -> Dict[str, object]:
    if text.startswith("﻿"):
        text = text[1:]
    records = []
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise _error("Tabs are not valid indentation", path, number)
        content = _strip_comment(raw, path, number)
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        if indent % 2:
            raise _error("Indentation must use two spaces per level", path, number)
        stripped = content[indent:]
        if stripped in ("---", "...") or stripped.startswith("%"):
            raise _error("YAML documents and directives are unsupported", path, number)
        records.append((indent, stripped, number))
    if not records:
        return {}

    def block(index: int, indent: int):
        sequence = records[index][1].startswith("-")
        output = [] if sequence else {}
        while index < len(records):
            current_indent, body, line = records[index]
            if current_indent < indent:
                break
            if current_indent != indent:
                raise _error("Unexpected indentation", path, line)
            if sequence:
                if not body.startswith("- "):
                    raise _error("Mixed mapping and sequence", path, line)
                value_text = body[2:].strip()
                if value_text.startswith("- "):
                    raise _error("Nested block sequences are unsupported", path, line)
                output.append(_scalar(value_text, path, line))
                index += 1
            else:
                if body.startswith("-"):
                    raise _error("Mixed mapping and sequence", path, line)
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$", body)
                if not match or (match.group(2) and not match.group(2)[0].isspace()):
                    raise _error("Invalid mapping entry", path, line)
                key, remainder = match.group(1), match.group(2).strip()
                if key in output:
                    raise ConfigError("CONFIG_DUPLICATE_KEY", "Duplicate key", path=path, line=line, key=key)
                index += 1
                if remainder:
                    output[key] = _scalar(remainder, path, line)
                else:
                    if index >= len(records) or records[index][0] <= indent:
                        raise _error("A key without a value requires a nested block", path, line)
                    output[key], index = block(index, indent + 2)
        return output, index

    value, end = block(0, records[0][0])
    if records[0][0] != 0 or end != len(records) or not isinstance(value, dict):
        raise _error("Top level must be a mapping", path, records[0][2])
    return value


def _kind(value: object) -> type:
    return bool if isinstance(value, bool) else type(value)


def _leaf_origins(value: object, source: str, prefix: str, origins: Dict[str, str]) -> None:
    if isinstance(value, dict):
        if not value and prefix:
            origins[prefix] = source
        for key, child in value.items():
            _leaf_origins(child, source, "%s.%s" % (prefix, key) if prefix else key, origins)
    else:
        origins[prefix] = source


def _merge(target: Dict[str, object], incoming: Mapping[str, object], source: str,
           origins: Dict[str, str], path: Optional[Path], prefix: str = "") -> None:
    for key, value in incoming.items():
        dotted = "%s.%s" % (prefix, key) if prefix else key
        if key not in target:
            target[key] = copy.deepcopy(value)
            _leaf_origins(value, source, dotted, origins)
        elif isinstance(target[key], dict) and isinstance(value, dict):
            if value:
                _merge(target[key], value, source, origins, path, dotted)  # type: ignore[arg-type]
        else:
            old = target[key]
            if old is not None and value is not None and _kind(old) is not _kind(value):
                raise ConfigError("CONFIG_TYPE_MISMATCH", "Configuration types differ", path=path, key=dotted)
            target[key] = copy.deepcopy(value)
            for existing in list(origins):
                if existing == dotted or existing.startswith(dotted + "."):
                    del origins[existing]
            _leaf_origins(value, source, dotted, origins)


def _validate(values: Mapping[str, object]) -> None:
    schema = values.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema != 1:
        raise ConfigError("CONFIG_SCHEMA_VERSION", "schema_version must be integer 1", key="schema_version")
    if not isinstance(values.get("auto_commit"), bool):
        raise ConfigError("CONFIG_VALIDATION", "auto_commit must be boolean", key="auto_commit")
    language = values.get("language")
    if not isinstance(language, dict):
        raise ConfigError("CONFIG_VALIDATION", "language must be a mapping", key="language")
    for key in ("interaction", "artifacts", "specs"):
        value = language.get(key)
        if not isinstance(value, str) or not value or not _LANGUAGE.match(value):
            raise ConfigError("CONFIG_VALIDATION", "Invalid language identifier", key="language.%s" % key)
    project = values.get("project")
    if project is not None:
        if not isinstance(project, dict):
            raise ConfigError("CONFIG_VALIDATION", "project must be a mapping", key="project")
        if "id" in project:
            import uuid
            try:
                uuid.UUID(project["id"] if isinstance(project["id"], str) else "")
            except (ValueError, AttributeError):
                raise ConfigError("CONFIG_VALIDATION", "project.id must be a UUID", key="project.id")


def load_config(project_root: Optional[Path], user_root: Path, *,
                defaults: Optional[Mapping[str, object]] = None) -> ConfigResult:
    values: Dict[str, object] = copy.deepcopy(dict(defaults if defaults is not None else DEFAULT_CONFIG))
    origins: Dict[str, str] = {}
    _leaf_origins(values, "<defaults>", "", origins)
    paths = [user_root / "config.yaml", user_root / "config.local.yaml"]
    if project_root is not None:
        paths.extend([project_root / ".fstar" / "config.yaml", project_root / ".fstar" / "config.local.yaml"])
    sources: List[Path] = []
    project_config = project_root / ".fstar" / "config.yaml" if project_root is not None else None
    for candidate in paths:
        try:
            text = candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except UnicodeError as exc:
            raise ConfigError("CONFIG_ENCODING", str(exc), path=candidate)
        except OSError as exc:
            raise ConfigError("CONFIG_READ_ERROR", str(exc), path=candidate)
        layer = parse_config(text, candidate)
        project_value = layer.get("project")
        if isinstance(project_value, dict) and "id" in project_value and candidate != project_config:
            raise ConfigError("CONFIG_PROJECT_IDENTITY", "project.id may only be declared by project config.yaml", path=candidate, key="project.id")
        _merge(values, layer, str(candidate), origins, candidate)
        sources.append(candidate)
    _validate(values)
    return ConfigResult(values, tuple(sources), origins)
