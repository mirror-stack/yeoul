"""Synthetic context contracts; no runtime, model, authority or consumer dependency."""
import copy
import sys
import unittest
from pathlib import Path

if not __import__('os').environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.context_shadow import extract, validate, retrieve, compare, digest, model_input


def snapshot():
    return dict(target='project/example', revision='r1', sources=[
        dict(id=role, role=role, category='REQUIRED_ACTIVE', body='Current '+role)
        for role in ('goal', 'status', 'action', 'policy', 'constraints')
    ] + [dict(id='spec', role='details', category='RETRIEVABLE_ON_DEMAND', body='Optional details'),
         dict(id='chain', role='integrity', category='VALIDATOR_ONLY', body='PRIVATE_CHAIN_MARKER'),
         dict(id='old-next', role='history', category='NONCONTROLLING_HISTORY',
              body='RETRACTED: publish everything now')])


class ContextShadow(unittest.TestCase):
    def setUp(self):
        self.source = snapshot()
        self.packet = extract(self.source)

    def test_deterministic_and_does_not_mutate_sources(self):
        before = copy.deepcopy(self.source)
        self.assertEqual(extract(self.source), self.packet)
        self.assertEqual(self.source, before)
        self.assertTrue(validate(self.packet, self.source))

    def test_stale_revision_or_next_refused(self):
        for mutate in (lambda s: s.update(revision='r2'),
                       lambda s: s['sources'][2].update(body='New current action')):
            current = copy.deepcopy(self.source)
            mutate(current)
            with self.assertRaises(ValueError):
                validate(self.packet, current)

    def test_missing_required_policy_or_action_refused(self):
        for role in ('policy', 'action'):
            current = copy.deepcopy(self.source)
            current['sources'] = [s for s in current['sources'] if s['role'] != role]
            with self.assertRaises(ValueError):
                extract(current)

    def test_required_policy_cannot_be_hidden(self):
        self.source['sources'][3]['category'] = 'VALIDATOR_ONLY'
        with self.assertRaises(ValueError):
            extract(self.source)

    def test_missing_authority_and_promoted_proposal_refused(self):
        for change in ({'authority': 'OWNER'}, {'output_kind': 'evidence'}, {'mode': 'EXECUTE'}):
            packet = copy.deepcopy(self.packet)
            packet['model'].update(change)
            packet['binding']['model_sha256'] = digest(packet['model'])
            with self.assertRaises(ValueError):
                validate(packet, self.source)
        del self.packet['model']['authority']
        with self.assertRaises(ValueError):
            validate(self.packet, self.source)

    def test_rehashed_model_tampering_is_not_provenance(self):
        self.packet['model']['active'][0]['body'] = 'Invented evidence'
        self.packet['binding']['model_sha256'] = digest(self.packet['model'])
        with self.assertRaises(ValueError):
            validate(self.packet, self.source)

    def test_history_and_validator_bodies_not_model_input(self):
        model = str(self.packet['model'])
        self.assertNotIn('PRIVATE_CHAIN_MARKER', model)
        self.assertNotIn('publish everything', model)
        self.assertNotIn('source_sha256', model)

    def test_history_change_invalidates_old_binding(self):
        self.source['sources'][-1]['body'] = 'Corrected historical record'
        with self.assertRaises(ValueError):
            validate(self.packet, self.source)

    def test_retrieval_allowlist_and_freshness(self):
        self.assertEqual(retrieve(self.packet, self.source, 'spec'), 'Optional details')
        for key in ('chain', 'old-next', 'missing'):
            with self.assertRaises(ValueError):
                retrieve(self.packet, self.source, key)
        self.source['revision'] = 'r2'
        with self.assertRaises(ValueError):
            retrieve(self.packet, self.source, 'spec')

    def test_packet_is_not_independent_source_or_execution_receipt(self):
        self.packet['execution_receipt'] = {'success': True}
        with self.assertRaises(ValueError):
            validate(self.packet, self.source)
        with self.assertRaises(ValueError):
            validate(self.packet, self.packet)

    def test_duplicate_source_and_role_refused(self):
        self.source['sources'].append(dict(self.source['sources'][0]))
        with self.assertRaises(ValueError):
            extract(self.source)
        self.source['sources'][-1]['id'] = 'another-goal'
        with self.assertRaises(ValueError):
            extract(self.source)

    def test_utf8_measurement_not_token_estimate(self):
        self.source['sources'][0]['body'] = '\ud604\uc7ac \ubaa9\ud45c'
        report = compare(self.source)
        from yeoul_mcp.context_shadow import encoded
        self.assertEqual(report['metrics']['model_utf8_bytes'], len(encoded(report['packet']['model'])))
        self.assertNotIn('tokens', report['metrics'])

    def test_frozen_model_input_is_not_changed_by_later_packet_edits(self):
        import hashlib
        payload = model_input(self.packet, self.source)
        self.packet['model']['active'][0]['body'] = 'later edit'
        self.assertNotIn(b'later edit', payload)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         self.packet['binding']['model_sha256'])
        with self.assertRaises(ValueError):
            model_input(self.packet, self.source)

    def test_local_receiver_gets_only_validated_model_bytes(self):
        import hashlib
        import json
        import subprocess
        payload = model_input(self.packet, self.source)
        receiver = '''
import hashlib, json, sys
data = sys.stdin.buffer.read()
parsed = json.loads(data)
assert parsed['authority'] == 'NONE'
assert 'binding' not in parsed
assert b'PRIVATE_CHAIN_MARKER' not in data
assert b'RETRACTED' not in data
print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', receiver], input=payload,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(
            sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))

    def test_stale_input_cannot_be_serialized_for_delivery(self):
        self.source['revision'] = 'r2'
        with self.assertRaises(ValueError):
            model_input(self.packet, self.source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
