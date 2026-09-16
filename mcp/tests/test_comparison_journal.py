"""Temporary synthetic record persistence and uncertain-run refusal."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from comparison_design import design
from comparison_journal import ComparisonJournal
from test_comparison_results import fixtures
from yeoul_mcp import runtime
from yeoul_mcp.workspace import read_json


class ComparisonJournalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-comparison-journal-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.journal = ComparisonJournal(self.root, design())
        self.record = fixtures()[0]
        self.run = self.record['run_id']

    def directory(self):
        return self.root/'.yeoul-mcp/comparison'/self.run

    def test_reserve_finish_and_reopen_never_repeat_or_overwrite(self):
        self.journal.reserve(self.run)
        self.journal.finish(self.record)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        reopened = ComparisonJournal(self.root, design())
        with self.assertRaises(FileExistsError):
            reopened.reserve(self.run)
        with self.assertRaises(FileExistsError):
            reopened.finish(self.record)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(read_json(self.directory()/'result.json'), self.record)

    def test_unfinished_reservation_blocks_new_host(self):
        self.journal.reserve(self.run)
        with self.assertRaises(FileExistsError):
            ComparisonJournal(self.root, design()).reserve(self.run)
        self.assertFalse((self.directory()/'result.json').exists())

    def test_two_real_hosts_only_one_reserves_the_run(self):
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from comparison_design import design
from comparison_journal import ComparisonJournal
try:
    ComparisonJournal(sys.argv[2], design()).reserve(sys.argv[3])
except FileExistsError:
    sys.exit(2)
'''
        commands = [sys.executable, '-B', '-c', code, str(Path(__file__).parent), str(self.root), self.run]
        children = []
        try:
            for _ in range(2):
                children.append(subprocess.Popen(commands, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            outputs = [child.communicate(timeout=10) for child in children]
            self.assertEqual(sorted(child.returncode for child in children), [0, 2], outputs)
            self.assertEqual(read_json(self.directory()/'intent.json')['run']['run_id'], self.run)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_result_without_intent_or_changed_input_refused(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.journal.finish(self.record)
        self.journal.reserve(self.run)
        with self.assertRaises(ValueError):
            self.journal.finish(dict(self.record, delivered_prompt='changed'))
        self.assertFalse((self.directory()/'result.json').exists())

    def test_record_flush_failure_preserves_file_and_denies_overwrite(self):
        self.journal.reserve(self.run)
        from comparison_journal import _once
        path = self.directory()/'result.json'
        with patch('comparison_journal.os.fsync', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                _once(path, self.record)
        self.assertTrue(path.exists())
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.journal.finish(self.record)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            self.journal.reserve(self.run)

    def test_intent_failure_leaves_exclusive_run_tombstone(self):
        # First establish the experiment manifest; do not inject unrelated setup failure.
        with runtime.workspace_lock(self.root) as control:
            self.journal._directory(control)
        with patch('comparison_journal._once', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.journal.reserve(self.run)
        self.assertTrue(self.directory().is_dir())
        with self.assertRaises(FileExistsError):
            self.journal.reserve(self.run)

    def test_changed_design_and_unknown_run_refused(self):
        changed = copy.deepcopy(design())
        changed['primary_runs'] = 1
        with self.assertRaises(ValueError):
            ComparisonJournal(self.root, changed)
        with self.assertRaises(ValueError):
            self.journal.reserve('../escape')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_transport_failure_record_is_preserved_not_repaired(self):
        self.journal.reserve(self.run)
        record = dict(self.record, messages=[], transport_status='interrupted', elapsed_ms=None)
        self.journal.finish(record)
        self.assertEqual(read_json(self.directory()/'result.json'), record)


if __name__ == '__main__':
    unittest.main(verbosity=2)
