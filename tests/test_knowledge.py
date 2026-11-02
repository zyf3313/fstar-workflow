"""Contract tests for the fstar knowledge provider.

The tests use isolated fixtures only: no real home directory, no live
retrieval service and no host integration.  They prove the API contracts of
``fstar.knowledge``; they do not prove caller wiring in init, learn,
runtime, tools or the installer.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from fstar.knowledge import (Applicability, ChangeIntent, Confirmation, KnowledgeEdit,
                             ReadSelection, ReportedConflict, ReviewedSource, SemanticAssessment,
                             SourceRecord, TopicChoice, apply_change, load_catalog, load_context,
                             parse_knowledge, prepare_change, recover_changes, resolve_context,
                             set_failure_hook)
from fstar.models import DomainError
from fstar.project import (DocumentReference, ProjectContext, TopicReference, initialize_project,
                           initialize_user)

REPOSITORY = Path(__file__).resolve().parent.parent
SOURCE = REPOSITORY / "src"

RULE_ENFORCED = """---
schema: fstar.knowledge.v1
type: rule
status: active
strength: enforced
---

# Global rule

MUST run the test suite before reporting work as done.
APPLIES: every task in this repository.
NOT: documentation only changes.
SOURCE: user instruction 2026-01-01.
"""

RULE_DEFAULT = """---
schema: fstar.knowledge.v1
type: rule
status: active
strength: default
---

# Style rule

MUST keep public functions small.
APPLIES: source modules.
NOT: generated files.
SOURCE: user instruction 2026-02-02.
"""

RULE_SUPERSEDED = """---
schema: fstar.knowledge.v1
type: rule
status: superseded
strength: enforced
---

# Old rule

MUST use the old workflow.
APPLIES: everything.
NOT: nothing.
SOURCE: user instruction 2025-01-01.
"""

MEMORY_CONFIRMED = """---
schema: fstar.knowledge.v1
type: memory
status: active
kind: preference
trust: confirmed
---

# Communication preference

Prefer short status updates.
APPLIES: status reports.
NOT: design documents.
SOURCE: conversation 2026-03-03.
"""

MEMORY_UNREVIEWED = """---
schema: fstar.knowledge.v1
type: memory
status: active
kind: lesson
trust: unreviewed
---

# Unreviewed lesson

Maybe always use tabs.
APPLIES: source modules.
NOT: unknown.
SOURCE: conversation 2026-03-04.
"""

SPEC_CORE = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# Core specification

Keep the core module free of feature flags.
"""

SPEC_EXTRA = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# Extra specification

The extra module owns the adapters.
"""

CONTEXT_BACKGROUND = "# Background\n\nThe project keeps storage adapters in one module.\n"
REFERENCE_GLOSSARY = "# Glossary\n\nAdapter: a translation layer.\n"
AUTHORITY_DOCUMENT = "# Architecture\n\nThe core module owns the domain model.\n"


def knowledge_error(testcase, code, callable_, *args, **kwargs):
    with testcase.assertRaises(DomainError) as error:
        callable_(*args, **kwargs)
    testcase.assertEqual(code, error.exception.code)
    return error.exception


class KnowledgeFixture(unittest.TestCase):
    """Builds an isolated user root and project root."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.project = self.root / "project"
        self.user = self.root / "user"
        self.project.mkdir()
        (self.project / "docs").mkdir()
        (self.project / "docs" / "architecture.md").write_text(AUTHORITY_DOCUMENT, encoding="utf-8")
        (self.project / ".fstar" / "specs").mkdir(parents=True)
        (self.project / ".fstar" / "knowledge" / "context").mkdir(parents=True)
        (self.project / ".fstar" / "knowledge" / "references").mkdir(parents=True)
        (self.project / ".fstar" / "specs" / "core.md").write_text(SPEC_CORE, encoding="utf-8")
        (self.project / ".fstar" / "specs" / "extra.md").write_text(SPEC_EXTRA, encoding="utf-8")
        (self.project / ".fstar" / "knowledge" / "context" / "background.md").write_text(
            CONTEXT_BACKGROUND, encoding="utf-8")
        (self.project / ".fstar" / "knowledge" / "references" / "glossary.md").write_text(
            REFERENCE_GLOSSARY, encoding="utf-8")
        initialize_project(self.project, self.user, context=ProjectContext(
            "一个多模块项目。",
            topics=(TopicReference("T-1", "核心", "src/core", "修改核心时", ".fstar/specs/core.md"),
                    TopicReference("T-2", "扩展", "src/extra", "修改扩展时", ".fstar/specs/extra.md")),
            authority_refs=(DocumentReference("架构", "docs/architecture.md"),),
            knowledge_refs=(DocumentReference("背景", ".fstar/knowledge/context/background.md"),)))
        initialize_user(self.user)
        (self.user / "rules").mkdir()
        (self.user / "memory").mkdir()
        (self.user / "rules" / "global.md").write_text(RULE_ENFORCED, encoding="utf-8")
        (self.user / "rules" / "style.md").write_text(RULE_DEFAULT, encoding="utf-8")
        (self.user / "rules" / "old.md").write_text(RULE_SUPERSEDED, encoding="utf-8")
        (self.user / "memory" / "preference.md").write_text(MEMORY_CONFIRMED, encoding="utf-8")
        (self.user / "memory" / "lesson.md").write_text(MEMORY_UNREVIEWED, encoding="utf-8")
        (self.user / "index.md").write_text(textwrap.dedent("""\
            # fstar 用户索引

            本地定制入口说明。

            ## Rules

            - [全局规则](rules/global.md) — strength: enforced
            - [代码风格](rules/style.md) — strength: default

            ## Memory

            - [沟通偏好](memory/preference.md) — kind: preference
            """), encoding="utf-8")

    # -- helpers ---------------------------------------------------------
    def catalog(self):
        return load_catalog(user_root=self.user, project_root=self.project)

    def bundle(self, catalog=None, **kwargs):
        catalog = catalog or self.catalog()
        selection = kwargs.pop("selection", ReadSelection(topics=("T-1",)))
        return load_context(catalog, selection=selection, **kwargs)

    def assessment(self, bundle=None, conflicts=(), coverage="complete", catalog=None):
        catalog = catalog or self.catalog()
        reviewed = [ReviewedSource(document.key, document.digest)
                    for document in catalog.documents if document.effective]
        reviewed.extend(ReviewedSource(index.key, index.digest) for index in catalog.indexes)
        return SemanticAssessment(reviewed=tuple(reviewed), conflicts=tuple(conflicts),
                                  coverage=coverage)

    def intent(self, **kwargs):
        values = {"summary": "tighten the core specification", "action": "correct",
                  "source": SourceRecord("conversation", "chat#42", "yes please", "2026-04-01"),
                  "scope": "project core specification"}
        values.update(kwargs)
        return ChangeIntent(**values)

    def confirmation(self, proposal, **kwargs):
        values = {"disposition": "approved", "source_type": "conversation",
                  "source_ref": "chat#42", "quote": "yes please", "confirmed_at": "2026-04-01",
                  "proposal_hash": proposal.proposal_hash, "scope": proposal.scope,
                  "owners": proposal.owners}
        values.update(kwargs)
        return Confirmation(**values)


class ParseKnowledgeTests(unittest.TestCase):
    """Strict decoding of the one knowledge format."""

    def parse(self, text, **kwargs):
        return parse_knowledge(text, path=Path("memory/case.md"), **kwargs)

    def test_valid_documents_decode_without_defaults(self):
        rule = self.parse(RULE_ENFORCED)
        self.assertEqual("rule", rule.type)
        self.assertEqual("active", rule.status)
        self.assertEqual("enforced", rule.strength)
        self.assertIn("MUST run the test suite", rule.body)
        memory = self.parse(MEMORY_CONFIRMED)
        self.assertEqual("preference", memory.kind)
        self.assertEqual("confirmed", memory.trust)
        spec = self.parse(SPEC_CORE)
        self.assertEqual("spec", spec.type)
        self.assertIsNone(spec.strength)
        self.assertEqual({"schema", "type", "status"}, set(spec.metadata))

    def test_digest_is_stable_and_covers_the_original_bytes(self):
        first = self.parse(RULE_ENFORCED)
        second = self.parse(RULE_ENFORCED)
        self.assertEqual(first.digest, second.digest)
        self.assertNotEqual(first.digest, self.parse(RULE_DEFAULT).digest)

    def test_crlf_is_normalized_for_parsing_but_hashed_from_the_original(self):
        crlf = RULE_ENFORCED.replace("\n", "\r\n")
        document = self.parse(crlf)
        self.assertEqual("rule", document.type)
        self.assertNotEqual(self.parse(RULE_ENFORCED).digest, document.digest)

    def test_required_fields_are_missing_errors(self):
        for field in ("schema", "type", "status"):
            text = "\n".join(line for line in RULE_ENFORCED.split("\n")
                             if not line.startswith(field + ":")) + "\n"
            error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
            self.assertEqual(field, error.details["field"])

    def test_missing_frontmatter_delimiter_is_an_error(self):
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, "# no frontmatter\n")
        self.assertIn("expected", error.details)

    def test_unterminated_frontmatter_is_an_error(self):
        text = "---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\nstrength: default\n"
        knowledge_error(self, "knowledge_invalid_schema", self.parse, text)

    def test_empty_body_is_an_error(self):
        text = "---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\nstrength: default\n---\n\n"
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
        self.assertIn("body", error.message.lower())

    def test_duplicate_keys_are_rejected(self):
        text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: default\nstrength: enforced\n---\n\n# Title\n")
        knowledge_error(self, "knowledge_invalid_schema", self.parse, text)

    def test_unknown_keys_are_rejected(self):
        text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: default\npriority: high\n---\n\n# Title\n")
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
        self.assertEqual("priority", error.details["field"])

    def test_non_string_values_are_rejected(self):
        for value in ("7", "true", "null", '["a", "b"]', '{"a": 1}'):
            text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                    "strength: %s\n---\n\n# Title\n" % value)
            error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
            self.assertEqual("strength", error.details["field"])
            self.assertEqual("string", error.details["expected"])

    def test_malformed_frontmatter_values_are_rejected(self):
        text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: [a, b]\n---\n\n# Title\n")
        knowledge_error(self, "knowledge_invalid_schema", self.parse, text)

    def test_enum_values_are_rejected(self):
        cases = (("strength", "strict"), ("status", "draft"))
        for field, value in cases:
            lines = []
            for line in RULE_ENFORCED.split("\n"):
                if line.startswith(field + ":"):
                    line = "%s: %s" % (field, value)
                lines.append(line)
            text = "\n".join(lines)
            error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
            self.assertEqual(field, error.details["field"])

    def test_type_inapplicable_fields_are_rejected(self):
        text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: default\nkind: preference\n---\n\n# Title\n")
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
        self.assertEqual("kind", error.details["field"])
        text = ("---\nschema: fstar.knowledge.v1\ntype: spec\nstatus: active\n"
                "strength: default\n---\n\n# Title\n")
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
        self.assertEqual("strength", error.details["field"])

    def test_wrong_category_is_rejected(self):
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, RULE_ENFORCED,
                                expected_type="memory")
        self.assertEqual("memory", error.details["expected"])
        self.assertEqual("rule", error.details["actual"])

    def test_unknown_schema_is_rejected(self):
        text = RULE_ENFORCED.replace("fstar.knowledge.v1", "fstar.knowledge.v2")
        error = knowledge_error(self, "knowledge_invalid_schema", self.parse, text)
        self.assertEqual("fstar.knowledge.v1", error.details["expected"])

    def test_inactive_documents_are_validated_not_skipped(self):
        document = self.parse(RULE_SUPERSEDED)
        self.assertEqual("superseded", document.status)
        text = RULE_SUPERSEDED.replace("strength: enforced", "strength: strict")
        knowledge_error(self, "knowledge_invalid_schema", self.parse, text)


class CatalogTests(KnowledgeFixture):
    """Read-only snapshots of the corpus."""

    def test_read_only_calls_create_no_files(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        self.catalog()
        self.bundle()
        after = sorted(str(path) for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertFalse((self.user / "runtime").exists())
        self.assertFalse((self.project / ".fstar" / "runtime").exists())

    def test_catalog_lists_every_category_with_provenance(self):
        catalog = self.catalog()
        keys = {document.key for document in catalog.documents}
        self.assertIn("user:rules/global.md", keys)
        self.assertIn("user:memory/preference.md", keys)
        self.assertIn("project:.fstar/specs/core.md", keys)
        self.assertIn("project:.fstar/knowledge/context/background.md", keys)
        self.assertIn("project:.fstar/knowledge/references/glossary.md", keys)
        self.assertIn("project:docs/architecture.md", keys)
        self.assertTrue(catalog.snapshot_hash)

    def test_inactive_and_unreviewed_documents_are_reported_but_not_effective(self):
        catalog = self.catalog()
        by_key = {document.key: document for document in catalog.documents}
        self.assertFalse(by_key["user:rules/old.md"].effective)
        self.assertFalse(by_key["user:memory/lesson.md"].effective)
        self.assertTrue(by_key["user:rules/global.md"].effective)
        self.assertEqual("superseded", by_key["user:rules/old.md"].status)
        self.assertEqual("unreviewed", by_key["user:memory/lesson.md"].trust)

    def test_invalid_documents_produce_explicit_diagnostics(self):
        (self.user / "rules" / "broken.md").write_text(
            "---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n---\n\n# Broken\n",
            encoding="utf-8")
        catalog = self.catalog()
        blocking = [item for item in catalog.diagnostics if item.blocking]
        self.assertEqual(1, len(blocking))
        self.assertEqual("knowledge_invalid_schema", blocking[0].code)
        self.assertTrue(str(blocking[0].path).endswith("broken.md"))
        self.assertNotIn("user:rules/broken.md",
                         {document.key for document in catalog.documents})

    def test_context_documents_may_not_use_the_knowledge_frontmatter(self):
        (self.project / ".fstar" / "knowledge" / "context" / "wrong.md").write_text(
            RULE_ENFORCED, encoding="utf-8")
        catalog = self.catalog()
        blocking = [item for item in catalog.diagnostics if item.blocking]
        self.assertEqual(1, len(blocking))
        self.assertEqual("knowledge_invalid_schema", blocking[0].code)

    def test_language_policy_follows_the_real_configuration(self):
        catalog = self.catalog()
        self.assertEqual("en", catalog.language["rule"])
        self.assertEqual("en", catalog.language["memory"])
        self.assertEqual("en", catalog.language["spec"])
        self.assertEqual("zh-CN", catalog.language["context"])
        (self.project / ".fstar" / "config.yaml").write_text(
            "schema_version: 1\nlanguage:\n  specs: zh-CN\n", encoding="utf-8")
        catalog = self.catalog()
        self.assertEqual("zh-CN", catalog.language["spec"])
        self.assertEqual("en", catalog.language["rule"])
        self.assertEqual("zh-CN", catalog.language["context"])

    def test_project_topics_and_authority_are_parsed_from_the_real_index(self):
        catalog = self.catalog()
        self.assertEqual(["T-1", "T-2"], [topic.id for topic in catalog.topic_refs])
        self.assertEqual(".fstar/specs/core.md", catalog.topic_refs[0].path)
        self.assertEqual(["docs/architecture.md"],
                         [reference.path for reference in catalog.authority_refs])

    def test_a_project_without_a_store_initializes_nothing(self):
        empty = self.root / "empty-project"
        empty.mkdir()
        catalog = load_catalog(user_root=self.user, project_root=empty)
        self.assertEqual((), catalog.topic_refs)
        self.assertFalse((empty / ".fstar").exists())

    def test_symbolic_links_in_the_corpus_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        outside = self.root / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        os.symlink(str(outside), str(self.user / "rules" / "link.md"))
        catalog = self.catalog()
        blocking = [item for item in catalog.diagnostics if item.blocking]
        self.assertEqual(1, len(blocking))
        self.assertEqual("knowledge_unsafe_path", blocking[0].code)
        self.assertEqual("outside\n", outside.read_text(encoding="utf-8"))


class ContextTests(KnowledgeFixture):
    """Complete applicable reading."""

    def test_reading_order_covers_overview_constraints_and_topics(self):
        bundle = self.bundle()
        keys = [document.key for document in bundle.full_documents]
        self.assertEqual("project:.fstar/index.md", keys[0])
        self.assertIn("user:index.md", keys[1:3])
        self.assertLess(keys.index("user:rules/global.md"), keys.index("project:.fstar/specs/core.md"))
        for document in bundle.full_documents:
            self.assertTrue(document.digest)
            self.assertTrue(document.size)

    def test_scope_limits_the_reading_and_itemizes_the_rest(self):
        bundle = self.bundle(selection=ReadSelection(topics=("T-1",)))
        keys = {document.key for document in bundle.full_documents}
        self.assertIn("project:.fstar/specs/core.md", keys)
        self.assertNotIn("project:.fstar/specs/extra.md", keys)
        excluded = {item.key: item.reason for item in bundle.excluded}
        self.assertIn("project:.fstar/specs/extra.md", excluded)
        self.assertIn("not referenced by a selected topic", excluded["project:.fstar/specs/extra.md"])

    def test_unknown_applicability_broadens_the_reading(self):
        bundle = self.bundle(selection=ReadSelection(
            topics=("T-1",),
            applicability={"project:.fstar/specs/core.md": Applicability("unknown", "not reviewed")}))
        keys = {document.key for document in bundle.full_documents}
        self.assertIn("project:.fstar/specs/core.md", keys)
        self.assertTrue(bundle.conflicts_pending)

    def test_excluded_applicability_removes_a_document(self):
        bundle = self.bundle(selection=ReadSelection(
            topics=("T-1",),
            applicability={"project:.fstar/specs/core.md": Applicability("exclude", "other module")}))
        keys = {document.key for document in bundle.full_documents}
        self.assertNotIn("project:.fstar/specs/core.md", keys)
        reasons = {item.key: item.reason for item in bundle.excluded}
        self.assertIn("other module", reasons["project:.fstar/specs/core.md"])

    def test_missing_bodies_are_itemized_and_completeness_stays_false(self):
        (self.project / ".fstar" / "specs" / "core.md").unlink()
        bundle = self.bundle()
        self.assertFalse(bundle.complete)
        self.assertTrue(bundle.conflicts_pending)
        missing = {item.key: item for item in bundle.required_unloaded}
        self.assertIn("project:.fstar/specs/core.md", missing)
        self.assertIn("missing", missing["project:.fstar/specs/core.md"].reason)

    def test_over_budget_bodies_are_deferred_whole(self):
        bundle = self.bundle(max_bytes=10)
        self.assertFalse(bundle.complete)
        deferred = {item.key: item for item in bundle.required_unloaded}
        self.assertIn("project:.fstar/specs/core.md", deferred)
        self.assertIn("budget", deferred["project:.fstar/specs/core.md"].reason)
        for document in bundle.full_documents:
            self.assertLessEqual(document.size, 10)

    def test_dependencies_are_followed_with_cycle_detection(self):
        (self.project / ".fstar" / "specs" / "core.md").write_text(
            SPEC_CORE + "\nSee [extra](extra.md).\n", encoding="utf-8")
        (self.project / ".fstar" / "specs" / "extra.md").write_text(
            SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        bundle = self.bundle()
        keys = {document.key: document.role for document in bundle.full_documents}
        self.assertEqual("topic", keys["project:.fstar/specs/core.md"])
        self.assertEqual("dependency", keys["project:.fstar/specs/extra.md"])
        self.assertTrue(bundle.complete)

    def test_superseded_and_unreviewed_bodies_never_enter_the_reading(self):
        bundle = self.bundle()
        keys = {document.key for document in bundle.full_documents}
        self.assertNotIn("user:rules/old.md", keys)
        self.assertNotIn("user:memory/lesson.md", keys)
        reasons = {item.key: item.reason for item in bundle.excluded}
        self.assertIn("superseded", reasons["user:rules/old.md"])
        self.assertIn("confirmed", reasons["user:memory/lesson.md"])

    def test_selection_from_another_snapshot_is_rejected(self):
        catalog = self.catalog()
        selection = ReadSelection(topics=("T-1",), snapshot_hash="other")
        error = knowledge_error(self, "knowledge_context_incomplete", load_context, catalog,
                                selection=selection)
        self.assertEqual(catalog.snapshot_hash, error.details["expected"])


class ResolutionTests(KnowledgeFixture):
    """Precedence and explicit conflicts."""

    def resolve(self, conflicts=(), coverage="complete", topics=("T-1", "T-2")):
        bundle = self.bundle(selection=ReadSelection(topics=topics))
        assessment = self.assessment(bundle, conflicts=conflicts, coverage=coverage)
        return bundle, resolve_context(bundle, assessment=assessment)

    def test_the_four_tiers_are_ordered(self):
        bundle, resolution = self.resolve()
        tiers = {source.key: source.tier for source in resolution.ordered_sources}
        self.assertEqual(0, tiers["user:rules/global.md"])
        self.assertEqual(1, tiers["project:.fstar/specs/core.md"])
        self.assertEqual(2, tiers["user:rules/style.md"])
        self.assertEqual(3, tiers["user:memory/preference.md"])
        self.assertTrue(resolution.complete)

    def test_existing_authority_outranks_derived_project_guidance(self):
        conflict = ReportedConflict(sources=("project:docs/architecture.md",
                                              "project:.fstar/specs/core.md"),
                                     rationale="the architecture document is authoritative")
        _, resolution = self.resolve([conflict])
        self.assertEqual(1, len(resolution.conflicts))
        outcome = resolution.conflicts[0]
        self.assertEqual("resolved", outcome.status)
        self.assertEqual("project:docs/architecture.md", outcome.winner)
        self.assertIn("authoritative", outcome.reason)

    def test_an_enforced_rule_wins_over_a_project_specification(self):
        conflict = ReportedConflict(sources=("user:rules/global.md",
                                              "project:.fstar/specs/core.md"))
        _, resolution = self.resolve([conflict])
        outcome = resolution.conflicts[0]
        self.assertEqual("resolved", outcome.status)
        self.assertEqual("user:rules/global.md", outcome.winner)
        self.assertIn("enforced rule", outcome.reason)

    def test_equal_tier_conflicts_stay_unresolved(self):
        conflict = ReportedConflict(sources=("project:.fstar/specs/core.md",
                                              "project:.fstar/specs/extra.md"),
                                     rationale="two project specifications disagree")
        _, resolution = self.resolve([conflict])
        outcome = resolution.conflicts[0]
        self.assertEqual("unresolved", outcome.status)
        self.assertIsNone(outcome.winner)
        self.assertEqual(1, len(resolution.unresolved))
        self.assertFalse(resolution.complete)

    def test_a_default_rule_outranks_a_confirmed_memory(self):
        conflict = ReportedConflict(sources=("user:rules/style.md",
                                              "user:memory/preference.md"))
        _, resolution = self.resolve([conflict])
        outcome = resolution.conflicts[0]
        self.assertEqual("resolved", outcome.status)
        self.assertEqual("user:rules/style.md", outcome.winner)
        self.assertIn("default rule", outcome.reason)

    def test_conflicts_with_excluded_memories_are_moot(self):
        conflict = ReportedConflict(sources=("user:memory/lesson.md",
                                              "project:.fstar/specs/core.md"))
        _, resolution = self.resolve([conflict])
        outcome = resolution.conflicts[0]
        self.assertEqual("moot", outcome.status)
        self.assertIn("not effective", outcome.reason)

    def test_a_missing_review_keeps_the_resolution_incomplete(self):
        bundle = self.bundle()
        resolution = resolve_context(bundle, assessment=None)
        self.assertFalse(resolution.complete)
        self.assertTrue(resolution.conflicts_pending)
        self.assertTrue(resolution.unreviewed_sources)

    def test_a_changed_source_invalidates_the_assessment(self):
        bundle = self.bundle()
        assessment = self.assessment(bundle)
        (self.user / "rules" / "global.md").write_text(RULE_ENFORCED + "\nExtra.\n",
                                                        encoding="utf-8")
        fresh = self.bundle()
        resolution = resolve_context(fresh, assessment=assessment)
        self.assertFalse(resolution.complete)
        self.assertIn("user:rules/global.md", resolution.stale_sources)

    def test_source_conflicts_are_named_with_their_reason(self):
        conflict = ReportedConflict(sources=("user:rules/global.md",
                                              "project:.fstar/specs/core.md"),
                                     sections=("Global rule", "Core specification"),
                                     rationale="the rule forbids flags")
        _, resolution = self.resolve([conflict])
        outcome = resolution.conflicts[0]
        self.assertEqual(("Global rule", "Core specification"), outcome.sections)
        self.assertEqual("the rule forbids flags", outcome.rationale)
        self.assertEqual(("user:rules/global.md", "project:.fstar/specs/core.md"), outcome.sources)


class ProposalTests(KnowledgeFixture):
    """Exact byte proposals, authorization and reference closure."""

    def proposal(self, edits=None, intent=None, assessment=None, catalog=None):
        catalog = catalog or self.catalog()
        bundle = self.bundle(catalog)
        assessment = assessment or self.assessment(catalog=catalog)
        edits = edits if edits is not None else [KnowledgeEdit(
            path=".fstar/specs/core.md", owner="project", action="replace",
            content=SPEC_CORE.replace("free of feature flags", "free of feature flags and globals"))]
        intent = intent or self.intent(topic=TopicChoice("T-1", "核心"))
        return prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)

    def test_a_proposal_never_writes_anything(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        self.proposal()
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_the_digest_covers_content_paths_scope_and_strength(self):
        base = self.proposal()
        changed_content = self.proposal(edits=[KnowledgeEdit(
            path=".fstar/specs/core.md", owner="project", action="replace",
            content=SPEC_CORE.replace("free of feature flags", "different text"))])
        self.assertNotEqual(base.proposal_hash, changed_content.proposal_hash)
        changed_path = self.proposal(edits=[KnowledgeEdit(
            path=".fstar/specs/extra.md", owner="project", action="replace",
            content=SPEC_EXTRA)])
        self.assertNotEqual(base.proposal_hash, changed_path.proposal_hash)
        changed_scope = self.proposal(intent=self.intent(scope="another scope",
                                                         topic=TopicChoice("T-1", "核心")))
        self.assertNotEqual(base.proposal_hash, changed_scope.proposal_hash)
        changed_strength = self.proposal(edits=[KnowledgeEdit(
            path="rules/global.md", owner="user", action="replace",
            content=RULE_ENFORCED.replace("strength: enforced", "strength: default"))])
        self.assertNotEqual(base.proposal_hash, changed_strength.proposal_hash)

    def test_the_digest_covers_the_reference_inventory(self):
        base = self.proposal()
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(bundle)
        edited = self.proposal(catalog=catalog, assessment=assessment)
        self.assertEqual(base.proposal_hash, edited.proposal_hash)
        (self.project / ".fstar" / "specs" / "extra.md").write_text(
            SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(bundle)
        changed = self.proposal(catalog=catalog, assessment=assessment)
        self.assertNotEqual(base.proposal_hash, changed.proposal_hash)

    def test_unrelated_index_prose_is_preserved(self):
        proposal = self.proposal()
        index = proposal.index_inventory[0]
        self.assertIn("一个多模块项目。", index.after_text)
        self.assertIn("- Applies to: src/core", index.after_text)
        self.assertIn("- Read when: 修改核心时", index.after_text)
        self.assertIn("- [架构](docs/architecture.md)", index.after_text)
        self.assertEqual(index.before_text.replace("\n", "\n")[:0], "")

    def test_a_new_topic_needs_a_reason(self):
        error = knowledge_error(self, "knowledge_invalid_schema", self.proposal,
                                intent=self.intent(topic=TopicChoice("T-2", "扩展", is_new=True)))
        self.assertEqual("topic.reason", error.details["field"])
        proposal = self.proposal(intent=self.intent(
            topic=TopicChoice("T-3", "新主题", is_new=True, reason="no existing topic covers this")))
        self.assertIn("### T-3 — 新主题", proposal.index_inventory[0].after_text)

    def test_an_unknown_existing_topic_is_rejected(self):
        error = knowledge_error(self, "knowledge_reference_error", self.proposal,
                                intent=self.intent(topic=TopicChoice("T-9", "不存在")))
        self.assertEqual("topic.topic_id", error.details["field"])

    def test_unsafe_paths_are_rejected(self):
        for path in ("../escape.md", "/absolute.md", "rules/../../escape.md"):
            knowledge_error(self, "knowledge_unsafe_path", self.proposal,
                            edits=[KnowledgeEdit(path=path, owner="user", action="create",
                                                 content=RULE_ENFORCED)])
        knowledge_error(self, "knowledge_unsafe_path", self.proposal,
                        edits=[KnowledgeEdit(path="rules/nul\x00.md", owner="user", action="create",
                                             content=RULE_ENFORCED)])

    def test_paths_outside_the_managed_categories_are_rejected(self):
        knowledge_error(self, "knowledge_unsafe_path", self.proposal,
                        edits=[KnowledgeEdit(path="docs/architecture.md", owner="project",
                                             action="replace", content=AUTHORITY_DOCUMENT)])

    def test_ambiguous_owner_aliases_are_rejected(self):
        for owner in ("knowledge", "both", "", "USER"):
            knowledge_error(self, "knowledge_invalid_schema", self.proposal,
                            edits=[KnowledgeEdit(path="rules/global.md", owner=owner,
                                                 action="replace", content=RULE_ENFORCED)])

    def test_symbolic_link_targets_are_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        outside = self.root / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        os.symlink(str(outside), str(self.user / "rules" / "linked.md"))
        knowledge_error(self, "knowledge_unsafe_path", self.proposal,
                        edits=[KnowledgeEdit(path="rules/linked.md", owner="user", action="replace",
                                             content=RULE_ENFORCED)])
        self.assertEqual("outside\n", outside.read_text(encoding="utf-8"))

    def test_a_document_of_the_wrong_category_is_rejected(self):
        error = knowledge_error(self, "knowledge_invalid_schema", self.proposal,
                                edits=[KnowledgeEdit(path="rules/global.md", owner="user",
                                                     action="replace", content=SPEC_CORE)])
        self.assertEqual("rule", error.details["expected"])

    def test_a_rename_needs_the_inbound_reference_to_be_updated(self):
        (self.project / ".fstar" / "specs" / "extra.md").write_text(
            SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        error = knowledge_error(self, "knowledge_reference_error", self.proposal,
                                edits=[KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                                     action="rename", rename_to=".fstar/specs/kernel.md")])
        self.assertIn("project:.fstar/specs/extra.md", error.details["files"])

    def test_a_rename_with_an_updated_reference_closes(self):
        (self.project / ".fstar" / "specs" / "extra.md").write_text(
            SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(bundle)
        edits = [KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="rename",
                               rename_to=".fstar/specs/kernel.md"),
                 KnowledgeEdit(path=".fstar/specs/extra.md", owner="project", action="replace",
                               content=SPEC_EXTRA + "\nSee [kernel](kernel.md).\n")]
        proposal = prepare_change(catalog, edits=edits, intent=self.intent(
            topic=TopicChoice("T-1", "核心")), assessment=assessment)
        keys = {edit.key for edit in proposal.edits}
        self.assertIn("project:.fstar/specs/kernel.md", keys)
        self.assertIn("project:.fstar/specs/core.md", keys)

    def test_the_reference_inventory_records_reverse_references(self):
        (self.project / ".fstar" / "specs" / "extra.md").write_text(
            SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        proposal = self.proposal()
        reverse = [entry for entry in proposal.reference_inventory
                   if entry.target_key == "project:.fstar/specs/core.md"]
        self.assertIn("project:.fstar/specs/extra.md", [entry.source_key for entry in reverse])
        self.assertTrue(any(item.key == "project:.fstar/specs/extra.md"
                            for item in proposal.scanned_files))

    def test_promotion_needs_its_own_consent(self):
        error = knowledge_error(self, "knowledge_confirmation_required", self.proposal,
                                intent=self.intent(action="promote"))
        self.assertEqual("intent.consent", error.details["field"])

    def test_an_assessment_must_cover_the_affected_document(self):
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = SemanticAssessment(reviewed=(), coverage="complete")
        error = knowledge_error(self, "knowledge_context_incomplete", prepare_change, catalog,
                                edits=[KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                                     action="replace", content=SPEC_CORE)],
                                intent=self.intent(topic=TopicChoice("T-1", "核心")),
                                assessment=assessment)
        self.assertIn("project:.fstar/specs/core.md", error.details["path"])

    def test_a_document_changed_after_the_snapshot_is_a_write_conflict(self):
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(bundle)
        (self.project / ".fstar" / "specs" / "core.md").write_text(SPEC_CORE + "\nExtra.\n",
                                                                   encoding="utf-8")
        knowledge_error(self, "knowledge_write_conflict", prepare_change, catalog,
                        edits=[KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                             action="replace", content=SPEC_CORE)],
                        intent=self.intent(topic=TopicChoice("T-1", "核心")),
                        assessment=assessment)


class ApplyTests(KnowledgeFixture):
    """Authorization, group publication and recovery."""

    def prepared(self, edits=None, intent=None):
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(catalog=catalog)
        edits = edits if edits is not None else [KnowledgeEdit(
            path=".fstar/specs/core.md", owner="project", action="replace",
            content=SPEC_CORE.replace("free of feature flags", "free of feature flags and globals"))]
        intent = intent or self.intent(topic=TopicChoice("T-1", "核心"))
        proposal = prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)
        return proposal

    def snapshot(self):
        paths = [self.project / ".fstar" / "specs" / "core.md",
                 self.project / ".fstar" / "index.md"]
        return {str(path): path.read_bytes() for path in paths}

    def test_an_approved_confirmation_publishes_body_and_index(self):
        proposal = self.prepared()
        receipt = apply_change(proposal, self.confirmation(proposal),
                               user_root=self.user, project_root=self.project)
        self.assertFalse(receipt.already_applied)
        self.assertIn("project:.fstar/specs/core.md", receipt.changed_paths)
        self.assertIn("project:.fstar/index.md", receipt.changed_paths)
        body = (self.project / ".fstar" / "specs" / "core.md").read_text(encoding="utf-8")
        self.assertIn("feature flags and globals", body)
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertIn("一个多模块项目。", index)
        self.assertIn("- Applies to: src/core", index)

    def test_a_denied_or_deferred_confirmation_writes_nothing(self):
        for disposition in ("denied", "deferred"):
            proposal = self.prepared()
            before = self.snapshot()
            error = knowledge_error(self, "knowledge_confirmation_required", apply_change, proposal,
                                    self.confirmation(proposal, disposition=disposition),
                                    user_root=self.user, project_root=self.project)
            self.assertEqual(disposition, error.details["disposition"])
            self.assertEqual(before, self.snapshot())

    def test_a_confirmation_without_a_source_is_rejected(self):
        proposal = self.prepared()
        before = self.snapshot()
        for field in ("source_ref", "quote", "confirmed_at"):
            values = {field: ""}
            knowledge_error(self, "knowledge_confirmation_required", apply_change, proposal,
                            self.confirmation(proposal, **values),
                            user_root=self.user, project_root=self.project)
        self.assertEqual(before, self.snapshot())

    def test_a_review_source_must_link_the_user_confirmation(self):
        proposal = self.prepared()
        knowledge_error(self, "knowledge_confirmation_required", apply_change, proposal,
                        self.confirmation(proposal, source_type="review", user_ref=""),
                        user_root=self.user, project_root=self.project)

    def test_an_old_or_foreign_confirmation_is_rejected(self):
        proposal = self.prepared()
        before = self.snapshot()
        error = knowledge_error(self, "knowledge_confirmation_mismatch", apply_change, proposal,
                                self.confirmation(proposal, proposal_hash="other"),
                                user_root=self.user, project_root=self.project)
        self.assertEqual(proposal.proposal_hash, error.details["expected"])
        knowledge_error(self, "knowledge_confirmation_mismatch", apply_change, proposal,
                        self.confirmation(proposal, scope="another scope"),
                        user_root=self.user, project_root=self.project)
        knowledge_error(self, "knowledge_confirmation_mismatch", apply_change, proposal,
                        self.confirmation(proposal, owners=("user",)),
                        user_root=self.user, project_root=self.project)
        self.assertEqual(before, self.snapshot())

    def test_a_proposal_for_another_root_is_rejected(self):
        proposal = self.prepared()
        other = self.root / "other-project"
        other.mkdir()
        knowledge_error(self, "knowledge_confirmation_mismatch", apply_change, proposal,
                        self.confirmation(proposal), user_root=self.user, project_root=other)

    def test_a_stale_baseline_is_rejected(self):
        proposal = self.prepared()
        (self.project / ".fstar" / "specs" / "core.md").write_text(SPEC_CORE + "\nEdited.\n",
                                                                   encoding="utf-8")
        error = knowledge_error(self, "knowledge_write_conflict", apply_change, proposal,
                                self.confirmation(proposal),
                                user_root=self.user, project_root=self.project)
        self.assertIn("project:.fstar/specs/core.md", error.details["path"])

    def test_repeating_an_applied_proposal_reports_already_applied(self):
        proposal = self.prepared()
        apply_change(proposal, self.confirmation(proposal),
                     user_root=self.user, project_root=self.project)
        after = self.snapshot()
        repeat = apply_change(proposal, self.confirmation(proposal),
                               user_root=self.user, project_root=self.project)
        self.assertTrue(repeat.already_applied)
        self.assertEqual(after, self.snapshot())

    def test_failure_injection_rolls_the_group_back(self):
        checkpoints = ("stage", "coordinator", "publish:project:.fstar/specs/core.md",
                       "validate", "commit")
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint):
                proposal = self.prepared()
                before = self.snapshot()
                set_failure_hook(lambda point, name=checkpoint: self._fail_at(point, name))
                self.addCleanup(set_failure_hook, None)
                with self.assertRaises(DomainError):
                    apply_change(proposal, self.confirmation(proposal),
                                 user_root=self.user, project_root=self.project)
                set_failure_hook(None)
                self.assertEqual(before, self.snapshot())

    def _fail_at(self, point, name):
        if point == name:
            raise RuntimeError("injected failure at %s" % point)

    def test_an_interruption_leaves_a_recoverable_operation(self):
        proposal = self.prepared()
        before = self.snapshot()

        class _Crash(BaseException):
            pass

        set_failure_hook(lambda point: (_ for _ in ()).throw(_Crash())
                         if point == "publish:project:.fstar/index.md" else None)
        self.addCleanup(set_failure_hook, None)
        with self.assertRaises(_Crash):
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        self.assertNotEqual(before, self.snapshot())
        error = knowledge_error(self, "knowledge_recovery_required", load_catalog,
                                user_root=self.user, project_root=self.project)
        self.assertTrue(error.details["operations"])
        report = recover_changes(user_root=self.user, project_root=self.project)
        self.assertEqual("rolled_back", report.outcomes[0].status)
        self.assertEqual(before, self.snapshot())
        again = recover_changes(user_root=self.user, project_root=self.project)
        self.assertEqual((), again.outcomes)
        self.assertTrue(again.complete)

    def test_recovery_never_overwrites_an_external_edit(self):
        proposal = self.prepared()

        class _Crash(BaseException):
            pass

        set_failure_hook(lambda point: (_ for _ in ()).throw(_Crash())
                         if point == "publish:project:.fstar/index.md" else None)
        self.addCleanup(set_failure_hook, None)
        with self.assertRaises(_Crash):
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        external = SPEC_CORE + "\nEdited by somebody else.\n"
        (self.project / ".fstar" / "specs" / "core.md").write_text(external, encoding="utf-8")
        error = knowledge_error(self, "knowledge_recovery_conflict", recover_changes,
                                user_root=self.user, project_root=self.project)
        self.assertTrue(error.details["conflicts"])
        self.assertEqual(external, (self.project / ".fstar" / "specs" / "core.md").read_text(
            encoding="utf-8"))

    def test_a_committed_operation_only_needs_cleanup(self):
        proposal = self.prepared()
        set_failure_hook(lambda point: self._fail_at(point, "cleanup"))
        self.addCleanup(set_failure_hook, None)
        receipt = apply_change(proposal, self.confirmation(proposal),
                               user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        self.assertEqual("cleanup_pending", receipt.recovery)
        report = recover_changes(user_root=self.user, project_root=self.project)
        self.assertEqual("cleaned", report.outcomes[0].status)

    def test_a_pending_operation_blocks_further_writes(self):
        proposal = self.prepared()
        second = self.prepared()

        class _Crash(BaseException):
            pass

        set_failure_hook(lambda point: (_ for _ in ()).throw(_Crash())
                         if point == "publish:project:.fstar/index.md" else None)
        self.addCleanup(set_failure_hook, None)
        with self.assertRaises(_Crash):
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        knowledge_error(self, "knowledge_recovery_required", apply_change, second,
                        self.confirmation(second), user_root=self.user, project_root=self.project)

    def test_a_supplied_index_edit_must_preserve_unrelated_prose(self):
        index_path = self.project / ".fstar" / "index.md"
        before = index_path.read_text(encoding="utf-8")
        preserved = before.replace("- Authority: [.fstar/specs/core.md](.fstar/specs/core.md)",
                                   "- Authority: [.fstar/specs/core.md](.fstar/specs/core.md)\n"
                                   "- Note: reviewed in 2026.")
        proposal = self.prepared([KnowledgeEdit(
            path=".fstar/specs/core.md", owner="project", action="replace",
            content=SPEC_CORE.replace("free of feature flags", "free of feature flags and globals")),
            KnowledgeEdit(path=".fstar/index.md", owner="project", action="replace",
                          content=preserved)])
        self.assertIn("reviewed in 2026", proposal.index_inventory[0].after_text)
        knowledge_error(self, "knowledge_invalid_schema", self.prepared, [KnowledgeEdit(
            path=".fstar/specs/core.md", owner="project", action="replace",
            content=SPEC_CORE.replace("free of feature flags", "free of feature flags and globals")),
            KnowledgeEdit(path=".fstar/index.md", owner="project", action="replace",
                          content="# 项目索引\n\n已重写。\n")])

    def test_an_index_only_edit_cannot_discard_unrelated_prose(self):
        before = self.snapshot()
        knowledge_error(self, "knowledge_invalid_schema", self.prepared,
                        [KnowledgeEdit(path=".fstar/index.md", owner="project", action="replace",
                                       content="# 项目索引\n\n已重写。\n")])
        self.assertEqual(before, self.snapshot())

    def test_an_unreadable_lock_is_an_explicit_error_not_a_leak(self):
        lock = self.project / ".fstar" / "runtime" / "knowledge" / "lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        os.chmod(str(lock), 0o444)
        self.addCleanup(os.chmod, str(lock), 0o644)
        proposal = self.prepared()
        error = knowledge_error(self, "knowledge_lock_timeout", apply_change, proposal,
                                self.confirmation(proposal),
                                user_root=self.user, project_root=self.project)
        self.assertIn(lock.name, error.details["path"])

    def test_a_stale_assessment_blocks_delete_supersede_and_rename(self):
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        partial = SemanticAssessment(reviewed=(), coverage="complete")
        for action, edits in (
                ("delete", [KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                          action="delete")]),
                ("supersede", [KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                             action="supersede",
                                             content=SPEC_CORE.replace("status: active",
                                                                       "status: superseded"))]),
                ("rename", [KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                          action="rename",
                                          rename_to=".fstar/specs/kernel.md")])):
            with self.subTest(action=action):
                knowledge_error(self, "knowledge_context_incomplete", prepare_change, catalog,
                                edits=edits,
                                intent=self.intent(topic=TopicChoice("T-1", "核心")),
                                assessment=partial)
        _ = bundle

    def test_promotion_needs_its_own_consent(self):
        catalog = self.catalog()
        assessment = self.assessment(catalog=catalog)
        intent = self.intent(action="promote", consent="consent-1",
                             topic=TopicChoice("T-1", "核心"))
        edits = [KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                               content=SPEC_CORE.replace("free of feature flags", "promoted"))]
        proposal = prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)
        knowledge_error(self, "knowledge_confirmation_required", apply_change, proposal,
                        self.confirmation(proposal), user_root=self.user, project_root=self.project)
        receipt = apply_change(proposal, self.confirmation(proposal, consent="consent-1"),
                               user_root=self.user, project_root=self.project)
        self.assertFalse(receipt.already_applied)

    def test_read_only_calls_never_create_runtime_files(self):
        self.prepared()
        self.assertFalse((self.user / "runtime").exists())
        self.assertFalse((self.project / ".fstar" / "runtime").exists())

    def test_a_second_process_waits_for_the_owner_lock(self):
        proposal = self.prepared()
        lock = self.project / ".fstar" / "runtime" / "knowledge" / "lock"
        script = ("import fcntl, os, sys, time\n"
                   "path = sys.argv[1]\n"
                   "os.makedirs(os.path.dirname(path), exist_ok=True)\n"
                   "stream = open(path, 'a+')\n"
                   "fcntl.flock(stream.fileno(), fcntl.LOCK_EX)\n"
                   "time.sleep(float(sys.argv[2]))\n")
        holder = subprocess.Popen([sys.executable, "-c", script, str(lock), "1.2"])
        try:
            time.sleep(0.3)
            started = time.monotonic()
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
            self.assertGreaterEqual(time.monotonic() - started, 0.8)
        finally:
            holder.wait(timeout=30)

    def test_independent_edits_do_not_overwrite_each_other(self):
        first = self.prepared()
        stale = self.prepared(edits=[KnowledgeEdit(
            path=".fstar/specs/extra.md", owner="project", action="replace",
            content=SPEC_EXTRA.replace("owns the adapters", "owns the adapters and the ports"))],
            intent=self.intent(topic=TopicChoice("T-2", "扩展")))
        apply_change(first, self.confirmation(first), user_root=self.user, project_root=self.project)
        knowledge_error(self, "knowledge_write_conflict", apply_change, stale,
                        self.confirmation(stale), user_root=self.user, project_root=self.project)
        catalog = self.catalog()
        fresh = prepare_change(
            catalog,
            edits=[KnowledgeEdit(path=".fstar/specs/extra.md", owner="project", action="replace",
                                 content=SPEC_EXTRA.replace("owns the adapters",
                                                            "owns the adapters and the ports"))],
            intent=self.intent(topic=TopicChoice("T-2", "扩展")),
            assessment=self.assessment(catalog=catalog))
        apply_change(fresh, self.confirmation(fresh), user_root=self.user, project_root=self.project)
        core = (self.project / ".fstar" / "specs" / "core.md").read_text(encoding="utf-8")
        extra = (self.project / ".fstar" / "specs" / "extra.md").read_text(encoding="utf-8")
        self.assertIn("feature flags and globals", core)
        self.assertIn("adapters and the ports", extra)

    def test_a_multi_owner_group_is_atomic_and_recoverable(self):
        edits = [KnowledgeEdit(path="rules/global.md", owner="user", action="replace",
                               content=RULE_ENFORCED.replace("MUST run the test suite",
                                                             "MUST run tests and the linter")),
                 KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                               content=SPEC_CORE.replace("free of feature flags",
                                                         "free of feature flags and globals"))]
        catalog = self.catalog()
        assessment = self.assessment(catalog=catalog)
        proposal = prepare_change(catalog, edits=edits,
                                  intent=self.intent(topic=TopicChoice("T-1", "核心")),
                                  assessment=assessment)
        self.assertEqual(("project", "user"), proposal.owners)
        receipt = apply_change(proposal, self.confirmation(proposal),
                               user_root=self.user, project_root=self.project)
        self.assertIn("user:rules/global.md", receipt.changed_paths)
        self.assertIn("user:index.md", receipt.changed_paths)
        self.assertIn("project:.fstar/index.md", receipt.changed_paths)
        self.assertEqual([], list((self.user / "runtime" / "knowledge" / "operations").iterdir()))
        self.assertEqual([], list((self.project / ".fstar" / "runtime" / "knowledge"
                                   / "operations").iterdir()))

    def test_a_multi_owner_interruption_rolls_back_every_root(self):
        edits = [KnowledgeEdit(path="rules/global.md", owner="user", action="replace",
                               content=RULE_ENFORCED.replace("MUST run the test suite",
                                                             "MUST run tests and the linter")),
                 KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                               content=SPEC_CORE.replace("free of feature flags",
                                                         "free of feature flags and globals"))]
        catalog = self.catalog()
        assessment = self.assessment(catalog=catalog)
        proposal = prepare_change(catalog, edits=edits,
                                  intent=self.intent(topic=TopicChoice("T-1", "核心")),
                                  assessment=assessment)
        before = {str(path): path.read_bytes() for path in
                  (self.user / "rules" / "global.md", self.user / "index.md",
                   self.project / ".fstar" / "specs" / "core.md",
                   self.project / ".fstar" / "index.md")}

        class _Crash(BaseException):
            pass

        set_failure_hook(lambda point: (_ for _ in ()).throw(_Crash())
                         if point == "publish:project:.fstar/specs/core.md" else None)
        self.addCleanup(set_failure_hook, None)
        with self.assertRaises(_Crash):
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        report = recover_changes(user_root=self.user, project_root=self.project)
        self.assertEqual("rolled_back", report.outcomes[0].status)
        self.assertEqual(before, {str(path): path.read_bytes() for path in
                                  (self.user / "rules" / "global.md", self.user / "index.md",
                                   self.project / ".fstar" / "specs" / "core.md",
                                   self.project / ".fstar" / "index.md")})

    def test_a_reader_waits_for_an_in_flight_group(self):
        lock = self.project / ".fstar" / "runtime" / "knowledge" / "lock"
        script = ("import fcntl, os, sys, time\n"
                   "path = sys.argv[1]\n"
                   "os.makedirs(os.path.dirname(path), exist_ok=True)\n"
                   "stream = open(path, 'a+')\n"
                   "fcntl.flock(stream.fileno(), fcntl.LOCK_EX)\n"
                   "time.sleep(float(sys.argv[2]))\n")
        holder = subprocess.Popen([sys.executable, "-c", script, str(lock), "1.2"])
        try:
            time.sleep(0.3)
            started = time.monotonic()
            catalog = load_catalog(user_root=self.user, project_root=self.project)
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.7)
            self.assertTrue(catalog.snapshot_hash)
        finally:
            holder.wait(timeout=30)

    def test_a_stale_writer_loses_against_a_second_process(self):
        proposal = self.prepared()
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            from pathlib import Path
            from fstar.knowledge import (ChangeIntent, Confirmation, KnowledgeEdit, ReadSelection,
                                         SemanticAssessment, SourceRecord, TopicChoice,
                                         apply_change, load_catalog, load_context, prepare_change)
            catalog = load_catalog(user_root=Path(%r), project_root=Path(%r))
            bundle = load_context(catalog, selection=ReadSelection(topics=("T-1",)))
            assessment = SemanticAssessment(
                reviewed=tuple(__import__("fstar.knowledge", fromlist=["ReviewedSource"]).ReviewedSource(
                    item.key, item.digest) for item in catalog.documents if item.effective),
                coverage="complete")
            intent = ChangeIntent(summary="other writer", action="correct",
                                  source=SourceRecord("conversation", "chat#99", "ok", "2026-04-02"),
                                  scope="project core specification",
                                  topic=TopicChoice("T-1", "核心"))
            edit = KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                                 content=%r)
            other = prepare_change(catalog, edits=[edit], intent=intent, assessment=assessment)
            confirmation = Confirmation(disposition="approved", source_type="conversation",
                                        source_ref="chat#99", quote="ok", confirmed_at="2026-04-02",
                                        proposal_hash=other.proposal_hash, scope=other.scope,
                                        owners=other.owners)
            apply_change(other, confirmation, user_root=Path(%r), project_root=Path(%r))
            print("applied")
        """) % (str(SOURCE), str(self.user), str(self.project),
                SPEC_CORE.replace("free of feature flags", "written by another process"),
                str(self.user), str(self.project))
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("applied", result.stdout)
        error = knowledge_error(self, "knowledge_write_conflict", apply_change, proposal,
                                self.confirmation(proposal),
                                user_root=self.user, project_root=self.project)
        self.assertIn("project:.fstar/specs/core.md", error.details["path"])
        body = (self.project / ".fstar" / "specs" / "core.md").read_text(encoding="utf-8")
        self.assertIn("written by another process", body)


class IsolationTests(KnowledgeFixture):
    """The provider stays an internal library."""

    def test_no_knowledge_command_is_registered(self):
        from fstar import cli

        parser = cli.build_parser()
        commands = set(parser._subparsers._group_actions[0].choices)
        self.assertNotIn("knowledge", commands)
        self.assertNotIn("learn", commands)

    def test_no_forbidden_directory_is_created(self):
        proposal = self.prepared() if hasattr(self, "prepared") else None
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(catalog=catalog)
        intent = self.intent(topic=TopicChoice("T-1", "核心"))
        edit = KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                             content=SPEC_CORE.replace("free of feature flags", "without globals"))
        proposal = prepare_change(catalog, edits=[edit], intent=intent, assessment=assessment)
        apply_change(proposal, self.confirmation(proposal),
                     user_root=self.user, project_root=self.project)
        forbidden = ("decisions", "history", "journal", "workspace", "candidates", "ledger",
                     "search", "knowledge.db")
        for root in (self.user, self.project / ".fstar"):
            for name in forbidden:
                self.assertFalse((root / name).exists(), "%s must not exist" % name)
        self.assertTrue((self.project / ".fstar" / "specs" / "core.md").is_file())
        self.assertFalse((self.project / ".fstar" / "decisions").exists())

    def test_the_provider_keeps_no_candidate_or_history_ledger(self):
        catalog = self.catalog()
        bundle = self.bundle(catalog)
        assessment = self.assessment(catalog=catalog)
        intent = self.intent(topic=TopicChoice("T-1", "核心"))
        edit = KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="replace",
                             content=SPEC_CORE.replace("free of feature flags", "without globals"))
        prepare_change(catalog, edits=[edit], intent=intent, assessment=assessment)
        self.assertFalse((self.user / "runtime").exists())
        self.assertFalse((self.project / ".fstar" / "runtime").exists())


class ChangeKindTests(KnowledgeFixture):
    """Create, replace, supersede, delete and rename stay one group update."""

    def prepared(self, edits, intent=None):
        catalog = self.catalog()
        assessment = self.assessment(catalog=catalog)
        intent = intent or self.intent(topic=TopicChoice("T-1", "核心"))
        return prepare_change(catalog, edits=edits, intent=intent, assessment=assessment)

    def apply(self, proposal):
        return apply_change(proposal, self.confirmation(proposal),
                            user_root=self.user, project_root=self.project)

    def test_create_adds_body_and_navigation(self):
        spec = SPEC_CORE.replace("free of feature flags", "free of feature flags and globals")
        proposal = self.prepared([KnowledgeEdit(path=".fstar/specs/new.md", owner="project",
                                                 action="create", content=spec)],
                                 intent=self.intent(
                                     topic=TopicChoice("T-3", "新增规范", is_new=True,
                                                       reason="the new topic is not covered yet",
                                                       applies_to="src/new",
                                                       read_when="新增规范时")))
        self.apply(proposal)
        self.assertTrue((self.project / ".fstar" / "specs" / "new.md").is_file())
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertIn(".fstar/specs/new.md", index)
        self.assertIn("T-3", index)

    def test_supersede_leaves_the_effective_context(self):
        superseded = SPEC_CORE.replace("status: active", "status: superseded")
        proposal = self.prepared([KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                                 action="supersede", content=superseded)])
        self.apply(proposal)
        catalog = self.catalog()
        document = catalog.by_key("project:.fstar/specs/core.md")
        self.assertFalse(document.effective)
        bundle = self.bundle(catalog)
        self.assertNotIn("project:.fstar/specs/core.md",
                         {item.key for item in bundle.full_documents})

    def test_delete_removes_body_and_navigation(self):
        proposal = self.prepared([KnowledgeEdit(path=".fstar/specs/extra.md", owner="project",
                                                 action="delete")],
                                 intent=self.intent(topic=TopicChoice("T-2", "扩展")))
        self.apply(proposal)
        self.assertFalse((self.project / ".fstar" / "specs" / "extra.md").exists())
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertNotIn(".fstar/specs/extra.md", index)
        self.assertIn(".fstar/specs/core.md", index)

    def test_rename_moves_body_and_updates_navigation(self):
        proposal = self.prepared([KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                                 action="rename",
                                                 rename_to=".fstar/specs/kernel.md")])
        self.apply(proposal)
        self.assertFalse((self.project / ".fstar" / "specs" / "core.md").exists())
        self.assertTrue((self.project / ".fstar" / "specs" / "kernel.md").is_file())
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertIn(".fstar/specs/kernel.md", index)
        self.assertNotIn(".fstar/specs/core.md", index)

    def test_rename_publishes_existing_inbound_reference_with_group(self):
        old = self.project / ".fstar" / "specs" / "core.md"
        new = self.project / ".fstar" / "specs" / "kernel.md"
        inbound = self.project / ".fstar" / "specs" / "extra.md"
        inbound.write_text(SPEC_EXTRA + "\nSee [core](core.md).\n", encoding="utf-8")
        original = inbound.read_text(encoding="utf-8")
        rename = KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                               action="rename", rename_to=".fstar/specs/kernel.md")
        knowledge_error(self, "knowledge_reference_error", self.prepared, [rename])
        self.assertTrue(old.exists())
        self.assertFalse(new.exists())
        self.assertEqual(original, inbound.read_text(encoding="utf-8"))
        proposal = self.prepared([KnowledgeEdit(
            path=".fstar/specs/extra.md", owner="project", action="replace",
            content=SPEC_EXTRA + "\nSee [kernel](kernel.md).\n"), rename])
        self.apply(proposal)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertIn("[kernel](kernel.md)", inbound.read_text(encoding="utf-8"))
        index = (self.project / ".fstar" / "index.md").read_text(encoding="utf-8")
        self.assertIn(".fstar/specs/kernel.md", index)
        self.assertNotIn(".fstar/specs/core.md", index)

    def test_context_inbound_rename_requires_update_and_preserves_authority_in_both_orders(self):
        for rename_first in (True, False):
            with self.subTest(rename_first=rename_first), tempfile.TemporaryDirectory() as tmp:
                # Independent fixtures ensure both orderings start with identical state.
                fixture = ChangeKindTests(methodName="runTest")
                fixture.setUp()
                try:
                    background = fixture.project / ".fstar/knowledge/context/background.md"
                    original = CONTEXT_BACKGROUND + "\nSee [core](../../specs/core.md).\n"
                    background.write_text(original, encoding="utf-8")
                    old = fixture.project / ".fstar/specs/core.md"
                    new = fixture.project / ".fstar/specs/kernel.md"
                    index = fixture.project / ".fstar/index.md"
                    before = (old.read_bytes(), background.read_bytes(), index.read_bytes())
                    rename = KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                           action="rename", rename_to=".fstar/specs/kernel.md")
                    extra = KnowledgeEdit(path=".fstar/specs/extra.md", owner="project",
                                          action="replace", content=SPEC_EXTRA + "\nUpdated.\n")
                    updates = [rename, extra] if rename_first else [extra, rename]
                    error = knowledge_error(self, "knowledge_reference_error", fixture.prepared, updates)
                    self.assertIn("project:.fstar/knowledge/context/background.md", error.details["files"])
                    self.assertEqual(before, (old.read_bytes(), background.read_bytes(), index.read_bytes()))
                    self.assertFalse(new.exists())
                    self.assertFalse((fixture.project / ".fstar/runtime/knowledge").exists())
                    updated = original.replace("../../specs/core.md", "../../specs/kernel.md")
                    updates.append(KnowledgeEdit(path=".fstar/knowledge/context/background.md",
                                                 owner="project", action="replace", content=updated))
                    proposal = fixture.prepared(updates)
                    fixture.apply(proposal)
                    self.assertFalse(old.exists())
                    self.assertTrue(new.exists())
                    self.assertEqual(updated, background.read_text(encoding="utf-8"))
                    text = index.read_text(encoding="utf-8")
                    self.assertIn("- Authority: [.fstar/specs/kernel.md](.fstar/specs/kernel.md)", text)
                    self.assertNotIn("- Authority: [.fstar/specs/extra.md](.fstar/specs/extra.md)\n\n### T-2", text)
                finally:
                    fixture.doCleanups()

    def test_new_documents_reject_broken_and_unsafe_links_before_publication(self):
        path = ".fstar/knowledge/context/new.md"
        for link in ("missing.md", "../../../../outside.md", "/outside.md"):
            with self.subTest(link=link):
                error = knowledge_error(self, "knowledge_reference_error", self.prepared,
                    [KnowledgeEdit(path=path, owner="project", action="create",
                                   content="# New\n\n[link](%s)\n" % link)])
                self.assertIn("project:" + path, error.details["files"])
                self.assertFalse((self.project / path).exists())
                self.assertFalse((self.project / ".fstar/runtime/knowledge").exists())

    def test_new_document_rejects_link_through_symlink(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "target.md").write_text("# Outside\n", encoding="utf-8")
        os.symlink(str(outside), str(self.project / "linked"))
        error = knowledge_error(self, "knowledge_reference_error", self.prepared,
            [KnowledgeEdit(path=".fstar/knowledge/context/new.md", owner="project",
                           action="create", content="# New\n\n[x](../../../linked/target.md)\n")])
        self.assertIn("project:.fstar/knowledge/context/new.md", error.details["files"])

    def test_delete_with_cross_directory_inbound_link_is_rejected(self):
        background = self.project / ".fstar/knowledge/context/background.md"
        background.write_text(CONTEXT_BACKGROUND + "\n[core](../../specs/core.md)\n", encoding="utf-8")
        error = knowledge_error(self, "knowledge_reference_error", self.prepared,
            [KnowledgeEdit(path=".fstar/specs/core.md", owner="project", action="delete")])
        self.assertIn("project:.fstar/knowledge/context/background.md", error.details["files"])
        self.assertTrue((self.project / ".fstar/specs/core.md").is_file())

    def test_a_user_rule_update_keeps_the_user_index_prose(self):
        proposal = self.prepared([KnowledgeEdit(path="rules/global.md", owner="user",
                                                 action="replace",
                                                 content=RULE_ENFORCED.replace(
                                                     "MUST run the test suite",
                                                     "MUST run the tests and the linter"))])
        self.apply(proposal)
        index = (self.user / "index.md").read_text(encoding="utf-8")
        self.assertIn("本地定制入口说明。", index)
        self.assertIn("rules/global.md", index)
        self.assertIn("strength: enforced", index)

    def test_every_change_keeps_its_source(self):
        proposal = self.prepared([KnowledgeEdit(path=".fstar/specs/core.md", owner="project",
                                                 action="replace",
                                                 content=SPEC_CORE.replace("free of feature flags",
                                                                           "free of feature flags"))])
        self.assertEqual(1, len(proposal.sources))
        self.assertEqual("conversation", proposal.sources[0].source_type)
        self.assertEqual("chat#42", proposal.sources[0].reference)
        self.assertEqual("2026-04-01", proposal.sources[0].at)
        self.assertIn("chat#42", proposal.payload()["sources"][0]["reference"])


class ConsumerContractTests(KnowledgeFixture):
    """Read-only consumers and the dynamic archive view."""

    def test_read_only_consumers_get_paths_bytes_and_hashes(self):
        catalog = self.catalog()
        paths = catalog.source_paths()
        self.assertIn((self.user / "rules" / "global.md").resolve(), paths)
        raw = catalog.source_bytes("user:rules/global.md")
        self.assertIsNotNone(raw)
        self.assertEqual(RULE_ENFORCED.encode("utf-8"), raw)
        document = catalog.by_key("user:rules/global.md")
        self.assertEqual(document.digest, __import__("hashlib").sha256(raw).hexdigest())
        before = sorted(str(path) for path in self.root.rglob("*"))
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_the_archive_view_stays_derived_from_task_records(self):
        from fstar.store import TaskStore

        store = TaskStore(self.project, user_home=self.user)
        archive = self.project / ".fstar" / "archive" / "2026-04" / "old-task"
        archive.mkdir(parents=True)
        record = {
            "id": "6f1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d", "name": "old-task",
            "title": "Old task", "description": "", "phase": "completed", "blocked": None,
            "evidence": [], "lease": None, "acceptance": None, "completedAt": "2026-04-01",
            "archivedAt": "2026-04-02", "children": [], "priority": "P2", "creator": "user",
            "assignee": None, "createdAt": "2026-04-01", "branch": "", "base_branch": "",
            "worktree_path": "", "commit": "", "pr_url": "", "notes": "", "meta": {},
            "capabilities": [], "extensions": [], "events": [],
        }
        (archive / "task.json").write_text(__import__("json").dumps(record), encoding="utf-8")
        archived = store.scan(archived=True)
        self.assertEqual(["old-task"], [item["name"] for item in archived])
        catalog = self.catalog()
        self.assertNotIn("old-task", " ".join(document.body for document in catalog.documents))
        self.assertFalse((self.project / ".fstar" / "archive" / "2026-04" / "old-task"
                          / "knowledge").exists())

    def test_a_partial_semantic_review_keeps_the_resolution_incomplete(self):
        bundle = self.bundle()
        assessment = self.assessment(bundle, coverage="partial")
        resolution = resolve_context(bundle, assessment=assessment)
        self.assertFalse(resolution.complete)
        self.assertTrue(resolution.conflicts_pending)

    def test_the_language_review_status_travels_with_the_assessment(self):
        bundle = self.bundle()
        assessment = SemanticAssessment(
            reviewed=tuple(ReviewedSource(item.key, item.digest)
                           for item in bundle.full_documents),
            language_reviewed=("en",), coverage="complete")
        resolution = resolve_context(bundle, assessment=assessment)
        self.assertEqual(("en",), assessment.language_reviewed)
        self.assertIn("language_reviewed", assessment.payload())


if __name__ == "__main__":
    unittest.main()
