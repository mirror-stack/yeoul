"""Logical worker tasks survive host restarts; no privileged calls by default."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError


@unittest.skipUnless(sys.platform == 'linux', 'Linux isolated task adapter')
class WorkerTaskContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='yeoul-logical-worker-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls = []
        self.allowed = True
        self.tasks = self.make()

    def invoke(self, command, payload, timeout):
        self.calls.append((command, payload, timeout))
        return b'proposal' if command[0].endswith('systemd-run') else b'not-found'

    def make(self, invoke=None, argv=None):
        return WorkerTasks(self.root, invoke or self.invoke, argv=argv or ['/usr/bin/true'], uid=1000, gid=1000,
                           authorize=lambda task, action: self.allowed)

    def test_restart_delivers_same_output_without_second_invocation(self):
        self.assertEqual(self.tasks.execute('ticket-1', b'input'), b'proposal')
        count = len(self.calls)
        reopened = self.make()
        self.assertEqual(reopened.execute('ticket-1', b'input'), b'proposal')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(reopened.inspect('ticket-1')['state'], 'returned')

    def test_changed_input_or_profile_cannot_reuse_task(self):
        self.tasks.execute('ticket-1', b'input')
        count = len(self.calls)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_conflict'):
            self.tasks.execute('ticket-1', b'other')
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_conflict'):
            self.make(argv=['/usr/bin/false']).execute('ticket-1', b'input')
        self.assertEqual(len(self.calls), count)

    def test_current_authorization_required_for_replay_and_inspection(self):
        self.tasks.execute('ticket-1', b'input')
        self.allowed = False
        with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
            self.tasks.execute('ticket-1', b'input')
        with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
            self.tasks.inspect('ticket-1')

    def test_uncertain_execution_does_not_get_a_new_unit_after_restart(self):
        def fail(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                raise WorkerTransportError('worker_timeout')
            return b'not-found'
        with self.assertRaises(WorkerTransportError):
            self.make(invoke=fail).execute('ticket-1', b'input')
        before = self.make().inspect('ticket-1')
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_needs_attention'):
            self.make().execute('ticket-1', b'input')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.make().inspect('ticket-1')['unit'], before['unit'])

    def test_mapping_only_interruption_requires_inspection_not_new_execution(self):
        from yeoul_mcp.isolated_worker import IsolatedWorker
        with patch.object(IsolatedWorker, 'run', side_effect=RuntimeError('synthetic crash')):
            with self.assertRaises(RuntimeError):
                self.tasks.execute('ticket-1', b'input')
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_needs_attention'):
            self.make().execute('ticket-1', b'input')
        self.assertEqual(self.calls, [])

    def test_operator_retirement_preserves_originals_and_blocks_task_id(self):
        from yeoul_mcp.isolated_worker import IsolatedWorker
        with patch.object(IsolatedWorker, 'run', side_effect=RuntimeError('synthetic crash')):
            with self.assertRaises(RuntimeError):
                self.tasks.execute('ticket-1', b'input')
        mapping = self.tasks._path('ticket-1')
        before = mapping.read_bytes()
        with self.assertRaises(ValueError):
            self.tasks.retire('ticket-1', note='not enough')
        result = self.tasks.retire('ticket-1', note='synthetic state inspected', children_stopped=True)
        self.assertTrue(result['changed'])
        self.assertEqual(mapping.read_bytes(), before)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_retired'):
            self.make().execute('ticket-1', b'input')
        self.assertEqual(self.make().inspect('ticket-1')['state'], 'retired')

    def test_retirement_before_dispatch_reservation_prevents_launch(self):
        from yeoul_mcp.worker_host import WorkerJournal
        original = WorkerJournal.__call__
        def journal(store, raw):
            original(store, raw)
            if json.loads(raw)['state'] == 'start_requested':
                self.tasks.retire('ticket-1', note='before dispatch; no child launched', children_stopped=True)
        with patch.object(WorkerJournal, '__call__', journal):
            with self.assertRaises(WorkerTransportError):
                self.tasks.execute('ticket-1', b'input')
        self.assertFalse(any(c[0][0].endswith('systemd-run') for c in self.calls))

    def test_permission_revoked_before_dispatch_is_rechecked(self):
        from yeoul_mcp.worker_host import WorkerJournal
        original = WorkerJournal.__call__
        def journal(store, raw):
            original(store, raw)
            if json.loads(raw)['state'] == 'start_requested':
                self.allowed = False
        with patch.object(WorkerJournal, '__call__', journal):
            with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
                self.tasks.execute('ticket-1', b'input')
        self.assertFalse(any(c[0][0].endswith('systemd-run') for c in self.calls))

    def test_retirement_after_dispatch_withholds_delivery_but_preserves_result(self):
        def invoke(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                self.tasks.retire('ticket-1', note='synthetic dispatch inspected', children_stopped=True)
                return b'proposal'
            return b'not-found'
        tasks = self.make(invoke=invoke)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_task_retired_or_changed'):
            tasks.execute('ticket-1', b'input')
        self.assertEqual(tasks.inspect('ticket-1')['state'], 'retired')
        row = tasks._load('ticket-1')
        self.assertEqual(tasks.journal.read_output(row['unit']), b'proposal')

    def test_revocation_during_execution_withholds_result(self):
        def invoke(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                self.allowed = False
                return b'proposal'
            return b'not-found'
        with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
            self.make(invoke=invoke).execute('ticket-1', b'input')

    def test_two_processes_share_one_logical_task_execution(self):
        import yeoul_mcp
        source = str(Path(yeoul_mcp.__file__).resolve().parents[1])
        code = '''
import sys
from pathlib import Path
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError
def invoke(command, payload, timeout):
    if command[0].endswith('systemd-run'):
        with (Path(sys.argv[1])/'invocations.txt').open('a') as stream:
            stream.write('called\\n')
        return b'proposal'
    return b'not-found'
tasks = WorkerTasks(sys.argv[1], invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                    authorize=lambda task, action: True)
try:
    tasks.execute('ticket-1', b'input')
except WorkerTransportError as exc:
    assert exc.reason == 'worker_task_needs_attention', exc
    print('held')
else:
    print('returned')
'''
        children = []
        try:
            for _ in range(2):
                children.append(subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root)],
                    env=dict(os.environ, PYTHONPATH=source), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            states = []
            for child in children:
                out, err = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, out + err)
                states.append(out.strip())
            self.assertIn('returned', states)
            self.assertEqual((self.root/'invocations.txt').read_text(), 'called\n')
            self.assertEqual(self.make().execute('ticket-1', b'input'), b'proposal')
            self.assertEqual(self.calls, [])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()


    def test_cancel_before_reservation_blocks_start_without_attestation(self):
        from yeoul_mcp.worker_host import WorkerJournal
        original = WorkerJournal.__call__
        def journal(store, raw):
            original(store, raw)
            if json.loads(raw)['state'] == 'start_requested':
                result = self.tasks.cancel('ticket-1', note='synthetic cancellation')
                self.assertEqual(result['state'], 'dispatch_not_reserved')
                self.assertFalse(result['cancellation_complete'])
        with patch.object(WorkerJournal, '__call__', journal), self.assertRaises(WorkerTransportError):
            self.tasks.execute('ticket-1', b'input')
        self.assertFalse(any(c[0][0].endswith('systemd-run') for c in self.calls))
        with self.assertRaisesRegex(WorkerTransportError, 'cancel_requested'):
            self.make().execute('ticket-1', b'input')

    def test_cancel_after_dispatch_stops_exact_unit_and_withholds_output(self):
        observations = []
        def invoke(command, payload, timeout):
            self.calls.append((command, payload, timeout))
            if command[0].endswith('systemd-run'):
                observations.append(tasks.cancel('ticket-1', note='synthetic cancellation'))
                return b'proposal'
            if 'show' in command and not observations:
                # Initial preflight must remain absent; cancellation sees loaded.
                return b'loaded' if any(c[0][0].endswith('systemd-run') for c in self.calls) and not any('stop' in c[0] for c in self.calls) else b'not-found'
            return b'not-found'
        tasks = self.make(invoke=invoke)
        with self.assertRaises(WorkerTransportError):
            tasks.execute('ticket-1', b'input')
        unit = tasks._load('ticket-1')['unit']
        self.assertTrue(any(c[0] == ('/usr/bin/systemctl', '--no-ask-password', 'stop', unit) for c in self.calls))
        self.assertEqual(observations[0]['state'], 'absence_observed')
        self.assertFalse(observations[0]['cancellation_complete'])
        self.assertEqual(tasks.journal.read_output(unit), b'proposal')
        self.assertEqual(self.make().inspect('ticket-1')['state'], 'cancel_requested')

    def test_cancel_permission_and_persistence_fail_before_host_call(self):
        self.tasks.execute('ticket-1', b'input')
        count = len(self.calls)
        self.allowed = False
        with self.assertRaises(WorkerTransportError):
            self.tasks.cancel('ticket-1', note='denied')
        self.assertFalse(self.tasks._cancelled('ticket-1'))
        self.allowed = True
        with patch('yeoul_mcp.worker_tasks.write_json', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.tasks.cancel('ticket-1', note='not durable')
        self.assertEqual(len(self.calls), count)

    def test_failed_stop_is_preserved_and_reobservation_does_not_restart(self):
        self.tasks.execute('ticket-1', b'input')
        def broken(command, payload, timeout):
            raise RuntimeError('PRIVATE_BROKER_ERROR')
        result = self.make(invoke=broken).cancel('ticket-1', note='synthetic')
        self.assertEqual(result['state'], 'unconfirmed')
        self.assertEqual(result['stage'], 'initial_show')
        count = len(self.calls)
        second = self.make().cancel('ticket-1', note='observe again')
        self.assertEqual(second['state'], 'absence_observed')
        self.assertTrue(all(not c[0][0].endswith('systemd-run') for c in self.calls[count:]))
        directory = self.tasks._path('ticket-1').with_suffix('.cancellations')
        self.assertEqual(len(list(directory.iterdir())), 4)
        self.assertNotIn('PRIVATE_BROKER_ERROR', ''.join(p.read_text() for p in directory.iterdir()))


    def test_restart_reports_interrupted_cancellation_without_mutation(self):
        from yeoul_mcp import worker_tasks
        self.tasks.execute('ticket-1', b'input')
        original = worker_tasks.write_json
        def fail_result(path, value):
            if path.name.endswith('.result.json'):
                raise OSError('synthetic result persistence crash')
            original(path, value)
        with patch.object(worker_tasks, 'write_json', side_effect=fail_result), self.assertRaises(OSError):
            self.tasks.cancel('ticket-1', note='synthetic')
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        count = len(self.calls)
        report = self.make().inspect('ticket-1')
        self.assertEqual(report['cancellation']['unresolved_attempts'], 1)
        self.assertEqual(report['cancellation']['attempts'][0]['state'], 'observation_missing')
        self.assertFalse(report['retry_authorized'])
        self.assertEqual(len(self.calls), count)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_corrupt_cancellation_evidence_is_visible_and_blocks_further_stop(self):
        from yeoul_mcp.workspace import write_json
        self.tasks.execute('ticket-1', b'input')
        self.tasks.cancel('ticket-1', note='synthetic')
        directory = self.tasks._path('ticket-1').with_suffix('.cancellations')
        result_path = next(directory.glob('*.result.json'))
        value = json.loads(result_path.read_text())
        value['cancellation_complete'] = True
        write_json(result_path, value)
        count = len(self.calls)
        report = self.make().inspect('ticket-1')
        self.assertEqual(report['cancellation']['status'], 'evidence_unreadable')
        self.assertTrue(report['needs_attention'])
        with self.assertRaises(ValueError):
            self.make().cancel('ticket-1', note='must inspect evidence first')
        self.assertEqual(len(self.calls), count)

    def test_orphan_result_never_becomes_completed_cancellation(self):
        self.tasks.execute('ticket-1', b'input')
        self.tasks.cancel('ticket-1', note='synthetic')
        directory = self.tasks._path('ticket-1').with_suffix('.cancellations')
        # Delete only a generated temporary fixture to model interrupted/corrupt storage.
        next(directory.glob('*.request.json')).unlink()
        report = self.make().inspect('ticket-1')
        self.assertEqual(report['cancellation']['status'], 'evidence_unreadable')
        self.assertFalse(report['cancellation']['cancellation_complete'])

    def test_64_incomplete_attempts_exhaust_bound_before_host_io(self):
        from yeoul_mcp.workspace import write_json
        from yeoul_mcp import worker_tasks
        self.tasks.execute('ticket-1', b'input')
        original = worker_tasks.write_json
        def fail_result(path, value):
            if path.name.endswith('.result.json'):
                raise OSError('synthetic crash')
            original(path, value)
        with patch.object(worker_tasks, 'write_json', side_effect=fail_result), self.assertRaises(OSError):
            self.tasks.cancel('ticket-1', note='synthetic')
        directory = self.tasks._path('ticket-1').with_suffix('.cancellations')
        first = json.loads(next(directory.glob('*.request.json')).read_text())
        for i in range(63):
            attempt = f'{i:032x}'
            write_json(directory / (attempt + '.request.json'), dict(first, attempt=attempt))
        count = len(self.calls)
        self.assertEqual(self.make().inspect('ticket-1')['cancellation']['unresolved_attempts'], 64)
        with self.assertRaisesRegex(ValueError, 'observation limit'):
            self.make().cancel('ticket-1', note='bounded')
        self.assertEqual(len(self.calls), count)


    def test_actual_gate_process_denies_after_cancellation_within_ticket_window(self):
        from yeoul_mcp.isolated_worker import _START_GUARD
        observed = []
        def invoke(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                manifest = json.loads(command[-1])
                self.assertEqual(manifest['version'], 3)
                code = _START_GUARD + '\nimport json,sys; check_launch(json.loads(sys.argv[1]), sys.argv[2])'
                argv = [sys.executable, '-I', '-B', '-c', code, json.dumps(manifest), manifest['launch_directory']]
                before = subprocess.run(argv, capture_output=True, timeout=5)
                self.assertEqual(before.returncode, 0, before.stderr)
                observed.append(tasks.cancel('ticket-1', note='revoke before delayed start'))
                after = subprocess.run(argv, capture_output=True, timeout=5)
                self.assertNotEqual(after.returncode, 0)
                self.assertIn(b'worker launch revoked', after.stderr)
                raise WorkerTransportError('worker_exit_failed')
            return b'not-found'
        tasks = self.make(invoke=invoke)
        with self.assertRaises(WorkerTransportError):
            tasks.execute('ticket-1', b'input')
        self.assertEqual(observed[0]['state'], 'absence_observed')
        self.assertFalse(observed[0]['cancellation_complete'])

    def test_missing_or_changed_launch_permit_denies(self):
        from yeoul_mcp.isolated_worker import check_launch
        from yeoul_mcp.workspace import write_json
        self.tasks.execute('ticket-1', b'input')
        manifest = self.tasks.journal.inspect(self.tasks._load('ticket-1')['unit'])['events'][0]['manifest']
        directory = Path(manifest['launch_directory'])
        check_launch(manifest, str(directory))
        permit = directory / 'launch.json'
        write_json(permit, {'version': 1, 'unit': manifest['unit'], 'manifest_sha256': '0'*64})
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            check_launch(manifest, str(directory))
        # Delete only the generated temporary permit fixture to model missing storage.
        permit.unlink()
        with self.assertRaises(FileNotFoundError):
            check_launch(manifest, str(directory))


    def test_real_host_sigkill_at_cancellation_persistence_boundaries(self):
        import signal
        import yeoul_mcp
        source = str(Path(yeoul_mcp.__file__).resolve().parent.parent)
        code = r'''
import os, signal, sys
from pathlib import Path
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp import worker_tasks
root, point = Path(sys.argv[1]), sys.argv[2]
def invoke(command, payload, timeout):
    return b'proposal' if command[0].endswith('systemd-run') else b'not-found'
tasks = WorkerTasks(root, invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                   authorize=lambda task, action: True)
tasks.execute('crash-task', b'synthetic')
original = worker_tasks.write_json
def crash_after_write(path, value):
    original(path, value)
    matched = ((point == 'intent' and path.name.endswith('.cancel.json')) or
               (point == 'marker' and path.name == 'launch.revoked.json') or
               (point == 'request' and path.name.endswith('.request.json')) or
               (point == 'result' and path.name.endswith('.result.json')))
    if matched:
        os.kill(os.getpid(), signal.SIGKILL)
worker_tasks.write_json = crash_after_write
tasks.cancel('crash-task', note='synthetic crash boundary')
raise AssertionError('expected kill boundary was not reached')
'''
        for point in ('intent', 'marker', 'request', 'result'):
            with self.subTest(point=point), tempfile.TemporaryDirectory(prefix='yeoul-cancel-crash-') as tmp:
                root = Path(tmp)
                child = subprocess.run([sys.executable, '-B', '-c', code, tmp, point],
                    env=dict(os.environ, PYTHONPATH=source), capture_output=True, timeout=15)
                self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr)
                calls = []
                def observe(command, payload, timeout):
                    calls.append(command)
                    if command[0].endswith('systemd-run'):
                        raise AssertionError('recovery must never launch')
                    return b'not-found'
                reopened = WorkerTasks(root, observe, argv=['/usr/bin/true'], uid=1000, gid=1000,
                                       authorize=lambda task, action: True)
                originals = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                report = reopened.inspect('crash-task')
                self.assertEqual(calls, [])
                evidence = report['cancellation']
                self.assertEqual(evidence['revocation_marker'], 'missing' if point == 'intent' else 'present')
                self.assertEqual(evidence['unresolved_attempts'], 1 if point == 'request' else 0)
                self.assertFalse(evidence['cancellation_complete'])
                with self.assertRaisesRegex(WorkerTransportError, 'cancel_requested'):
                    reopened.execute('crash-task', b'synthetic')
                resumed = reopened.cancel('crash-task', note='operator resumes observation')
                self.assertEqual(resumed['state'], 'absence_observed')
                self.assertFalse(resumed['cancellation_complete'])
                self.assertEqual(reopened.inspect('crash-task')['cancellation']['revocation_marker'], 'present')
                self.assertTrue(all(p.read_bytes() == content for p, content in originals.items()))


    def test_retention_limit_blocks_only_new_work_and_preserves_recovery(self):
        tasks = WorkerTasks(self.root, self.invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                            authorize=lambda task, action: True, max_retained_tasks=1)
        tasks.execute('retained', b'input')
        originals = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        count = len(self.calls)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_retention_limit'):
            tasks.execute('new', b'input')
        self.assertEqual(len(self.calls), count)
        self.assertFalse(tasks._path('new').exists())
        self.assertEqual(tasks.execute('retained', b'input'), b'proposal')
        self.assertEqual(tasks.inspect('retained')['state'], 'returned')
        tasks.cancel('retained', note='cancellation remains available at capacity')
        self.assertTrue(all(p.read_bytes() == raw for p, raw in originals.items()))
        with self.assertRaisesRegex(WorkerTransportError, 'worker_retention_limit'):
            tasks.execute('new', b'input')

    def test_retention_policy_validation_and_unknown_storage(self):
        for limit in (True, 0, 10001, 1.5):
            with self.assertRaises(ValueError):
                WorkerTasks(self.root, self.invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                            authorize=lambda task, action: True, max_retained_tasks=limit)
        from yeoul_mcp.workspace import write_json
        self.tasks.execute('old', b'input')
        write_json(self.tasks._path('old').parent / 'unknown.json', {'synthetic': True})
        count = len(self.calls)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_storage_needs_attention'):
            self.tasks.execute('new', b'input')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.tasks.execute('old', b'input'), b'proposal')

    def test_two_real_hosts_cannot_overbook_the_last_retention_slot(self):
        import yeoul_mcp
        code = r'''
import sys
from pathlib import Path
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError
def invoke(command, payload, timeout):
    return b'proposal' if command[0].endswith('systemd-run') else b'not-found'
tasks = WorkerTasks(Path(sys.argv[1]), invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                   authorize=lambda task, action: True, max_retained_tasks=1)
try:
    tasks.execute(sys.argv[2], b'synthetic')
    print('admitted')
except WorkerTransportError as exc:
    print(exc.reason)
'''
        source = str(Path(yeoul_mcp.__file__).resolve().parent.parent)
        children = []
        try:
            for task in ('first', 'second'):
                children.append(subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root), task],
                    env=dict(os.environ, PYTHONPATH=source), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            states = []
            for child in children:
                out, err = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, err)
                states.append(out.strip())
            self.assertCountEqual(states, ['admitted', 'worker_retention_limit'])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
