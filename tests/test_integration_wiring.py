"""Coordinator-owned shared wiring tests (parent design §8 handoff rows).

These prove the five consumer wirings the nine delivered children left to the
coordinator:

1. runtime-hooks: inject.resource_root delegates to the version resolver with
   real project/user context; the registration planner references the
   installed launcher with honest evidence levels.
2. tool-classifier: the package registry root follows the resolver; a valid
   pin changes the registry actually consumed.
3. workflow-content consumers: routing/role injection follows the resolved
   root, so a pin changes consumed content (AC-04 "real consumption").
4. help / entry-index: the entry index is read and then verified against the
   actual disk; an indexed entry whose file is gone is never claimed
   installed.
5. Honesty invariants: no silent bundle fallback while claiming a pin, and
   resolution creates nothing.

Every test uses temporary roots only; nothing reads the real ``~/.fstar`` or
writes real host settings. Fixture caches are hand-built with correct
baselines (the same shape installer.apply_plan writes), so the tests exercise
the real verification path rather than bypassing it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fstar import installer  # noqa: E402
from fstar.content import validate_resources  # noqa: E402
from fstar.models import DomainError  # noqa: E402
from fstar.runtime import hooks, inject, registration  # noqa: E402
from fstar import tool_classifier as classifier  # noqa: E402

BUNDLE_ROOT = REPO
BUNDLED_RESOURCES = REPO / "resources"


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class WiringCase(unittest.TestCase):
    """Temp user/project roots; no real host or user state is touched."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-wiring-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user_root = self.tmp / "user" / ".fstar"
        self.project_root = self.tmp / "project"
        self.user_root.mkdir(parents=True)
        self.project_root.mkdir(parents=True)

    # -- fixture helpers ---------------------------------------------------

    def _tree(self, root: Path) -> set:
        entries = set()
        if not root.exists():
            return entries
        for path in sorted(root.rglob("*")):
            entries.add((str(path), path.is_dir()))
        return entries

    def build_cache(self, version: str, *, routing: str, role_body: str,
                    registry_tool: str = "fixturetool") -> Path:
        """Build a complete, correctly-baselined version cache.

        The cache carries the full resource inventory (validated by
        validate_resources) with version-specific content, plus a
        manifest.json of the exact shape apply_plan writes, so resolution
        goes through the real integrity verification.
        """
        cache = self.user_root / "resources" / version
        if cache.exists():
            shutil.rmtree(cache)
        shutil.copytree(BUNDLED_RESOURCES, cache,
                        ignore=shutil.ignore_patterns("package-assets.json"))
        (cache / "runtime" / "routing.md").write_text(routing, encoding="utf-8")
        # Role cards require simple frontmatter (validate_resources); the
        # version-specific body rides under it so A/B content differs.
        (cache / "agents" / "fstar-implement.md").write_text(
            "---\nname: fstar-implement\ndescription: \"%s\"\n---\n\n%s\n"
            % (role_body, role_body), encoding="utf-8")
        registry_dir = cache / "registry"
        registry_dir.mkdir(exist_ok=True)
        (registry_dir / ("%s.yaml" % registry_tool)).write_text(
            'schema: "fstar.tool.registry.v1"\n'
            'tool: %s\n'
            'kind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "cache registry %s"}]\n'
            % (registry_tool, version), encoding="utf-8")
        for stale in registry_dir.glob("*.yaml"):
            if stale.name != "%s.yaml" % registry_tool:
                stale.unlink()
        files = []
        for path in sorted(cache.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                files.append({"source": str(path.relative_to(cache)),
                              "sha256": _sha(path), "installed": True})
        payload = {"schema": installer.BUNDLE_SCHEMA, "resource_version": version,
                   "files": files, "supported_data_schemas": [1]}
        (cache / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
        return cache

    def pin_user_version(self, version: str) -> None:
        (self.user_root / "version").write_text("%s\n" % version, encoding="utf-8")

    def pin_project_version(self, version: str) -> None:
        config = self.project_root / ".fstar" / "config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('schema_version: 1\nresources:\n  version: "%s"\n' % version,
                          encoding="utf-8")


# ---------------------------------------------------------------------------
# Row 1: runtime-hooks — resource_root delegates to the resolver
# ---------------------------------------------------------------------------

class ResourceRootResolutionTests(WiringCase):
    def test_no_user_root_is_exactly_the_bundled_copy(self):
        # (a) unchanged behavior for fresh projects: no user root, no pin.
        self.assertEqual(inject.resource_root(), BUNDLED_RESOURCES)
        self.assertEqual(inject.resource_root(None, None), BUNDLED_RESOURCES)
        # Read creates nothing anywhere.
        before_user = self._tree(self.user_root)
        inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(self._tree(self.user_root), before_user)

    def test_user_version_pin_selects_the_cache(self):
        # (b) a pinned user version is actually consumed.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        root = inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(root, cache)
        self.assertEqual((root / "runtime" / "routing.md").read_text(), "routing A")

    def test_project_pin_wins_over_user_version(self):
        self.build_cache("A", routing="routing A", role_body="role A")
        self.build_cache("B", routing="routing B", role_body="role B")
        self.pin_user_version("B")
        self.pin_project_version("A")
        root = inject.resource_root(self.project_root, self.user_root)
        self.assertEqual((root / "runtime" / "routing.md").read_text(), "routing A")

    def test_broken_pin_raises_instead_of_serving_the_bundle(self):
        # (c) invalid pinned root -> honest error, no silent bundle fallback
        # while claiming the pin.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        (cache / "runtime" / "routing.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(caught.exception.code, "resource_integrity")

    def test_missing_pinned_version_raises_not_latest(self):
        self.pin_user_version("not-installed")
        with self.assertRaises(DomainError) as caught:
            inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(caught.exception.code, "resource_version_unavailable")

    def test_routing_and_role_inputs_follow_the_resolved_root(self):
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        routing = inject.routing_input(cache)
        card = inject.role_card("implement", cache)
        self.assertEqual(routing.text, "routing A")
        # The role card keeps its frontmatter; the version-specific body is
        # what must differ between the pin and the bundle.
        self.assertIn("role A", card.text)
        self.assertNotIn("role A", inject.role_card("implement").text)
        # Default (no root) still reads the bundled copy.
        self.assertEqual(inject.routing_input().text,
                         (BUNDLED_RESOURCES / "runtime" / "routing.md").read_text())


class HookInjectionTests(WiringCase):
    """session-context / worker-context consume the resolved root."""

    def _session_text(self) -> str:
        return hooks.session_context({"session_id": "s1"}, start=self.project_root,
                                     user_root=self.user_root)["text"]

    def test_no_pin_injects_bundled_routing(self):
        # (a) fresh project: unchanged behavior.
        text = self._session_text()
        self.assertIn((BUNDLED_RESOURCES / "runtime" / "routing.md").read_text().splitlines()[0],
                      text)

    def test_pin_changes_injected_routing_content(self):
        # (b) the pin really changes consumed content, not just version output.
        self.build_cache("A", routing="ROUTING-FROM-PIN-A", role_body="role A")
        self.pin_user_version("A")
        self.assertIn("ROUTING-FROM-PIN-A", self._session_text())

    def test_broken_pin_fails_the_hook_honestly(self):
        # (c) no silent bundle injection while a pin is claimed.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        (cache / "runtime" / "routing.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            self._session_text()
        self.assertEqual(caught.exception.code, "resource_integrity")

    def test_worker_context_role_card_follows_the_pin(self):
        self.build_cache("A", routing="routing A", role_body="ROLE-CARD-FROM-PIN-A")
        self.pin_user_version("A")
        result = hooks.worker_context({}, role="implement", start=self.project_root,
                                      user_root=self.user_root)
        self.assertIn("ROLE-CARD-FROM-PIN-A", result["text"])


class RegistrationPlannerTests(WiringCase):
    def test_plan_references_the_installed_launcher(self):
        result = registration.plan("claude")
        for entry in result["entries"]:
            command = entry["hooks"][0]["command"]
            launcher = Path(command.split(" ")[0].strip("'"))
            self.assertEqual(launcher.name, "fstar-hook.cjs")
            # Only claims an installed launcher that actually exists.
            self.assertTrue(launcher.is_file(), command)
            self.assertTrue(entry["hooks"][0]["launcher_installed"])
            # Honest evidence level: schema observation, not live delivery.
            self.assertEqual(entry["hooks"][0]["evidence"], "observed-schema")

    def test_plan_command_matches_what_install_registers(self):
        # The planner and the installer must not diverge: same launcher, same
        # semantic argument, same quoting rules.
        result = registration.plan("claude")
        planned = {entry["semantic"]: entry["hooks"][0]["command"] for entry in result["entries"]}
        for semantic in installer.HOOK_SEMANTICS:
            self.assertEqual(planned[semantic], installer._hook_command(semantic))

    def test_uninstall_note_is_not_a_substring_heuristic(self):
        for host in ("claude", "codex"):
            result = registration.plan(host)
            self.assertIn("manifest", result["uninstall"])
            self.assertNotIn("contains 'fstar.runtime'", result["uninstall"])

    def test_semantics_are_declared_explicitly(self):
        for host in ("claude", "codex"):
            for entry in registration.plan(host)["entries"]:
                self.assertIn(entry["semantic"], installer.HOOK_SEMANTICS)
                # The installer resolves semantics from the explicit key.
                self.assertEqual(installer._semantic_for_shape(entry), entry["semantic"])


# ---------------------------------------------------------------------------
# Row 2: tool-classifier — registry root follows the resolver
# ---------------------------------------------------------------------------

class ClassifierRegistryRootTests(WiringCase):
    def _registry_tools(self, **kwargs) -> dict:
        entries, diagnostics = classifier.load_registry(
            project_root=self.project_root, user_root=self.user_root, **kwargs)
        self.assertEqual([], diagnostics)
        return entries

    def test_no_pin_loads_the_bundled_registry(self):
        # (a) unchanged behavior: the bundled registry is consumed.
        entries = self._registry_tools()
        self.assertEqual({"codegraph", "gh", "qmd", "psql", "sqlite3", "pytest"}, set(entries))

    def test_pin_changes_the_registry_consumed(self):
        # (b) a pinned version's registry is actually consumed (A/B differ).
        self.build_cache("A", routing="routing A", role_body="role A", registry_tool="toolA")
        self.build_cache("B", routing="routing B", role_body="role B", registry_tool="toolB")
        self.pin_user_version("A")
        self.assertEqual(set(self._registry_tools()), {"toolA"})
        self.pin_user_version("B")
        self.assertEqual(set(self._registry_tools()), {"toolB"})

    def test_broken_pin_fails_the_scan_honestly(self):
        # (c) no silent fallback to the bundled registry while claiming a pin.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        (cache / "registry" / "fixturetool.yaml").write_text("tampered", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            self._registry_tools()
        self.assertEqual(caught.exception.code, "resource_integrity")

    def test_explicit_package_root_still_overrides_for_fixtures(self):
        # The existing fixture parameter keeps working (tests rely on it).
        fixture = self.tmp / "fixture-registry"
        fixture.mkdir()
        (fixture / "only.yaml").write_text(
            'schema: "fstar.tool.registry.v1"\n'
            'tool: only\nkind: cli\n'
            'capabilities: [{"id": "code-structure", "match": "strong", "basis": "x"}]\n',
            encoding="utf-8")
        entries = self._registry_tools(package_root=fixture)
        self.assertEqual(set(entries), {"only"})


# ---------------------------------------------------------------------------
# Row 3: content authority — the selected root must validate
# ---------------------------------------------------------------------------

class ContentAuthorityTests(WiringCase):
    def test_pinned_cache_passes_validate_resources(self):
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.assertEqual((), validate_resources(cache))

    def test_invalid_selected_root_is_an_honest_error(self):
        # A pinned root that fails content validation is never silently
        # swapped for the bundle: the resolver's integrity check fires first,
        # and even a hash-consistent but structurally broken root surfaces
        # through validate_resources when inspected.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        target = cache / "skills" / "fstar-help" / "SKILL.md"
        target.write_text("tampered", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(caught.exception.code, "resource_integrity")
        # doctor (strict=False) reports instead of raising, and validates
        # whatever root is selected.
        report = installer.doctor(roots=installer.Roots(
            user_root=self.user_root, runtime_root=self.user_root / "runtime",
            project_root=self.project_root, bundle_root=BUNDLE_ROOT))
        self.assertFalse(report["healthy"])
        self.assertTrue(any(problem["code"] == "resource_integrity"
                            for problem in report["diagnostics"]))


# ---------------------------------------------------------------------------
# Row 4: help / entry-index — read the index, then check the real files
# ---------------------------------------------------------------------------

class EntryIndexTests(WiringCase):
    def _write_index(self, entries: list) -> None:
        (self.user_root / "entry-index.json").write_text(
            json.dumps({"schema": installer.ENTRY_INDEX_SCHEMA, "entries": entries}),
            encoding="utf-8")

    def test_help_directs_doctor_disk_verified_entries(self):
        help_text = (BUNDLE_ROOT / "resources" / "skills" / "fstar-help" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("fstar --json doctor", help_text)
        self.assertIn("`entries` report", help_text)
        self.assertIn("absent index", help_text)

    def test_no_index_is_an_explicit_empty_report(self):
        # (a) unchanged behavior when no index exists.
        report = installer.entry_index_report(self.user_root)
        self.assertFalse(report["index_present"])
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["active"], [])
        self.assertEqual(report["missing"], [])
        self.assertIs(installer.entry_index_report(None)["index_present"], False)

    def test_only_entries_that_exist_on_disk_are_claimed_active(self):
        # (b) the report claims exactly the entries whose files exist.
        real = self.tmp / "host" / "settings.json"
        real.parent.mkdir(parents=True)
        real.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "fixture-hook"}]}]}}), encoding="utf-8")
        self._write_index([
            {"id": "claude:SessionStart", "host": "claude", "kind": "hook",
             "semantic": "session-context", "event": "SessionStart", "invocation": "fixture-hook",
             "installed_path": str(real), "ownership": "owned", "status": "active"},
            {"id": "claude:PreToolUse", "host": "claude", "kind": "hook",
             "semantic": "worker-context", "event": "PreToolUse",
             "installed_path": str(self.tmp / "host" / "gone.json"),
             "ownership": "owned", "status": "active"},
        ])
        report = installer.entry_index_report(self.user_root)
        self.assertEqual(report["active"], ["claude:SessionStart"])
        self.assertEqual(report["missing"], ["claude:PreToolUse"])
        missing = next(item for item in report["entries"] if item["id"] == "claude:PreToolUse")
        self.assertEqual(missing["status"], "missing")

    def test_doctor_reports_indexed_but_uninstalled_entries(self):
        # (c) an entry-index that claims uninstalled entries is a defect the
        # doctor surfaces; it is never presented as installed.
        self._write_index([
            {"id": "claude:SessionStart", "host": "claude", "kind": "hook",
             "semantic": "session-context", "event": "SessionStart",
             "installed_path": str(self.tmp / "host" / "gone.json"),
             "ownership": "owned", "status": "active"},
        ])
        report = installer.doctor(roots=installer.Roots(
            user_root=self.user_root, runtime_root=self.user_root / "runtime",
            project_root=self.project_root, bundle_root=BUNDLE_ROOT))
        self.assertFalse(report["healthy"])
        self.assertEqual(report["entries"]["missing"], ["claude:SessionStart"])
        self.assertTrue(any(diagnostic["code"] == "entry_index_stale"
                            for diagnostic in report["diagnostics"]))

    def test_report_is_read_only(self):
        self._write_index([
            {"id": "claude:SessionStart", "host": "claude", "kind": "hook",
             "semantic": "session-context", "event": "SessionStart",
             "installed_path": str(self.tmp / "host" / "gone.json"),
             "ownership": "owned", "status": "active"},
        ])
        before = self._tree(self.user_root)
        installer.entry_index_report(self.user_root)
        self.assertEqual(self._tree(self.user_root), before)

    def test_real_install_index_verifies_active(self):
        # End-to-end with the real installer: after install, every indexed
        # entry is backed by a real settings file.
        host_root = self.tmp / "host" / "claude"
        host_root.mkdir(parents=True)
        roots = installer.Roots(user_root=self.user_root, runtime_root=self.user_root / "runtime",
                                project_root=self.project_root,
                                host_roots={"claude": host_root}, bundle_root=BUNDLE_ROOT)
        plan = installer.plan_install(operation="install", roots=roots, hosts=["claude"])
        installer.apply_plan(plan, roots=roots)
        report = installer.entry_index_report(self.user_root)
        # 4 hook registrations plus 16 adapted host files (12 skills, 4 agents).
        self.assertEqual(len(report["active"]), 20)
        self.assertEqual(report["missing"], [])
        settings = host_root / "settings.json"
        original = settings.read_text(encoding="utf-8")
        for change in ("matcher", "timeout"):
            document = json.loads(original)
            group = document["hooks"]["SessionStart"][0]
            if change == "matcher":
                group["matcher"] = ["wrong"]
            else:
                group["hooks"][0]["timeout"] = 999
            settings.write_text(json.dumps(document), encoding="utf-8")
            self.assertIn("claude:SessionStart", installer.entry_index_report(self.user_root)["missing"])
        document = json.loads(original)
        del document["hooks"]["SessionStart"]
        settings.write_text(json.dumps(document), encoding="utf-8")
        report = installer.entry_index_report(self.user_root)
        self.assertIn("claude:SessionStart", report["missing"])
        self.assertEqual(len(report["active"]), 19)
        self.assertFalse(installer.doctor(roots=roots)["healthy"])
        settings.write_text(original, encoding="utf-8")
        # Uninstall removes the settings file: the index must stop claiming
        # the entries (the real uninstall also updates the index, so both the
        # index and the report stay honest).
        plan = installer.plan_install(operation="uninstall", roots=roots, hosts=["claude"])
        installer.apply_plan(plan, roots=roots)
        report = installer.entry_index_report(self.user_root)
        self.assertEqual(report["active"], [])
        self.assertEqual(report["missing"], [])


# ---------------------------------------------------------------------------
# Row 5: honesty invariants across the wiring
# ---------------------------------------------------------------------------

class HonestyInvariantTests(WiringCase):
    def test_resolution_never_creates_files(self):
        self.pin_user_version("A")
        before_user = self._tree(self.user_root)
        before_project = self._tree(self.project_root)
        with self.assertRaises(DomainError):
            inject.resource_root(self.project_root, self.user_root)
        self.assertEqual(self._tree(self.user_root), before_user)
        self.assertEqual(self._tree(self.project_root), before_project)

    def test_no_silent_bundle_fallback_anywhere(self):
        # Every consumer fails on a broken pin rather than serving the bundle.
        cache = self.build_cache("A", routing="routing A", role_body="role A")
        self.pin_user_version("A")
        (cache / "runtime" / "routing.md").write_text("tampered", encoding="utf-8")
        for call in (
            lambda: inject.resource_root(self.project_root, self.user_root),
            lambda: classifier.load_registry(project_root=self.project_root,
                                             user_root=self.user_root),
            lambda: hooks.session_context({"session_id": "s"}, start=self.project_root,
                                          user_root=self.user_root),
        ):
            with self.assertRaises(DomainError) as caught:
                call()
            self.assertEqual(caught.exception.code, "resource_integrity")


if __name__ == "__main__":
    unittest.main()
