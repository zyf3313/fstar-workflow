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

    def _fake_binary(self, *, fail: bool = False, hang: bool = False, version: str = "0.1.4380") -> Path:
        """A real executable standing in for the Magpie CLI (never the app)."""
        binary = self.tmp / "fake bin" / "magpie"  # space in path exercises argv passing
        binary.parent.mkdir(parents=True, exist_ok=True)
        if hang:
            body = "import time; time.sleep(60)\n"
        elif fail:
            body = ("import sys\n"
                    "if sys.argv[1:] == ['--version']:\n"
                    "    print('9.9.9999'); sys.exit(0)\n"
                    "sys.exit(3)\n")
        else:
            body = ("import sys\n"
                    "args = sys.argv[1:]\n"
                    "if args == ['--version']:\n"
                    "    print(%r); sys.exit(0)\n"
                    "if len(args) >= 4 and args[:3] == ['library', 'skill', 'hand-over']:\n"
                    "    print('handed over ' + ' '.join(args[3:])); sys.exit(0)\n"
                    "sys.exit(2)\n" % version)
        binary.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def _stage_skill(self, name: str, content: str = "fstar skill\n") -> Path:
        return _write(self.skills_root / name / "SKILL.md", content)


class TestDiscovery(MagpieCase):
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


class TestProbe(MagpieCase):
    def test_probe_success(self):
        binary = self._fake_binary()
        status = magpie.probe(binary=str(binary))
        self.assertTrue(status.available)
        self.assertEqual(status.version, "0.1.4380")

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
                                probe_status=magpie.MagpieStatus(True, str(binary), "0.1.4380") if binary
                                else magpie.MagpieStatus(False, None, None, "magpie binary not found"))

    def test_missing_magpie_is_a_clean_skip(self):
        report = self._run(binary=None)
        self.assertEqual(report["status"], "skipped")

    def test_magpie_managed_skill_is_not_restaged_when_the_content_changes(self):
        # Ownership handoff: Magpie took the skill over (the file left
        # ~/.agents/skills). A new fstar version must not drop a competing
        # copy back in; there is no verified public update path for a
        # handed-over skill, so the update is reported instead.
        import shutil
        binary = self._fake_binary()
        self._stage_skill("fstar-init")
        self._run(binary=binary)
        shutil.rmtree(self.agents_source / "fstar-init")
        self._stage_skill("fstar-init", "fstar skill, new version\n")
        report = self._run(binary=binary)
        self.assertEqual(report["skills"][0]["action"], "magpie_managed_update_required")
        self.assertFalse((self.agents_source / "fstar-init" / "SKILL.md").exists())
        self.assertEqual(report["status"], "degraded")

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
        self.assertEqual(record["skills"]["fstar-init"]["ownership"], "magpie")

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


class TestInstallMagpieOption(MagpieCase):
    """`fstar install --magpie`: optional, opt-in, isolated, never fatal."""

    def _install(self, *, binary, agents_source, user_root, magpie_flag=True):
        import contextlib
        import io
        from fstar.cli import main

        os.environ[magpie.BINARY_ENV] = str(binary)
        os.environ[magpie.AGENTS_SOURCE_ENV] = str(agents_source)
        self.addCleanup(os.environ.pop, magpie.BINARY_ENV, None)
        self.addCleanup(os.environ.pop, magpie.AGENTS_SOURCE_ENV, None)
        out, err = io.StringIO(), io.StringIO()
        argv = ["--json", "--user-data-root", str(user_root),
                "install", "--host", "claude",
                "--host-root", "claude=%s" % (self.tmp / "host" / "claude")] \
                + (["--magpie"] if magpie_flag else [])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_install_with_magpie_hands_over_named_skills(self):
        binary = self._fake_binary()
        user_root = self.user_root
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=user_root)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["status"], "integrated")
        self.assertTrue(any(item["action"] == "handed_over" for item in payload["magpie"]["skills"]))
        # The record lives in the user root, the staged skills in the
        # injected agents source.
        self.assertTrue((user_root / "magpie-integration.json").is_file())

    def test_install_survives_a_failing_magpie(self):
        binary = self._fake_binary(fail=True)
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["magpie"]["status"], "degraded")
        # The base install still happened.
        self.assertTrue((self.tmp / "host" / "claude" / "skills").is_dir())

    def test_install_without_the_flag_never_touches_magpie(self):
        binary = self._fake_binary()
        code, output = self._install(binary=binary, agents_source=self.agents_source,
                                     user_root=self.user_root, magpie_flag=False)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertNotIn("magpie", payload)
        self.assertFalse((self.user_root / "magpie-integration.json").exists())
