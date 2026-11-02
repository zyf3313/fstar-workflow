from __future__ import annotations

import contextlib
import copy
import fcntl
import importlib
import importlib.machinery
import io
import json
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from fstar import cli, tools
from fstar.content import validate_resources
from fstar.models import DomainError
from fstar.store import TaskStore, content_hash
from fstar.tasks import TaskService, source_snapshot

ROOT = Path(__file__).resolve().parent.parent
RESOURCES = ROOT / "resources"
CAPABILITIES = (
    "code-structure", "web-research", "knowledge-retrieval", "data-access", "test-execution",
)
SECTION_HEADINGS = (
    "## Definition",
    "## Decidable criteria",
    "## Three-layer verification",
    "## Recommended implementation",
    "## Common non-qualifying implementations",
    "## Fallback",
    "## Recording requirements",
)


# ---------------------------------------------------------------------------
# multiprocessing workers (module level so they can be spawned)
# ---------------------------------------------------------------------------

def _apply_worker(proposal_path, confirmation_path, user_root, project_root, runtime_root, result_path):
    from pathlib import Path

    from fstar import tools
    from fstar.models import DomainError

    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    confirmation = json.loads(Path(confirmation_path).read_text(encoding="utf-8"))
    try:
        outcome = tools.apply_binding(
            proposal, confirmation, clock=lambda: "2026-10-29T10:00:00Z",
            user_root=Path(user_root), project_root=Path(project_root),
            runtime_root=Path(runtime_root), lock_timeout=5.0,
        )
        result = {"code": outcome["status"]}
    except DomainError as exc:
        result = {"code": exc.code}
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")


def _lock_holder(runtime_root, marker, seconds):
    runtime = Path(runtime_root)
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "tools.lock").open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        Path(marker).write_text("held", encoding="utf-8")
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self, value="2026-10-29T10:00:00Z"):
        self.value = value

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value


def tool_snapshot(tool="codegraph", *, kind="mcp", version=None, capability="code-structure",
                  match="strong", basis="symbol-level lookup", source=None):
    if source is None:
        source = {"kind": "registry", "reference": "registry/%s.yaml@v1" % tool}
    return {
        "tool": tool,
        "kind": kind,
        "version": version,
        "capabilities": [{"id": capability, "match": match, "basis": basis, "basis_source": source}],
    }


def document(tools_list=None, bindings=None, history=None, detected_at=None):
    return {
        "schema": "fstar.tools.v1",
        "detected_at": detected_at,
        "tools": tools_list or [],
        "bindings": bindings or {},
        "history": history or [],
    }


def confirmation_for(proposal, **overrides):
    confirmation = {
        "source_id": "input-17",
        "type": "conversation",
        "at": "2026-10-29T09:59:00Z",
        "actor": {"role": "user", "id": "user-1"},
        "reference": "host/session-1/input-17",
        "quote": "use codegraph for structure retrieval",
        "scope": {
            "target": proposal["target"],
            "path": proposal["path"],
            "changes": copy.deepcopy(proposal["changes"]),
            "tools": copy.deepcopy(proposal["tools"]),
        },
        "validates": proposal["digest"],
    }
    confirmation.update(overrides)
    return confirmation


def bound_binding(tool_id, capability, path, *, target="user", source_id="s-1", **overrides):
    confirmation = {
        "source_id": source_id,
        "type": "conversation",
        "at": "2026-10-29T09:00:00Z",
        "actor": {"role": "user", "id": "user-1"},
        "reference": "host/session/input-1",
        "quote": "use %s" % tool_id,
        "scope": {
            "target": target,
            "path": str(path),
            "changes": {capability: tool_id},
            "tools": {},
        },
        "validates": "proposal-digest",
    }
    confirmation.update(overrides)
    return {"tool": tool_id, "reason": "user selected %s" % tool_id, "confirmation": confirmation}


def null_binding(capability, path, *, target="user", source_id="s-null"):
    confirmation = {
        "source_id": source_id,
        "type": "conversation",
        "at": "2026-10-29T09:00:00Z",
        "actor": {"role": "user", "id": "user-1"},
        "reference": "host/session/input-2",
        "quote": "do not bind this capability",
        "scope": {"target": target, "path": str(path), "changes": {capability: None}, "tools": {}},
        "validates": "proposal-digest",
    }
    return {"tool": None, "reason": "explicit unbind", "confirmation": confirmation}


class ToolsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.project = root / "project"
        (self.project / ".fstar").mkdir(parents=True)
        (self.project / ".fstar" / ".schema-version").write_text("1\n", encoding="utf-8")
        self.user = root / "user"
        self.user.mkdir()
        self.runtime = root / "runtime"
        self.clock = Clock()
        self.user_tools = self.user / "tools.yaml"
        self.project_tools = self.project / ".fstar" / "tools.yaml"

    def write_layer(self, path, doc):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tools.serialize_tools(doc), encoding="utf-8")
        return tools.load_tools(path)

    def user_layer(self, doc):
        return self.write_layer(self.user_tools, doc)

    def project_layer(self, doc):
        return self.write_layer(self.project_tools, doc)

    def proposal(self, *, target="user", changes, tools_map=None, reason="user selected a tool"):
        loaded = tools.load_tools(self.user_tools if target == "user" else self.project_tools)
        return tools.build_binding_proposal(
            target=target, loaded=loaded, changes=changes, reason=reason, tools=tools_map,
        )

    def apply(self, proposal, confirmation, **overrides):
        arguments = {
            "clock": self.clock,
            "user_root": self.user,
            "project_root": self.project,
            "runtime_root": self.runtime,
        }
        arguments.update(overrides)
        return tools.apply_binding(proposal, confirmation, **arguments)

    def apply_change(self, changes, tools_map=None, *, target="user", **confirmation_overrides):
        proposal = self.proposal(target=target, changes=changes, tools_map=tools_map)
        confirmation = confirmation_for(proposal, **confirmation_overrides)
        return proposal, confirmation, self.apply(proposal, confirmation)


# ---------------------------------------------------------------------------
# T1: actual parser subset and writer round-trip
# ---------------------------------------------------------------------------

class ParserSubsetTests(ToolsCase):
    def test_serialized_document_round_trips(self):
        doc = document(
            [tool_snapshot(version="1.2.3", basis="symbol # lookup: yes")],
            {"code-structure": bound_binding("codegraph", "code-structure", self.user_tools)},
            detected_at="2026-10-29T08:00:00Z",
        )
        text = tools.serialize_tools(doc)
        loaded = self.write_layer(self.user_tools, doc)
        self.assertEqual("loaded", loaded["state"])
        self.assertEqual(doc, loaded["document"])
        self.assertEqual(text, self.user_tools.read_text(encoding="utf-8"))

    def test_unicode_quotes_colons_and_hash_round_trip(self):
        doc = document()
        binding = bound_binding("tool-ü", "web-research", self.user_tools)
        binding["reason"] = "用户选定 web research: \"Exa\" # keep"
        binding["tool"] = "tool-ü"
        doc["tools"] = [tool_snapshot("tool-ü", capability="web-research", source={
            "kind": "user", "reference": "input-1",
            "confirmation": {
                "source_id": "c-1", "type": "conversation", "at": "2026-10-29T08:30:00Z",
                "actor": {"role": "user", "id": "u"},
                "reference": "session/input-1", "quote": "确认：strong",
                "scope": {"target": "user", "path": str(self.user_tools),
                          "changes": {"web-research": "strong"}, "tools": {}},
                "validates": "d-1",
            },
        })]
        doc["bindings"] = {"web-research": binding}
        loaded = self.write_layer(self.user_tools, doc)
        self.assertEqual(doc["bindings"], loaded["document"]["bindings"])
        self.assertIn("用户选定", self.user_tools.read_text(encoding="utf-8"))

    def test_scalar_block_sequence_of_json_objects_parses(self):
        text = (
            "schema: \"fstar.tools.v1\"\n"
            "detected_at: null\n"
            "tools:\n"
            "  - {\"tool\": \"a\", \"kind\": \"cli\", \"version\": null, \"capabilities\": []}\n"
            "  - {\"tool\": \"b\", \"kind\": \"skill\", \"version\": null, \"capabilities\": []}\n"
            "bindings: {}\n"
            "history: []\n"
        )
        self.user_tools.write_text(text, encoding="utf-8")
        loaded = tools.load_tools(self.user_tools)
        self.assertEqual(["a", "b"], [tool["tool"] for tool in loaded["document"]["tools"]])

    def test_block_mapping_sequence_reports_migration_hint(self):
        self.user_tools.write_text(
            "schema: \"fstar.tools.v1\"\n"
            "detected_at: null\n"
            "tools:\n"
            "  - tool: codegraph\n"
            "    kind: mcp\n"
            "bindings: {}\n"
            "history: []\n",
            encoding="utf-8",
        )
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        self.assertEqual("tools_invalid_schema", raised.exception.code)
        self.assertIn("line", raised.exception.details)
        self.assertIn("hint", raised.exception.details)
        self.assertIn("JSON flow", raised.exception.details["hint"])

    def test_bad_indentation_duplicate_keys_and_nan_rejected(self):
        cases = {
            "indent": "schema: \"fstar.tools.v1\"\n detected_at: null\n",
            "duplicate": "schema: \"a\"\nschema: \"b\"\n",
            "nan": "schema: \"fstar.tools.v1\"\ndetected_at: null\nx: NaN\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.user_tools.write_text(text, encoding="utf-8")
                with self.assertRaises(DomainError) as raised:
                    tools.load_tools(self.user_tools)
                self.assertEqual("tools_invalid_schema", raised.exception.code)

    def test_unknown_schema_field_and_capability_rejected(self):
        bad = document()
        bad["schema"] = "fstar.tools.v2"
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(bad)
        self.assertEqual("tools_invalid_schema", raised.exception.code)

        doc = document([tool_snapshot(capability="code-text")])
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(doc)
        self.assertIn("Unknown capability", raised.exception.message)

        doc = document()
        doc["bindings"] = {"code-text": bound_binding("x", "code-text", self.user_tools)}
        with self.assertRaises(DomainError):
            tools.validate_tools(doc)

        doc = document()
        doc["extra"] = True
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(doc)
        self.assertIn("extra", raised.exception.details["unknown"])

    def test_duplicate_tool_ids_and_capability_entries_rejected(self):
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(document([tool_snapshot(), tool_snapshot()]))
        self.assertIn("Duplicate tool", raised.exception.message)
        duplicate = tool_snapshot()
        duplicate["capabilities"].append(copy.deepcopy(duplicate["capabilities"][0]))
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(document([duplicate]))
        self.assertIn("Duplicate capability", raised.exception.message)

    def test_enum_and_type_errors(self):
        cases = []
        bad_kind = tool_snapshot()
        bad_kind["kind"] = "daemon"
        cases.append(bad_kind)
        bad_match = tool_snapshot(match="maybe")
        cases.append(bad_match)
        bad_version = tool_snapshot()
        bad_version["version"] = 1
        cases.append(bad_version)
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(DomainError) as raised:
                    tools.validate_tools(document([bad]))
                self.assertEqual("tools_invalid_schema", raised.exception.code)

    def test_probe_cannot_be_strong_and_unclassified_must_be_none(self):
        probe = tool_snapshot(match="strong", source={"kind": "probe", "reference": "probe:x"})
        with self.assertRaises(DomainError):
            tools.validate_tools(document([probe]))
        unclassified = tool_snapshot(match="weak", source={"kind": "unclassified", "reference": "none"})
        with self.assertRaises(DomainError):
            tools.validate_tools(document([unclassified]))
        user_strong = tool_snapshot(match="strong", source={"kind": "user", "reference": "input-1"})
        with self.assertRaises(DomainError):
            tools.validate_tools(document([user_strong]))

    def test_user_strong_requires_capability_judgment_in_confirmation(self):
        classification = {
            "source_id": "c-1", "type": "conversation", "at": "2026-10-29T08:30:00Z",
            "actor": {"role": "user", "id": "u"},
            "reference": "session/input-1", "quote": "this tool does structure",
            "scope": {"target": "user", "path": str(self.user_tools),
                      "changes": {"web-research": "strong"}, "tools": {}},
            "validates": "d-1",
        }
        tool = tool_snapshot(match="strong", capability="code-structure", source={
            "kind": "user", "reference": "input-1", "confirmation": classification,
        })
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(document([tool]))
        self.assertIn("capability judgment", raised.exception.message)

    def test_parser_error_keeps_path_line_and_original_code(self):
        self.user_tools.write_text(
            "schema: \"fstar.tools.v1\"\ndetected_at: null\ntools: [ {\"tool\": } ]\n",
            encoding="utf-8",
        )
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        details = raised.exception.details
        self.assertEqual(str(self.user_tools), details["path"])
        self.assertEqual(3, details["line"])
        self.assertIn("parser_code", details)


# ---------------------------------------------------------------------------
# T2: missing vs broken layers
# ---------------------------------------------------------------------------

class LoadTests(ToolsCase):
    def test_missing_file_is_a_state_not_an_error(self):
        loaded = tools.load_tools(self.user_tools)
        self.assertEqual("missing", loaded["state"])
        self.assertIsNone(loaded["document"])
        self.assertIsNone(loaded["digest"])

    def test_empty_file_is_not_missing(self):
        self.user_tools.write_text("", encoding="utf-8")
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        self.assertEqual("tools_invalid_schema", raised.exception.code)

    def test_non_utf8_file_is_encoding_error(self):
        self.user_tools.write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        self.assertEqual("tools_encoding_error", raised.exception.code)

    def test_directory_instead_of_file_is_read_error(self):
        self.user_tools.mkdir()
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        self.assertEqual("tools_read_error", raised.exception.code)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read everything")
    def test_unreadable_file_is_read_error(self):
        self.user_tools.write_text("schema: \"fstar.tools.v1\"\n", encoding="utf-8")
        self.user_tools.chmod(0)
        self.addCleanup(lambda: self.user_tools.chmod(0o600))
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.user_tools)
        self.assertEqual("tools_read_error", raised.exception.code)

    def test_bad_project_layer_is_not_masked_by_good_user_layer(self):
        self.user_layer(document([tool_snapshot()]))
        self.project_tools.write_text("schema: [unterminated\n", encoding="utf-8")
        with self.assertRaises(DomainError) as raised:
            tools.load_tools(self.project_tools)
        self.assertEqual("tools_invalid_schema", raised.exception.code)
        # A layer result carrying a corrupt document is re-validated, not skipped.
        forged = {"state": "loaded", "path": str(self.project_tools), "digest": "x",
                  "document": {"schema": "wrong"}}
        with self.assertRaises(DomainError):
            tools.resolve_bindings(project=forged, user=tools.load_tools(self.user_tools))

    def test_reads_and_proposals_create_no_directories_or_files(self):
        missing_root = self.root / "absent" / "user"
        missing_path = missing_root / "tools.yaml"
        loaded = tools.load_tools(missing_path)
        tools.build_binding_proposal(
            target="user", loaded=loaded, changes={"test-execution": "project-runner"},
            reason="recommend", tools={"project-runner": tool_snapshot(
                "project-runner", kind="builtin", capability="test-execution")},
        )
        self.assertFalse(missing_root.exists())
        self.assertFalse(self.runtime.exists())


# ---------------------------------------------------------------------------
# T3: per-item resolution and provenance snapshots
# ---------------------------------------------------------------------------

class ResolutionTests(ToolsCase):
    def test_project_overrides_only_its_own_items(self):
        self.project_layer(document(
            [tool_snapshot("pstruct", version="9.0.0")],
            {"code-structure": bound_binding("pstruct", "code-structure", self.project_tools, target="project")},
        ))
        self.user_layer(document(
            [tool_snapshot("ustruct"), tool_snapshot("uqmd", capability="knowledge-retrieval")],
            {
                "code-structure": bound_binding("ustruct", "code-structure", self.user_tools),
                "knowledge-retrieval": bound_binding("uqmd", "knowledge-retrieval", self.user_tools, source_id="s-2"),
            },
        ))
        resolution = tools.resolve_bindings(
            project=tools.load_tools(self.project_tools), user=tools.load_tools(self.user_tools),
        )
        entries = {entry["capability"]: entry for entry in resolution["capabilities"]}
        self.assertEqual("bound", entries["code-structure"]["state"])
        self.assertEqual("pstruct", entries["code-structure"]["tool"]["tool"])
        self.assertEqual("9.0.0", entries["code-structure"]["tool"]["version"])
        self.assertEqual("project", entries["code-structure"]["origin"]["layer"])
        self.assertEqual("uqmd", entries["knowledge-retrieval"]["tool"]["tool"])
        self.assertEqual("user", entries["knowledge-retrieval"]["origin"]["layer"])
        self.assertEqual("recommended", entries["data-access"]["state"])
        self.assertIsNone(entries["data-access"]["binding_digest"])

    def test_explicit_null_binding_shadows_lower_layer(self):
        self.project_layer(document(
            [],
            {"code-structure": null_binding("code-structure", self.project_tools, target="project")},
        ))
        self.user_layer(document(
            [tool_snapshot("ustruct")],
            {"code-structure": bound_binding("ustruct", "code-structure", self.user_tools)},
        ))
        resolution = tools.resolve_bindings(
            project=tools.load_tools(self.project_tools), user=tools.load_tools(self.user_tools),
        )
        entry = resolution["capabilities"][0]
        self.assertEqual("unbound", entry["state"])
        self.assertIsNone(entry["tool"])
        # An explicit unbind still carries its own authorization snapshot.
        self.assertEqual("project", entry["origin"]["layer"])

    def test_missing_key_inherits_from_next_layer(self):
        self.project_layer(document([tool_snapshot("pstruct")], {}))
        self.user_layer(document(
            [tool_snapshot("ustruct")],
            {"code-structure": bound_binding("ustruct", "code-structure", self.user_tools)},
        ))
        resolution = tools.resolve_bindings(
            project=tools.load_tools(self.project_tools), user=tools.load_tools(self.user_tools),
        )
        entry = resolution["capabilities"][0]
        self.assertEqual("user", entry["origin"]["layer"])
        self.assertEqual("ustruct", entry["tool"]["tool"])

    def test_defaults_are_recommendation_only(self):
        resolution = tools.resolve_bindings()
        for entry in resolution["capabilities"]:
            self.assertEqual("recommended", entry["state"])
            self.assertIsNone(entry["confirmation"])
            self.assertEqual("defaults", entry["origin"]["layer"])
            self.assertIsNone(entry["binding_digest"])
            self.assertTrue(entry["recommendation"]["tool"])

    def test_same_named_tool_is_not_spliced_across_layers(self):
        self.project_layer(document(
            [tool_snapshot("codegraph", version="9.9.9")],
            {"code-structure": bound_binding("codegraph", "code-structure", self.project_tools,
                                             target="project", source_id="project-input")},
        ))
        self.user_layer(document(
            [tool_snapshot("codegraph", version="1.0.0")],
            {"web-research": bound_binding("codegraph", "web-research", self.user_tools)},
        ))
        resolution = tools.resolve_bindings(
            project=tools.load_tools(self.project_tools), user=tools.load_tools(self.user_tools),
        )
        entry = resolution["capabilities"][0]
        self.assertEqual("project-input", entry["confirmation"]["source_id"])
        self.assertEqual("9.9.9", entry["tool"]["version"])
        self.assertEqual("project", entry["origin"]["layer"])

    def test_dangling_binding_reference_is_rejected(self):
        doc = document([], {"code-structure": bound_binding("ghost", "code-structure", self.user_tools)})
        with self.assertRaises(DomainError) as raised:
            tools.validate_tools(doc)
        self.assertIn("absent", raised.exception.message)


# ---------------------------------------------------------------------------
# T4: confirmation gates
# ---------------------------------------------------------------------------

class ConfirmationTests(ToolsCase):
    def test_missing_confirmation_is_rejected_without_touching_anything(self):
        proposal = self.proposal(
            changes={"code-structure": "codegraph"},
            tools_map={"codegraph": tool_snapshot()},
        )
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, None)
        self.assertEqual("tools_confirmation_required", raised.exception.code)
        self.assertEqual(3, raised.exception.status)
        self.assertFalse(self.user_tools.exists())
        self.assertFalse(self.runtime.exists())

    def test_agent_actor_cannot_confirm(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal, actor={"role": "agent", "id": "a-1"})
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation)
        self.assertEqual("tools_confirmation_required", raised.exception.code)
        self.assertFalse(self.user_tools.exists())

    def test_conversation_requires_quote_and_reference(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        for field in ("quote", "reference"):
            confirmation = confirmation_for(proposal, **{field: ""})
            with self.subTest(field=field):
                with self.assertRaises(DomainError) as raised:
                    self.apply(proposal, confirmation)
                self.assertEqual("tools_confirmation_required", raised.exception.code)

    def test_review_marker_alone_is_rejected(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal, type="review", quote="approved")
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation)
        self.assertEqual("tools_confirmation_required", raised.exception.code)

    def test_scope_must_match_full_diff(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        variants = {
            "target": {"target": "project", "path": proposal["path"],
                       "changes": proposal["changes"], "tools": proposal["tools"]},
            "path": {"target": "user", "path": str(self.root / "other.yaml"),
                     "changes": proposal["changes"], "tools": proposal["tools"]},
            "changes": {"target": "user", "path": proposal["path"],
                        "changes": {"web-research": "codegraph"}, "tools": proposal["tools"]},
            "tools": {"target": "user", "path": proposal["path"],
                      "changes": proposal["changes"], "tools": {}},
        }
        for name, scope in variants.items():
            confirmation = confirmation_for(proposal, scope=scope)
            with self.subTest(name):
                with self.assertRaises(DomainError) as raised:
                    self.apply(proposal, confirmation)
                self.assertEqual("tools_invalid_confirmation", raised.exception.code)
        self.assertFalse(self.user_tools.exists())

    def test_stale_proposal_digest_is_rejected(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal, validates="0" * 64)
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation)
        self.assertEqual("tools_stale_confirmation", raised.exception.code)

    def test_package_grant_and_strong_match_do_not_replace_confirmation(self):
        doc = document([tool_snapshot()],
                       {"code-structure": bound_binding("codegraph", "code-structure", self.user_tools)})
        del doc["bindings"]["code-structure"]["confirmation"]
        with self.assertRaises(DomainError):
            tools.validate_tools(doc)
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, {})
        self.assertEqual("tools_confirmation_required", raised.exception.code)

    def test_weak_selection_does_not_upgrade_match(self):
        weak = tool_snapshot(match="weak", source={"kind": "probe", "reference": "probe:struct"})
        self.apply_change({"code-structure": "codegraph"}, {"codegraph": weak})
        resolution = tools.resolve_bindings(user=tools.load_tools(self.user_tools))
        entry = resolution["capabilities"][0]
        self.assertEqual("bound", entry["state"])
        self.assertEqual("weak", entry["match"]["match"])
        self.assertEqual("probe", entry["match"]["basis_source"]["kind"])


# ---------------------------------------------------------------------------
# T5: atomic confirmed mutation
# ---------------------------------------------------------------------------

class ApplyTests(ToolsCase):
    def test_confirmed_change_updates_only_target_item_and_history(self):
        self.user_layer(document(
            [tool_snapshot("keep", capability="web-research")],
            {"web-research": bound_binding("keep", "web-research", self.user_tools)},
        ))
        before = tools.load_tools(self.user_tools)["document"]
        proposal, confirmation, result = self.apply_change(
            {"code-structure": "codegraph"}, {"codegraph": tool_snapshot()},
        )
        self.assertEqual("applied", result["status"])
        after = tools.load_tools(self.user_tools)["document"]
        self.assertEqual(before["bindings"]["web-research"], after["bindings"]["web-research"])
        self.assertEqual("codegraph", after["bindings"]["code-structure"]["tool"])
        self.assertEqual(confirmation, after["bindings"]["code-structure"]["confirmation"])
        self.assertEqual(1, len(after["history"]))
        self.assertEqual(proposal["digest"], after["history"][0]["source"]["validates"])
        self.assertEqual(before["detected_at"], after["detected_at"])

    def test_rejected_and_stale_leave_bytes_and_history_untouched(self):
        self.user_layer(document([tool_snapshot()], {}))
        original = self.user_tools.read_bytes()
        proposal = self.proposal(changes={"code-structure": "codegraph"})
        stale = confirmation_for(proposal, validates="0" * 64)
        with self.assertRaises(DomainError):
            self.apply(proposal, stale)
        self.assertEqual(original, self.user_tools.read_bytes())
        with self.assertRaises(DomainError):
            self.apply(proposal, confirmation_for(proposal, actor={"role": "agent", "id": "a"}))
        self.assertEqual(original, self.user_tools.read_bytes())

    def test_concurrent_file_change_is_a_conflict(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal)
        self.user_layer(document([tool_snapshot("other", capability="web-research")], {}))
        swapped = self.user_tools.read_bytes()
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation)
        self.assertEqual("tools_binding_conflict", raised.exception.code)
        self.assertEqual(4, raised.exception.status)
        self.assertEqual(swapped, self.user_tools.read_bytes())

    def test_lock_timeout_is_a_conflict_status(self):
        self.user_layer(document())
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal)
        marker = self.root / "held"
        process = multiprocessing.Process(target=_lock_holder, args=(self.runtime, marker, 2.0))
        process.start()
        self.addCleanup(process.join)
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists())
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation, lock_timeout=0.2)
        self.assertEqual("tools_lock_timeout", raised.exception.code)
        self.assertEqual(4, raised.exception.status)

    def test_two_processes_commit_exactly_once(self):
        self.user_layer(document())
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        confirmation = confirmation_for(proposal)
        proposal_path = self.root / "proposal.json"
        confirmation_path = self.root / "confirmation.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
        results = [self.root / ("result-%d.json" % index) for index in range(2)]
        processes = [
            multiprocessing.Process(target=_apply_worker, args=(
                proposal_path, confirmation_path, self.user, self.project, self.runtime, result,
            ))
            for result in results
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            self.assertEqual(0, process.exitcode)
        codes = [json.loads(result.read_text(encoding="utf-8"))["code"] for result in results]
        self.assertEqual(1, codes.count("applied"))
        self.assertEqual(1, codes.count("already_applied"))
        document_after = tools.load_tools(self.user_tools)["document"]
        self.assertEqual(1, len(document_after["history"]))

    def test_atomic_replace_failure_keeps_original_and_cleans_temp(self):
        self.user_layer(document())
        original = self.user_tools.read_bytes()
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        with mock.patch("fstar.tools.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(DomainError) as raised:
                self.apply(proposal, confirmation_for(proposal))
        self.assertEqual("tools_write_failed", raised.exception.code)
        self.assertEqual(original, self.user_tools.read_bytes())
        leftovers = [name for name in os.listdir(self.user) if name.startswith(".tools-")]
        self.assertEqual([], leftovers)

    def test_target_outside_the_allowed_root_is_rejected(self):
        outside = self.root / "outside" / "tools.yaml"
        loaded = tools.load_tools(outside)
        proposal = tools.build_binding_proposal(
            target="user", loaded=loaded, changes={"code-structure": "codegraph"},
            reason="escape", tools={"codegraph": tool_snapshot()},
        )
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation_for(proposal))
        self.assertEqual("tools_unsafe_target", raised.exception.code)
        self.assertFalse(outside.exists())

    def test_symlinked_target_is_rejected(self):
        victim = self.root / "victim.yaml"
        victim.write_text("keep me\n", encoding="utf-8")
        # The proposal is built while the target is absent (a legitimate
        # missing layer); the symlink is introduced afterwards, before apply.
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        self.user_tools.symlink_to(victim)
        with self.assertRaises(DomainError) as raised:
            self.apply(proposal, confirmation_for(proposal))
        self.assertEqual("tools_unsafe_target", raised.exception.code)
        self.assertEqual("keep me\n", victim.read_text(encoding="utf-8"))

    def test_project_binding_requires_initialized_project(self):
        project = self.root / "not-initialized"
        project.mkdir()
        tools_file = project / ".fstar" / "tools.yaml"
        loaded = tools.load_tools(tools_file)
        proposal = tools.build_binding_proposal(
            target="project", loaded=loaded, changes={"code-structure": "codegraph"},
            reason="bind", tools={"codegraph": tool_snapshot()},
        )
        with self.assertRaises(DomainError) as raised:
            tools.apply_binding(
                proposal, confirmation_for(proposal), clock=self.clock,
                user_root=self.user, project_root=project, runtime_root=self.runtime,
            )
        self.assertEqual("project_not_initialized", raised.exception.code)
        self.assertFalse(tools_file.exists())

    def test_successful_commit_round_trips_through_the_parser(self):
        from fstar.config import parse_config

        result = self.apply_change({"knowledge-retrieval": "project-index"},
                                   {"project-index": tool_snapshot("project-index", kind="builtin",
                                                                   capability="knowledge-retrieval")})[2]
        text = self.user_tools.read_text(encoding="utf-8")
        parsed = tools.validate_tools(parse_config(text, self.user_tools))
        self.assertEqual(result["digest"], tools._sha256(text.encode("utf-8")))
        self.assertEqual("project-index", parsed["bindings"]["knowledge-retrieval"]["tool"])
    def test_same_source_id_for_different_change_is_a_conflict(self):
        proposal = self.proposal(changes={"code-structure": "codegraph"},
                                 tools_map={"codegraph": tool_snapshot()})
        self.apply(proposal, confirmation_for(proposal))
        other = self.proposal(changes={"web-research": "search"},
                              tools_map={"search": tool_snapshot("search", capability="web-research")})
        with self.assertRaises(DomainError) as raised:
            self.apply(other, confirmation_for(other, source_id="input-17"))
        self.assertEqual("tools_binding_conflict", raised.exception.code)


# ---------------------------------------------------------------------------
# T6/T7: availability, gaps and provenance inputs
# ---------------------------------------------------------------------------

def observation(tool="codegraph", capability="code-structure", layer="discoverable",
                status="verified", at="2026-10-29T09:00:00Z", scope=None, **extra):
    value = {
        "tool": tool,
        "capability": capability,
        "layer": layer,
        "status": status,
        "at": at,
        "scope": scope or {"project": "p-1", "host": "h-1", "session": "s-1"},
        "evidence_ref": None,
        "reason": None,
        "call_id": None,
    }
    if status == "verified":
        value["evidence_ref"] = "evidence/%s-%s" % (tool, layer)
    if status == "failed":
        value["reason"] = "layer probe failed"
    if layer == "minimal_call" and status == "verified":
        value["call_id"] = "call-1"
    value.update(extra)
    return value


class AvailabilityTests(ToolsCase):
    def resolution(self, tool="codegraph", capability="code-structure", match="strong"):
        snapshot = tool_snapshot(tool, capability=capability, match=match,
                                 source={"kind": "probe", "reference": "probe"} if match == "weak" else None)
        self.user_layer(document([snapshot], {
            capability: bound_binding(tool, capability, self.user_tools),
        }))
        return tools.resolve_bindings(user=tools.load_tools(self.user_tools))

    def test_three_layers_are_reported_independently(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(
            resolution,
            [observation(), observation(layer="minimal_call", status="failed")],
        )
        entry = assessment["capabilities"][0]
        self.assertEqual("verified", entry["layers"]["discoverable"]["status"])
        self.assertEqual("unknown", entry["layers"]["client_loaded"]["status"])
        self.assertEqual("not_observed", entry["layers"]["client_loaded"]["reason"])
        self.assertEqual("failed", entry["layers"]["minimal_call"]["status"])
        self.assertEqual("layer probe failed", entry["layers"]["minimal_call"]["reason"])
        self.assertEqual(["client_loaded", "minimal_call"], entry["missing_layers"])
        self.assertFalse(entry["layers"]["client_loaded"]["status"] == "verified")

    def test_observation_validation(self):
        resolution = self.resolution()
        bad_cases = [
            observation(status="verified", evidence_ref=""),
            observation(layer="minimal_call", status="verified", call_id=None),
            observation(status="failed", reason=None),
            observation(capability="code-text"),
            observation(layer="installed"),
            observation(status="ok"),
            {**observation(), "scope": {"project": "p"}},
            {**observation(), "unexpected": 1},
        ]
        for bad in bad_cases:
            with self.subTest(bad=bad):
                with self.assertRaises(DomainError) as raised:
                    tools.assess_availability(resolution, [bad])
                self.assertEqual("tools_invalid_observation", raised.exception.code)

    def test_observations_for_other_tools_do_not_apply(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(
            resolution, [observation(tool="other-tool"), observation(tool="other-tool", layer="minimal_call")],
        )
        entry = assessment["capabilities"][0]
        self.assertEqual("unknown", entry["layers"]["discoverable"]["status"])
        self.assertEqual("unknown", entry["layers"]["minimal_call"]["status"])

    def test_scope_mismatch_cannot_form_a_verified_triple(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(resolution, [
            observation(scope={"project": "p-1", "host": "h-1", "session": "s-1"}),
            observation(layer="minimal_call", scope={"project": "p-1", "host": "h-1", "session": "s-2"}),
        ])
        entry = assessment["capabilities"][0]
        self.assertEqual("unknown", entry["layers"]["discoverable"]["status"])
        self.assertEqual("scope_mismatch", entry["layers"]["discoverable"]["reason"])
        self.assertEqual("unknown", entry["layers"]["minimal_call"]["status"])
        self.assertEqual("scope_mismatch", entry["layers"]["minimal_call"]["reason"])

    def test_stale_observations_are_unknown_not_verified(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(
            resolution,
            [observation(at="2026-10-29T08:00:00Z"),
             observation(layer="client_loaded", at="2026-10-29T08:00:00Z")],
            now="2026-10-29T10:00:00Z", max_age_seconds=3600,
        )
        entry = assessment["capabilities"][0]
        self.assertEqual("unknown", entry["layers"]["discoverable"]["status"])
        self.assertEqual("stale_observation", entry["layers"]["discoverable"]["reason"])
        self.assertTrue(entry["layers"]["discoverable"]["stale"])

    def test_version_unknown_stays_null_in_provenance(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(resolution, [
            observation(),
            observation(layer="client_loaded"),
            observation(layer="minimal_call"),
        ])
        record = tools.build_provenance(resolution, {
            "capability": "code-structure",
            "at": "2026-10-29T09:30:00Z",
            "call": {"id": "call-1", "reference": "host/tool-call-1", "operation": "lookup symbol foo"},
            "result": "passed",
        }, assessment)
        self.assertIsNone(record["version"])

    def test_no_adapter_reports_unknown_and_gap(self):
        resolution = self.resolution()
        assessment = tools.assess_availability(resolution, [])
        entry = assessment["capabilities"][0]
        self.assertEqual(["discoverable", "client_loaded", "minimal_call"], entry["missing_layers"])
        # Only the bound capability gaps here; the other four are recommended
        # from defaults and each of them reports its own gap as well.
        self.assertEqual(5, len(assessment["gaps"]))
        gap = next(item for item in assessment["gaps"] if item["capability"] == "code-structure")
        self.assertEqual("capabilities/code-structure.md", gap["recommendations"]["source"])
        self.assertIn("Literal text search", gap["fallback"])


class GapAndProvenanceTests(ToolsCase):
    def test_every_capability_gap_has_layers_reason_source_and_fallback(self):
        resolution = tools.resolve_bindings()
        assessment = tools.assess_availability(resolution, [])
        self.assertEqual(5, len(assessment["gaps"]))
        for gap in assessment["gaps"]:
            self.assertIn(gap["capability"], CAPABILITIES)
            self.assertEqual(["discoverable", "client_loaded", "minimal_call"], gap["missing_layers"])
            self.assertTrue(gap["reasons"])
            self.assertTrue(gap["recommendations"]["source"].startswith("capabilities/"))
            self.assertTrue(gap["fallback"])

    def test_not_run_test_execution_is_not_a_pass(self):
        snapshot = tool_snapshot("project-runner", kind="builtin", capability="test-execution",
                                 match="weak", source={"kind": "probe", "reference": "probe:tests"})
        self.user_layer(document([snapshot], {
            "test-execution": bound_binding("project-runner", "test-execution", self.user_tools),
        }))
        resolution = tools.resolve_bindings(user=tools.load_tools(self.user_tools))
        assessment = tools.assess_availability(resolution, [
            observation(tool="project-runner", capability="test-execution", layer="minimal_call",
                        status="unknown", reason="not_run", call_id=None),
        ])
        entry = assessment["capabilities"][4]
        self.assertEqual("unknown", entry["layers"]["minimal_call"]["status"])
        self.assertIn("minimal_call", entry["missing_layers"])
        gap = next(item for item in assessment["gaps"] if item["capability"] == "test-execution")
        self.assertIn("static checks", gap["fallback"])

    def test_provenance_requires_a_real_call_not_a_scan_record(self):
        resolution = tools.resolve_bindings()
        scan_like = {
            "capability": "code-structure",
            "at": "2026-10-29T09:30:00Z",
            "detected_at": "2026-10-29T08:00:00Z",
            "tools": [],
        }
        with self.assertRaises(DomainError) as raised:
            tools.build_provenance(resolution, scan_like)
        self.assertEqual("tools_invalid_call_record", raised.exception.code)
        with self.assertRaises(DomainError) as raised:
            tools.build_provenance(resolution, {
                "capability": "code-structure",
                "at": "2026-10-29T09:30:00Z",
                "call": {"id": "", "reference": "host/x", "operation": "op"},
                "result": "passed",
            })
        self.assertEqual("tools_invalid_call_record", raised.exception.code)
        with self.assertRaises(DomainError):
            tools.build_provenance(resolution, {
                "capability": "code-structure",
                "at": "2026-10-29T09:30:00Z",
                "call": {"id": "c", "reference": "r", "operation": "op"},
                "result": "maybe",
            })

    def test_failed_call_is_recorded_honestly_and_extras_are_not_stored(self):
        resolution = tools.resolve_bindings()
        record = tools.build_provenance(resolution, {
            "capability": "code-structure",
            "at": "2026-10-29T09:30:00Z",
            "call": {"id": "call-9", "reference": "host/tool-call-9",
                     "operation": "lookup known symbol", "raw_response": "secret body"},
            "result": "failed",
            "fallback": True,
        })
        self.assertEqual("failed", record["call"]["result"])
        self.assertTrue(record["fallback"])
        self.assertNotIn("raw_response", record["call"])
        self.assertEqual("fstar.tool-use.v1", record["schema"])

    def test_degraded_call_on_unbound_capability_names_the_actual_tool(self):
        # The contract's fallback path (literal search for an explicitly
        # unbound capability) is a real call and must be recordable with the
        # tool actually used, not silently dropped or misnamed.
        self.user_layer(document([], {"code-structure": null_binding("code-structure", self.user_tools)}))
        resolution = tools.resolve_bindings(user=tools.load_tools(self.user_tools))
        self.assertEqual("unbound", resolution["capabilities"][0]["state"])
        record = tools.build_provenance(resolution, {
            "capability": "code-structure",
            "at": "2026-10-29T09:30:00Z",
            "call": {"id": "call-rg", "reference": "host/tool-call-rg",
                     "operation": "grep symbol foo in src"},
            "result": "passed",
            "tool": "rg",
        })
        self.assertEqual("rg", record["tool"])
        self.assertTrue(record["fallback"])
        self.assertIsNone(record["binding_origin"])
        self.assertIsNone(record["binding_digest"])
        self.assertIsNone(record["kind"])
        self.assertIsNone(record["version"])
        # The session-only record is accepted end to end.
        out = tools.record_provenance(None, None, record, lease_token=None, clock=self.clock)
        self.assertEqual("session_only", out["persistence"])
        # Without naming the degraded-path tool the record cannot be built.
        with self.assertRaises(DomainError) as raised:
            tools.build_provenance(resolution, {
                "capability": "code-structure",
                "at": "2026-10-29T09:30:00Z",
                "call": {"id": "call-x", "reference": "host/x", "operation": "op"},
                "result": "passed",
            })
        self.assertEqual("tools_invalid_call_record", raised.exception.code)

    def test_call_through_a_different_tool_is_fallback_not_the_bound_tool(self):
        # A bound capability whose real call was served by another tool must
        # not be recorded as if the bound tool made the call.
        self.user_layer(document([tool_snapshot()], {
            "code-structure": bound_binding("codegraph", "code-structure", self.user_tools),
        }))
        resolution = tools.resolve_bindings(user=tools.load_tools(self.user_tools))
        record = tools.build_provenance(resolution, {
            "capability": "code-structure",
            "at": "2026-10-29T09:30:00Z",
            "call": {"id": "call-rg2", "reference": "host/tool-call-rg2",
                     "operation": "grep symbol bar in src"},
            "result": "passed",
            "tool": "rg",
        })
        self.assertEqual("rg", record["tool"])
        self.assertTrue(record["fallback"])
        self.assertIsNotNone(record["binding_origin"])
        self.assertEqual("codegraph", record["binding_origin"]["layer"] and
                         resolution["capabilities"][0]["tool"]["tool"])
        # A call that did use the bound tool keeps its snapshot metadata.
        bound_record = tools.build_provenance(resolution, {
            "capability": "code-structure",
            "at": "2026-10-29T09:31:00Z",
            "call": {"id": "call-cg", "reference": "host/tool-call-cg",
                     "operation": "lookup symbol bar"},
            "result": "passed",
        })
        self.assertEqual("codegraph", bound_record["tool"])
        self.assertFalse(bound_record["fallback"])
        self.assertEqual("mcp", bound_record["kind"])

    def test_most_recent_observation_is_selected_by_parsed_time(self):
        # Fractional and non-fractional ISO seconds must compare by time, not
        # by raw string order.
        self.user_layer(document([tool_snapshot()], {
            "code-structure": bound_binding("codegraph", "code-structure", self.user_tools),
        }))
        resolution = tools.resolve_bindings(user=tools.load_tools(self.user_tools))
        assessment = tools.assess_availability(resolution, [
            observation(at="2026-10-29T09:00:00.500Z", status="failed", reason="later failure"),
            observation(at="2026-10-29T09:00:00Z"),
        ])
        entry = assessment["capabilities"][0]
        self.assertEqual("failed", entry["layers"]["discoverable"]["status"])
        self.assertEqual("later failure", entry["layers"]["discoverable"]["reason"])


# ---------------------------------------------------------------------------
# T8: provenance through the real core store
# ---------------------------------------------------------------------------

class ProvenanceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / "project"
        (self.project / ".fstar").mkdir(parents=True)
        (self.project / ".fstar" / ".schema-version").write_text("1\n", encoding="utf-8")
        self.store = TaskStore(self.project, user_home=root / "user", runtime_root=root / "runtime")
        self.runtime = root / "runtime"
        self.clock = Clock()
        self.service = TaskService(self.store, clock=self.clock)
        self.agent = {"role": "agent", "id": "coordinator", "session": "s1"}
        self.user = {"role": "user", "id": "user-1", "session": "s1"}

    def source(self, ref, source_type="conversation"):
        task = self.store.read(ref)
        return {
            "source_id": "source-" + task["id"],
            "type": source_type,
            "at": self.clock(),
            "actor": self.user,
            "reference": "prompt:42",
            "quote": "start it",
            "scope": "task",
            "validates": source_snapshot(task),
        }

    def started_task(self, name="tool-task"):
        self.service.create(name=name, title=name, description="Deliver", actor=self.agent, session_id="s1")
        self.service.start(name, actor=self.user, confirmation=self.source(name), session_id="s1")
        return self.service.acquire_lease(name, holder="worker", role="implement",
                                          actor={"role": "agent", "id": "worker", "session": "s1"})

    def record(self, capability="code-structure", tool="codegraph", call_id="call-1"):
        return {
            "schema": "fstar.tool-use.v1",
            "id": "record-" + call_id,
            "capability": capability,
            "tool": tool,
            "kind": "mcp",
            "version": None,
            "at": "2026-10-29T09:30:00Z",
            "binding_origin": {"layer": "user", "path": "/tmp/tools.yaml", "digest": "d"},
            "binding_digest": "bd",
            "match": "strong",
            "basis": "symbol-level",
            "call": {"id": call_id, "reference": "host/tool-call-1", "operation": "lookup", "result": "passed"},
            "availability": None,
            "fallback": False,
        }

    def test_record_round_trip_keeps_other_task_fields(self):
        lease = self.started_task()
        before = self.store.read("tool-task")
        result = tools.record_provenance(
            self.store, "tool-task", self.record(), lease_token=lease["token"], clock=self.clock,
        )
        self.assertEqual("task", result["persistence"])
        after = self.store.read("tool-task")
        self.assertEqual(1, len(after["capabilities"]))
        self.assertEqual("record-call-1", after["capabilities"][0]["id"])
        self.assertTrue(any(event["type"] == "capability_recorded" for event in after["events"]))
        self.assertEqual(before["extensions"], after["extensions"])
        self.assertEqual(before["phase"], after["phase"])
        self.assertEqual(before["acceptance"], after["acceptance"])
        self.assertEqual(before["lease"]["expires_at"], after["lease"]["expires_at"])

    def test_same_id_same_content_is_idempotent(self):
        lease = self.started_task()
        record = self.record()
        tools.record_provenance(self.store, "tool-task", record, lease_token=lease["token"], clock=self.clock)
        again = tools.record_provenance(self.store, "tool-task", record, lease_token=lease["token"], clock=self.clock)
        self.assertTrue(again["idempotent"])
        self.assertEqual(1, len(self.store.read("tool-task")["capabilities"]))

    def test_same_id_different_content_is_a_conflict(self):
        lease = self.started_task()
        tools.record_provenance(self.store, "tool-task", self.record(), lease_token=lease["token"], clock=self.clock)
        changed = self.record()
        changed["call"]["result"] = "failed"
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(self.store, "tool-task", changed, lease_token=lease["token"], clock=self.clock)
        self.assertEqual("tools_provenance_conflict", raised.exception.code)
        self.assertEqual(1, len(self.store.read("tool-task")["capabilities"]))

    def test_missing_or_expired_lease_is_rejected(self):
        self.started_task()
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(self.store, "tool-task", self.record(), lease_token="wrong", clock=self.clock)
        self.assertEqual("invalid_lease", raised.exception.code)
        self.clock.set("2027-01-01T00:00:00Z")
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(self.store, "tool-task", self.record(), lease_token="any", clock=self.clock)
        self.assertIn(raised.exception.code, {"invalid_lease", "expired_lease"})
        self.assertEqual(0, len(self.store.read("tool-task")["capabilities"]))

    def test_dropped_task_is_rejected(self):
        lease = self.started_task()
        task = self.store.read("tool-task")
        confirmation = {
            "source_id": "drop-1", "type": "conversation", "at": self.clock(), "actor": self.user,
            "reference": "prompt:drop", "quote": "drop it", "scope": "task",
            "validates": source_snapshot(task),
        }
        self.service.drop("tool-task", actor=self.user, confirmation=confirmation,
                          reason="no longer needed", disposition="keep")
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(self.store, "tool-task", self.record(), lease_token=lease["token"], clock=self.clock)
        self.assertEqual("tools_task_dropped", raised.exception.code)

    def test_session_only_record_touches_nothing(self):
        def snapshot():
            return sorted(str(path) for path in self.tmp.name and Path(self.tmp.name).rglob("*"))

        before = snapshot()
        result = tools.record_provenance(self.store, None, self.record(), lease_token=None, clock=self.clock)
        self.assertEqual("session_only", result["persistence"])
        self.assertEqual(before, snapshot())

    def test_rebuild_replaces_the_snapshot_under_both_locks(self):
        lease = self.started_task()
        rebuilt = self.record(call_id="call-1")
        rebuilt["fallback"] = True
        rebuilt["binding_digest"] = "digest-after-race"

        def rebuild(task):
            # Runs under the task lock and the cooperating tools lock: a second
            # descriptor cannot re-acquire that lock non-blockingly, proving the
            # rebuild is inside the critical section.
            with (self.runtime / "tools.lock").open("a+") as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return rebuilt

        result = tools.record_provenance(
            self.store, "tool-task", self.record(), lease_token=lease["token"], clock=self.clock,
            rebuild=rebuild, runtime_root=self.runtime,
        )
        self.assertTrue(result["rebuilt"])
        stored = self.store.read("tool-task")["capabilities"]
        self.assertEqual(1, len(stored))
        self.assertTrue(stored[0]["fallback"])
        self.assertEqual("digest-after-race", stored[0]["binding_digest"])

    def test_rebuild_rejects_lease_expiring_during_callback_and_releases_locks(self):
        lease = self.started_task()
        before = self.store.read("tool-task")
        def rebuild(task):
            self.clock.set("2027-01-01T00:00:00Z")
            return self.record()
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(self.store, "tool-task", None, lease_token=lease["token"], clock=self.clock,
                                    rebuild=rebuild, runtime_root=self.runtime)
        self.assertEqual("expired_lease", raised.exception.code)
        self.assertEqual(before, self.store.read("tool-task"))
        with self.store.transaction():
            with tools.tools_lock(self.runtime):
                pass

    def test_rebuild_requires_runtime_root_and_session_only_rejects_it(self):
        lease = self.started_task()
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(
                self.store, "tool-task", self.record(), lease_token=lease["token"], clock=self.clock,
                rebuild=lambda task: self.record(), runtime_root=None,
            )
        self.assertEqual("tools_invalid_record", raised.exception.code)
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(
                self.store, None, self.record(), lease_token=None, clock=self.clock,
                rebuild=lambda task: self.record(), runtime_root=self.runtime,
            )
        self.assertEqual("tools_invalid_record", raised.exception.code)
        self.assertEqual(0, len(self.store.read("tool-task")["capabilities"]))

    def test_rebuild_conflict_and_idempotence_use_the_rebuilt_record(self):
        lease = self.started_task()
        committed = self.record(call_id="call-1")
        tools.record_provenance(self.store, "tool-task", committed, lease_token=lease["token"], clock=self.clock)
        # Same id, different content after the rebuild: a conflict.
        changed = self.record(call_id="call-1")
        changed["fallback"] = True
        with self.assertRaises(DomainError) as raised:
            tools.record_provenance(
                self.store, "tool-task", committed, lease_token=lease["token"], clock=self.clock,
                rebuild=lambda task: changed, runtime_root=self.runtime,
            )
        self.assertEqual("tools_provenance_conflict", raised.exception.code)
        # Same id and identical content after the rebuild: idempotent.
        again = tools.record_provenance(
            self.store, "tool-task", committed, lease_token=lease["token"], clock=self.clock,
            rebuild=lambda task: copy.deepcopy(committed), runtime_root=self.runtime,
        )
        self.assertTrue(again["idempotent"])
        self.assertEqual(1, len(self.store.read("tool-task")["capabilities"]))


# ---------------------------------------------------------------------------
# T9: the single tools scan command and the injected classifier protocol
# ---------------------------------------------------------------------------

SCAN_SNAPSHOT = {
    "schema": "fstar.tools.scan.v1",
    "detected_at": "2026-10-29T08:00:00Z",
    "tools": [],
    "observations": [],
    "proposals": [],
    "diagnostics": [],
}


def _fake_classifier(scan_function):
    module = types.ModuleType("fstar.tool_classifier")
    module.__spec__ = importlib.machinery.ModuleSpec("fstar.tool_classifier", loader=None)
    module.scan_tools = scan_function
    return module


class ScanCommandTests(ToolsCase):
    def tearDown(self):
        sys.modules.pop("fstar.tool_classifier", None)

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_parser_exposes_only_tools_scan(self):
        parser = cli.build_parser()
        actions = [action for action in parser._actions
                   if isinstance(action, __import__("argparse")._SubParsersAction)]
        self.assertEqual(1, len(actions))
        choices = actions[0].choices
        self.assertIn("tools", choices)
        # The tools module registers no user command of its own beyond scan.
        # install/update/uninstall/doctor/migrate/version are the installer's
        # package-management surface (parent design §4.1), not tools commands.
        for forbidden in ("bind", "status", "validate", "verify", "reminder"):
            self.assertNotIn(forbidden, choices)
        nested = [action for action in choices["tools"]._actions
                  if isinstance(action, __import__("argparse")._SubParsersAction)]
        self.assertEqual(1, len(nested))
        self.assertEqual({"scan"}, set(nested[0].choices))

    def test_scan_handler_runs_before_project_discovery_and_reports_unavailable(self):
        # The classifier is delivered; simulate its genuine absence (the import
        # machinery treats a None entry as "module missing") so the shell's
        # pre-service-discovery unavailability path stays covered.
        with mock.patch.dict(sys.modules, {"fstar.tool_classifier": None}):
            with tempfile.TemporaryDirectory() as empty:
                previous = os.getcwd()
                os.chdir(empty)
                try:
                    code, _, stderr = self.run_cli([
                        "--json", "--user-data-root", str(self.user),
                        "--runtime-root", str(self.runtime), "tools", "scan",
                    ])
                finally:
                    os.chdir(previous)
        self.assertNotEqual(0, code)
        payload = json.loads(stderr)
        self.assertEqual("tools_classifier_unavailable", payload["error"]["code"])
        self.assertNotEqual("project_not_initialized", payload["error"]["code"])
        self.assertIn("details", payload["error"])

    def test_delivered_classifier_scan_runs_through_cli_on_uninitialized_directory(self):
        # Positive path: the real delivered classifier runs through the real
        # cli.main on an uninit directory and returns a valid scan.v1.
        with tempfile.TemporaryDirectory() as empty:
            previous = os.getcwd()
            os.chdir(empty)
            try:
                code, stdout, stderr = self.run_cli([
                    "--json", "--user-data-root", str(self.user),
                    "--runtime-root", str(self.runtime), "tools", "scan",
                ])
            finally:
                os.chdir(previous)
        self.assertEqual(0, code)
        payload = json.loads(stdout)
        self.assertEqual("fstar.tools.scan.v1", payload["schema"])
        self.assertEqual(
            sorted(["schema", "detected_at", "tools", "observations", "proposals", "diagnostics"]),
            sorted(payload),
        )
        # A scan is proposal-only: no binding or metadata is created.
        self.assertFalse((Path(empty) / ".fstar").exists())
        self.assertFalse((self.user / "tools.yaml").exists())

    def test_injected_fixed_snapshot_is_returned_through_the_cli(self):
        calls = {}

        def scan_tools(*, project_root, user_root, host_snapshot):
            calls["project_root"] = project_root
            calls["user_root"] = user_root
            calls["host_snapshot"] = host_snapshot
            return copy.deepcopy(SCAN_SNAPSHOT)

        sys.modules["fstar.tool_classifier"] = _fake_classifier(scan_tools)
        with tempfile.TemporaryDirectory() as empty:
            previous = os.getcwd()
            os.chdir(empty)
            try:
                code, stdout, _ = self.run_cli([
                    "--json", "--user-data-root", str(self.user),
                    "--runtime-root", str(self.runtime), "tools", "scan",
                ])
            finally:
                os.chdir(previous)
        self.assertEqual(0, code)
        self.assertEqual(SCAN_SNAPSHOT, json.loads(stdout))
        self.assertEqual(Path(empty).resolve(), calls["project_root"])
        self.assertEqual(self.user.resolve(), calls["user_root"])
        self.assertIsNone(calls["host_snapshot"])
        self.assertFalse((Path(empty) / ".fstar").exists())
        self.assertFalse((self.user / "tools.yaml").exists())

    def test_internal_import_failure_is_not_swallowed(self):
        # A module that exists but whose own imports fail must surface as
        # tools_classifier_import_failed, never as an empty successful scan.
        # The real classifier is delivered, so the failure is injected through a
        # raising loader on the import path (the delivered module is untouched).
        tools._classifier_scan()  # ensure the real module is cached first
        real = sys.modules["fstar.tool_classifier"]

        class RaisingLoader:
            def create_module(self, module):
                raise ImportError("internal dependency missing")

            def exec_module(self, module):
                raise ImportError("internal dependency missing")

        spec = importlib.machinery.ModuleSpec("fstar.tool_classifier", RaisingLoader())
        finder = types.SimpleNamespace(find_spec=lambda fullname, path=None, target=None: spec)

        def restore():
            sys.meta_path.pop(0)
            sys.modules.pop("fstar.tool_classifier", None)
            sys.modules["fstar.tool_classifier"] = real

        sys.modules.pop("fstar.tool_classifier", None)
        sys.meta_path.insert(0, finder)
        self.addCleanup(restore)
        with self.assertRaises(DomainError) as raised:
            tools._classifier_scan()
        self.assertEqual("tools_classifier_import_failed", raised.exception.code)
        self.assertNotEqual("tools_classifier_unavailable", raised.exception.code)
        restore()
        # The delivered classifier still resolves after the injection is removed.
        self.assertTrue(callable(tools._classifier_scan()))

    def test_classifier_runtime_error_propagates(self):
        def scan_tools(**kwargs):
            raise RuntimeError("classifier exploded")

        sys.modules["fstar.tool_classifier"] = _fake_classifier(scan_tools)
        with self.assertRaises(RuntimeError):
            tools._handle_tools_scan(types.SimpleNamespace(
                project=None, user_data_root=str(self.user), runtime_root=str(self.runtime),
            ))

    def test_invalid_scan_result_is_rejected(self):
        def scan_tools(**kwargs):
            return {"schema": "wrong", "tools": []}

        sys.modules["fstar.tool_classifier"] = _fake_classifier(scan_tools)
        with self.assertRaises(DomainError) as raised:
            tools._handle_tools_scan(types.SimpleNamespace(
                project=None, user_data_root=str(self.user), runtime_root=str(self.runtime),
            ))
        self.assertEqual("tools_scan_invalid", raised.exception.code)

    def test_bare_tools_requires_a_subcommand(self):
        code, _, stderr = self.run_cli(["--json", "tools"])
        self.assertNotEqual(0, code)
        self.assertEqual("tools_command_required", json.loads(stderr)["error"]["code"])

    def test_cli_subprocess_smoke_on_uninitialized_directory(self):
        # Real subprocess: the delivered classifier returns a valid scan.v1 on
        # an uninit directory and creates no fstar metadata anywhere.
        with tempfile.TemporaryDirectory() as empty:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(ROOT / "src")
            completed = subprocess.run(
                [sys.executable, "-m", "fstar", "--json", "--user-data-root", str(self.user),
                 "--runtime-root", str(self.runtime), "tools", "scan"],
                cwd=empty, env=environment, capture_output=True, text=True, timeout=60,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(0, completed.returncode)
            self.assertEqual("fstar.tools.scan.v1", payload["schema"])
            self.assertFalse((Path(empty) / ".fstar").exists())
        self.assertFalse((self.user / "tools.yaml").exists())

    def test_cli_subprocess_reports_unavailable_when_module_is_genuinely_absent(self):
        # The unavailable shell contract stays covered in a real subprocess:
        # marking the module missing before importing the CLI yields the stable
        # non-zero tools_classifier_unavailable, not project_not_initialized.
        program = (
            "import sys, json, io, contextlib, os, tempfile\n"
            "sys.modules['fstar.tool_classifier'] = None\n"
            "from fstar import cli\n"
            "with tempfile.TemporaryDirectory() as empty:\n"
            "    previous = os.getcwd(); os.chdir(empty)\n"
            "    try:\n"
            "        out, err = io.StringIO(), io.StringIO()\n"
            "        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):\n"
            "            code = cli.main(['--json', 'tools', 'scan'])\n"
            "    finally:\n"
            "        os.chdir(previous)\n"
            "print(json.dumps({'code': code, 'stderr': err.getvalue()}))\n"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-c", program],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, completed.returncode)
        outcome = json.loads(completed.stdout)
        self.assertNotEqual(0, outcome["code"])
        payload = json.loads(outcome["stderr"])
        self.assertEqual("tools_classifier_unavailable", payload["error"]["code"])
        self.assertNotEqual("project_not_initialized", payload["error"]["code"])


# ---------------------------------------------------------------------------
# T10: contracts, schema, reference, and public surfaces
# ---------------------------------------------------------------------------

class ResourceContractTests(unittest.TestCase):
    def test_exactly_five_contracts_with_seven_sections(self):
        files = sorted(path.name for path in (RESOURCES / "capabilities").glob("*.md"))
        self.assertEqual(sorted("%s.md" % capability for capability in CAPABILITIES), files)
        for capability in CAPABILITIES:
            text = (RESOURCES / "capabilities" / ("%s.md" % capability)).read_text(encoding="utf-8")
            with self.subTest(capability=capability):
                self.assertIn("id: %s" % capability, text)
                positions = [text.index(heading) for heading in SECTION_HEADINGS]
                self.assertEqual(sorted(positions), positions)
                self.assertNotIn("code-text", text)
                normalized = " ".join(text.split())
                self.assertIn(" ".join(tools.FALLBACKS[capability].split()), normalized)

    def test_contracts_include_judgment_points_and_safe_probes(self):
        code_structure = (RESOURCES / "capabilities" / "code-structure.md").read_text(encoding="utf-8")
        self.assertIn("file:line", code_structure)
        data_access = (RESOURCES / "capabilities" / "data-access.md").read_text(encoding="utf-8")
        self.assertIn("write statement is never a verification probe", data_access)
        test_execution = (RESOURCES / "capabilities" / "test-execution.md").read_text(encoding="utf-8")
        self.assertIn("isolated fixture", test_execution)
        self.assertIn("not a side-effect-free probe", test_execution)

    def test_published_schema_json(self):
        schema = json.loads((RESOURCES / "schemas" / "tools.schema.json").read_text(encoding="utf-8"))
        self.assertIn("$schema", schema)
        self.assertEqual(
            ["schema", "detected_at", "tools", "bindings", "history"], schema["required"],
        )
        capability_enum = schema["definitions"]["match"]["properties"]["id"]["enum"]
        self.assertEqual(list(CAPABILITIES), capability_enum)
        raw = json.dumps(schema)
        self.assertNotIn("code-text", raw)
        self.assertEqual("fstar.tools.v1", schema["properties"]["schema"]["const"])
        self.assertFalse(schema["additionalProperties"])

    def test_reference_examples_parse_with_the_real_parser(self):
        from fstar.config import parse_config

        text = (RESOURCES / "references" / "tool-bindings.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
        self.assertTrue(blocks)
        for block in blocks:
            document = tools.validate_tools(parse_config(block, Path("fixture/tools.yaml")))
            self.assertEqual("fstar.tools.v1", document["schema"])
            # And the same document round-trips through the schema writer.
            self.assertEqual(document, tools.validate_tools(
                parse_config(tools.serialize_tools(document), Path("fixture/tools.yaml"))))

    def test_single_guidance_entry_and_reference_loading(self):
        skill = (RESOURCES / "skills" / "fstar-tools" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("../../references/tool-bindings.md", skill)
        self.assertIn("fstar tools scan", skill)
        self.assertIn("Do not install tools or change bindings automatically", skill)
        reference = (RESOURCES / "references" / "tool-bindings.md").read_text(encoding="utf-8")
        for needle in ("Supported YAML subset", "fstar.tools.scan.v1", "fstar.tool-use.v1",
                       "tools_confirmation_required", "tools_stale_confirmation"):
            self.assertIn(needle, reference)

    def test_resources_still_validate_cleanly(self):
        self.assertEqual([], [diagnostic.code for diagnostic in validate_resources(RESOURCES)])

    def test_public_api_surface(self):
        for name in (
            "load_tools", "validate_tools", "resolve_bindings", "build_binding_proposal",
            "apply_binding", "assess_availability", "build_provenance", "record_provenance",
            "register_commands",
        ):
            self.assertTrue(callable(getattr(tools, name)), name)
        self.assertEqual(5, len(tools.CAPABILITIES))
        self.assertEqual(5, len(tools.FALLBACKS))


if __name__ == "__main__":
    unittest.main()
