import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fstar.project import (DocumentReference, InitError, ProjectContext, TopicReference,
                           initialize_project, initialize_user)


class ProjectTests(unittest.TestCase):
    def test_project_minimal_idempotent_and_no_user_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            user = Path(temp) / "user"
            project.mkdir()
            first = initialize_project(project, user)
            self.assertEqual({"index.md", "config.yaml", ".gitignore", ".schema-version"},
                             {path.name for path in first.created})
            before = {path.name: path.read_bytes() for path in (project / ".fstar").iterdir()}
            second = initialize_project(project, user)
            self.assertEqual((), second.created)
            self.assertEqual(before, {path.name: path.read_bytes() for path in (project / ".fstar").iterdir()})
            self.assertFalse(user.exists())

    def test_user_minimal_and_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "user"
            preview = initialize_user(root, dry_run=True)
            self.assertEqual(3, len(preview.created))
            self.assertFalse(root.exists())
            result = initialize_user(root)
            self.assertEqual({"index.md", "config.yaml", ".gitignore"}, {path.name for path in result.created})
            self.assertFalse((root / "rules").exists())
            self.assertFalse((root / "memory").exists())

    def test_real_context_references_without_fixed_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "docs").mkdir()
            (project / "docs" / "architecture.md").write_text("authority", encoding="utf-8")
            context = ProjectContext(
                "多模块项目",
                topics=(TopicReference("T-1", "核心", "src/core", "修改核心时", "docs/architecture.md#core"),),
                authority_refs=(DocumentReference("架构", "docs/architecture.md"),))
            result = initialize_project(project, project / "unused", context=context)
            index = (project / ".fstar" / "index.md").read_text(encoding="utf-8")
            self.assertTrue(result.context_complete)
            self.assertIn("docs/architecture.md", index)
            self.assertEqual("authority", (project / "docs" / "architecture.md").read_text(encoding="utf-8"))
            self.assertFalse((project / ".fstar" / "frontend").exists())

    def test_existing_index_preserved_and_warned(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            initialize_project(project, project / "user")
            index = project / ".fstar" / "index.md"
            index.write_bytes(b"custom\r\n")
            context = ProjectContext("known", authority_refs=(DocumentReference("readme", "README.md"),))
            (project / "README.md").write_text("x", encoding="utf-8")
            result = initialize_project(project, project / "user", context=context)
            self.assertEqual(b"custom\r\n", index.read_bytes())
            self.assertIn("INDEX_PRESERVED", [warning.code for warning in result.warnings])
            self.assertFalse(result.context_complete)

    def test_symlinks_and_outside_references_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            outside = Path(temp) / "outside"
            project.mkdir()
            outside.mkdir()
            (outside / "sentinel").write_text("safe", encoding="utf-8")
            os.symlink(str(outside), str(project / ".fstar"))
            with self.assertRaises(InitError):
                initialize_project(project, Path(temp) / "user")
            self.assertEqual("safe", (outside / "sentinel").read_text(encoding="utf-8"))

    def test_existing_ignore_preserved_with_actionable_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            data = project / ".fstar"
            data.mkdir()
            ignore = data / ".gitignore"
            ignore.write_bytes(b"custom\r\n")
            result = initialize_project(project, project / "user")
            self.assertEqual(b"custom\r\n", ignore.read_bytes())
            warnings = [warning for warning in result.warnings if warning.code == "IGNORE_RULES_MISSING"]
            self.assertEqual(1, len(warnings))
            self.assertIn("/runtime/", warnings[0].message)

    def test_target_symlink_is_rejected_without_touching_outside_file(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            outside = Path(temp) / "outside.txt"
            data = project / ".fstar"
            data.mkdir(parents=True)
            outside.write_text("safe", encoding="utf-8")
            os.symlink(str(outside), str(data / "index.md"))
            with self.assertRaises(InitError) as error:
                initialize_project(project, Path(temp) / "user")
            self.assertIn(error.exception.code, ("PATH_CONFLICT", "SYMLINK_NOT_ALLOWED"))
            self.assertEqual("safe", outside.read_text(encoding="utf-8"))

    def test_outside_context_reference_is_rejected_without_creating_layout(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            project.mkdir()
            outside = Path(temp) / "outside.md"
            outside.write_text("safe", encoding="utf-8")
            os.symlink(str(outside), str(project / "authority.md"))
            context = ProjectContext("known", authority_refs=(DocumentReference("outside", "authority.md"),))
            with self.assertRaises(InitError) as error:
                initialize_project(project, Path(temp) / "user", context=context)
            self.assertEqual("REFERENCE_OUTSIDE_PROJECT", error.exception.code)
            self.assertFalse((project / ".fstar").exists())

    def test_existing_user_schema_is_validated_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "user"
            root.mkdir()
            config = root / "config.yaml"
            config.write_bytes(b"schema_version: 2\r\n")
            with self.assertRaises(InitError) as error:
                initialize_user(root)
            self.assertEqual("INCOMPATIBLE_SCHEMA", error.exception.code)
            self.assertEqual(b"schema_version: 2\r\n", config.read_bytes())
            self.assertFalse((root / "index.md").exists())

    def test_incompatible_schema_and_partial_failure_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            data = project / ".fstar"
            data.mkdir()
            (data / ".schema-version").write_text("2\n", encoding="utf-8")
            with self.assertRaises(InitError) as error:
                initialize_project(project, project / "user")
            self.assertEqual("INCOMPATIBLE_SCHEMA", error.exception.code)
            (data / ".schema-version").unlink()
            original = os.open
            calls = {"count": 0}
            def failing(path, flags, mode=0o777):
                calls["count"] += 1
                if calls["count"] == 3:
                    raise OSError("injected")
                return original(path, flags, mode)
            with mock.patch("fstar.project.os.open", side_effect=failing):
                with self.assertRaises(InitError) as failure:
                    initialize_project(project, project / "user")
            self.assertEqual(2, len(failure.exception.created))
            retry = initialize_project(project, project / "user")
            self.assertEqual(2, len(retry.created))


if __name__ == "__main__":
    unittest.main()
