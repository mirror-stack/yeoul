import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.candidate_input import collect_candidate


@unittest.skipUnless(sys.platform == 'linux', 'Linux candidate collector')
class CandidateInput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul candidate ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.file = self.root/'proposal.json'
        self.file.write_bytes(b'{"total":17}')

    def test_immutable_exact_bytes_no_source_change(self):
        result = collect_candidate(self.root, 'proposal.json')
        self.assertEqual(result, self.file.read_bytes())
        self.file.write_bytes(b'changed')
        self.assertEqual(result, b'{"total":17}')

    def test_path_escape_and_ambiguous_paths_rejected(self):
        for path in ('../proposal.json', '/etc/passwd', 'a/../proposal.json',
                     './proposal.json', 'a//b', 'a\\b', '', 'a:b', 'a/'*65+'b', 'x'*4097):
            with self.subTest(path=path), self.assertRaises(ValueError):
                collect_candidate(self.root, path)

    def test_symlinks_in_root_parent_or_leaf_refused(self):
        (self.root/'link').symlink_to(self.file)
        (self.root/'alias').symlink_to(self.root, target_is_directory=True)
        for root, path in ((self.root, 'link'), (self.root, 'alias/proposal.json'),
                           (self.root/'alias', 'proposal.json')):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                collect_candidate(root, path)

    def test_hardlink_and_fifo_refused(self):
        os.link(self.file, self.root/'alias')
        with self.assertRaises(ValueError):
            collect_candidate(self.root, 'proposal.json')
        os.mkfifo(self.root/'pipe')
        with self.assertRaises(ValueError):
            collect_candidate(self.root, 'pipe')

    def test_declared_and_actual_size_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            collect_candidate(self.root, 'proposal.json', byte_limit=2)
        def growing(fd, size):
            # All reads here are of the candidate, not directories.
            return b'x' * size
        with patch('yeoul_mcp.candidate_input.os.read', growing):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                collect_candidate(self.root, 'proposal.json', byte_limit=20)

    def test_replacement_during_read_is_refused(self):
        original = os.read
        changed = False
        def replace(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                replacement = self.root/'replacement'
                replacement.write_bytes(b'other')
                replacement.replace(self.file)
                changed = True
            return data
        with patch('yeoul_mcp.candidate_input.os.read', replace):
            with self.assertRaisesRegex(ValueError, 'changed while reading'):
                collect_candidate(self.root, 'proposal.json')

    def test_deadline_and_bad_limit_refused(self):
        with patch('yeoul_mcp.candidate_input.time.monotonic', side_effect=[0, 10]):
            with self.assertRaisesRegex(ValueError, 'deadline'):
                collect_candidate(self.root, 'proposal.json', timeout=1)
        for limit in (0, True, -1):
            with self.assertRaises(ValueError):
                collect_candidate(self.root, 'proposal.json', byte_limit=limit)


if __name__ == '__main__':
    unittest.main(verbosity=2)
