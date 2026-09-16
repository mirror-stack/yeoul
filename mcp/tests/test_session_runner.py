"""Actual synthetic child-process bridge checks; no external models."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.session_context import SessionContext
from yeoul_mcp.session_runner import run_session
from yeoul_mcp.worker_transport import CommandWorker


@unittest.skipUnless(sys.platform == 'linux', 'Linux command transport capability only')
class Runner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = SessionContext.create(self.root / 'state.sqlite')
        self.session.record('old source with needed detail', origin='trace', expected_revision=0)

    def tearDown(self):
        self.session.close()
        self.temp.cleanup()

    def run_worker(self, code, audit_name='audit.sqlite', **kwargs):
        worker = CommandWorker([sys.executable, '-c',
            'import json,sys\np=json.load(sys.stdin)\n' + code], cwd=self.root, timeout=2)
        return run_session(self.session, worker, self.root / audit_name, **kwargs)

    def test_retrieve_then_answer_with_no_state_write(self):
        result = self.run_worker('''
r=p['request']
assert r['delivery']=='REPLACE_CONTEXT' and 'messages' not in r
if not r['retrieved']:
    out=dict(kind='retrieve',turn=1,start=16,limit=6)
else:
    assert r['retrieved'][0]['text']=='needed'
    out=dict(kind='answer',text='Use needed detail')
print(json.dumps(dict(input_sha256=p['input_sha256'],**out)))
''')
        self.assertEqual(result['state'], 'answer_candidate')
        self.assertEqual(result['calls'], 2)
        self.assertEqual(self.session.revision, 1)
        self.assertIsNone(result['model_tokens'])
        with SessionContext(self.root / 'audit.sqlite') as audit:
            events = [json.loads(json.loads(r[0])['text']) for r in
                      audit.db.execute('SELECT payload FROM log ORDER BY seq')]
        self.assertEqual([e['type'] for e in events],
                         ['intent', 'response', 'retrieval', 'intent', 'response', 'result'])

    def test_wrong_binding_held_and_raw_retained(self):
        result = self.run_worker('print(\'{"kind":"answer","text":"x","input_sha256":"bad"}\')')
        self.assertEqual(result['state'], 'needs_review')
        with SessionContext(self.root / 'audit.sqlite') as audit:
            self.assertIn('raw_hex', audit.db.execute('SELECT payload FROM log WHERE seq=2').fetchone()[0])

    def test_terminal_done_is_delivered_as_current_not_unknown(self):
        turn=self.session.record('Importer verified complete',origin='tool',expected_revision=1)
        text='Importer verified complete'
        self.session.review(turn,[dict(kind='task',key='importer',text=text,status='done',
            start=0,end=len(text),quote=text,evidence='fixture:pass',reopen=False)],
            expected_revision=2,reason='fixture completion')
        result=self.run_worker('''
r=p['request']
assert r['context']['retired']==[{'key':'importer','kind':'task','revision':3,'status':'done','turn':2}]
assert r['context']['state_semantics']['done']=='currently_completed'
assert 'retired done is completed, not unknown' in r['instruction']
print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='done')))
''')
        self.assertEqual(result['state'],'answer_candidate')
        self.assertEqual(result['text'],'done')

    def done_session(self):
        turn=self.session.record('Importer verified complete',origin='tool',expected_revision=1)
        text='Importer verified complete'
        self.session.review(turn,[dict(kind='task',key='importer',text=text,status='done',
            start=0,end=len(text),quote=text,evidence='fixture:pass',reopen=False)],
            expected_revision=2,reason='fixture completion')

    def test_answer_reviewer_holds_state_contradiction_without_returning_text(self):
        self.done_session()
        def review(context,answer,binding):
            state=json.loads(context);candidate=json.loads(answer)['text']
            self.assertEqual(state['retired'][0]['status'],'done')
            return dict(status='fail' if candidate=='unknown' else 'pass',evidence_ref='fixture:state')
        result=self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='unknown')))",
            answer_reviewers={'state':('fixture-reviewer',review)})
        self.assertEqual(result['reason'],'answer_review_not_passed')
        self.assertNotIn('text',result)
        self.assertIn('verification_fail',result['review_reasons'])

    def test_answer_reviewer_pass_is_bound_but_not_authorized(self):
        self.done_session()
        seen=[]
        def review(context,answer,binding):
            seen.append((context,answer,binding))
            return dict(status='pass',evidence_ref='fixture:state')
        result=self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='done')))",
            answer_reviewers={'state':('fixture-reviewer',review)})
        self.assertEqual(result['state'],'answer_candidate')
        self.assertEqual(result['authority'],'NONE')
        self.assertEqual(result['answer_binding'],json.loads(seen[0][2]))
        self.assertEqual(result['answer_reports'][0]['provider_id'],'fixture-reviewer')
        with SessionContext(self.root/'audit.sqlite') as audit:
            events=[json.loads(json.loads(row[0])['text']) for row in
                    audit.db.execute('SELECT payload FROM log ORDER BY seq')]
        self.assertEqual([event['type'] for event in events],
            ['intent','response','answer_review_intent','answer_review_response','result'])
        self.assertEqual(events[2]['binding'],result['answer_binding'])
        self.assertEqual(events[3]['report'],result['answer_reports'][0])

    def test_answer_reviewer_failure_and_state_change_hold(self):
        self.done_session()
        def broken(*args): raise RuntimeError('private diagnostic')
        result=self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='done')))",
            answer_reviewers={'state':('fixture-reviewer',broken)})
        self.assertEqual(result['reason'],'answer_reviewer_failed')
        self.assertNotIn('private diagnostic',str(result))
        with SessionContext(self.root/'audit.sqlite') as audit:
            events=[json.loads(json.loads(row[0])['text']) for row in
                    audit.db.execute('SELECT payload FROM log ORDER BY seq')]
        self.assertEqual([event['type'] for event in events],
            ['intent','response','answer_review_intent','answer_review_failed','result'])
        self.assertEqual(events[3]['reason'],'reviewer_failed')
        self.assertNotIn('private diagnostic',json.dumps(events))

    def test_answer_reviewer_state_change_discards_pass(self):
        self.done_session()
        def review(*args):
            self.session.record('new request',origin='user',expected_revision=3)
            return dict(status='pass',evidence_ref='fixture:state')
        result=self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='done')))",
            answer_reviewers={'state':('fixture-reviewer',review)})
        self.assertEqual(result['reason'],'stale_session')
        self.assertNotIn('text',result)

    def test_answer_reviewer_interruption_leaves_unreplayable_intent(self):
        called=[]
        def interrupted(*args):
            called.append('first')
            raise KeyboardInterrupt()
        code="print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='candidate')))"
        with self.assertRaises(KeyboardInterrupt):
            self.run_worker(code,answer_reviewers={'state':('fixture-reviewer',interrupted)})
        self.assertEqual(called,['first'])
        with SessionContext(self.root/'audit.sqlite') as audit:
            events=[json.loads(json.loads(row[0])['text']) for row in
                    audit.db.execute('SELECT payload FROM log ORDER BY seq')]
        self.assertEqual([event['type'] for event in events],
                         ['intent','response','answer_review_intent'])
        with self.assertRaises(FileExistsError):
            self.run_worker(code,answer_reviewers={
                'state':('fixture-reviewer',lambda *args:called.append('replayed'))})
        self.assertEqual(called,['first'])

    def test_answer_review_audit_failure_blocks_callback_or_candidate(self):
        code="print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='candidate')))"
        original=SessionContext.record
        for fail_at,expected_calls,expected_events in (
                (3,0,['intent','response']),
                (4,1,['intent','response','answer_review_intent'])):
            with self.subTest(fail_at=fail_at):
                audit_name=f'audit-fail-{fail_at}.sqlite'
                audit_path=self.root/audit_name
                writes=[]
                callback_calls=[]
                def record(session,text,**kwargs):
                    if session.path == audit_path:
                        writes.append(text)
                        if len(writes) == fail_at:
                            raise OSError('injected audit failure')
                    return original(session,text,**kwargs)
                def review(*args):
                    callback_calls.append(True)
                    return dict(status='pass',evidence_ref='fixture:state')
                with patch.object(SessionContext,'record',record):
                    with self.assertRaisesRegex(OSError,'injected audit failure'):
                        self.run_worker(code,audit_name=audit_name,
                            answer_reviewers={'state':('fixture-reviewer',review)})
                self.assertEqual(len(callback_calls),expected_calls)
                with SessionContext(audit_path) as audit:
                    events=[json.loads(json.loads(row[0])['text']) for row in
                            audit.db.execute('SELECT payload FROM log ORDER BY seq')]
                self.assertEqual([event['type'] for event in events],expected_events)

    def test_search_discovers_range_then_retrieves_without_preknown_turn(self):
        self.session.record('noise ' * 200 + 'ticket-Z31 archived detail',
                            origin='trace', expected_revision=1)
        result = self.run_worker('''
r=p['request']['retrieved']
if not r:
    out=dict(kind='search',query='ticket-Z31')
elif len(r)==1:
    match=r[0]['snippets'][0]
    offset=match['start']+match['text'].index('ticket-Z31')
    assert r[0]['search']['complete'] is True
    out=dict(kind='retrieve',turn=match['turn'],start=offset,limit=len('ticket-Z31'))
else:
    assert r[1]['text']=='ticket-Z31'
    out=dict(kind='answer',text=r[1]['text'])
print(json.dumps(dict(input_sha256=p['input_sha256'],**out)))
''')
        self.assertEqual(result['state'], 'answer_candidate')
        self.assertEqual(result['text'], 'ticket-Z31')
        self.assertEqual(result['calls'], 3)
        self.assertEqual(self.session.revision, 2)
        events = []
        with SessionContext(self.root / 'audit.sqlite') as audit:
            events = [json.loads(json.loads(r[0])['text']) for r in
                      audit.db.execute('SELECT payload FROM log ORDER BY seq')]
        sources = [e['source'] for e in events if e['type'] == 'retrieval']
        from yeoul_mcp.context_shadow import encoded
        self.assertEqual(result['retrieval_bytes'], sum(len(encoded(s)) for s in sources))

    def test_search_limit_is_not_reported_as_exhaustive(self):
        for _ in range(4):
            self.session.record('match in archive', origin='trace',
                                expected_revision=self.session.revision)
        result = self.run_worker('''
r=p['request']['retrieved']
if not r:
    out=dict(kind='search',query='match')
else:
    assert len(r[0]['snippets'])==3
    assert r[0]['search']['complete'] is False
    assert r[0]['search_stats']['stop_reason']=='snippet_limit'
    out=dict(kind='answer',text='Partial search only')
print(json.dumps(dict(input_sha256=p['input_sha256'],**out)))
''')
        self.assertEqual(result['state'], 'answer_candidate')

    def test_repeated_search_stops(self):
        result = self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='search',query='needed')))")
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(result['calls'], 2)

    def test_search_shares_retrieval_budget(self):
        result = self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='search',query='needed')))", retrieval_byte_budget=1)
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['retrieval_bytes'], 0)

    def test_pending_overflow_does_not_dispatch(self):
        self.session.record('x' * 5000, origin='user', expected_revision=1)
        result = self.run_worker('raise AssertionError("must not run")', byte_budget=1024)
        self.assertEqual(result['calls'], 0)
        self.assertEqual(result['reason'], 'mandatory_context_exceeds_budget')

    def test_timeout_holds_without_retry(self):
        worker = CommandWorker([sys.executable, '-c', 'import time; time.sleep(5)'],
                               cwd=self.root, timeout=0.1)
        result = run_session(self.session, worker, self.root / 'audit.sqlite')
        self.assertEqual(result['reason'], 'transport_failed')
        self.assertEqual(result['calls'], 1)

    def test_duplicate_fields_rejected(self):
        result = self.run_worker('print(\'{"kind":"answer","kind":"answer"}\')')
        self.assertEqual(result['state'], 'needs_review')

    def test_lookup_call_budget(self):
        result = self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='retrieve',turn=1,start=0,limit=5)))", max_calls=1)
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['retrieval_bytes'], 0)
        self.assertEqual(result['state'], 'needs_review')

    def test_lookup_byte_budget(self):
        result = self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='retrieve',turn=1,start=0,limit=5)))", retrieval_byte_budget=1)
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(result['calls'], 1)

    def test_repeated_lookup_stops(self):
        result = self.run_worker("print(json.dumps(dict(input_sha256=p['input_sha256'],kind='retrieve',turn=1,start=0,limit=5)))")
        self.assertEqual(result['calls'], 2)
        self.assertEqual(result['state'], 'needs_review')

    def test_changed_state_during_process_discards_answer(self):
        code = f'''
sys.path.insert(0,{str(Path(sys.modules[SessionContext.__module__].__file__).resolve().parents[1])!r})
from yeoul_mcp.session_context import SessionContext
with SessionContext({str(self.session.path)!r}) as s:
    s.record('concurrent user update',origin='user',expected_revision=s.revision)
print(json.dumps(dict(input_sha256=p['input_sha256'],kind='answer',text='stale')))
'''
        result = self.run_worker(code)
        self.assertEqual(result['reason'], 'stale_session')
        self.assertNotIn('text', result)

    def test_failed_process_no_retry_and_existing_audit_not_overwritten(self):
        result = self.run_worker('sys.exit(2)')
        self.assertEqual(result['reason'], 'transport_failed')
        self.assertEqual(result['calls'], 1)
        with self.assertRaises(FileExistsError):
            self.run_worker('sys.exit(0)')


if __name__ == '__main__':
    unittest.main()
