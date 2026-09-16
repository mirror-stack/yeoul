"""Real UNIX peer credentials with host-owned temporary policies; no admin calls."""
from contextvars import copy_context
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.worker_access import WorkerAccess
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError


@unittest.skipUnless(sys.platform == 'linux', 'Linux SO_PEERCRED required')
class WorkerPeerAccess(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='yeoul-peer-access-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.access = WorkerAccess(self.root)
        self.grants = {'owned': {'uid': os.getuid(), 'actions': ['execute', 'inspect', 'retire']},
                       'foreign': {'uid': os.getuid()+1, 'actions': ['execute', 'inspect']}}
        self.revision = self.access.configure(self.grants)
        self.client, self.server = socket.socketpair()
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.calls = []
        def invoke(command, payload, timeout):
            self.calls.append(command)
            return b'proposal' if command[0].endswith('systemd-run') else b'not-found'
        self.tasks = WorkerTasks(self.root, invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                                 authorize=self.access.authorize)

    def test_real_peer_may_only_access_its_granted_task(self):
        with self.access.connection(self.server):
            self.assertTrue(self.access.authorize('owned', 'execute'))
            self.assertFalse(self.access.authorize('foreign', 'execute'))
            self.assertFalse(self.access.authorize('unknown', 'execute'))
            self.assertFalse(self.access.authorize('owned', 'configure'))
            self.assertFalse(self.access.authorize('owned', 'cancel'))
            with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
                self.tasks.execute('foreign', b'input')
            self.assertEqual(self.tasks.execute('owned', b'input'), b'proposal')

    def test_no_connection_or_expired_context_never_authorizes(self):
        self.assertFalse(self.access.authorize('owned', 'execute'))
        with self.access.connection(self.server):
            copied = copy_context()
            self.assertTrue(copied.run(self.access.authorize, 'owned', 'execute'))
        self.assertFalse(copied.run(self.access.authorize, 'owned', 'execute'))
        self.assertFalse(self.access.authorize('owned', 'execute'))

    def test_revoke_is_seen_by_existing_connection_and_result_delivery(self):
        with self.access.connection(self.server):
            self.tasks.execute('owned', b'input')
            self.access.configure({}, expected_revision=self.revision)
            with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
                self.tasks.execute('owned', b'input')
        self.assertEqual(len(list((self.root/'.yeoul-mcp/history').glob('worker-access-*.json'))), 1)

    def test_action_grants_are_not_implicitly_elevated(self):
        self.access.configure({'owned': {'uid': os.getuid(), 'actions': ['inspect']}},
                              expected_revision=self.revision)
        with self.access.connection(self.server):
            self.assertTrue(self.access.authorize('owned', 'inspect'))
            self.assertFalse(self.access.authorize('owned', 'execute'))
            self.assertFalse(self.access.authorize('owned', 'retire'))

    def test_corrupt_policy_fails_closed_without_execution(self):
        self.access.path.write_text('{broken')
        with self.access.connection(self.server):
            with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
                self.tasks.execute('owned', b'input')
        self.assertEqual(self.calls, [])

    def test_stale_policy_update_preserves_current_policy(self):
        self.access.configure({}, expected_revision=self.revision)
        before = self.access.path.read_bytes()
        with self.assertRaises(ValueError):
            self.access.configure(self.grants, expected_revision=self.revision)
        self.assertEqual(self.access.path.read_bytes(), before)

    def test_closed_connection_does_not_retain_authority(self):
        with self.access.connection(self.server):
            self.server.close()
            self.assertFalse(self.access.authorize('owned', 'execute'))

    def test_tcp_socket_is_not_a_local_authenticated_peer(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
            with self.assertRaises(ValueError):
                with self.access.connection(tcp):
                    pass


    def test_policy_revocation_blocks_a_queued_launch_gate(self):
        import json
        from yeoul_mcp.isolated_worker import check_launch
        observed = []
        def invoke(command, payload, timeout):
            if command[0].endswith('systemd-run'):
                manifest = json.loads(command[-1])
                self.access.configure({'owned': {'uid': os.getuid(), 'actions': ['inspect']}},
                                      expected_revision=self.revision)
                with self.assertRaisesRegex(ValueError, 'revoked'):
                    check_launch(manifest, manifest['launch_directory'])
                observed.append('gate denied')
                return b'proposal'
            return b'not-found'
        tasks = WorkerTasks(self.root, invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                            authorize=self.access.authorize)
        with self.access.connection(self.server):
            with self.assertRaisesRegex(WorkerTransportError, 'permission_denied'):
                tasks.execute('owned', b'input')
            self.assertEqual(tasks.inspect('owned')['cancellation']['revocation_marker'], 'present')
        self.assertEqual(observed, ['gate denied'])

    def test_restoring_policy_never_rearms_a_revoked_logical_task(self):
        with self.access.connection(self.server):
            self.tasks.execute('owned', b'input')
            revision = self.access.configure({}, expected_revision=self.revision)
            self.access.configure(self.grants, expected_revision=revision)
            with self.assertRaisesRegex(WorkerTransportError, 'cancel_requested'):
                self.tasks.execute('owned', b'input')

    def test_owner_transfer_revokes_existing_unit_but_other_action_change_does_not(self):
        with self.access.connection(self.server):
            self.tasks.execute('owned', b'input')
        revision = self.access.configure({'owned': {'uid': os.getuid(), 'actions': ['execute', 'inspect']}},
                                         expected_revision=self.revision)
        self.assertFalse(self.tasks._cancelled('owned'))
        self.access.configure({'owned': {'uid': os.getuid()+1, 'actions': ['execute', 'inspect']}},
                              expected_revision=revision)
        self.assertTrue(self.tasks._cancelled('owned'))

    def test_policy_write_failure_preserves_revocation_and_retry_history(self):
        from yeoul_mcp import worker_access
        with self.access.connection(self.server):
            self.tasks.execute('owned', b'input')
        before = self.access.path.read_bytes()
        count = len(self.calls)
        original = worker_access.write_json
        def fail_policy(path, value):
            if path == self.access.path:
                raise OSError('synthetic policy commit failure')
            original(path, value)
        with patch.object(worker_access, 'write_json', side_effect=fail_policy), self.assertRaises(OSError):
            self.access.configure({}, expected_revision=self.revision)
        self.assertEqual(self.access.path.read_bytes(), before)
        self.assertTrue(self.tasks._cancelled('owned'))
        with self.access.connection(self.server):
            self.assertEqual(self.tasks.inspect('owned')['cancellation']['revocation_marker'], 'present')
            with self.assertRaisesRegex(WorkerTransportError, 'cancel_requested'):
                self.tasks.execute('owned', b'input')
        self.access.configure({}, expected_revision=self.revision)
        self.assertEqual(len(self.calls), count)

    def test_revocation_marker_failure_does_not_commit_new_policy(self):
        from yeoul_mcp import worker_tasks
        with self.access.connection(self.server):
            self.tasks.execute('owned', b'input')
        before = self.access.path.read_bytes()
        original = worker_tasks.write_json
        def fail_marker(path, value):
            if path.name == 'launch.revoked.json':
                raise OSError('synthetic marker failure')
            original(path, value)
        with patch.object(worker_tasks, 'write_json', side_effect=fail_marker), self.assertRaises(OSError):
            self.access.configure({}, expected_revision=self.revision)
        self.assertEqual(self.access.path.read_bytes(), before)
        with self.access.connection(self.server):
            self.assertEqual(self.tasks.inspect('owned')['cancellation']['revocation_marker'], 'missing')
        self.access.configure({}, expected_revision=self.revision)
        self.assertTrue((self.tasks.journal.directory(self.tasks._load('owned')['unit']) / 'launch.revoked.json').exists())


    def test_recovery_confirmation_uses_real_peer_identity(self):
        from yeoul_mcp.recovery_actions import RecoveryActions
        self.access.configure({'owned': {'uid': os.getuid(), 'actions': ['execute', 'inspect', 'cancel']}},
                              expected_revision=self.revision)
        actions = RecoveryActions(self.tasks, principal=self.access.subject)
        with self.access.connection(self.server):
            self.assertEqual(self.access.subject(), os.getuid())
            self.tasks.execute('owned', b'input')
            preview = actions.prepare_cancel('owned', note='synthetic real peer confirmation')
            self.assertFalse(preview['execution_performed'])
            result = actions.confirm_cancel(preview['token'])
            self.assertEqual(result['state'], 'absence_observed')
        with self.assertRaisesRegex(WorkerTransportError, 'identity_required'):
            actions.confirm_cancel(preview['token'])


if __name__ == '__main__':
    unittest.main()
