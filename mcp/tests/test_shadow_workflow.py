"""File-backed synthetic host integration. No live model or product installation."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.context_shadow import encoded
from yeoul_mcp.shadow_workflow import run_shadow
from yeoul_mcp.worker_transport import CommandWorker


class ShadowWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul shadow host ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root/'snapshot.json'
        self.snapshot = dict(target='synthetic-table', revision='r1', sources=[
            dict(id=role, role=role, category='REQUIRED_ACTIVE', body=body)
            for role, body in [('goal', 'Report total count'), ('status', '[4,7,6]'),
                               ('action', 'Propose a sum only'), ('policy', 'READ_ONLY'),
                               ('constraints', 'No execution. Worker statements are unverified.')]
        ] + [dict(id='history', role='history', category='NONCONTROLLING_HISTORY', body='OLD_TOTAL_18'),
             dict(id='private', role='audit', category='VALIDATOR_ONLY', body='PRIVATE_MARKER')])
        self.source.write_bytes(encoded(self.snapshot))
        self.calls = []

    def load(self):
        return json.loads(self.source.read_bytes())

    def worker(self, payload):
        self.calls.append('worker')
        self.assertIsInstance(payload, bytes)
        self.assertNotIn(b'PRIVATE_MARKER', payload)
        self.assertNotIn(b'OLD_TOTAL_18', payload)
        return encoded(dict(input_sha256=hashlib.sha256(payload).hexdigest(), proposal={'total': 17}))

    def verifier(self, source, proposal, binding):
        self.calls.append('verifier')
        rows = json.loads(next(s['body'] for s in json.loads(source)['sources'] if s['id'] == 'status'))
        correct = json.loads(proposal).get('total') == sum(rows)
        return dict(status='pass' if correct else 'fail', evidence_ref='synthetic-check:sum-v1')

    def run_flow(self, worker=None, verifier=None, loader=None):
        return run_shadow('task-1', loader or self.load, worker or self.worker,
                          {'sum': ('fixture-verifier', verifier or self.verifier)})

    def change_source(self):
        self.snapshot['revision'] = 'r2'
        self.source.write_bytes(encoded(self.snapshot))

    def test_connected_success_is_review_not_execution_and_preserves_source(self):
        before = self.source.read_bytes()
        result = self.run_flow()
        self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(result['authority'], 'NONE')
        self.assertEqual(result['execution'], 'NOT_PERFORMED')
        self.assertEqual(self.calls, ['worker', 'verifier'])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_false_worker_claim_is_rejected_by_independent_adapter(self):
        def wrong(payload):
            return encoded(dict(input_sha256=hashlib.sha256(payload).hexdigest(), proposal={'total': 18}))
        result = self.run_flow(worker=wrong)
        self.assertEqual(result['state'], 'needs_review')
        self.assertIn('verification_fail', result['reasons'])

    def test_real_child_process_receives_only_model_payload(self):
        code = '''
import hashlib, json, sys
raw = sys.stdin.buffer.read()
model = json.loads(raw)
assert model['authority'] == 'NONE'
assert b'PRIVATE_MARKER' not in raw and b'OLD_TOTAL_18' not in raw
rows = json.loads(next(s['body'] for s in model['active'] if s['id'] == 'status'))
print(json.dumps({'input_sha256': hashlib.sha256(raw).hexdigest(), 'proposal': {'total': sum(rows)}}))
'''
        def child(payload):
            response = subprocess.run([sys.executable, '-I', '-B', '-c', code],
                                      cwd=self.tmp.name, input=payload, capture_output=True, timeout=5)
            self.assertEqual(response.returncode, 0, response.stderr)
            return response.stdout
        result = self.run_flow(worker=child)
        self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(result['proposal'], {'total': 17})

    def test_multiple_required_checks_cannot_be_replaced_by_one_pass(self):
        providers = {'sum': ('fixture-verifier', self.verifier),
                     'second': ('second-provider', lambda *args: dict(status='unknown', evidence_ref='fixture'))}
        result = run_shadow('task-1', self.load, self.worker, providers)
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(len(result['reports']), 2)

    def test_missing_required_context_refuses_before_worker(self):
        self.snapshot['sources'] = [s for s in self.snapshot['sources'] if s['id'] != 'policy']
        self.source.write_bytes(encoded(self.snapshot))
        with self.assertRaises(ValueError):
            self.run_flow()
        self.assertEqual(self.calls, [])

    def test_change_during_worker_prevents_provider_use(self):
        def changed(payload):
            result = self.worker(payload)
            self.change_source()
            return result
        result = self.run_flow(worker=changed)
        self.assertEqual(result['reasons'], ['source_unavailable_or_changed'])
        self.assertEqual(self.calls, ['worker'])

    def test_change_during_verification_cannot_be_promoted(self):
        def changed(*args):
            result = self.verifier(*args)
            self.change_source()
            return result
        self.assertEqual(self.run_flow(verifier=changed)['reasons'], ['source_unavailable_or_changed'])

    def test_change_before_delivery_prevents_worker(self):
        reads = 0
        def loader():
            nonlocal reads
            reads += 1
            if reads == 2:
                self.change_source()
            return self.load()
        self.assertEqual(self.run_flow(loader=loader)['state'], 'needs_review')
        self.assertEqual(self.calls, [])

    def test_invalid_worker_outputs_never_reach_verifier(self):
        for raw in (b'{}', b'{"proposal":{},"proposal":{}}', b'x'*65537,
                    encoded(dict(input_sha256='wrong', proposal={})), b'{"x":NaN}'):
            with self.subTest(raw=raw[:70]):
                self.calls.clear()
                self.assertEqual(self.run_flow(worker=lambda _: raw)['reasons'], ['invalid_worker_reply'])
                self.assertEqual(self.calls, [])

    def test_provider_failure_unknown_and_retraction_hold(self):
        for status in ('fail', 'unknown', 'retracted'):
            result = self.run_flow(verifier=lambda *args: dict(status=status, evidence_ref='fixture'))
            self.assertEqual(result['state'], 'needs_review')
        def broken(*args):
            raise RuntimeError('synthetic failure')
        self.assertEqual(self.run_flow(verifier=broken)['reasons'], ['provider_error'])
        self.assertEqual(self.run_flow(worker=broken)['reasons'], ['worker_error'])

    def test_provider_cannot_override_bound_identity(self):
        result = self.run_flow(verifier=lambda *args: dict(status='pass', evidence_ref='fixture', provider_id='forged'))
        self.assertEqual(result['reasons'], ['provider_error'])

    def test_missing_host_policy_refused_before_worker(self):
        with self.assertRaises(ValueError):
            run_shadow('task-1', self.load, self.worker, {})
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bounded command transport')
    def test_bounded_worker_timeout_is_a_named_hold_not_a_proposal(self):
        worker = CommandWorker([sys.executable, '-I', '-c', 'import time; time.sleep(10)'],
                               cwd=self.tmp.name, timeout=0.15)
        result = self.run_flow(worker=worker)
        self.assertEqual(result['reasons'], ['worker_timeout'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
