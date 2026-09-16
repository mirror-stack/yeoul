"""Authorized recovery snapshots; temporary data only, no server or browser I/O."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from html.parser import HTMLParser

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.worker_tasks import WorkerTasks
from yeoul_mcp.recovery_view import recovery_view
from yeoul_mcp.workspace import write_json


@unittest.skipUnless(sys.platform == 'linux', 'Linux host tasks')
class RecoveryView(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-recovery-view-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.calls = []
        self.allowed = {'shown'}
        def invoke(command, payload, timeout):
            self.calls.append(command)
            return b'PRIVATE_RESULT' if command[0].endswith('systemd-run') else b'not-found'
        self.tasks = WorkerTasks(self.root, invoke, argv=['/usr/bin/true'], uid=1000, gid=1000,
            authorize=lambda task, action: task in self.allowed)
        self.tasks.execute('shown', b'PRIVATE_INPUT')

    def test_read_only_authorized_page_has_no_active_controls_or_private_data(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        count = len(self.calls)
        page = recovery_view(self.tasks, ['shown', 'secret-task'], language='ko')
        self.assertIn('작업자 결과 보존됨', page)
        for secret in ('secret-task', 'PRIVATE_RESULT', 'PRIVATE_INPUT', str(self.root)):
            self.assertNotIn(secret, page)
        class Tags(HTMLParser):
            def handle_starttag(inner, tag, attrs):
                self.assertNotIn(tag, ('script', 'iframe', 'form', 'button', 'a', 'img'))
        Tags().feed(page)
        self.assertIn('default-src', page)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_observed_absence_does_not_render_completed_cancellation(self):
        self.tasks.cancel('shown', note='PRIVATE_NOTE')
        page = recovery_view(self.tasks, ['shown'])
        self.assertIn('Service absence was observed', page)
        self.assertIn('not cancellation completion', page)
        self.assertNotIn('PRIVATE_NOTE', page)

    def test_corrupt_record_becomes_safe_attention_row(self):
        write_json(self.tasks._path('shown'), {'PRIVATE_FIELD': 'PRIVATE_VALUE'})
        page = recovery_view(self.tasks, ['shown'])
        self.assertIn('Records need review', page)
        self.assertNotIn('PRIVATE_VALUE', page)

    def test_revoked_during_collection_is_not_rendered(self):
        original = self.tasks.inspect
        def revoke(task):
            report = original(task)
            self.allowed.clear()
            return report
        with patch.object(self.tasks, 'inspect', side_effect=revoke):
            page = recovery_view(self.tasks, ['shown'])
        self.assertIn('No authorized tasks', page)
        self.assertNotIn('shown', page)

    def test_bounded_input_and_languages(self):
        for ids, language in ((['shown'] * 101, 'en'), (['<script>'], 'en'), ([], 'invalid')):
            with self.assertRaises(ValueError):
                recovery_view(self.tasks, ids, language=language)
        page = recovery_view(self.tasks, ['shown', 'shown'])
        self.assertEqual(page.count('<th scope="row">shown</th>'), 1)


if __name__ == '__main__':
    unittest.main()
