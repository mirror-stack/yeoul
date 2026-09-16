"""Offline wheel parity check. Build artifacts and execution stay in a temporary tree."""
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class DistributionContract(unittest.TestCase):
    def test_wheel_contains_current_harness_and_passes_its_regressions(self):
        with tempfile.TemporaryDirectory(prefix='yeoul distribution ') as folder:
            base = Path(folder)
            source = base / 'source'
            source.mkdir()
            for name in ('mcp', 'bin', 'templates'):
                shutil.copytree(REPO / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__', 'build', '*.egg-info', '_harness'))
            shutil.copy2(REPO / 'LICENSE', source / 'LICENSE')
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1',
                       PIP_DISABLE_PIP_VERSION_CHECK='1')
            build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(source / 'mcp'),
                                    '--no-deps', '--no-build-isolation', '--no-cache-dir',
                                    '--wheel-dir', str(base / 'wheels')],
                                   cwd=base, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheel, = (base / 'wheels').glob('*.whl')
            installed = base / 'installed'
            install = subprocess.run([sys.executable, '-m', 'pip', 'install', str(wheel),
                                      '--no-deps', '--no-compile', '--no-cache-dir',
                                      '--target', str(installed)], cwd=base, env=env,
                                     capture_output=True, text=True, timeout=90)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            package = installed / 'yeoul_mcp'
            for directory in ('bin', 'templates'):
                for original in (REPO / directory).iterdir():
                    if original.is_file() and not original.name.startswith('_t_'):
                        self.assertEqual(original.read_bytes(),
                                         (package / '_harness' / directory / original.name).read_bytes(),
                                         str(original))
            for original in (REPO / 'mcp' / 'yeoul_mcp').glob('*.py'):
                name = original.name
                self.assertEqual((REPO / 'mcp' / 'yeoul_mcp' / name).read_bytes(),
                                 (package / name).read_bytes(), name)
            self.assertFalse((package / 'verified_task.py').exists())
            self.assertFalse((package / 'verified_task_adapter.py').exists())
            # Run the same regression suite against the packaged harness, outside checkout.
            runner = '''
import importlib.util, sys, unittest
from pathlib import Path
spec = importlib.util.spec_from_file_location('packaged_hardening', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.REPO = Path(sys.argv[2])
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(module))
sys.exit(not result.wasSuccessful())
'''
            # Helpers imported by the suite must also come from the wheel, not checkout.
            env['PYTHONPATH'] = str(package / '_harness' / 'bin')
            test_copy = base / 'test_hardening.py'
            shutil.copy2(REPO / 'tests' / 'test_hardening.py', test_copy)
            result = subprocess.run([sys.executable, '-B', '-c', runner, str(test_copy),
                                     str(package / '_harness')], cwd=base, env=env,
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            env.update(PYTHONPATH=str(installed), PRODUCT_TEST_INSTALLED='1')
            installed_runner = '''
import runpy, sys
from pathlib import Path
import yeoul_mcp
assert Path(yeoul_mcp.__file__).resolve().parent == Path(sys.argv[2]).resolve(), yeoul_mcp.__file__
test = sys.argv[1]
sys.argv = [test]
runpy.run_path(test, run_name='__main__')
'''
            for name in ('test_context_shadow.py', 'test_session_context.py', 'test_session_extraction.py', 'test_session_runner.py', 'test_freshness.py', 'test_review_decision.py',
                         'test_shadow_workflow.py', 'test_product.py', 'test_runtime_contract.py',
                         'test_worker_transport.py', 'test_jsonl_transport.py', 'test_candidate_input.py',
                         'test_reviewed_execution.py', 'test_reviewed_tools.py',
                         'test_reviewed_crashes.py', 'test_isolated_worker.py', 'test_worker_host.py',
                         'test_worker_tasks.py', 'test_worker_access.py', 'test_recovery_view.py', 'test_worker_storage.py',
                         'test_evidence_compare.py', 'test_recovery_actions.py', 'test_file_sources.py',
                         'test_local_host.py', 'test_command_provider.py',
                         'test_mirror_registration_provider.py'):
                test_copy = base / name
                shutil.copy2(REPO / 'mcp' / 'tests' / name, test_copy)
                result = subprocess.run([sys.executable, '-B', '-c', installed_runner,
                                         str(test_copy), str(package)], cwd=base,
                                        env=env, capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                skipped = re.search(r'OK \(skipped=(\d+)\)', result.stderr)
                suffix = '; skipped=' + skipped.group(1) if skipped else ''
                print(name + ': passed against isolated installation' + suffix, flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
