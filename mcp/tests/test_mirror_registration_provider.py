"""Optional real Mirror source integration, using synthetic snapshot copies only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.command_provider import CommandProvider
from yeoul_mcp.context_shadow import encoded
from yeoul_mcp.mirror_registration_provider import CHECK, evaluate, _snapshot_path
from yeoul_mcp.local_host import LocalHost
from yeoul_mcp.product import workspace
from yeoul_mcp.workspace import write_json

MIRROR = importlib.util.find_spec('mirror_stack_mcp')


def sealed(rows, short=False):
    previous, out = 'genesis', []
    for row in rows:
        value = dict(row, prev_seal=previous)
        seal = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         allow_nan=False).encode()).hexdigest()
        value['seal'] = seal[:16] if short else seal
        previous = value['seal']
        out.append(json.dumps(value))
    return '\n'.join(out)+'\n'


@unittest.skipUnless(sys.platform == 'linux' and MIRROR is not None,
                     'requires Linux and an explicitly available optional Mirror package')
class MirrorRegistration(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-real-mirror-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.registration = dict(claim_id='synthetic', metric='acc', kill_condition='below 0.5')
        import yeoul_mcp
        paths = [str(Path(yeoul_mcp.__file__).resolve().parents[1]),
                 str(Path(MIRROR.origin).resolve().parents[1])]
        self.provider = CommandProvider(CHECK, 'local-mirror', [sys.executable, '-B', '-m',
            'yeoul_mcp.mirror_registration_provider', '--source-id', 'ledger',
            '--claim-id', 'synthetic', '--provider-id', 'local-mirror'], cwd=self.root,
            env=dict(PYTHONPATH=os.pathsep.join(paths), PYTHONDONTWRITEBYTECODE='1'))

    def snapshot(self, ledger):
        sources = [dict(id=role, role=role, category='REQUIRED_ACTIVE', body='synthetic '+role)
                   for role in ('goal', 'status', 'action', 'policy', 'constraints')]
        sources.append(dict(id='ledger', role='ledger', category='VALIDATOR_ONLY', body=ledger))
        return encoded(dict(target='synthetic', revision='fixture', sources=sources))

    def check(self, ledger, expected):
        raw = self.snapshot(ledger)
        before = list(self.root.iterdir())
        for stage in ('shadow', 'prepared'):
            result = (self.provider.shadow(raw, b'{}', b'{}') if stage == 'shadow'
                      else self.provider.prepared(b'{}', raw))
            self.assertEqual(result['status'], expected, result)
            self.assertEqual(result['evidence_ref'],
                             'mirror-snapshot-sha256:'+hashlib.sha256(ledger.encode()).hexdigest())
        self.assertEqual(list(self.root.iterdir()), before)

    def test_valid_registration_is_current_not_claim_truth(self):
        self.check(sealed([self.registration, dict(_type='result', claim_id='synthetic',
                                                  status='fail')]), 'pass')

    def test_retraction_blocks_instead_of_publish_go(self):
        self.check(sealed([self.registration, dict(_type='retraction', claim_id='synthetic',
                                                  reason='synthetic withdrawal')]), 'retracted')

    def test_malformed_withdrawal_is_unknown(self):
        self.check(sealed([self.registration, dict(_type='retraction', claim_id='synthetic')]), 'unknown')

    def test_missing_registration_is_unknown(self):
        self.check(sealed([dict(self.registration, claim_id='other')]), 'unknown')

    def test_corrupt_content_is_failed_integrity(self):
        self.check(sealed([self.registration]).replace('below 0.5', 'below 0.9'), 'fail')

    def test_legacy_short_hash_is_not_promoted(self):
        self.check(sealed([self.registration], short=True), 'unknown')

    def test_actual_mirror_reads_sealed_snapshot_and_descriptor_closes(self):
        from mirror_stack_mcp.integrity import read_verified
        ledger = sealed([self.registration])
        observed = []
        def inspect(path):
            observed.append(path)
            self.assertTrue(path.startswith('/proc/self/fd/'))
            self.assertEqual(Path(path).read_bytes(), ledger.encode())
            fd = os.open(path, os.O_WRONLY)
            try:
                with self.assertRaises(PermissionError):
                    os.write(fd, b'changed')
                with self.assertRaises(PermissionError):
                    os.ftruncate(fd, 0)
            finally:
                os.close(fd)
            return read_verified(path)
        with patch('mirror_stack_mcp.integrity.read_verified', side_effect=inspect):
            result = evaluate(json.loads(self.snapshot(ledger)), 'ledger', 'synthetic')
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(len(observed), 1)
        self.assertFalse(Path(observed[0]).exists())

    def test_memory_snapshot_closes_on_reader_failure(self):
        retained = None
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            with _snapshot_path(b'synthetic') as path:
                retained = path
                raise RuntimeError('synthetic')
        self.assertFalse(Path(retained).exists())

    def test_sealing_failure_closes_descriptor_without_fallback(self):
        import fcntl
        original = os.memfd_create
        created = []
        def track(*args):
            fd = original(*args)
            created.append(fd)
            return fd
        with patch('os.memfd_create', side_effect=track), patch.object(
                fcntl, 'fcntl', side_effect=OSError('synthetic sealing failure')):
            with self.assertRaises(OSError):
                with _snapshot_path(b'synthetic'):
                    self.fail('must not expose an unsealed snapshot')
        self.assertEqual(len(created), 1)
        with self.assertRaises(OSError):
            os.fstat(created[0])

    def test_sigkill_removes_owned_memory_file_without_named_copy(self):
        import select
        import signal
        import subprocess
        code = '''
import sys
from yeoul_mcp.mirror_registration_provider import _snapshot_path
with _snapshot_path(b'synthetic private snapshot') as path:
    print(path, flush=True)
    sys.stdin.buffer.read()
'''
        before = list(self.root.iterdir())
        child = subprocess.Popen([sys.executable, '-B', '-c', code], cwd=self.root,
            env=self.provider.transport.env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            readable, _, _ = select.select([child.stdout], [], [], 5)
            self.assertTrue(readable, 'child did not create memory snapshot')
            path = child.stdout.readline().strip()
            self.assertTrue(path.startswith('/proc/self/fd/'), path)
            remote = Path('/proc')/str(child.pid)/'fd'/path.rsplit('/', 1)[1]
            self.assertEqual(remote.read_bytes(), b'synthetic private snapshot')
            child.kill()
            child.communicate(timeout=5)
            self.assertEqual(child.returncode, -signal.SIGKILL)
            self.assertFalse(remote.exists())
            self.assertEqual(list(self.root.iterdir()), before)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def local_host(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('YEOUL_', 'AM_'))}
        guard = patch.dict(os.environ, env, clear=True)
        guard.start()
        self.addCleanup(guard.stop)
        root = self.root/'workspace'
        workspace.setup(root, 'discuss', 'prepared_only')
        active = workspace.activated(root)
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        source_snapshot = json.loads(self.snapshot(sealed([self.registration])))
        manifest = dict(version=1, target='synthetic', sources=[])
        for source in source_snapshot['sources']:
            path = source['id']+'.txt'
            (root/path).write_text(source['body'], encoding='utf-8')
            manifest['sources'].append(dict(id=source['id'], role=source['role'],
                                            category=source['category'], path=path))
        write_json(root/'.yeoul-mcp/source-manifest.json', manifest)
        def worker(raw):
            self.assertNotIn(b'kill_condition', raw)
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(), proposal={'fixture': True}))
        host = LocalHost(root, worker=worker, allowed_tools={'yeoul_new'},
            providers={CHECK: ('local-mirror', self.provider.shadow, self.provider.prepared)})
        return root, host

    def test_real_mirror_check_connects_to_explicitly_approved_local_write(self):
        root, host = self.local_host()
        task = host.prepare('synthetic', 'yeoul_new', dict(name='synthetic', no_arc=True))
        self.assertEqual(task['state'], 'prepared')
        self.assertFalse((root/'projects/synthetic').exists())
        result = host.commit(task['task_id'], approve=lambda _: True)
        self.assertEqual(result['result']['exit_code'], 0, result)
        self.assertTrue((root/'projects/synthetic').is_dir())

    def test_withdrawal_after_preparation_blocks_old_commit_and_new_shadow(self):
        root, host = self.local_host()
        task = host.prepare('synthetic', 'yeoul_new', dict(name='synthetic', no_arc=True))
        (root/'ledger.txt').write_text(sealed([self.registration,
            dict(_type='retraction', claim_id='synthetic', reason='synthetic withdrawn')]),
            encoding='utf-8', newline='\n')
        approvals = []
        def approve(request):
            approvals.append(request)
            return True
        result = host.commit(task['task_id'], approve=approve)
        self.assertNotEqual(result['result']['exit_code'], 0)
        self.assertFalse(approvals)
        fresh = host.prepare('new-shadow', 'yeoul_new', dict(name='synthetic', no_arc=True))
        self.assertEqual(fresh['state'], 'needs_review')
        self.assertIn('verification_retracted', fresh['reasons'])
        self.assertFalse((root/'projects/synthetic').exists())


if __name__ == '__main__':
    unittest.main()
