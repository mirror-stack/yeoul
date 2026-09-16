"""Host-only isolated execution contract and explicitly approved integration."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import subprocess
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.isolated_worker import IsolatedWorker, start_ticket, check_start, _BOOTSTRAP
from yeoul_mcp.worker_transport import CommandWorker, WorkerTransportError
from yeoul_mcp.shadow_workflow import run_shadow
from yeoul_mcp.workspace import write_json
from yeoul_mcp.worker_host import WorkerJournal, ProfileBroker
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_access import WorkerAccess
import socket


class IsolatedContract(unittest.TestCase):
    def setUp(self):
        self.events, self.calls = [], []

    def record(self, raw):
        self.events.append(json.loads(raw))

    def broker(self, command, payload, timeout):
        self.calls.append((command, payload, timeout))
        return b'not-found\n' if command[0].endswith('systemctl') else b'proposal'

    def worker(self, **kwargs):
        return IsolatedWorker(['/usr/bin/python3', '-c', 'pass'], uid=1000, gid=1000,
            broker=kwargs.get('broker', self.broker), record_event=kwargs.get('record', self.record))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_manifest_fixed_limits_and_cleanup_before_return(self):
        self.assertEqual(self.worker()(b'input'), b'proposal')
        self.assertEqual([row['state'] for row in self.events],
                         ['prepared', 'start_requested', 'cleanup_confirmed', 'returned'])
        manifest = self.events[0]['manifest']
        self.assertEqual(manifest['input_sha256'], hashlib.sha256(b'input').hexdigest())
        self.assertEqual(manifest['limits']['memory_bytes'], 134217728)
        command = next(call[0] for call in self.calls if call[0][0].endswith('systemd-run'))
        self.assertIn('--uid=1000', command)
        self.assertIn('--property=ProtectControlGroups=yes', command)
        self.assertNotIn('sudo', command)
        self.assertEqual(len({row['manifest_sha256'] for row in self.events}), 1)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_durable_preparation_failure_prevents_launch(self):
        def fail(raw):
            raise OSError('synthetic log failure')
        with self.assertRaisesRegex(WorkerTransportError, 'isolation_audit_failed'):
            self.worker(record=fail)(b'input')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][0][0].endswith('systemctl'))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_timeout_explicitly_stops_service(self):
        count = 0
        def broker(command, payload, timeout):
            nonlocal count
            self.calls.append(command)
            if command[0].endswith('systemd-run'):
                raise WorkerTransportError('worker_timeout')
            if 'show' in command:
                count += 1
                return b'loaded' if count == 2 else b'not-found'
            return b''
        with self.assertRaisesRegex(WorkerTransportError, 'worker_timeout'):
            self.worker(broker=broker)(b'input')
        self.assertTrue(any('stop' in call for call in self.calls))
        self.assertEqual(self.events[-1]['state'], 'held')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_uncertain_cleanup_withholds_valid_reply(self):
        count = 0
        def broker(command, payload, timeout):
            nonlocal count
            if command[0].endswith('systemd-run'):
                return b'valid proposal'
            if 'show' in command:
                count += 1
                return b'not-found' if count == 1 else b'loaded'
            return b''
        with self.assertRaisesRegex(WorkerTransportError, 'isolation_cleanup_incomplete'):
            self.worker(broker=broker)(b'input')
        self.assertEqual(self.events[-1]['state'], 'cleanup_unconfirmed')
        self.assertEqual(self.events[-1]['cleanup_stage'], 'still_loaded')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_cleanup_failure_stages_are_retained_without_exception_text(self):
        from yeoul_mcp.worker_host import _event
        for failed_stage in ('initial_show', 'stop', 'final_show'):
            with self.subTest(stage=failed_stage), tempfile.TemporaryDirectory() as tmp:
                self.events = []
                journal = WorkerJournal(Path(tmp).resolve())
                count = 0
                def record(raw):
                    journal(raw)
                    self.record(raw)
                def broker(command, payload, timeout):
                    nonlocal count
                    if command[0].endswith('systemd-run'):
                        return b'proposal'
                    if 'show' in command:
                        count += 1
                        if count == 1:
                            return b'not-found'
                        if ((count == 2 and failed_stage == 'initial_show') or
                                (count == 3 and failed_stage == 'final_show')):
                            raise RuntimeError('PRIVATE_DIAGNOSTIC')
                        return b'loaded'
                    if failed_stage == 'stop':
                        raise RuntimeError('PRIVATE_DIAGNOSTIC')
                    return b''
                with self.assertRaisesRegex(WorkerTransportError, 'isolation_cleanup_incomplete'):
                    self.worker(broker=broker, record=record)(b'input')
                event = self.events[-1]
                self.assertEqual(event['cleanup_stage'], failed_stage)
                self.assertNotIn('PRIVATE_DIAGNOSTIC', json.dumps(self.events))
                self.assertEqual(WorkerJournal(Path(tmp).resolve()).inspect(event['unit'])['state'], 'cleanup_unconfirmed')
                legacy = dict(event)
                del legacy['cleanup_stage']
                _event(legacy)
                with self.assertRaises(ValueError):
                    _event(dict(event, cleanup_stage='arbitrary text'))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux adapter')
    def test_collision_never_stops_existing_unit(self):
        with self.assertRaisesRegex(WorkerTransportError, 'isolation_unit_collision'):
            self.worker(broker=lambda *args: b'loaded')(b'input')
        self.assertEqual(self.events, [])

    def test_reject_root_or_unmounted_executable(self):
        for uid, exe in ((0, '/usr/bin/python3'), (1000, '/srv/worker/run'),
                         (1000, '/usr/bin/../../bin/sh')):
            with self.subTest(uid=uid, executable=exe), self.assertRaises(ValueError):
                IsolatedWorker([exe], uid=uid, gid=1000, broker=self.broker, record_event=self.record)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux boot clock')
    def test_start_ticket_boundaries_and_reboot_refusal(self):
        ticket = start_ticket()
        with patch('time.clock_gettime_ns', return_value=ticket['issued_ns']):
            check_start(ticket)
        for now in (ticket['issued_ns'] - 1, ticket['expires_ns']):
            with patch('time.clock_gettime_ns', return_value=now), self.assertRaises(ValueError):
                check_start(ticket)
        for changed in (dict(ticket, boot_id='00000000-0000-0000-0000-000000000000'),
                        dict(ticket, issued_ns=True),
                        dict(ticket, expires_ns=ticket['expires_ns'] + 1)):
            with self.assertRaises(ValueError):
                check_start(changed)
        with patch('time.time', side_effect=AssertionError('wall clock must not be consulted')):
            check_start(ticket)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bootstrap')
    def test_actual_bootstrap_rejects_expired_ticket_before_worker_code(self):
        ticket = start_ticket()
        ticket['issued_ns'] -= 6_000_000_000
        ticket['expires_ns'] -= 6_000_000_000
        result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', _BOOTSTRAP,
                                 json.dumps({'start_ticket': ticket})], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'worker start ticket expired', result.stderr)


@unittest.skipUnless(os.environ.get('YEOUL_RUN_RESOURCE_TESTS') == '1' and sys.platform == 'linux',
                     'explicit approval for temporary system service integration required')
class IsolatedIntegration(unittest.TestCase):
    def test_actual_isolated_shadow_and_failure_hold(self):
        # This administrative bridge is test-host code, NOT a worker-facing API.
        trace = []
        def broker(command, payload, timeout):
            self.assertIn(command[0], ('/usr/bin/systemd-run', '/usr/bin/systemctl'))
            action = 'start' if command[0].endswith('systemd-run') else ('show' if 'show' in command else 'stop')
            try:
                value = CommandWorker(['/usr/bin/sudo', '-n', *command], cwd='/tmp',
                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, timeout=timeout)(payload)
            except WorkerTransportError as exc:
                trace.append((action, exc.reason))
                raise
            # Retain only control observations, never input or proposal bytes.
            trace.append((action, value.decode('ascii', errors='replace')[:80] if action == 'show' else 'ok'))
            return value
        snapshot = dict(target='synthetic-sum', revision='r1', sources=[
            dict(id=role, role=role, category='REQUIRED_ACTIVE', body=body)
            for role, body in [('goal', 'Sum observed rows'), ('status', '[4,7,6]'),
                ('action', 'Proposal only'), ('policy', 'READ_ONLY'), ('constraints', 'No source writes')]])
        snapshot['sources'].append(dict(id='private', role='audit', category='VALIDATOR_ONLY', body='PRIVATE_MARKER'))
        code = '''
import hashlib, json, sys
from pathlib import Path
raw = sys.stdin.buffer.read()
assert b'PRIVATE_MARKER' not in raw
assert not Path('/home').exists() and not Path('/data').exists()
assert not Path('/run/yeoul-launch').exists()
model = json.loads(raw)
rows = json.loads(next(s['body'] for s in model['active'] if s['id'] == 'status'))
print(json.dumps(dict(input_sha256=hashlib.sha256(raw).hexdigest(), proposal=dict(total=sum(rows)))))
'''
        with tempfile.TemporaryDirectory(prefix='yeoul-isolated-audit-') as tmp:
            events = []
            journal = WorkerJournal(Path(tmp).resolve())
            def record(raw):
                event = json.loads(raw)
                journal(raw)
                events.append(event)
            def make_worker(argv, timeout):
                allowed = ProfileBroker(journal, broker, argv=argv, uid=os.getuid(), gid=os.getgid(), timeout=timeout)
                return IsolatedWorker(argv, broker=allowed, record_event=record, timeout=timeout)
            def verify(snapshot_raw, proposal_raw, binding):
                return dict(status='pass' if json.loads(proposal_raw)['total'] == 17 else 'fail',
                            evidence_ref='synthetic:sum')
            worker = make_worker(['/usr/bin/python3', '-I', '-B', '-c', code], 10)
            result = run_shadow('resource-shadow', lambda: snapshot, worker, {'sum': ('fixture', verify)})
            self.assertEqual(result['state'], 'ready_for_review', result)
            self.assertEqual(result['authority'], 'NONE')
            self.assertEqual(result['execution'], 'NOT_PERFORMED')
            self.assertEqual(result['proposal'], {'total': 17})
            self.assertEqual(events[-1]['state'], 'returned')
            self.assertEqual(len(list(Path(tmp).resolve().rglob('00000*.json'))), len(events))
            retained = WorkerJournal(Path(tmp).resolve()).read_output(events[0]['unit'])
            self.assertEqual(json.loads(retained)['proposal'], {'total': 17})
            noisy = make_worker(['/usr/bin/python3', '-I', '-B', '-c',
                'import sys; sys.stdin.buffer.read(); print("x"*70000)'], 10)
            result = run_shadow('resource-overflow', lambda: snapshot, noisy, {'sum': ('fixture', verify)})
            self.assertEqual(result['state'], 'needs_review', result)
            self.assertIn('worker_stdout_limit', result['reasons'], (result, trace))
            self.assertEqual(events[-1]['state'], 'held')
            stalled = make_worker(['/usr/bin/python3', '-I', '-B', '-c',
                'import sys,time; sys.stdin.buffer.read(); time.sleep(8)'], 1)
            result = run_shadow('resource-deadline', lambda: snapshot, stalled, {'sum': ('fixture', verify)})
            self.assertEqual(result['state'], 'needs_review', result)
            self.assertEqual(result['execution'], 'NOT_PERFORMED')
            self.assertEqual(events[-1]['state'], 'held')
            calls = []
            def counted(command, payload, timeout):
                calls.append(command)
                return broker(command, payload, timeout)
            access = WorkerAccess(Path(tmp).resolve())
            access.configure({'synthetic-task': {'uid': os.getuid(), 'actions': ['execute', 'inspect']}})
            server, client = socket.socketpair()
            self.addCleanup(server.close)
            self.addCleanup(client.close)
            managed = WorkerTasks(Path(tmp).resolve(), counted, argv=['/usr/bin/python3', '-I', '-B', '-c', code],
                uid=os.getuid(), gid=os.getgid(), authorize=access.authorize, timeout=10)
            supplied = []
            def mapped(payload):
                supplied.append(payload)
                with access.connection(server):
                    return managed.execute('synthetic-task', payload)
            result = run_shadow('logical-shadow', lambda: snapshot, mapped, {'sum': ('fixture', verify)})
            self.assertEqual(result['state'], 'ready_for_review', result)
            count = len(calls)
            reopened = WorkerTasks(Path(tmp).resolve(), counted, argv=['/usr/bin/python3', '-I', '-B', '-c', code],
                uid=os.getuid(), gid=os.getgid(), authorize=access.authorize, timeout=10)
            with access.connection(server):
                self.assertEqual(json.loads(reopened.execute('synthetic-task', supplied[0]))['proposal'], {'total': 17})
            self.assertEqual(len(calls), count)

            # A request accepted by the host but delayed before service creation
            # must fail inside the real service before any payload program runs.
            delayed_calls = []
            def delayed(command, payload, timeout):
                if command[0].endswith('systemd-run'):
                    delayed_calls.append(command)
                    time.sleep(5.1)
                return broker(command, payload, timeout)
            delayed_argv = ['/usr/bin/python3', '-I', '-B', '-c', 'print("UNEXPECTED_WORKER_START")']
            delayed_profile = ProfileBroker(journal, delayed, argv=delayed_argv,
                uid=os.getuid(), gid=os.getgid(), timeout=10)
            expired_worker = IsolatedWorker(delayed_argv, broker=delayed_profile,
                record_event=record, timeout=10)
            with self.assertRaises(WorkerTransportError):
                expired_worker(b'synthetic')
            self.assertEqual(len(delayed_calls), 1)
            self.assertNotEqual(events[-1]['state'], 'returned')


    def test_actual_running_service_cancellation(self):
        from concurrent.futures import ThreadPoolExecutor
        def invoke(command, payload, timeout):
            return CommandWorker(['/usr/bin/sudo', '-n', *command], cwd='/tmp',
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, timeout=timeout)(payload)
        with tempfile.TemporaryDirectory(prefix='yeoul-cancel-audit-') as tmp:
            tasks = WorkerTasks(Path(tmp).resolve(), invoke,
                argv=['/usr/bin/python3', '-I', '-B', '-c', 'import time; time.sleep(20)'],
                uid=os.getuid(), gid=os.getgid(), timeout=10,
                authorize=lambda task, action: task == 'synthetic-cancel' and action in ('execute', 'cancel', 'inspect'))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(tasks.execute, 'synthetic-cancel', b'synthetic')
                deadline = time.monotonic() + 5
                loaded = False
                while time.monotonic() < deadline and not pending.done():
                    if not tasks._path('synthetic-cancel').exists():
                        time.sleep(.05)
                        continue
                    unit = tasks._load('synthetic-cancel')['unit']
                    state = tasks.worker._call(['/usr/bin/systemctl', 'show', unit, '--property=LoadState', '--value'])
                    if state.strip() == b'loaded':
                        loaded = True
                        break
                    time.sleep(.05)
                self.assertTrue(loaded, 'synthetic service was not observed loaded')
                result = tasks.cancel('synthetic-cancel', note='approved synthetic running-service stop')
                self.assertEqual(result['state'], 'absence_observed', result)
                self.assertFalse(result['cancellation_complete'])
                with self.assertRaises(WorkerTransportError):
                    pending.result(timeout=15)
                self.assertEqual(tasks.inspect('synthetic-cancel')['state'], 'cancel_requested')


    def test_actual_late_service_after_cancellation_is_held(self):
        with tempfile.TemporaryDirectory(prefix='yeoul-late-cancel-') as tmp:
            observed = []
            def invoke(command, payload, timeout):
                if command[0].endswith('systemd-run'):
                    observed.append(tasks.cancel('late-task', note='cancel queued synthetic request'))
                return CommandWorker(['/usr/bin/sudo', '-n', *command], cwd='/tmp',
                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, timeout=timeout)(payload)
            tasks = WorkerTasks(Path(tmp).resolve(), invoke,
                argv=['/usr/bin/python3', '-I', '-B', '-c', 'print("UNEXPECTED_LATE_RESULT")'],
                uid=os.getuid(), gid=os.getgid(), timeout=10,
                authorize=lambda task, action: task == 'late-task' and action in ('execute', 'cancel', 'inspect'))
            with self.assertRaises(WorkerTransportError):
                tasks.execute('late-task', b'synthetic')
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0]['state'], 'absence_observed')
            unit = tasks._load('late-task')['unit']
            report = tasks.journal.inspect(unit)
            self.assertNotEqual(report['state'], 'returned')
            self.assertFalse((tasks.journal.directory(unit) / 'output.json').exists())


    def test_actual_worker_survives_host_death_then_reopened_host_stops_it(self):
        import signal
        import yeoul_mcp
        source = str(Path(yeoul_mcp.__file__).resolve().parent.parent)
        worker_argv = ['/usr/bin/python3', '-I', '-B', '-c',
                       'import time; time.sleep(30) # YEOUL_SYNTHETIC_HOST_DEATH']
        code = r'''
import json, os, sys
from pathlib import Path
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import CommandWorker
def invoke(command, payload, timeout):
    return CommandWorker(['/usr/bin/sudo', '-n', *command], cwd='/tmp',
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, timeout=timeout)(payload)
tasks = WorkerTasks(Path(sys.argv[1]), invoke, argv=json.loads(sys.argv[2]),
    uid=os.getuid(), gid=os.getgid(), timeout=20, authorize=lambda task, action: True)
tasks.execute('host-death', b'synthetic')
'''
        calls = []
        def observe(command, payload, timeout):
            self.assertFalse(command[0].endswith('systemd-run'), 'reopened host must not launch')
            calls.append(command)
            return CommandWorker(['/usr/bin/sudo', '-n', *command], cwd='/tmp',
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}, timeout=timeout)(payload)
        with tempfile.TemporaryDirectory(prefix='yeoul-real-host-death-') as tmp:
            root = Path(tmp).resolve()
            reopened = WorkerTasks(root, observe, argv=worker_argv, uid=os.getuid(), gid=os.getgid(),
                                  timeout=20, authorize=lambda task, action: True)
            child = subprocess.Popen([sys.executable, '-B', '-c', code, str(root), json.dumps(worker_argv)],
                env=dict(os.environ, PYTHONPATH=source), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            unit = None
            try:
                worker_seen = False
                deadline = time.monotonic() + 5
                expected = b'\0'.join(arg.encode() for arg in worker_argv) + b'\0'
                while time.monotonic() < deadline and child.poll() is None:
                    if reopened._path('host-death').exists():
                        unit = reopened._load('host-death')['unit']
                        group = Path('/sys/fs/cgroup/system.slice') / unit / 'cgroup.procs'
                        if group.exists():
                            for pid in group.read_text().split():
                                try:
                                    if (Path('/proc') / pid / 'cmdline').read_bytes() == expected:
                                        worker_seen = True
                                        break
                                except FileNotFoundError:
                                    pass
                    if worker_seen:
                        break
                    time.sleep(.05)
                self.assertTrue(worker_seen, 'actual synthetic worker was not observed in its unit cgroup')
                child.kill()
                _, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, -signal.SIGKILL, stderr)
                active = observe(('/usr/bin/systemctl', 'show', unit, '--property=ActiveState', '--value'), b'', 5)
                self.assertEqual(active.strip(), b'active', 'service did not outlive its host')
                originals = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                before = reopened.inspect('host-death')
                self.assertEqual(before['state'], 'start_requested')
                with self.assertRaisesRegex(WorkerTransportError, 'needs_attention'):
                    reopened.execute('host-death', b'synthetic')
                result = reopened.cancel('host-death', note='approved recovery of synthetic orphan service')
                self.assertEqual(result['state'], 'absence_observed', result)
                self.assertFalse(result['cancellation_complete'])
                self.assertTrue(all(path.read_bytes() == raw for path, raw in originals.items()))
                self.assertEqual(reopened.inspect('host-death')['state'], 'cancel_requested')
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
                # Cleanup is restricted to the validated unit created by this fixture.
                if unit is not None:
                    state = observe(('/usr/bin/systemctl', 'show', unit, '--property=LoadState', '--value'), b'', 5)
                    if state.strip() != b'not-found':
                        observe(('/usr/bin/systemctl', '--no-ask-password', 'stop', unit), b'', 8)
                    self.assertEqual(observe(('/usr/bin/systemctl', 'show', unit,
                        '--property=LoadState', '--value'), b'', 5).strip(), b'not-found')


if __name__ == '__main__':
    unittest.main()
