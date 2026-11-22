"""Magpie optional integration tests (P-003/R-004).

Every test uses fakes and isolated temporary roots: the real Magpie app is
never discovered (PATH-independent discovery is injected) and never executed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fstar import magpie  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class MagpieCase(unittest.TestCase):
    def setUp(self) -> None:
        import shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="fstar-magpie-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.user_root = self.tmp / "user" / ".fstar"
        self.user_root.mkdir(parents=True)
        self.skills_root = self.tmp / "bundle" / "skills"
        self.agents_source = self.tmp / "home" / ".agents" / "skills"

    def _fake_binary(self, *, fail: bool = False, hang: bool = False, version: str = "0.1.4582",
                     instructions: str = "") -> Path:
        """A real executable standing in for the Magpie CLI (never the app).

        It understands the public commands fstar uses: ``--version``,
        ``library skill hand-over <name...>``, ``library instructions`` and
        ``library instructions set <file>``.
        """
        binary = self.tmp / "fake bin" / "magpie"  # space in path exercises argv passing
        binary.parent.mkdir(parents=True, exist_ok=True)
        state = self.tmp / "magpie-state"
        state.mkdir(parents=True, exist_ok=True)
        instructions_file = state / "instructions.md"
        instructions_file.write_text(instructions, encoding="utf-8")
        if hang:
            body = "import time; time.sleep(60)\n"
        elif fail:
            body = ("import sys\n"
                    "if sys.argv[1:] == ['--version']:\n"
                    "    print('9.9.9999'); sys.exit(0)\n"
                    "sys.exit(3)\n")
        else:
            body = ("import sys, pathlib\n"
                    "args = sys.argv[1:]\n"
                    "state = pathlib.Path(%r)\n"
                    "instructions = state / 'instructions.md'\n"
                    "if args == ['--version']:\n"
                    "    print(%r); sys.exit(0)\n"
                    "if len(args) >= 4 and args[:3] == ['library', 'skill', 'hand-over']:\n"
                    "    print('handed over ' + ' '.join(args[3:])); sys.exit(0)\n"
                    "if args == ['library', 'instructions']:\n"
                    "    sys.stdout.write(instructions.read_text() if instructions.is_file() else '')\n"
                    "    sys.exit(0)\n"
                    "if len(args) == 4 and args[:3] == ['library', 'instructions', 'set']:\n"
                    "    instructions.write_text(pathlib.Path(args[3]).read_text()); print('ok'); sys.exit(0)\n"
                    "sys.exit(2)\n" % (str(state), version))
        binary.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def _stage_skill(self, name: str, content: str = "fstar skill\n") -> Path:
        return _write(self.skills_root / name / "SKILL.md", content)


class TestDiscovery(MagpieCase):
    def setUp(self) -> None:
        super().setUp()
        # The suite-wide guard points the binary override at a path that does
        # not exist, so the real app stays unreachable; these tests exercise
        # the discovery rules themselves.
        self._previous = os.environ.pop(magpie.BINARY_ENV, None)
        self.addCleanup(self._restore_binary)

    def _restore_binary(self) -> None:
        if self._previous is None:
            os.environ.pop(magpie.BINARY_ENV, None)
        else:
            os.environ[magpie.BINARY_ENV] = self._previous

    def test_missing_binary_returns_none(self):
        self.assertIsNone(magpie.default_discovery(home=self.tmp / "empty-home"))

    def test_fake_app_location_found_under_injected_home(self):
        binary = self.tmp / "home" / "Applications" / "magpie.app" / "Contents" / "MacOS" / "magpie"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        self.assertEqual(magpie.default_discovery(home=self.tmp / "home"), str(binary))

    def test_real_home_not_scanned_when_home_injected(self):
        # With an injected (empty) home, the real /Applications app must not
        # leak into discovery.
        self.assertIsNone(magpie.default_discovery(home=self.tmp / "empty-home"))

    def test_suite_guard_keeps_the_real_app_unreachable(self):
        # The package guard in tests/__init__.py must keep every other test
        # away from the real Magpie app.
        os.environ[magpie.BINARY_ENV] = os.path.join(tempfile.gettempdir(), "fstar-no-magpie-binary")
        self.assertIsNone(magpie.default_discovery())


class TestProbe(MagpieCase):
    def test_probe_success(self):
        binary = self._fake_binary()
        status = magpie.probe(binary=str(binary))
        self.assertTrue(status.available)
        self.assertEqual(status.version, "0.1.4582")

    def test_probe_failure(self):
        binary = self._fake_binary(fail=False)
        status = magpie.probe(binary=str(binary), runner=lambda argv, timeout: (1, "", "boom"))
        self.assertFalse(status.available)
        self.assertIn("exit 1", status.reason)

    def test_probe_timeout(self):
        status = magpie.probe(binary="whatever",
                              runner=self._raising_runner_timeout)
        self.assertFalse(status.available)
        self.assertIn("timed out", status.reason)

    def _raising_runner_timeout(self, argv, timeout):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)


class TestIntegrate(MagpieCase):
    def _run(self, binary=None, handover=None, runner=None):
        # The real hand-over path runs unless a handover stub is injected;
        # a fake binary whose hand-over fails exercises the degraded path.
        return magpie.integrate(skills_root=self.skills_root, agents_source=self.agents_source,
                                binary=str(binary) if binary else "unused",
                                user_root=self.user_root,
                                discover=lambda: str(binary) if binary else None,
                                runner=runner or (lambda argv, timeout: (0, "ok", "")),
                                handover=handover or (None if runner is not None
                                                      else magpie._public_handover),
                                probe_status=magpie.MagpieStatus(True, str(binary), "0.1.4582") if binary
                                else magpie.MagpieStatus(False, None, None, "magpie binary not found"))

    def test_missing_magpie_is_a_clean_skip(self):
        report = self._run(binary=None)
        self.assertEqual(report["status"], "skipped")

    def test_changed_content_is_re_handed_over_under_the_additive_model(self):
        # The library hand-over is additive: a new fstar version re-stages
        # into fstar's own staging copy and hands the changed content over.
        import shutil
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._run(binary=binary)
        shutil.rmtree(self.agents_source / "fstar-init")
        self._stage_skill("fstar-init", "fstar skill, new version\n")
        report = self._run(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "handed_over")
        self.assertTrue((self.agents_source / "fstar-init" / "SKILL.md").exists())
        self.assertEqual(report["status"], "integrated")

    def test_injected_discovery_is_used_when_no_binary_is_given(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        report = magpie.integrate(skills_root=self.skills_root, agents_source=self.agents_source,
                                  binary=None, user_root=self.user_root,
                                  discover=lambda: str(binary),
                                  runner=magpie.default_runner)
        self.assertEqual(report["status"], "integrated")
        self.assertEqual(report["binary"], str(binary))
        self.assertTrue((self.agents_source / "fstar-init" / "SKILL.md").is_file())

    def test_discovery_that_finds_nothing_is_a_clean_skip(self):
        self._stage_skill("fstar-init")
        report = magpie.integrate(skills_root=self.skills_root, agents_source=self.agents_source,
                                  binary=None, user_root=self.user_root,
                                  discover=lambda: None,
                                  runner=magpie.default_runner)
        self.assertEqual(report["status"], "skipped")
        self.assertFalse((self.agents_source / "fstar-init" / "SKILL.md").exists())

    def test_successful_handover(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        report = self._run(binary=binary)
        self.assertEqual(report["status"], "integrated")
        self.assertEqual(report["skills"][0]["action"], "handed_over")
        self.assertTrue((self.agents_source / "fstar-init" / "SKILL.md").is_file())
        record = json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))
        self.assertEqual(record["skills"]["fstar-init"]["library"], "handed_over")

    def test_idempotent_repeat(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._run(binary=binary)
        second = self._run(binary=binary)
        self.assertEqual(second["skills"][0]["action"], "already_integrated")

    def test_user_conflict_not_overwritten(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        _write(self.agents_source / "fstar-init" / "SKILL.md", "user's own skill\n")
        report = self._run(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "conflict")
        self.assertEqual((self.agents_source / "fstar-init" / "SKILL.md").read_text(encoding="utf-8"),
                         "user's own skill\n")

    def test_handover_failure_degrades_without_losing_staging(self):
        binary = self._fake_binary(fail=True)
        self._stage_skill("fstar-init")
        report = self._run(binary=binary, runner=magpie.default_runner)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["skills"][0]["action"], "staged_unconfirmed")
        # The staged copy remains for a later retry; the failure did not
        # abort the whole integration report.
        self.assertTrue((self.agents_source / "fstar-init" / "SKILL.md").is_file())

    def test_handover_timeout_reports(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        def timing_out_handover(names, binary=None, runner=None):
            return {"ok": False, "reason": "hand-over timed out"}
        report = magpie.integrate(skills_root=self.skills_root, agents_source=self.agents_source,
                                  binary=str(binary), user_root=self.user_root,
                                  discover=lambda: str(binary),
                                  runner=lambda argv, timeout: (0, "ok", ""),
                                  handover=timing_out_handover)
        self.assertEqual(report["skills"][0]["action"], "staged_unconfirmed")

    def test_space_in_binary_path(self):
        binary = self._fake_binary()  # path already contains a space ("fake bin")
        self._stage_skill("fstar-init")
        report = magpie.integrate(skills_root=self.skills_root, agents_source=self.agents_source,
                                  binary=str(binary), user_root=self.user_root,
                                  runner=magpie.default_runner)
        self.assertEqual(report["status"], "integrated")

    def test_partial_success_reports_per_skill(self):
        binary = self._fake_binary(fail=True)
        self._stage_skill("fstar-init")
        self._stage_skill("fstar-plan")
        _write(self.agents_source / "fstar-plan" / "SKILL.md", "user's plan skill\n")
        report = self._run(binary=binary, runner=magpie.default_runner)
        actions = {item["skill"]: item["action"] for item in report["skills"]}
        self.assertEqual(actions["fstar-plan"], "conflict")
        self.assertEqual(actions["fstar-init"], "staged_unconfirmed")
        self.assertEqual(report["status"], "degraded")

    def test_uninstall_keeps_magpie_owned_and_modified(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._run(binary=binary)
        # Simulate a second skill that was staged but never confirmed.
        record = json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))
        staged = _write(self.agents_source / "fstar-plan" / "SKILL.md", "staged plan\n")
        record["skills"]["fstar-plan"] = {"sha256": magpie.__dict__ and __import__("hashlib").sha256(b"staged plan\n").hexdigest(),
                                          "ownership": "staged"}
        (self.user_root / "magpie-integration.json").write_text(json.dumps(record), encoding="utf-8")
        # A modified staged skill must be kept.
        staged.write_text("user touched\n", encoding="utf-8")
        outcome = magpie.uninstall_local(user_root=self.user_root, agents_source=self.agents_source)
        self.assertTrue(any(item["skill"] == "fstar-init" and "Magpie" in item["reason"] for item in outcome["kept"]))
        kept_modified = [item for item in outcome["kept"] if item["skill"] == "fstar-plan"]
        self.assertTrue(kept_modified)
        self.assertTrue(staged.is_file())


import json  # noqa: E402

if __name__ == "__main__":
    unittest.main()


class TestSoftRouter(MagpieCase):
    """route_skills: the additive Magpie library distribution (R-003 rework).

    Native copies are the installer's business and always exist; every
    per-skill result here describes ONLY the library distribution.
    """

    def _route(self, *, binary=None, **kwargs):
        return magpie.route_skills(skills_root=self.skills_root,
                                   agents_source=self.agents_source,
                                   user_root=self.user_root,
                                   binary=str(binary) if binary else None,
                                   discover=lambda: str(binary) if binary else None,
                                   runner=magpie.default_runner,
                                   **kwargs)

    def _record(self) -> dict:
        return json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))

    def test_magpie_present_hands_the_skill_over_to_the_library(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        report = self._route(binary=binary)
        self.assertEqual(report["status"], "handed_over")
        self.assertEqual(report["library"]["fstar-init"], "handed_over")
        self.assertEqual(report["skills"][0]["action"], "handed_over")
        entry = self._record()["skills"]["fstar-init"]
        self.assertEqual(entry["library"], "handed_over")
        self.assertNotIn("ownership", entry)

    def test_a_failed_hand_over_reports_the_missing_library_share_only(self):
        binary = self._fake_binary(fail=True)
        self._stage_skill("fstar-init")
        self._stage_skill("fstar-plan")
        report = self._route(binary=binary)
        actions = {item["skill"]: item["action"] for item in report["skills"]}
        self.assertEqual(actions["fstar-init"], "handover_failed")
        self.assertEqual(actions["fstar-plan"], "handover_failed")
        self.assertEqual(report["library"]["fstar-init"], "handover_failed")
        self.assertEqual(report["status"], "degraded")
        # The staged copy is removed again so nothing half-handed-over
        # lingers; the native copy (installer-owned) is not this module's
        # concern and is never implied to be missing.
        self.assertFalse((self.agents_source / "fstar-init" / "SKILL.md").exists())
        self.assertEqual(self._record()["skills"]["fstar-init"]["library"], "handover_failed")

    def test_magpie_absent_reports_a_clean_absence(self):
        self._stage_skill("fstar-init")
        report = self._route(binary=None)
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["library"]["fstar-init"], "absent")
        self.assertEqual(report["skills"][0]["action"], "magpie_absent")
        self.assertFalse((self.user_root / "magpie-integration.json").exists())

    def test_a_dry_run_changes_nothing(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        report = self._route(binary=binary, dry_run=True)
        self.assertEqual(report["status"], "preview")
        self.assertEqual(report["skills"][0]["action"], "would_hand_over")
        self.assertFalse((self.agents_source / "fstar-init" / "SKILL.md").exists())
        self.assertFalse((self.user_root / "magpie-integration.json").exists())

    def test_repeating_the_route_is_idempotent(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._route(binary=binary)
        second = self._route(binary=binary)
        self.assertEqual(second["skills"][0]["action"], "already_integrated")
        self.assertEqual(second["library"]["fstar-init"], "handed_over")

    def test_a_changed_fingerprint_re_hands_the_skill_over(self):
        # With the additive model the library update is no longer blocked:
        # new content is re-staged and re-handed-over through the public CLI.
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._route(binary=binary)
        self._stage_skill("fstar-init", "fstar skill, new version\n")
        # The first hand-over left the staged copy behind; the re-stage of
        # changed content over our own staged copy is allowed (it is ours).
        report = self._route(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "handed_over")
        entry = self._record()["skills"]["fstar-init"]
        import hashlib
        self.assertEqual(entry["sha256"],
                         hashlib.sha256(b"fstar skill, new version\n").hexdigest())

    def test_a_handed_over_skill_survives_a_missing_magpie_informationally(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._route(binary=binary)
        # Magpie disappears: informational only, never a fallback request.
        report = self._route(binary=None)
        self.assertEqual(report["skills"][0]["action"], "library_unreachable")
        self.assertEqual(report["library"]["fstar-init"], "handed_over")
        self.assertIn("unaffected", report["skills"][0]["reason"])
        self.assertNotIn("--native-only", report["skills"][0]["reason"])
        self.assertEqual(report["status"], "skipped")

    def test_native_only_never_consults_magpie(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        report = self._route(binary=binary, native_only=True)
        self.assertEqual(report["status"], "native_only")
        self.assertFalse(report["magpie"]["consulted"])
        self.assertEqual(report["library"]["fstar-init"], "absent")
        self.assertFalse((self.agents_source / "fstar-init" / "SKILL.md").exists())
        self.assertFalse((self.user_root / "magpie-integration.json").exists())

    def test_native_only_after_a_hand_over_leaves_the_record_untouched(self):
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._route(binary=binary)
        self._route(binary=binary, native_only=True)
        entry = self._record()["skills"]["fstar-init"]
        # --native-only skips the hand-over; it does not rewrite history.
        self.assertEqual(entry["library"], "handed_over")

    def test_a_legacy_ownership_magpie_record_is_read_as_handed_over(self):
        # A record written by the retired ownership model.
        import hashlib
        payload = b"fstar skill\n"
        _write(self.user_root / "magpie-integration.json", json.dumps({
            "schema": magpie.INTEGRATION_SCHEMA,
            "skills": {"fstar-init": {"sha256": hashlib.sha256(payload).hexdigest(),
                                      "ownership": "magpie"}}}))
        self._stage_skill("fstar-init")
        binary = self._fake_binary()
        # Same fingerprint: recognized as already handed over, no re-stage.
        report = self._route(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "already_integrated")
        # Magpie gone: informational, native unaffected.
        report = self._route(binary=None)
        self.assertEqual(report["skills"][0]["action"], "library_unreachable")

    def test_a_legacy_ownership_magpie_record_with_new_content_re_hands_over(self):
        import hashlib
        _write(self.user_root / "magpie-integration.json", json.dumps({
            "schema": magpie.INTEGRATION_SCHEMA,
            "skills": {"fstar-init": {"sha256": hashlib.sha256(b"old\n").hexdigest(),
                                      "ownership": "magpie"}}}))
        self._stage_skill("fstar-init")
        binary = self._fake_binary()
        report = self._route(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "handed_over")
        entry = self._record()["skills"]["fstar-init"]
        self.assertEqual(entry["library"], "handed_over")
        self.assertNotIn("ownership", entry)


class TestSharedInstructions(MagpieCase):
    """The shared library instructions channel (R-004)."""

    def _share(self, binary, **kwargs):
        return magpie.share_instructions(binary=str(binary), user_root=self.user_root,
                                         runner=magpie.default_runner, **kwargs)

    def test_an_empty_library_receives_the_workflow_entry(self):
        binary = self._fake_binary()
        result = self._share(binary)
        self.assertEqual(result["action"], "written")
        published = (self.tmp / "magpie-state" / "instructions.md").read_text(encoding="utf-8")
        self.assertIn("fstar workflow", published)
        # Natural language, not a command dump.
        self.assertNotIn("fstar install", published)

    def test_user_instructions_are_kept_and_reported_as_a_conflict(self):
        binary = self._fake_binary(instructions="my own notes\n")
        result = self._share(binary)
        self.assertEqual(result["action"], "conflict")
        published = (self.tmp / "magpie-state" / "instructions.md").read_text(encoding="utf-8")
        self.assertEqual(published, "my own notes\n")

    def test_our_own_instructions_are_replaced_on_a_second_run(self):
        binary = self._fake_binary()
        self._share(binary)
        result = self._share(binary)
        self.assertEqual(result["action"], "updated")

    def test_an_unavailable_capability_is_skipped(self):
        binary = self._fake_binary(fail=True)
        result = self._share(binary)
        self.assertEqual(result["action"], "unavailable")
        self.assertTrue(result["reason"])

    def test_a_dry_run_writes_nothing(self):
        binary = self._fake_binary()
        result = self._share(binary, write=False)
        self.assertEqual(result["action"], "would_write")
        published = (self.tmp / "magpie-state" / "instructions.md").read_text(encoding="utf-8")
        self.assertEqual(published, "")


class TestInstallMagpieOption(MagpieCase):
    """`fstar install`: the Magpie soft router, isolated and never fatal."""

    def _install(self, *, binary, agents_source, user_root, extra=()):
        import contextlib
        import io
        from fstar.cli import main

        previous = {key: os.environ.get(key) for key in (magpie.BINARY_ENV, magpie.AGENTS_SOURCE_ENV)}
        os.environ[magpie.BINARY_ENV] = str(binary)
        os.environ[magpie.AGENTS_SOURCE_ENV] = str(agents_source)
        self.addCleanup(self._restore_env, previous)
        out, err = io.StringIO(), io.StringIO()
        argv = ["--json", "--user-data-root", str(user_root),
                "install", "--host", "claude",
                "--host-root", "claude=%s" % (self.tmp / "host" / "claude")] + list(extra)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue() + err.getvalue()

    def _restore_env(self, previous: dict) -> None:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_install_hands_the_skills_over_to_magpie(self):
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["status"], "handed_over")
        self.assertTrue(any(item["action"] == "handed_over" for item in payload["magpie"]["skills"]))
        # The library hand-over is recorded in its own field.
        self.assertTrue((self.user_root / "magpie-integration.json").is_file())
        record = json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))
        self.assertEqual(record["skills"]["fstar-init"]["library"], "handed_over")

    def test_native_copies_exist_even_when_skills_are_handed_over(self):
        # R-003 rework: /fstar-* slash commands are a client feature supplied
        # only by the host's native skills directory, so the native copies are
        # always installed alongside the library hand-over.
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root)
        self.assertEqual(code, 0)
        host_skills = self.tmp / "host" / "claude" / "skills"
        for skill in ("fstar-init", "fstar-plan", "fstar-execute"):
            self.assertTrue((host_skills / skill / "SKILL.md").is_file(),
                            "missing native copy for %s" % skill)
        self.assertEqual(len(list(host_skills.glob("fstar-*/SKILL.md"))), 11)
        # Role cards are not a Magpie capability: they stay native too.
        self.assertTrue((self.tmp / "host" / "claude" / "agents" / "fstar-implement.md").is_file())

    def test_a_failed_hand_over_leaves_the_native_copy_installed(self):
        binary = self._fake_binary(fail=True)
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["status"], "degraded")
        # The native install still happened, in full.
        host_skills = self.tmp / "host" / "claude" / "skills"
        self.assertEqual(len(list(host_skills.glob("fstar-*/SKILL.md"))), 11)
        # The library share is reported missing for every skill.
        self.assertEqual(set(payload["magpie"]["library"].values()), {"handover_failed"})
        record = json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))
        self.assertEqual(record["skills"]["fstar-init"]["library"], "handover_failed")

    def test_install_with_native_only_never_touches_magpie(self):
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root, extra=["--native-only"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["status"], "native_only")
        self.assertFalse(payload["magpie"]["magpie"]["consulted"])
        self.assertEqual(len(list((self.tmp / "host" / "claude" / "skills").glob("fstar-*/SKILL.md"))), 11)
        self.assertFalse(self.agents_source.exists())
        self.assertFalse((self.user_root / "magpie-integration.json").exists())

    def test_a_magpie_gone_after_a_hand_over_leaves_the_native_install_usable(self):
        binary = self._fake_binary()
        self._install(binary=binary, agents_source=self.agents_source,
                      user_root=self.user_root)
        # Magpie disappears: the native skills stay fully usable; doctor only
        # reports an informational diagnostic.
        import contextlib
        import io
        from fstar.cli import main
        previous = os.environ[magpie.BINARY_ENV]
        os.environ[magpie.BINARY_ENV] = str(self.tmp / "nonexistent-magpie")
        self.addCleanup(os.environ.__setitem__, magpie.BINARY_ENV, previous)
        argv = ["--json", "--user-data-root", str(self.user_root), "doctor"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(argv)
        report = json.loads(out.getvalue() + err.getvalue())
        diagnostic = [item for item in report["diagnostics"]
                     if item["code"] == "MAGPIE_LIBRARY_UNREACHABLE"]
        self.assertEqual(len(diagnostic), 1)
        self.assertEqual(diagnostic[0].get("severity"), "info")
        # Informational only: the report is still healthy.
        self.assertTrue(report["healthy"])
        # Native copies untouched.
        self.assertEqual(len(list((self.tmp / "host" / "claude" / "skills").glob("fstar-*/SKILL.md"))), 11)

    def test_install_publishes_the_shared_workflow_entry(self):
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["instructions"]["action"], "written")
        published = (self.tmp / "magpie-state" / "instructions.md").read_text(encoding="utf-8")
        self.assertIn("fstar workflow", published)

    def test_a_dry_run_hands_nothing_over(self):
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root, extra=["--dry-run"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["magpie"]["skills"][0]["action"], "would_hand_over")
        self.assertFalse(self.agents_source.exists())
        self.assertFalse((self.user_root / "magpie-integration.json").exists())


class TestDistributionAdapter(MagpieCase):
    """S-5: the Magpie distribution through the shared capability adapter.

    The adapter's probe/handshake are read-only (the fake binary is only
    invoked for --version by the caller-supplied status); the actual
    hand-over still happens exclusively through route_skills, reached via
    the injected route callable exactly as the installer wires it.
    """

    def _record(self) -> dict:
        return json.loads((self.user_root / "magpie-integration.json").read_text(encoding="utf-8"))

    def _adapter(self, binary):
        from fstar.capability_adapters import MagpieDistributionAdapter

        return MagpieDistributionAdapter(
            probe_call=lambda: magpie.probe(binary=str(binary)),
            route=lambda **kwargs: magpie.route_skills(
                skills_root=self.skills_root, agents_source=self.agents_source,
                user_root=self.user_root, binary=str(binary), **kwargs))

    def test_probe_is_available_and_handshake_confirms_distribution(self):
        adapter = self._adapter(self._fake_binary())
        status = adapter.probe()
        self.assertTrue(status.available)
        self.assertEqual(status.capabilities, ["distribution"])
        confirmed = adapter.handshake(["distribution"])
        self.assertTrue(confirmed.available)
        # Read-only: no hand-over happened, no record was written.
        self.assertFalse((self.user_root / "magpie-integration.json").exists())
        self.assertFalse(self.agents_source.exists())

    def test_route_through_the_adapter_hands_skills_over(self):
        adapter = self._adapter(self._fake_binary())
        self._stage_skill("fstar-init")
        report = adapter.route()
        self.assertEqual(report["status"], "handed_over")
        self.assertEqual(report["library"]["fstar-init"], "handed_over")
        self.assertEqual(self._record()["skills"]["fstar-init"]["library"], "handed_over")

    def test_absent_magpie_probe_degrades_to_the_native_fallback(self):
        from fstar.capability_adapters import CapabilityRegistry, CLASS_FALLBACKS

        adapter = self._adapter(self._fake_binary(fail=True))
        registry = CapabilityRegistry({"distribution": adapter})
        result = registry.resolve("distribution")
        # The fake binary still answers --version (availability), but the
        # hand-over fails; the class fallback is what the caller uses.
        self.assertIn(result["fallback"], CLASS_FALLBACKS["distribution"])
        self.assertEqual(result["capabilities"], ["distribution"])
        # Nothing was staged or written during a probe/handshake-only path.
        self.assertFalse((self.user_root / "magpie-integration.json").exists())

    def test_missing_registry_degrades_for_every_class(self):
        from fstar.capability_adapters import default_registry

        report = default_registry().report()
        for name, entry in report["classes"].items():
            self.assertFalse(entry["available"], name)
            self.assertTrue(entry["fallback"], name)
