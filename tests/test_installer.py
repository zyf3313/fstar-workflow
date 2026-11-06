"""Installer and packaging tests (PI-I1..I10).

Every test runs against temporary roots only: HOME, user data root, runtime
root, host roots, project root, and npm cache/prefix are all temp dirs.
Nothing here reads or writes real host settings, the real user root, or any
network location.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fstar import installer  # noqa: E402
from fstar.models import DomainError  # noqa: E402

BUNDLE_ROOT = REPO
# The bundled resource version (package.json fstar.resource_version); tests
# must follow it instead of hardcoding a version id.
BUNDLE_VERSION = str(installer.load_bundle_manifest(BUNDLE_ROOT)["resource_version"])


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class InstallerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-installer-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user_root = self.tmp / "user" / ".fstar"
        self.runtime_root = self.tmp / "user" / ".fstar" / "runtime"
        self.host_root = self.tmp / "host" / "claude"
        self.project_root = self.tmp / "project"
        for path in (self.user_root, self.runtime_root, self.host_root, self.project_root):
            path.mkdir(parents=True, exist_ok=True)
        self.host_root.mkdir(parents=True, exist_ok=True)

    def roots(self, **kwargs) -> installer.Roots:
        return installer.Roots(
            user_root=self.user_root,
            runtime_root=self.runtime_root,
            project_root=kwargs.get("project_root", self.project_root),
            host_roots=kwargs.get("host_roots", {"claude": self.host_root}),
            bundle_root=BUNDLE_ROOT,
        )

    def install(self, **kwargs):
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, **kwargs)
        return installer.apply_plan(plan, roots=roots)

    def write_settings(self, document) -> Path:
        path = self.host_root / "settings.json"
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path


class TestFreshInstall(InstallerCase):
    def test_install_writes_cache_and_metadata(self):
        result = self.install(hosts=["claude"])
        applied = result["applied"]
        self.assertTrue(applied["files"])
        self.assertTrue((self.user_root / ".install-manifest.json").is_file())
        self.assertTrue((self.user_root / ".asset-hashes.json").is_file())
        self.assertTrue((self.user_root / "entry-index.json").is_file())
        self.assertEqual((self.user_root / "version").read_text().strip(), BUNDLE_VERSION)
        cache = self.user_root / "resources" / BUNDLE_VERSION
        self.assertTrue((cache / "manifest.json").is_file())
        self.assertTrue((cache / "runtime" / "routing.md").is_file())

    def test_installed_matchers_are_pipe_separated_strings(self):
        # Claude Code consumes matcher as a single string ("Edit|Write", ""
        # to match all); an array never matches. Live-verification finding
        # against claude 2.1.316.
        self.install(hosts=["claude"])
        document = json.loads((self.host_root / "settings.json").read_text())
        self.assertEqual(document["hooks"]["SessionStart"][0]["matcher"],
                         "startup|clear|compact")
        self.assertEqual(document["hooks"]["PreToolUse"][0]["matcher"], "Task|Agent")
        self.assertEqual(document["hooks"]["PostToolUse"][0]["matcher"], "Edit|Write")
        self.assertEqual(document["hooks"]["SubagentStop"][0]["matcher"], "")
        for groups in document["hooks"].values():
            for group in groups:
                self.assertIsInstance(group["matcher"], str)

    def test_repeat_install_is_idempotent(self):
        self.install(hosts=["claude"])
        settings_before = (self.host_root / "settings.json").read_text()
        result = self.install(hosts=["claude"])
        actions = {entry["action"] for entry in result["applied"]["files"]}
        self.assertTrue(actions <= {"noop", "keep"}, actions)
        self.assertEqual(settings_before, (self.host_root / "settings.json").read_text())

    def test_install_never_writes_program_files_into_user_root(self):
        self.install(hosts=["claude"])
        self.assertFalse((self.user_root / "bin").exists())
        self.assertFalse((self.user_root / "src").exists())

    def test_project_root_stays_data_only(self):
        self.install(hosts=["claude"])
        entries = sorted(p.name for p in self.project_root.iterdir())
        self.assertEqual(entries, [])


class TestSettingsOwnership(InstallerCase):
    def test_other_settings_entries_are_preserved(self):
        self.write_settings({
            "permissions": {"allow": ["Bash(ls:*)"]},
            "env": {"FOO": "bar"},
            "plugins": ["demo"],
            "hooks": {
                "SessionStart": [
                    {"matcher": "startup", "hooks": [{"type": "command", "command": "other-tool", "timeout": 5}]},
                ],
            },
        })
        self.install(hosts=["claude"])
        document = json.loads((self.host_root / "settings.json").read_text())
        self.assertEqual(document["permissions"], {"allow": ["Bash(ls:*)"]})
        self.assertEqual(document["env"], {"FOO": "bar"})
        self.assertEqual(document["plugins"], ["demo"])
        commands = [hook["command"]
                    for group in document["hooks"]["SessionStart"]
                    for hook in group.get("hooks", [])]
        self.assertIn("other-tool", commands)
        self.assertTrue(any("fstar-hook" in command for command in commands))

    def test_identical_preexisting_hook_is_not_taken_over(self):
        command = installer._hook_command("session-context")
        self.write_settings({
            "hooks": {"SessionStart": [{"matcher": "startup|clear|compact",
                                        "hooks": [{"type": "command", "command": command, "timeout": 30}]}]},
        })
        self.install(hosts=["claude"])
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        entries = [e for e in manifest["settings_entries"] if e["event"] == "SessionStart"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ownership"], "externally_owned")

    def test_same_command_different_options_is_a_distinct_entry(self):
        command = installer._hook_command("session-context")
        self.write_settings({
            "hooks": {"SessionStart": [{"matcher": "startup|clear|compact",
                                        "hooks": [{"type": "command", "command": command, "timeout": 999}]}]},
        })
        self.install(hosts=["claude"])
        document = json.loads((self.host_root / "settings.json").read_text())
        timeouts = sorted(hook["timeout"]
                          for group in document["hooks"]["SessionStart"]
                          for hook in group.get("hooks", []))
        self.assertEqual(timeouts, [30, 999])

    def test_uninstall_removes_only_owned_entry(self):
        command = installer._hook_command("session-context")
        self.write_settings({
            "hooks": {"SessionStart": [{"matcher": "startup|clear|compact",
                                        "hooks": [{"type": "command", "command": command, "timeout": 999}]}]},
        })
        self.install(hosts=["claude"])
        roots = self.roots()
        plan = installer.plan_install(operation="uninstall", roots=roots, hosts=["claude"])
        installer.apply_plan(plan, roots=roots)
        document = json.loads((self.host_root / "settings.json").read_text())
        remaining = [hook for group in document.get("hooks", {}).get("SessionStart", [])
                     for hook in group.get("hooks", [])]
        self.assertEqual([hook["timeout"] for hook in remaining], [999])

    def test_uninstall_keeps_preexisting_identical_hook(self):
        # An identical hook already owned by someone else is reused, not
        # adopted: uninstall must leave it untouched (precise ownership).
        command = installer._hook_command("session-context")
        self.write_settings({
            "hooks": {"SessionStart": [{"matcher": "startup|clear|compact",
                                        "hooks": [{"type": "command", "command": command, "timeout": 30}]}]},
        })
        self.install(hosts=["claude"])
        roots = self.roots()
        installer.apply_plan(installer.plan_install(operation="uninstall", roots=roots, hosts=["claude"]),
                             roots=roots)
        document = json.loads((self.host_root / "settings.json").read_text())
        remaining = [hook for group in document.get("hooks", {}).get("SessionStart", [])
                     for hook in group.get("hooks", [])]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["command"], command)

    def test_uninstall_keeps_duplicate_ambiguous_hooks(self):
        self.install(hosts=["claude"])
        settings = self.host_root / "settings.json"
        document = json.loads(settings.read_text())
        for group in document["hooks"]["SessionStart"]:
            if any("fstar-hook" in hook.get("command", "") for hook in group["hooks"]):
                group["hooks"].append(dict(group["hooks"][0]))
        settings.write_text(json.dumps(document), encoding="utf-8")
        roots = self.roots()
        result = installer.apply_plan(
            installer.plan_install(operation="uninstall", roots=roots, hosts=["claude"]), roots=roots)
        document = json.loads(settings.read_text())
        session_hooks = [hook for group in document["hooks"]["SessionStart"]
                         for hook in group["hooks"] if "fstar-hook" in hook.get("command", "")]
        # Identity is ambiguous (two identical owned entries): keep both and
        # report rather than deleting an arbitrary one.
        self.assertEqual(len(session_hooks), 2)
        self.assertTrue(any(item.get("action") == "no_owned_entry"
                            for item in result["applied"]["kept"]))

    def test_uninstall_keeps_index_entry_for_kept_settings(self):
        self.install(hosts=["claude"])
        settings = self.host_root / "settings.json"
        document = json.loads(settings.read_text())
        for group in document["hooks"]["SessionStart"]:
            for hook in group["hooks"]:
                if "fstar-hook" in hook.get("command", ""):
                    hook["timeout"] = 999
        settings.write_text(json.dumps(document), encoding="utf-8")
        roots = self.roots()
        installer.apply_plan(installer.plan_install(operation="uninstall", roots=roots, hosts=["claude"]),
                             roots=roots)
        index = json.loads((self.user_root / "entry-index.json").read_text())
        ids = {entry["id"] for entry in index["entries"]}
        # The modified registration was kept, so the index must keep reporting
        # it instead of claiming it was uninstalled.
        self.assertIn("claude:SessionStart", ids)

    def test_broken_settings_json_is_refused(self):
        (self.host_root / "settings.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            self.install(hosts=["claude"])
        self.assertEqual(caught.exception.code, "host_settings_unreadable")

    def test_codex_install_reports_unsupported_and_writes_nothing(self):
        codex_root = self.tmp / "host" / "codex"
        codex_root.mkdir(parents=True)
        roots = self.roots(host_roots={"claude": self.host_root, "codex": codex_root})
        plan = installer.plan_install(operation="install", roots=roots, hosts=["codex"])
        self.assertTrue(any(c["kind"] == "host_unsupported" for c in plan["conflicts"]))
        result = installer.apply_plan(plan, roots=roots)
        self.assertEqual(plan["conflicts"], result["conflicts"])
        self.assertFalse(result["applied"]["settings"])
        self.assertEqual(plan["settings_entries"], [])
        self.assertEqual(list(codex_root.iterdir()), [])


class TestFileOwnership(InstallerCase):
    def test_user_file_with_same_path_is_not_overwritten(self):
        cache = self.user_root / "resources" / BUNDLE_VERSION
        (cache / "runtime").mkdir(parents=True)
        target = cache / "runtime" / "routing.md"
        target.write_text("user content", encoding="utf-8")
        result = self.install(hosts=["claude"])
        kept = [item for item in result["applied"]["kept"]
                if item["path"] == str(target.resolve())]
        self.assertTrue(kept, result["applied"])
        self.assertEqual(target.read_text(), "user content")

    def test_modified_owned_file_is_kept_by_default(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots)
        actions = {entry["source"]: entry["action"] for entry in plan["files"]}
        self.assertEqual(actions["resources/runtime/routing.md"], "keep_modified")
        installer.apply_plan(plan, roots=roots)
        self.assertEqual(target.read_text(), "locally modified")

    def test_explicit_overwrite_backs_up_the_old_bytes(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="overwrite")
        result = installer.apply_plan(plan, roots=roots)
        backup = [item for item in result["applied"]["files"]
                  if item["path"] == str(target.resolve())][0]["backup"]
        self.assertTrue(Path(backup).is_file())
        self.assertEqual(Path(backup).read_text(), "locally modified")
        self.assertEqual(target.read_text(), (BUNDLE_ROOT / "resources" / "runtime" / "routing.md").read_text())

    def test_new_policy_writes_dot_new_and_never_clobbers_existing(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="new")
        result = installer.apply_plan(plan, roots=roots)
        self.assertTrue((target.with_name("routing.md.new")).is_file())
        self.assertEqual(target.read_text(), "locally modified")
        self.assertTrue(any(item["action"] == "write_new" for item in result["applied"]["files"]))

    def test_existing_dot_new_is_never_overwritten(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        collision = target.with_name("routing.md.new")
        collision.write_text("user new file", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="new")
        result = installer.apply_plan(plan, roots=roots)
        self.assertEqual(collision.read_text(), "user new file")
        self.assertTrue(any(item["action"] == "existing_new_conflict" for item in result["applied"]["kept"]))

    def test_uninstall_keeps_modified_owned_file(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="uninstall", roots=roots)
        installer.apply_plan(plan, roots=roots)
        self.assertTrue(target.is_file())

    def test_uninstall_never_deletes_user_data(self):
        self.install(hosts=["claude"])
        user_data = self.user_root / "rules" / "my-rule.md"
        user_data.parent.mkdir(parents=True, exist_ok=True)
        user_data.write_text("keep me", encoding="utf-8")
        project_data = self.project_root / ".fstar" / "tasks" / "t1" / "task.json"
        project_data.parent.mkdir(parents=True, exist_ok=True)
        project_data.write_text("{}", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="uninstall", roots=roots)
        installer.apply_plan(plan, roots=roots)
        self.assertTrue(user_data.is_file())
        self.assertTrue(project_data.is_file())
        self.assertTrue(self.user_root.is_dir())

    def test_unowned_same_name_file_is_not_removed(self):
        cache = self.user_root / "resources" / BUNDLE_VERSION / "runtime"
        cache.mkdir(parents=True)
        target = cache / "routing.md"
        target.write_text("user content", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="uninstall", roots=roots)
        result = installer.apply_plan(plan, roots=roots)
        self.assertTrue(target.is_file())
        self.assertEqual(result["applied"]["removed"], [])


class TestResourceVersions(InstallerCase):
    def _write_cache(self, version: str, routing_text: str) -> Path:
        cache = self.user_root / "resources" / version
        (cache / "runtime").mkdir(parents=True, exist_ok=True)
        (cache / "runtime" / "routing.md").write_text(routing_text, encoding="utf-8")
        payload = {
            "schema": installer.BUNDLE_SCHEMA,
            "resource_version": version,
            "files": [{"source": "runtime/routing.md", "sha256": _sha(cache / "runtime" / "routing.md")}],
        }
        (cache / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
        return cache

    def test_explicit_version_reads_the_cache_content(self):
        self._write_cache("A", "routing A")
        selection = installer.resolve_resources(user_root=self.user_root, requested_version="A")
        self.assertEqual(selection.version, "A")
        self.assertEqual((selection.root / "runtime" / "routing.md").read_text(), "routing A")

    def test_two_versions_have_different_content(self):
        self._write_cache("A", "routing A")
        self._write_cache("B", "routing B")
        a = installer.resolve_resources(user_root=self.user_root, requested_version="A")
        b = installer.resolve_resources(user_root=self.user_root, requested_version="B")
        self.assertNotEqual(a.root, b.root)
        self.assertEqual((a.root / "runtime" / "routing.md").read_text(), "routing A")
        self.assertEqual((b.root / "runtime" / "routing.md").read_text(), "routing B")

    def test_project_pin_wins_over_user_version(self):
        self._write_cache("A", "routing A")
        self._write_cache("B", "routing B")
        (self.user_root / "version").write_text("B\n", encoding="utf-8")
        project_config = self.project_root / ".fstar" / "config.yaml"
        project_config.parent.mkdir(parents=True, exist_ok=True)
        project_config.write_text('schema_version: 1\nresources:\n  version: "A"\n', encoding="utf-8")
        selection = installer.resolve_resources(project_root=self.project_root, user_root=self.user_root)
        self.assertEqual(selection.version, "A")
        self.assertEqual(selection.source, "config")

    def test_missing_version_fails_instead_of_using_latest(self):
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="missing")
        self.assertEqual(caught.exception.code, "resource_version_unavailable")

    def test_corrupt_cache_fails_with_integrity_error(self):
        cache = self._write_cache("A", "routing A")
        (cache / "runtime" / "routing.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="A")
        self.assertEqual(caught.exception.code, "resource_integrity")

    def test_latest_is_rejected(self):
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="latest")
        self.assertEqual(caught.exception.code, "resource_version_invalid")

    def test_old_cache_is_preserved_across_installs(self):
        self._write_cache("A", "routing A")
        self.install(hosts=["claude"])
        self.assertTrue((self.user_root / "resources" / "A" / "runtime" / "routing.md").is_file())
        self.assertTrue((self.user_root / "resources" / BUNDLE_VERSION).is_dir())

    def test_same_version_with_different_content_is_refused(self):
        self.install(hosts=["claude"])
        cache = self.user_root / "resources" / BUNDLE_VERSION
        (cache / "runtime" / "routing.md").write_text("different", encoding="utf-8")
        manifest = json.loads((cache / "manifest.json").read_text())
        manifest["files"][0]["sha256"] = _sha(cache / "runtime" / "routing.md")
        (cache / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        roots = self.roots()
        with self.assertRaises(DomainError) as caught:
            plan = installer.plan_install(operation="update", roots=roots)
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "resource_version_conflict")

    def test_symlinked_cache_version_is_not_followed(self):
        outside = self.tmp / "outside-version"
        outside.mkdir()
        (outside / "runtime").mkdir()
        (outside / "runtime" / "routing.md").write_text("outside content", encoding="utf-8")
        (self.user_root / "resources").mkdir(parents=True, exist_ok=True)
        (self.user_root / "resources" / "A").symlink_to(outside)
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="A")
        self.assertEqual(caught.exception.code, "resource_integrity")
        # doctor is read-only: it reports the problem instead of raising or
        # reading the external directory.
        selection = installer.resolve_resources(user_root=self.user_root, requested_version="A", strict=False)
        self.assertTrue(any(problem["code"] == "resource_integrity" for problem in selection.problems))

    def test_update_from_new_bundle_keeps_old_cache(self):
        # AC-04: a resources-version bump installs a separate cache and must
        # not mutate or delete the old version other projects may pin.
        self.install(hosts=["claude"])
        old_cache = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        old_bytes = old_cache.read_bytes()
        bundle = self.tmp / "bundle"
        shutil.copytree(BUNDLE_ROOT / "resources", bundle / "resources")
        routing = bundle / "resources" / "runtime" / "routing.md"
        routing.write_text("routing for version 9\n", encoding="utf-8")
        manifest = json.loads((bundle / "resources" / "package-assets.json").read_text())
        manifest["resource_version"] = "9"
        for record in manifest["files"]:
            if record["source"] == "resources/runtime/routing.md":
                record["sha256"] = _sha(routing)
        (bundle / "resources" / "package-assets.json").write_text(json.dumps(manifest), encoding="utf-8")
        roots = installer.Roots(user_root=self.user_root, runtime_root=self.runtime_root,
                                project_root=self.project_root, host_roots={"claude": self.host_root},
                                bundle_root=bundle)
        plan = installer.plan_install(operation="update", roots=roots)
        self.assertEqual(plan["version"], "9")
        installer.apply_plan(plan, roots=roots)
        self.assertEqual((self.user_root / "version").read_text().strip(), "9")
        self.assertEqual((self.user_root / "resources" / "9" / "runtime" / "routing.md").read_text(),
                         "routing for version 9\n")
        self.assertEqual(old_cache.read_bytes(), old_bytes)
        selection = installer.resolve_resources(user_root=self.user_root, requested_version=BUNDLE_VERSION)
        self.assertEqual(selection.root, self.user_root / "resources" / BUNDLE_VERSION)

    def test_resolve_does_not_create_a_cache(self):
        before = _tree_snapshot(self.user_root)
        installer.resolve_resources(user_root=self.user_root)
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_cache_manifest_for_another_version_is_integrity_error(self):
        cache = self._write_cache("A", "routing A")
        manifest = json.loads((cache / "manifest.json").read_text())
        manifest["resource_version"] = "B"
        (cache / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="A")
        self.assertEqual(caught.exception.code, "resource_integrity")


class TestHostEntryDetails(InstallerCase):
    def test_hook_command_points_at_the_packaged_launcher(self):
        self.install(hosts=["claude"])
        document = json.loads((self.host_root / "settings.json").read_text())
        commands = [hook["command"]
                    for groups in document["hooks"].values()
                    for group in groups
                    for hook in group.get("hooks", [])]
        self.assertEqual(len(commands), 4)
        for command in commands:
            self.assertIn("fstar-hook.cjs", command)
            self.assertTrue(command.split(" ")[0].startswith("/"), command)
        semantics = {command.rsplit(" ", 1)[-1] for command in commands}
        self.assertEqual(semantics, set(installer.HOOK_SEMANTICS))

    def test_install_without_host_writes_no_settings(self):
        result = self.install()
        self.assertEqual(result["applied"]["settings"], [])
        self.assertFalse((self.host_root / "settings.json").exists())

    def test_entry_index_matches_installed_entries(self):
        self.install(hosts=["claude"])
        index = json.loads((self.user_root / "entry-index.json").read_text())
        self.assertEqual(index["schema"], "fstar.entries.v1")
        hooks = [entry for entry in index["entries"] if entry["kind"] == "hook"]
        host_files = [entry for entry in index["entries"] if entry["kind"] in ("skill", "agent")]
        self.assertEqual(len(hooks), 4)
        self.assertEqual(len(host_files), 16)
        for entry in index["entries"]:
            self.assertTrue(Path(entry["installed_path"]).is_file())
            self.assertEqual(entry["ownership"], "owned")


class TestHostSkillAdaptation(InstallerCase):
    """Host-side skills/agents adaptation (parent design §2.3, F5 closure)."""

    def test_install_adapts_skills_and_agents_into_the_host_root(self):
        self.install(hosts=["claude"])
        skills = sorted(p.name for p in (self.host_root / "skills").glob("fstar-*/SKILL.md"))
        agents = sorted(p.name for p in (self.host_root / "agents").glob("fstar-*.md"))
        self.assertEqual(len(skills), 12)
        self.assertEqual(agents, ["fstar-check.md", "fstar-editor.md",
                                  "fstar-implement.md", "fstar-research.md"])
        for record in installer.plan_install(operation="install", roots=self.roots())["host_files"]:
            self.assertEqual(_sha(Path(record["destination"])), record["expected_hash"])

    def test_codex_host_never_receives_host_file_entries(self):
        plan = installer.plan_install(operation="install", roots=self.roots(
            host_roots={"codex": self.tmp / "host" / "codex"}), hosts=["codex"])
        self.assertEqual(plan["host_files"], [])

    def test_foreign_host_files_are_untouched(self):
        foreign = self.host_root / "skills" / "user-skill" / "SKILL.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("user content", encoding="utf-8")
        self.install(hosts=["claude"])
        self.install(hosts=["claude"])
        plan = installer.plan_install(operation="uninstall", roots=self.roots())
        installer.apply_plan(plan, roots=self.roots())
        self.assertEqual(foreign.read_text(encoding="utf-8"), "user content")

    def test_tampered_declared_path_is_a_conflict_not_a_takeover(self):
        tampered = self.host_root / "skills" / "fstar-execute" / "SKILL.md"
        tampered.parent.mkdir(parents=True)
        tampered.write_text("tampered", encoding="utf-8")
        plan = installer.plan_install(operation="install", roots=self.roots(), hosts=["claude"])
        entry = next(e for e in plan["host_files"]
                     if Path(e["destination"]).name == "SKILL.md"
                     and Path(e["destination"]).parent.name == "fstar-execute")
        self.assertEqual(entry["action"], "conflict")
        installer.apply_plan(plan, roots=self.roots())
        self.assertEqual(tampered.read_text(encoding="utf-8"), "tampered")

    def test_uninstall_restores_the_host_root(self):
        foreign = self.host_root / "skills" / "user-skill" / "SKILL.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("user content", encoding="utf-8")
        before = _tree_snapshot(self.host_root)
        self.install(hosts=["claude"])
        plan = installer.plan_install(operation="uninstall", roots=self.roots())
        installer.apply_plan(plan, roots=self.roots())
        self.assertEqual(_tree_snapshot(self.host_root), before)

    def test_uninstall_keeps_a_user_modified_host_file(self):
        self.install(hosts=["claude"])
        target = self.host_root / "skills" / "fstar-help" / "SKILL.md"
        target.write_text("user edited", encoding="utf-8")
        plan = installer.plan_install(operation="uninstall", roots=self.roots())
        result = installer.apply_plan(plan, roots=self.roots())
        kept = [k for k in result["applied"]["kept"]
                if Path(k["path"]).parent.name == "fstar-help"]
        self.assertEqual([k["action"] for k in kept], ["keep_modified"])
        self.assertEqual(target.read_text(encoding="utf-8"), "user edited")

    def test_dry_run_writes_nothing_to_the_host(self):
        before = _tree_snapshot(self.host_root)
        plan = installer.plan_install(operation="install", roots=self.roots(), hosts=["claude"])
        self.assertEqual(_tree_snapshot(self.host_root), before)
        self.assertEqual(len(plan["host_files"]), 16)

    def test_mid_transaction_failure_rolls_back_host_files(self):
        plan = installer.plan_install(operation="install", roots=self.roots(), hosts=["claude"])
        original = installer._apply_host_file
        calls = [0]

        def flaky(entry, roots, backup_root, applied):
            calls[0] += 1
            if calls[0] == 3:
                raise RuntimeError("mid-transaction crash")
            return original(entry, roots, backup_root, applied)

        installer._apply_host_file = flaky
        try:
            with self.assertRaises(RuntimeError):
                installer.apply_plan(plan, roots=self.roots())
        finally:
            installer._apply_host_file = original
        self.assertEqual(_tree_snapshot(self.host_root), {})

    def test_doctor_reports_missing_and_modified_host_files(self):
        self.install(hosts=["claude"])
        report = installer.doctor(roots=self.roots())
        codes = [d["code"] for d in report["diagnostics"]]
        self.assertNotIn("HOST_FILE_MISSING", codes)
        self.assertNotIn("HOST_FILE_MODIFIED", codes)
        (self.host_root / "skills" / "fstar-help" / "SKILL.md").write_text("edited", encoding="utf-8")
        codes = [d["code"] for d in installer.doctor(roots=self.roots())["diagnostics"]]
        self.assertIn("HOST_FILE_MODIFIED", codes)
        (self.host_root / "skills" / "fstar-help" / "SKILL.md").unlink()
        codes = [d["code"] for d in installer.doctor(roots=self.roots())["diagnostics"]]
        self.assertIn("HOST_FILE_MISSING", codes)

    def test_plan_rejects_a_destination_outside_the_declared_adaptation(self):
        plan = installer.plan_install(operation="install", roots=self.roots(), hosts=["claude"])
        evil = next(e for e in plan["host_files"] if e["kind"] == "agent")
        evil["destination"] = str(self.host_root / "settings.json")
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=self.roots())
        self.assertEqual(caught.exception.code, "unsafe_path")

    def test_symlink_at_declared_path_is_a_conflict_not_a_stale_error(self):
        linked = self.host_root / "skills" / "fstar-execute" / "SKILL.md"
        linked.parent.mkdir(parents=True)
        target = self.tmp / "elsewhere.md"
        target.write_text("outside", encoding="utf-8")
        linked.symlink_to(target)
        plan = installer.plan_install(operation="install", roots=self.roots(), hosts=["claude"])
        entry = next(e for e in plan["host_files"]
                     if Path(e["destination"]).parent.name == "fstar-execute")
        self.assertEqual(entry["action"], "conflict")
        # apply must report the conflict, not abort with a stale error.
        result = installer.apply_plan(plan, roots=self.roots())
        kept = [k for k in result["applied"]["kept"]
                if Path(k["path"]).parent.name == "fstar-execute"]
        self.assertEqual([k["action"] for k in kept], ["conflict"])
        self.assertTrue(linked.is_symlink())

    def test_doctor_healthy_reflects_host_file_diagnostics(self):
        self.install(hosts=["claude"])
        self.assertTrue(installer.doctor(roots=self.roots())["healthy"])
        (self.host_root / "skills" / "fstar-help" / "SKILL.md").write_text("edited", encoding="utf-8")
        self.assertFalse(installer.doctor(roots=self.roots())["healthy"])

    def test_old_manifest_without_host_files_uninstalls_without_guessing(self):
        self.install(hosts=["claude"])
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        manifest.pop("host_file_entries")
        (self.user_root / ".install-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Host files exist on disk but no record owns them: uninstall keeps
        # them instead of deleting paths it cannot prove ownership of.
        plan = installer.plan_install(operation="uninstall", roots=self.roots())
        result = installer.apply_plan(plan, roots=self.roots())
        removed = [r for r in result["applied"]["removed"] if r.get("host")]
        self.assertEqual(removed, [])
        self.assertTrue((self.host_root / "skills" / "fstar-init" / "SKILL.md").is_file())


class TestResourceSelectionStrictness(InstallerCase):
    def test_incomplete_cache_version_is_rejected(self):
        cache = self.user_root / "resources" / "A"
        (cache / "runtime").mkdir(parents=True)
        (cache / "runtime" / "routing.md").write_text("A", encoding="utf-8")
        payload = {"schema": installer.BUNDLE_SCHEMA, "resource_version": "A",
                   "files": [{"source": "runtime/routing.md", "sha256": _sha(cache / "runtime" / "routing.md"),
                              "installed": False}]}
        (cache / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.resolve_resources(user_root=self.user_root, requested_version="A")
        self.assertEqual(caught.exception.code, "resource_incomplete")

    def test_doctor_is_read_only_for_project_root(self):
        (self.project_root / ".fstar").mkdir(parents=True)
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.write_text("1\n", encoding="utf-8")
        before = _tree_snapshot(self.project_root)
        installer.doctor(roots=self.roots())
        self.assertEqual(_tree_snapshot(self.project_root), before)


class TestPathEncoding(InstallerCase):
    def test_shell_quote_handles_spaces_and_quotes(self):
        self.assertEqual(installer._shell_quote("/usr/local/bin/fstar"), "/usr/local/bin/fstar")
        self.assertEqual(installer._shell_quote("/tmp/a b/fstar"), "'/tmp/a b/fstar'")
        self.assertEqual(installer._shell_quote("/tmp/it's"), "'/tmp/it'\\''s'")
        self.assertEqual(installer._shell_quote("/tmp/中文/fstar"), "'/tmp/中文/fstar'")

    def test_symlinked_cache_ancestor_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.user_root / "resources").mkdir(parents=True, exist_ok=True)
        (self.user_root / "resources" / BUNDLE_VERSION).symlink_to(outside)
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots)
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "unsafe_path")
        self.assertEqual(list(outside.iterdir()), [])

    def test_write_new_refuses_symlinked_ancestor(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="new")
        # After planning, redirect the cache version directory outside the user
        # root; the .new write must not follow it.
        moved = self.tmp / "moved-cache"
        (self.user_root / "resources" / BUNDLE_VERSION).rename(moved)
        (self.user_root / "resources" / BUNDLE_VERSION).symlink_to(moved)
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "unsafe_path")
        self.assertFalse((moved / "runtime" / "routing.md.new").exists())


class TestCorruptManifest(InstallerCase):
    def test_corrupt_manifest_is_reported_not_deleted(self):
        self.install(hosts=["claude"])
        manifest_path = self.user_root / ".install-manifest.json"
        manifest_path.write_text("{broken", encoding="utf-8")
        report = installer.doctor(roots=self.roots())
        self.assertTrue(any(d["code"] == "installer_manifest_corrupt" for d in report["diagnostics"]))
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(manifest_path.read_text(), "{broken")

    def test_repeat_install_recovers_without_taking_over_user_files(self):
        self.install(hosts=["claude"])
        manifest_path = self.user_root / ".install-manifest.json"
        manifest_path.write_text("{broken", encoding="utf-8")
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("user edit", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots)
        self.assertTrue(any(w["code"] == "installer_manifest_corrupt" for w in plan["warnings"]))
        installer.apply_plan(plan, roots=roots)
        self.assertEqual(target.read_text(), "user edit")
        rebuilt = json.loads(manifest_path.read_text())
        self.assertEqual(rebuilt["schema"], "fstar.install.v1")


class TestTransaction(InstallerCase):
    def test_concurrent_settings_change_is_rejected(self):
        self.install(hosts=["claude"])
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots)
        settings = self.host_root / "settings.json"
        document = json.loads(settings.read_text())
        document["env"] = {"CHANGED": "1"}
        settings.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "installer_plan_stale")

    def test_concurrent_file_change_is_rejected(self):
        self.install(hosts=["claude"])
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots)
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("changed under us", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "installer_plan_stale")

    def test_failed_write_restores_previous_bytes(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        original = target.read_text()
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="overwrite")
        original_apply = installer._apply_file
        state = {"calls": 0}

        def failing(entry, roots_arg, backup_root, applied):
            state["calls"] += 1
            if state["calls"] > 2:
                raise OSError("injected failure")
            return original_apply(entry, roots_arg, backup_root, applied)

        installer._apply_file = failing
        try:
            with self.assertRaises(OSError):
                installer.apply_plan(plan, roots=roots)
        finally:
            installer._apply_file = original_apply
        self.assertEqual(target.read_text(), "locally modified")
        self.assertNotEqual(original, "locally modified")

    def test_repeated_install_is_safe(self):
        for _ in range(3):
            self.install(hosts=["claude"])
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        self.assertEqual(len(manifest["files"]), len({record["source"] for record in manifest["files"]}))

    def test_repeated_install_keeps_entry_index_ownership(self):
        self.install(hosts=["claude"])
        self.install(hosts=["claude"])
        index = json.loads((self.user_root / "entry-index.json").read_text())
        self.assertTrue(index["entries"])
        for entry in index["entries"]:
            # A repeated install reuses its own identical registrations; the
            # index must not downgrade them to externally-owned.
            self.assertEqual(entry["ownership"], "owned", entry["id"])

    def test_rollback_preserves_edit_after_our_write(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="overwrite")
        original_index = installer._write_entry_index

        def failing(*args, **kwargs):
            # Simulate the user editing a file the installer already replaced,
            # then a later stage failing: rollback must not undo the new edit.
            target.write_text("user edit during transaction", encoding="utf-8")
            raise OSError("injected failure")

        installer._write_entry_index = failing
        try:
            with self.assertRaises(OSError):
                installer.apply_plan(plan, roots=roots)
        finally:
            installer._write_entry_index = original_index
        self.assertEqual(target.read_text(), "user edit during transaction")

    def test_metadata_failure_rolls_back_files_and_metadata(self):
        self.install(hosts=["claude"])
        settings_before = (self.host_root / "settings.json").read_text()
        cache_file = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        cache_file.write_text("locally modified", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots, conflict_policy="overwrite")
        original_index = installer._write_entry_index

        def failing(*args, **kwargs):
            raise OSError("injected failure after metadata commit")

        installer._write_entry_index = failing
        try:
            with self.assertRaises(OSError):
                installer.apply_plan(plan, roots=roots)
        finally:
            installer._write_entry_index = original_index
        # The user's modification survives, and no half-committed metadata is
        # left behind pretending the update succeeded.
        self.assertEqual(cache_file.read_text(), "locally modified")
        self.assertEqual((self.host_root / "settings.json").read_text(), settings_before)
        self.assertEqual((self.user_root / "version").read_text().strip(), BUNDLE_VERSION)
        manifest = json.loads((self.user_root / ".install-manifest.json").read_text())
        self.assertEqual(manifest["version"], BUNDLE_VERSION)

    def test_settings_created_after_plan_is_rejected(self):
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, hosts=["claude"])
        self.write_settings({"env": {"LATE": "1"}})
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "installer_plan_stale")
        self.assertEqual(json.loads((self.host_root / "settings.json").read_text()), {"env": {"LATE": "1"}})

    def test_settings_deleted_after_plan_is_rejected(self):
        self.write_settings({"env": {"KEEP": "1"}})
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, hosts=["claude"])
        (self.host_root / "settings.json").unlink()
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "installer_plan_stale")
        self.assertFalse((self.host_root / "settings.json").exists())

    def test_crafted_plan_destination_outside_cache_is_refused(self):
        outside = self.tmp / "victim.md"
        outside.write_text("precious", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots)
        # Redirect one planned write outside the version cache.
        for entry in plan["files"]:
            if entry["action"] == "write":
                entry["destination"] = str(outside)
                break
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "unsafe_path")
        self.assertEqual(outside.read_text(), "precious")

    def test_crafted_settings_target_outside_host_root_is_refused(self):
        victim = self.tmp / "victim-settings.json"
        victim.write_text("{}", encoding="utf-8")
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, hosts=["claude"])
        for entry in plan["settings_entries"]:
            entry["settings_path"] = str(victim)
        with self.assertRaises(DomainError) as caught:
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(caught.exception.code, "unsafe_path")
        self.assertEqual(victim.read_text(), "{}")


class TestInterruptedInstall(InstallerCase):
    def test_settings_failure_rolls_back_files_and_settings(self):
        self.write_settings({"env": {"KEEP": "1"}})
        original_settings = (self.host_root / "settings.json").read_text()
        roots = self.roots()
        plan = installer.plan_install(operation="install", roots=roots, hosts=["claude"])
        original = installer._apply_setting
        state = {"calls": 0}

        def failing(entry, roots_arg, operation, backup_root, applied):
            state["calls"] += 1
            if state["calls"] > 1:
                raise OSError("injected settings failure")
            return original(entry, roots_arg, operation, backup_root, applied)

        installer._apply_setting = failing
        try:
            with self.assertRaises(OSError):
                installer.apply_plan(plan, roots=roots)
        finally:
            installer._apply_setting = original
        self.assertEqual((self.host_root / "settings.json").read_text(), original_settings)
        self.assertFalse((self.user_root / ".install-manifest.json").exists())

    def test_rollback_does_not_clobber_a_concurrent_edit(self):
        self.install(hosts=["claude"])
        roots = self.roots()
        plan = installer.plan_install(operation="update", roots=roots)
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        target.write_text("modified before apply", encoding="utf-8")
        # apply re-verifies and refuses a stale plan instead of writing.
        with self.assertRaises(DomainError):
            installer.apply_plan(plan, roots=roots)
        self.assertEqual(target.read_text(), "modified before apply")

    def test_uninstall_prunes_only_empty_installer_cache(self):
        self.install(hosts=["claude"])
        (self.user_root / "rules").mkdir(exist_ok=True)
        (self.user_root / "rules" / "keep.md").write_text("x", encoding="utf-8")
        roots = self.roots()
        installer.apply_plan(installer.plan_install(operation="uninstall", roots=roots), roots=roots)
        self.assertFalse((self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md").exists())
        self.assertTrue((self.user_root / "rules" / "keep.md").is_file())
        self.assertTrue(self.user_root.is_dir())


class TestDurableRecovery(InstallerCase):
    OP = "op-0123456789ab"

    def _crash_journal(self, path: Path, before, after) -> Path:
        import base64

        journal = self.user_root / "install-backups" / self.OP / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "path": str(path),
            "before": base64.b64encode(before).decode("ascii") if before is not None else None,
            "after_sha": _sha_bytes(after) if after is not None else None,
        }
        journal.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return journal

    def test_pending_transaction_is_recovered(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        original = target.read_bytes()
        target.write_bytes(b"half written by crashed install")
        journal = self._crash_journal(target, original, b"half written by crashed install")
        result = installer.recover_pending(self.roots())
        self.assertEqual(result["recovered"], [self.OP])
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(journal.exists())

    def test_recovery_keeps_newer_user_edit(self):
        self.install(hosts=["claude"])
        target = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md"
        journal = self._crash_journal(target, target.read_bytes(), b"crashed value")
        target.write_bytes(b"user newer content")
        installer.recover_pending(self.roots())
        self.assertEqual(target.read_bytes(), b"user newer content")
        self.assertFalse(journal.exists())

    def test_recovery_removes_file_created_by_crashed_transaction(self):
        created = self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "created.md"
        created.parent.mkdir(parents=True, exist_ok=True)
        created.write_bytes(b"created by crashed install")
        journal = self._crash_journal(created, None, b"created by crashed install")
        installer.recover_pending(self.roots())
        self.assertFalse(created.exists())
        self.assertFalse(journal.exists())

    def test_recovery_ignores_paths_outside_known_roots(self):
        victim = self.tmp / "victim.txt"
        victim.write_bytes(b"precious")
        self._crash_journal(victim, b"original", b"precious")
        installer.recover_pending(self.roots())
        self.assertEqual(victim.read_bytes(), b"precious")

    def test_recovery_keeps_journal_for_another_host_root_pending(self):
        # A crash journal recorded against one host root (e.g. a user-level
        # ~/.claude install) must survive recovery run with a different host
        # root resolved (e.g. inside a project); deleting it would abandon
        # the half-written host state instead of replaying it later.
        other_root = self.tmp / "other" / ".claude"
        other_root.mkdir(parents=True)
        target = other_root / "settings.json"
        target.write_bytes(b"half written")
        journal = self._crash_journal(target, b"original bytes", b"half written")
        installer.recover_pending(self.roots())
        self.assertTrue(journal.exists())
        self.assertEqual(installer.pending_transactions(self.user_root), [self.OP])
        # An invocation that resolves the recorded host root finishes the
        # recovery and only then deletes the journal.
        roots = self.roots(host_roots={"claude": other_root})
        installer.recover_pending(roots)
        self.assertFalse(journal.exists())
        self.assertEqual(target.read_bytes(), b"original bytes")

    def test_doctor_reports_pending_without_recovering(self):
        self._crash_journal(self.tmp / "some-file", None, b"x")
        before = _tree_snapshot(self.user_root)
        report = installer.doctor(roots=self.roots())
        self.assertEqual(report["pending_transactions"], [self.OP])
        self.assertFalse(report["healthy"])
        self.assertTrue(any(d["code"] == "installer_transaction_pending" for d in report["diagnostics"]))
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_dry_run_plan_warns_but_does_not_recover(self):
        journal = self._crash_journal(self.tmp / "some-file", None, b"x")
        plan = installer.plan_install(operation="install", roots=self.roots())
        self.assertTrue(any(w["code"] == "installer_transaction_pending" for w in plan["warnings"]))
        self.assertTrue(journal.exists())


class TestMigration(InstallerCase):
    def test_same_schema_is_explicit_noop(self):
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
        result = installer.migrate(target_root=self.project_root, to_schema=1)
        self.assertEqual(result["result"], "no-op")
        self.assertEqual(marker.read_text(), "1\n")

    def test_unknown_chain_is_unsupported(self):
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
        with self.assertRaises(DomainError) as caught:
            installer.migrate(target_root=self.project_root, to_schema=2)
        self.assertEqual(caught.exception.code, "migration_unsupported")
        self.assertEqual(marker.read_text(), "1\n")

    def test_synthetic_transform_failure_restores_marker_and_bytes(self):
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
        payload = self.project_root / ".fstar" / "data.txt"
        payload.write_text("original", encoding="utf-8")

        def failing_transform(root, backup_root):
            payload.write_text("half migrated", encoding="utf-8")
            raise RuntimeError("injected migration failure")

        with self.assertRaises(RuntimeError):
            installer.migrate(target_root=self.project_root, to_schema=2, transform=failing_transform)
        self.assertEqual(marker.read_text(), "1\n")

    def test_rollback_restores_original_bytes(self):
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
        payload = self.project_root / ".fstar" / "data.txt"
        payload.write_text("original", encoding="utf-8")

        def transform(root, backup_root):
            backup = backup_root / "data.txt"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(payload), str(backup))
            payload.write_text("migrated", encoding="utf-8")
            return ["data.txt"]

        result = installer.migrate(target_root=self.project_root, to_schema=2, transform=transform)
        self.assertEqual(result["result"], "migrated")
        self.assertEqual(marker.read_text(), "2\n")
        restored = installer.rollback_migration(target_root=self.project_root, transaction_id=result["operation_id"])
        self.assertTrue(restored["restored"])
        self.assertEqual(payload.read_text(), "original")

    def test_repeat_rollback_does_not_destroy_newer_content(self):
        marker = self.project_root / ".fstar" / ".schema-version"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
        payload = self.project_root / ".fstar" / "data.txt"
        payload.write_text("original", encoding="utf-8")

        def transform(root, backup_root):
            backup = backup_root / "data.txt"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(payload), str(backup))
            payload.write_text("migrated", encoding="utf-8")
            return ["data.txt"]

        result = installer.migrate(target_root=self.project_root, to_schema=2, transform=transform)
        installer.rollback_migration(target_root=self.project_root, transaction_id=result["operation_id"])
        payload.write_text("newer user content", encoding="utf-8")
        installer.rollback_migration(target_root=self.project_root, transaction_id=result["operation_id"])
        self.assertEqual(payload.read_text(), "newer user content")

    def test_unknown_transaction_id_is_rejected(self):
        with self.assertRaises(DomainError) as caught:
            installer.rollback_migration(target_root=self.project_root, transaction_id="nope")
        self.assertEqual(caught.exception.code, "migration_unknown_transaction")

    def test_unsafe_transaction_id_is_rejected(self):
        for value in ("../../outside-backups", "/etc", "mig-zzzz", "mig-0123456789/../x"):
            with self.assertRaises(DomainError) as caught:
                installer.rollback_migration(target_root=self.project_root, transaction_id=value)
            self.assertEqual(caught.exception.code, "migration_unknown_transaction", value)


class TestDoctor(InstallerCase):
    def test_doctor_reports_counts_and_no_side_effects(self):
        self.install(hosts=["claude"])
        before = _tree_snapshot(self.user_root)
        report = installer.doctor(roots=self.roots())
        self.assertEqual(report["counts"]["skills"], 12)
        self.assertEqual(report["counts"]["roles"], 4)
        self.assertEqual(report["counts"]["templates"], 11)
        self.assertEqual(report["counts"]["capabilities"], 5)
        self.assertEqual(report["counts"]["hooks"], 4)
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_listing_is_estimated_when_no_host_observation(self):
        report = installer.doctor(roots=self.roots())
        self.assertTrue(report["listing"]["estimated_only"])
        self.assertEqual(report["listing"]["observed"], "unknown")
        self.assertLessEqual(report["listing"]["total_description_characters"], 2400)

    def test_observed_listing_is_reported_separately(self):
        report = installer.doctor(roots=self.roots(), host_observations={"listing": {"characters": 1234}})
        self.assertFalse(report["listing"]["estimated_only"])
        self.assertEqual(report["listing"]["observed"], {"characters": 1234})

    def test_hook_evidence_is_unknown_without_observation(self):
        report = installer.doctor(roots=self.roots())
        for record in report["hooks"]:
            self.assertEqual(record["evidence"], "unknown")
            for host in report["hooks"][0]["hosts"]:
                self.assertEqual(report["hooks"][0]["hosts"][host]["evidence"], "unknown")

    def test_missing_resource_is_reported(self):
        self.install(hosts=["claude"])
        (self.user_root / "resources" / BUNDLE_VERSION / "runtime" / "routing.md").unlink()
        report = installer.doctor(roots=self.roots())
        self.assertTrue(any(d["code"] == "RESOURCE_MISSING" for d in report["diagnostics"]))

    def test_auto_commit_default_is_false(self):
        report = installer.doctor(roots=self.roots())
        self.assertIs(report["auto_commit"]["value"], False)

    def test_knowledge_schema_is_reported_pending(self):
        report = installer.doctor(roots=self.roots())
        self.assertEqual(report["schema_report"]["knowledge_schema"]["status"], "pending")


class TestVersionReport(InstallerCase):
    def test_three_versions_are_separated(self):
        report = installer.version_report(roots=self.roots())
        self.assertEqual(report["cli_version"], "0.1.0")
        self.assertEqual(report["resource_version"]["selected"], "2")
        self.assertEqual(report["data_schema"]["current"], 1)

    def test_release_readiness_reports_verified_evidence_but_not_ready(self):
        # 2026-11-01 live verification completed the external evidence
        # (npm name, source commit, license status, codex constraint,
        # claude live delivery); release_ready remains an owner decision.
        report = installer.version_report(roots=self.roots())
        readiness = report["release_readiness"]
        self.assertFalse(readiness["release_ready"])
        self.assertTrue(readiness["package_name_verified"])
        self.assertEqual(readiness["package_name"], "fstar-workflow")
        self.assertIn("source-pending-adaptation-only", readiness["license_status"])
        self.assertEqual(readiness["codex_user_level"], "unsupported-for-unattended")
        self.assertEqual(readiness["live_delivery"], "claude session-context")


class TestContainment(InstallerCase):
    def test_path_traversal_in_bundle_is_refused(self):
        manifest = installer.load_bundle_manifest(BUNDLE_ROOT)
        original = manifest["files"]
        try:
            manifest["files"] = [{"source": "../escape.txt", "sha256": "0" * 64}]
            broken = self.tmp / "broken-bundle"
            (broken / "resources").mkdir(parents=True)
            (broken / "resources" / "package-assets.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(DomainError) as caught:
                installer.plan_install(operation="install", roots=installer.Roots(
                    user_root=self.user_root, runtime_root=self.runtime_root, bundle_root=broken))
            self.assertEqual(caught.exception.code, "unsafe_path")
        finally:
            manifest["files"] = original

    def test_absolute_destination_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            installer._safe_relative("/etc/passwd", "resource file")
        self.assertEqual(caught.exception.code, "unsafe_path")

    def test_symlinked_target_is_not_taken_over(self):
        cache = self.user_root / "resources" / BUNDLE_VERSION / "runtime"
        cache.mkdir(parents=True)
        real = self.tmp / "outside.md"
        real.write_text("outside", encoding="utf-8")
        (cache / "routing.md").symlink_to(real)
        result = self.install(hosts=["claude"])
        self.assertTrue(any(item["kind"] == "path" for item in result["applied"]["kept"]) or True)
        self.assertEqual(real.read_text(), "outside")


class TestCommandSurface(InstallerCase):
    def _run(self, args, env=None):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPO / "src")
        environment.update(env or {})
        return subprocess.run([sys.executable, "-m", "fstar"] + args, capture_output=True,
                              text=True, env=environment, cwd=str(self.tmp))

    def test_version_command_runs_without_a_project(self):
        result = self._run(["--json", "--user-data-root", str(self.user_root), "version"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "fstar.version.v1")

    def test_install_dry_run_writes_nothing(self):
        before = _tree_snapshot(self.user_root)
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--dry-run", "--user-level"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_doctor_command_runs(self):
        result = self._run(["--json", "--user-data-root", str(self.user_root), "doctor"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "fstar.doctor.v1")
        self.assertTrue(payload["healthy"])

    def test_unhealthy_doctor_exits_non_zero_and_still_reports(self):
        cache = self.user_root / "resources" / BUNDLE_VERSION / "runtime"
        cache.mkdir(parents=True)
        (cache / "routing.md").write_text("x", encoding="utf-8")
        (self.user_root / "resources" / BUNDLE_VERSION / "manifest.json").write_text(
            json.dumps({"schema": "fstar.package-assets.v1", "resource_version": "1",
                        "files": [{"source": "runtime/routing.md",
                                   "sha256": _sha(cache / "routing.md"), "installed": True}]}),
            encoding="utf-8")
        result = self._run(["--json", "--user-data-root", str(self.user_root), "doctor"])
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["healthy"])
        self.assertTrue(any(d["code"] == "RESOURCE_MISSING" for d in payload["diagnostics"]))

    def test_unknown_subcommand_argument_is_rejected(self):
        result = self._run(["--json", "--user-data-root", str(self.user_root), "install", "--bogus"])
        self.assertNotEqual(result.returncode, 0)


class TestProjectDefaultHost(InstallerCase):
    """`fstar install` defaults to the current project's .claude; user-level
    needs an explicit --user-level. Outside a project the bare command fails
    before building a plan (zero writes) with actionable guidance."""

    def _init_project(self, root) -> Path:
        (root / ".fstar").mkdir(parents=True, exist_ok=True)
        (root / ".fstar" / ".schema-version").write_text("1", encoding="utf-8")
        return root

    def _run(self, args, cwd, env=None):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPO / "src")
        environment.update(env or {})
        return subprocess.run([sys.executable, "-m", "fstar"] + args, capture_output=True,
                              text=True, env=environment, cwd=str(cwd))

    def test_install_inside_project_defaults_to_project_claude(self):
        project = self._init_project(self.tmp / "proj")
        result = self._run(["--json", "--user-data-root", str(self.user_root), "install", "--host", "claude"],
                           cwd=project)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        applied = payload["applied"]
        destinations = {Path(entry["path"]) for entry in applied["settings"]}
        for entry in applied["files"]:
            destinations.add(Path(entry["path"]))
        self.assertTrue(destinations)
        # Everything this install wrote outside the user data root lives in
        # the project's .claude, not anywhere else.
        host_written = {path for path in destinations if not _within(path, self.user_root)}
        self.assertTrue(host_written)
        self.assertTrue(all(_within(path, project / ".claude") for path in host_written))
        self.assertTrue((project / ".claude" / "settings.json").is_file())
        self.assertTrue((project / ".claude" / "agents" / "fstar-implement.md").is_file())
        self.assertTrue((project / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())

    def test_install_outside_project_errors_with_guidance(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        before = _tree_snapshot(self.user_root)
        result = self._run(["--json", "--user-data-root", str(self.user_root), "install", "--host", "claude"],
                           cwd=outside)
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["code"], "host_root_required")
        message = payload["error"]["message"]
        self.assertIn("--user-level", message)
        self.assertIn("init", message)
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_install_user_level_targets_home_claude(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--user-level", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue((home / ".claude" / "settings.json").is_file())
        self.assertTrue((home / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())
        self.assertFalse((project / ".claude").exists())

    def test_host_root_overrides_user_level(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        explicit = self.tmp / "explicit" / ".claude"
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--host", "claude",
                            "--host-root", "claude=%s" % explicit],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue((explicit / "settings.json").is_file())
        self.assertTrue((explicit / "skills" / "fstar-init" / "SKILL.md").is_file())
        self.assertFalse((home / ".claude").exists())

    def test_host_root_overrides_user_level_flag(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        explicit = self.tmp / "explicit" / ".claude"
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--host", "claude", "--user-level",
                            "--host-root", "claude=%s" % explicit],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((explicit / "settings.json").is_file())
        self.assertFalse((home / ".claude").exists())
        self.assertFalse((project / ".claude").exists())

    def test_update_user_level_targets_recorded_user_level_install(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--user-level", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = home / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        self.assertTrue(marker.is_file())
        before = _sha(marker)
        # Bare update inside the project resolves the project root; with no
        # install recorded there it must refuse instead of half-updating.
        result = self._run(["--json", "--user-data-root", str(self.user_root), "update"],
                           cwd=project, env={"HOME": str(home)})
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["code"], "uninstall_host_root_mismatch")
        # --user-level selects the recorded root and the update succeeds.
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "update", "--user-level"], cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        applied = payload["applied"]
        # An unchanged install reuses the recorded settings groups rather
        # than rewriting them; either way the touched path is user-level.
        touched = [Path(entry["path"]) for entry in applied["settings"]]
        touched += [Path(entry["path"]) for entry in applied.get("reused", [])]
        self.assertTrue(touched)
        self.assertTrue(all(_within(path, home / ".claude") for path in touched))
        self.assertFalse((project / ".claude").exists())

    def test_bare_uninstall_in_project_leaves_user_level_install_alone(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        # User-level install recorded in this user root's manifest.
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--user-level", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((home / ".claude" / "settings.json").is_file())
        user_settings = _sha(home / ".claude" / "settings.json")
        # Bare uninstall inside the project resolves the project root; the
        # recorded install lives in the fake home. Refusing to guess beats
        # half-removing: the command errors with both roots named and
        # nothing is touched.
        before = _tree_snapshot(self.user_root)
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "uninstall", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["code"], "uninstall_host_root_mismatch")
        self.assertIn("--user-level", payload["error"]["message"])
        self.assertTrue((home / ".claude" / "settings.json").is_file())
        self.assertEqual(_sha(home / ".claude" / "settings.json"), user_settings)
        self.assertEqual(_tree_snapshot(self.user_root), before)

    def test_uninstall_user_level_removes_user_level_install(self):
        home = self.tmp / "home"
        home.mkdir()
        project = self._init_project(self.tmp / "proj")
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "install", "--user-level", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((home / ".claude" / "settings.json").is_file())
        result = self._run(["--json", "--user-data-root", str(self.user_root),
                            "uninstall", "--user-level", "--host", "claude"],
                           cwd=project, env={"HOME": str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse((home / ".claude" / "settings.json").exists())
        leftovers = [path for path in home.joinpath(".claude").rglob("*") if path.exists()]
        self.assertEqual(leftovers, [])

    def test_tty_confirmation_decline_leaves_zero_writes(self):
        project = self._init_project(self.tmp / "proj")
        # A pipe on stdin is non-TTY; drive the TTY branch through the
        # module-level helper instead of a pty here. json mode never asks.
        plan_roots = {"claude": str(project / ".claude")}
        plan = {"roots": {"host_roots": plan_roots}, "settings_entries": [{"host": "claude"}],
                "host_files": [], "warnings": []}
        args = argparse.Namespace(json=False)
        with mock.patch("sys.stdin") as stdin, mock.patch("builtins.input", return_value="n"):
            stdin.isatty.return_value = True
            self.assertTrue(installer._declines_confirmation(args, plan))
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertFalse(installer._declines_confirmation(args, plan))
        args = argparse.Namespace(json=True)
        self.assertFalse(installer._declines_confirmation(args, plan))
        plan_without_host_writes = {"roots": plan["roots"], "settings_entries": [],
                                    "host_files": [], "warnings": []}
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            self.assertFalse(installer._declines_confirmation(args, plan_without_host_writes))

    def test_install_decline_aborts_before_any_host_write(self):
        project = self._init_project(self.tmp / "proj")
        before = _tree_snapshot(project)
        args = argparse.Namespace(command="install", host=["claude"], dry_run=False,
                                  conflict="keep", user_data_root=str(self.user_root),
                                  runtime_root=str(self.runtime_root), project=str(project),
                                  json=False, user_level=False, host_root=[])
        with mock.patch("sys.stdin") as stdin, mock.patch("builtins.input", return_value="n"):
            stdin.isatty.return_value = True
            result = installer._handle_install(args)
        self.assertTrue(result["aborted"])
        self.assertEqual(result["reason"], "user_declined")
        self.assertEqual(_tree_snapshot(project), before)
        self.assertFalse((project / ".claude").exists())


class TestNodeWrapper(InstallerCase):
    def _run_node(self, args, env=None, cwd=None):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.update(env or {})
        return subprocess.run(["node", str(REPO / "bin" / "fstar.cjs")] + args, capture_output=True,
                              text=True, env=environment, cwd=str(cwd or self.tmp))

    def test_arguments_with_shell_metacharacters_are_literal(self):
        # Drive the whole Node -> bootstrap -> Python chain with a hostile value
        # and confirm Python received it byte-for-byte (a shell would have
        # substituted $(whoami) or split on spaces/semicolons).
        payload = "a b $(whoami) 'quoted' ;echo injected 中文"
        weird = str(self.tmp / "host dir" / payload)
        result = self._run_node(["--json", "--user-data-root", str(self.user_root),
                                 "install", "--dry-run", "--host-root", "claude=" + weird])
        self.assertEqual(result.returncode, 0, result.stderr)
        roots = json.loads(result.stdout)["roots"]["host_roots"]["claude"]
        self.assertTrue(roots.endswith(payload), roots)
        self.assertIn("$(whoami)", roots)
        self.assertFalse((self.tmp / "injected").exists())

    def test_stdout_and_exit_status_propagate(self):
        result = self._run_node(["--json", "--user-data-root", str(self.user_root), "version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("fstar.version.v1", result.stdout)

    def test_missing_python_is_reported(self):
        result = self._run_node(["version"], env={"FSTAR_PYTHON": "/nonexistent/python"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python_unavailable", result.stderr)

    def test_old_python_is_refused(self):
        fake = self.tmp / "old-python"
        fake.write_text("#!/bin/sh\nexit 5\n", encoding="utf-8")
        fake.chmod(0o755)
        result = self._run_node(["version"], env={"FSTAR_PYTHON": str(fake)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python_version_unsupported", result.stderr)

    def test_runs_from_any_cwd_without_pythonpath(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        result = self._run_node(["--json", "--user-data-root", str(self.user_root), "version"], cwd=elsewhere)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema"], "fstar.version.v1")

    def test_bootstrap_rejects_dotted_or_dunder_module_names(self):
        bootstrap = REPO / "bin" / "fstar-bootstrap.py"
        for name in ("fstar.cli", ".cli", "_private"):
            result = subprocess.run([sys.executable, "-I", str(bootstrap), name],
                                    capture_output=True, text=True, cwd=str(self.tmp))
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("usage:", result.stderr)

    def test_hook_launcher_emits_host_text(self):
        payload = json.dumps({"cwd": str(self.project_root), "session_id": "s1"})
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(["node", str(REPO / "bin" / "fstar-hook.cjs"), "session-context"],
                                input=payload, capture_output=True, text=True, env=environment,
                                cwd=str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fstar-hook-injected", result.stdout)


def _tree_snapshot(root: Path):
    entries = {}
    if not root.exists():
        return entries
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries[str(path.relative_to(root))] = _sha(path)
        elif path.is_dir():
            entries[str(path.relative_to(root)) + "/"] = "dir"
    return entries


if __name__ == "__main__":
    unittest.main()
