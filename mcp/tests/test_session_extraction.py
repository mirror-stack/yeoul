"""Synthetic worker/reviewer controls; not natural-language model accuracy."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.context_shadow import encoded
from yeoul_mcp.session_context import SessionContext
from yeoul_mcp.session_extraction import extract_changes, commit_changes

TEXT='Stop the parser; review schemas instead.'

def changes():
    return [dict(kind='goal',key='main',text='Review schemas',status='active',start=0,
        end=len(TEXT),quote=TEXT,evidence='',reopen=False)]


class Extraction(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s=SessionContext.create(Path(self.tmp.name)/'session.db')
        self.turn=self.s.record(TEXT,origin='user',expected_revision=0)
        self.reviewers={'meaning':('synthetic-reviewer',lambda *args:dict(status='pass',evidence_ref='fixture:review'))}

    def tearDown(self):
        self.s.close(); self.tmp.cleanup()

    def worker(self,raw):
        request=json.loads(raw)
        return encoded(dict(input_sha256=request['input_sha256'],changes=changes(),unresolved=[]))

    def proposal(self):
        result=extract_changes(self.s,self.turn,self.worker)
        self.assertEqual(result['state'],'candidate')
        return result['proposal']

    def test_extract_does_not_commit_and_explicit_review_updates_state(self):
        p=self.proposal()
        self.assertEqual(self.s.revision,1)
        out=commit_changes(self.s,p,self.reviewers,lambda *args:True)
        self.assertEqual(out['state'],'state_updated')
        state=json.loads(self.s.context(recent_turns=0)['model_input'])
        self.assertEqual(state['pending'],[])
        self.assertEqual(state['active'][0]['text'],'Review schemas')
        with self.assertRaises(ValueError):
            commit_changes(self.s,p,self.reviewers,lambda *args:True)

    def test_dry_run_preserves_revision_and_pending(self):
        event=self.s.review(self.turn,changes(),expected_revision=1,reason='preview',dry_run=True)
        self.assertEqual(event['type'],'review')
        self.assertEqual(self.s.revision,1)
        self.assertEqual(len(json.loads(self.s.context()['model_input'])['pending']),1)

    def audit_events(self, path):
        with SessionContext(path) as audit:
            return [json.loads(json.loads(row[0])['text']) for row in
                    audit.db.execute('SELECT payload FROM log ORDER BY seq')]

    def test_audited_intent_exists_before_worker_and_preserves_reply(self):
        path = Path(self.tmp.name) / 'attempt.db'
        def worker(wire):
            events = self.audit_events(path)
            self.assertEqual([e['type'] for e in events], ['intent'])
            self.assertEqual(events[0]['wire'].encode(), wire)
            return self.worker(wire)
        result = extract_changes(self.s, self.turn, worker, audit_path=path)
        events = self.audit_events(path)
        self.assertEqual([e['type'] for e in events], ['intent', 'response', 'result'])
        self.assertEqual(events[-1]['result'], result)
        self.assertEqual(json.loads(bytes.fromhex(events[1]['raw_hex']))['changes'], changes())
        self.assertEqual(self.s.revision, 1)
        with self.assertRaises(FileExistsError):
            extract_changes(self.s, self.turn, worker, audit_path=path)

    def test_audited_failures_are_terminal_without_retry(self):
        calls = []
        def worker(wire):
            calls.append(wire)
            raise RuntimeError('private worker diagnostic')
        path = Path(self.tmp.name) / 'failed.db'
        result = extract_changes(self.s, self.turn, worker, audit_path=path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['reason'], 'extractor_failed')
        events = self.audit_events(path)
        self.assertEqual([e['type'] for e in events], ['intent', 'result'])
        self.assertNotIn('private worker diagnostic', json.dumps(events))
        self.assertIsNone(events[-1]['result']['output_bytes'])

    def test_interruption_leaves_intent_and_reuse_is_refused(self):
        path = Path(self.tmp.name) / 'interrupted.db'
        def interrupted(wire):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            extract_changes(self.s, self.turn, interrupted, audit_path=path)
        self.assertEqual([e['type'] for e in self.audit_events(path)], ['intent'])
        with self.assertRaises(FileExistsError):
            extract_changes(self.s, self.turn, self.worker, audit_path=path)
        self.assertEqual(self.s.revision, 1)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX process kill semantics')
    def test_process_kill_after_intent_preserves_pending_and_refuses_replay(self):
        path = Path(self.tmp.name) / 'killed.db'
        package_root = str(Path(sys.modules[SessionContext.__module__].__file__).resolve().parents[1])
        code = '''
import sys,time
sys.path.insert(0,sys.argv[1])
from yeoul_mcp.session_context import SessionContext
from yeoul_mcp.session_extraction import extract_changes
with SessionContext(sys.argv[2]) as session:
    def worker(wire):
        print('INTENT_COMMITTED',flush=True)
        time.sleep(30)
    extract_changes(session,1,worker,audit_path=sys.argv[3])
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, package_root,
                                  str(self.s.path), str(path)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(5), 'worker readiness timeout')
                self.assertEqual(child.stdout.readline(), b'INTENT_COMMITTED\n')
            child.kill()
            child.communicate(timeout=5)
            self.assertEqual(child.returncode, -9)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
            child.stdout.close()
            child.stderr.close()
        self.assertEqual([e['type'] for e in self.audit_events(path)], ['intent'])
        self.assertEqual(self.s.revision, 1)
        self.assertEqual(len(json.loads(self.s.context()['model_input'])['pending']), 1)
        called = []
        with self.assertRaises(FileExistsError):
            extract_changes(self.s, self.turn, lambda wire: called.append(wire), audit_path=path)
        self.assertEqual(called, [])

    def test_audited_malformed_and_oversized_responses(self):
        for index, raw in enumerate((b'\xff', b'x' * 65537, {'not': 'bytes'})):
            with self.subTest(index=index):
                path = Path(self.tmp.name) / f'invalid-{index}.db'
                result = extract_changes(self.s, self.turn, lambda _: raw, audit_path=path)
                self.assertEqual(result['state'], 'needs_review')
                response = self.audit_events(path)[1]
                self.assertEqual(response['raw_omitted'], index != 0)
                if index == 0:
                    self.assertEqual(response['raw_hex'], 'ff')
                elif index == 1:
                    self.assertEqual(response['output_bytes'], 65537)
                    self.assertEqual(len(response['output_sha256']), 64)

    def test_audit_write_failure_blocks_dispatch_or_candidate(self):
        original = SessionContext.record
        for fail_at in (1, 2, 3):
            calls, writes = [], []
            def record(s, text, **kwargs):
                writes.append(text)
                if len(writes) == fail_at:
                    raise OSError('injected storage failure')
                return original(s, text, **kwargs)
            def worker(wire):
                calls.append(wire)
                return self.worker(wire)
            path = Path(self.tmp.name) / f'write-{fail_at}.db'
            with patch.object(SessionContext, 'record', record):
                with self.assertRaises(OSError):
                    extract_changes(self.s, self.turn, worker, audit_path=path)
            self.assertEqual(len(calls), 0 if fail_at == 1 else 1)
            self.assertEqual(len(self.audit_events(path)), fail_at - 1)
        self.assertEqual(self.s.revision, 1)

    def test_uncertainty_never_dismisses_turn(self):
        def worker(raw):
            return encoded(dict(input_sha256=json.loads(raw)['input_sha256'],changes=[],unresolved=['Possible quote, not a new decision']))
        result=extract_changes(self.s,self.turn,worker)
        self.assertEqual(result['reason'],'unresolved_extraction')
        self.assertEqual(self.s.revision,1)

    def test_malformed_wrong_binding_and_unproven_quote_are_held(self):
        for raw in (b'{',b'{"input_sha256":"a","input_sha256":"b"}',b'x'*65537,
                    encoded(dict(input_sha256='wrong',changes=changes(),unresolved=[]))):
            self.assertEqual(extract_changes(self.s,self.turn,lambda _:raw)['state'],'needs_review')
        def worker(raw):
            value=json.loads(self.worker(raw)); value['changes'][0]['quote']='Invented quote'
            return encoded(value)
        self.assertEqual(extract_changes(self.s,self.turn,worker)['state'],'needs_review')
        self.assertEqual(self.s.revision,1)

    def test_state_change_during_extraction_is_held(self):
        def worker(raw):
            self.s.record('New direction',origin='user',expected_revision=1)
            return self.worker(raw)
        self.assertEqual(extract_changes(self.s,self.turn,worker)['reason'],'invalid_or_stale_extraction')
        self.assertEqual(self.s.revision,2)

    def test_unique_exact_quote_alignment_keeps_raw_and_requires_review(self):
        path=Path(self.tmp.name)/'aligned.db'
        raw_replies=[]
        def worker(raw):
            value=json.loads(self.worker(raw))
            value['changes'][0].update(start=1,end=len(TEXT)+1)
            reply=encoded(value);raw_replies.append(reply)
            return reply
        result=extract_changes(self.s,self.turn,worker,audit_path=path)
        self.assertEqual(result['state'],'candidate')
        self.assertEqual(result['proposal']['changes'][0]['start'],0)
        self.assertEqual(result['span_corrections'],[dict(change_index=0,
            original_start=1,original_end=len(TEXT)+1,start=0,end=len(TEXT))])
        self.assertEqual(bytes.fromhex(self.audit_events(path)[1]['raw_hex']),raw_replies[0])
        self.assertEqual(self.s.revision,1)
        out=commit_changes(self.s,result['proposal'],self.reviewers,lambda *args:False)
        self.assertEqual(out['reason'],'approval_denied')
        self.assertEqual(self.s.revision,1)

    def test_ambiguous_quote_and_non_integer_offsets_are_not_repaired(self):
        turn=self.s.record('repeat repeat',origin='user',expected_revision=1)
        for start,end in ((1,7),(True,6),(0,6.0)):
            def worker(raw):
                c=changes()[0];c.update(quote='repeat',start=start,end=end)
                return encoded(dict(input_sha256=json.loads(raw)['input_sha256'],changes=[c],unresolved=[]))
            self.assertEqual(extract_changes(self.s,turn,worker)['state'],'needs_review')
        self.assertEqual(self.s.revision,2)

    def test_span_alignment_never_bypasses_done_origin_or_uncertainty(self):
        def worker(raw):
            c=changes()[0];c.update(kind='task',status='done',evidence='claimed',start=1,end=2)
            return encoded(dict(input_sha256=json.loads(raw)['input_sha256'],changes=[c],unresolved=[]))
        self.assertEqual(extract_changes(self.s,self.turn,worker)['state'],'needs_review')
        def uncertain(raw):
            value=json.loads(self.worker(raw));value['unresolved']=['Need host review']
            return encoded(value)
        # Do not filter or reinterpret model uncertainty in host code, even if
        # the new instructions tell the model to distinguish procedure/meaning.
        self.assertEqual(extract_changes(self.s,self.turn,uncertain)['reason'],'unresolved_extraction')

    def test_alignment_uses_unicode_codepoints_and_does_not_rewrite_text(self):
        source='\uac00\ub098 choose JSON'
        turn=self.s.record(source,origin='user',expected_revision=1)
        def worker(raw):
            c=changes()[0];c.update(quote='choose JSON',start=7,end=18)
            return encoded(dict(input_sha256=json.loads(raw)['input_sha256'],changes=[c],unresolved=[]))
        result=extract_changes(self.s,turn,worker)
        self.assertEqual(result['state'],'candidate')
        c=result['proposal']['changes'][0]
        self.assertEqual((c['start'],c['end']),(3,len(source)))
        self.assertEqual(c['text'],changes()[0]['text'])

    def test_reviewer_denial_and_host_denial_preserve_pending(self):
        p=self.proposal()
        for status in ('fail','unknown','retracted'):
            reviewers={'meaning':('synthetic-reviewer',lambda *args:dict(status=status,evidence_ref='fixture:denial'))}
            self.assertEqual(commit_changes(self.s,p,reviewers,lambda *args:True)['state'],'needs_review')
        self.assertEqual(commit_changes(self.s,p,self.reviewers,lambda *args:False)['reason'],'approval_denied')
        self.assertEqual(self.s.revision,1)

    def test_latest_revision_checked_after_approval_callback(self):
        def approve(*args):
            self.s.record('Conflicting new request',origin='user',expected_revision=1)
            return True
        with self.assertRaisesRegex(ValueError,'stale'):
            commit_changes(self.s,self.proposal(),self.reviewers,approve)
        self.assertEqual(self.s.revision,2)

    def test_provider_cannot_replace_binding_or_choose_requirements(self):
        bad={'meaning':('synthetic-reviewer',lambda *args:dict(status='pass',evidence_ref='fixture',binding={}))}
        self.assertEqual(commit_changes(self.s,self.proposal(),bad,lambda *args:True)['reason'],'reviewer_failed')
        with self.assertRaises(ValueError):
            commit_changes(self.s,self.proposal(),{},lambda *args:True)

    def test_budget_blocks_worker_and_exception_preserves_turn(self):
        called=[]
        with self.assertRaises(ValueError):
            extract_changes(self.s,self.turn,lambda raw:called.append(raw),byte_budget=256)
        self.assertEqual(called,[])
        def broken(raw): raise RuntimeError('private failure')
        result=extract_changes(self.s,self.turn,broken)
        self.assertEqual(result['reason'],'extractor_failed')
        self.assertNotIn('private failure',str(result))
        self.assertEqual(self.s.revision,1)


if __name__=='__main__': unittest.main()
