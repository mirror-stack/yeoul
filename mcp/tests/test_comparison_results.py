"""Synthetic accounting controls; no authentic model result or billing is claimed."""
import copy
import json
import unittest

from comparison_design import cases, design, retrieval_reply
from comparison_results import summarize


def fixtures():
    sources = {c['case_id']: c for c in cases()}
    records = []
    for run in design()['runs']:
        row = sources[run['case_id']]
        action, claim = row['accepted'][0]
        messages = [dict(role='assistant', content=json.dumps(dict(next_action=action, claim=claim)))]
        requests = [dict(input_tokens=100, output_tokens=10)]
        if run['case_id'] == 'retrieval' and run['arm'] == 'active':
            messages = [dict(role='assistant', content='{"request_source":"detail"}'),
                        dict(role='user', content=retrieval_reply('retrieval', 'detail'))] + messages
            requests.append(dict(input_tokens=120, output_tokens=10))
        records.append(dict(run_id=run['run_id'], delivered_prompt=row['prompts'][run['arm']],
            messages=messages, transport_status='complete', elapsed_ms=100, requests=requests))
    return records


class ComparisonResults(unittest.TestCase):
    def test_missing_safety_observations_are_not_safe_samples(self):
        record = fixtures()[0]
        record['messages'][0]['content'] = '{"next_action":"deploy_now","claim":"no_execution"}'
        result = summarize([record])
        self.assertEqual(result['arms']['full']['unsafe_recommendations'], 1)
        self.assertEqual(result['arms']['full']['safety_unclassified'], 35)
        self.assertEqual(result['arms']['active']['safety_unclassified'], 36)
        record['messages'][0]['content'] = '{"next_action":'
        result = summarize([record])
        self.assertEqual(result['arms']['full']['unsafe_recommendations'], 0)
        self.assertEqual(result['arms']['full']['safety_unclassified'], 36)

    def test_full_synthetic_matrix_counts_followups_but_never_adopts(self):
        result = summarize(fixtures())
        self.assertTrue(result['all_runs_recorded'])
        self.assertTrue(result['success_count_not_lower'])
        self.assertEqual(result['arms']['active']['tokens']['input_tokens']['complete_total'], 3960)
        self.assertEqual(result['arms']['active']['tokens']['output_tokens']['attempted_requests'], 39)
        self.assertEqual(result['adoption'], 'NOT_EVALUATED')
        self.assertEqual(result['cost_savings'], 'UNMEASURED')

    def test_missing_samples_stay_in_denominator_and_no_comparison_pass(self):
        result = summarize(fixtures()[:2])
        self.assertEqual(len(result['missing_run_ids']), 70)
        for arm in result['arms'].values():
            self.assertEqual(arm['task_success_rate'], 1/36)
            self.assertIsNone(arm['tokens']['input_tokens']['complete_total'])
        self.assertIsNone(result['success_count_not_lower'])
        self.assertIsNone(result['latency_within_1_25'])

    def test_unknown_usage_is_not_zero_or_partial_complete_total(self):
        records = fixtures()
        records[0]['requests'][0]['input_tokens'] = None
        arm = 'full'  # First frozen run.
        result = summarize(records)['arms'][arm]['tokens']['input_tokens']
        self.assertEqual(result['observed_sum'], 3500)
        self.assertIsNone(result['complete_total'])
        self.assertEqual(result['measured_requests'], 35)

    def test_interrupted_run_cannot_pass_even_with_correct_buffered_answer(self):
        records = fixtures()
        records[0]['transport_status'] = 'interrupted'
        records[0]['elapsed_ms'] = None
        result = summarize(records)
        self.assertFalse(result['runs'][0]['task_success'])
        self.assertEqual(result['arms']['full']['transport_failed'], 1)
        self.assertIsNone(result['latency_ratio'])

    def test_failed_retrieval_preserves_attempt_usage_and_failure(self):
        record = next(r for r in fixtures() if r['run_id'] == 'r1-retrieval-active')
        record['messages'] = record['messages'][:2]
        record['transport_status'] = 'error'
        result = summarize([record])
        self.assertEqual(result['arms']['active']['task_success'], 0)
        self.assertEqual(result['arms']['active']['tokens']['input_tokens']['observed_sum'], 220)

    def test_duplicate_unknown_and_inconsistent_request_counts_refused(self):
        record = fixtures()[0]
        with self.assertRaises(ValueError):
            summarize([record, record])
        for update in (dict(run_id='unknown'), dict(requests=[]),
                       dict(requests=record['requests']*2), dict(messages=[])):
            with self.assertRaises(ValueError):
                summarize([dict(record, **update)])

    def test_invalid_times_tokens_and_booleans_refused(self):
        record = fixtures()[0]
        for value in (-1, True, float('nan'), float('inf'), 10**400):
            with self.assertRaises(ValueError):
                summarize([dict(record, elapsed_ms=value)])
        for value in (-1, True, 1.5, '100'):
            with self.assertRaises(ValueError):
                summarize([dict(record, requests=[dict(input_tokens=value, output_tokens=1)])])

    def test_inputs_are_preserved_and_empty_collection_is_unmeasured(self):
        records = fixtures()[:2]
        before = copy.deepcopy(records)
        summarize(records)
        self.assertEqual(records, before)
        result = summarize([])
        self.assertIsNone(result['arms']['full']['median_elapsed_ms'])
        self.assertIsNone(result['arms']['active']['tokens']['input_tokens']['observed_sum'])
        self.assertEqual(len(result['missing_run_ids']), 72)


if __name__ == '__main__':
    unittest.main(verbosity=2)
