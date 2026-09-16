"""Bounded operator confirmation using temporary synthetic worker records."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.recovery_actions import RecoveryActions
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError
from yeoul_mcp.worker_host import _sha
from yeoul_mcp.workspace import write_json


@unittest.skipUnless(sys.platform == 'linux', 'Linux host tasks')
class RecoveryConfirmation(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-recovery-actions-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.uid, self.allowed, self.calls = 1000, True, []
        def invoke(command, payload, timeout):
            self.calls.append(command)
            return b'proposal' if command[0].endswith('systemd-run') else b'not-found'
        self.tasks = WorkerTasks(self.root, invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                                 authorize=lambda task, action: self.allowed)
        self.tasks.execute('synthetic', b'input')
        self.actions = RecoveryActions(self.tasks, principal=lambda: self.uid)

    def prepare(self):
        return self.actions.prepare_cancel('synthetic', note='synthetic operator confirmation')['token']

    def test_preview_has_no_effect_and_confirmation_is_single_use(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        count = len(self.calls)
        token = self.prepare()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        result = self.actions.confirm_cancel(token)
        self.assertFalse(result['cancellation_complete'])
        count = len(self.calls)
        with self.assertRaises(WorkerTransportError):
            self.actions.confirm_cancel(token)
        self.assertEqual(len(self.calls), count)

    def test_other_account_expiry_and_restart_deny(self):
        token = self.prepare()
        self.uid += 1
        with self.assertRaises(WorkerTransportError):
            self.actions.confirm_cancel(token)
        self.uid -= 1
        restarted = RecoveryActions(self.tasks, principal=lambda: self.uid)
        with self.assertRaises(WorkerTransportError):
            restarted.confirm_cancel(token)
        with patch('yeoul_mcp.recovery_actions._now', return_value=float('inf')):
            with self.assertRaises(WorkerTransportError):
                self.actions.confirm_cancel(token)
        self.assertFalse(self.tasks._cancelled('synthetic'))

    def test_changed_mapping_is_rejected_inside_cancel_lock(self):
        token = self.prepare()
        row = self.tasks._load('synthetic')
        row['created_ns'] += 1
        row['sha256'] = _sha({k: v for k, v in row.items() if k != 'sha256'})
        write_json(self.tasks._path('synthetic'), row)
        with self.assertRaisesRegex(WorkerTransportError, 'target_changed'):
            self.actions.confirm_cancel(token)
        self.assertFalse(self.tasks._cancelled('synthetic'))

    def test_revoked_permission_and_failed_request_are_not_replayed(self):
        token = self.prepare()
        self.allowed = False
        with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
            self.actions.confirm_cancel(token)
        self.allowed = True
        with self.assertRaisesRegex(WorkerTransportError, 'confirmation_invalid'):
            self.actions.confirm_cancel(token)

    def test_concurrent_confirmations_only_dispatch_once(self):
        token = self.prepare()
        def confirm():
            try:
                self.actions.confirm_cancel(token)
                return 'confirmed'
            except WorkerTransportError:
                return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertCountEqual(results, ['confirmed', 'refused'])
        directory = self.tasks._path('synthetic').with_suffix('.cancellations')
        self.assertEqual(len(list(directory.glob('*.request.json'))), 1)

    def test_pending_limit_and_invalid_identity(self):
        limited = RecoveryActions(self.tasks, principal=lambda: self.uid, max_pending=1)
        limited.prepare_cancel('synthetic', note='first')
        with self.assertRaisesRegex(WorkerTransportError, 'capacity'):
            limited.prepare_cancel('synthetic', note='second')
        self.uid = True
        with self.assertRaisesRegex(WorkerTransportError, 'identity_required'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
