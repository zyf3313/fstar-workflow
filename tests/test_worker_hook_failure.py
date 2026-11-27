import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fstar.models import DomainError
from fstar.runtime import __main__ as runtime

ROOT = Path(__file__).resolve().parents[1]


class WorkerHookFailureTests(unittest.TestCase):
    def call(self, name, payload, error=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(runtime, '_read_payload', return_value=payload), \
             mock.patch.object(runtime.hooks, 'worker_context', side_effect=error,
                               return_value={'text': 'role context'}), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = runtime.main([name])
        return status, out.getvalue(), err.getvalue()

    def test_claude_missing_card_blocks_agent_and_task(self):
        for tool in ('Agent', 'Task'):
            payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool,
                       'tool_input': {'subagent_type': 'fstar-learn'}}
            error = DomainError('role_card_unavailable', 'role card unavailable')
            status, out, err = self.call('worker-context', payload, error)
            self.assertEqual((status, out), (2, ''))
            self.assertIn('role_card_unavailable', err)
            self.assertIn('role card unavailable', err)

    def test_other_errors_and_events_keep_nonblocking_exit(self):
        for event, tool, code in [('PreToolUse', 'Agent', 'other_error'),
                                  ('SubagentStart', 'Agent', 'role_card_unavailable'),
                                  ('PreToolUse', 'Bash', 'role_card_unavailable'),
                                  ('', 'Agent', 'role_card_unavailable')]:
            payload = {'hook_event_name': event, 'tool_name': tool,
                       'tool_input': {'subagent_type': 'fstar-learn'}}
            status, _, _ = self.call('worker-context', payload, DomainError(code, 'failure'))
            self.assertEqual(status, 1, (event, tool, code))

    def test_success_and_other_hook_keep_existing_behavior(self):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                   'tool_input': {'subagent_type': 'fstar-learn'}}
        self.assertEqual(self.call('worker-context', payload), (0, 'role context\n', ''))
        with mock.patch.object(runtime, '_read_payload', return_value=payload), \
             mock.patch.object(runtime.hooks, 'prompt_context',
                               side_effect=DomainError('role_card_unavailable', 'failure')), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runtime.main(['prompt-context']), 1)

    def test_node_launcher_forwards_block_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / 'user'
            cache = user / 'resources' / '10'
            routing = cache / 'runtime' / 'routing.md'
            routing.parent.mkdir(parents=True)
            routing.write_text('old routing', encoding='utf-8')
            manifest = {'schema': 'fstar.package-assets.v1', 'resource_version': '10',
                        'files': [{'source': 'runtime/routing.md',
                                   'sha256': hashlib.sha256(routing.read_bytes()).hexdigest()}]}
            (cache / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (user / 'version').write_text('10\n', encoding='utf-8')
            payload = {'cwd': str(root), 'hook_event_name': 'PreToolUse', 'tool_name': 'Agent',
                       'tool_input': {'subagent_type': 'fstar-learn'}}
            env = dict(os.environ, FSTAR_USER_ROOT=str(user), FSTAR_PROJECT=str(root))
            result = subprocess.run(['node', str(ROOT / 'bin' / 'fstar-hook.cjs'), 'worker-context'],
                                    input=json.dumps(payload), text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('role_card_unavailable', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
