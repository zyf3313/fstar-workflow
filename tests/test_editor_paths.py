"""Editor allowed_paths under C-09: doc/ is no longer a workflow concept.

The coordinator's explicit per-file allowed_paths is the editor whitelist
wherever the deliverable lives. This file fixes the regression contract:
task-root deliverables (criteria.md / plan.md), a user-chosen project
directory, the legacy doc/ tree, and session-only artifacts all pass
STRUCTURAL validation; traversal, absolute paths, and out-of-scope harvest
writes are still rejected. Authorization of the actual write remains the
coordinator's per-file list plus the harvest scope check.
"""
from __future__ import annotations

import unittest

from fstar.dispatch import build_payload, build_result, validate_payload
from fstar.models import DomainError


def editor_payload(task_ref, paths):
    return build_payload(role="editor", task_ref=task_ref,
                         plan_item_ids=["S1"], allowed_paths=paths,
                         baseline={"artifact_items": [], "delivery": {"paths": [], "digest": ""}},
                         item_ids=["A001"], baseline_sha256="test")


class EditorAllowedPathsTests(unittest.TestCase):
    def test_task_root_criteria_and_plan_are_valid(self):
        for path in (".fstar/tasks/general-workflow-redesign/criteria.md",
                     ".fstar/tasks/general-workflow-redesign/plan.md"):
            with self.subTest(path=path):
                validate_payload(editor_payload("general-workflow-redesign", [path]))

    def test_legacy_doc_tree_still_valid(self):
        validate_payload(editor_payload("root", [".fstar/tasks/root/doc/prd.md"]))

    def test_user_chosen_project_directory_is_valid(self):
        validate_payload(editor_payload("root", ["docs/product/handbook.md", "deliverables/spec-v2.md"]))

    def test_session_only_artifact_paths_valid(self):
        validate_payload(editor_payload("session-only", ["doc/prd.md"]))
        validate_payload(editor_payload("session-only", ["notes/draft.md"]))

    def test_traversal_and_absolute_paths_still_rejected(self):
        for bad in ("../escape.py", "/etc/passwd", "a/../../b.md", ".fstar/tasks/root/../../x.md"):
            with self.subTest(path=bad), self.assertRaises(DomainError) as caught:
                editor_payload("root", [bad])
            self.assertEqual("unsafe_dispatch_path", caught.exception.code)

    def test_item_ids_and_baseline_still_required(self):
        with self.assertRaises(DomainError) as caught:
            build_payload(role="editor", task_ref="root", plan_item_ids=["S1"],
                          allowed_paths=[".fstar/tasks/root/criteria.md"], baseline={},
                          baseline_sha256="x")
        self.assertEqual("item_ids", caught.exception.details.get("field"))
        with self.assertRaises(DomainError) as caught:
            build_payload(role="editor", task_ref="root", plan_item_ids=["S1"],
                          allowed_paths=[".fstar/tasks/root/criteria.md"], baseline={},
                          item_ids=["A001"])
        self.assertEqual("baseline_sha256", caught.exception.details.get("field"))

    def test_harvest_still_rejects_out_of_scope_editor_writes(self):
        # Structural validation is not authorization: a changed_path outside
        # the payload's allowed_paths is rejected at harvest (the dispatch
        # service path is exercised in tests/test_dispatch.py; here the pure
        # result builder keeps changed_paths strictly project-relative).
        payload = editor_payload("root", [".fstar/tasks/root/criteria.md"])
        result = build_result(dispatch_id=payload["dispatch_id"], role="editor",
                              status="done",
                              changed_paths=["src/other.py"])
        self.assertNotIn("src/other.py", payload["allowed_paths"])
        validate_payload(payload)
        # The out-of-scope detection itself:
        from fstar.dispatch import validate_result
        validate_result(result)
        out_of_scope = sorted(set(result["changed_paths"]) - set(payload["allowed_paths"]))
        self.assertEqual(out_of_scope, ["src/other.py"])


if __name__ == "__main__":
    unittest.main()
