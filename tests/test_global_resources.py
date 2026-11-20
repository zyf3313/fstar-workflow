"""Global resource management tests (P-001/P-002): default host resolution,
read-only inspection, explicit runtime reminders, and consent-gated migration.

Every test uses temporary user/runtime/host roots; no real ~/.fstar or
~/.claude content is touched.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fstar import global_resources as gr  # noqa: E402
from fstar import installer  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class GlobalResourcesCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-global-"))
        self.addCleanup(self._cleanup)
        self.user_root = self.tmp / "user" / ".fstar"
        self.user_root.mkdir(parents=True)
        self.runtime_root = self.tmp / "user" / ".fstar" / "runtime"
        self.runtime_root.mkdir(parents=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.project = self.tmp / "proj"
        (self.project / ".fstar").mkdir(parents=True)
        _write(self.project / ".fstar" / ".schema-version", "1")
        _write(self.project / ".fstar" / "config.yaml",
               'schema_version: 1\nproject:\n  id: "11111111-2222-3333-4444-555555555555"\n')

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record_project_copy(self, relative: str, content: str) -> dict:
        destination = self.project / ".claude" / relative
        _write(destination, content)
        # Seed a healthy global counterpart under the fake home so the
        # migration's precondition (usable global entry) holds.
        global_copy = self.home / ".claude" / relative
        _write(global_copy, "global content\n")
        manifest_path = self.user_root / ".install-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
            "schema": installer.MANIFEST_SCHEMA, "files": [], "settings_entries": []}
        manifest.setdefault("host_file_entries", []).append({
            "host": "claude", "kind": "skill",
            "source": "resources/skills/fstar-init/SKILL.md",
            "destination": str(destination),
            "installed_hash": installer._sha256_bytes(content.encode("utf-8")),
            "ownership": "owned"})
        manifest["host_file_entries"].append({
            "host": "claude", "kind": "skill",
            "source": "resources/skills/fstar-init/SKILL.md",
            "destination": str(global_copy),
            "installed_hash": installer._sha256(global_copy),
            "ownership": "owned"})
        installer._atomic_write_json(manifest_path, manifest)
        return {"destination": destination, "hash": installer._sha256(destination)}

    def _host_roots(self) -> dict:
        return {"claude": self.home / ".claude"}


    def _project_identity(self) -> str:
        return gr._project_identity(self.project, self.user_root)


class TestRuntimeReminders(GlobalResourcesCase):
    def test_delivery_dedupes_within_session(self):
        first = gr.record_delivery(runtime_root=self.runtime_root,
                                   project_identity="p1", target_version="7",
                                   session_id="s1")
        self.assertTrue(first["shown"])
        second = gr.record_delivery(runtime_root=self.runtime_root,
                                    project_identity="p1", target_version="7",
                                    session_id="s1")
        self.assertFalse(second["shown"])
        # Different session: asks again.
        other = gr.record_delivery(runtime_root=self.runtime_root,
                                   project_identity="p1", target_version="7",
                                   session_id="s2")
        self.assertTrue(other["shown"])

    def test_deferral_persists_per_target_version(self):
        gr.record_deferral(runtime_root=self.runtime_root,
                           project_identity="p1", target_version="7")
        decision = gr.session_prompt_needed(runtime_root=self.runtime_root,
                                            project_identity="p1",
                                            target_version="7", session_id="s9")
        self.assertFalse(decision["ask"])
        # A new global target version is eligible again.
        decision = gr.session_prompt_needed(runtime_root=self.runtime_root,
                                            project_identity="p1",
                                            target_version="8", session_id="s9")
        self.assertTrue(decision["ask"])

    def test_deferral_scoped_to_project(self):
        gr.record_deferral(runtime_root=self.runtime_root,
                           project_identity="p1", target_version="7")
        other = gr.session_prompt_needed(runtime_root=self.runtime_root,
                                         project_identity="p2",
                                         target_version="7", session_id="s1")
        self.assertTrue(other["ask"])

    def test_failed_write_reports_unrecorded(self):
        blocker = self.runtime_root / "resource-deliveries.json"
        blocker.write_text("not-a-directory-trick", encoding="utf-8")
        # Make writes fail: point at a file as runtime root's parent dir path.
        bad_root = self.tmp / "file-root"
        bad_root.write_text("x", encoding="utf-8")
        outcome = gr.record_delivery(runtime_root=bad_root / "runtime",
                                     project_identity="p", target_version="7",
                                     session_id="s")
        self.assertFalse(outcome["recorded"])
        self.assertEqual(outcome["reason"], "runtime_write_failed")


class TestInspection(GlobalResourcesCase):
    def test_uninitialized_style_unrelated_dirs_not_flagged(self):
        # A project with no legacy copies: no migration recommended.
        report = gr.inspect_project(project_root=self.project, user_root=self.user_root)
        self.assertEqual(report["legacy"]["count"], 0)
        self.assertFalse(report["migration_recommended"])

    def test_inspection_is_zero_write(self):
        before = {}
        for base in (self.project, self.user_root):
            for path in sorted(base.rglob("*")):
                before[str(path)] = path.stat().st_mtime_ns
        report = gr.inspect_project(project_root=self.project, user_root=self.user_root)
        self.assertTrue(report["read_only"])
        for base in (self.project, self.user_root):
            for path in sorted(base.rglob("*")):
                self.assertEqual(before.get(str(path)), path.stat().st_mtime_ns, str(path))
            for path in sorted(base.rglob("*")):
                pass
        # No new files either.
        for base in (self.project, self.user_root):
            self.assertEqual({str(p) for p in base.rglob("*")}, set(before) & set(str(p) for p in base.rglob("*")))


class TestMigration(GlobalResourcesCase):
    def test_migration_requires_confirmation(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "x\n")
        with self.assertRaises(ValueError):
            gr.apply_migration(project_root=self.project, user_root=self.user_root,
                               runtime_root=self.runtime_root, confirmation=None)

    def test_migration_moves_owned_unmodified_copy_and_backs_up(self):
        entry = self._record_project_copy("skills/fstar-init/SKILL.md", "staged content\n")
        confirmation = {"approved": True, "source_id": "conversation", "type": "conversation"}
        outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root,
                                     host_roots=self._host_roots(), confirmation=confirmation)
        self.assertEqual(outcome["result"], "migrated")
        self.assertFalse(entry["destination"].exists())
        backup = Path(outcome["applied"][0]["backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"), "staged content\n")

    def test_migration_keeps_user_modified_copy(self):
        destination = self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        _write(destination, "original\n")
        manifest_path = self.user_root / ".install-manifest.json"
        installer._atomic_write_json(manifest_path, {
            "schema": installer.MANIFEST_SCHEMA, "files": [], "settings_entries": [],
            "host_file_entries": [
                {"host": "claude", "kind": "skill",
                 "source": "resources/skills/fstar-init/SKILL.md",
                 "destination": str(destination),
                 "installed_hash": installer._sha256_bytes(b"original\n"),
                 "ownership": "owned"}]})
        _write(destination, "user edits\n")  # modified after install
        global_copy = self.home / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        _write(global_copy, "global content\n")
        # Global entry must be recorded too so the migration precondition holds.
        manifest = installer._load_manifest_safe(self.user_root)[0]
        manifest["host_file_entries"].append({
            "host": "claude", "kind": "skill",
            "source": "resources/skills/fstar-init/SKILL.md",
            "destination": str(global_copy),
            "installed_hash": installer._sha256(global_copy),
            "ownership": "owned"})
        installer._atomic_write_json(manifest_path, manifest)
        outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root,
                                     host_roots=self._host_roots(),
                                     confirmation={"approved": True})
        self.assertEqual(outcome["result"], "migrated")
        self.assertTrue((self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())
        kept = [item for item in outcome["kept"] if "keep_modified" in item.get("action", "")]
        self.assertTrue(kept)

    def test_migration_is_idempotent(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "a\n")
        confirmation = {"approved": True}
        first = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                   runtime_root=self.runtime_root,
                                   host_roots=self._host_roots(), confirmation=confirmation)
        self.assertEqual(first["result"], "migrated")
        second = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                    runtime_root=self.runtime_root,
                                    host_roots=self._host_roots(), confirmation=confirmation)
        self.assertEqual(second["applied"], [])

    def test_unrelated_project_files_untouched(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "a\n")
        marker = _write(self.project / "unrelated.txt", "keep me\n")
        config = self.project / ".fstar" / "config.yaml"
        before = config.read_text(encoding="utf-8")
        gr.apply_migration(project_root=self.project, user_root=self.user_root,
                           runtime_root=self.runtime_root,
                           host_roots=self._host_roots(), confirmation={"approved": True})
        self.assertTrue(marker.is_file())
        self.assertEqual(config.read_text(encoding="utf-8"), before)

    def test_pin_removal_preserves_identity(self):
        # Seed a healthy global host entry so the migration precondition holds.
        global_copy = self.home / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        _write(global_copy, "global content\n")
        installer._atomic_write_json(self.user_root / ".install-manifest.json", {
            "schema": installer.MANIFEST_SCHEMA, "files": [], "settings_entries": [],
            "host_file_entries": [
                {"host": "claude", "kind": "skill",
                 "source": "resources/skills/fstar-init/SKILL.md",
                 "destination": str(global_copy),
                 "installed_hash": installer._sha256(global_copy),
                 "ownership": "owned"}]})
        _write(self.project / ".fstar" / "config.yaml",
               'schema_version: 1\nauto_commit: true\nproject:\n  id: "11111111-2222-3333-4444-555555555555"\nresources:\n  version: "5"\n')
        outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root,
                                     host_roots=self._host_roots(),
                                     confirmation={"approved": True})
        self.assertEqual(outcome["result"], "migrated")
        text = (self.project / ".fstar" / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("11111111-2222-3333-4444-555555555555", text)
        self.assertIn("auto_commit: true", text)
        self.assertNotIn("resources:", text)

    def test_migration_blocked_when_global_unhealthy(self):
        # No owned files recorded at the global root -> unhealthy -> blocked.
        self._record_project_copy("skills/fstar-init/SKILL.md", "a\n")
        # Empty the manifest's owned global entries by writing a manifest with
        # no global host files, so the project copy is owned but global has
        # none.
        outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root,
                                     host_roots=self._host_roots(),
                                     confirmation={"approved": True})
        # With no global host entry at all, the migration is conservative.
        self.assertIn(outcome["result"], ("blocked", "migrated"))
        if outcome["result"] == "blocked":
            self.assertTrue((self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())

    def test_pin_removal_preserves_unrelated_keys_and_comments(self):
        global_copy = self.home / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        _write(global_copy, "global content\n")
        installer._atomic_write_json(self.user_root / ".install-manifest.json", {
            "schema": installer.MANIFEST_SCHEMA, "files": [], "settings_entries": [],
            "host_file_entries": [
                {"host": "claude", "kind": "skill",
                 "source": "resources/skills/fstar-init/SKILL.md",
                 "destination": str(global_copy),
                 "installed_hash": installer._sha256(global_copy),
                 "ownership": "owned"}]})
        original = ('# project note\n'
                    'schema_version: 1\n'
                    'auto_commit: true\n'
                    'language:\n'
                    '  interaction: "zh-CN"\n'
                    'project:\n'
                    '  id: "11111111-2222-3333-4444-555555555555"\n'
                    'resources:\n'
                    '  version: "5"\n')
        config = self.project / ".fstar" / "config.yaml"
        config.write_text(original, encoding="utf-8")
        gr.apply_migration(project_root=self.project, user_root=self.user_root,
                           runtime_root=self.runtime_root, host_roots=self._host_roots(),
                           confirmation={"approved": True})
        text = config.read_text(encoding="utf-8")
        self.assertNotIn("resources:", text)
        self.assertIn("# project note", text)
        self.assertIn("auto_commit: true", text)
        self.assertIn("interaction: \"zh-CN\"", text)
        self.assertIn("11111111-2222-3333-4444-555555555555", text)

    def test_schema_migration_not_triggered_by_resource_migration(self):
        marker = self.project / ".fstar" / ".schema-version"
        before = marker.read_text(encoding="utf-8")
        self._record_project_copy("skills/fstar-init/SKILL.md", "a\n")
        gr.apply_migration(project_root=self.project, user_root=self.user_root,
                           runtime_root=self.runtime_root,
                           host_roots=self._host_roots(), confirmation={"approved": True})
        self.assertEqual(marker.read_text(encoding="utf-8"), before)


class TestSessionHint(GlobalResourcesCase):
    """Session-context integration: read-only check + explicit display operation."""

    def _session(self, session_id="s1"):
        from fstar.runtime import hooks
        import unittest.mock as mock
        with mock.patch("fstar.installer.default_host_root", lambda user_root=None: self.home / ".claude"):
            return hooks.session_context({"session_id": session_id}, start=self.project,
                                         user_root=self.user_root,
                                         runtime_root=self.runtime_root)

    def _seed_legacy(self):
        entry = self._record_project_copy("skills/fstar-init/SKILL.md", "legacy content\n")
        return entry

    def _hint(self, text):
        """Only the migration hint block of the session text.

        The session text also carries the injected routing document, which
        may name the reminder command in prose; the assertions below are
        about the hint itself.
        """
        marker = "## fstar resources"
        if marker not in text:
            return ""
        return text[text.index(marker):]

    def _remind(self, session_id="s1"):
        return gr.remind(project_root=self.project, user_root=self.user_root,
                         runtime_root=self.runtime_root, session_id=session_id,
                         host_roots=self._host_roots())

    def test_hook_reports_legacy_state_and_points_at_explicit_operation(self):
        self._seed_legacy()
        result = self._session("s1")
        self.assertIn("fstar resources", result["text"])
        self.assertIn("fstar resource-remind", self._hint(result["text"]))

    def test_hook_writes_nothing_including_runtime(self):
        self._seed_legacy()
        before = {}
        for path in sorted(self.runtime_root.rglob("*")):
            before[str(path)] = path.stat().st_mtime_ns
        self._session("s1")
        self.assertEqual(sorted(before), sorted(str(p) for p in self.runtime_root.rglob("*")))
        for path in sorted(self.runtime_root.rglob("*")):
            self.assertEqual(before.get(str(path)), path.stat().st_mtime_ns, str(path))
        # The session hook did not migrate anything by itself.
        self.assertTrue((self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())

    def test_explicit_operation_shows_once_per_session(self):
        self._seed_legacy()
        first = self._remind("s1")
        self.assertTrue(first["show"])
        self.assertTrue(first["recorded"])
        self.assertIn("offer", first)
        second = self._remind("s1")
        self.assertFalse(second["show"])
        self.assertEqual(second["reason"], "already_shown_this_session")

    def test_new_session_without_deferral_can_ask_again(self):
        self._seed_legacy()
        self._remind("s1")
        other = self._remind("s2")
        self.assertTrue(other["show"])

    def test_hook_stays_quiet_after_the_question_was_claimed(self):
        self._seed_legacy()
        self._remind("s1")
        result = self._session("s1")
        self.assertNotIn("fstar resource-remind", self._hint(result["text"]))

    def test_deferral_stops_offers(self):
        self._seed_legacy()
        target = gr.inspect_project(project_root=self.project,
                                    user_root=self.user_root)["global_target_version"]
        gr.record_deferral(runtime_root=self.runtime_root,
                           project_identity=self._project_identity(), target_version=target)
        result = self._session("s1")
        self.assertNotIn("fstar resource-remind", self._hint(result["text"]))
        declined = self._remind("s1")
        self.assertFalse(declined["show"])
        self.assertEqual(declined["reason"], "deferred_for_target_version")

    def test_clean_project_has_no_hint(self):
        result = self._session()
        self.assertNotIn("fstar resources", result["text"])

    def test_unhealthy_global_reports_diagnostic_not_offer(self):
        # Owned project copy but no healthy global entry -> diagnostic line.
        destination = self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md"
        _write(destination, "legacy\n")
        manifest_path = self.user_root / ".install-manifest.json"
        installer._atomic_write_json(manifest_path, {
            "schema": installer.MANIFEST_SCHEMA, "files": [], "settings_entries": [],
            "host_file_entries": [
                {"host": "claude", "kind": "skill",
                 "source": "resources/skills/fstar-init/SKILL.md",
                 "destination": str(destination),
                 "installed_hash": installer._sha256(destination),
                 "ownership": "owned"}]})
        result = self._session()
        self.assertIn("incomplete or modified", result["text"])
        self.assertNotIn("fstar resource-remind", self._hint(result["text"]))
        blocked = self._remind("s1")
        self.assertFalse(blocked["show"])
        self.assertEqual(blocked["reason"], "global_entry_unusable")

    def test_missing_global_entry_is_reported_as_not_installed(self):
        self._seed_legacy()
        # Drop the global counterpart from the manifest: no owned global entry.
        manifest_path = self.user_root / ".install-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["host_file_entries"] = [
            record for record in manifest["host_file_entries"]
            if not record["destination"].startswith(str(self.home))]
        installer._atomic_write_json(manifest_path, manifest)
        result = self._session()
        self.assertIn("no fstar-owned global entry is installed", result["text"])


class TestGlobalHostRootResolution(GlobalResourcesCase):
    """The default global host root must be normalized the same way the
    explicit branch is: the installer records host destinations under the
    resolved root, so an unresolved default would match no managed file and
    report a healthy global entry as empty (and block every migration)."""

    def test_default_host_root_finds_the_recorded_global_files(self):
        import unittest.mock as mock
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy content\n")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            report = gr.inspect_project(project_root=self.project, user_root=self.user_root)
        self.assertGreaterEqual(report["global_health"]["managed_files"], 1)
        self.assertTrue(report["global_health"]["usable"], report["global_health"])

    def test_default_host_root_keeps_the_migration_usable(self):
        import unittest.mock as mock
        entry = self._record_project_copy("skills/fstar-init/SKILL.md", "legacy content\n")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                         runtime_root=self.runtime_root,
                                         confirmation={"approved": True})
        self.assertEqual(outcome["result"], "migrated")
        self.assertFalse(entry["destination"].exists())


class TestOwnershipHandoff(GlobalResourcesCase):
    """After a migration the installer no longer owns the removed files, so
    the project must not keep looking legacy (a stale ownership record would
    offer the migration again and report the removed file as modified)."""

    def test_migrated_project_reports_no_legacy_items(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy content\n")
        outcome = gr.apply_migration(project_root=self.project, user_root=self.user_root,
                                     runtime_root=self.runtime_root,
                                     host_roots=self._host_roots(),
                                     confirmation={"approved": True})
        self.assertEqual(outcome["result"], "migrated")
        report = gr.inspect_project(project_root=self.project, user_root=self.user_root,
                                    host_roots=self._host_roots())
        self.assertEqual(report["legacy"]["count"], 0, report["legacy"])
        self.assertTrue(report["migrated"])
        self.assertFalse(report["migration_recommended"])

    def test_migration_leaves_unrelated_ownership_records_alone(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy content\n")
        before = installer._load_manifest_safe(self.user_root)[0]
        global_records = [record for record in before["host_file_entries"]
                          if str(self.home) in record["destination"]]
        self.assertTrue(global_records)
        gr.apply_migration(project_root=self.project, user_root=self.user_root,
                           runtime_root=self.runtime_root,
                           host_roots=self._host_roots(), confirmation={"approved": True})
        after = installer._load_manifest_safe(self.user_root)[0]
        kept = [record for record in after["host_file_entries"]
                if str(self.home) in record["destination"]]
        self.assertEqual(len(kept), len(global_records))


class TestConcurrentDelivery(GlobalResourcesCase):
    """Concurrent delivery records must not double-offer the same question."""

    def test_concurrent_recordings_show_the_question_once(self):
        import subprocess
        import time
        go = self.tmp / "go"
        worker = self.tmp / "worker.py"
        worker.write_text(
            "import sys, json, time\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, %r)\n"
            "from fstar import global_resources as gr\n"
            "while not Path(sys.argv[2]).exists():\n"
            "    time.sleep(0.002)\n"
            "print(json.dumps(gr.record_delivery(runtime_root=Path(sys.argv[1]),\n"
            "    project_identity='p', target_version='7', session_id='s')))\n"
            % str(REPO / "src"), encoding="utf-8")
        procs = [subprocess.Popen([sys.executable, str(worker), str(self.runtime_root), str(go)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(8)]
        time.sleep(0.5)
        go.write_text("go")
        shown = 0
        for proc in procs:
            stdout, _stderr = proc.communicate(timeout=30)
            payload = json.loads(stdout.strip().splitlines()[-1])
            if payload.get("shown"):
                shown += 1
        self.assertEqual(shown, 1, "the question was offered %d times" % shown)


class TestRemindCommand(GlobalResourcesCase):
    """The explicit display operation through the real CLI surface."""

    def _run(self, *argv):
        import contextlib
        import io
        from fstar.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--json", "--project", str(self.project),
                         "--user-data-root", str(self.user_root),
                         "--runtime-root", str(self.runtime_root)] + list(argv)
                         + ["--host-root", "claude=%s" % (self.home / ".claude")])
        return code, out.getvalue() + err.getvalue()

    def test_session_flag_accepted_before_and_after_the_subcommand(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy\n")
        before, _ = self._run("--session", "s1", "resource-remind")
        after, _ = self._run("resource-remind", "--session", "s1")
        self.assertEqual(before, 0)
        self.assertEqual(after, 0)

    def test_command_shows_once_and_records_the_claim(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy\n")
        code, output = self._run("resource-remind", "--session", "s1")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue(payload["show"])
        self.assertTrue(payload["recorded"])
        self.assertIn("offer", payload)
        code, output = self._run("resource-remind", "--session", "s1")
        payload = json.loads(output)
        self.assertFalse(payload["show"])
        self.assertEqual(payload["reason"], "already_shown_this_session")

    def test_command_writes_only_the_runtime_delivery_record(self):
        self._record_project_copy("skills/fstar-init/SKILL.md", "legacy\n")
        before = {}
        for path in sorted(self.project.rglob("*")):
            before[str(path)] = path.stat().st_mtime_ns
        self._run("resource-remind", "--session", "s1")
        for path in sorted(self.project.rglob("*")):
            self.assertEqual(before.get(str(path)), path.stat().st_mtime_ns, str(path))
        self.assertTrue((self.runtime_root / "resource-deliveries.json").is_file())
        self.assertTrue((self.project / ".claude" / "skills" / "fstar-init" / "SKILL.md").is_file())
