"""Real synthetic processes only: no accounts, models, network or installation."""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.jsonl_transport import JsonlProcess
from yeoul_mcp.worker_transport import WorkerTransportError


@unittest.skipUnless(sys.platform == 'linux', 'Linux transport')
class JsonlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='yeoul-jsonl-')
        self.addCleanup(folder.cleanup)
        self.cwd = folder.name

    def process(self, code, **limits):
        return JsonlProcess([sys.executable, '-B', '-u', '-c', code], cwd=self.cwd, **limits)

    def test_duplex_unicode_notifications_and_cleanup(self):
        code = '''import sys,json
for line in sys.stdin:
 print('{"method":"notice"}')
 print(json.dumps({'id':json.loads(line)['id'],'result':'\uc5ec\uc6b8'}))
'''
        with self.process(code) as p:
            for number in range(3):
                p.send({'id':number,'params':'\uac00\uc0c1'})
                self.assertEqual(p.receive(), {'method':'notice'})
                self.assertEqual(p.receive(), {'id':number,'result':'\uc5ec\uc6b8'})
        self.assertIsNotNone(p.child.returncode)
        with self.assertRaises(WorkerTransportError):
            p.receive()

    def test_silence_timeout_poison_and_cleanup(self):
        started = time.monotonic()
        with self.process('import time; time.sleep(30)', timeout=.2) as p:
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_timeout'):
                p.receive()
            with self.assertRaisesRegex(WorkerTransportError, 'unavailable'):
                p.send({'id':1})
        self.assertLess(time.monotonic()-started, 3)
        self.assertIsNotNone(p.child.returncode)

    def test_blocked_stdin_respects_deadline(self):
        with self.process('import time; time.sleep(30)', timeout=.2) as p:
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_timeout'):
                p.send({'text':'x'*500000})

    def test_stdout_and_stderr_flood_bounded(self):
        for fd, name in [(1,'stdout'),(2,'stderr')]:
            with self.subTest(name=name), self.process(
                f'import os,time; os.write({fd}, b"x"*2000); time.sleep(30)',
                stdout_limit=1000, stderr_limit=1000) as p:
                with self.assertRaisesRegex(WorkerTransportError, 'jsonl_'+name+'_limit'):
                    p.receive()

    def test_partial_eof_never_returns_response(self):
        with self.process('import os; os.write(1,b\'{"result":1}\')') as p:
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_eof'):
                p.receive()

    def test_malformed_duplicate_nonfinite_and_nonobject(self):
        for raw in [b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{"x":1e999}\n',
                    b'[]\n', b'\xff\n', b'{broken}\n']:
            with self.subTest(raw=raw), self.process(
                f'import os,time; os.write(1,{raw!r}); time.sleep(30)') as p:
                with self.assertRaisesRegex(WorkerTransportError, 'jsonl_response_invalid'):
                    p.receive()

    def test_input_cap_is_cumulative(self):
        with self.process('import time; time.sleep(30)', input_limit=10) as p:
            p.send({})
            p.send({})
            p.send({})
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_input_limit'):
                p.send({})

    def test_output_cap_is_cumulative_across_frames(self):
        code = 'import sys\nfor line in sys.stdin: print("{}",flush=True)'
        with self.process(code, stdout_limit=8) as p:
            for _ in range(2):
                p.send({})
                self.assertEqual(p.receive(), {})
            p.send({})
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_stdout_limit'):
                p.receive()

    def test_no_deadline_reset_on_receive(self):
        with self.process('import time; print("{}",flush=True); time.sleep(30)', timeout=.2) as p:
            self.assertEqual(p.receive(), {})
            time.sleep(.25)
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_timeout'):
                p.receive()

    def test_exception_closes_owned_child_and_session_is_not_reusable(self):
        p = self.process('import time; time.sleep(30)')
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            with p:
                raise ValueError('synthetic')
        self.assertIsNotNone(p.child.returncode)
        with self.assertRaises(ValueError):
            p.__enter__()

    def test_same_group_child_cannot_write_after_caller_cancels(self):
        marker = Path(self.cwd)/'unexpected'
        descendant = 'import time,pathlib; time.sleep(.5); pathlib.Path("unexpected").touch()'
        code = (f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{descendant!r}]); '
                'print("{}",flush=True); time.sleep(30)')
        with self.process(code) as p:
            self.assertEqual(p.receive(), {})
        time.sleep(.65)
        self.assertFalse(marker.exists())

    def test_invalid_outbound_json_poisons_session_without_sending(self):
        for value in [[], {'x':float('nan')}, {'x':object()}]:
            with self.subTest(value=type(value)), self.process('import time; time.sleep(30)') as p:
                with self.assertRaisesRegex(WorkerTransportError, 'jsonl_request_invalid'):
                    p.send(value)
                self.assertEqual(p.sent, 0)

    def test_launch_failure_has_no_fallback(self):
        # Use our traversable fixture, not a host path that may deny access.
        missing = Path(self.cwd) / 'missing-yeoul-jsonl-test'
        p = JsonlProcess([str(missing)], cwd=self.cwd)
        with self.assertRaises(FileNotFoundError):
            with p:
                self.fail('must not enter')
        self.assertTrue(p.closed)

    def test_nonstring_request_keys_are_not_coerced_to_duplicate_keys(self):
        with self.process('import time; time.sleep(30)') as p:
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_request_invalid'):
                p.send({'nested': {1: 'first', '1': 'second'}})
            self.assertEqual(p.sent, 0)

    def test_escaped_unpaired_surrogate_is_not_valid_utf8_content(self):
        with self.process('import time; time.sleep(30)') as p:
            p.buffer.extend(b'{"result":"\\ud800"}\n')
            with self.assertRaisesRegex(WorkerTransportError, 'jsonl_response_invalid'):
                p.receive()

    def test_selector_error_poisons_session_without_raw_error(self):
        with self.process('import time; time.sleep(30)') as p:
            with patch.object(p.selector, 'select', side_effect=OSError('private detail')):
                with self.assertRaisesRegex(WorkerTransportError, '^jsonl_io_failed$'):
                    p.receive()
            with self.assertRaisesRegex(WorkerTransportError, 'unavailable'):
                p.send({})

    def test_response_parsed_after_deadline_is_refused(self):
        import yeoul_mcp.jsonl_transport as transport
        with self.process('import time; time.sleep(30)') as p:
            p.buffer.extend(b'{}\n')
            original = transport.json.loads
            def expire(raw, **kwargs):
                result = original(raw, **kwargs)
                p.deadline = 0
                return result
            with patch.object(transport.json, 'loads', side_effect=expire):
                with self.assertRaisesRegex(WorkerTransportError, 'jsonl_timeout'):
                    p.receive()

    def test_stdin_registration_failure_poisons_session(self):
        with self.process('import time; time.sleep(30)') as p:
            with patch.object(p.selector, 'register', side_effect=OSError('private registration')):
                with self.assertRaisesRegex(WorkerTransportError, '^jsonl_io_failed$'):
                    p.send({})
            with self.assertRaisesRegex(WorkerTransportError, 'unavailable'):
                p.receive()

    def test_stdin_unregister_failure_poisons_session(self):
        with self.process('import time; time.sleep(30)') as p:
            with patch.object(p.selector, 'unregister', side_effect=OSError('private unregister')):
                with self.assertRaisesRegex(WorkerTransportError, '^jsonl_io_failed$'):
                    p.send({})
            with self.assertRaisesRegex(WorkerTransportError, 'unavailable'):
                p.receive()

    def test_unregister_error_does_not_replace_original_failure(self):
        with self.process('import time; time.sleep(30)') as p:
            with patch.object(p.selector, 'unregister', side_effect=OSError('private unregister')):
                with patch.object(p, '_pump', side_effect=lambda *args: p._fail('jsonl_timeout')):
                    with self.assertRaisesRegex(WorkerTransportError, '^jsonl_timeout$'):
                        p.send({})
            self.assertTrue(p.failed)

    def test_output_eof_unregister_error_poisons_session(self):
        import selectors
        for stream_name in ('stdout', 'stderr'):
            with self.subTest(stream=stream_name), self.process('import time; time.sleep(30)') as p:
                stream = getattr(p.child, stream_name)
                key = p.selector.get_key(stream)
                with patch.object(p.selector, 'select', return_value=[(key, selectors.EVENT_READ)]), \
                     patch('yeoul_mcp.jsonl_transport.os.read', return_value=b''), \
                     patch.object(p.selector, 'unregister', side_effect=OSError('private output detail')):
                    with self.assertRaisesRegex(WorkerTransportError, '^jsonl_io_failed$'):
                        p.receive()
                with self.assertRaisesRegex(WorkerTransportError, 'unavailable'):
                    p.send({})

    def test_poll_silence_does_not_poison_or_renew_deadline(self):
        with self.process('import sys,time; time.sleep(.2); print(sys.stdin.readline(),end="",flush=True); time.sleep(1)') as p:
            deadline=p.deadline
            self.assertIsNone(p.poll())
            self.assertFalse(p.failed)
            p.send({'cancel':'synthetic'})
            self.assertEqual(p.receive(),{'cancel':'synthetic'})
            self.assertEqual(p.deadline,deadline)

    def test_poll_never_returns_partial_frame(self):
        with self.process('import time; time.sleep(30)') as p:
            p.buffer.extend(b'{"x":')
            self.assertIsNone(p.poll())
            p.buffer.extend(b'1}\n')
            self.assertEqual(p.poll(),{'x':1})
            p.deadline=0
            with self.assertRaisesRegex(WorkerTransportError,'jsonl_timeout'): p.poll()


if __name__ == '__main__':
    unittest.main(verbosity=2)
