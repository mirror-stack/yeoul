"""Explicit Linux/bwrap capability test. Synthetic temporary paths only.

Opt in with YEOUL_RUN_ISOLATION_TESTS=1. Absence is a skip, never isolation proof.
No package installation, account creation, host chmod or product activation.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.shadow_workflow import run_shadow
from yeoul_mcp.worker_transport import CommandWorker
from yeoul_mcp.candidate_input import collect_candidate


@unittest.skipUnless(os.environ.get('YEOUL_RUN_ISOLATION_TESTS') == '1',
                     'explicit isolated-worker test opt-in required')
class WorkerIsolation(unittest.TestCase):
    def test_readonly_source_private_output_and_host_boundaries(self):
        self.exercise()

    def test_isolated_worker_connects_to_shadow_review(self):
        self.exercise(connected=True)

    def test_isolated_worker_wrong_answer_is_not_promoted(self):
        self.exercise(connected=True, wrong=True)

    def exercise(self, connected=False, wrong=False):
        if not shutil.which('bwrap') or not Path('/usr/bin/python3').is_file():
            self.skipTest('requires existing Linux bwrap and system Python')
        with tempfile.TemporaryDirectory(prefix='yeoul isolated worker ') as folder:
            base = Path(folder).resolve()
            source, work, hidden = base/'source', base/'work', base/'host-only'
            for directory in (source, work, hidden):
                directory.mkdir()
            source_file = source/'observations.json'
            source_file.write_text('[4,7,6]', encoding='utf-8')
            marker = hidden/'private.txt'
            marker.write_text('synthetic-host-only', encoding='utf-8')
            before = {str(p): (p.read_bytes(), p.stat().st_mode)
                      for p in (source_file, marker)}
            # A live host listener avoids mistaking a nonexistent service for isolation.
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen(1)
                code = r'''
import hashlib, json, os, socket, sys
from pathlib import Path
checks = {}
def denied(name, action):
    try:
        action()
    except OSError as exc:
        checks[name] = {'denied': True, 'errno': exc.errno}
    else:
        raise AssertionError('unexpected access: ' + name)
data = json.loads(Path('/input/observations.json').read_text())
assert data == [4,7,6]
payload = sys.stdin.buffer.read()
if payload:
    model = json.loads(payload)
    assert model['authority'] == 'NONE'
    assert b'PRIVATE_VALIDATOR' not in payload and b'OLD_HISTORY' not in payload
    active_rows = json.loads(next(s['body'] for s in model['active'] if s['id'] == 'status'))
    assert active_rows == data
denied('overwrite_input', lambda: Path('/input/observations.json').write_text('changed'))
denied('delete_input', lambda: Path('/input/observations.json').unlink())
denied('chmod_input', lambda: os.chmod('/input/observations.json', 0o777))
denied('rename_input', lambda: os.rename('/input/observations.json', '/work/stolen'))
denied('hardlink_input', lambda: os.link('/input/observations.json', '/work/alias'))
Path('/work/link').symlink_to('/input/observations.json')
denied('symlink_write_input', lambda: Path('/work/link').write_text('changed'))
denied('read_host_file', lambda: Path(sys.argv[1]).read_text())
denied('write_host_file', lambda: Path(sys.argv[1]).write_text('changed'))
denied('host_proc_root', lambda: Path('/proc/' + sys.argv[3] + '/root' + sys.argv[1]).read_text())
assert 'YEOUL_ISOLATION_SENTINEL' not in os.environ
checks['host_environment_hidden'] = True
with socket.socket() as conn:
    conn.settimeout(1)
    denied('host_loopback', lambda: conn.connect(('127.0.0.1', int(sys.argv[2]))))
proposal = {'total': sum(data) + int(sys.argv[4])}
Path('/work/proposal.json').write_text(json.dumps(proposal))
checks['candidate_written'] = True
print(json.dumps({'input_sha256': hashlib.sha256(payload).hexdigest(), 'proposal': proposal}
                 if payload else checks))
'''
                command = [shutil.which('bwrap'), '--unshare-user', '--unshare-pid',
                           '--unshare-net', '--unshare-ipc', '--unshare-uts',
                           '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
                           '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
                           '--setenv', 'LANG', 'C.UTF-8', '--ro-bind', '/usr', '/usr',
                           '--ro-bind', '/lib', '/lib', '--symlink', 'usr/bin', '/bin']
                if Path('/lib64').exists():
                    command += ['--ro-bind', '/lib64', '/lib64']
                command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                            '--ro-bind', str(source), '/input', '--bind', str(work), '/work',
                            '--chdir', '/work', '--', '/usr/bin/python3', '-I', '-B', '-c', code,
                            str(marker), str(listener.getsockname()[1]), str(os.getpid()), str(int(wrong))]
                def launch(payload):
                    return CommandWorker(command, cwd=str(base), timeout=15,
                                         env={'YEOUL_ISOLATION_SENTINEL': 'synthetic-only'})(payload)
                if connected:
                    def load():
                        return dict(target='synthetic-input', revision='r1', sources=[
                            dict(id=role, role=role, category='REQUIRED_ACTIVE', body=body)
                            for role, body in [('goal', 'Return the sum'),
                                               ('status', source_file.read_text()),
                                               ('action', 'Proposal only'), ('policy', 'READ_ONLY'),
                                               ('constraints', 'Do not execute proposals')]
                        ] + [dict(id='private', role='audit', category='VALIDATOR_ONLY', body='PRIVATE_VALIDATOR'),
                             dict(id='old', role='history', category='NONCONTROLLING_HISTORY', body='OLD_HISTORY')])
                    def verify(snapshot, raw, binding):
                        proposal = json.loads(raw)
                        rows = json.loads(next(s['body'] for s in json.loads(snapshot)['sources'] if s['id'] == 'status'))
                        passed = (set(proposal) == {'total'} and type(proposal['total']) is int
                                  and proposal['total'] == sum(rows))
                        return dict(status='pass' if passed else 'fail', evidence_ref='synthetic-sum-check')
                    review = run_shadow('isolated-task', load, launch, {'sum': ('fixture-verifier', verify)})
                    self.assertEqual(review['state'], 'needs_review' if wrong else 'ready_for_review', review)
                    self.assertEqual(review['execution'], 'NOT_PERFORMED')
                    self.assertEqual(review['authority'], 'NONE')
                    if wrong:
                        self.assertIn('verification_fail', review['reasons'])
                    checks = {'connected_review': review['state']}
                else:
                    checks = json.loads(launch(b''))
                    self.assertTrue(all(value is True or value['denied'] for value in checks.values()))
                    self.assertEqual(len(checks), 12)
            candidate = collect_candidate(work, 'proposal.json')
            self.assertEqual(json.loads(candidate), {'total': 17 + int(wrong)})
            for filename, (body, mode) in before.items():
                self.assertEqual(Path(filename).read_bytes(), body)
                self.assertEqual(Path(filename).stat().st_mode, mode)
            self.assertFalse((source/'proposal.json').exists())
            print('isolation assertions:', json.dumps(checks, sort_keys=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
