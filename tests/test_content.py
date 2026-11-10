from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fstar.content import (ContentError, MAP_SCHEMA, REQUIRED_SLOTS, ROLES, SKILLS,
                           TEMPLATES, build_artifact_map, extract_artifact,
                           load_mapping, validate_resources)
from fstar.evidence import EvidenceService
from fstar.store import TaskStore
from fstar.tasks import TaskService

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"


def marker_mapping(kind="prd"):
    return {
        "schema": MAP_SCHEMA, "artifact_type": kind,
        "slots": {name: {"start_marker": "<%s>" % name, "end_marker": "</%s>" % name}
                  for name in REQUIRED_SLOTS},
        "items": {"mode": "markers", "start_template": "<item:{id}>",
                  "end_template": "</item:{id}>"},
        "references": {"mode": "markers", "prefix": "<ref:", "suffix": ">", "separator": "#"},
    }


def artifact_text(item_id="需求一", reference=None):
    slots = "".join("<%s>%s</%s>" % (name, "" if name == "reviewer" else name, name)
                    for name in REQUIRED_SLOTS)
    ref = "<ref:%s>" % reference if reference else ""
    return slots + "<item:%s>正文%s</item:%s>" % (item_id, ref, item_id)


class InventoryTests(unittest.TestCase):
    def test_exact_inventory_and_validator(self):
        self.assertEqual(12, len(SKILLS))
        self.assertEqual(4, len(ROLES))
        self.assertEqual(11, len(TEMPLATES))
        self.assertEqual([], list(validate_resources(RESOURCES)))
        self.assertEqual(3, len(list((RESOURCES / "templates").rglob("*.mapping.yaml"))))

    def test_descriptions_and_frontmatter(self):
        descriptions = []
        for name in SKILLS:
            text = (RESOURCES / "skills" / ("fstar-" + name) / "SKILL.md").read_text()
            description = next(line for line in text.splitlines() if line.startswith("description:"))
            value = description.split(":", 1)[1].strip().strip('"')
            descriptions.append(value)
            self.assertLessEqual(len(value), 200)
            self.assertTrue(any("一" <= char <= "鿿" for char in value))
        self.assertLessEqual(sum(map(len, descriptions)), 2400)

    def test_fixed_package_ids_and_no_retired_inventory(self):
        routing = (RESOURCES / "runtime" / "routing.md").read_text()
        ids = {"planning-review", "persistent-task", "multi-agent", "project-governance", "tool-capability"}
        self.assertTrue(all("`%s`" % item in routing for item in ids))
        for retired in ("fstar-finish", "fstar-recall", "fstar-ui", "test-cases.md", "review-log.md"):
            self.assertFalse((RESOURCES / "skills" / retired).exists())


class MappingTests(unittest.TestCase):
    def write_mapping(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "mapping.yaml"
        path.write_text(text)
        return path

    def test_load_mapping_rejects_duplicate_nonfinite_and_yaml(self):
        good = marker_mapping()
        loaded = load_mapping(self.write_mapping(json.dumps(good)))
        self.assertEqual(MAP_SCHEMA, loaded["schema"])
        for text, code in [('{"schema":"%s","schema":"x"}' % MAP_SCHEMA, "MAPPING_DUPLICATE_KEY"),
                           ('{"schema":"%s","artifact_type":"x","items":{"mode":"file"},"n":NaN}' % MAP_SCHEMA, "MAPPING_UNSUPPORTED_SYNTAX"),
                           ("schema: fstar.template-map.v1", "MAPPING_UNSUPPORTED_SYNTAX")]:
            with self.subTest(code=code), self.assertRaises(ContentError) as caught:
                load_mapping(self.write_mapping(text))
            self.assertEqual(code, caught.exception.code)

    def test_default_and_custom_title_language_id_extract(self):
        extraction = extract_artifact(artifact_text("功能-甲"), marker_mapping(), artifact="doc/prd.md")
        self.assertTrue(extraction.ok, extraction.diagnostics)
        self.assertEqual("功能-甲", extraction.items[0].id)
        self.assertEqual("", extraction.slots["reviewer"])

    def test_explicit_boundaries_support_arbitrary_layout(self):
        mapping = marker_mapping()
        mapping["items"] = {"mode": "explicit", "entries": [{"id": "任意 ID", "start_marker": "BEGIN", "end_marker": "END"}]}
        extraction = extract_artifact(artifact_text().split("<item:", 1)[0] + "BEGIN任意正文END", mapping, artifact="doc/prd.md")
        self.assertTrue(extraction.ok, extraction.diagnostics)
        self.assertEqual("任意 ID", extraction.items[0].id)

    def test_failure_cases_are_diagnostic(self):
        cases = []
        cases.append((artifact_text().replace("<author>", ""), marker_mapping(), "MARKER_COUNT"))
        cases.append((artifact_text("X") + "<item:X>again</item:X>", marker_mapping(), "MARKER_COUNT"))
        duplicate = marker_mapping(); duplicate["items"] = {"mode": "explicit", "entries": [{"id":"X","start_marker":"A","end_marker":"B"},{"id":"X","start_marker":"C","end_marker":"D"}]}
        cases.append((artifact_text().split("<item:", 1)[0] + "AtB CtD", duplicate, "DUPLICATE_ID"))
        for text, mapping, code in cases:
            with self.subTest(code=code):
                extraction = extract_artifact(text, mapping, artifact="doc/prd.md")
                self.assertIn(code, {item.code for item in extraction.diagnostics})

    def test_links_and_dependencies_shape(self):
        mapping = marker_mapping()
        extraction = extract_artifact(artifact_text("R-1", "doc/prd.md#R-1"), mapping, artifact="doc/prd.md")
        output = build_artifact_map([extraction])
        self.assertEqual(["R-1"], output["doc/prd.md"]["R-1"]["dependencies"])
        bad = extract_artifact(artifact_text("R-1", "doc/prd.md#missing"), mapping, artifact="doc/prd.md")
        with self.assertRaises(ContentError):
            build_artifact_map([bad])

    def test_cross_artifact_dependency_refused_until_core_contract_supports_it(self):
        extraction = extract_artifact(artifact_text("R-1", "doc/design.md#D-1"), marker_mapping(), artifact="doc/prd.md")
        design = extract_artifact(artifact_text("D-1"), marker_mapping("design"), artifact="doc/design.md")
        with self.assertRaisesRegex(ContentError, "artifact-local"):
            build_artifact_map([extraction, design])

    def test_mapping_separator_is_honored(self):
        mapping = marker_mapping()
        mapping["references"]["separator"] = "::"
        extraction = extract_artifact(artifact_text("R-1", "doc/prd.md::R-1"), mapping, artifact="doc/prd.md")
        self.assertTrue(extraction.ok, extraction.diagnostics)
        self.assertEqual(("doc/prd.md#R-1",), extraction.items[0].references)
        output = build_artifact_map([extraction])
        self.assertEqual(["R-1"], output["doc/prd.md"]["R-1"]["dependencies"])

    def test_invalid_reference_mapping_is_diagnosed(self):
        invalid_mode = {"schema": MAP_SCHEMA, "artifact_type": "prd",
                        "items": {"mode": "markers"}, "references": {"mode": "guessing"}}
        with self.assertRaises(ContentError) as caught:
            load_mapping(self.write_mapping(json.dumps(invalid_mode)))
        self.assertEqual("MAPPING_REFERENCES", caught.exception.code)
        mapping = marker_mapping()
        mapping["items"] = {"mode": "explicit", "entries": [{"id": "X", "start_marker": "A", "end_marker": "B"}]}
        mapping["references"] = {"mode": "explicit",
                                 "entries": [{"source": "ghost", "target": "doc/prd.md#X"}]}
        text = artifact_text().split("<item:", 1)[0] + "A body B"
        extraction = extract_artifact(text, mapping, artifact="doc/prd.md")
        self.assertIn("UNKNOWN_REFERENCE_SOURCE", {item.code for item in extraction.diagnostics})

    def test_invalid_extraction_cannot_build_map(self):
        invalid = extract_artifact("", marker_mapping(), artifact="doc/prd.md")
        with self.assertRaises(ContentError):
            build_artifact_map([invalid])


class CoreIntegrationTests(unittest.TestCase):
    def test_content_map_persists_and_core_hashes_marker_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"; project.mkdir()
            (project / ".fstar").mkdir(); (project / ".fstar" / ".schema-version").write_text("1\n")
            store = TaskStore(project, user_home=root / "user", runtime_root=root / "runtime")
            task = TaskService(store).create(name="content", title="Content", description="R-1", actor={"role":"agent","id":"a"})
            relative = "doc/prd.md"; (project / "doc").mkdir()
            text = artifact_text("R-1")
            (project / relative).write_text(text)
            extraction = extract_artifact(text, marker_mapping(), artifact=relative)
            mapping = build_artifact_map([extraction])
            service = EvidenceService(store)
            service.persist_artifact_map("content", mapping=mapping, source={"ref":"fixture"})
            snapshot = service.snapshot("content", artifact=relative, items=["R-1"])
            self.assertEqual("R-1", snapshot["items"][0]["id"])
            persisted = store.read("content")["meta"]["templates"]["artifact_map"]
            self.assertEqual(mapping, persisted)
            self.assertNotIn("sha256", mapping[relative]["R-1"])


class ValidatorCoverageTests(unittest.TestCase):
    def copy_resources(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "resources"
        shutil.copytree(RESOURCES, target)
        return target

    def test_required_singletons_are_checked(self):
        root = self.copy_resources()
        (root / "runtime" / "routing.md").unlink()
        (root / "references" / "knowledge-format.md").unlink()
        diagnostics = list(validate_resources(root))
        missing = [item for item in diagnostics if item.code == "RESOURCE_MISSING"]
        self.assertTrue(any("routing.md" in item.path for item in missing))
        self.assertTrue(any("knowledge-format.md" in item.path for item in missing))

    def test_placeholder_declarations_are_enforced(self):
        root = self.copy_resources()
        plan = root / "templates" / "task" / "plan.md"
        plan.write_text(plan.read_text(encoding="utf-8") + "\n{{undeclared_name}}\n", encoding="utf-8")
        codes = {item.code for item in validate_resources(root)}
        self.assertIn("PLACEHOLDER_UNDECLARED", codes)

    def test_shipped_mapping_pairs_extract(self):
        self.assertEqual([], list(validate_resources(RESOURCES)))

    def test_broken_mapping_surfaces_as_diagnostic(self):
        root = self.copy_resources()
        (root / "templates" / "doc" / "prd.mapping.yaml").write_text(
            '{"schema": "fstar.template-map.v1", "schema": "duplicate"}', encoding="utf-8")
        codes = {item.code for item in validate_resources(root)}
        self.assertIn("MAPPING_DUPLICATE_KEY", codes)


class SemanticContentTests(unittest.TestCase):
    def all_text(self):
        return "\n".join(path.read_text() for path in RESOURCES.rglob("*.md"))

    def test_routing_negotiation_refusal_and_minimal_loop(self):
        text = (RESOURCES / "runtime" / "routing.md").read_text()
        for phrase in ("only one highest-value package", "After refusal", "do not ask again", "native implement", "independent `fstar-check`", "explicit user confirmation", "`fstar-debug` is core-automatic", "at most one automatic retry"):
            self.assertIn(phrase, text)
        # Init runs the scan; applying bindings is still gated and project-only.
        self.assertIn("runs an initial proposal-only tool scan", text)
        self.assertIn("written at project level only", text)
        self.assertNotIn("does not yet run that scan", text)

    def test_init_skill_binds_by_agent_with_one_confirmation(self):
        text = (RESOURCES / "skills/fstar-init/SKILL.md").read_text()
        for phrase in ("Initial capability binding", "at most one tool",
                       "30–50 entries", "project-level only",
                       "never overwrite silently", "Present one summary",
                       "tools_bridge"):
            self.assertIn(phrase, text)
        self.assertIn("never create or edit the user-level `~/.fstar/tools.yaml`", text)
        self.assertIn("leave the capability unbound", text)

    def test_routing_declares_read_only_binding_table_injection(self):
        text = (RESOURCES / "runtime" / "routing.md").read_text()
        self.assertIn("inject the resolved read-only binding table without any grant", text)
        self.assertIn("reading it is discovery and never authorizes changing tools.yaml", text)

    def test_archive_only_reminders_and_continue_boundary(self):
        archive = (RESOURCES / "skills/fstar-archive/SKILL.md").read_text()
        continuing = (RESOURCES / "skills/fstar-continue/SKILL.md").read_text()
        self.assertIn("only then", archive)
        self.assertIn("do not search history or issue archive reminders", continuing)

    def test_editor_background_conflict_and_ownership(self):
        doc = (RESOURCES / "skills/fstar-doc/SKILL.md").read_text()
        editor = (RESOURCES / "agents/fstar-editor.md").read_text()
        self.assertIn("background fstar-editor", doc)
        self.assertIn("Queue edits", doc)
        self.assertIn("stale-baseline", doc)
        self.assertIn("Never add/delete IDs", editor)
        self.assertIn("protocol, not a security sandbox", editor)

    def test_check_self_repair_and_final_overall_check(self):
        text = (RESOURCES / "skills/fstar-check/SKILL.md").read_text()
        self.assertIn("repair production or test code", text)
        self.assertIn("finish with one overall check", text)
        self.assertIn("Do not recursively dispatch another checker", text)

    def test_knowledge_schema_and_language_keys(self):
        reference = (RESOURCES / "references/knowledge-format.md").read_text()
        self.assertIn("fstar.knowledge.v1", reference)
        self.assertIn("enforced rule > explicit project spec > default rule > confirmed memory", reference)
        self.assertIn("unreviewed memories are not loaded", reference)
        self.assertIn("never becomes a rule automatically", reference)
        self.assertIn("language.specs", reference)
        all_text = self.all_text()
        self.assertNotIn("language.task", all_text)

    def test_template_source_and_design_chapters(self):
        design = (RESOURCES / "templates/doc/design.md").read_text()
        self.assertIn("674bea37cf2f6f25cd20dab93e1a54ae1f13ce66", design)
        for heading in ("## 7. 影响范围", "## 8. 配置与字典", "## 9. 附录、评审与版本"):
            self.assertIn(heading, design)
        self.assertNotIn("## 7. 测试与验收", design)

    def test_plan_seven_sections_and_no_second_approval(self):
        plan = (RESOURCES / "templates/task/plan.md").read_text()
        for heading in ("Summary", "Patterns to Mirror", "Files to Change", "Tasks", "Validation", "Risks", "Acceptance"):
            self.assertIn("## " + heading, plan)
        skill = (RESOURCES / "skills/fstar-plan/SKILL.md").read_text()
        self.assertIn("do not request a second plan approval", skill)


if __name__ == "__main__":
    unittest.main()
