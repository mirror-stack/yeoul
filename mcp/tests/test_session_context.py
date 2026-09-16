"""Real SQLite/restart tests of the opt-in long-session core; no model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.session_context import SessionContext
from yeoul_mcp.context_shadow import encoded


def change(text, *, kind='task', key='import', status='open', evidence='', reopen=False):
    return dict(kind=kind,key=key,text=text,status=status,start=0,end=len(text),
                quote=text,evidence=evidence,reopen=reopen)


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        # macOS reports temporary paths under /var, which is a system symlink.
        # Resolve this trusted fixture before testing the product's link refusal.
        self.root=Path(self.temp.name).resolve()
        self.path=self.root/'session.sqlite'
        self.s=SessionContext.create(self.path)

    def tearDown(self):
        self.s.close()
        self.temp.cleanup()

    def accept(self,text,origin='user',**kwargs):
        turn=self.s.record(text,origin=origin,expected_revision=self.s.revision)
        self.s.review(turn,[change(text,**kwargs)],expected_revision=self.s.revision,reason='host review')
        return turn

    def model(self,**kwargs):
        return json.loads(self.s.context(**kwargs)['model_input'])

    def test_current_goal_replaces_old_and_preserves_source(self):
        first=self.accept('Build parser',kind='goal',key='main',status='active')
        self.accept('Stop parser; review schemas',kind='goal',key='main',status='active')
        model=self.model(recent_turns=0)
        self.assertEqual([x['text'] for x in model['active']],['Stop parser; review schemas'])
        old=json.loads(self.s.retrieve(first,expected_revision=self.s.revision))
        self.assertEqual(old['text'],'Build parser')

    def test_completion_guards_repetition_and_explicit_reopen(self):
        self.accept('Implement importer')
        self.accept('Importer verified complete',origin='tool',status='done',evidence='validator:27')
        self.assertEqual(self.model(recent_turns=0)['retired'][0]['status'],'done')
        state=self.model(recent_turns=0)
        self.assertEqual(state['state_semantics']['done'],'currently_completed')
        self.assertIn('never unknown',state['instruction'])
        turn=self.s.record('Implement importer again',origin='user',expected_revision=self.s.revision)
        rev=self.s.revision
        with self.assertRaisesRegex(ValueError,'explicit user reopen'):
            self.s.review(turn,[change('Implement importer again')],expected_revision=rev,reason='replay')
        self.assertEqual(self.s.revision,rev)
        self.s.review(turn,[change('Implement importer again',reopen=True)],expected_revision=rev,reason='explicit reopen')
        self.assertEqual(self.model(recent_turns=0)['active'][0]['status'],'open')

    def test_assistant_cannot_self_promote(self):
        turn=self.s.record('Everything is complete',origin='assistant',expected_revision=0)
        with self.assertRaisesRegex(ValueError,'assistant proposals'):
            self.s.review(turn,[change('Everything is complete',status='done',evidence='self')],expected_revision=1,reason='claim')
        self.assertEqual(self.model()['pending'][0]['turn'],turn)

    def test_tool_cannot_rewrite_policy(self):
        turn=self.s.record('Deploy now',origin='tool',expected_revision=0)
        with self.assertRaisesRegex(ValueError,'user-origin'):
            self.s.review(turn,[change('Deploy now',kind='policy',status='active')],expected_revision=1,reason='tool instruction')

    def test_done_requires_tool_and_evidence(self):
        for origin,evidence in [('user','validator:1'),('tool','')]:
            turn=self.s.record('Done',origin=origin,expected_revision=self.s.revision)
            with self.assertRaisesRegex(ValueError,'completion evidence'):
                self.s.review(turn,[change('Done',status='done',evidence=evidence)],expected_revision=self.s.revision,reason='review')

    def test_atomic_batch_source_quote_and_duplicate_rejection(self):
        turn=self.s.record('Create parser',origin='user',expected_revision=0)
        good=change('Create parser')
        invalid=dict(good,key='other',quote='Invented')
        for changes in ([good,invalid],[good,good]):
            with self.assertRaises(ValueError):
                self.s.review(turn,changes,expected_revision=1,reason='batch')
            self.assertEqual(self.s.revision,1)
            self.assertEqual(self.model()['active'],[])

    def test_two_connections_cas_and_pending_inclusion(self):
        with SessionContext(self.path) as second:
            rev=second.revision
            self.s.record('User changed target',origin='user',expected_revision=0)
            with self.assertRaisesRegex(ValueError,'stale'):
                second.record('Old write',origin='user',expected_revision=rev)
            self.assertIn('User changed target',second.context()['model_input'].decode())

    def test_hundreds_of_traces_do_not_expand_required_state(self):
        self.accept('Never deploy',kind='policy',key='deployment',status='active')
        before=len(self.s.context(byte_budget=2048,recent_turns=0)['model_input'])
        for i in range(512):
            self.s.record(f'Trace {i}: '+('diagnostic '*80),origin='trace',expected_revision=self.s.revision)
        after=self.s.context(byte_budget=2048,recent_turns=0)
        self.assertEqual(after['state'],'ready')
        self.assertLess(abs(after['utf8_bytes']-before),10)
        self.assertIn('Never deploy',after['model_input'].decode())

    def test_pending_over_budget_is_held_not_truncated(self):
        self.s.record('User requirement '*300,origin='user',expected_revision=0)
        result=self.s.context(byte_budget=1024)
        self.assertEqual(result['state'],'needs_review')
        self.assertIsNone(result['model_input'])

    def test_revoked_decision_has_tombstone(self):
        self.accept('Use graph DB',kind='decision',key='storage',status='active')
        self.accept('Revoke graph DB plan',kind='decision',key='storage',status='revoked')
        model=self.model(recent_turns=0)
        self.assertEqual(model['active'],[])
        self.assertEqual(model['retired'][0]['key'],'storage')

    def test_bounded_literal_retrieval_and_stale_refusal(self):
        turn=self.s.record('\uc655\uc790\ub294 \uc232\uc73c\ub85c \uac14\ub2e4. '+'archive '*1000,origin='trace',expected_revision=0)
        result=json.loads(self.s.retrieve(turn,start=0,limit=3,expected_revision=1))
        self.assertEqual(result['text'],'\uc655\uc790\ub294')
        with self.assertRaisesRegex(ValueError,'invalid revision'):
            self.s.retrieve(turn,expected_revision=True)
        self.assertLess(len(json.dumps(result)),500)
        self.assertEqual(self.model(query='\uc232',recent_turns=1)['snippets'][0]['turn'],turn)
        self.s.record('next',origin='trace',expected_revision=1)
        with self.assertRaisesRegex(ValueError,'stale'):
            self.s.retrieve(turn,expected_revision=1)

    def test_new_process_restores_same_replacement_context(self):
        self.accept('Keep local',kind='constraint',key='scope',status='active')
        before=self.s.context(recent_turns=0)['sha256']
        script='from yeoul_mcp.session_context import SessionContext; import sys; s=SessionContext(sys.argv[1]); print(s.context(recent_turns=0)["sha256"]); s.close()'
        env=dict(os.environ,PYTHONPATH=str(Path(__import__('yeoul_mcp').__file__).parent.parent))
        run=subprocess.run([sys.executable,'-B','-c',script,str(self.path)],env=env,
                           capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(run.stdout.strip(),before)

    def test_existing_database_not_overwritten_and_log_not_editable(self):
        self.s.record('retain',origin='trace',expected_revision=0)
        with self.assertRaises(FileExistsError): SessionContext.create(self.path)
        with self.assertRaises(Exception): self.s.db.execute('DELETE FROM log')
        self.assertEqual(self.s.revision,1)

    def test_explicit_dismiss_keeps_archive(self):
        turn=self.s.record('Unrelated aside',origin='user',expected_revision=0)
        self.s.review(turn,[],expected_revision=1,reason='host classified as noncontrolling aside')
        self.assertEqual(self.model()['pending'],[])
        self.assertEqual(json.loads(self.s.retrieve(turn,expected_revision=2))['text'],'Unrelated aside')

    def test_search_returns_late_match_with_exact_source_offsets(self):
        text='prefix '*700+'UniqueNeedle'+' suffix'*400
        turn=self.s.record(text,origin='trace',expected_revision=0)
        snippet=self.model(query='UniqueNeedle',recent_turns=1)['snippets'][0]
        self.assertIn('UniqueNeedle',snippet['text'])
        self.assertEqual(snippet['turn'],turn)
        self.assertEqual(text[snippet['start']:snippet['end']],snippet['text'])
        self.assertLessEqual(len(snippet['text']),1000)
        self.assertTrue(snippet['truncated'])

    def test_search_handles_escaped_text_not_json_metadata(self):
        text='prefix: "quoted"\nline after a newline'
        self.s.record(text,origin='trace',expected_revision=0)
        packet=self.s.context(query='"quoted"\nline')
        self.assertEqual(len(json.loads(packet['model_input'])['snippets']),1)
        self.assertEqual(packet['search_stats']['strategy'],'fts5_trigram')
        self.assertEqual(self.model(query='origin')['snippets'],[])

    def test_search_index_finds_old_exact_match_with_one_candidate_budget(self):
        turn=self.s.record('old UniqueNeedle source',origin='trace',expected_revision=0)
        for number in range(100):
            self.s.record('recent irrelevant %d' % number,origin='trace',
                          expected_revision=self.s.revision)
        packet=self.s.context(query='UniqueNeedle',recent_turns=1,search_event_limit=1)
        body=json.loads(packet['model_input'])
        self.assertEqual(body['snippets'][0]['turn'],turn)
        self.assertTrue(body['search']['complete'])
        self.assertEqual(packet['search_stats']['scanned_events'],1)
        self.assertEqual(packet['search_stats']['strategy'],'fts5_trigram')
        self.assertTrue(packet['search_stats']['index_verified'])

    def test_search_index_preserves_case_sensitive_absence(self):
        self.s.record('UniqueNeedle',origin='trace',expected_revision=0)
        packet=self.s.context(query='uniqueneedle',recent_turns=1)
        body=json.loads(packet['model_input'])
        self.assertEqual(body['snippets'],[])
        self.assertTrue(body['search']['complete'])
        self.assertEqual(packet['search_stats']['strategy'],'fts5_trigram')
        self.assertTrue(packet['search_stats']['index_verified'])

    def test_changed_search_projection_falls_back_to_bounded_journal_scan(self):
        self.s.record('old UniqueNeedle source',origin='trace',expected_revision=0)
        self.s.close()
        import sqlite3
        db=sqlite3.connect(self.path)
        db.execute("UPDATE turn_search SET text='old DifferentNeedle source' WHERE rowid=1")
        db.commit();db.close()
        self.s=SessionContext(self.path)
        self.assertFalse(self.s.search_index_status()['available'])
        packet=self.s.context(query='UniqueNeedle',recent_turns=1)
        self.assertEqual(packet['search_stats']['strategy'],'journal_scan')
        self.assertEqual(json.loads(packet['model_input'])['snippets'][0]['turn'],1)
        source=list(self.s.db.execute('SELECT seq,payload,parent,digest FROM log ORDER BY seq'))
        rebuilt=self.s.rebuild_search_index(expected_revision=1)
        self.assertEqual(rebuilt['indexed_turns'],1)
        self.assertEqual(rebuilt['source_events_preserved'],1)
        self.assertEqual(list(self.s.db.execute(
            'SELECT seq,payload,parent,digest FROM log ORDER BY seq')),source)
        packet=self.s.context(query='UniqueNeedle',recent_turns=1)
        self.assertEqual(packet['search_stats']['strategy'],'fts5_trigram')
        self.assertTrue(packet['search_stats']['index_verified'])

    def test_search_index_rebuild_revision_cas_precedes_replacement(self):
        self.s.record('one searchable source',origin='trace',expected_revision=0)
        with SessionContext(self.path) as other:
            other.record('two searchable source',origin='trace',expected_revision=1)
        with self.assertRaisesRegex(ValueError,'stale session revision'):
            self.s.rebuild_search_index(expected_revision=1)
        self.assertEqual(self.s.revision,2)
        self.assertTrue(self.s.search_index_status()['verified'])

    def test_short_query_uses_bounded_journal_scan(self):
        self.s.record('a x',origin='trace',expected_revision=0)
        packet=self.s.context(query='x',recent_turns=1)
        self.assertEqual(packet['search_stats']['strategy'],'journal_scan')

    def test_search_budget_reports_incomplete_not_absent(self):
        self.s.record('old needle',origin='trace',expected_revision=0)
        self.s.record('recent irrelevant',origin='trace',expected_revision=1)
        packet=self.s.context(query='needle',search_event_limit=1,use_search_index=False)
        body=json.loads(packet['model_input'])
        self.assertEqual(body['snippets'],[])
        self.assertFalse(body['search']['complete'])
        self.assertEqual(packet['search_stats']['stop_reason'],'event_limit')
        self.assertEqual(packet['search_stats']['scanned_events'],1)
        packet=self.s.context(query='needle',search_byte_limit=1,use_search_index=False)
        self.assertEqual(packet['search_stats']['stop_reason'],'byte_limit')
        self.assertFalse(json.loads(packet['model_input'])['search']['complete'])

    def test_new_journal_persists_event_limit_and_refuses_before_write(self):
        path=self.root/'limited.sqlite'
        with SessionContext.create(path,max_events=1,max_payload_bytes=4096) as limited:
            limited.record('one',origin='user',expected_revision=0)
            before=limited.journal_usage()
            with self.assertRaisesRegex(ValueError,'event limit'):
                limited.record('two',origin='user',expected_revision=1)
            self.assertEqual(limited.revision,1)
            self.assertEqual(limited.journal_usage(),before)
        with SessionContext(path) as reopened:
            self.assertEqual(reopened.journal_usage(),before)
            with self.assertRaisesRegex(ValueError,'event limit'):
                reopened.record('retry',origin='user',expected_revision=1)

    def test_journal_byte_limit_counts_utf8_payload_and_rolls_back(self):
        path=self.root/'bytes.sqlite'
        with SessionContext.create(path,max_events=100,max_payload_bytes=1024) as limited:
            event=dict(type='turn',text='\uac00'*300,origin='trace')
            limited.record(event['text'],origin='trace',expected_revision=0)
            usage=limited.journal_usage()
            self.assertEqual(usage['payload_bytes'],len(encoded(event)))
            self.assertLessEqual(usage['payload_bytes'],1024)
            with self.assertRaisesRegex(ValueError,'byte limit'):
                limited.record('x'*200,origin='trace',expected_revision=1)
            self.assertEqual(limited.journal_usage(),usage)

    def test_main_database_limit_is_persisted_and_applied(self):
        path=self.root/'database-limit.sqlite'
        maximum=1024*1024
        with SessionContext.create(path,max_events=100,max_payload_bytes=65536,
                                   max_database_bytes=maximum) as limited:
            usage=limited.journal_usage()
            self.assertEqual(usage['max_database_bytes'],maximum)
            self.assertLessEqual(usage['database_bytes'],maximum)
            page_size=limited.db.execute('PRAGMA page_size').fetchone()[0]
            pages=limited.db.execute('PRAGMA max_page_count').fetchone()[0]
            self.assertLessEqual(page_size*pages,maximum)
        with SessionContext(path) as reopened:
            self.assertEqual(reopened.journal_usage(),usage)

    def test_main_database_limit_refuses_atomically_on_python_without_error_constant(self):
        path=self.root/'full-database.sqlite'
        maximum=1024*1024
        with SessionContext.create(path,max_events=10,max_payload_bytes=maximum,
                                   max_database_bytes=maximum) as limited:
            refused=False
            for number in range(10):
                before=limited.journal_usage()
                revision=limited.revision
                try:
                    limited.record(('%05d-' % number)+('abcdefg'*14000),origin='trace',
                                   expected_revision=revision)
                except ValueError as exc:
                    self.assertRegex(str(exc),'database byte limit')
                    self.assertEqual(limited.revision,revision)
                    self.assertEqual(limited.journal_usage(),before)
                    refused=True
                    break
            self.assertTrue(refused,'main-database cap was not reached')

    def test_database_limit_validation_does_not_replace_existing_file(self):
        path=self.root/'invalid-database-limit.sqlite'
        with self.assertRaisesRegex(ValueError,'database limit'):
            SessionContext.create(path,max_payload_bytes=2*1024*1024,
                                  max_database_bytes=1024*1024)
        self.assertFalse(path.exists())

    def test_create_failure_does_not_strand_exclusive_placeholder(self):
        path=self.root/'failed-create.sqlite'
        with patch('yeoul_mcp.session_context.sqlite3.connect',
                   side_effect=__import__('sqlite3').OperationalError('injected open failure')):
            with self.assertRaisesRegex(__import__('sqlite3').OperationalError,
                                        'injected open failure'):
                SessionContext.create(path)
        self.assertFalse(path.exists())
        recovered=SessionContext.create(path)
        recovered.close()

    def test_main_database_cap_refuses_unbounded_wal_mode(self):
        path=self.root/'wal.sqlite'
        limited=SessionContext.create(path);limited.close()
        import sqlite3
        db=sqlite3.connect(path)
        self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(),'wal')
        db.close()
        with self.assertRaisesRegex(ValueError,'delete journal mode'):
            SessionContext(path)

    def test_persisted_free_space_floor_refuses_all_derived_and_source_writes(self):
        self.s.record('one searchable source',origin='trace',expected_revision=0)
        before=self.s.journal_usage()
        self.assertEqual(before['min_free_bytes'],67108864)
        self.assertFalse(before['free_space_reserved'])
        with patch.object(SessionContext,'_free_bytes',return_value=0):
            self.assertEqual(self.s.storage_status()['observed_free_bytes'],0)
            for operation in (
                    lambda:self.s.record('two',origin='trace',expected_revision=1),
                    lambda:self.s.write_checkpoint(expected_revision=1),
                    lambda:self.s.rebuild_search_index(expected_revision=1)):
                with self.assertRaisesRegex(ValueError,'free-space floor'):
                    operation()
        self.assertEqual(self.s.revision,1)
        self.assertEqual(self.s.journal_usage(),before)

    def test_create_checks_free_space_floor_before_creating_file(self):
        path=self.root/'no-space.sqlite'
        with patch.object(SessionContext,'_free_bytes',return_value=0):
            with self.assertRaisesRegex(ValueError,'free-space floor'):
                SessionContext.create(path,min_free_bytes=1)
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(ValueError,'free-space floor'):
            SessionContext.create(path,min_free_bytes=True)

    def test_free_space_observation_uses_portable_disk_usage(self):
        usage=type('Usage',(),dict(total=1000,used=250,free=750))()
        with patch('yeoul_mcp.session_context.shutil.disk_usage',return_value=usage) as observed:
            self.assertEqual(SessionContext._free_bytes(self.path.parent),750)
        observed.assert_called_once_with(self.path.parent)

    def test_checkpoint_fast_reopen_matches_full_and_preserves_source(self):
        self.accept('Keep local',kind='constraint',key='scope',status='active')
        pending=self.s.record('Pending question',origin='user',expected_revision=self.s.revision)
        count=self.s.journal_usage()['event_count']
        made=self.s.write_checkpoint(expected_revision=self.s.revision)
        self.assertEqual(made['source_events_preserved'],count)
        self.assertEqual(self.s.journal_usage()['event_count'],count)
        later=self.s.record('later trace',origin='trace',expected_revision=self.s.revision)
        expected=self.s.context(recent_turns=0)['sha256']
        with SessionContext(self.path,use_checkpoint=True) as fast:
            status=fast.replay_status()
            self.assertEqual(status['mode'],'checkpoint')
            self.assertEqual(status['checkpoint_revision'],count)
            self.assertEqual(status['replayed_events'],1)
            self.assertFalse(status['full_prefix_verified'])
            self.assertEqual(fast.context(recent_turns=0)['sha256'],expected)
            self.assertEqual(json.loads(fast.retrieve(pending,
                expected_revision=later))['text'],'Pending question')
        with SessionContext(self.path) as full:
            self.assertEqual(full.replay_status()['mode'],'full')
            self.assertTrue(full.replay_status()['full_prefix_verified'])
            self.assertEqual(full.context(recent_turns=0)['sha256'],expected)

    def test_invalid_checkpoint_falls_back_to_full_replay(self):
        self.s.record('source remains authoritative',origin='trace',expected_revision=0)
        self.s.write_checkpoint(expected_revision=1)
        self.s.db.execute("UPDATE checkpoint SET payload='{}' WHERE slot=1")
        with SessionContext(self.path,use_checkpoint=True) as reopened:
            status=reopened.replay_status()
            self.assertEqual(status['mode'],'full')
            self.assertEqual(status['checkpoint_ignored'],'invalid')
            self.assertTrue(status['full_prefix_verified'])
            self.assertEqual(json.loads(reopened.retrieve(1,
                expected_revision=1))['text'],'source remains authoritative')

    def test_fast_checkpoint_requires_full_verification_before_replacement(self):
        self.s.record('one',origin='trace',expected_revision=0)
        self.s.write_checkpoint(expected_revision=1)
        with SessionContext(self.path,use_checkpoint=True) as fast:
            with self.assertRaisesRegex(ValueError,'full replay verification'):
                fast.write_checkpoint(expected_revision=1)
            verified=fast.verify_full()
            self.assertTrue(verified['full_prefix_verified'])
            self.assertEqual(fast.write_checkpoint(expected_revision=1)['revision'],1)

    def test_checkpoint_write_uses_current_revision_cas(self):
        self.s.record('one',origin='trace',expected_revision=0)
        with SessionContext(self.path) as other:
            other.record('two',origin='trace',expected_revision=1)
        with self.assertRaisesRegex(ValueError,'stale session revision'):
            self.s.write_checkpoint(expected_revision=1)
        self.assertEqual(self.s.revision,2)
        self.assertFalse(self.s.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone())

    def test_full_verification_detects_prefix_change_skipped_by_fast_checkpoint(self):
        self.s.record('alpha',origin='trace',expected_revision=0)
        self.s.write_checkpoint(expected_revision=1)
        self.s.close()
        import sqlite3
        db=sqlite3.connect(self.path)
        db.execute('DROP TRIGGER no_update')
        payload=db.execute('SELECT payload FROM log WHERE seq=1').fetchone()[0]
        db.execute('UPDATE log SET payload=? WHERE seq=1',(payload.replace('alpha','bravo'),))
        db.commit();db.close()
        self.s=SessionContext(self.path,use_checkpoint=True)
        self.assertEqual(self.s.replay_status()['mode'],'checkpoint')
        with self.assertRaisesRegex(ValueError,'changed journal payload'):
            self.s.verify_full()

    def test_journal_usage_counter_mismatch_refuses_reopen(self):
        path=self.root/'counter.sqlite'
        limited=SessionContext.create(path,max_events=2,max_payload_bytes=2048)
        limited.record('one',origin='trace',expected_revision=0);limited.close()
        import sqlite3
        db=sqlite3.connect(path);db.execute('UPDATE limits SET payload_bytes=0');db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'counter mismatch'):
            SessionContext(path)

    def test_two_connections_share_persisted_quota(self):
        path=self.root/'shared-limit.sqlite'
        first=SessionContext.create(path,max_events=2,max_payload_bytes=4096)
        with first, SessionContext(path) as second:
            first.record('one',origin='trace',expected_revision=0)
            second.record('two',origin='trace',expected_revision=1)
            self.assertEqual(first.journal_usage()['event_count'],2)
            with self.assertRaisesRegex(ValueError,'event limit'):
                first.record('three',origin='trace',expected_revision=2)
            self.assertEqual(second.journal_usage()['event_count'],2)

    def test_legacy_version_one_database_remains_readable_but_reports_unbounded(self):
        path=self.root/'legacy.sqlite'
        import sqlite3
        db=sqlite3.connect(path)
        db.executescript('CREATE TABLE meta(version INTEGER NOT NULL,session TEXT NOT NULL);'
            'CREATE TABLE log(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL,parent TEXT NOT NULL,digest TEXT NOT NULL);'
            "INSERT INTO meta VALUES(1,'legacy');")
        db.commit();db.close()
        with SessionContext(path) as legacy:
            self.assertEqual(legacy.journal_usage(),dict(bounded=False,event_count=0,
                payload_bytes=0,max_events=None,max_payload_bytes=None))
            legacy.record('compatible',origin='trace',expected_revision=0)
            self.assertFalse(legacy.journal_usage()['bounded'])

    def test_first_bounded_schema_remains_readable_without_database_cap(self):
        path=self.root/'old-bounded.sqlite'
        import sqlite3
        db=sqlite3.connect(path)
        db.executescript('CREATE TABLE meta(version INTEGER NOT NULL,session TEXT NOT NULL);'
            'CREATE TABLE log(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL,parent TEXT NOT NULL,digest TEXT NOT NULL);'
            'CREATE TABLE limits(max_events INTEGER NOT NULL,max_payload_bytes INTEGER NOT NULL,'
            'event_count INTEGER NOT NULL,payload_bytes INTEGER NOT NULL);'
            "INSERT INTO meta VALUES(1,'old-bounded');INSERT INTO limits VALUES(4,4096,0,0);")
        db.commit();db.close()
        with SessionContext(path) as old:
            self.assertEqual(old.journal_usage(),dict(bounded=True,event_count=0,
                payload_bytes=0,max_events=4,max_payload_bytes=4096))
            old.record('compatible',origin='trace',expected_revision=0)
            self.assertNotIn('max_database_bytes',old.journal_usage())
            with self.assertRaisesRegex(ValueError,'bounded main database'):
                old.rebuild_search_index(expected_revision=1)


if __name__=='__main__': unittest.main()
