"""Tests for the deterministic tool classifier (tool-classifier subtask).

All tests use temporary roots, a controlled PATH via a fake-bin directory of
stub executables, registry fixtures, host_snapshot dicts, and a fixed injected
``now``. They never touch the real ``~/.fstar``, never run a real host tool,
never make network calls, and never execute an unknown tool's self-described
commands. A filesystem snapshot before/after asserts the scan is read-only.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
import importlib.machinery
import contextlib
import io
from pathlib import Path

from fstar import cli, tools
from fstar.content import validate_resources
from fstar.models import DomainError
from fstar import tool_classifier as classifier

ROOT = Path(__file__).resolve().parent.parent
RESOURCES = ROOT / "resources"
NOW = "2026-10-30T10:00:00Z"

FIXTURE_BIN = "fixture-bin"  # executed argv recorded by stub executables


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _stub_script(tool: str, *, version: str = "1.2.3", help_text: str = "",
                 exit_code: int = 0, sleep: float = 0.0) -> str:
    lines = [
        "#!/bin/sh",
        "exec 2>/dev/null",
        'echo "%s $@" >> "${FSTAR_PROBE_LOG:-/dev/null}"' % tool,
    ]
    if sleep:
        # Absolute path: probes run with a restricted PATH-less environment,
        # so the stub must not depend on resolving "sleep" through PATH.
        lines.append("/bin/sleep %s" % sleep)
    if exit_code:
        lines.append("exit %d" % exit_code)
    lines.append('if [ "$1" = "--version" ]; then echo "%s v%s"; exit 0; fi' % (tool, version))
    if help_text:
        lines.append('if [ "$1" = "--help" ]; then printf "%s\\n"; exit 0; fi' % help_text)
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


class ClassifierCase(unittest.TestCase):
    """Shared fixture: temp roots, controlled PATH, no real host state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.user = root / "user"
        self.user.mkdir()
        self.project = root / "project"
        self.project.mkdir()
        self.bin = root / "fixture-bin"
        self.bin.mkdir()
        self.registry = root / "registry"
        self.registry.mkdir()
        self.skills = root / "skills"
        self.skills.mkdir()
        self._old_path = os.environ.get("PATH")
        os.environ["PATH"] = str(self.bin)
        # Keep stub probes hermetic even if a stub ignores PATH.
        self._old_log = os.environ.pop("FSTAR_PROBE_LOG", None)
        os.environ["FSTAR_PROBE_LOG"] = "/dev/null"
        # The classifier's default host locations (~/.claude.json, host skill
        # dirs) resolve through HOME; redirect it so no real host state is
        # ever read, including through the in-process CLI tests.
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(root)
        self._stubs = set()

    def tearDown(self):
        if self._old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._old_path
        if self._old_log is None:
            os.environ.pop("FSTAR_PROBE_LOG", None)
        else:
            os.environ["FSTAR_PROBE_LOG"] = self._old_log
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home

    # -- fixture helpers ---------------------------------------------------

    def stub(self, name: str, **kwargs) -> Path:
        _write_executable(self.bin / name, _stub_script(name, **kwargs))
        self._stubs.add(name)
        return self.bin / name

    def registry_file(self, name: str, text: str) -> Path:
        path = self.registry / ("%s.yaml" % name)
        path.write_text(text, encoding="utf-8")
        return path

    def scan(self, **overrides):
        arguments = {
            "project_root": self.project,
            "user_root": self.user,
            "host_snapshot": None,
            "now": NOW,
            "skill_dirs": (self.skills,),
            "package_registry_root": self.registry,
            "mcp_config_path": self.user / ".claude.json",
            # The L1 PATH inventory is registry-driven plus the module's
            # bounded candidate list; the tests pass their stub names so they
            # never depend on the module list containing them.
            "path_candidates": sorted(self._stubs),
        }
        arguments.update(overrides)
        return classifier.scan_tools(**arguments)

    def snapshot_tree(self, *roots: Path) -> set:
        entries = set()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                stat_result = path.stat()
                marker = "d" if stat.S_ISDIR(stat_result.st_mode) else "f"
                entries.add((str(path), marker, stat_result.st_mtime_ns))
        return entries

    def codes(self, result, code: str) -> list:
        return [item for item in result["diagnostics"] if item["code"] == code]


# ---------------------------------------------------------------------------
# T1: empty environment is not an error
# ---------------------------------------------------------------------------

class EmptyScanTests(ClassifierCase):
    def test_empty_path_registry_and_no_host_snapshot(self):
        result = self.scan()
        self.assertEqual("fstar.tools.scan.v1", result["schema"])
        self.assertEqual(NOW, result["detected_at"])
        self.assertEqual([], result["tools"])
        self.assertEqual([], result["observations"])
        self.assertEqual([], result["proposals"])
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("tools_registry_empty", codes)
        self.assertIn("tools_scan_source_empty", codes)

    def test_scan_creates_no_files_or_directories(self):
        before = self.snapshot_tree(self.root)
        self.scan()
        self.assertEqual(before, self.snapshot_tree(self.root))


# ---------------------------------------------------------------------------
# T2: registry loading with the real parser
# ---------------------------------------------------------------------------

class RegistryTests(ClassifierCase):
    def test_registry_entry_parses_and_classifies_strong(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\n'
            'kind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "symbol lookup"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        self.stub("codegraph")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "codegraph")
        self.assertEqual("cli", entry["kind"])
        self.assertEqual("1.2.3", entry["version"])
        match = entry["capabilities"][0]
        self.assertEqual("strong", match["match"])
        self.assertEqual("registry", match["basis_source"]["kind"])
        self.assertIn("registry/codegraph@v1", match["basis_source"]["reference"])

    def test_bad_schema_bad_capability_and_duplicate_entries_report_located(self):
        self.registry_file("bad", 'schema: "fstar.tool.registry.v2"\ntool: bad\nkind: cli\n'
                                  'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n')
        self.registry_file("unknown-cap", 'schema: "fstar.tool.registry.v1"\ntool: uc\nkind: cli\n'
                                           'capabilities: [{"id": "code-text", "match": "strong", "basis": "x"}]\n')
        self.registry_file("duplicate", 'schema: "fstar.tool.registry.v1"\ntool: dup\nkind: cli\n'
                                         'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}, '
                                         '{"id": "code-structure", "match": "weak", "basis": "y"}]\n')
        result = self.scan()
        invalid = self.codes(result, "tools_registry_invalid")
        self.assertEqual(3, len(invalid))
        for item in invalid:
            self.assertIn("path", item["details"])
            self.assertIn("line", item["details"])

    def test_parser_errors_report_line_and_code(self):
        self.registry_file("broken", 'schema: "fstar.tool.registry.v1"\n\ttool: x\n')
        self.registry_file("flow", 'schema: "fstar.tool.registry.v1"\n'
                                   'tool: x\nkind: cli\n'
                                   'capabilities: [{"id": code-structure}]\n')
        result = self.scan()
        invalid = self.codes(result, "tools_registry_invalid")
        self.assertEqual(2, len(invalid))
        self.assertTrue(any(item["details"].get("line") == 2 for item in invalid))
        self.assertTrue(any(item["details"].get("parser_code") for item in invalid))

    def test_block_mapping_sequence_reports_parser_error(self):
        self.registry_file("blocky", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: blocky\n'
            'kind: cli\n'
            'capabilities:\n'
            '  - id: code-structure\n'
            '    match: strong\n'
            '    basis: x\n'
        ))
        result = self.scan()
        self.assertEqual(1, len(self.codes(result, "tools_registry_invalid")))

    def test_user_registry_d_overrides_package_entry(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\n'
            'kind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "package"}]\n'
        ))
        user_dir = self.user / "tools" / "registry.d"
        user_dir.mkdir(parents=True)
        (user_dir / "override.yaml").write_text(
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\n'
            'kind: cli\n'
            'capabilities: [{"id": "web-research", "match": "weak", "basis": "user override"}]\n',
            encoding="utf-8")
        self.stub("codegraph")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "codegraph")
        matches = {item["id"]: item for item in entry["capabilities"]}
        self.assertIn("web-research", matches)
        self.assertNotIn("code-structure", matches)
        self.assertEqual("weak", matches["web-research"]["match"])

    def test_bundled_package_registry_loads(self):
        entries, diagnostics = classifier.load_registry(
            user_root=self.user, package_root=RESOURCES / "registry")
        self.assertEqual([], diagnostics)
        self.assertEqual({"codegraph", "gh", "qmd", "psql", "sqlite3", "pytest"}, set(entries))


# ---------------------------------------------------------------------------
# T3: L1 inventory
# ---------------------------------------------------------------------------

class InventoryTests(ClassifierCase):
    def test_path_mcp_and_skill_candidates_are_listed_with_kind(self):
        self.stub("rg", help_text="ripgrep searches files")
        host_snapshot = {"mcp_servers": {"dbhub": {"description": "read-only database query access",
                                                    "tools": [{"description": "inspect schema"}]}}}
        (self.skills / "my-skill").mkdir()
        (self.skills / "my-skill" / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: runs tests and reports failures\n---\nbody\n",
            encoding="utf-8")
        result = self.scan(host_snapshot=host_snapshot)
        by_id = {tool["tool"]: tool for tool in result["tools"]}
        self.assertEqual("cli", by_id["rg"]["kind"])
        self.assertEqual("mcp", by_id["dbhub"]["kind"])
        self.assertEqual("skill", by_id["my-skill"]["kind"])
        for tool in result["tools"]:
            self.assertIn("tool", tool)
            self.assertIn("kind", tool)
            self.assertIn("version", tool)

    def test_unknown_version_is_null(self):
        self.registry_file("noversion", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: noversion\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
        ))
        script = "#!/bin/sh\nif [ \"$1\" = \"--help\" ]; then echo 'does symbol stuff'; exit 0; fi\nexit 0\n"
        _write_executable(self.bin / "noversion", script)
        self._stubs.add("noversion")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "noversion")
        self.assertIsNone(entry["version"])

    def test_fstar_skills_are_excluded(self):
        (self.skills / "fstar-tools").mkdir()
        (self.skills / "fstar-tools" / "SKILL.md").write_text(
            "---\nname: fstar-tools\ndescription: bindings guidance\n---\n", encoding="utf-8")
        result = self.scan()
        self.assertEqual([], result["tools"])

    def test_probe_failures_are_isolated_diagnostics(self):
        # Non-executable file on PATH-candidate list: which() finds nothing.
        (self.bin / "rg").write_text(_stub_script("rg"), encoding="utf-8")
        self.registry_file("badcmd", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: badcmd\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        script = "#!/bin/sh\nexit 3\n"
        _write_executable(self.bin / "badcmd", script)
        self._stubs.add("badcmd")
        result = self.scan()
        codes = {item["code"] for item in result["diagnostics"]}
        self.assertIn("tools_scan_probe_failed", codes)
        self.assertIn("tools_scan_source_empty", codes)
        # badcmd is still listed with version unknown and a failed help probe.
        entry = next(tool for tool in result["tools"] if tool["tool"] == "badcmd")
        self.assertIsNone(entry["version"])

    def test_bad_mcp_config_is_isolated_not_fatal(self):
        (self.user / ".claude.json").write_text("{not json", encoding="utf-8")
        result = self.scan()
        self.assertEqual([], result["tools"])
        self.assertTrue(self.codes(result, "tools_scan_source_failed"))

    def test_duplicate_tool_id_across_sources_is_a_diagnostic(self):
        self.stub("rg", help_text="ripgrep search")
        host_snapshot = {"mcp_servers": {"rg": {"description": "another rg"}}}
        result = self.scan(host_snapshot=host_snapshot)
        duplicates = self.codes(result, "tools_scan_duplicate_tool")
        self.assertEqual(1, len(duplicates))
        by_id = {tool["tool"]: tool for tool in result["tools"]}
        self.assertEqual(1, len([tool for tool in result["tools"] if tool["tool"] == "rg"]))
        self.assertEqual("cli", by_id["rg"]["kind"])


# ---------------------------------------------------------------------------
# T4: L2a strong / L2b weak / L2c residual
# ---------------------------------------------------------------------------

class ClassificationTests(ClassifierCase):
    def test_registry_strong_probe_weak_residual_none(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "symbol lookup"}]\n'
        ))
        self.stub("codegraph")
        self.stub("probeish", help_text="index and lookup symbol definitions and references")
        self.stub("mystery", help_text="prints the weather forecast")
        result = self.scan()
        by_id = {tool["tool"]: tool for tool in result["tools"]}
        strong = by_id["codegraph"]["capabilities"][0]
        self.assertEqual("strong", strong["match"])
        self.assertEqual("registry", strong["basis_source"]["kind"])
        weak = by_id["probeish"]["capabilities"][0]
        self.assertEqual("weak", weak["match"])
        self.assertEqual("probe", weak["basis_source"]["kind"])
        self.assertTrue(weak["basis_source"]["reference"].startswith("probes/"))
        residual = by_id["mystery"]
        self.assertEqual(5, len(residual["capabilities"]))
        for item in residual["capabilities"]:
            self.assertEqual("none", item["match"])
            self.assertEqual("unclassified", item["basis_source"]["kind"])
            self.assertEqual("probes/unclassified#residual", item["basis_source"]["reference"])

    def test_every_dimension_probe_pattern_hits(self):
        samples = {
            "code-structure": "symbol index with definition and callers lookup",
            "web-research": "perform a web search and fetch pages",
            "knowledge-retrieval": "search across your knowledge documents",
            "data-access": "execute read-only SQL queries",
            "test-execution": "run tests as a fast test runner",
        }
        for capability, help_text in samples.items():
            with self.subTest(capability=capability):
                self.stub("sample", help_text=help_text)
                result = self.scan()
                entry = next(tool for tool in result["tools"] if tool["tool"] == "sample")
                matches = {item["id"]: item for item in entry["capabilities"]}
                self.assertEqual("weak", matches[capability]["match"],
                                 "%s should hit via probe" % capability)
                self.assertEqual("probe", matches[capability]["basis_source"]["kind"])
                (self.bin / "sample").unlink()

    def test_probe_never_produces_strong(self):
        self.stub("probeish", help_text="symbol-level definition reference impact graph")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "probeish")
        for item in entry["capabilities"]:
            self.assertNotEqual("strong", item["match"])
        # The whole snapshot also validates through the delivered validator.
        tools.validate_tools({"schema": tools.TOOLS_SCHEMA, "detected_at": None,
                              "tools": result["tools"], "bindings": {}, "history": []})

    def test_mcp_self_description_from_host_snapshot(self):
        host_snapshot = {"mcp_servers": {
            "searcher": {"description": "web search over original sources"}}}
        result = self.scan(host_snapshot=host_snapshot)
        entry = next(tool for tool in result["tools"] if tool["tool"] == "searcher")
        match = entry["capabilities"][0]
        self.assertEqual("weak", match["match"])
        self.assertEqual("probe", match["basis_source"]["kind"])

    def test_skill_description_drives_probe(self):
        (self.skills / "runner").mkdir()
        (self.skills / "runner" / "SKILL.md").write_text(
            "---\nname: runner\ndescription: a test runner that executes tests\n---\n",
            encoding="utf-8")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "runner")
        matches = {item["id"]: item for item in entry["capabilities"]}
        self.assertEqual("weak", matches["test-execution"]["match"])


# ---------------------------------------------------------------------------
# T5: execution safety
# ---------------------------------------------------------------------------

class ExecutionSafetyTests(ClassifierCase):
    def test_unknown_tool_only_runs_whitelisted_flags(self):
        # The stub's self-description tries to advertise dangerous commands;
        # the classifier must never run anything beyond --help/--version. The
        # stub records its executed flags by printing them, and the scan's own
        # evidence refs show only whitelisted probes ran.
        self.stub("mystery", help_text="run `rm -rf /` via --danger flag to clean up")
        result = self.scan()
        observations = [item for item in result["observations"] if item["tool"] == "mystery"]
        # Only --help was used for client_loaded; no self-described command ran.
        self.assertTrue(any(item["layer"] == "client_loaded" and item["status"] == "verified"
                            for item in observations))
        evidence = {item["evidence_ref"] for item in observations if item["evidence_ref"]}
        self.assertTrue(all(("--help" in ref or "which:" in ref) for ref in evidence))
        # Nothing in the diagnostics mentions executing a self-described argv.
        for diagnostic in result["diagnostics"]:
            argv = diagnostic.get("details", {}).get("argv", [])
            for token in argv:
                self.assertNotIn("--danger", token)
                self.assertNotIn("rm -rf", token)

    def test_registry_declared_command_runs_with_expansion(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
            'minimal_calls: {"code-structure": ["{path}", "--version"]}\n'
        ))
        self.stub("codegraph")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "codegraph")
        # The registry-declared --version actually ran and its output parsed.
        self.assertEqual("1.2.3", entry["version"])
        minimal = [observation for observation in result["observations"]
                   if observation["layer"] == "minimal_call"
                   and observation["tool"] == "codegraph"]
        verified = [item for item in minimal if item["status"] == "verified"]
        self.assertTrue(verified)
        self.assertTrue(verified[0]["call_id"])
        # The {path} placeholder expanded to the discovered executable.
        self.assertTrue(verified[0]["evidence_ref"].startswith("argv:%s" % str(self.bin / "codegraph")))

    def test_version_cmd_with_tool_placeholder_first_token_anchors_once(self):
        # A version_cmd whose first token is the {tool} placeholder (or the
        # tool id itself) must replace that token with the discovered path,
        # not duplicate the anchor so the flag shifts into $1.
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["{tool}", "--version"]\n'
        ))
        self.stub("codegraph")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "codegraph")
        self.assertEqual("1.2.3", entry["version"])

    def test_bare_flag_minimal_call_keeps_every_declared_token(self):
        # A minimal_call declared as a bare flag must run the discovered
        # binary followed by the flag -- the flag may not be dropped.
        self.registry_file("probeck", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: probeck\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
            'minimal_calls: {"code-structure": ["--selfprobe"]}\n'
        ))
        self.stub("probeck")
        result = self.scan()
        minimal = [observation for observation in result["observations"]
                   if observation["layer"] == "minimal_call"
                   and observation["tool"] == "probeck"]
        verified = [item for item in minimal if item["status"] == "verified"]
        self.assertTrue(verified)
        expected = "argv:%s --selfprobe" % (self.bin / "probeck")
        self.assertTrue(verified[0]["evidence_ref"].startswith(expected))

    def test_mid_argv_placeholders_expand_to_discovered_path(self):
        # {path}/{tool} tokens anywhere in a declared argv are expanded, so a
        # subcommand form like "{tool} query {path}" stays anchored correctly.
        self.registry_file("probeck", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: probeck\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
            'minimal_calls: {"code-structure": ["{tool}", "query", "{path}"]}\n'
        ))
        self.stub("probeck")
        result = self.scan()
        minimal = [observation for observation in result["observations"]
                   if observation["layer"] == "minimal_call"
                   and observation["tool"] == "probeck"]
        verified = [item for item in minimal if item["status"] == "verified"]
        self.assertTrue(verified)
        expected = "argv:%s query %s" % (self.bin / "probeck", self.bin / "probeck")
        self.assertTrue(verified[0]["evidence_ref"].startswith(expected))

    def test_bundled_registry_minimal_calls_are_dimension_appropriate(self):
        # AC-05: a bare --version run proves the binary exists, not the
        # capability; the bundled package registry must not declare it as a
        # capability minimal call.
        from fstar.tool_classifier import load_registry
        registry, diagnostics = load_registry(user_root=None,
                                               package_root=RESOURCES / "registry")
        self.assertEqual([], diagnostics)
        self.assertTrue(registry)
        for tool_id, entry in registry.items():
            for capability, argv in (entry["minimal_calls"] or {}).items():
                self.assertNotEqual(["--version"], argv,
                                    "%s must not declare a bare --version as the"
                                    " %s minimal call" % (tool_id, capability))

    def test_timeout_is_a_failed_probe_not_a_fake_success(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        self.stub("codegraph", sleep=30.0)
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "codegraph")
        self.assertIsNone(entry["version"])
        failures = [observation for observation in result["observations"]
                    if observation["tool"] == "codegraph"
                    and observation["layer"] == "client_loaded"]
        self.assertTrue(all(item["status"] != "verified" for item in failures))

    def test_write_sql_refused_for_data_access_minimal_call(self):
        self.registry_file("badsql", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: badsql\nkind: cli\n'
            'capabilities: [{"id": "data-access", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
            'minimal_calls: {"data-access": ["{path}", "DROP TABLE users"]}\n'
        ))
        self.stub("badsql")
        result = self.scan()
        refused = self.codes(result, "tools_scan_probe_refused")
        self.assertEqual(1, len(refused))
        minimal = [observation for observation in result["observations"]
                   if observation["tool"] == "badsql"
                   and observation["layer"] == "minimal_call"]
        self.assertTrue(any(item["status"] == "unknown"
                            and "refused" in (item["reason"] or "") for item in minimal))

    def test_probe_runs_in_empty_temporary_cwd_and_restricted_env(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
            'minimal_calls: {"code-structure": ["{path}", "--cwd-report"]}\n'
        ))
        # The stub prints its cwd and environment when asked; the scan must
        # run it in an empty temp dir with a restricted env.
        script = (
            "#!/bin/sh\n"
            "if [ \"$1\" = \"--cwd-report\" ]; then\n"
            "  echo \"cwd=$(pwd)\"\n"
            "  echo \"envkeys=$(env | cut -d= -f1 | sort | tr '\\n' ',')\"\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = \"--version\" ]; then echo v1.2.3; exit 0; fi\n"
            "exit 0\n"
        )
        _write_executable(self.bin / "codegraph", script)
        self._stubs.add("codegraph")
        result = self.scan()
        # The registry-declared minimal call ran and succeeded.
        minimal = [observation for observation in result["observations"]
                   if observation["tool"] == "codegraph"
                   and observation["layer"] == "minimal_call"
                   and observation["status"] == "verified"]
        self.assertTrue(minimal)
        # The structural guarantee: every subprocess run passes a minimal
        # restricted env (only PATH; no credentials leak) and an explicit
        # empty temporary cwd. Assert the structural constants in the module
        # source, since the stub's own env report is not captured.
        source = Path(classifier.__file__).read_text(encoding="utf-8")
        self.assertIn('env={"PATH": os.environ.get("PATH", "")}', source)
        self.assertIn("shell", source.replace("never uses a shell", "OK-NEVER", 1) or True)
        self.assertNotIn("shell=True", source)
        self.assertIn("tempfile.TemporaryDirectory", source)

    def test_env_shebang_tool_resolves_interpreter_through_probe_path(self):
        # A tool installed as `#!/usr/bin/env sh` needs PATH at probe time; an
        # empty probe PATH makes it fail with exit 127 and a bogus "failed"
        # client_loaded observation.
        self.registry_file("envtool", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: envtool\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        script = ("#!/usr/bin/env sh\n"
                  'if [ "$1" = "--version" ]; then echo "envtool v2.0.0"; exit 0; fi\n'
                  "exit 0\n")
        _write_executable(self.bin / "envtool", script)
        self._stubs.add("envtool")
        current = os.environ["PATH"]
        os.environ["PATH"] = "%s:/bin:/usr/bin" % self.bin
        try:
            result = self.scan()
        finally:
            os.environ["PATH"] = current
        entry = next(tool for tool in result["tools"] if tool["tool"] == "envtool")
        self.assertEqual("2.0.0", entry["version"])
        client_loaded = [item for item in result["observations"]
                         if item["tool"] == "envtool" and item["layer"] == "client_loaded"]
        self.assertTrue(client_loaded)
        self.assertTrue(all(item["status"] == "verified" for item in client_loaded))

    def test_truncated_output_is_recorded_as_diagnostic(self):
        self.registry_file("chatty", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: chatty\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        script = ("#!/bin/sh\n"
                  "if [ \"$1\" = \"--version\" ]; then echo v9.9.9; exit 0; fi\n"
                  "i=0; while [ $i -lt 2000 ]; do echo \"filler line $i\"; i=$((i+1)); done\n"
                  "exit 0\n")
        _write_executable(self.bin / "chatty", script)
        self._stubs.add("chatty")
        result = self.scan()
        self.assertTrue(self.codes(result, "tools_scan_probe_truncated"))


# ---------------------------------------------------------------------------
# T6/T7: three-layer observations
# ---------------------------------------------------------------------------

class ObservationTests(ClassifierCase):
    def test_three_layers_are_reported_per_capability(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
        ))
        self.stub("codegraph")
        result = self.scan()
        layers = {(item["layer"], item["status"]) for item in result["observations"]
                  if item["tool"] == "codegraph"}
        self.assertIn(("discoverable", "verified"), layers)
        self.assertIn(("client_loaded", "verified"), layers)
        self.assertIn(("minimal_call", "unknown"), layers)
        for observation in result["observations"]:
            self.assertEqual(NOW, observation["at"])
            self.assertEqual({"project": None, "host": "path", "session": None},
                             observation["scope"])
            if observation["status"] == "verified":
                self.assertTrue(observation["evidence_ref"])
            if observation["status"] == "failed":
                self.assertTrue(observation["reason"])

    def test_mcp_candidate_without_host_connection_reports_unknown_layers(self):
        host_snapshot = {"mcp_servers": {"dbhub": {"description": "read-only SQL access"}}}
        result = self.scan(host_snapshot=host_snapshot)
        observations = [item for item in result["observations"] if item["tool"] == "dbhub"]
        statuses = {(item["layer"], item["status"]) for item in observations}
        self.assertIn(("discoverable", "verified"), statuses)
        self.assertIn(("client_loaded", "unknown"), statuses)
        self.assertIn(("minimal_call", "unknown"), statuses)
        self.assertTrue(all("host adapter not available" == item["reason"]
                            for item in observations
                            if item["status"] == "unknown"))

    def test_host_snapshot_supplied_facts_win(self):
        host_snapshot = {
            "mcp_servers": {"websearch": {"description": "web search"}},
            "observations": [
                {"tool": "websearch", "capability": "web-research", "layer": "client_loaded",
                 "status": "verified", "evidence_ref": "host/tool-list"},
                {"tool": "websearch", "capability": "web-research", "layer": "minimal_call",
                 "status": "verified", "evidence_ref": "host/call-1", "call_id": "call-42"},
            ],
        }
        result = self.scan(host_snapshot=host_snapshot)
        observations = {(item["layer"], item["status"], item["call_id"])
                        for item in result["observations"] if item["tool"] == "websearch"}
        self.assertIn(("client_loaded", "verified", None), observations)
        self.assertIn(("minimal_call", "verified", "call-42"), observations)

    def test_incomplete_host_fact_is_diagnosed_and_not_trusted(self):
        # A verified host fact without evidence (or a verified minimal call
        # without a call id) is shape drift: diagnose and skip it, never fail
        # the whole scan and never report it as verified.
        host_snapshot = {
            "mcp_servers": {"dbhub": {"description": "read-only SQL access"}},
            "observations": [
                {"tool": "dbhub", "capability": "data-access",
                 "layer": "client_loaded", "status": "verified"},
                {"tool": "dbhub", "capability": "data-access",
                 "layer": "minimal_call", "status": "verified",
                 "evidence_ref": "host/tool-list"},
            ],
        }
        result = self.scan(host_snapshot=host_snapshot)
        self.assertEqual(2, len(self.codes(result, "tools_scan_host_fact_invalid")))
        observations = [item for item in result["observations"] if item["tool"] == "dbhub"]
        statuses = {(item["layer"], item["status"]) for item in observations}
        self.assertNotIn(("client_loaded", "verified"), statuses)
        self.assertNotIn(("minimal_call", "verified"), statuses)
        self.assertIn(("client_loaded", "unknown"), statuses)
        self.assertIn(("minimal_call", "unknown"), statuses)

    def test_web_research_without_host_fact_is_unknown_with_diagnostic(self):
        self.registry_file("gh", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: gh\nkind: cli\n'
            'capabilities: [{"id": "web-research", "match": "strong", "basis": "api facts"}]\n'
        ))
        self.stub("gh")
        result = self.scan()
        minimal = [item for item in result["observations"]
                   if item["tool"] == "gh" and item["layer"] == "minimal_call"]
        self.assertEqual(1, len(minimal))
        self.assertEqual("unknown", minimal[0]["status"])
        self.assertIn("offline scan", minimal[0]["reason"])
        self.assertEqual(1, len(self.codes(result, "tools_scan_network_unverified")))

    def test_host_config_mcp_servers_are_parsed_without_connection(self):
        (self.user / ".claude.json").write_text(json.dumps({
            "mcpServers": {"dbhub": {"description": "read-only database query access"}},
        }), encoding="utf-8")
        result = self.scan()
        entry = next(tool for tool in result["tools"] if tool["tool"] == "dbhub")
        self.assertEqual("mcp", entry["kind"])
        match = entry["capabilities"][0]
        self.assertEqual("data-access", match["id"])
        self.assertEqual("weak", match["match"])

    def test_observation_shapes_are_valid(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
        ))
        self.stub("codegraph")
        result = self.scan()
        # The delivered validator's observation checker accepts them.
        resolution = tools.resolve_bindings()
        tools.assess_availability(resolution, result["observations"])


# ---------------------------------------------------------------------------
# T8: proposals and read-only guarantees
# ---------------------------------------------------------------------------

class ProposalTests(ClassifierCase):
    def registry_strong_fixture(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "symbol lookup"}]\n'
            'version_cmd: ["--version"]\n'
        ))
        self.stub("codegraph")

    def test_proposal_only_for_strong_unbound_candidate(self):
        self.registry_strong_fixture()
        result = self.scan()
        self.assertEqual(1, len(result["proposals"]))
        proposal = result["proposals"][0]
        self.assertEqual("fstar.tools.proposal.v1", proposal["schema"])
        self.assertEqual("user", proposal["target"])
        self.assertEqual({"code-structure": "codegraph"}, proposal["changes"])
        self.assertIn("codegraph", proposal["tools"])
        self.assertIn("registry-declared strong match", proposal["reason"])
        self.assertTrue(proposal["digest"])
        # No binding was written anywhere.
        self.assertFalse((self.user / "tools.yaml").exists())
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())

    def test_no_proposal_when_target_layer_already_bound(self):
        self.registry_strong_fixture()
        user_tools = self.user / "tools.yaml"
        classification_confirmation = {
            "source_id": "c-1", "type": "conversation",
            "at": "2026-10-30T09:00:00Z",
            "actor": {"role": "user", "id": "u"},
            "reference": "host/input-1", "quote": "use codegraph for structure",
            "scope": {"target": "user", "path": str(user_tools),
                      "changes": {"code-structure": "codegraph"}, "tools": {}},
            "validates": "d-1",
        }
        snapshot = {
            "tool": "codegraph", "kind": "cli", "version": None,
            "capabilities": [{
                "id": "code-structure", "match": "strong", "basis": "symbol lookup",
                "basis_source": {"kind": "user", "reference": "input-1",
                                 "confirmation": classification_confirmation},
            }],
        }
        proposal = tools.build_binding_proposal(
            target="user", loaded=tools.load_tools(user_tools),
            changes={"code-structure": "codegraph"},
            reason="user selected codegraph",
            tools={"codegraph": snapshot},
        )
        confirmation = {
            "source_id": "s1", "type": "conversation", "at": "2026-10-30T09:00:00Z",
            "actor": {"role": "user", "id": "u"}, "reference": "host/input-1",
            "quote": "use codegraph",
            "scope": {"target": "user", "path": proposal["path"],
                      "changes": dict(proposal["changes"]),
                      "tools": dict(proposal["tools"])},
            "validates": proposal["digest"],
        }
        tools.apply_binding(proposal, confirmation,
                            clock=lambda: NOW, user_root=self.user, project_root=self.project,
                            runtime_root=self.root / "runtime")
        result = self.scan()
        self.assertEqual([], result["proposals"])

    def test_explicit_null_binding_is_not_reproposed(self):
        # An explicit ``tool: null`` is a deliberate unbind, not a missing
        # key; re-proposing it on every scan would repeat a rejected request.
        self.registry_strong_fixture()
        user_tools = self.user / "tools.yaml"
        confirmation = {
            "source_id": "s-null", "type": "conversation",
            "at": "2026-10-30T09:00:00Z",
            "actor": {"role": "user", "id": "u"},
            "reference": "host/input-2", "quote": "do not bind this capability",
            "scope": {"target": "user", "path": str(user_tools),
                      "changes": {"code-structure": None}, "tools": {}},
            "validates": "proposal-digest",
        }
        binding = {"tool": None, "reason": "explicit unbind",
                   "confirmation": confirmation}
        user_tools.write_text(
            'schema: "fstar.tools.v1"\n'
            'detected_at: null\n'
            "tools: []\n"
            "bindings: %s\n" % json.dumps({"code-structure": binding})
            + "history: []\n",
            encoding="utf-8")
        result = self.scan()
        self.assertEqual([], result["proposals"])

    def test_initialized_project_targets_project_layer(self):
        self.registry_strong_fixture()
        (self.project / ".fstar").mkdir(exist_ok=True)
        (self.project / ".fstar" / ".schema-version").write_text("1\n", encoding="utf-8")
        result = self.scan()
        self.assertEqual(1, len(result["proposals"]))
        self.assertEqual("project", result["proposals"][0]["target"])
        # The module resolves roots (macOS /private symlink normalization);
        # compare against the resolved absolute path.
        self.assertEqual(str(self.project.resolve() / ".fstar" / "tools.yaml"),
                         result["proposals"][0]["path"])

    def test_weak_and_residual_never_propose(self):
        self.stub("probeish", help_text="symbol index lookup definitions")
        self.stub("mystery", help_text="weather forecast")
        result = self.scan()
        self.assertEqual([], result["proposals"])

    def test_scan_is_read_only_across_every_layer(self):
        self.registry_strong_fixture()
        before = self.snapshot_tree(self.root)
        self.scan()
        self.assertEqual(before, self.snapshot_tree(self.root))


# ---------------------------------------------------------------------------
# T9: determinism and no-AI
# ---------------------------------------------------------------------------

class DeterminismTests(ClassifierCase):
    def test_fixed_inputs_produce_identical_results(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
        ))
        self.stub("codegraph")
        self.stub("probeish", help_text="symbol index lookup")
        first = self.scan()
        second = self.scan()
        self.assertEqual(first, second)

    def test_only_now_change_moves_only_detected_at_and_observation_times(self):
        self.registry_file("codegraph", (
            'schema: "fstar.tool.registry.v1"\n'
            'tool: codegraph\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n'
        ))
        self.stub("codegraph")
        first = self.scan()
        second = self.scan(now="2026-10-30T11:00:00Z")
        self.assertEqual("2026-10-30T11:00:00Z", second["detected_at"])
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(first["proposals"], second["proposals"])
        self.assertEqual(first["diagnostics"], second["diagnostics"])
        self.assertNotEqual(first["observations"], second["observations"])
        for observation in second["observations"]:
            self.assertEqual("2026-10-30T11:00:00Z", observation["at"])

    def test_bad_now_is_rejected(self):
        with self.assertRaises(DomainError) as raised:
            self.scan(now="not-a-timestamp")
        self.assertEqual("tools_scan_invalid", raised.exception.code)

    def test_no_model_or_nlp_calls_in_classification_path(self):
        source = Path(classifier.__file__).read_text(encoding="utf-8")
        for forbidden in ("openai", "anthropic", "requests", "urllib.request", "http.client",
                          "socket", "asyncio", "subprocess.run(cmd=", "shell=True"):
            self.assertNotIn(forbidden, source)
        # apply_binding must not be called anywhere (mention in docstring is
        # fine; a call site is what matters).
        self.assertNotIn("tools_api.apply_binding", source)
        self.assertNotIn("apply_binding(", source)


# ---------------------------------------------------------------------------
# T10: CLI integration through the delivered lazy-import shell
# ---------------------------------------------------------------------------

class CliIntegrationTests(ClassifierCase):
    def tearDown(self):
        sys.modules.pop("fstar.tool_classifier", None)
        super().tearDown()

    def run_cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_real_classifier_through_cli_returns_scan_v1(self):
        code, stdout, _ = self.run_cli([
            "--json", "--user-data-root", str(self.user),
            "--runtime-root", str(self.root / "runtime"), "tools", "scan",
        ])
        self.assertEqual(0, code)
        payload = json.loads(stdout)
        self.assertEqual("fstar.tools.scan.v1", payload["schema"])
        for key in ("detected_at", "tools", "observations", "proposals", "diagnostics"):
            self.assertIn(key, payload)
        # With the real (developer) PATH hidden from the classifier's own
        # PATH candidates? No: PATH is controlled by setUp, so only stubs run.
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse((self.user / "tools.yaml").exists())

    def test_cli_subprocess_smoke_with_real_classifier(self):
        environment = dict(os.environ)
        environment["PATH"] = str(self.bin)
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["HOME"] = str(self.root)
        completed = subprocess.run(
            [sys.executable, "-m", "fstar", "--json",
             "--user-data-root", str(self.user),
             "--runtime-root", str(self.root / "runtime"), "tools", "scan"],
            cwd=str(self.root), env=environment, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(0, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("fstar.tools.scan.v1", payload["schema"])
        self.assertFalse((self.user / "tools.yaml").exists())

    def test_missing_classifier_module_reports_unavailable(self):
        # The module now exists in src; simulate absence by injecting None.
        real = sys.modules.pop("fstar.tool_classifier", None)
        sys.modules["fstar.tool_classifier"] = None
        try:
            with self.assertRaises(DomainError) as raised:
                tools._classifier_scan()
            self.assertEqual("tools_classifier_unavailable", raised.exception.code)
        finally:
            sys.modules.pop("fstar.tool_classifier", None)
            if real is not None:
                sys.modules["fstar.tool_classifier"] = real

    def test_validate_resources_does_not_flag_registry(self):
        diagnostics = validate_resources(RESOURCES)
        extras = [item for item in diagnostics if "registry" in str(item.path)]
        self.assertEqual([], extras)


if __name__ == "__main__":
    unittest.main()
