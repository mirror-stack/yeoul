"""Offline build and direct wheel import; no pip install or deployment.

Requires already available pip/setuptools/wheel. Does not replace installation,
entrypoint, harness execution-permission or live MCP integration tests.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]


class WheelArchive(unittest.TestCase):
    def test_archive_parity_and_pure_contracts_without_install(self):
        with tempfile.TemporaryDirectory(prefix='yeoul archive check ') as folder:
            base = Path(folder)
            source = base / 'source'
            source.mkdir()
            for name in ('mcp', 'bin', 'templates'):
                shutil.copytree(REPO / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__', 'build', '*.egg-info', '_harness'))
            shutil.copy2(REPO / 'LICENSE', source / 'LICENSE')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1',
                       PIP_DISABLE_PIP_VERSION_CHECK='1')
            result = subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(source / 'mcp'),
                                     '--no-deps', '--no-build-isolation', '--no-cache-dir',
                                     '--wheel-dir', str(base / 'wheels')],
                                    cwd=base, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wheel, = (base / 'wheels').glob('*.whl')
            with zipfile.ZipFile(wheel) as archive:
                for original in (REPO / 'mcp' / 'yeoul_mcp').glob('*.py'):
                    self.assertEqual(original.read_bytes(), archive.read('yeoul_mcp/'+original.name))
                for directory in ('bin', 'templates'):
                    for original in (REPO / directory).iterdir():
                        if original.is_file() and not original.name.startswith('_t_'):
                            self.assertEqual(original.read_bytes(), archive.read(
                                'yeoul_mcp/_harness/'+directory+'/'+original.name))
                self.assertNotIn('yeoul_mcp/verified_task.py', archive.namelist())
                self.assertNotIn('yeoul_mcp/verified_task_adapter.py', archive.namelist())
            runner = '''
import importlib, importlib.util, os, sys, unittest
sys.path.insert(0, sys.argv[1])
os.environ['PRODUCT_TEST_INSTALLED'] = '1'
for name in ('context_shadow', 'review_decision', 'shadow_workflow', 'worker_transport',
             'jsonl_transport', 'candidate_input', 'session_context', 'session_extraction',
             'session_runner'):
    module = importlib.import_module('yeoul_mcp.'+name)
    assert module.__file__.startswith(sys.argv[1] + '/'), module.__file__
suite = unittest.TestSuite()
for index, path in enumerate(sys.argv[2:]):
    spec = importlib.util.spec_from_file_location('archive_test_'+str(index), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
'''
            copies = []
            for name in ('test_context_shadow.py', 'test_review_decision.py', 'test_shadow_workflow.py',
                         'test_worker_transport.py', 'test_jsonl_transport.py', 'test_candidate_input.py', 'test_isolated_worker.py',
                         'test_worker_host.py', 'test_worker_tasks.py', 'test_worker_access.py', 'test_recovery_view.py',
                         'test_worker_storage.py', 'test_evidence_compare.py', 'test_recovery_actions.py',
                         'test_file_sources.py', 'test_session_context.py', 'test_session_extraction.py',
                         'test_session_runner.py'):
                dest = base / name
                shutil.copy2(REPO / 'mcp' / 'tests' / name, dest)
                copies.append(str(dest))
            result = subprocess.run([sys.executable, '-I', '-B', '-c', runner, str(wheel), *copies],
                                    cwd=base, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
