"""S-5 protocol contract tests: selected_skills / skill_usage.

The selection decisions here are FIXTURES (preset lists): these tests prove
the protocol transport and validation, not that a host would choose the same
skills. Live host semantic selection is a separate, unverified scenario
(S5-A01/A03/A04).
"""
from __future__ import annotations

import unittest

from fstar.dispatch import (
    build_payload,
    build_result,
    build_worker_prompt,
    validate_payload,
    validate_result,
)
from fstar.models import DomainError


def payload(**overrides):
    fields = dict(
        role="implement", task_ref="root", plan_item_ids=["P-1"],
        allowed_paths=["src/x.py"],
        baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
    )
    fields.update(overrides)
    return build_payload(**fields)


def result(dispatch_id="d-1", **overrides):
    fields = dict(dispatch_id=dispatch_id, role="implement", status="done",
                  changed_paths=["src/x.py"])
    fields.update(overrides)
    return build_result(**fields)


class SelectedSkillsPayloadTests(unittest.TestCase):
    def test_old_payload_without_skill_fields_stays_valid(self):
        built = payload()
        self.assertNotIn("selected_skills", built)
        validate_payload(built)

    def test_selected_skill_round_trips_with_source_and_scope(self):
        selection = [{"skill": "frontend-design",
                      "source": "user-named",
                      "reason": "the user named it and it covers the UI scope",
                      "scope": ["src/ui"]}]
        built = payload(selected_skills=selection)
        self.assertEqual(built["selected_skills"], selection)
        validate_payload(built)

    def test_selection_object_is_not_mutated(self):
        selection = [{"skill": "a", "source": "agent-selected", "reason": "r"}]
        payload(selected_skills=selection)
        self.assertEqual(selection, [{"skill": "a", "source": "agent-selected", "reason": "r"}])

    def test_malformed_entries_are_rejected(self):
        cases = [
            {"source": "agent-selected", "reason": "r"},          # no skill
            {"skill": "a", "reason": "r", "source": "telepathy"},  # unknown source
            {"skill": "a", "source": "agent-selected"},            # no reason
            {"skill": "a", "reason": "r", "scope": [1]},           # bad scope
            {"skill": "", "reason": "r"},                          # empty id
        ]
        for entry in cases:
            with self.assertRaises(DomainError, msg=entry) as caught:
                validate_payload(dict(payload(), selected_skills=[entry]))
            self.assertEqual(caught.exception.code, "invalid_dispatch_payload")

    def test_scalar_scope_is_accepted(self):
        built = payload(selected_skills=[{"skill": "a", "reason": "r", "scope": "src/x.py"}])
        validate_payload(built)

    def test_selected_skills_never_widen_allowed_paths(self):
        built = payload(selected_skills=[{"skill": "a", "reason": "r", "scope": ["entire-repo"]}])
        self.assertEqual(built["allowed_paths"], ["src/x.py"])

    def test_worker_prompt_renders_selection_and_anti_recursion(self):
        built = payload(selected_skills=[
            {"skill": "user-named-skill", "source": "user-named", "reason": "named by the user"},
            {"skill": "pytest-helper", "source": "agent-selected", "reason": "covers tests",
             "scope": ["tests/"]},
        ])
        prompt = build_worker_prompt(built)
        self.assertIn("selected_skills", prompt)
        self.assertIn("user-named-skill (source: user-named", prompt)
        self.assertIn("pytest-helper", prompt)
        self.assertIn("scope=tests/", prompt)
        self.assertIn("never widens allowed_paths", prompt)
        self.assertIn("Do not recursively start the same fstar action", prompt)

    def test_prompt_without_selection_has_no_skill_section(self):
        prompt = build_worker_prompt(payload())
        self.assertNotIn("selected_skills", prompt)


class SkillUsageResultTests(unittest.TestCase):
    def test_old_result_without_skill_usage_stays_valid(self):
        built = result()
        self.assertNotIn("skill_usage", built)
        validate_result(built)

    def test_usage_states_round_trip(self):
        usage = [
            {"skill": "a", "state": "succeeded"},
            {"skill": "b", "state": "attempted"},
            {"skill": "c", "state": "failed", "reason": "tool error"},
            {"skill": "d", "state": "not_used", "reason": "intent did not match"},
        ]
        built = result(skill_usage=usage)
        self.assertEqual(built["skill_usage"], usage)
        validate_result(built)

    def test_not_used_requires_a_reason(self):
        with self.assertRaises(DomainError) as caught:
            result(skill_usage=[{"skill": "a", "state": "not_used"}])
        self.assertEqual(caught.exception.code, "invalid_dispatch_result")

    def test_failed_requires_a_reason(self):
        with self.assertRaises(DomainError):
            result(skill_usage=[{"skill": "a", "state": "failed"}])

    def test_unknown_state_is_rejected(self):
        with self.assertRaises(DomainError):
            result(skill_usage=[{"skill": "a", "state": "installed"}])

    def test_empty_list_is_allowed(self):
        built = result(skill_usage=[])
        self.assertEqual(built["skill_usage"], [])


if __name__ == "__main__":
    unittest.main()
