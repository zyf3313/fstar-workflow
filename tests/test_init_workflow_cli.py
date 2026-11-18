import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InitWorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.user = self.root / "user"
        self.context = self.root / "context.json"
        (self.project / "README.md").write_text("authority", encoding="utf-8")
        self.context.write_text(json.dumps({"project_summary": "A real project", "topics": [{
            "id": "core", "title": "Core", "applies_to": "src", "read_when": "editing", "path": "README.md"}],
            "authority_refs": [{"title": "Readme", "path": "README.md"}]}), encoding="utf-8")
        self.env = dict(os.environ, HOME=str(self.home), PATH="", PYTHONDONTWRITEBYTECODE="1")
        self.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "fstar", "--json", "--user-data-root", str(self.user),
                               "init", str(self.project), *args], env=self.env, cwd=self.root,
                              capture_output=True, text=True, timeout=60)

    def test_fresh_machine_previews_and_creates_both_roots_once(self):
        preview = self.cli("--dry-run", "--context", str(self.context))
        self.assertEqual(0, preview.returncode, preview.stderr)
        preview = json.loads(preview.stdout)
        self.assertIn("USER_ROOT_CREATED", [w["code"] for w in preview["warnings"]])
        self.assertIn(str((self.user / "config.yaml").resolve()), preview["created"])
        self.assertIn(str((self.project / ".fstar" / "index.md").resolve()), preview["created"])
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse(self.user.exists())

        result = self.cli("--context", str(self.context))
        self.assertEqual(0, result.returncode, result.stderr)
        result = json.loads(result.stdout)
        self.assertTrue(result["context_complete"])
        self.assertIn("USER_ROOT_CREATED", [w["code"] for w in result["warnings"]])
        self.assertIn(str((self.user / "config.yaml").resolve()), result["created"])
        self.assertIn(str((self.project / ".fstar" / "index.md").resolve()), result["created"])
        index = self.project / ".fstar" / "index.md"
        self.assertIn("A real project", index.read_text(encoding="utf-8"))
        self.assertIn("README.md", index.read_text(encoding="utf-8"))
        before = index.read_bytes()

        repeat = self.cli("--context", str(self.context))
        self.assertEqual(0, repeat.returncode, repeat.stderr)
        repeat = json.loads(repeat.stdout)
        self.assertEqual([], repeat["created"])
        self.assertNotIn("USER_ROOT_CREATED", [w["code"] for w in repeat["warnings"]])
        self.assertIn("INDEX_PRESERVED", [w["code"] for w in repeat["warnings"]])
        self.assertEqual(before, index.read_bytes())

    def test_existing_generated_skeleton_is_backfilled_without_confirmation(self):
        fresh = self.cli()
        self.assertEqual(0, fresh.returncode, fresh.stderr)
        index = self.project / ".fstar" / "index.md"
        self.assertIn("待补", index.read_text(encoding="utf-8"))

        result = self.cli("--context", str(self.context))
        self.assertEqual(0, result.returncode, result.stderr)
        result = json.loads(result.stdout)
        self.assertIn("INDEX_BACKFILLED", [w["code"] for w in result["warnings"]])
        self.assertTrue(result["context_complete"])
        updated = index.read_text(encoding="utf-8")
        self.assertIn("A real project", updated)
        self.assertNotIn("待补", updated)

    def test_user_init_and_invalid_context_have_no_project_side_effects(self):
        result = self.cli("--user")
        self.assertEqual(0, result.returncode, result.stderr)
        result = json.loads(result.stdout)
        self.assertEqual(str(self.user.resolve()), result["root"])
        self.assertFalse((self.project / ".fstar").exists())
        self.assertTrue((self.user / "config.yaml").is_file())
        self.assertEqual([], list(self.home.iterdir()))

    def test_reference_and_shape_errors_do_not_write(self):
        for context in (
            {"project_summary": "  ", "authority_refs": [{"title": "x", "path": "../outside"}]},
            {"project_summary": "x", "authority_refs": [{"title": "x", "path": "../outside"}]},
            {"project_summary": "x", "topics": "bad"},
        ):
            with self.subTest(context=context):
                self.context.write_text(json.dumps(context))
                result = self.cli("--context", str(self.context))
                self.assertNotEqual(0, result.returncode)
                self.assertFalse((self.project / ".fstar").exists())
                self.assertFalse(self.user.exists())
                self.assertEqual([], list(self.home.iterdir()))

    def test_bad_context_is_rejected_before_project_writes(self):
        self.context.write_text('{"project_summary": "x", "topics": [{}]}', encoding="utf-8")
        result = self.cli("--context", str(self.context))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("invalid_project_context", json.loads(result.stderr)["error"]["code"])
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse(self.user.exists())
