"""Independent local host composition with synthetic files and trusted fixtures."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.local_host import LocalHost
from yeoul_mcp.command_provider import CommandProvider
from yeoul_mcp.product import workspace
from yeoul_mcp.context_shadow import encoded
from yeoul_mcp.workspace import write_json


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux current-file collector')
class LocalHostTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-local-host-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / 'project'
        env = {k: v for k, v in os.environ.items() if not k.startswith(('YEOUL_', 'AM_'))}
        guard = patch.dict(os.environ, env, clear=True)
        guard.start()
        self.addCleanup(guard.stop)
        workspace.setup(self.root, 'discuss', 'prepared_only')
        active = workspace.activated(self.root)
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        manifest = dict(version=1, target='synthetic', sources=[])
        for role in ('goal', 'status', 'action', 'policy', 'constraints', 'private'):
            (self.root / (role + '.txt')).write_text('synthetic ' + role)
            manifest['sources'].append(dict(id=role, role=role, path=role+'.txt',
                category='VALIDATOR_ONLY' if role == 'private' else 'REQUIRED_ACTIVE'))
        write_json(self.root / '.yeoul-mcp/source-manifest.json', manifest)
        self.status = 'pass'
        self.requests = []
        self.host = self.make_host()

    def make_host(self, provider_id='fixture'):
        def worker(raw):
            self.assertNotIn(b'synthetic private', raw)
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(),
                                proposal={'suggestion': 'create synthetic project'}))
        def shadow(*args):
            return dict(status='pass', evidence_ref='synthetic:shadow')
        def prepared(request, snapshot):
            value = json.loads(request)
            self.assertEqual(value['job']['tool'], 'yeoul_new')
            self.assertEqual(value['job']['arguments']['name'], 'synthetic')
            self.assertIn(b'synthetic private', snapshot)
            self.requests.append(value)
            return dict(status=self.status, evidence_ref='synthetic:current')
        return LocalHost(self.root, worker=worker,
            providers={'check': (provider_id, shadow, prepared)}, allowed_tools={'yeoul_new'})

    def prepare(self):
        return self.host.prepare('synthetic', 'yeoul_new', dict(name='synthetic', no_arc=True))['task_id']

    def test_full_path_requires_separate_approval_and_replays_without_callbacks(self):
        task = self.prepare()
        target = self.root / 'projects/synthetic'
        self.assertFalse(target.exists())
        denied = self.host.commit(task, approve=lambda _: False)
        self.assertNotEqual(denied['result']['exit_code'], 0)
        self.assertFalse(target.exists())
        approval_requests = []
        def approve(raw):
            approval_requests.append(json.loads(raw))
            return True
        result = self.host.commit(task, approve=approve)
        self.assertEqual(result['result']['exit_code'], 0, result)
        self.assertTrue(target.is_dir())
        self.assertEqual(approval_requests[-1], self.requests[-1])
        count = len(self.requests)
        def forbidden(_):
            self.fail('completed task must not request approval again')
        self.assertEqual(self.host.commit(task, approve=forbidden), result)
        self.assertEqual(len(self.requests), count)

    def test_new_host_resumes_prepared_job_without_shadow_rerun(self):
        task = self.prepare()
        restarted = self.make_host()
        restarted.worker = lambda _: self.fail('must not rerun shadow')
        self.assertEqual(restarted.commit(task, approve=lambda _: True)['result']['exit_code'], 0)

    def test_private_source_change_blocks_before_provider_and_approval(self):
        task = self.prepare()
        (self.root/'private.txt').write_text('changed private evidence')
        result = self.host.commit(task, approve=lambda _: self.fail('stale approval'))
        self.assertNotEqual(result['result']['exit_code'], 0)
        self.assertFalse(self.requests)
        self.assertFalse((self.root/'projects/synthetic').exists())

    def test_current_retraction_is_not_shadow_success(self):
        task = self.prepare()
        self.status = 'retracted'
        result = self.host.commit(task, approve=lambda _: self.fail('retracted approval'))
        self.assertNotEqual(result['result']['exit_code'], 0)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse((self.root/'projects/synthetic').exists())

    def test_source_change_during_approval_blocks_write(self):
        task = self.prepare()
        def approve(_):
            (self.root/'policy.txt').write_text('new policy')
            return True
        self.assertNotEqual(self.host.commit(task, approve=approve)['result']['exit_code'], 0)
        self.assertFalse((self.root/'projects/synthetic').exists())

    def test_provider_identity_change_does_not_reuse_prepared_contract(self):
        task = self.prepare()
        other = self.make_host('replacement')
        self.assertNotEqual(other.commit(task, approve=lambda _: True)['result']['exit_code'], 0)
        self.assertFalse(self.requests)

    def test_tool_outside_host_allowlist_is_refused_before_worker(self):
        self.host.worker = lambda _: self.fail('must not call worker')
        with self.assertRaises(ValueError):
            self.host.prepare('bad', 'arc_open', dict(slug='bad'))

    def test_nonboolean_approval_does_not_authorize(self):
        task = self.prepare()
        self.assertNotEqual(self.host.commit(task, approve=lambda _: 'yes')['result']['exit_code'], 0)
        self.assertFalse((self.root/'projects/synthetic').exists())

    def test_shadow_failure_does_not_create_prepared_job(self):
        before = list((self.root/'.yeoul-mcp/tasks').glob('*.json'))
        self.host.worker = lambda _: b'{}'
        result = self.host.prepare('bad', 'yeoul_new', dict(name='synthetic', no_arc=True))
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(list((self.root/'.yeoul-mcp/tasks').glob('*.json')), before)

    def test_change_during_prepared_verification_blocks_approval(self):
        task = self.prepare()
        provider_id, shadow, original = self.host.providers['check']
        def verify(request, snapshot):
            result = original(request, snapshot)
            (self.root/'policy.txt').write_text('changed during verification')
            return result
        self.host.providers['check'] = (provider_id, shadow, verify)
        result = self.host.commit(task, approve=lambda _: self.fail('changed approval'))
        self.assertNotEqual(result['result']['exit_code'], 0)
        self.assertFalse((self.root/'projects/synthetic').exists())

    def test_unmanaged_host_does_not_call_worker_or_activate_itself(self):
        self.host.worker = lambda _: self.fail('unmanaged worker')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                self.prepare()
            self.assertNotIn('YEOUL_MCP_ROOT', os.environ)

    def test_subprocess_provider_timeout_retraction_then_fresh_pass(self):
        task = self.prepare()
        _, shadow, _ = self.host.providers['check']
        approvals = []
        def approve(request):
            approvals.append(request)
            return True
        for status in ('timeout', 'retracted', 'pass'):
            if status == 'timeout':
                code = 'import time; time.sleep(30)'
            else:
                code = '''
import hashlib, json, sys
raw = sys.stdin.buffer.read()
request = json.loads(raw)
job = request['body']['request']['job']
assert request['stage'] == 'prepared'
assert job['tool'] == 'yeoul_new' and job['arguments']['name'] == 'synthetic'
print(json.dumps(dict(version=1, request_id=request['request_id'],
    request_sha256=hashlib.sha256(raw).hexdigest(), check_id=request['check_id'],
    provider_id=request['provider_id'], status=sys.argv[1], evidence_ref='synthetic:subprocess')))
'''
            adapter = CommandProvider('check', 'fixture',
                [sys.executable, '-B', '-c', code, status], cwd=self.root, env={}, timeout=0.5)
            self.host.providers['check'] = ('fixture', shadow, adapter.prepared)
            result = self.host.commit(task, approve=approve)
            self.assertEqual(result['result']['exit_code'] == 0, status == 'pass', result)
            self.assertEqual(len(approvals), 1 if status == 'pass' else 0)
            self.assertEqual((self.root/'projects/synthetic').exists(), status == 'pass')


if __name__ == '__main__':
    unittest.main()
