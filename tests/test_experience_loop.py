"""Experience-loop contract tests for the fstar knowledge provider.

Closed loop on temporary fixtures only: deposit (authorized learn) →
scope-filtered reading → user correction through the same proposal pipeline →
retirement/expiry no longer injects.  No real user knowledge or configuration
is touched, nothing is learned automatically and no direct write path exists
outside ``prepare_change``/``apply_change``.
"""

import tempfile
import unittest
from pathlib import Path

from fstar.knowledge import (Applicability, ChangeIntent, Confirmation, KnowledgeEdit,
                             ReadSelection, ReviewedSource, SemanticAssessment, SourceRecord,
                             apply_change, load_catalog, load_context, parse_knowledge,
                             prepare_change, set_failure_hook)
from fstar.models import DomainError
from fstar.project import (DocumentReference, ProjectContext, TopicReference,
                           initialize_project, initialize_user)

RULE_ENFORCED = """---
schema: fstar.knowledge.v1
type: rule
status: active
strength: enforced
---

# Global rule

MUST run the test suite before reporting work as done.
"""

# Old-schema memory: no experience-loop fields at all.
MEMORY_PLAIN = """---
schema: fstar.knowledge.v1
type: memory
status: active
kind: preference
trust: confirmed
---

# Plain preference

Prefer short status updates.
"""

MEMORY_SUPERSEDED = """---
schema: fstar.knowledge.v1
type: memory
status: superseded
kind: lesson
trust: confirmed
---

# Stopped lesson

An already retired lesson.
"""

SPEC_CORE = """---
schema: fstar.knowledge.v1
type: spec
status: active
---

# Core specification

Keep the core module free of feature flags.
"""

CONTEXT_BACKGROUND = "# Background\n\nThe project keeps storage adapters in one module.\n"
AUTHORITY_DOCUMENT = "# Architecture\n\nThe core module owns the domain model.\n"


def memory_document(title, *, status="active", kind="preference", trust="confirmed",
                    scope=None, confidence=None, source=None, expires=None,
                    conditions=None, body=None):
    """Build one memory document; ``None`` fields are simply omitted."""

    lines = ["---", "schema: fstar.knowledge.v1", "type: memory",
             "status: %s" % status, "kind: %s" % kind, "trust: %s" % trust]
    for key, value in (("scope", scope), ("confidence", confidence), ("source", source),
                       ("expires", expires), ("conditions", conditions)):
        if value is not None:
            lines.append("%s: %s" % (key, value))
    lines.extend(["---", "", "# %s" % title, "", body or ("Body of %s." % title), ""])
    return "\n".join(lines)


def knowledge_error(testcase, code, callable_, *args, **kwargs):
    with testcase.assertRaises(DomainError) as error:
        callable_(*args, **kwargs)
    testcase.assertEqual(code, error.exception.code)
    return error.exception


class ExperienceLoopFixture(unittest.TestCase):
    """Isolated user root and project root, mirroring the knowledge fixtures."""

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
        (self.project / ".fstar" / "specs" / "core.md").write_text(SPEC_CORE, encoding="utf-8")
        (self.project / ".fstar" / "knowledge" / "context" / "background.md").write_text(
            CONTEXT_BACKGROUND, encoding="utf-8")
        initialize_project(self.project, self.user, context=ProjectContext(
            "一个多模块项目。",
            topics=(TopicReference("T-1", "核心", "src/core", "修改核心时", ".fstar/specs/core.md"),),
            authority_refs=(DocumentReference("架构", "docs/architecture.md"),),
            knowledge_refs=(DocumentReference("背景", ".fstar/knowledge/context/background.md"),)))
        initialize_user(self.user)
        (self.user / "rules").mkdir()
        (self.user / "memory").mkdir()
        (self.user / "rules" / "global.md").write_text(RULE_ENFORCED, encoding="utf-8")
        (self.user / "memory" / "plain.md").write_text(MEMORY_PLAIN, encoding="utf-8")
        (self.user / "memory" / "old.md").write_text(MEMORY_SUPERSEDED, encoding="utf-8")
        (self.user / "index.md").write_text(
            "# fstar 用户索引\n\n## Rules\n\n- [全局规则](rules/global.md) — strength: enforced\n\n"
            "## Memory\n\n- [普通偏好](memory/plain.md) — kind: preference\n", encoding="utf-8")

    # -- helpers ---------------------------------------------------------
    def catalog(self):
        return load_catalog(user_root=self.user, project_root=self.project)

    def bundle(self, catalog=None, **kwargs):
        catalog = catalog or self.catalog()
        selection = kwargs.pop("selection", ReadSelection(topics=("T-1",)))
        return load_context(catalog, selection=selection, **kwargs)

    def assessment(self, catalog):
        reviewed = [ReviewedSource(document.key, document.digest)
                    for document in catalog.documents if document.effective]
        reviewed.extend(ReviewedSource(index.key, index.digest) for index in catalog.indexes)
        return SemanticAssessment(reviewed=tuple(reviewed))

    def intent(self, **kwargs):
        values = {"summary": "record a scoped experience", "action": "create",
                  "source": SourceRecord("conversation", "chat#s6", "please remember this", "2026-11-21"),
                  "scope": "user experience memory"}
        values.update(kwargs)
        return ChangeIntent(**values)

    def confirmation(self, proposal, **kwargs):
        values = {"disposition": "approved", "source_type": "conversation",
                  "source_ref": "chat#s6", "quote": "please remember this",
                  "confirmed_at": "2026-11-21", "proposal_hash": proposal.proposal_hash,
                  "scope": proposal.scope, "owners": proposal.owners,
                  "consent": proposal.consent}
        values.update(kwargs)
        return Confirmation(**values)

    def prepared(self, edits, intent=None):
        catalog = self.catalog()
        return prepare_change(catalog, edits=edits, intent=intent or self.intent(),
                              assessment=self.assessment(catalog))

    def apply(self, proposal):
        return apply_change(proposal, self.confirmation(proposal),
                            user_root=self.user, project_root=self.project)

    def learn(self, relative, text, **intent_kwargs):
        """Deposit one memory through the authorized pipeline."""

        proposal = self.prepared([KnowledgeEdit(path=relative, owner="user",
                                                action="create", content=text)],
                                 intent=self.intent(**intent_kwargs))
        receipt = self.apply(proposal)
        return proposal, receipt

    def injected_keys(self, **kwargs):
        bundle = self.bundle(**kwargs)
        return ({document.key for document in bundle.full_documents},
                {item.key: item.reason for item in bundle.excluded}, bundle)


class FieldTests(ExperienceLoopFixture):
    """S6-A01: new fields land, old documents keep parsing."""

    def test_new_fields_roundtrip_through_the_authorized_pipeline(self):
        text = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="inferred",
            source="task-payments-042", expires="2030-01-01",
            conditions="适用于旧版部署流程", body="Use blue/green deployments for payments.")
        _, receipt = self.learn("memory/deployment.md", text)
        self.assertIn("user:memory/deployment.md", receipt.changed_paths)

        on_disk = (self.user / "memory" / "deployment.md").read_text(encoding="utf-8")
        self.assertIn("scope: scenario:payments", on_disk)
        self.assertIn("confidence: inferred", on_disk)
        self.assertIn("source: task-payments-042", on_disk)
        self.assertIn("expires: 2030-01-01", on_disk)
        self.assertIn("conditions: 适用于旧版部署流程", on_disk)

        document = parse_knowledge(on_disk, path="memory/deployment.md")
        self.assertEqual("scenario:payments", document.scope)
        self.assertEqual("inferred", document.confidence)
        self.assertEqual("task-payments-042", document.source)
        self.assertEqual("2030-01-01", document.expires)
        self.assertEqual("适用于旧版部署流程", document.conditions)

        catalog = self.catalog()
        entry = catalog.by_key("user:memory/deployment.md")
        self.assertTrue(entry.effective)
        self.assertEqual("scenario:payments", entry.scope)
        self.assertEqual("inferred", entry.confidence)

    def test_old_documents_without_new_fields_keep_parsing_and_loading(self):
        document = parse_knowledge(MEMORY_PLAIN, path="memory/plain.md")
        self.assertIsNone(document.scope)
        self.assertIsNone(document.confidence)
        self.assertIsNone(document.source)
        self.assertIsNone(document.expires)
        self.assertIsNone(document.conditions)
        catalog = self.catalog()
        self.assertTrue(catalog.by_key("user:memory/plain.md").effective)
        keys, _, bundle = self.injected_keys()
        self.assertIn("user:memory/plain.md", keys)
        self.assertTrue(bundle.complete)

    def test_invalid_field_values_are_rejected(self):
        cases = (
            ("scope", "global"), ("scope", "scenario:"), ("scope", "scenario:two words"),
            ("scope", "item:x y"), ("scope", "personal:extra"),
            ("confidence", "guessed"),
            ("expires", "2026-1-1"), ("expires", "2026-13-01"), ("expires", "not-a-date"),
            ("expires", "2026-02-30"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                text = memory_document("Bad", **{field: value})
                error = knowledge_error(self, "knowledge_invalid_schema", parse_knowledge, text,
                                        path="memory/bad.md")
                self.assertEqual(field, error.details["field"])
        # Empty scalars are rejected by the frontmatter parser itself.
        for field in ("source", "conditions"):
            with self.subTest(field=field, value="empty"):
                text = memory_document("Bad", **{field: " "})
                knowledge_error(self, "knowledge_invalid_schema", parse_knowledge, text,
                                path="memory/bad.md")

    def test_experience_fields_are_memory_only(self):
        text = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: default\nscope: personal\n---\n\n# Title\n")
        error = knowledge_error(self, "knowledge_invalid_schema", parse_knowledge, text,
                                path="rules/bad.md")
        self.assertEqual("scope", error.details["field"])
        text = ("---\nschema: fstar.knowledge.v1\ntype: spec\nstatus: active\n"
                "confidence: verified\n---\n\n# Title\n")
        error = knowledge_error(self, "knowledge_invalid_schema", parse_knowledge, text,
                                path=".fstar/specs/bad.md")
        self.assertEqual("confidence", error.details["field"])

    def test_pipeline_rejects_invalid_new_field_content(self):
        text = memory_document("Bad", expires="not-a-date")
        error = knowledge_error(self, "knowledge_invalid_schema", self.prepared,
                                [KnowledgeEdit(path="memory/bad.md", owner="user",
                                               action="create", content=text)])
        self.assertEqual("expires", error.details["field"])
        self.assertFalse((self.user / "memory" / "bad.md").exists())


class ScopeFilteringTests(ExperienceLoopFixture):
    """S6-A02: retrieval filters by the current reading scope."""

    def setUp(self):
        super().setUp()
        self.learn("memory/personal.md",
                   memory_document("Personal lesson", scope="personal",
                                   confidence="verified", body="Personal habit."))
        self.learn("memory/payments.md",
                   memory_document("Payments lesson", scope="scenario:payments",
                                   confidence="verified", body="Payments habit."))
        self.learn("memory/task42.md",
                   memory_document("Task lesson", scope="item:task-42",
                                   confidence="explicit-request", body="Task habit."))

    def test_scope_filtering_injects_matches_and_excludes_the_rest(self):
        keys, excluded, bundle = self.injected_keys(selection=ReadSelection(
            topics=("T-1",), scope=("scenario:payments",)))
        self.assertIn("user:memory/plain.md", keys)          # absent scope applies broadly
        self.assertIn("user:memory/personal.md", keys)       # explicit personal too
        self.assertIn("user:memory/payments.md", keys)
        self.assertNotIn("user:memory/task42.md", keys)
        self.assertIn("does not match the current reading scope",
                      excluded["user:memory/task42.md"])
        self.assertTrue(bundle.complete)

        keys, excluded, _ = self.injected_keys(selection=ReadSelection(
            topics=("T-1",), scope=("scenario:payments", "item:task-42")))
        self.assertIn("user:memory/task42.md", keys)

        keys, excluded, _ = self.injected_keys(selection=ReadSelection(topics=("T-1",)))
        self.assertIn("user:memory/plain.md", keys)
        self.assertNotIn("user:memory/payments.md", keys)
        self.assertNotIn("user:memory/task42.md", keys)

    def test_direct_selection_and_dependencies_cannot_bypass_scope(self):
        for field in ("documents", "dependencies"):
            with self.subTest(field=field):
                selection = ReadSelection(topics=("T-1",), scope=("scenario:other",),
                                          **{field: ("user:memory/payments.md",)})
                keys, excluded, _ = self.injected_keys(selection=selection)
                self.assertNotIn("user:memory/payments.md", keys)
                self.assertIn("does not match the current reading scope",
                              excluded["user:memory/payments.md"])

    def test_direct_selection_of_a_matching_scope_still_injects(self):
        selection = ReadSelection(topics=("T-1",), scope=("scenario:payments",),
                                  documents=("user:memory/payments.md",))
        keys, _, _ = self.injected_keys(selection=selection)
        self.assertIn("user:memory/payments.md", keys)

    def test_no_matching_scope_is_empty_but_valid(self):
        keys, excluded, bundle = self.injected_keys(selection=ReadSelection(
            topics=("T-1",), scope=("scenario:none",)))
        for key in ("user:memory/payments.md", "user:memory/task42.md"):
            self.assertNotIn(key, keys)
            self.assertIn("does not match the current reading scope", excluded[key])
        self.assertIn("user:memory/personal.md", keys)  # personal stays broad
        self.assertTrue(bundle.complete)

    def test_invalid_scope_tag_in_the_selection_is_rejected(self):
        for tag in ("global", "scenario:", "item:x y"):
            with self.subTest(tag=tag):
                knowledge_error(self, "knowledge_invalid_schema", self.bundle,
                                selection=ReadSelection(topics=("T-1",), scope=(tag,)))

    def test_stopped_documents_are_not_injectable_via_any_path(self):
        for field in ("documents", "dependencies", "global_constraints"):
            with self.subTest(field=field):
                selection = ReadSelection(topics=("T-1",),
                                          **{field: ("user:memory/old.md",)})
                keys, excluded, _ = self.injected_keys(selection=selection)
                self.assertNotIn("user:memory/old.md", keys)
                self.assertIn("superseded", excluded["user:memory/old.md"])


class CorrectionTests(ExperienceLoopFixture):
    """S6-A03: corrections reuse the authorized proposal pipeline."""

    def setUp(self):
        super().setUp()
        self.original = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="inferred",
            source="task-payments-042", body="Use rolling deployments for payments.")
        self.learn("memory/deployment.md", self.original)

    def correction_edits(self):
        superseded = self.original.replace("status: active", "status: superseded")
        corrected = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="verified",
            source="user-correction-chat#7", body="Use blue/green deployments for payments.")
        return [KnowledgeEdit(path="memory/deployment.md", owner="user",
                              action="supersede", content=superseded),
                KnowledgeEdit(path="memory/deployment-corrected.md", owner="user",
                              action="create", content=corrected)]

    def test_correction_keeps_the_old_record_and_marks_it_superseded(self):
        proposal = self.prepared(self.correction_edits(), intent=self.intent(action="correct"))
        receipt = self.apply(proposal)
        self.assertEqual(proposal.proposal_hash, receipt.proposal_hash)
        self.assertIn("user:memory/deployment.md", receipt.changed_paths)
        self.assertIn("user:memory/deployment-corrected.md", receipt.changed_paths)

        old = (self.user / "memory" / "deployment.md").read_text(encoding="utf-8")
        self.assertIn("status: superseded", old)
        self.assertIn("Use rolling deployments for payments.", old)  # auditable body kept
        self.assertIn("source: task-payments-042", old)              # provenance kept
        new = parse_knowledge((self.user / "memory" / "deployment-corrected.md").read_text(
            encoding="utf-8"), path="memory/deployment-corrected.md")
        self.assertEqual("active", new.status)
        self.assertEqual("verified", new.confidence)
        self.assertEqual("user-correction-chat#7", new.source)

        index = (self.user / "index.md").read_text(encoding="utf-8")
        self.assertNotIn("memory/deployment.md)", index)
        self.assertIn("memory/deployment-corrected.md", index)

        catalog = self.catalog()
        self.assertFalse(catalog.by_key("user:memory/deployment.md").effective)
        self.assertTrue(catalog.by_key("user:memory/deployment-corrected.md").effective)

    def test_correction_without_confirmation_writes_nothing(self):
        proposal = self.prepared(self.correction_edits(), intent=self.intent(action="correct"))
        before = (self.user / "memory" / "deployment.md").read_bytes()
        for disposition in ("denied", "deferred"):
            error = knowledge_error(self, "knowledge_confirmation_required", apply_change,
                                    proposal, self.confirmation(proposal, disposition=disposition),
                                    user_root=self.user, project_root=self.project)
            self.assertEqual(disposition, error.details["disposition"])
        self.assertEqual(before, (self.user / "memory" / "deployment.md").read_bytes())
        self.assertFalse((self.user / "memory" / "deployment-corrected.md").exists())

    def test_correction_failure_rolls_the_group_back(self):
        proposal = self.prepared(self.correction_edits(), intent=self.intent(action="correct"))
        before = (self.user / "memory" / "deployment.md").read_bytes()
        index_before = (self.user / "index.md").read_bytes()
        set_failure_hook(lambda point: (_ for _ in ()).throw(RuntimeError("injected"))
                         if point == "publish:user:memory/deployment-corrected.md" else None)
        self.addCleanup(set_failure_hook, None)
        with self.assertRaises(DomainError):
            apply_change(proposal, self.confirmation(proposal),
                         user_root=self.user, project_root=self.project)
        set_failure_hook(None)
        self.assertEqual(before, (self.user / "memory" / "deployment.md").read_bytes())
        self.assertEqual(index_before, (self.user / "index.md").read_bytes())
        self.assertFalse((self.user / "memory" / "deployment-corrected.md").exists())


class RetirementAndExpiryTests(ExperienceLoopFixture):
    """S6-A04: stopped and expired entries never inject, with reasons."""

    def setUp(self):
        super().setUp()
        self.learn("memory/legacy.md",
                   memory_document("Legacy lesson", scope="scenario:payments",
                                   confidence="verified", expires="2026-01-01",
                                   body="Legacy deployment habit."))
        self.learn("memory/fresh.md",
                   memory_document("Fresh lesson", scope="scenario:payments",
                                   confidence="verified", expires="2030-01-01",
                                   body="Fresh deployment habit."))

    def test_expired_memory_is_not_injected_with_reason(self):
        keys, excluded, bundle = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)),
            now="2026-06-01")
        self.assertNotIn("user:memory/legacy.md", keys)
        self.assertIn("memory expired on 2026-01-01", excluded["user:memory/legacy.md"])
        self.assertIn("user:memory/fresh.md", keys)
        self.assertTrue(bundle.complete)
        # Before the expiry date the same document still injects.
        keys, _, _ = self.injected_keys(selection=ReadSelection(topics=("T-1",),
                                                                scope=("scenario:payments",)),
                                        now="2025-06-01")
        self.assertIn("user:memory/legacy.md", keys)

    def test_expiry_blocks_direct_selection_and_dependencies_too(self):
        for field in ("documents", "dependencies"):
            with self.subTest(field=field):
                selection = ReadSelection(topics=("T-1",), scope=("scenario:payments",),
                                          **{field: ("user:memory/legacy.md",)})
                keys, excluded, _ = self.injected_keys(selection=selection, now="2026-06-01")
                self.assertNotIn("user:memory/legacy.md", keys)
                self.assertIn("memory expired on 2026-01-01",
                              excluded["user:memory/legacy.md"])

    def test_invalid_now_override_is_rejected(self):
        knowledge_error(self, "knowledge_invalid_schema", self.bundle, now="not-a-date")
        knowledge_error(self, "knowledge_invalid_schema", self.bundle, now="2026-13-01")

    def test_retirement_through_the_pipeline_stops_injection(self):
        current = (self.user / "memory" / "fresh.md").read_text(encoding="utf-8")
        proposal = self.prepared([KnowledgeEdit(
            path="memory/fresh.md", owner="user", action="supersede",
            content=current.replace("status: active", "status: superseded"))],
            intent=self.intent(action="supersede"))
        self.apply(proposal)

        keys, excluded, _ = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)),
            now="2026-06-01")
        self.assertNotIn("user:memory/fresh.md", keys)
        self.assertIn("superseded", excluded["user:memory/fresh.md"])
        # The retired body stays on disk for audit; the index drops navigation.
        self.assertIn("status: superseded",
                      (self.user / "memory" / "fresh.md").read_text(encoding="utf-8"))
        self.assertNotIn("memory/fresh.md)", (self.user / "index.md").read_text(encoding="utf-8"))
        # And it cannot be smuggled back through a direct selection.
        selection = ReadSelection(topics=("T-1",), scope=("scenario:payments",),
                                  documents=("user:memory/fresh.md",))
        keys, excluded, _ = self.injected_keys(selection=selection, now="2026-06-01")
        self.assertNotIn("user:memory/fresh.md", keys)
        self.assertIn("superseded", excluded["user:memory/fresh.md"])


class PromotionTests(ExperienceLoopFixture):
    """S6-A05: inferred memories never silently become rules."""

    def setUp(self):
        super().setUp()
        self.learn("memory/inferred.md",
                   memory_document("Inferred lesson", scope="scenario:payments",
                                   confidence="inferred", body="Inferred habit."))

    def test_promotion_of_an_inferred_memory_needs_its_own_consent(self):
        rule = ("---\nschema: fstar.knowledge.v1\ntype: rule\nstatus: active\n"
                "strength: default\n---\n\n# Promoted rule\n\nUse blue/green deployments.\n")
        memory = (self.user / "memory" / "inferred.md").read_text(encoding="utf-8")
        edits = [KnowledgeEdit(path="rules/promoted.md", owner="user",
                               action="create", content=rule),
                 KnowledgeEdit(path="memory/inferred.md", owner="user",
                               action="supersede",
                               content=memory.replace("status: active", "status: superseded"))]
        error = knowledge_error(self, "knowledge_confirmation_required", self.prepared, edits,
                                intent=self.intent(action="promote", consent=""))
        self.assertEqual("intent.consent", error.details["field"])
        proposal = self.prepared(edits, intent=self.intent(
            action="promote", consent="user asked to promote this lesson on chat#9"))
        self.assertIn("user asked to promote this lesson", proposal.consent)

    def test_confidence_is_carried_honestly_into_the_reading(self):
        self.learn("memory/verified.md",
                   memory_document("Verified lesson", scope="scenario:payments",
                                   confidence="verified", body="Verified habit."))
        bundle = self.bundle(selection=ReadSelection(topics=("T-1",),
                                                      scope=("scenario:payments",)))
        by_key = {document.key: document for document in bundle.full_documents}
        self.assertEqual("verified", by_key["user:memory/verified.md"].confidence)
        self.assertEqual("inferred", by_key["user:memory/inferred.md"].confidence)
        self.assertIsNone(by_key["user:memory/plain.md"].confidence)  # old schema: unspecified

    def test_a_skill_preference_is_just_an_ordinary_candidate(self):
        before = sorted(str(path) for path in self.user.rglob("*"))
        _, receipt = self.learn(
            "memory/skill-pref.md",
            memory_document("Skill preference", kind="preference", confidence="inferred",
                            source="conversation-chat#11", body="Prefer tool A over tool B."),
            summary="record a skill preference as an ordinary memory candidate")
        self.assertIn("user:memory/skill-pref.md", receipt.changed_paths)
        after = sorted(str(path) for path in self.user.rglob("*"))
        # Only the memory body is added and the user index is updated in place:
        # no candidate ledger, no automatic habit store, nothing learned
        # outside the pipeline.
        added = [path for path in after if path not in before]
        self.assertEqual([str(self.user / "memory" / "skill-pref.md")], added)
        self.assertIn("memory/skill-pref.md",
                      (self.user / "index.md").read_text(encoding="utf-8"))


class ConditionLayeringTests(ExperienceLoopFixture):
    """S6-A06: prose conditions are never machine-judged."""

    def setUp(self):
        super().setUp()
        self.learn("memory/conditional.md",
                   memory_document("Conditional lesson", scope="scenario:payments",
                                   confidence="verified",
                                   conditions="仅在旧版部署流程仍在使用时适用",
                                   body="Conditional habit."))
        self.learn("memory/timed.md",
                   memory_document("Timed lesson", scope="scenario:payments",
                                   confidence="verified", expires="2026-01-01",
                                   conditions="仅在旧版部署流程仍在使用时适用",
                                   body="Timed habit."))

    def test_unjudged_conditions_stay_unknown_and_block_injection(self):
        keys, excluded, _ = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)),
            now="2025-06-01")
        self.assertNotIn("user:memory/conditional.md", keys)
        reason = excluded["user:memory/conditional.md"]
        self.assertIn("unknown", reason)
        self.assertIn("仅在旧版部署流程仍在使用时适用", reason)
        self.assertNotIn("expired", reason)

    def test_an_explicit_judgement_controls_the_conditioned_memory(self):
        include = ReadSelection(
            topics=("T-1",), scope=("scenario:payments",),
            applicability={"user:memory/conditional.md":
                           Applicability("include", "user confirmed it still applies")})
        keys, _, _ = self.injected_keys(selection=include, now="2025-06-01")
        self.assertIn("user:memory/conditional.md", keys)

        exclude = ReadSelection(
            topics=("T-1",), scope=("scenario:payments",),
            applicability={"user:memory/conditional.md":
                           Applicability("exclude", "the old flow is gone")})
        keys, excluded, _ = self.injected_keys(selection=exclude, now="2025-06-01")
        self.assertNotIn("user:memory/conditional.md", keys)
        self.assertIn("the old flow is gone", excluded["user:memory/conditional.md"])

    def test_machine_expiry_takes_precedence_and_never_judges_prose(self):
        keys, excluded, _ = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)),
            now="2026-06-01")
        self.assertNotIn("user:memory/timed.md", keys)
        reason = excluded["user:memory/timed.md"]
        self.assertIn("memory expired on 2026-01-01", reason)
        self.assertNotIn("unknown", reason)
        # Before the date the prose layer still applies on its own.
        keys, excluded, _ = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)),
            now="2025-06-01")
        self.assertNotIn("user:memory/timed.md", keys)
        self.assertIn("unknown", excluded["user:memory/timed.md"])


class CompatibilityTests(ExperienceLoopFixture):
    """S6-A07: old corpus, budgets and read-only behaviour stay intact."""

    def test_old_corpus_reading_is_unchanged(self):
        keys, excluded, bundle = self.injected_keys()
        self.assertIn("user:rules/global.md", keys)
        self.assertIn("user:memory/plain.md", keys)
        self.assertIn("project:.fstar/specs/core.md", keys)
        self.assertIn("project:.fstar/knowledge/context/background.md", keys)
        self.assertIn("project:docs/architecture.md", keys)
        self.assertNotIn("user:memory/old.md", keys)
        self.assertIn("superseded", excluded["user:memory/old.md"])
        self.assertTrue(bundle.complete)

    def test_over_budget_bodies_are_still_deferred_whole(self):
        self.learn("memory/verbose.md",
                   memory_document("Verbose lesson", scope="scenario:payments",
                                   confidence="verified", body="Verbose habit. " * 20))
        bundle = self.bundle(selection=ReadSelection(topics=("T-1",),
                                                      scope=("scenario:payments",)),
                             max_bytes=10)
        self.assertFalse(bundle.complete)
        deferred = {item.key for item in bundle.required_unloaded}
        self.assertIn("user:memory/verbose.md", deferred)
        self.assertIn("user:memory/plain.md", deferred)
        for document in bundle.full_documents:
            self.assertLessEqual(document.size, 10)

    def test_reads_create_no_files_and_change_nothing(self):
        self.learn("memory/deployment.md",
                   memory_document("Deployment lesson", scope="scenario:payments",
                                   confidence="inferred", expires="2030-01-01",
                                   conditions="适用于旧版部署流程"))
        before = sorted((str(path), path.read_bytes()) for path in self.user.rglob("*")
                        if path.is_file())
        for kwargs in ({}, {"now": "2031-01-01"},
                       {"selection": ReadSelection(topics=("T-1",), scope=("scenario:x",))}):
            with self.subTest(kwargs=kwargs):
                self.bundle(**kwargs)
        after = sorted((str(path), path.read_bytes()) for path in self.user.rglob("*")
                       if path.is_file())
        self.assertEqual(before, after)

    def test_selection_without_scope_or_now_still_works(self):
        bundle = load_context(self.catalog(), selection=ReadSelection(topics=("T-1",)))
        self.assertTrue(bundle.complete)


class ClosedLoopTests(ExperienceLoopFixture):
    """The spec's acceptance loop: deposit → scoped read → correct → retire."""

    def test_full_experience_loop(self):
        # 1. Deposit a scoped, inferred experience through the pipeline.
        original = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="inferred",
            source="task-payments-042", expires="2030-01-01",
            conditions="适用于旧版部署流程", body="Use rolling deployments for payments.")
        self.learn("memory/deployment.md", original)

        # 2. Scoped reading: matching scope plus the user's explicit judgement
        #    of the prose condition injects it; other readings exclude it.
        judged = ReadSelection(
            topics=("T-1",), scope=("scenario:payments",),
            applicability={"user:memory/deployment.md":
                           Applicability("include", "user confirmed the old flow still applies")})
        keys, _, bundle = self.injected_keys(selection=judged, now="2026-11-01")
        self.assertIn("user:memory/deployment.md", keys)
        # The unjudged prose condition keeps it out of scoped readings, and an
        # unscoped reading excludes it on the machine scope layer.
        keys, excluded, _ = self.injected_keys(
            selection=ReadSelection(topics=("T-1",), scope=("scenario:payments",)))
        self.assertNotIn("user:memory/deployment.md", keys)
        self.assertIn("unknown", excluded["user:memory/deployment.md"])
        keys, excluded, _ = self.injected_keys(selection=ReadSelection(topics=("T-1",)))
        self.assertNotIn("user:memory/deployment.md", keys)
        self.assertIn("does not match the current reading scope",
                      excluded["user:memory/deployment.md"])

        # 3. User correction through the same authorized pipeline.
        superseded = original.replace("status: active", "status: superseded")
        corrected = memory_document(
            "Deployment lesson", scope="scenario:payments", confidence="verified",
            source="user-correction-chat#7", expires="2030-01-01",
            conditions="适用于旧版部署流程", body="Use blue/green deployments for payments.")
        proposal = self.prepared(
            [KnowledgeEdit(path="memory/deployment.md", owner="user",
                           action="supersede", content=superseded),
             KnowledgeEdit(path="memory/deployment-corrected.md", owner="user",
                           action="create", content=corrected)],
            intent=self.intent(action="correct"))
        receipt = self.apply(proposal)
        self.assertEqual(proposal.proposal_hash, receipt.proposal_hash)
        self.assertIn("status: superseded",
                      (self.user / "memory" / "deployment.md").read_text(encoding="utf-8"))

        # 4. Retirement + expiry: neither injects, both explain themselves.
        current = (self.user / "memory" / "deployment-corrected.md").read_text(encoding="utf-8")
        retire = self.prepared([KnowledgeEdit(
            path="memory/deployment-corrected.md", owner="user", action="supersede",
            content=current.replace("status: active", "status: superseded"))],
            intent=self.intent(action="supersede"))
        self.apply(retire)

        expired = memory_document("Expired lesson", scope="scenario:payments",
                                  confidence="verified", expires="2026-01-01",
                                  body="Expired habit.")
        self.learn("memory/expired.md", expired)

        selection = ReadSelection(topics=("T-1",), scope=("scenario:payments",),
                                  documents=("user:memory/deployment.md",
                                             "user:memory/deployment-corrected.md",
                                             "user:memory/expired.md"))
        keys, excluded, _ = self.injected_keys(selection=selection, now="2026-11-01")
        self.assertNotIn("user:memory/deployment.md", keys)
        self.assertNotIn("user:memory/deployment-corrected.md", keys)
        self.assertNotIn("user:memory/expired.md", keys)
        self.assertIn("superseded", excluded["user:memory/deployment.md"])
        self.assertIn("superseded", excluded["user:memory/deployment-corrected.md"])
        self.assertIn("memory expired on 2026-01-01", excluded["user:memory/expired.md"])


if __name__ == "__main__":
    unittest.main()
