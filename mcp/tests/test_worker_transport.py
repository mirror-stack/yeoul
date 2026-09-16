"""Real synthetic child processes; no live model or operational settings."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.worker_transport import CommandWorker, WorkerTransportError


@unittest.skipUnless(sys.platform == 'linux', 'Linux transport capability only')
class WorkerTransport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul transport ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def worker(self, code, **limits):
        return CommandWorker([sys.executable, '-I', '-B', '-c', code], cwd=self.root, **limits)

    def test_exact_input_and_bounded_output(self):
        data = b'x' * 200000
        worker = self.worker('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())', stdout_limit=len(data))
        self.assertEqual(worker(data), data)

    def test_output_limit_is_not_truncated_success(self):
        for stream in ('stdout', 'stderr'):
            worker = self.worker(f'import sys; sys.{stream}.buffer.write(b"x" * 1000000)',
                                 stdout_limit=1024, stderr_limit=1024)
            with self.subTest(stream=stream), self.assertRaisesRegex(WorkerTransportError, 'worker_'+stream+'_limit'):
                worker(b'')

    def test_unresponsive_worker_times_out(self):
        start = time.monotonic()
        with self.assertRaisesRegex(WorkerTransportError, 'worker_timeout'):
            self.worker('import time; time.sleep(10)', timeout=0.15)(b'')
        self.assertLess(time.monotonic()-start, 3)

    def test_unconsumed_input_is_not_accepted(self):
        with self.assertRaisesRegex(WorkerTransportError, 'worker_input_incomplete'):
            self.worker('import os; os.close(0); print("{}")')(b'x'*1000000)

    def test_nonzero_exit_does_not_return_partial_output(self):
        with self.assertRaisesRegex(WorkerTransportError, 'worker_exit_failed'):
            self.worker('import sys; print("partial"); sys.exit(3)')(b'')

    def test_no_ambient_environment_or_shell_expansion(self):
        with patch.dict(os.environ, YEOUL_PRIVATE_TEST='synthetic-secret'):
            self.assertEqual(self.worker('import os; print(os.environ.get("YEOUL_PRIVATE_TEST", "absent"))')(b''), b'absent\n')

    def test_input_limit_prevents_launch(self):
        marker = self.root/'launched'
        worker = self.worker('from pathlib import Path; Path("launched").touch()', input_limit=1)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_input_limit'):
            worker(b'xx')
        self.assertFalse(marker.exists())

    def test_invalid_limits_refused(self):
        for limits in ({'timeout': float('nan')}, {'stdout_limit': True}, {'cleanup_timeout': 0}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.worker('pass', **limits)

    def test_missing_executable_never_falls_back(self):
        worker = CommandWorker([str(self.root/'missing')], cwd=self.root)
        with self.assertRaisesRegex(WorkerTransportError, 'worker_launch_failed'):
            worker(b'')

    def test_successful_parent_does_not_leave_same_group_child(self):
        marker = self.root/'survived'
        child_code = 'import time; from pathlib import Path; time.sleep(1); Path("survived").touch()'
        code = ('import subprocess,sys; '
                f'subprocess.Popen([sys.executable,"-c",{child_code!r}], '
                'stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); '
                'print("done")')
        self.assertEqual(self.worker(code)(b''), b'done\n')
        time.sleep(1.1)
        self.assertFalse(marker.exists())

    def test_lingering_child_is_stopped_on_timeout(self):
        marker = self.root/'survived'
        child_code = 'import time; from pathlib import Path; time.sleep(1); Path("survived").touch()'
        code = ('import subprocess,sys,time; '
                f'subprocess.Popen([sys.executable,"-c",{child_code!r}]); '
                'time.sleep(10)')
        with self.assertRaisesRegex(WorkerTransportError, 'worker_timeout'):
            self.worker(code, timeout=0.2)(b'')
        time.sleep(1.1)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
