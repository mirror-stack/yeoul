"""Real temporary business writes through the host-only review gate."""
import json
import hashlib
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.product import workspace
from yeoul_mcp import server
from yeoul_mcp import runtime
from yeoul_mcp.reviewed_execution import execute_reviewed
from yeoul_mcp.shadow_workflow import run_shadow
from yeoul_mcp.context_shadow import encoded


class ReviewedExecution(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='yeoul-reviewed-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'workspace'
        env = {k: v for k, v in os.environ.items() if not k.startswith('YEOUL_')}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        workspace.setup(self.root, 'discuss', 'prepared_only')
        stack.enter_context(workspace.activated(self.root))
        self.task = workspace.prepare(self.root, 'yeoul_new', {'name': 'one', 'no_arc': True},
            review={'proposal': {'intent': 'create one'},
                    'requirements': {'policy': 'test-provider'}})['task_id']

    def host(self, raw):
        self.assertIsInstance(raw, bytes)
        value = json.loads(raw)
        return {'approved': True, 'reports': [{'check_id': 'policy',
            'provider_id': 'test-provider', 'binding': value['binding'],
            'status': 'pass', 'evidence_ref': 'synthetic:one'}]}

    def execute(self, host=None):
        return execute_reviewed(workspace, self.root, self.task, host or self.host)

    def assert_no_write(self, result):
        self.assertNotEqual(result['result']['exit_code'], 0)
        self.assertFalse((self.root / 'projects/one').exists())
        self.assertEqual(workspace.receipt(self.root, self.task)['state'], 'not_recorded')

    def test_approved_write_and_completed_replay_without_new_approval(self):
        first = self.execute()
        self.assertEqual(first['result']['exit_code'], 0)
        with patch.object(server, '_run', side_effect=AssertionError('must not execute')):
            self.assertEqual(workspace.execute(self.root, self.task), first)
            self.assertEqual(self.execute(lambda _: {'approved': False, 'reports': []}), first)

    def test_plain_and_direct_call_cannot_bypass_review(self):
        self.assert_no_write(workspace.execute(self.root, self.task))
        direct = server.yeoul_new('one', no_arc=True, operation_id=self.task)
        self.assertNotEqual(direct['exit_code'], 0)
        self.assert_no_write(workspace.execute(self.root, self.task))

    def test_approval_withdrawn(self):
        def host(raw):
            result = self.host(raw)
            result['approved'] = False
            return result
        self.assert_no_write(self.execute(host))

    def shadow_review(self):
        """Synthetic proposal stage, deliberately distinct from prepared execution."""
        snapshot = dict(target='synthetic-project', revision='source-v1', sources=[
            dict(id=role, role=role, category='REQUIRED_ACTIVE', body=body)
            for role, body in [('goal', 'Create project one'), ('status', 'Not created'),
                ('action', 'Propose creation only'), ('policy', 'Host approval required'),
                ('constraints', 'No worker writes')]])
        def worker(raw):
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(),
                                proposal={'intent': 'create one'}))
        result = run_shadow('synthetic-proposal', lambda: snapshot, worker,
            {'policy': ('test-provider', lambda *args:
                        dict(status='pass', evidence_ref='synthetic:shadow'))})
        self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(result['proposal'], workspace.load_job(self.root, self.task)['review']['proposal'])
        self.assertFalse((self.root / 'projects/one').exists())
        return result

    def test_shadow_success_cannot_be_reused_as_prepared_approval(self):
        shadow = self.shadow_review()
        self.assert_no_write(self.execute(lambda raw:
            dict(approved=True, reports=shadow['reports'])))
        audit = json.loads(self.audits()[0].read_text())
        self.assertIn('stale_or_different_proposal', audit['decision']['reasons'])
        self.assertEqual(audit['reports'], shadow['reports'])

    def test_shadow_success_then_current_retraction_blocks_actual_write(self):
        self.shadow_review()
        calls = []
        def host(raw):
            value = json.loads(raw)
            calls.append(value['binding'])
            self.assertEqual(value['job']['tool'], 'yeoul_new')
            self.assertEqual(value['job']['arguments']['name'], 'one')
            result = self.host(raw)
            result['reports'][0].update(status='retracted', evidence_ref='synthetic:withdrawal')
            return result
        self.assert_no_write(self.execute(host))
        self.assertEqual(len(calls), 1)
        audit = json.loads(self.audits()[0].read_text())
        self.assertIn('verification_retracted', audit['decision']['reasons'])
        self.assertEqual(audit['reports'][0]['evidence_ref'], 'synthetic:withdrawal')

    def test_shadow_then_fresh_prepared_verification_writes_once(self):
        shadow = self.shadow_review()
        calls = []
        def host(raw):
            value = json.loads(raw)
            self.assertNotEqual(value['binding'], shadow['binding'])
            self.assertEqual(value['job']['tool'], 'yeoul_new')
            self.assertEqual(value['job']['arguments']['name'], 'one')
            calls.append(value['binding'])
            return self.host(raw)
        first = self.execute(host)
        self.assertEqual(first['result']['exit_code'], 0)
        self.assertTrue((self.root / 'projects/one').is_dir())
        before = {p.name: p.read_bytes() for p in self.audits()}
        self.assertEqual(self.execute(host), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.audits()})

    def test_missing_retracted_or_wrong_provider(self):
        for kind in ('missing', 'retracted', 'provider'):
            with self.subTest(kind=kind):
                def host(raw):
                    result = self.host(raw)
                    if kind == 'missing':
                        result['reports'] = []
                    elif kind == 'retracted':
                        result['reports'][0]['status'] = 'retracted'
                    else:
                        result['reports'][0]['provider_id'] = 'worker-selected'
                    return result
                self.assert_no_write(self.execute(host))

    def test_changed_binding_fields_rejected(self):
        for field in ('task_id', 'target', 'revision', 'proposal_sha256'):
            with self.subTest(field=field):
                def host(raw):
                    result = self.host(raw)
                    result['reports'][0]['binding'][field] = '0' * 64
                    return result
                self.assert_no_write(self.execute(host))

    def test_changed_direct_arguments_rejected(self):
        result = server.yeoul_new('other', no_arc=True, operation_id=self.task)
        self.assertNotEqual(result['exit_code'], 0)
        self.assertFalse((self.root / 'projects/other').exists())

    def test_target_changed_during_host_review(self):
        def host(raw):
            result = self.host(raw)
            (self.root / 'projects/one').mkdir(parents=True)
            return result
        result = self.execute(host)
        self.assertEqual(result['result']['runtime_status'], 'stale_precondition')
        self.assertEqual(workspace.receipt(self.root, self.task)['state'], 'not_recorded')

    def test_host_failure_does_not_arm_receipt(self):
        def host(raw):
            raise RuntimeError('synthetic unavailable')
        self.assert_no_write(self.execute(host))

    def test_current_permission_still_required(self):
        with patch.dict(os.environ, YEOUL_MCP_ALLOW_WRITE='0'):
            self.assert_no_write(self.execute())

    def test_plain_preparation_remains_compatible(self):
        task = workspace.prepare(self.root, 'yeoul_new', {'name': 'other', 'no_arc': True})['task_id']
        self.assertEqual(workspace.load_job(self.root, task)['schema'], 2)
        self.assertEqual(workspace.execute(self.root, task)['result']['exit_code'], 0)

    def test_interruption_preserves_pending_and_blocks_retry(self):
        with patch.object(server, '_run', return_value={
                'exit_code': 124, 'stdout': '', 'stderr': 'synthetic timeout'}):
            result = self.execute()
        self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')
        self.assertEqual(workspace.receipt(self.root, self.task)['state'], 'pending')
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            self.assertEqual(self.execute()['result']['runtime_status'], 'reconciliation_required')

    def test_completed_receipt_write_failure_preserves_effect_and_blocks_retry(self):
        original = runtime.write_json
        def write(path, value):
            if value.get('state') == 'complete':
                raise OSError('synthetic completion log failure')
            return original(path, value)
        with patch.object(runtime, 'write_json', side_effect=write):
            result = self.execute()
        self.assertTrue((self.root / 'projects/one').exists())
        self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')
        self.assertEqual(workspace.receipt(self.root, self.task)['state'], 'pending')
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            self.assertEqual(self.execute()['result']['runtime_status'], 'reconciliation_required')

    def test_pending_receipt_write_failure_blocks_new_execution(self):
        original = runtime.write_json
        def write(path, value):
            if value.get('state') == 'pending':
                raise OSError('synthetic pending log failure')
            return original(path, value)
        with patch.object(runtime, 'write_json', side_effect=write):
            result = self.execute()
        self.assertFalse((self.root / 'projects/one').exists())
        self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')
        self.assertEqual(workspace.active(self.root)['state'], 'missing')
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            self.assertEqual(self.execute()['result']['runtime_status'], 'reconciliation_required')

    def audits(self):
        return sorted((self.root / '.yeoul-mcp/reviews').glob('*.json'))

    def test_audit_preserves_denial_then_approval_and_replay_adds_nothing(self):
        self.assert_no_write(self.execute(lambda _: {'approved': False, 'reports': []}))
        first = {p.name: p.read_bytes() for p in self.audits()}
        self.assertEqual(len(first), 1)
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        self.assertEqual(len(self.audits()), 2)
        for name, raw in first.items():
            self.assertEqual((self.root / '.yeoul-mcp/reviews' / name).read_bytes(), raw)
        success = next(json.loads(p.read_text()) for p in self.audits()
                       if json.loads(p.read_text())['approved'])
        self.assertEqual(success['reports'][0]['evidence_ref'], 'synthetic:one')
        before = {p.name: p.read_bytes() for p in self.audits()}
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.audits()})

    def test_audit_failure_prevents_business_write_and_receipt(self):
        original = runtime.write_json
        def write(path, value):
            if path.parent.name == 'reviews':
                raise OSError('synthetic audit failure')
            return original(path, value)
        with patch.object(runtime, 'write_json', side_effect=write):
            self.assert_no_write(self.execute())
        self.assertFalse((self.root / '.yeoul-mcp/active.json').exists())

    def test_missing_linked_audit_requires_reconciliation_not_reexecution(self):
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        audit = self.audits()[0]
        audit.rename(audit.with_suffix('.retained-for-test'))
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            result = self.execute()
        self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')

    def test_malformed_host_result_leaves_sanitized_audit(self):
        self.assert_no_write(self.execute(lambda _: {'secret': 'must-not-retain'}))
        self.assertEqual(len(self.audits()), 1)
        raw = self.audits()[0].read_text()
        self.assertNotIn('must-not-retain', raw)
        self.assertEqual(json.loads(raw)['error'], 'host_review_unavailable_or_invalid')

    def test_interrupted_write_keeps_linked_review_evidence(self):
        with patch.object(server, '_run', return_value={
                'exit_code': 124, 'stdout': '', 'stderr': 'synthetic timeout'}):
            self.execute()
        self.assertEqual(workspace.receipt(self.root, self.task)['state'], 'pending')
        self.assertEqual(len(self.audits()), 1)
        self.assertTrue(json.loads(self.audits()[0].read_text())['approved'])

    def test_new_receipt_cannot_lose_audit_reference_silently(self):
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        path = self.root / '.yeoul-mcp' / (hashlib.sha256(self.task.encode()).hexdigest() + '.json')
        row = runtime.read_json(path)
        self.assertEqual(row['version'], 2)
        del row['review_audit']
        runtime.write_json(path, row)
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            self.assertEqual(self.execute()['result']['runtime_status'], 'reconciliation_required')

    def test_changed_audit_cannot_replay_as_intact_evidence(self):
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        path = self.audits()[0]
        event = json.loads(path.read_text())
        event['reports'][0]['status'] = 'retracted'
        runtime.write_json(path, event)
        with patch.object(server, '_run', side_effect=AssertionError('no retry')):
            self.assertEqual(self.execute()['result']['runtime_status'], 'reconciliation_required')

    def snapshot_all(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_missing_audit_recovery_diagnosis_is_readonly_not_authority(self):
        self.assertEqual(self.execute()['result']['exit_code'], 0)
        path = self.audits()[0]
        path.rename(path.with_suffix('.retained'))
        before = self.snapshot_all()
        report = workspace.recover(self.root)
        self.assertEqual(report['diagnosis'], 'evidence_unreadable')
        self.assertEqual(report['active']['state'], 'unreadable')
        self.assertEqual(report['tasks']['tasks'][0]['state'], 'unreadable')
        self.assertFalse(report['retry_authorized'])
        self.assertTrue(report['read_only'])
        self.assertEqual(before, self.snapshot_all())
        with self.assertRaises((ValueError, OSError)):
            workspace.recover(self.root, acknowledge=True, children_stopped=True,
                              note='Must not bypass unreadable audit')
        self.assertEqual(before, self.snapshot_all())

    def test_corrupt_task_does_not_hide_other_tasks(self):
        other = workspace.prepare(self.root, 'yeoul_new', dict(name='other', no_arc=True))['task_id']
        workspace.job_path(self.root, self.task).write_text('{broken')
        before = self.snapshot_all()
        report = workspace.recover(self.root)
        rows = {row['task_id']: row for row in report['tasks']['tasks']}
        self.assertEqual(rows[self.task]['state'], 'unreadable')
        self.assertEqual(rows[other]['state'], 'not_recorded')
        self.assertEqual(report['diagnosis'], 'evidence_unreadable')
        self.assertEqual(before, self.snapshot_all())

    def test_corrupt_active_marker_diagnosis_does_not_clear_it(self):
        marker = self.root / '.yeoul-mcp/active.json'
        marker.write_text('{broken')
        before = self.snapshot_all()
        report = workspace.recover(self.root)
        self.assertEqual(report['diagnosis'], 'evidence_unreadable')
        self.assertFalse(report['retry_authorized'])
        self.assertEqual(before, self.snapshot_all())

    def test_no_active_marker_is_not_proof_of_completion(self):
        before = self.snapshot_all()
        report = workspace.recover(self.root)
        self.assertEqual(report['diagnosis'], 'no_active_interruption_detected')
        self.assertFalse(report['retry_authorized'])
        self.assertEqual(before, self.snapshot_all())

    def test_pending_receipt_without_active_marker_is_reported(self):
        with patch.object(server, '_run', return_value=dict(exit_code=124, stdout='', stderr='timeout')):
            self.execute()
        marker = self.root / '.yeoul-mcp/active.json'
        marker.rename(marker.with_suffix('.retained'))
        before = self.snapshot_all()
        report = workspace.recover(self.root)
        self.assertEqual(report['diagnosis'], 'orphaned_pending_receipt')
        self.assertFalse(report['retry_authorized'])
        self.assertEqual(before, self.snapshot_all())


if __name__ == '__main__':
    unittest.main()
