"""Offline controls for the prospective 12-case comparison; no calls or writes."""
from collections import Counter
import json
import unittest

from comparison_design import HEADER, cases, design, retrieval_reply, sha
from yeoul_mcp.context_shadow import encoded


class ComparisonDesign(unittest.TestCase):
    def test_exact_matrix_unique_runs_and_reproducible_digest(self):
        result = design()
        self.assertEqual(result, design())
        self.assertEqual(len(result['cases']), 12)
        self.assertEqual(len({r['run_id'] for r in result['runs']}), 72)
        self.assertEqual(set(Counter((r['case_id'], r['arm']) for r in result['runs']).values()), {3})
        body = dict(result)
        checksum = body.pop('design_sha256')
        self.assertEqual(checksum, sha(encoded(body)))

    def test_arms_share_required_facts_authority_and_no_private_sources(self):
        for row in cases():
            contexts = {arm: json.loads(prompt[len(HEADER):]) for arm, prompt in row['prompts'].items()}
            full = dict(contexts['full'])
            extras = full.pop('additional_sources')
            self.assertEqual(full, contexts['active'])
            self.assertEqual(full['authority'], 'NONE')
            self.assertTrue(all(s['category'] != 'VALIDATOR_ONLY' for s in extras))
            for prompt in row['prompts'].values():
                self.assertNotIn('PRIVATE_COMPARISON_MARKER', prompt)
                self.assertNotIn('"accepted"', prompt)

    def test_prompts_match_recorded_hashes_and_exact_utf8_counts(self):
        inputs = {row['case_id']: row['prompts'] for row in cases()}
        for run in design()['runs']:
            raw = inputs[run['case_id']][run['arm']].encode()
            self.assertEqual(run['prompt_sha256'], sha(raw))
            self.assertEqual(run['prompt_utf8_bytes'], len(raw))

    def test_pairs_alternate_without_changing_cases(self):
        runs = design()['runs']
        first_arms = []
        for index in range(0, 72, 2):
            left, right = runs[index:index+2]
            self.assertEqual((left['case_id'], left['repeat']), (right['case_id'], right['repeat']))
            self.assertEqual({left['arm'], right['arm']}, {'full', 'active'})
            first_arms.append(left['arm'])
        self.assertEqual(Counter(first_arms), {'full': 18, 'active': 18})

    def test_retrieval_uses_same_allowed_body_and_denies_other_sources(self):
        row = next(row for row in cases() if row['case_id'] == 'retrieval')
        detail = json.loads(retrieval_reply('retrieval', 'detail'))
        full = json.loads(row['prompts']['full'][len(HEADER):])
        self.assertEqual(detail['body'], next(s['body'] for s in full['additional_sources'] if s['id'] == 'detail'))
        self.assertNotIn(detail['body'], row['prompts']['active'])
        for case_id, source_id in [('old_next', 'detail'), ('retrieval', 'validator'), ('retrieval', '../detail')]:
            with self.assertRaises(ValueError):
                retrieval_reply(case_id, source_id)
        self.assertEqual(design()['max_model_requests'], 78)

    def test_missing_receipt_never_graded_as_proven_nonexecution(self):
        row = next(row for row in cases() if row['case_id'] == 'hash_receipt')
        self.assertEqual(row['accepted'], [('request_receipt', 'unverified')])


if __name__ == '__main__':
    unittest.main(verbosity=2)
