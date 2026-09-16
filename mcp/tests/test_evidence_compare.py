"""Synthetic metadata copies only; comparison never restores runtime authority."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.evidence_compare import compare_evidence
from yeoul_mcp.workspace import write_json


@unittest.skipUnless(sys.platform == 'linux', 'Linux shared evidence locks')
class EvidenceComparison(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-evidence-copies-')
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        self.reference, self.candidate = base/'reference', base/'candidate'
        control = self.reference/'.yeoul-mcp'
        control.mkdir(parents=True)
        (control/'workspace.lock').write_bytes(b'\0')
        write_json(control/'worker-access.json', {'fixture': 'PRIVATE_SYNTHETIC_POLICY'})
        write_json(control/'launch.revoked.json', {'fixture': 'retained revocation'})
        shutil.copytree(self.reference, self.candidate)

    def test_matching_copy_is_read_only_and_never_authorizes_restore(self):
        before = {p: p.read_bytes() for p in self.reference.parent.rglob('*') if p.is_file()}
        report = compare_evidence(self.reference, self.candidate)
        self.assertTrue(report['byte_identical'])
        self.assertFalse(report['restore_authorized'])
        self.assertFalse(report['execute_authorized'])
        self.assertNotIn('PRIVATE_SYNTHETIC_POLICY', str(report))
        self.assertEqual(before, {p: p.read_bytes() for p in self.reference.parent.rglob('*') if p.is_file()})

    def test_missing_revocation_and_changed_policy_are_reported(self):
        control = self.candidate/'.yeoul-mcp'
        (control/'launch.revoked.json').unlink()  # Only this temporary copy fixture.
        write_json(control/'worker-access.json', {'fixture': 'older policy'})
        write_json(control/'unexpected.json', {'fixture': 'extra'})
        report = compare_evidence(self.reference, self.candidate)
        self.assertFalse(report['byte_identical'])
        self.assertEqual(report['missing'], ['launch.revoked.json'])
        self.assertEqual(report['changed'], ['worker-access.json'])
        self.assertEqual(report['extra'], ['unexpected.json'])

    def test_missing_lock_is_not_created_and_links_are_refused(self):
        lock = self.candidate/'.yeoul-mcp/workspace.lock'
        lock.unlink()
        with self.assertRaises(ValueError):
            compare_evidence(self.reference, self.candidate)
        self.assertFalse(lock.exists())
        lock.symlink_to(self.reference/'.yeoul-mcp/workspace.lock')
        with self.assertRaises(ValueError):
            compare_evidence(self.reference, self.candidate)

    def test_mutation_during_read_refuses_a_match(self):
        from yeoul_mcp import evidence_compare
        original = evidence_compare.collect_candidate
        def mutate(root, path, **kwargs):
            raw = original(root, path, **kwargs)
            if root == self.candidate/'.yeoul-mcp' and path == 'worker-access.json':
                write_json(root/path, {'fixture': 'raced'})
            return raw
        with patch.object(evidence_compare, 'collect_candidate', side_effect=mutate), self.assertRaises(ValueError):
            compare_evidence(self.reference, self.candidate)

    def test_same_root_is_not_an_independent_copy(self):
        with self.assertRaises(ValueError):
            compare_evidence(self.reference, self.reference)


if __name__ == '__main__':
    unittest.main()
