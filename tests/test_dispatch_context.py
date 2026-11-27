import contextlib
import io
import json
import os
import subprocess
import unittest
from unittest import mock

from fstar.cli import main

from fstar.dispatch import DispatchService, build_payload, build_result, build_worker_prompt, prepare_read_context
from fstar.models import DomainError
from fstar.store import TaskStore
from fstar.tasks import TaskService
from tests.test_dispatch import DispatchCase


class ContextHandoffTests(DispatchCase):
    def setUp(self):
        super().setUp()
        (self.project / '.fstar' / 'specs').mkdir()
        (self.project / '.fstar' / 'specs' / 'guide.md').write_text('checkout guide\n')
        (self.store.user_home / 'rules').mkdir(parents=True)
        (self.store.user_home / 'rules' / 'guide.md').write_text('user rule\n')

    def selection(self):
        return {'selection_reason': 'guides relevant to implementation', 'entries': [
            {'root': 'project', 'path': '.fstar/specs/guide.md'},
            {'root': 'user', 'path': 'rules/guide.md'},
            {'root': 'user', 'path': 'rules/missing.md'},
            {'root': 'project', 'path': 'later.md', 'deferred': True, 'reason': 'outside current scope'},
        ]}

    def test_selection_prompt_and_session_harvest(self):
        selected = prepare_read_context(self.store, self.selection())
        self.assertEqual(['checkout guide\n', 'user rule\n'], [x['text'] for x in selected['loaded']])
        self.assertEqual(['missing', 'deferred'], [x['status'] for x in selected['context_report']['unloaded']])
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[], allowed_paths=[], baseline={},
                                read_context=selected['read_context'], context_report=selected['context_report'])
        prompt = build_worker_prompt(payload)
        self.assertIn('user root: rules/guide.md', prompt)
        self.assertIn('missing: file not found', prompt)
        self.assertIn('checkout guide\\n', prompt)
        self.assertIn('user rule\\n', prompt)
        for item in selected['read_context']:
            receipt = {key: item[key] for key in ('root', 'path', 'sha256')}
            self.assertIn(json.dumps(receipt, ensure_ascii=False, separators=(',', ':')), prompt)
        self.assertIn('root must be exactly "project" or "user"', prompt)
        self.assertIn('validation_facts entries are objects with string command and result', prompt)
        self.assertIn('changed_paths and blockers are string arrays', prompt)
        result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done')
        outcome = self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('session_only', outcome['persistence'])
        self.assertEqual('not_reported', outcome['context_reading']['status'])
        self.assertFalse(outcome['input_baseline_verified'])
        (self.store.user_home / 'rules' / 'guide.md').write_text('changed')
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('stale_input', caught.exception.code)
        (self.store.user_home / 'rules' / 'guide.md').unlink()
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('input_unverifiable', caught.exception.code)

    def test_receipt_matching_and_diagnostics(self):
        selected = prepare_read_context(self.store, {'selection_reason': 'guide', 'entries': [
            {'root': 'project', 'path': '.fstar/specs/guide.md'}]})
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[],
                                allowed_paths=[], baseline={}, read_context=selected['read_context'])
        receipt = {key: selected['read_context'][0][key] for key in ('root', 'path', 'sha256')}
        for reported, status, reason in [
            (dict(receipt, root='project root'), 'not_reported', 'root must be exactly project or user'),
            (receipt, 'worker_reported', None),
            (dict(receipt, sha256='wrong'), 'not_reported', 'receipt does not match a loaded context entry'),
            ({key: receipt[key] for key in ('path', 'sha256')}, 'not_reported', 'receipt root is required'),
        ]:
            with self.subTest(reported=reported):
                result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done',
                                      input_baseline={'read_context': [reported]})
                reading = self.dispatch.harvest(result, payload, lease_token='')['context_reading']
                self.assertEqual(status, reading['status'])
                expected = [] if reason is None else [{'index': 0, 'reason': reason}]
                self.assertEqual(expected, reading['malformed_receipts'])
                self.assertEqual(0, reading['malformed_receipts_omitted'])

    def test_malformed_receipts_are_bounded_and_do_not_copy_bodies(self):
        selected = prepare_read_context(self.store, {'selection_reason': 'guide', 'entries': [
            {'root': 'project', 'path': '.fstar/specs/guide.md'}]})
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[],
                                allowed_paths=[], baseline={}, read_context=selected['read_context'])
        receipt = {key: selected['read_context'][0][key] for key in ('root', 'path', 'sha256')}
        body = 'secret-body-' * 1000
        invalid = dict(receipt, root='project root', text=body, extra=body)
        for reported in ([invalid], [invalid] * 25, body):
            with self.subTest(kind=type(reported).__name__, count=len(reported)):
                result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done',
                                      input_baseline={'read_context': reported})
                reading = self.dispatch.harvest(result, payload, lease_token='')['context_reading']
                encoded = json.dumps(reading)
                self.assertEqual('not_reported', reading['status'])
                self.assertNotIn('secret-body-', encoded)
                self.assertLess(len(encoded), 5000)
                if isinstance(reported, list):
                    self.assertEqual(min(len(reported), 10), len(reading['malformed_receipts']))
                    self.assertEqual(max(len(reported) - 10, 0), reading['malformed_receipts_omitted'])
                else:
                    self.assertEqual([{'reason': 'read_context must be an array', 'type': 'string'}],
                                     reading['malformed_receipts'])

    def test_short_receipt_values_do_not_leak_to_outcomes_or_evidence(self):
        self.create_started()
        selected = prepare_read_context(self.store, {'selection_reason': 'guide', 'entries': [
            {'root': 'project', 'path': '.fstar/specs/guide.md'}]})
        receipt = {key: selected['read_context'][0][key] for key in ('root', 'path', 'sha256')}
        reported = [dict(receipt, **{key: 'SECRET_BODY_' + key}) for key in ('root', 'path', 'sha256')]
        session = build_payload(role='implement', task_ref='session-only', plan_item_ids=[],
                                allowed_paths=[], baseline={}, read_context=selected['read_context'])
        result = build_result(dispatch_id=session['dispatch_id'], role='implement', status='done',
                              input_baseline={'read_context': reported})
        reading = self.dispatch.harvest(result, session, lease_token='')['context_reading']
        self.assertEqual('not_reported', reading['status'])
        self.assertEqual(3, len(reading['malformed_receipts']))
        self.assertNotIn('SECRET_BODY_', json.dumps(reading))
        payload = self.payload(paths=[], baseline={}, read_context=selected['read_context'])
        registration = self.dispatch.register(payload)
        result = self.result(payload, changed=[], input_baseline={'read_context': reported})
        outcome = self.dispatch.harvest(result, registration['payload'], lease_token=registration['lease_token'])
        self.assertEqual('stale', outcome['state'])
        self.assertNotIn('SECRET_BODY_', json.dumps(outcome))
        self.assertNotIn('SECRET_BODY_', json.dumps(self.store.read('root')['evidence'][-1]))

    def test_user_input_is_verified_even_when_project_output_has_same_name(self):
        selected = prepare_read_context(self.store, self.selection())
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[],
                                allowed_paths=['rules/guide.md'], baseline={}, read_context=selected['read_context'])
        result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done',
                              changed_paths=['rules/guide.md'])
        (self.store.user_home / 'rules' / 'guide.md').write_text('changed')
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('stale_input', caught.exception.code)

    def test_persistent_evidence_keeps_user_root_and_freshness(self):
        self.create_started()
        selected = prepare_read_context(self.store, self.selection())
        payload = self.payload(paths=[], baseline={}, read_context=selected['read_context'], context_report=selected['context_report'])
        registration = self.dispatch.register(payload)
        receipts = [{key: item[key] for key in ('root', 'path', 'sha256')} for item in selected['read_context']]
        result = self.result(payload, changed=[], input_baseline={'read_context': receipts})
        outcome = self.dispatch.harvest(result, registration['payload'], lease_token=registration['lease_token'])
        self.assertEqual('worker_reported', outcome['context_reading']['status'])
        self.assertEqual('valid', outcome['state'])
        task = self.store.read('root')
        evidence = task['evidence'][-1]
        self.assertIn({'root': 'user', 'user_root': str(self.store.user_home), 'path': 'rules/guide.md', 'sha256': selected['read_context'][1]['sha256']}, evidence['input_files'])
        self.assertEqual([], self.service.evidence._validate_current(evidence, 'root', task=task))
        (self.store.user_home / 'rules' / 'guide.md').write_text('changed')
        self.assertIn({'type': 'input_file', 'path': 'rules/guide.md', 'root': 'user'}, self.service.evidence._validate_current(evidence, 'root', task=task))
        (self.store.user_home / 'rules' / 'guide.md').unlink()
        self.assertTrue(self.service.evidence._validate_current(evidence, 'root', task=task))
        other = TaskStore(self.project, user_home=self.project.parent / 'other-user', runtime_root=self.store.runtime_root)
        self.assertTrue(TaskService(other, clock=self.clock).evidence._validate_current(evidence, 'root', task=task))

    def test_unreported_worker_read_is_stale(self):
        self.create_started()
        selected = prepare_read_context(self.store, self.selection())
        payload = self.payload(paths=[], baseline={}, read_context=selected['read_context'], context_report=selected['context_report'])
        registration = self.dispatch.register(payload)
        outcome = self.dispatch.harvest(self.result(payload, changed=[]), registration['payload'], lease_token=registration['lease_token'])
        self.assertEqual('stale', outcome['state'])
        self.assertEqual('not_reported', outcome['context_reading']['status'])
        evidence = self.store.read('root')['evidence'][-1]
        self.assertEqual('context_reading_not_reported', evidence['stale_reasons'][0]['type'])

    def test_tampered_body_and_wrong_source_are_rejected(self):
        selected = prepare_read_context(self.store, self.selection())
        entries = [dict(item) for item in selected['read_context']]
        entries[0]['text'] = 'tampered'
        with self.assertRaises(DomainError):
            build_payload(role='implement', task_ref='session-only', plan_item_ids=[], allowed_paths=[], baseline={}, read_context=entries)
        entries = [dict(item) for item in selected['read_context']]
        entries[1]['user_root'] = str(self.project)
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[], allowed_paths=[], baseline={}, read_context=entries)
        result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done')
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('input_unverifiable', caught.exception.code)
        entries = [dict(selected['read_context'][0], checkout=str(self.project.parent))]
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[], allowed_paths=[], baseline={}, read_context=entries)
        result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done')
        with self.assertRaises(DomainError) as caught:
            self.dispatch.harvest(result, payload, lease_token='')
        self.assertEqual('input_unverifiable', caught.exception.code)

    def test_unsafe_and_symlink_paths(self):
        for path in ('../outside', '/etc/passwd'):
            with self.assertRaises(DomainError):
                prepare_read_context(self.store, {'selection_reason': 'test', 'entries': [{'root': 'user', 'path': path}]})
        (self.store.user_home / 'alias').symlink_to(self.project, target_is_directory=True)
        selected = prepare_read_context(self.store, {'selection_reason': 'test', 'entries': [{'root': 'user', 'path': 'alias/.fstar/specs/guide.md'}]})
        self.assertEqual('error', selected['context_report']['unloaded'][0]['status'])
        self.assertFalse(selected['read_context'])

    def test_cli_selection_and_budget(self):
        selection_file = self.project / 'selection.json'
        selection_file.write_text(json.dumps(self.selection()))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(['--project', str(self.project), '--user-data-root', str(self.store.user_home),
                           'dispatch', 'context', '--selection', str(selection_file)])
        self.assertEqual(0, status)
        self.assertEqual('user rule\n', json.loads(output.getvalue())['loaded'][1]['text'])
        with mock.patch('fstar.runtime.inject.read_budgets', return_value={'max_file_bytes': 2, 'max_artifact_bytes': 2, 'max_total_bytes': 2}):
            selected = prepare_read_context(self.store, self.selection())
        self.assertEqual([], selected['loaded'])
        self.assertEqual('deferred', selected['context_report']['unloaded'][0]['status'])
        self.assertIn('sha256', selected['context_report']['unloaded'][0])

    def test_linked_worktree_evidence_tracks_source_checkout(self):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        def git(*args):
            subprocess.run(['git', *map(str, args)], check=True, capture_output=True, env=env)
        git('init', '-q', self.project)
        (self.project / '.fstar/config.yaml').write_text('project:\n  id: "context-test-project"\n')
        # The store cached its identity at setUp time; re-open it so the
        # newly committed config.yaml's project id is the cached identity
        # rather than an external change observed mid-lifetime.
        self.store = TaskStore(self.project, user_home=self.store.user_home, runtime_root=self.store.runtime_root)
        self.service = TaskService(self.store, clock=self.clock)
        self.dispatch = DispatchService(self.store, clock=self.clock, task_service=self.service)
        git('-C', self.project, 'add', '-f', '.fstar/.schema-version', '.fstar/specs/guide.md', '.fstar/config.yaml')
        git('-C', self.project, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'baseline')
        worktree = self.project.parent / 'checkout'
        git('-C', self.project, 'worktree', 'add', '-q', '-b', 'context-test', worktree)
        (worktree / '.fstar/specs/guide.md').write_text('branch guide\n')
        git('-C', worktree, 'add', '-f', '.fstar/specs/guide.md')
        git('-C', worktree, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'branch guide')
        self.create_started()
        main_store = self.store
        branch_store = TaskStore(worktree, user_home=main_store.user_home, runtime_root=main_store.runtime_root)
        branch_service = DispatchService(branch_store, clock=self.clock)
        selected = prepare_read_context(branch_store, {'selection_reason': 'branch guide', 'entries': [
            {'root': 'project', 'path': '.fstar/specs/guide.md'}]})
        self.assertEqual('branch guide\n', selected['loaded'][0]['text'])
        payload = self.payload(paths=[], baseline={}, read_context=selected['read_context'], context_report=selected['context_report'])
        registered = branch_service.register(payload)
        receipt = [{key: selected['read_context'][0][key] for key in ('root', 'path', 'sha256')}]
        result = self.result(payload, changed=[], input_baseline={'read_context': receipt})
        outcome = branch_service.harvest(result, registered['payload'], lease_token=registered['lease_token'])
        self.assertEqual('valid', outcome['state'])
        evidence = main_store.read('root')['evidence'][-1]
        main_evidence = TaskService(main_store, clock=self.clock).evidence
        self.assertEqual([], main_evidence._validate_current(evidence, 'root'))
        (worktree / '.fstar/specs/guide.md').write_text('changed branch\n')
        self.assertTrue(main_evidence._validate_current(evidence, 'root'))
        git('-C', self.project, 'worktree', 'remove', '--force', worktree)
        self.assertTrue(main_evidence._validate_current(evidence, 'root'))

    def test_legacy_and_empty_selection(self):
        selected = prepare_read_context(self.store, {'selection_reason': 'no relevant context', 'entries': []})
        self.assertEqual([], selected['read_context'])
        payload = build_payload(role='implement', task_ref='session-only', plan_item_ids=[], allowed_paths=[], baseline={})
        self.assertNotIn('context_report', payload)
        result = build_result(dispatch_id=payload['dispatch_id'], role='implement', status='done')
        self.assertFalse(self.dispatch.harvest(result, payload, lease_token='')['recorded'])
