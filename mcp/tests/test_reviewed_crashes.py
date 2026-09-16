"""POSIX SIGKILL at durable boundaries, only in owned temporary subprocesses."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp import server, runtime
from yeoul_mcp.product import workspace

SOURCE = str(Path(server.__file__).resolve().parents[1])
CHILD = '''
import json, os, signal, sys
from pathlib import Path
from yeoul_mcp import runtime, server
from yeoul_mcp.product import workspace
from yeoul_mcp.reviewed_execution import execute_reviewed
root, task, stage = sys.argv[1:4]
def host(raw):
    binding = json.loads(raw)['binding']
    return dict(approved=True, reports=[dict(check_id='synthetic', provider_id='fixture',
        binding=binding, status='pass', evidence_ref='fixture:crash')])
def die():
    os.kill(os.getpid(), signal.SIGKILL)
original_write = runtime.write_json
def write(path, value):
    original_write(path, value)
    if ((stage == 'audit' and path.parent.name == 'reviews')
        or (stage == 'active' and path.name == 'active.json')
        or (stage == 'pending' and value.get('state') == 'pending')
        or (stage == 'complete' and value.get('state') == 'complete')):
        die()
runtime.write_json = write
original_run = server._run
def run(*args, **kwargs):
    result = original_run(*args, **kwargs)
    if len(sys.argv) == 5:
        assert result['exit_code'] == -signal.SIGKILL, result
    if stage == 'effect':
        assert result['exit_code'] == 0, result
        die()
    return result
server._run = run
if len(sys.argv) == 5:
    server.BIN = Path(sys.argv[4])
print(json.dumps(execute_reviewed(workspace, root, task, host)))
'''


@unittest.skipUnless(os.name == 'posix', 'requires POSIX SIGKILL')
class ReviewedCrashes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul-crash-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'workspace'
        env = {k: v for k, v in os.environ.items() if not k.startswith(('YEOUL_', 'AM_'))}
        self.patch = patch.dict(os.environ, env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        workspace.setup(self.root, 'discuss', 'prepared_only')
        active = workspace.activated(self.root)
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)

    def prepare(self, tool='yeoul_new', **args):
        return workspace.prepare(self.root, tool, args or dict(name='synthetic', no_arc=True),
            review=dict(proposal={'intent': tool}, requirements={'synthetic': 'fixture'}))['task_id']

    def child(self, task, stage, scripts=None):
        args = [sys.executable, '-B', '-c', CHILD, str(self.root), task, stage]
        if scripts is not None:
            args.append(str(scripts))
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True, timeout=25,
            env=dict(os.environ, PYTHONPATH=SOURCE, PYTHONDONTWRITEBYTECODE='1'))

    def test_sigkill_at_each_durable_boundary_then_new_process_retry(self):
        # Each boundary has an independent root, retaining every pre-restart byte.
        for stage in ('audit', 'active', 'pending', 'effect', 'complete'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(prefix='yeoul-stage-') as tmp:
                root = Path(tmp).resolve() / 'workspace'
                workspace.setup(root, 'discuss', 'prepared_only')
                with workspace.activated(root):
                    saved_root, self.root = self.root, root
                    try:
                        task = self.prepare()
                        killed = self.child(task, stage)
                        self.assertEqual(killed.returncode, -signal.SIGKILL, killed.stdout + killed.stderr)
                        control = root / '.yeoul-mcp'
                        audits = {p.name: p.read_bytes() for p in (control / 'reviews').glob('*.json')}
                        self.assertEqual(len(audits), 1)
                        effect = (root / 'projects/synthetic').exists()
                        self.assertEqual(effect, stage in ('effect', 'complete'))
                        path = control / (hashlib.sha256(task.encode()).hexdigest() + '.json')
                        receipt_before = path.read_bytes() if path.exists() else None
                        restarted = self.child(task, 'retry')
                        self.assertEqual(restarted.returncode, 0, restarted.stdout + restarted.stderr)
                        result = json.loads(restarted.stdout)['result']
                        if stage in ('audit', 'complete'):
                            self.assertEqual(result['exit_code'], 0, result)
                        else:
                            self.assertEqual(result['runtime_status'], 'reconciliation_required', result)
                            self.assertEqual((root / 'projects/synthetic').exists(), effect)
                            workspace.recover(root, acknowledge=True, children_stopped=True,
                                note='Owned child SIGKILL confirmed; synthetic effects and records inspected')
                            self.assertEqual(workspace.receipt(root, task)['state'], 'retired')
                        if receipt_before is not None:
                            self.assertEqual(path.read_bytes(), receipt_before)
                        for name, raw in audits.items():
                            self.assertEqual((control / 'reviews' / name).read_bytes(), raw)
                    finally:
                        self.root = saved_root

    def test_real_shell_killed_after_archive_move_preserves_partial_state(self):
        self.assert_archive_interruption('mv "$ARC_DIR" "$ARCHIVE_DIR/"', False, False)

    def test_real_shell_killed_after_summary_update_preserves_partial_state(self):
        self.assert_archive_interruption("sed_inplace 's/Arc close draft/Arc closed/'", True, False)

    def test_real_shell_killed_after_archive_record_does_not_claim_completion(self):
        self.assert_archive_interruption("printf 'ARCHIVE_RECORD ", True, True)

    def assert_archive_interruption(self, marker, closed, recorded):
        import shutil
        # Instrument only a private copy; no production fault-injection switch.
        scripts = Path(self.tmp.name).resolve() / 'scripts'
        shutil.copytree(server.BIN, scripts)
        close = scripts / 'arc-close'
        original = close.read_text(encoding='utf-8')
        checkpoints = [line for line in original.splitlines(keepends=True) if marker in line]
        self.assertEqual(len(checkpoints), 1)
        checkpoint = checkpoints[0]
        close.write_text(original.replace(checkpoint, checkpoint + 'kill -KILL "$$"\n'),
                         encoding='utf-8', newline='\n')
        opened = self.child(self.prepare('arc_open', slug='synthetic', arcs_dir='arcs'), 'run')
        self.assertEqual(json.loads(opened.stdout)['result']['exit_code'], 0)
        arc = next((self.root / 'arcs').glob('*_synthetic'))
        args = dict(arc_dir=str(arc), verdict='GO synthetic')
        draft = self.child(self.prepare('arc_close', **args), 'run')
        self.assertEqual(json.loads(draft.stdout)['result']['exit_code'], 0)
        summary = next(arc.glob('_SUMMARY*'))
        summary.write_text(summary.read_text(encoding='utf-8').replace(
            '(fill in)', 'synthetic concrete conclusion'), encoding='utf-8', newline='\n')
        task = self.prepare('arc_close', **args)
        interrupted = self.child(task, 'run', scripts)
        self.assertEqual(interrupted.returncode, 0, interrupted.stdout + interrupted.stderr)
        self.assertEqual(json.loads(interrupted.stdout)['result']['runtime_status'], 'reconciliation_required')
        archived = arc.parent / '_archive' / arc.name
        self.assertFalse(arc.exists())
        self.assertTrue(archived.exists())
        self.assertTrue((archived / '.close.lock').is_dir())
        thread = (archived / 'ARC' / (arc.name + '.md')).read_text(encoding='utf-8')
        self.assertIn('status: "Closed"' if closed else 'Close-Pending', thread)
        self.assertEqual('ARCHIVE_RECORD ' in (archived / 'STATE.md').read_text(
            encoding='utf-8'), recorded)
        self.assertEqual('Arc closed' in (archived / summary.name).read_text(
            encoding='utf-8'), closed)
        self.assertEqual(workspace.receipt(self.root, task)['state'], 'pending')
        receipt = self.root / '.yeoul-mcp' / (hashlib.sha256(task.encode()).hexdigest() + '.json')
        retained_receipt = receipt.read_bytes()
        reviews = self.root / '.yeoul-mcp/reviews'
        retained_reviews = {p.name: p.read_bytes() for p in reviews.glob('*.json')}
        retained = {str(p.relative_to(archived)): p.read_bytes() for p in archived.rglob('*') if p.is_file()}
        self.assertEqual(json.loads(self.child(task, 'retry').stdout)['result']['runtime_status'], 'reconciliation_required')
        workspace.recover(self.root, acknowledge=True, children_stopped=True,
            note='Synthetic shell SIGKILL confirmed; interrupted archive retained for manual inspection')
        self.assertEqual(workspace.receipt(self.root, task)['state'], 'retired')
        self.assertEqual(retained, {str(p.relative_to(archived)): p.read_bytes() for p in archived.rglob('*') if p.is_file()})
        self.assertTrue((archived / '.close.lock').exists(), 'recovery must not pretend to repair the archive')
        self.assertEqual(receipt.read_bytes(), retained_receipt)
        self.assertEqual({p.name: p.read_bytes() for p in reviews.glob('*.json')}, retained_reviews)


if __name__ == '__main__':
    unittest.main()
