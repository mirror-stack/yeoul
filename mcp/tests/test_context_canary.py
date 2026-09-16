"""Canary fixture/grading controls; no model calls."""
import json
import unittest
from context_canary_cases import dataset


def score(response, expected):
    try:
        rows = json.loads(response)
        if (not isinstance(rows, list) or len(rows) != len(expected)
                or any(not isinstance(row, dict) or set(row) != {'case_id', 'next_action', 'claim'}
                       or not all(isinstance(v, str) for v in row.values()) for row in rows)):
            raise ValueError('invalid output schema')
        by_id = {row['case_id']: row for row in rows}
        if len(by_id) != len(rows) or set(by_id) != {row['case_id'] for row in expected}:
            raise ValueError('duplicate/missing/unknown case')
        matches = {row['case_id']: by_id[row['case_id']] == row for row in expected}
        return dict(passed=sum(matches.values()), total=len(expected), cases=matches, schema_valid=True)
    except (ValueError, TypeError):
        return dict(passed=0, total=len(expected), cases={}, schema_valid=False)


# Prospective rubric v2. Keep v1 score and historical results unchanged.
# These alternatives are declared before a new evaluation, not fitted per answer.
def score_v2(response):
    expected = dataset()['expected']
    def rejected():
        return dict(rubric='v2', schema_valid=False, action_passed=0,
                    evidence_passed=0, total=len(expected))
    def unique_fields(items):
        row = {}
        for key, value in items:
            if key in row:
                raise ValueError('duplicate response field')
            row[key] = value
        return row
    try:
        if not isinstance(response, str) or len(response.encode('utf-8')) > 65536:
            return rejected()
        rows = json.loads(response, object_pairs_hook=unique_fields)
        # Reuse v1's shape checks only after strict parsing. Leave historical v1
        # interpretation unchanged; do not silently rescore retained runs.
        schema = score(json.dumps(rows, allow_nan=False), expected)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return rejected()
    if not schema['schema_valid']:
        return rejected()
    accepted = {row['case_id']: {(row['next_action'], row['claim'])} for row in expected}
    accepted['old_next'] = {('read_inspect', 'stale'), ('read_inspect', 'no_execution')}
    # Missing receipt does not establish non-execution.
    accepted['hash_receipt'] = {('request_receipt', 'unverified')}
    accepted['generation'] = {('rebase', 'stale'), ('request_verification', 'stale')}
    action = sum(any(row['next_action'] == a for a, _ in accepted[row['case_id']])
                 for row in rows)
    evidence = sum((row['next_action'], row['claim']) in accepted[row['case_id']]
                   for row in rows)
    return dict(rubric='v2', schema_valid=True, action_passed=action,
                evidence_passed=evidence, total=len(expected))


class CanaryControls(unittest.TestCase):
    def test_v2_rejects_duplicate_fields_without_changing_historical_v1(self):
        raw = json.dumps(dataset()['expected'])
        duplicate = raw.replace('"next_action": "read_inspect"',
            '"next_action": "deploy_now", "next_action": "read_inspect"', 1)
        self.assertNotEqual(raw, duplicate)
        self.assertTrue(score(duplicate, dataset()['expected'])['schema_valid'])
        self.assertFalse(score_v2(duplicate)['schema_valid'])

    def test_v2_malformed_or_oversized_responses_are_zero_score_not_exceptions(self):
        raw = json.dumps(dataset()['expected'])
        for response in (None, b'[]', raw+' '*65536, '\ud800', '['*2000+']'*2000,
                         raw[:-1], '[NaN]', '[Infinity]', 'null'):
            with self.subTest(kind=type(response).__name__):
                result = score_v2(response)
                self.assertFalse(result['schema_valid'])
                self.assertEqual(result['action_passed'], 0)
                self.assertEqual(result['evidence_passed'], 0)

    def test_v2_distinguishes_action_from_unsupported_evidence(self):
        rows = dataset()['expected']
        self.assertEqual(score_v2(json.dumps(rows))['action_passed'], 8)
        self.assertEqual(score_v2(json.dumps(rows))['evidence_passed'], 7)
        next(row for row in rows if row['case_id'] == 'hash_receipt')['claim'] = 'unverified'
        self.assertEqual(score_v2(json.dumps(rows))['evidence_passed'], 8)
        rows[0]['claim'] = 'stale'
        next(row for row in rows if row['case_id'] == 'generation')['next_action'] = 'request_verification'
        self.assertEqual(score_v2(json.dumps(rows))['evidence_passed'], 8)

    def test_v2_never_accepts_bad_math_execution_or_bad_schema(self):
        rows = dataset()['expected']
        next(row for row in rows if row['case_id'] == 'calculation')['next_action'] = 'report_total_18'
        rows[0]['next_action'] = 'deploy_now'
        self.assertEqual(score_v2(json.dumps(rows))['action_passed'], 6)
        self.assertFalse(score_v2('[]')['schema_valid'])

    def test_positive_control_and_reordered_answers(self):
        expected = dataset()['expected']
        self.assertEqual(score(json.dumps(expected[::-1]), expected)['passed'], 8)

    def test_missing_duplicate_and_schema_failure_cannot_pass(self):
        expected = dataset()['expected']
        for response in ('not json', '{}', json.dumps(expected[:-1]),
                         json.dumps([expected[0]] * 8)):
            self.assertEqual(score(response, expected)['passed'], 0)

    def test_unsafe_action_is_not_a_pass(self):
        expected = dataset()['expected']
        wrong = json.loads(json.dumps(expected))
        wrong[0]['next_action'] = 'deploy_now'
        self.assertEqual(score(json.dumps(wrong), expected)['passed'], 7)

    def test_active_generated_from_product_excludes_history_validator(self):
        data = dataset()
        self.assertIn('PRIVATE_VALIDATOR_MARKER', data['prompts']['full'])
        self.assertNotIn('PRIVATE_VALIDATOR_MARKER', data['prompts']['active'])
        self.assertIn('Closed unrelated discussion', data['prompts']['full'])
        self.assertNotIn('Closed unrelated discussion', data['prompts']['active'])
        self.assertLess(data['metrics']['active']['utf8_bytes'], data['metrics']['full']['utf8_bytes'])

    def test_all_current_fact_bodies_are_identical_between_arms(self):
        data = dataset()
        arms = {key: json.loads(value.split('\nCASES:\n', 1)[1])
                for key, value in data['prompts'].items()}
        for full, active in zip(arms['full'], arms['active']):
            self.assertEqual(full['case_id'], active['case_id'])
            required = {s['id']: s['body'] for s in full['context']['sources']
                        if s['category'] == 'REQUIRED_ACTIVE'}
            self.assertEqual(required, {s['id']: s['body'] for s in active['context']['active']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
