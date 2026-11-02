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

    def test_context_scan_preview_and_repeat_preservation(self):
        preview = self.cli("--dry-run", "--context", str(self.context))
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertIsNone(json.loads(preview.stdout)["tool_proposals"])
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse(self.user.exists())
        result = self.cli("--context", str(self.context))
        self.assertEqual(0, result.returncode, result.stderr)
        result = json.loads(result.stdout)
        self.assertTrue(result["context_complete"])
        self.assertEqual("fstar.tools.scan.v1", result["tool_proposals"]["schema"])
        index = self.project / ".fstar" / "index.md"
        self.assertIn("A real project", index.read_text(encoding="utf-8"))
        self.assertIn("README.md", index.read_text(encoding="utf-8"))
        self.assertFalse((self.project / ".fstar" / "tools.yaml").exists())
        self.assertFalse((self.user / "tools.yaml").exists())
        before = index.read_bytes()
        repeat = self.cli("--context", str(self.context))
        self.assertEqual(0, repeat.returncode, repeat.stderr)
        self.assertIn("INDEX_PRESERVED", [w["code"] for w in json.loads(repeat.stdout)["warnings"]])
        self.assertEqual(before, index.read_bytes())

    def test_user_init_and_invalid_context_have_no_scan_side_effects(self):
        result = self.cli("--user")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNone(json.loads(result.stdout)["tool_proposals"])
        self.assertFalse((self.project / ".fstar").exists())
        self.assertFalse((self.user / "tools.yaml").exists())
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
