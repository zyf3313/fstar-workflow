import tempfile
import unittest
from pathlib import Path

from fstar.config import ConfigError, load_config, parse_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_read_only_and_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "missing"
            result = load_config(None, root)
            self.assertEqual("zh-CN", result.values["language"]["interaction"])
            self.assertFalse(result.values["auto_commit"])
            self.assertFalse(root.exists())

    def test_five_layers_merge_and_origins(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            user = base / "user"
            project = base / "project"
            (project / ".fstar").mkdir(parents=True)
            user.mkdir()
            (user / "config.yaml").write_text("custom:\n  value: user\nitems: [1, 2]\n", encoding="utf-8")
            (user / "config.local.yaml").write_text("custom:\n  local: true\n", encoding="utf-8")
            (project / ".fstar" / "config.yaml").write_text(
                "schema_version: 1\nproject:\n  id: 123e4567-e89b-12d3-a456-426614174000\ncustom:\n  value: project\nitems: []\n", encoding="utf-8")
            (project / ".fstar" / "config.local.yaml").write_text("custom:\n  nullable: null\n", encoding="utf-8")
            result = load_config(project, user)
            self.assertEqual({"value": "project", "local": True, "nullable": None}, result.values["custom"])
            self.assertEqual([], result.values["items"])
            self.assertEqual(str(project / ".fstar" / "config.yaml"), result.origins["custom.value"])

    def test_subset_acceptance(self):
        path = Path("config.yaml")
        value = parse_config("\ufeffname: 'it''s # fine'\r\nquoted: \"a: # b\"\r\nlist:\r\n  - true\r\n  - 2.5e2\r\nflow: {\"valid_key\": [1, null]}\r\n", path)
        self.assertEqual("it's # fine", value["name"])
        self.assertEqual(250.0, value["list"][1])

    def test_subset_rejections_are_explicit(self):
        samples = (
            "a: 01\n", "a: &x value\n", "a: *x\n", "a: !tag value\n",
            "a: |\n  value\n", "a:\n   b: 1\n", "a:\n    b: 1\n",
            "a: 1\na: 2\n", "a: [1,]\n", "a: {'x': 1}\n",
            "a: {x: 1}\n", "a: \"unterminated\n", "---\na: 1\n",
            "a: NaN\n", "a: 1e309\n", "a:\n  - one\n  - - two\n",
        )
        for text in samples:
            with self.subTest(text=text), self.assertRaises(ConfigError):
                parse_config(text, Path("bad.yaml"))

    def test_flow_duplicate_and_nonfinite_have_explicit_errors(self):
        with self.assertRaises(ConfigError) as duplicate:
            parse_config('a: {"x": 1, "x": 2}\n', Path("bad.yaml"))
        self.assertEqual("CONFIG_DUPLICATE_KEY", duplicate.exception.code)
        with self.assertRaises(ConfigError):
            parse_config("a: [1e309]\n", Path("bad.yaml"))

    def test_empty_mapping_does_not_clear_existing_mapping(self):
        defaults = {"schema_version": 1, "auto_commit": False,
                    "language": {"interaction": "zh-CN", "artifacts": "zh-CN", "specs": "en"},
                    "custom": {"nested": True}}
        with tempfile.TemporaryDirectory() as temp:
            user = Path(temp)
            (user / "config.yaml").write_text("custom: {}\n", encoding="utf-8")
            result = load_config(None, user, defaults=defaults)
            self.assertEqual({"nested": True}, result.values["custom"])
            result.values["custom"]["nested"] = False
            self.assertTrue(defaults["custom"]["nested"])

    def test_project_identity_is_rejected_from_project_local(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            user = Path(temp) / "user"
            (project / ".fstar").mkdir(parents=True)
            (project / ".fstar" / "config.yaml").write_text(
                "schema_version: 1\nproject:\n  id: 123e4567-e89b-12d3-a456-426614174000\n", encoding="utf-8")
            (project / ".fstar" / "config.local.yaml").write_text(
                "project:\n  id: 123e4567-e89b-12d3-a456-426614174001\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as error:
                load_config(project, user)
            self.assertEqual("CONFIG_PROJECT_IDENTITY", error.exception.code)

    def test_type_mismatch_and_identity_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            user = Path(temp)
            (user / "config.yaml").write_text("auto_commit: 1\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as error:
                load_config(None, user)
            self.assertEqual("CONFIG_TYPE_MISMATCH", error.exception.code)
            (user / "config.yaml").write_text("project:\n  id: 123e4567-e89b-12d3-a456-426614174000\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as error:
                load_config(None, user)
            self.assertEqual("CONFIG_PROJECT_IDENTITY", error.exception.code)


if __name__ == "__main__":
    unittest.main()
