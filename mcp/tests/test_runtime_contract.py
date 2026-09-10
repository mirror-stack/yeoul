"""Managed stdio boundary, durable retry receipts, and real process contention.

Run directly with Python 3.10+; no installs or production workspace writes.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp'))
from yeoul_mcp import runtime, server

WORKER = '''
import json, os, sys, time
from pathlib import Path
from yeoul_mcp import runtime
runtime.LOCK_TIMEOUT = float(os.environ.get('TEST_LOCK_TIMEOUT', '5'))
@runtime.boundary(mutating=True)
def loop_guard_tick(value=1, operation_id=None):
    root = Path(os.environ['YEOUL_MCP_ROOT'])
    marker = json.loads((root/'.yeoul-mcp/active.json').read_text())
    assert json.loads((root/'.yeoul-mcp'/marker['receipt']).read_text())['state'] == 'pending'
    if os.environ.get('TEST_CRASH') == 'before':
        os._exit(77)
    count = root/'count'
    n = int(count.read_text()) if count.exists() else 0
    time.sleep(0.1)
    count.write_text(str(n+value))
    if os.environ.get('TEST_CRASH') == 'after':
        os._exit(77)
    return dict(exit_code=0, stdout=str(n+value), stderr='')
print(json.dumps(loop_guard_tick(operation_id=sys.argv[1])))
'''


class RuntimeContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yeoul runtime ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('YEOUL_')}
        self.env.update(YEOUL_MCP_ROOT=str(self.root), YEOUL_MCP_ALLOW_WRITE='1',
                        PYTHONPATH=str(ROOT / 'mcp'), PYTHONDONTWRITEBYTECODE='1')
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def spawn(self, operation, extra=None, code=WORKER):
        return subprocess.Popen([sys.executable, '-c', code, operation],
                                cwd=self.root, env=dict(self.env, **(extra or {})),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def result(self, child, expected=0):
        out, err = child.communicate(timeout=30)
        self.assertEqual(child.returncode, expected, out + err)
        return json.loads(out) if expected == 0 else None

    def assert_denied(self, result):
        self.assertNotEqual(result['exit_code'], 0, result)

    def test_explicit_root_and_denied_write(self):
        for raw in ('', '.', str(self.root / 'missing'), self.root.anchor):
            with self.subTest(root=raw), patch.dict(os.environ, {'YEOUL_MCP_ROOT': raw}):
                self.assert_denied(server.status())
        with patch.dict(os.environ, {'YEOUL_MCP_ALLOW_WRITE': '0'}):
            self.assert_denied(server.yeoul_new('p', no_arc=True, operation_id='new'))
        self.assert_denied(server.yeoul_new('p', no_arc=True))
        self.assertFalse((self.root / 'projects').exists())

    def test_paths_names_roles_and_implicit_environment(self):
        for name in ('../escape', '/escape', 'x/y', 'x\\y', '--option', '$(touch bad)', 'a\nb'):
            with self.subTest(name=name):
                self.assert_denied(server.yeoul_new(name, no_arc=True, operation_id='invalid'))
        for roles in ('analysis ../bad', 'analysis *', 'analysis;touch', 'analysis\nimpl'):
            self.assert_denied(server.arc_open('x', 'arcs', roles=roles, operation_id='invalid'))
        for workspace in ('..', str(self.root.parent), '.yeoul-mcp'):
            self.assert_denied(server.status(workspace=workspace))
        for variable in ('YEOUL_PROJECTS', 'YEOUL_INDEX', 'YEOUL_LEDGER', 'YEOUL_CLOSED_REGISTRY'):
            with self.subTest(variable=variable), patch.dict(os.environ, {variable: str(self.root.parent / 'outside')}):
                self.assert_denied(server.status())
        self.assert_denied(server.arc_close(str(self.root), 'GO', operation_id='outside-archive'))
        self.assertFalse((self.root / 'projects').exists())

    def test_symlink_hardlink_and_implicit_linked_ledger(self):
        arc = self.root / 'arc'
        arc.mkdir()
        (arc / '.prereg').write_text('claim\n' + str(self.root.parent / 'outside.jsonl') + '\nseal\n')
        self.assert_denied(server.arc_close('arc', 'GO', operation_id='bad-link'))
        self.assertFalse((arc / '.close.lock').exists())
        (arc / '.prereg').unlink()
        target = self.root / 'target'
        target.write_text('untouched')
        alias = self.root / 'alias'
        try:
            alias.symlink_to(target)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        self.assert_denied(server.status())
        alias.unlink()
        os.link(target, alias)
        self.assert_denied(server.status())
        self.assertEqual(target.read_text(), 'untouched')

    def test_read_only_creates_only_lock_metadata(self):
        self.assertEqual(server.status()['exit_code'], 0)
        self.assertEqual(server.arc_list()['exit_code'], 0)
        self.assertEqual({p.relative_to(self.root).as_posix() for p in self.root.rglob('*')},
                         {'.yeoul-mcp', '.yeoul-mcp/workspace.lock'})
        with patch.object(server, '_run', side_effect=AssertionError('must not execute')):
            self.assert_denied(server.verify_gate('TODO.md', revert=False, operation_id='verify'))

    def test_replay_conflict_and_guard_reset(self):
        (self.root / 'arc').mkdir()
        first = server.loop_guard_init('arc', operation_id='init')
        self.assertEqual(first['exit_code'], 0, first)
        self.assertEqual(server.loop_guard_tick('arc', tokens=5, operation_id='tick')['exit_code'], 0)
        before = (self.root / 'arc/loop_state.tsv').read_bytes()
        self.assertEqual(server.loop_guard_init('arc', operation_id='init'), first)
        self.assertEqual((self.root / 'arc/loop_state.tsv').read_bytes(), before)
        self.assertEqual(server.loop_guard_tick('arc', tokens=6, operation_id='tick')['runtime_status'],
                         'operation_conflict')
        self.assert_denied(server.loop_guard_init('arc', operation_id='different-init'))
        self.assertEqual((self.root / 'arc/loop_state.tsv').read_bytes(), before)

    def test_concurrent_processes_serialize_and_replay_after_restart(self):
        children = [self.spawn(op) for op in ('same', 'same', 'second', 'third')]
        results = [self.result(child) for child in children]
        self.assertTrue(all(r['exit_code'] == 0 for r in results), results)
        self.assertEqual(results[0], results[1])
        self.assertEqual((self.root / 'count').read_text(), '3')
        self.assertEqual(self.result(self.spawn('same')), results[0])
        self.assertEqual((self.root / 'count').read_text(), '3')

    def test_pending_before_effect_is_not_retried(self):
        self.result(self.spawn('crash', {'TEST_CRASH': 'before'}), expected=77)
        result = self.result(self.spawn('crash'))
        self.assertEqual(result['runtime_status'], 'reconciliation_required')
        self.assertFalse((self.root / 'count').exists())

    def test_crash_after_effect_blocks_other_ids_and_reads(self):
        self.result(self.spawn('crash', {'TEST_CRASH': 'after'}), expected=77)
        for op in ('crash', 'fresh-id'):
            self.assertEqual(self.result(self.spawn(op))['runtime_status'], 'reconciliation_required')
        self.assertEqual(server.status()['runtime_status'], 'reconciliation_required')
        self.assertEqual((self.root / 'count').read_text(), '1')

    def test_lock_wait_is_bounded_and_never_deletes_lock(self):
        with runtime.workspace_lock(self.root):
            lock = self.root / '.yeoul-mcp/workspace.lock'
            inode = lock.stat().st_ino
            start = time.monotonic()
            result = self.result(self.spawn('busy', {'TEST_LOCK_TIMEOUT': '0.15'}))
            self.assertIn('lock wait expired', result['stderr'])
            self.assertLess(time.monotonic() - start, 10)
            self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(self.result(self.spawn('busy'))['exit_code'], 0)

    def test_timeout_leaves_pending_and_preserves_receipt(self):
        helpers = self.root / 'helpers'
        helpers.mkdir()
        (helpers / 'loop-guard').write_text('sleep 2\n', encoding='utf-8')
        (self.root / 'arc').mkdir()
        with patch.object(server, 'BIN', helpers), patch.object(server, 'RUN_TIMEOUT', 0.1):
            result = server.loop_guard_tick('arc', operation_id='timeout')
        self.assertEqual(result['runtime_status'], 'reconciliation_required', result)
        again = server.loop_guard_tick('arc', operation_id='timeout')
        self.assertEqual(again['runtime_status'], 'reconciliation_required')
        receipt = self.root / '.yeoul-mcp' / (hashlib.sha256(b'timeout').hexdigest() + '.json')
        self.assertEqual(json.loads(receipt.read_text())['state'], 'pending')

    def test_corrupt_receipt_and_receipt_write_failure_fail_closed(self):
        self.assertEqual(self.result(self.spawn('ok'))['exit_code'], 0)
        receipt = self.root / '.yeoul-mcp' / (hashlib.sha256(b'ok').hexdigest() + '.json')
        receipt.write_text('{broken')
        self.assert_denied(self.result(self.spawn('ok')))
        self.assert_denied(self.result(self.spawn('another')))
        self.assertEqual((self.root / 'count').read_text(), '1')

    def test_receipt_failure_prevents_child_launch(self):
        with patch.object(runtime, 'write_json', side_effect=OSError('disk full')):
            with patch.object(server, '_run', side_effect=AssertionError('side effect before receipt')):
                self.assert_denied(server.yeoul_new('p', no_arc=True, operation_id='fail'))
        self.assertFalse((self.root / 'projects').exists())

    def test_active_marker_before_receipt_failure_blocks_new_ids(self):
        real_write = runtime.write_json

        def fail_receipt(path, data):
            if path.name != 'active.json':
                raise OSError('interrupted between active pointer and receipt')
            real_write(path, data)

        with patch.object(runtime, 'write_json', side_effect=fail_receipt):
            with patch.object(server, '_run', side_effect=AssertionError('must not launch')):
                result = server.yeoul_new('p', no_arc=True, operation_id='incomplete')
        self.assertEqual(result['runtime_status'], 'reconciliation_required')
        for op in ('incomplete', 'fresh'):
            result = server.yeoul_new('p', no_arc=True, operation_id=op)
            self.assertEqual(result['runtime_status'], 'reconciliation_required', result)
        self.assertEqual(server.status()['runtime_status'], 'reconciliation_required')
        self.assertFalse((self.root / 'projects').exists())

    def test_verification_requires_supervisor_baseline_and_exec(self):
        todo = self.root / 'TODO.md'
        todo.write_text('- [x] evidence. verify: `printf approved > verified.txt`\n')
        self.assert_denied(server.verify_gate('TODO.md', operation_id='verify'))
        self.assertFalse((self.root / 'verified.txt').exists())
        with patch.dict(os.environ, {'YEOUL_MCP_ALLOW_EXEC': '1'}):
            self.assert_denied(server.verify_gate('TODO.md', operation_id='verify'))
            approved = self.root / '.yeoul-approved/baseline.json'
            approved.parent.mkdir()
            approved.write_text(json.dumps(dict(version=1, todo=str(todo),
                                               text=todo.read_text().replace('[x]', '[ ]'))))
            with patch.dict(os.environ, {'YEOUL_MCP_VERIFY_BASELINE': str(approved)}):
                self.assert_denied(server.verify_gate('TODO.md', baseline_path='unapproved.json',
                                                     operation_id='wrong-baseline'))
                self.assert_denied(server.loop_guard_init('.yeoul-approved', operation_id='protected'))
                result = server.verify_gate('TODO.md', operation_id='verify')
                self.assertEqual(result['exit_code'], 0, result)
                self.assertEqual((self.root / 'verified.txt').read_text(), 'approved')
                todo.write_text('- [x] evidence. verify: `printf changed > bypass.txt`\n')
                result = server.verify_gate('TODO.md', operation_id='changed-criteria')
                self.assertEqual(result['exit_code'], 3, result)
                self.assertFalse((self.root / 'bypass.txt').exists())

    def test_same_second_open_preserves_both_arcs(self):
        first = server.arc_open('audit', 'arcs', operation_id='open-1')
        second = server.arc_open('audit', 'arcs', operation_id='open-2')
        self.assertEqual(first['exit_code'], 0, first)
        self.assertEqual(second['exit_code'], 0, second)
        arcs = list((self.root / 'arcs').iterdir())
        self.assertEqual(len(arcs), 2)
        self.assertTrue(all((a / 'ARC' / (a.name + '.md')).is_file() for a in arcs))

    def test_trusted_mode_without_id_remains_available(self):
        os.environ.pop('YEOUL_MCP_ROOT')
        os.environ.pop('YEOUL_MCP_ALLOW_WRITE')
        result = server.yeoul_new('trusted', no_arc=True, workspace=str(self.root))
        self.assertEqual(result['exit_code'], 0, result)
        self.assertFalse((self.root / '.yeoul-mcp').exists())
        self.assert_denied(server.yeoul_new('with-id', no_arc=True, workspace=str(self.root),
                                           operation_id='legacy'))

    def test_allowlist_and_policy_rechecked_before_replay(self):
        with patch.dict(os.environ, {'YEOUL_MCP_WRITE_TOOLS': 'yeoul_new'}):
            result = server.yeoul_new('p', no_arc=True, operation_id='new')
            self.assertEqual(result['exit_code'], 0, result)
            self.assert_denied(server.build_handoff('p', operation_id='handoff'))
        with patch.dict(os.environ, {'YEOUL_MCP_WRITE_TOOLS': ''}):
            self.assert_denied(server.yeoul_new('p', no_arc=True, operation_id='new'))
        with patch.dict(os.environ, {'YEOUL_MCP_WRITE_TOOLS': 'invented'}):
            self.assert_denied(server.yeoul_new('p', no_arc=True, operation_id='new'))
        self.assertEqual(server.yeoul_new('p', no_arc=True, operation_id='new'), result)
        target = self.root / 'alias'
        try:
            target.symlink_to(self.root / 'projects', target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        self.assert_denied(server.yeoul_new('p', no_arc=True, operation_id='new'))

    def test_strict_receipt_parser(self):
        self.assertEqual(self.result(self.spawn('strict'))['exit_code'], 0)
        path = self.root / '.yeoul-mcp' / (hashlib.sha256(b'strict').hexdigest() + '.json')
        original = path.read_text()
        record = json.loads(original)
        bad = ['[]', original.replace('"version": 1', '"version": 1, "version": 1', 1),
               original.replace('"exit_code": 0', '"exit_code": NaN'),
               original.replace('"exit_code": 0', '"exit_code": true'),
               original.replace('"state": "complete"', '"state": "other"')]
        for value in bad:
            with self.subTest(value=value[:60]):
                path.write_text(value)
                with self.assertRaises((runtime.Refusal, ValueError)):
                    runtime.read_json(path)
        path.write_text(original)
        self.assertEqual(runtime.read_json(path), record)

    @unittest.skipUnless(os.name == 'posix', 'POSIX owner/mode contract')
    def test_control_directory_owner_only(self):
        control = self.root / '.yeoul-mcp'
        control.mkdir(mode=0o755)
        control.chmod(0o755)
        self.assert_denied(server.status())
        self.assertFalse((control / 'workspace.lock').exists())
        control.chmod(0o700)
        self.assertEqual(server.status()['exit_code'], 0)

    def test_replay_after_original_arc_is_moved(self):
        arc = self.root / 'arc'
        arc.mkdir()
        first = server.loop_guard_init('arc', operation_id='init')
        self.assertEqual(first['exit_code'], 0, first)
        arc.rename(self.root / 'archived')
        self.assertEqual(server.loop_guard_init('arc', operation_id='init'), first)
        self.assertFalse(arc.exists())

    def test_stdio_schema_and_runtime_enforcement(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise():
            params = StdioServerParameters(command=sys.executable,
                     args=['-c', 'from yeoul_mcp.server import main; main()'], env=self.env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    tools = {t.name: t for t in listed.tools}
                    self.assertEqual(len(tools), 15)
                    readers = {'status', 'arc_list', 'ralph_gate_check'}
                    for name, tool in tools.items():
                        properties = tool.inputSchema['properties']
                        self.assertEqual('operation_id' in properties,
                                         name not in readers and not name.startswith('workspace_'))
                        self.assertNotIn('operation_id', tool.inputSchema.get('required', []))
                    response = await client.call_tool('yeoul_new', dict(name='wire', no_arc=True))
                    self.assertIn('operation_id required', response.content[0].text)
                    args = dict(name='wire', no_arc=True, operation_id='wire-new')
                    first = await client.call_tool('yeoul_new', args)
                    again = await client.call_tool('yeoul_new', args)
                    self.assertEqual(first.content, again.content)
                    self.assertTrue((self.root / 'projects/wire').is_dir())
        asyncio.run(asyncio.wait_for(exercise(), timeout=30))


if __name__ == '__main__':
    unittest.main(verbosity=2)
