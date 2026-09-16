"""Persistent execution records and host request allowlist, temporary roots only."""
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
from yeoul_mcp.isolated_worker import IsolatedWorker
from yeoul_mcp.worker_host import WorkerJournal, ProfileBroker
from yeoul_mcp.worker_transport import WorkerTransportError


@unittest.skipUnless(sys.platform == 'linux', 'Linux host adapter')
class WorkerHost(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='yeoul-host-journal-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.journal = WorkerJournal(self.root)
        self.calls, self.events = [], []
        self.argv = ['/usr/bin/python3', '-c', 'pass']
        self.broker = ProfileBroker(self.journal, self.invoke, argv=self.argv, uid=1000, gid=1000)
        self.worker = IsolatedWorker(self.argv, uid=1000, gid=1000, broker=self.broker, record_event=self.record)

    def invoke(self, command, payload, timeout):
        self.calls.append((command, payload, timeout))
        return b'proposal' if command[0].endswith('systemd-run') else b'not-found\n'

    def record(self, raw):
        self.journal(raw)
        self.events.append(json.loads(raw))

    def test_reopen_preserves_manifest_history_and_dispatch_reservation(self):
        self.assertEqual(self.worker(b'input'), b'proposal')
        unit = self.events[0]['unit']
        reopened = WorkerJournal(self.root)
        report = reopened.inspect(unit)
        self.assertEqual(report['state'], 'returned')
        self.assertTrue(report['dispatch_reserved'])
        self.assertFalse(report['retry_authorized'])
        self.assertFalse(report['needs_attention'])
        self.assertEqual(report['events'], self.events)
        count = len(self.calls)
        self.assertEqual(reopened.read_output(unit), b'proposal')
        self.assertEqual(len(self.calls), count)
        with self.assertRaises(ValueError):
            reopened.reserve(unit, self.events[0]['manifest'])

    def test_repeated_start_request_does_not_invoke_again(self):
        self.worker(b'input')
        start = next(call for call in self.calls if call[0][0].endswith('systemd-run'))
        count = len(self.calls)
        with self.assertRaises(ValueError):
            self.broker(*start)
        self.assertEqual(len(self.calls), count)

    def test_expiry_before_reservation_never_dispatches(self):
        original = self.record
        def expired_record(raw):
            original(raw)
            if json.loads(raw)['state'] == 'start_requested':
                ticket = self.events[0]['manifest']['start_ticket']
                clock = patch('time.clock_gettime_ns', return_value=ticket['expires_ns'])
                clock.start()
                self.addCleanup(clock.stop)
        worker = IsolatedWorker(self.argv, uid=1000, gid=1000,
                                broker=self.broker, record_event=expired_record)
        with self.assertRaises(WorkerTransportError):
            worker(b'input')
        self.assertFalse(any(call[0][0].endswith('systemd-run') for call in self.calls))
        self.assertFalse(self.journal.inspect(self.events[0]['unit'])['dispatch_reserved'])

    def test_profile_argument_input_and_property_tampering_refused(self):
        self.worker(b'input')
        command, payload, timeout = next(call for call in self.calls if call[0][0].endswith('systemd-run'))
        count = len(self.calls)
        for changed, data in ((command + ('--uid=0',), payload),
                              (tuple('--uid=0' if v == '--uid=1000' else v for v in command), payload),
                              (command, b'changed input')):
            with self.subTest(change=changed[-1][:20]), self.assertRaises(ValueError):
                self.broker(changed, data, timeout)
        with self.assertRaises(ValueError):
            self.broker(('/usr/bin/systemctl', '--no-ask-password', 'stop', 'existing.service'), b'', 8)
        self.assertEqual(len(self.calls), count)

    def test_log_failure_before_dispatch_never_invokes_service(self):
        from yeoul_mcp import worker_host
        original = worker_host.write_json
        def write(path, value):
            if path.name == 'dispatch.json':
                raise OSError('synthetic reservation persistence failure')
            return original(path, value)
        with patch.object(worker_host, 'write_json', side_effect=write):
            with self.assertRaises(WorkerTransportError):
                self.worker(b'input')
        self.assertFalse(any(call[0][0].endswith('systemd-run') for call in self.calls))

    def test_uncertain_start_is_reserved_after_reopen(self):
        def invoke(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                raise WorkerTransportError('worker_timeout')
            return b'not-found'
        broker = ProfileBroker(self.journal, invoke, argv=self.argv, uid=1000, gid=1000)
        worker = IsolatedWorker(self.argv, broker=broker, uid=1000, gid=1000, record_event=self.record)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_timeout'):
            worker(b'input')
        unit = self.events[0]['unit']
        report = WorkerJournal(self.root).inspect(unit)
        self.assertEqual(report['state'], 'held')
        self.assertTrue(report['dispatch_reserved'])
        with self.assertRaises(ValueError):
            WorkerJournal(self.root).reserve(unit, self.events[0]['manifest'])

    def test_duplicate_delivery_preserves_bytes_but_changed_event_refused(self):
        self.worker(b'input')
        unit = self.events[0]['unit']
        directory = self.journal.directory(unit)
        before = {p.name:p.read_bytes() for p in directory.iterdir()}
        self.journal(json.dumps(self.events[0]).encode())
        event = dict(self.events[0], manifest_sha256='0'*64)
        with self.assertRaises(ValueError):
            self.journal(json.dumps(event).encode())
        self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})

    def test_missing_or_changed_record_not_accepted_after_restart(self):
        self.worker(b'input')
        unit = self.events[0]['unit']
        path = self.journal.directory(unit) / '000002.json'
        path.rename(path.with_suffix('.retained'))
        with self.assertRaises(ValueError):
            WorkerJournal(self.root).inspect(unit)

    def test_changed_output_is_not_replayed(self):
        self.worker(b'input')
        unit = self.events[0]['unit']
        path = self.journal.directory(unit) / 'output.json'
        value = json.loads(path.read_text())
        value['base64'] = 'YmFk'
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            WorkerJournal(self.root).read_output(unit)

    def test_output_storage_failure_withholds_result(self):
        from yeoul_mcp import worker_host
        original = worker_host.write_json
        def write(path, value):
            if path.name == 'output.json':
                raise OSError('synthetic output storage failure')
            return original(path, value)
        with patch.object(worker_host, 'write_json', side_effect=write):
            with self.assertRaises(WorkerTransportError):
                self.worker(b'input')
        unit = self.events[0]['unit']
        self.assertEqual(WorkerJournal(self.root).inspect(unit)['state'], 'held')
        with self.assertRaises(ValueError):
            WorkerJournal(self.root).read_output(unit)

    def test_two_processes_only_one_reserves_dispatch(self):
        def prepare_only(raw):
            self.record(raw)
            if json.loads(raw)['state'] == 'start_requested':
                raise OSError('synthetic stop before broker invocation')
        self.worker.record_event = prepare_only
        with self.assertRaises(WorkerTransportError):
            self.worker(b'input')
        unit = self.events[0]['unit']
        code = '''
import sys
from yeoul_mcp.worker_host import WorkerJournal
j = WorkerJournal(sys.argv[1])
m = j.inspect(sys.argv[2])['events'][0]['manifest']
try:
    j.reserve(sys.argv[2], m)
except ValueError:
    print('blocked')
else:
    print('reserved')
'''
        import yeoul_mcp
        source = str(Path(yeoul_mcp.__file__).resolve().parents[1])
        children = []
        try:
            for _ in range(2):
                children.append(subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root), unit],
                    env=dict(os.environ, PYTHONPATH=source), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            outcomes = []
            for child in children:
                out, err = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, out + err)
                outcomes.append(out.strip())
            self.assertEqual(sorted(outcomes), ['blocked', 'reserved'])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_different_profile_cannot_stop_retained_unit(self):
        self.worker(b'input')
        unit = self.events[0]['unit']
        other = ProfileBroker(self.journal, self.invoke, argv=['/usr/bin/true'], uid=1000, gid=1000)
        count = len(self.calls)
        with self.assertRaises(ValueError):
            other(('/usr/bin/systemctl', '--no-ask-password', 'stop', unit), b'', 8)
        self.assertEqual(len(self.calls), count)


if __name__ == '__main__':
    unittest.main()
