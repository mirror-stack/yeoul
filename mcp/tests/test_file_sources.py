"""Current files selected by a protected synthetic host manifest."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.file_sources import FileSources
from yeoul_mcp.context_shadow import extract, encoded, validate
from yeoul_mcp.workspace import write_json
from yeoul_mcp.shadow_workflow import run_shadow


@unittest.skipUnless(sys.platform == 'linux', 'Linux bounded file collector')
class CurrentFiles(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-current-sources-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root/'.yeoul-mcp').mkdir(mode=0o700)
        self.manifest = dict(version=1, target='synthetic', sources=[])
        for role in ('goal', 'status', 'action', 'policy', 'constraints', 'detail', 'audit', 'history'):
            category = {'detail':'RETRIEVABLE_ON_DEMAND', 'audit':'VALIDATOR_ONLY',
                        'history':'NONCONTROLLING_HISTORY'}.get(role, 'REQUIRED_ACTIVE')
            (self.root/(role+'.txt')).write_text('synthetic '+role, encoding='utf-8')
            self.manifest['sources'].append(dict(id=role, role=role, category=category, path=role+'.txt'))
        self.path = self.root/'.yeoul-mcp/source-manifest.json'
        write_json(self.path, self.manifest)
        self.sources = FileSources(self.root)

    def test_current_snapshot_is_read_only_and_retains_roles(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        snapshot = self.sources.load_snapshot()
        packet = extract(snapshot)
        self.assertEqual(len(packet['model']['active']), 5)
        self.assertNotIn(b'synthetic audit', encoded(packet['model']))
        self.assertNotIn(b'synthetic history', encoded(packet['model']))
        self.assertEqual(snapshot, self.sources.load_snapshot())
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_valid_shadow_uses_current_allowlisted_detail(self):
        import hashlib
        session = self.sources.retrieval_session(extract(self.sources.load_snapshot()))
        def worker(raw):
            self.assertNotIn(b'synthetic audit', raw)
            detail = json.loads(session.request('detail'))['body']
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(), proposal={'detail': detail}))
        def provider(snapshot, proposal, binding):
            current = next(s['body'] for s in json.loads(snapshot)['sources'] if s['id'] == 'detail')
            return dict(status='pass' if json.loads(proposal)['detail'] == current else 'fail',
                        evidence_ref='synthetic-current-file')
        result = run_shadow('synthetic-file-query', self.sources.load_snapshot, worker,
                            {'detail-check': ('fixture', provider)})
        self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(result['authority'], 'NONE')
        self.assertEqual(result['execution'], 'NOT_PERFORMED')
        self.assertEqual(session.requests, 1)
        self.assertGreater(session.delivered_bytes, 0)

    def test_retrieval_counts_exact_wire_bytes_and_denied_attempts(self):
        packet = extract(self.sources.load_snapshot())
        session = self.sources.retrieval_session(packet, max_requests=2)
        raw = session.request('detail')
        self.assertEqual(json.loads(raw)['body'], 'synthetic detail')
        self.assertEqual(session.delivered_bytes, len(raw))
        with self.assertRaises(ValueError):
            session.request('audit')
        with self.assertRaisesRegex(ValueError, 'request limit'):
            session.request('detail')
        self.assertEqual(session.requests, 2)
        small = self.sources.retrieval_session(packet, max_bytes=1)
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            small.request('detail')
        self.assertEqual(small.delivered_bytes, 0)

    def test_source_change_invalidates_retrieval_and_shadow_review(self):
        packet = extract(self.sources.load_snapshot())
        (self.root/'policy.txt').write_text('changed synthetic policy')
        with self.assertRaises(ValueError):
            self.sources.retrieval_session(packet).request('detail')
        def worker(raw):
            import hashlib
            (self.root/'policy.txt').write_text('changed again')
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(), proposal={}))
        provider = lambda *args: dict(status='pass', evidence_ref='synthetic')
        result = run_shadow('test', self.sources.load_snapshot, worker, {'check': ('fixture', provider)})
        self.assertEqual(result['state'], 'needs_review')
        self.assertIn('source_unavailable_or_changed', result['reasons'])

    def test_missing_required_role_and_unprotected_manifest_refuse(self):
        self.manifest['sources'] = self.manifest['sources'][1:]
        write_json(self.path, self.manifest)
        with self.assertRaises(ValueError):
            self.sources.load_snapshot()
        self.path.chmod(0o666)  # Temporary fixture only.
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.sources.load_snapshot()

    def test_reclassification_changes_revision_and_does_not_reuse_old_packet(self):
        packet = extract(self.sources.load_snapshot())
        self.manifest['sources'][5]['category'] = 'VALIDATOR_ONLY'
        write_json(self.path, self.manifest)
        with self.assertRaises(ValueError):
            self.sources.retrieval_session(packet).request('detail')

    def test_interleaved_edit_and_link_are_refused(self):
        from yeoul_mcp import file_sources
        original = file_sources.collect_candidate
        changed = False
        def racing(root, path, **kwargs):
            nonlocal changed
            raw = original(root, path, **kwargs)
            if path == 'policy.txt' and not changed:
                changed = True
                (self.root/'goal.txt').write_text('synthetic concurrent edit')
            return raw
        with patch.object(file_sources, 'collect_candidate', side_effect=racing), self.assertRaises(ValueError):
            self.sources.load_snapshot()
        (self.root/'detail.txt').unlink()
        (self.root/'detail.txt').symlink_to(self.root/'policy.txt')
        with self.assertRaises(ValueError):
            self.sources.load_snapshot()


    def test_private_changes_do_not_change_public_packet_but_invalidate_host_binding(self):
        before = extract(self.sources.load_snapshot())
        for name in ('audit', 'history', 'detail'):
            with self.subTest(source=name):
                (self.root/(name+'.txt')).write_text('different nonpublic '+name)
                current = self.sources.load_snapshot()
                after = extract(current)
                self.assertEqual(before['model'], after['model'])
                self.assertNotEqual(before['binding']['source_sha256'], after['binding']['source_sha256'])
                with self.assertRaises(ValueError):
                    validate(before, current)

    def test_private_selection_paths_are_bound_without_public_fingerprint(self):
        before = extract(self.sources.load_snapshot())
        (self.root/'new-audit.txt').write_bytes((self.root/'audit.txt').read_bytes())
        self.manifest['sources'][6]['path'] = 'new-audit.txt'
        write_json(self.path, self.manifest)
        current = self.sources.load_snapshot()
        self.assertEqual(before['model'], extract(current)['model'])
        with self.assertRaises(ValueError):
            validate(before, current)
        packet = extract(current)
        reply = json.loads(self.sources.retrieval_session(packet).request('detail'))
        self.assertEqual(set(reply), {'id', 'body', 'model_sha256'})
        self.assertEqual(reply['model_sha256'], packet['binding']['model_sha256'])
        self.assertNotIn('new-audit.txt', json.dumps(reply))

    def test_host_selection_id_cannot_be_supplied_by_manifest(self):
        self.manifest['sources'][6]['id'] = '__yeoul_host_selection__'
        write_json(self.path, self.manifest)
        with self.assertRaises(ValueError):
            self.sources.load_snapshot()

    def test_provider_binding_changes_for_private_updates_without_worker_input_change(self):
        import hashlib
        inputs, bindings = [], []
        def worker(raw):
            inputs.append(raw)
            return encoded(dict(input_sha256=hashlib.sha256(raw).hexdigest(), proposal={}))
        def provider(snapshot, proposal, binding):
            bindings.append(json.loads(binding))
            return dict(status='pass', evidence_ref='synthetic-private-check')
        for value in ('synthetic-private-one', 'synthetic-private-two'):
            (self.root/'audit.txt').write_text(value)
            result = run_shadow('same-synthetic-task', self.sources.load_snapshot, worker,
                                {'check': ('fixture', provider)})
            self.assertEqual(result['state'], 'ready_for_review')
        self.assertEqual(inputs[0], inputs[1])
        self.assertNotEqual(bindings[0]['revision'], bindings[1]['revision'])


if __name__ == '__main__':
    unittest.main()
