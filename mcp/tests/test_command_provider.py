"""Synthetic subprocess verifier responses; no external provider or model."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.command_provider import CommandProvider
from yeoul_mcp.worker_transport import WorkerTransportError

REPLY = '''
import hashlib, json, sys
raw = sys.stdin.buffer.read()
request = json.loads(raw)
reply = dict(version=1, request_id=request['request_id'],
    request_sha256=hashlib.sha256(raw).hexdigest(), check_id=request['check_id'],
    provider_id=request['provider_id'], status='pass', evidence_ref='synthetic:checked')
'''


@unittest.skipUnless(sys.platform == 'linux', 'Linux bounded command transport')
class ProviderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-provider-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()

    def provider(self, code, **kwargs):
        return CommandProvider('check', 'fixture', [sys.executable, '-B', '-c', code],
                               cwd=self.root, env={}, **kwargs)

    def call(self, provider):
        return provider.prepared(b'{"job":{},"binding":{}}', b'{"sources":[]}')

    def test_both_stages_and_statuses(self):
        for stage in ('shadow', 'prepared'):
            for status in ('pass', 'fail', 'unknown', 'retracted'):
                with self.subTest(stage=stage, status=status):
                    code = REPLY + "\nassert request['stage'] == " + repr(stage)
                    code += "\nreply['status'] = " + repr(status) + "\nprint(json.dumps(reply))"
                    provider = self.provider(code)
                    result = (provider.shadow(b'{}', b'{}', b'{}') if stage == 'shadow'
                              else self.call(provider))
                    self.assertEqual(result, dict(status=status, evidence_ref='synthetic:checked'))

    def test_wrong_response_scope_and_schema_refused(self):
        for field, value in (('request_id', 'old'), ('request_sha256', '0'*64),
                             ('check_id', 'other'), ('provider_id', 'other'),
                             ('version', True), ('status', 'GO'), ('evidence_ref', '')):
            with self.subTest(field=field):
                code = REPLY + '\nreply[' + repr(field) + '] = ' + repr(value)
                with self.assertRaises(ValueError):
                    self.call(self.provider(code + '\nprint(json.dumps(reply))'))

    def test_missing_extra_duplicate_and_partial_json_refused(self):
        for suffix in ("del reply['status']; print(json.dumps(reply))",
                       "reply['approved'] = True; print(json.dumps(reply))",
                       "print(json.dumps(reply)[:-1] + ',\"status\":\"pass\"}')",
                       "print('{')"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.call(self.provider(REPLY + '\n' + suffix))

    def test_replayed_response_rejected_for_identical_request_body(self):
        provider = self.provider(REPLY + '\nprint(json.dumps(reply))')
        original = provider.transport
        replies = []
        def retained(payload):
            if not replies:
                replies.append(original(payload))
            return replies[0]
        provider.transport = retained
        self.call(provider)
        with self.assertRaises(ValueError):
            self.call(provider)

    def test_timeout_output_flood_and_nonzero_exit_refused(self):
        for code, reason in (("import time; time.sleep(30)", 'worker_timeout'),
                             ("print('x'*70000)", 'worker_stdout_limit'),
                             ("raise SystemExit(2)", 'worker_exit_failed')):
            with self.subTest(reason=reason), self.assertRaises(WorkerTransportError) as raised:
                self.call(self.provider(code, timeout=0.5))
            self.assertEqual(raised.exception.reason, reason)

    def test_oversized_input_is_refused_before_process_launch(self):
        provider = self.provider('raise SystemExit(99)')
        with self.assertRaises(ValueError):
            provider.prepared(b' ' * (4*1024*1024+1), b'{}')


if __name__ == '__main__':
    unittest.main()
