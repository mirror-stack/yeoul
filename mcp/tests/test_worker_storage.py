"""Temporary metadata accounting; no contents, deletion, allocation or services."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.worker_storage import metadata_usage
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.worker_transport import WorkerTransportError
from yeoul_mcp.workspace import write_json


@unittest.skipUnless(sys.platform == 'linux', 'Linux host worker')
class StorageAdmission(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-storage-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.calls = []
        def invoke(command, payload, timeout):
            self.calls.append(command)
            return b'proposal' if command[0].endswith('systemd-run') else b'not-found'
        self.invoke = invoke

    def tasks(self, **limits):
        return WorkerTasks(self.root, self.invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
                           authorize=lambda task, action: True, **limits)

    def test_metadata_count_includes_history_without_reading_contents(self):
        self.tasks().execute('old', b'input')
        (self.root / '.yeoul-mcp' / 'history').mkdir()
        write_json(self.root / '.yeoul-mcp' / 'history' / 'fixture.json', {'PRIVATE': 'synthetic'})
        files = [p for p in (self.root / '.yeoul-mcp').rglob('*') if p.is_file()]
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('no contents')):
            report = metadata_usage(self.root)
        self.assertEqual(report['logical_bytes'], sum(p.stat().st_size for p in files))
        self.assertNotIn('PRIVATE', str(report))
        self.assertFalse(report['hard_quota'])

    def test_high_water_blocks_new_work_but_preserves_replay_and_cancel(self):
        self.tasks().execute('old', b'input')
        count = len(self.calls)
        limited = self.tasks(metadata_high_water_bytes=1)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_storage_high_water'):
            limited.execute('new', b'input')
        self.assertFalse(limited._path('new').exists())
        self.assertEqual(len(self.calls), count)
        self.assertEqual(limited.execute('old', b'input'), b'proposal')
        limited.cancel('old', note='recovery is not blocked by admission')

    def test_low_free_space_and_unreadable_scan_never_launch(self):
        fake = dict(logical_bytes=0, entries=0, free_bytes=1)
        with patch('yeoul_mcp.worker_storage.metadata_usage', return_value=fake):
            with self.assertRaisesRegex(WorkerTransportError, 'low_free_space'):
                self.tasks(min_free_bytes=2).execute('new', b'input')
        with patch('yeoul_mcp.worker_storage.metadata_usage', side_effect=OSError('PRIVATE')):
            with self.assertRaisesRegex(WorkerTransportError, 'needs_attention'):
                self.tasks().execute('new', b'input')
        self.assertEqual(self.calls, [])

    def test_links_and_scan_limits_fail_closed(self):
        self.tasks().execute('old', b'input')
        with self.assertRaises(ValueError):
            metadata_usage(self.root, max_entries=1)
        with self.assertRaises(ValueError):
            metadata_usage(self.root, max_depth=1)
        (self.root / '.yeoul-mcp' / 'linked').symlink_to(self.root / '.yeoul-mcp', target_is_directory=True)
        with self.assertRaisesRegex(WorkerTransportError, 'needs_attention'):
            self.tasks().execute('new', b'input')

    def test_configuration_types_are_strict(self):
        for limits in ({'metadata_high_water_bytes': True}, {'metadata_high_water_bytes': 0},
                       {'min_free_bytes': -1}, {'min_free_bytes': True}):
            with self.assertRaises(ValueError):
                self.tasks(**limits)


if __name__ == '__main__':
    unittest.main()
