"""Nine real business tools through reviewed execution; synthetic temporary data."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.product import workspace
from yeoul_mcp import runtime, server
from yeoul_mcp.reviewed_execution import execute_reviewed
SOURCE = str(Path(server.__file__).resolve().parents[1])

TOOLS = ('yeoul_new', 'build_handoff', 'arc_open', 'arc_ticket', 'arc_close',
         'arc_prereg', 'loop_guard_init', 'loop_guard_tick', 'verify_gate')


def host(raw):
    value = json.loads(raw)
    return dict(approved=True, reports=[dict(check_id='synthetic', provider_id='fixture',
        binding=value['binding'], status='pass', evidence_ref='fixture:reviewed-tool')])


class ReviewedTools(unittest.TestCase):
    def plain(self, root, tool, **arguments):
        task = workspace.prepare(root, tool, arguments)['task_id']
        result = workspace.execute(root, task)['result']
        self.assertEqual(result['exit_code'], 0, result)

    @contextmanager
    def fixture(self, tool):
        with tempfile.TemporaryDirectory(prefix='yeoul-tools-') as tmp:
            root = Path(tmp) / 'workspace'
            env = {k: v for k, v in os.environ.items() if not k.startswith(('YEOUL_', 'AM_'))}
            with patch.dict(os.environ, env, clear=True):
                workspace.setup(root, 'develop', 'prepared_only')
                todo = root / 'TODO.md'
                todo.write_text('- [x] synthetic check. verify: `printf checked > verified.txt`\n')
                workspace.approve(root, todo)
                with workspace.activated(root):
                    arc = None
                    if tool.startswith('arc_') and tool != 'arc_open' or tool.startswith('loop_'):
                        self.plain(root, 'arc_open', slug='base', arcs_dir='arcs')
                        arc = next((root / 'arcs').glob('*_base'))
                    if tool == 'build_handoff':
                        self.plain(root, 'yeoul_new', name='base', no_arc=True)
                    if tool == 'loop_guard_tick':
                        self.plain(root, 'loop_guard_init', arc_dir=str(arc))
                    ledger = root / 'claims.jsonl'
                    if tool == 'arc_prereg':
                        body = dict(prev_seal='genesis', claim_id='c1', metric='synthetic',
                                    kill_condition='observed errors exceed 3 over 10 trials')
                        body['seal'] = hashlib.sha256(json.dumps(body, sort_keys=True,
                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                        ledger.write_text(json.dumps(body) + '\n')
                        (arc / '0001_spec.md').write_text('\n'.join(
                            '- **' + label + '**: ' + value for label, value in (
                                ('Goal', 'Measure synthetic parser errors across ten fixed input cases'),
                                ('Success condition', 'All ten fixed input cases produce expected parsed fields'),
                                ('Kill-condition', 'Observed errors exceed three across ten independent trials'),
                                ('Constraints', 'Use synthetic records only and preserve source input files'))))
                    args = {
                        'yeoul_new': dict(name='new', no_arc=True),
                        'build_handoff': dict(name='base'),
                        'arc_open': dict(slug='new', arcs_dir='arcs'),
                        'arc_ticket': dict(arc_dir=str(arc), role='analysis', slug='check', body='Synthetic review'),
                        'arc_close': dict(arc_dir=str(arc), verdict='GO synthetic'),
                        'arc_prereg': dict(arc_dir=str(arc), claim_id='c1', ledger=str(ledger)),
                        'loop_guard_init': dict(arc_dir=str(arc)),
                        'loop_guard_tick': dict(arc_dir=str(arc), tokens=5),
                        'verify_gate': dict(todo_path=str(todo)),
                    }[tool]
                    task = workspace.prepare(root, tool, args, review=dict(
                        proposal={'tool_intent': tool}, requirements={'synthetic': 'fixture'}))['task_id']
                    yield root, task, arc

    def business(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
                if p.is_file() and '.yeoul-mcp' not in p.relative_to(root).parts}

    def test_matrix_covers_every_mutating_tool(self):
        self.assertEqual(set(TOOLS), runtime.WRITE_TOOLS)

    def test_real_success_and_completed_replay_for_every_tool(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), self.fixture(tool) as (root, task, arc):
                before = self.business(root)
                result = execute_reviewed(workspace, root, task, host)
                self.assertEqual(result['result']['exit_code'], 0, result)
                self.assertNotEqual(before, self.business(root), tool)
                self.assertEqual(workspace.receipt(root, task)['state'], 'complete')
                if tool == 'arc_close':
                    # Draft success is not archive success or business completion.
                    self.assertTrue(arc.exists())
                    self.assertIn('Close-Pending', (arc / 'ARC' / (arc.name + '.md')).read_text())
                if tool == 'arc_prereg':
                    self.assertTrue((arc / '.prereg').exists())
                if tool == 'verify_gate':
                    self.assertEqual((root / 'verified.txt').read_text(), 'checked')
                after = self.business(root)
                with patch.object(server, '_run', side_effect=AssertionError('must not rerun')):
                    self.assertEqual(workspace.execute(root, task), result)
                self.assertEqual(after, self.business(root))

    def test_denied_review_preserves_every_business_target(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), self.fixture(tool) as (root, task, _):
                before = self.business(root)
                result = execute_reviewed(workspace, root, task,
                    lambda _: dict(approved=False, reports=[]))
                self.assertNotEqual(result['result']['exit_code'], 0)
                self.assertEqual(workspace.receipt(root, task)['state'], 'not_recorded')
                self.assertEqual(before, self.business(root))

    def test_interruption_recovery_preserves_evidence_and_retires_every_tool(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), self.fixture(tool) as (root, task, _):
                with patch.object(server, '_run', return_value=dict(
                        exit_code=124, stdout='', stderr='synthetic timeout')) as run:
                    result = execute_reviewed(workspace, root, task, host)
                    self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')
                    self.assertEqual(workspace.execute(root, task)['result']['runtime_status'], 'reconciliation_required')
                    self.assertEqual(run.call_count, 1)
                self.assertEqual(workspace.receipt(root, task)['state'], 'pending')
                receipt = root / '.yeoul-mcp' / (hashlib.sha256(task.encode()).hexdigest() + '.json')
                before = receipt.read_bytes()
                audits = {p.name: p.read_bytes() for p in (root / '.yeoul-mcp/reviews').glob('*.json')}
                self.assertTrue(workspace.recover(root, acknowledge=True,
                    note='Synthetic interrupted tool inspected; no child launched', children_stopped=True)['changed'])
                self.assertEqual(workspace.receipt(root, task)['state'], 'retired')
                self.assertEqual(receipt.read_bytes(), before)
                self.assertEqual(audits, {p.name: p.read_bytes() for p in (root / '.yeoul-mcp/reviews').glob('*.json')})
                with patch.object(server, '_run', side_effect=AssertionError('retired')):
                    self.assertEqual(workspace.execute(root, task)['result']['runtime_status'], 'reconciliation_required')

    def test_final_archive_with_lost_response_preserves_effect_without_retry(self):
        with self.fixture('arc_close') as (root, draft, arc):
            self.assertEqual(execute_reviewed(workspace, root, draft, host)['result']['exit_code'], 0)
            summary = next(arc.glob('_SUMMARY*'))
            summary.write_text(summary.read_text().replace('(fill in)', 'synthetic concrete conclusion'))
            task = workspace.prepare(root, 'arc_close', dict(arc_dir=str(arc), verdict='GO synthetic'),
                review=dict(proposal={'intent': 'archive synthetic conclusion'},
                            requirements={'synthetic': 'fixture'}))['task_id']
            original = server._run
            def lost_response(*args, **kwargs):
                result = original(*args, **kwargs)
                self.assertEqual(result['exit_code'], 0, result)
                return dict(exit_code=124, stdout='', stderr='synthetic response loss after archive')
            with patch.object(server, '_run', side_effect=lost_response):
                result = execute_reviewed(workspace, root, task, host)
            self.assertEqual(result['result']['runtime_status'], 'reconciliation_required')
            archived = arc.parent / '_archive' / arc.name
            self.assertFalse(arc.exists())
            self.assertTrue(archived.exists())
            self.assertIn('ARCHIVE_RECORD ', (archived / 'STATE.md').read_text())
            self.assertEqual(workspace.receipt(root, task)['state'], 'pending')
            retained = self.business(root)
            with patch.object(server, '_run', side_effect=AssertionError('do not repeat archive')):
                self.assertEqual(workspace.execute(root, task)['result']['runtime_status'], 'reconciliation_required')
            workspace.recover(root, acknowledge=True, children_stopped=True,
                              note='Synthetic archive and index inspected; response lost after completion')
            self.assertEqual(workspace.receipt(root, task)['state'], 'retired')
            self.assertEqual(retained, self.business(root))

    def test_two_processes_review_same_predecessor_only_one_writes(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assert_competing_commits(tool)

    def test_two_processes_final_archive_only_one_moves_and_replay_preserves_files(self):
        self.assert_competing_commits('arc_close', final_archive=True)

    def assert_competing_commits(self, tool, final_archive=False):
        with self.fixture(tool) as (root, first, arc):
            if final_archive:
                self.assertEqual(execute_reviewed(workspace, root, first, host)['result']['exit_code'], 0)
                summary = next(arc.glob('_SUMMARY*'))
                summary.write_text(summary.read_text().replace('(fill in)', 'synthetic concrete conclusion'))
                retained_summary = summary.read_bytes()
                first = workspace.prepare(root, 'arc_close', dict(arc_dir=str(arc), verdict='GO synthetic'),
                    review=dict(proposal={'intent': 'archive synthetic conclusion'},
                                requirements={'synthetic': 'fixture'}))['task_id']
            job = workspace.load_job(root, first)
            second = workspace.prepare(root, job['tool'], job['arguments'], review=job['review'])['task_id']
            code = '''
import json, sys
from yeoul_mcp.product import workspace
from yeoul_mcp.reviewed_execution import execute_reviewed
def host(raw):
    binding = json.loads(raw)['binding']
    return dict(approved=True, reports=[dict(check_id='synthetic', provider_id='fixture',
        binding=binding, status='pass', evidence_ref='fixture:concurrent')])
# Both imported workers must be alive before the parent releases either request.
print('ready', flush=True)
if sys.stdin.readline().strip() != 'go':
    raise RuntimeError('missing parent start signal')
print(json.dumps(execute_reviewed(workspace, sys.argv[1], sys.argv[2], host)))
'''
            children = []
            readers = []
            try:
                for task in (first, second):
                    children.append(subprocess.Popen([sys.executable, '-B', '-c', code, str(root), task],
                        cwd=root, env=dict(os.environ, PYTHONPATH=SOURCE, PYTHONDONTWRITEBYTECODE='1'),
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                # Pipe selectors are not portable to Windows. One bounded handshake
                # reader per owned child leaves stdout exclusively to communicate afterwards.
                ready = queue.Queue()
                def read_ready(child):
                    try:
                        ready.put(child.stdout.readline())
                    except Exception as exc:
                        ready.put(exc)
                readers = [threading.Thread(target=read_ready, args=(child,), daemon=True)
                           for child in children]
                for reader in readers:
                    reader.start()
                deadline = time.monotonic() + 25
                for _ in children:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, 'workers did not become ready')
                    self.assertEqual(ready.get(timeout=remaining), 'ready\n')
                for reader in readers:
                    reader.join(timeout=1)
                    self.assertFalse(reader.is_alive(), 'handshake reader did not exit')
                for child in children:
                    child.stdin.write('go\n')
                    child.stdin.flush()
                results = []
                for child in children:
                    out, err = child.communicate(timeout=25)
                    self.assertEqual(child.returncode, 0, out + err)
                    results.append(json.loads(out)['result'])
                self.assertEqual(sum(r['exit_code'] == 0 for r in results), 1)
                self.assertEqual(sum(r.get('runtime_status') == 'stale_precondition' for r in results), 1)
                self.assertEqual(sorted(workspace.receipt(root, task)['state'] for task in (first, second)),
                                 ['complete', 'not_recorded'])
                if final_archive:
                    archived = arc.parent / '_archive' / arc.name
                    self.assertFalse(arc.exists())
                    self.assertTrue(archived.is_dir())
                    sealed_summary = (archived / summary.name).read_bytes()
                    self.assertTrue(sealed_summary.startswith(
                        retained_summary.replace(b'Arc close draft', b'Arc closed') + b'\n- **Closed**: '))
                    self.assertEqual(sealed_summary.count(b'\n- **Closed**: '), 1)
                    self.assertEqual((archived / 'STATE.md').read_text().count('ARCHIVE_RECORD '), 1)
                    after = self.business(root)
                    with patch.object(server, '_run', side_effect=AssertionError('must not repeat archive')):
                        for task, original in zip((first, second), results):
                            replay = execute_reviewed(workspace, root, task, host)['result']
                            self.assertEqual(replay, original)
                    self.assertEqual(self.business(root), after)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                for reader in readers:
                    reader.join(timeout=2)
                for child in children:
                    child.communicate()


if __name__ == '__main__':
    unittest.main()
