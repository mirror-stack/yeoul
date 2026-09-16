"""Prepared target contracts, using temporary business state and real child processes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = str(Path(__file__).resolve().parents[1])
if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, SOURCE)
from yeoul_mcp.product import workspace
from yeoul_mcp import server, freshness
from yeoul_mcp.workspace import canonical, write_json
if os.environ.get('PRODUCT_TEST_INSTALLED'):
    SOURCE = str(Path(server.__file__).resolve().parents[1])


class Freshness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul freshness ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'workspace'
        env = {k: v for k, v in os.environ.items() if not k.startswith('YEOUL_')}
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        workspace.setup(self.root, 'discuss')
        self.active = workspace.activated(self.root)
        self.active.__enter__()
        self.addCleanup(self.active.__exit__, None, None, None)

    def prepare(self, name='one'):
        return workspace.prepare(self.root, 'yeoul_new', {'name': name, 'no_arc': True})['task_id']

    def execute(self, task):
        return workspace.execute(self.root, task)

    def test_same_target_only_first_executes(self):
        first, second = self.prepare(), self.prepare()
        self.assertEqual(self.execute(first)['result']['exit_code'], 0)
        self.assertEqual(self.execute(second)['result']['runtime_status'], 'stale_precondition')
        self.assertEqual(workspace.receipt(self.root, second)['state'], 'not_recorded')

    def test_strict_new_direct_write_is_refused_without_receipt(self):
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            result = server.yeoul_new('one', no_arc=True, operation_id='direct')
        self.assertEqual(result['runtime_status'], 'preparation_required')
        self.assertFalse((self.root/'projects/one').exists())
        receipt = self.root/'.yeoul-mcp'/(hashlib.sha256(b'direct').hexdigest()+'.json')
        self.assertFalse(receipt.exists())

    def test_strict_prepared_execution_and_stale_rejection(self):
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            first, second = self.prepare(), self.prepare()
            self.assertEqual(self.execute(first)['result']['exit_code'], 0)
            self.assertEqual(self.execute(second)['result']['runtime_status'], 'stale_precondition')
            self.assertEqual(self.execute(first)['result']['exit_code'], 0)

    def test_strict_transition_preserves_old_completed_direct_replay(self):
        result = server.yeoul_new('one', no_arc=True, operation_id='old-direct')
        self.assertEqual(result['exit_code'], 0)
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            self.assertEqual(server.yeoul_new('one', no_arc=True, operation_id='old-direct'), result)

    def test_strict_profile_transition_preserves_completed_legacy_job(self):
        task = self.prepare()
        path = workspace.job_path(self.root, task)
        job = workspace.load_job(self.root, task)
        job['schema'] = 1
        del job['precondition']
        del job['digest']
        job['digest'] = hashlib.sha256(canonical(job).encode()).hexdigest()
        write_json(path, job)
        first = self.execute(task)
        self.assertEqual(first['result']['exit_code'], 0)
        before = path.read_bytes()
        workspace.configure(self.root, 'discuss', 'prepared_only')
        with workspace.activated(self.root):
            self.assertEqual(self.execute(task), first)
        self.assertEqual(path.read_bytes(), before)

    def test_strict_replay_still_obeys_current_permissions(self):
        first = server.yeoul_new('one', no_arc=True, operation_id='old-direct')
        self.assertEqual(first['exit_code'], 0)
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1', YEOUL_MCP_ALLOW_WRITE='0'):
            denied = server.yeoul_new('one', no_arc=True, operation_id='old-direct')
        self.assertNotEqual(denied['exit_code'], 0)
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            self.assertEqual(server.yeoul_new('one', no_arc=True, operation_id='old-direct'), first)

    def test_strict_without_managed_root_cannot_fall_back_to_raw(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('YEOUL_')}
        env['YEOUL_MCP_REQUIRE_PREPARED'] = '1'
        with patch.dict(os.environ, env, clear=True), patch.object(server, '_run') as run:
            result = server.yeoul_new('one', no_arc=True)
            self.assertNotEqual(result['exit_code'], 0)
            run.assert_not_called()

    def test_strict_legacy_unexecuted_record_is_preserved_but_refused(self):
        task = self.prepare()
        path = workspace.job_path(self.root, task)
        job = workspace.load_job(self.root, task)
        job['schema'] = 1
        del job['precondition']
        del job['digest']
        job['digest'] = hashlib.sha256(canonical(job).encode()).hexdigest()
        write_json(path, job)
        before = path.read_bytes()
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            self.assertEqual(self.execute(task)['result']['runtime_status'], 'preparation_required')
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root/'projects/one').exists())

    def test_strict_profile_is_opt_in_and_survives_mode_configuration(self):
        self.assertNotIn('write_policy', workspace.load(self.root))
        workspace.configure(self.root, 'discuss', 'prepared_only')
        workspace.configure(self.root, 'discuss')
        config = workspace.load(self.root)
        self.assertEqual(config['write_policy'], 'prepared_only')
        self.assertEqual(workspace.environment(config)['YEOUL_MCP_REQUIRE_PREPARED'], '1')
        with workspace.activated(self.root):
            result = server.yeoul_new('one', no_arc=True, operation_id='direct')
            self.assertEqual(result['runtime_status'], 'preparation_required')
            self.assertEqual(self.execute(self.prepare())['result']['exit_code'], 0)

    def test_invalid_strict_setting_fails_closed(self):
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='yes'):
            self.assertNotEqual(server.yeoul_new('one', no_arc=True, operation_id='direct')['exit_code'], 0)
        self.assertFalse((self.root/'projects/one').exists())

    def test_strict_cli_configuration_and_doctor(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'yeoul_mcp.product',
                                 'configure', str(self.root), '--mode', 'discuss',
                                 '--write-policy', 'prepared_only', '--yes'],
                                env=dict(os.environ, PYTHONPATH=SOURCE), cwd=self.root,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(workspace.doctor(self.root)['write_policy'], 'prepared_only')
        self.assertTrue(list((self.root/'.yeoul-mcp/config-history').glob('*.json')))

    def test_strict_does_not_override_existing_write_denial(self):
        task = self.prepare()
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1', YEOUL_MCP_ALLOW_WRITE='0'):
            self.assertNotEqual(self.execute(task)['result']['exit_code'], 0)
        self.assertFalse((self.root/'projects/one').exists())

    def test_strict_pending_still_requires_reconciliation(self):
        task = self.prepare()
        with patch.dict(os.environ, YEOUL_MCP_REQUIRE_PREPARED='1'):
            with patch.object(server, '_run', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    self.execute(task)
            result = server.yeoul_new('two', no_arc=True, operation_id='another')
            self.assertEqual(result['runtime_status'], 'reconciliation_required')
        self.assertFalse((self.root/'projects/two').exists())

    def test_independent_projects_are_not_invalidated(self):
        first, second = self.prepare('one'), self.prepare('two')
        self.assertEqual(self.execute(first)['result']['exit_code'], 0)
        self.assertEqual(self.execute(second)['result']['exit_code'], 0)

    def test_replay_after_business_change_and_direct_replay(self):
        task = self.prepare()
        first = self.execute(task)
        (self.root/'projects/one/README.md').write_text('later business change')
        self.assertEqual(self.execute(task), first)
        self.assertEqual(server.yeoul_new('one', no_arc=True, operation_id=task), first['result'])

    def test_direct_prepared_id_cannot_bypass_freshness_or_arguments(self):
        task = self.prepare()
        (self.root/'projects/one').mkdir(parents=True)
        stale = server.yeoul_new('one', no_arc=True, operation_id=task)
        self.assertEqual(stale['runtime_status'], 'stale_precondition')
        changed = server.yeoul_new('two', no_arc=True, operation_id=task)
        self.assertNotEqual(changed['exit_code'], 0)
        self.assertFalse((self.root/'projects/two').exists())

    def test_policy_file_change_refuses_without_business_write(self):
        task = self.prepare()
        config = self.root/workspace.config_name
        config.write_text(config.read_text() + '\n')
        self.assertEqual(self.execute(task)['result']['runtime_status'], 'stale_precondition')
        self.assertFalse((self.root/'projects/one').exists())

    def test_unprepared_new_id_remains_outside_prepared_freshness(self):
        # Characterize a known compatibility boundary, NOT a security guarantee.
        # A stricter policy must deliberately change this test with approval.
        task = self.prepare()
        config = self.root/workspace.config_name
        config.write_text(config.read_text() + '\n')
        self.assertEqual(self.execute(task)['result']['runtime_status'], 'stale_precondition')
        direct = server.yeoul_new('one', no_arc=True, operation_id='unprepared-low-level')
        self.assertEqual(direct['exit_code'], 0, direct)
        self.assertTrue((self.root/'projects/one').is_dir())
        self.assertFalse((self.root/'.yeoul-mcp/tasks/unprepared-low-level.json').exists())

    def test_two_real_processes_one_target(self):
        tasks = [self.prepare(), self.prepare()]
        code = '''
import json, sys
from yeoul_mcp.product import workspace
print(json.dumps(workspace.execute(sys.argv[1], sys.argv[2])))
'''
        env = dict(os.environ, PYTHONPATH=SOURCE, PYTHONDONTWRITEBYTECODE='1')
        children = []
        try:
            for task in tasks:
                children.append(subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root), task],
                    cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            results = []
            for child in children:
                out, err = child.communicate(timeout=25)
                self.assertEqual(child.returncode, 0, out+err)
                results.append(json.loads(out)['result'])
            self.assertEqual(sum(r['exit_code'] == 0 for r in results), 1)
            self.assertEqual(sum(r.get('runtime_status') == 'stale_precondition' for r in results), 1)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_legacy_prepared_record_is_not_migrated(self):
        task = self.prepare()
        path = workspace.job_path(self.root, task)
        job = workspace.load_job(self.root, task)
        job['schema'] = 1
        del job['precondition']
        del job['digest']
        job['digest'] = hashlib.sha256(canonical(job).encode()).hexdigest()
        write_json(path, job)
        before = path.read_bytes()
        self.assertEqual(self.execute(task)['result']['exit_code'], 0)
        self.assertEqual(path.read_bytes(), before)

    def test_prepare_limit_does_not_save_partial_job(self):
        with patch.object(freshness, 'MAX_BYTES', 1):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertFalse(list((self.root/'.yeoul-mcp/tasks').glob('*.json')))

    def test_directory_enumeration_is_bounded_before_sorting(self):
        project = self.root/'projects/one'
        project.mkdir(parents=True)
        for name in ('a', 'b', 'c'):
            (project/name).write_text('data')
        with patch.object(freshness, 'MAX_ENTRIES', 3):
            with self.assertRaisesRegex(ValueError, 'scan limit'):
                self.prepare()
        self.assertFalse(list((self.root/'.yeoul-mcp/tasks').glob('*.json')))

    def test_growing_read_is_charged_to_byte_budget(self):
        import io
        profile = self.root/workspace.config_name
        real_open = Path.open
        def growing_open(path, *args, **kwargs):
            if path == profile and args == ('rb',):
                return io.BytesIO(b'x' * 4096)
            return real_open(path, *args, **kwargs)
        with patch.object(freshness, 'MAX_BYTES', profile.stat().st_size + 1), patch.object(Path, 'open', growing_open):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                self.prepare()
        self.assertFalse(list((self.root/'.yeoul-mcp/tasks').glob('*.json')))

    def test_arc_changes_refuse_prepared_ticket(self):
        opened = server.arc_open('a', 'arcs', operation_id='open')
        self.assertEqual(opened['exit_code'], 0, opened)
        arc = next((self.root/'arcs').glob('*_a'))
        task = workspace.prepare(self.root, 'arc_ticket', dict(
            arc_dir=str(arc), role='analysis', slug='check', body='Investigate only.'))['task_id']
        (arc/'STATE.md').write_text('changed current state')
        result = self.execute(task)['result']
        self.assertEqual(result['runtime_status'], 'stale_precondition')
        self.assertFalse(list((arc/'tickets/analysis').glob('*.md')))

    def test_interrupted_execution_keeps_pending_and_prevents_reexecution(self):
        task = self.prepare()
        with patch.object(server, '_run', return_value=dict(exit_code=124, stdout='', stderr='timeout')) as run:
            self.assertEqual(self.execute(task)['result']['runtime_status'], 'reconciliation_required')
            self.assertEqual(self.execute(task)['result']['runtime_status'], 'reconciliation_required')
            self.assertEqual(run.call_count, 1)
        self.assertEqual(workspace.receipt(self.root, task)['state'], 'pending')

    def test_close_includes_archive_destination_and_shared_index(self):
        self.assertEqual(server.arc_open('a', 'arcs', operation_id='open')['exit_code'], 0)
        arc = next((self.root/'arcs').glob('*_a'))
        task = workspace.prepare(self.root, 'arc_close', dict(arc_dir=str(arc), verdict='GO review'))['task_id']
        paths = {t['path'] for t in workspace.load_job(self.root, task)['precondition']['targets']}
        self.assertIn(str(arc.parent/'_archive'/arc.name), paths)
        self.assertIn(str(self.root/'KNOWLEDGE_INDEX.md'), paths)
        (self.root/'KNOWLEDGE_INDEX.md').write_text('another arc updated the shared index')
        with patch.object(server, '_run') as run:
            self.assertEqual(self.execute(task)['result']['runtime_status'], 'stale_precondition')
            run.assert_not_called()

    def test_all_mutating_tools_have_target_contracts(self):
        from yeoul_mcp.runtime import Policy, WRITE_TOOLS
        import inspect
        arc = self.root/'arc'
        arc.mkdir()
        ledger = self.root/'ledger.jsonl'
        ledger.write_text('fixture')
        approved = self.root/'.yeoul-approved'
        approved.mkdir()
        baseline = approved/'baseline.json'
        baseline.write_text('fixture')
        cases = {
            'yeoul_new': dict(name='one', no_arc=True),
            'build_handoff': dict(name='one'),
            'arc_open': dict(slug='a', arcs_dir='arcs'),
            'arc_ticket': dict(arc_dir=str(arc), role='analysis', slug='check', body='data'),
            'arc_close': dict(arc_dir=str(arc), verdict='GO'),
            'arc_prereg': dict(arc_dir=str(arc), claim_id='c', ledger=str(ledger)),
            'loop_guard_init': dict(arc_dir=str(arc)),
            'loop_guard_tick': dict(arc_dir=str(arc)),
            'verify_gate': dict(todo_path='TODO.md'),
        }
        self.assertEqual(set(cases), WRITE_TOOLS)
        with patch.dict(os.environ, YEOUL_MCP_ALLOW_EXEC='1', YEOUL_MCP_VERIFY_BASELINE=str(baseline)):
            for tool, arguments in cases.items():
                with self.subTest(tool=tool):
                    bound = inspect.signature(getattr(server, tool)).bind(**arguments)
                    bound.apply_defaults()
                    values = dict(bound.arguments)
                    policy = Policy(values)
                    policy.validate(tool, values)
                    snapshot = freshness.capture(policy, tool, values)
                    self.assertEqual(freshness.check_shape(snapshot), snapshot)
                    self.assertIn(str(self.root/workspace.config_name),
                                  [t['path'] for t in snapshot['targets']])

    def test_captured_prereg_ledger_change_is_stale(self):
        arc = self.root/'arc'
        arc.mkdir()
        ledger = self.root/'claims.jsonl'
        ledger.write_text('fixture before')
        task = workspace.prepare(self.root, 'arc_prereg', dict(
            arc_dir=str(arc), claim_id='c', ledger=str(ledger)))['task_id']
        ledger.write_text('fixture after')
        with patch.object(server, '_run') as run:
            self.assertEqual(self.execute(task)['result']['runtime_status'], 'stale_precondition')
            run.assert_not_called()

    def test_prereg_target_discovery_has_a_read_limit(self):
        from yeoul_mcp.runtime import Policy
        arc = self.root/'arc'
        arc.mkdir()
        (arc/'.prereg').write_bytes(b'claim\nledger.jsonl\n' + b'x' * 65536)
        with self.assertRaisesRegex(ValueError, 'preregistration metadata limit'):
            freshness.targets(Policy({}), 'loop_guard_tick', {'arc_dir': str(arc)})

    def test_prereg_target_discovery_bounds_actual_read(self):
        import io
        from yeoul_mcp.runtime import Policy
        arc = self.root/'arc'
        arc.mkdir()
        metadata = arc/'.prereg'
        metadata.write_text('claim\nledger.jsonl\n')
        real_open = Path.open
        class Growing(io.BytesIO):
            def read(self, size=-1):
                self.requested = size
                return super().read(size)
        stream = Growing(b'x' * 70000)
        def growing_open(path, *args, **kwargs):
            if path == metadata:
                return stream
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', growing_open):
            with self.assertRaisesRegex(ValueError, 'preregistration metadata limit'):
                freshness.targets(Policy({}), 'loop_guard_tick', {'arc_dir': str(arc)})
        self.assertEqual(stream.requested, 65537)

    def test_invalid_precondition_even_rehashed_is_refused(self):
        task = self.prepare()
        path = workspace.job_path(self.root, task)
        job = workspace.load_job(self.root, task)
        job['precondition']['targets'] = []
        del job['digest']
        job['digest'] = hashlib.sha256(canonical(job).encode()).hexdigest()
        write_json(path, job)
        with self.assertRaises(ValueError):
            self.execute(task)


if __name__ == '__main__':
    unittest.main(verbosity=2)
