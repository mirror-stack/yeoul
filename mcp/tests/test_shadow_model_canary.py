import unittest
from shadow_model_canary import design, replay


class ConnectedCanary(unittest.TestCase):
    def test_design_is_fixed_and_expected_answer_not_a_prompt_field(self):
        self.assertEqual(design(), design())
        self.assertNotIn('expected_total', design()['prompt'])

    def test_good_answer_is_review_only(self):
        result = replay('{"total":17}')
        self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(result['execution'], 'NOT_PERFORMED')

    def test_wrong_extra_duplicate_and_malformed_answers_do_not_pass(self):
        for raw in ('{"total":18}', '{"total":17,"execute":true}',
                    '{"total":true}', '{"total":17,"total":18}', 'not json'):
            with self.subTest(raw=raw):
                self.assertEqual(replay(raw)['state'], 'needs_review')


if __name__ == '__main__':
    unittest.main(verbosity=2)
