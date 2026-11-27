import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fstar.dispatch import build_payload, build_result
from fstar.models import DomainError
from fstar.runtime import hooks


class LearningRoleTests(unittest.TestCase):
    def test_session_role_dispatch_and_worker_context(self):
        payload = build_payload(role="learn", task_ref="session-only", plan_item_ids=[],
                                allowed_paths=[], baseline={})
        result = build_result(dispatch_id=payload["dispatch_id"], role="learn", status="done")
        self.assertEqual(result["role"], "learn")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = hooks.worker_context(payload, role="learn", task_ref="session-only",
                                           start=root, user_root=root / "user", as_json=True)
        self.assertEqual(context["role"], "learn")
        self.assertTrue(any(item.get("path") == "agents/fstar-learn.md"
                            for item in context["inputs"]))

    def test_host_agent_name_is_recognized(self):
        self.assertEqual("learn", hooks._role_from_payload({"subagent_type": "fstar-learn"}))

    def test_unreadable_card_is_reported_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(hooks.inject, "role_card", side_effect=UnicodeError("bad encoding")):
                with self.assertRaises(DomainError) as caught:
                    hooks.worker_context({"subagent_type": "fstar-learn", "task_ref": "session-only"},
                                         start=root, user_root=root / "user", as_json=True)
        self.assertEqual(caught.exception.code, "role_card_unavailable")


if __name__ == "__main__":
    unittest.main()
