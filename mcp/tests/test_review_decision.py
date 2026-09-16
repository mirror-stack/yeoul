import copy
from pathlib import Path
import sys
import unittest

if not __import__('os').environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.review_decision import decide


class ReviewDecision(unittest.TestCase):
    def setUp(self):
        self.binding = dict(task_id='one', target='report', revision='r1', proposal_sha256='a'*64)
        self.required = {'tests': 'test-runner', 'evidence': 'optional-provider'}
        self.reports = [dict(check_id=k, provider_id=v, binding=copy.deepcopy(self.binding),
                             status='pass', evidence_ref='host-record/'+k)
                        for k, v in self.required.items()]

    def test_all_required_pass_only_routes_to_review(self):
        before = copy.deepcopy(self.reports)
        result = decide(self.binding, self.required, self.reports)
        self.assertEqual(result, dict(state='ready_for_review', reasons=[], authority='NONE',
                                      execution='NOT_PERFORMED'))
        self.assertEqual(self.reports, before)

    def test_non_pass_and_missing_never_ready(self):
        for status in ('fail', 'unknown', 'retracted'):
            self.reports[0]['status'] = status
            self.assertIn('verification_'+status, decide(self.binding, self.required, self.reports)['reasons'])
        self.assertEqual(decide(self.binding, self.required, [])['reasons'], ['missing_check'])

    def test_binding_covers_task_target_revision_and_proposal(self):
        for key in self.binding:
            reports = copy.deepcopy(self.reports)
            reports[0]['binding'][key] = 'b'*64 if key == 'proposal_sha256' else 'other'
            self.assertIn('stale_or_different_proposal', decide(self.binding, self.required, reports)['reasons'])

    def test_worker_cannot_substitute_expected_provider(self):
        self.reports[0]['provider_id'] = 'worker'
        self.assertIn('provider_mismatch', decide(self.binding, self.required, self.reports)['reasons'])

    def test_duplicate_conflict_is_order_independent(self):
        duplicate = copy.deepcopy(self.reports[0])
        duplicate['status'] = 'retracted'
        reports = self.reports + [duplicate]
        result = decide(self.binding, self.required, reports)
        self.assertEqual(result, decide(self.binding, self.required, reports[::-1]))
        self.assertIn('duplicate_check', result['reasons'])

    def test_unexpected_check_is_not_silently_ignored(self):
        self.reports[0]['check_id'] = 'other'
        self.assertIn('unexpected_check', decide(self.binding, self.required, self.reports)['reasons'])

    def test_malformed_or_empty_requirements_cannot_pass(self):
        for required in ({}, [], {'tests': ''}):
            with self.assertRaises(ValueError):
                decide(self.binding, required, self.reports)
        for change in (dict(status=True), dict(evidence_ref=''), dict(authority='OWNER'),
                       dict(binding={}), dict(check_id=[])):
            reports = [dict(self.reports[0], **change), self.reports[1]]
            with self.subTest(change=change), self.assertRaises(ValueError):
                decide(self.binding, self.required, reports)


if __name__ == '__main__':
    unittest.main(verbosity=2)
