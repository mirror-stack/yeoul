"""Bounded duplex JSONL for trusted, host-selected Linux subprocesses.

Not a sandbox, model adapter, billing guard or remote cancellation guarantee.
No retries, automatic RPCs, credential lookup, or raw error output.
"""
import json
import math
import os
import selectors
import signal
import subprocess
import sys
import time

from .worker_transport import CommandWorker, WorkerTransportError


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite JSON value')


def _validate_content(value):
    """Validate acyclic parsed/serialized values without coercing object keys."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            item.encode('utf-8')
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError('nonfinite JSON value')
        elif isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError('string keys required')
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


class JsonlProcess:
    """One total deadline and cumulative byte caps, including notifications.

    The caller must use a context manager. Any I/O/protocol failure poisons the
    session; partial output cannot be recovered as a successful response. A
    successful receive is only a frame, never proof of task completion. Caller
    owns RPC matching, durable intent, tool policy, and remote cancel evidence.
    """
    def __init__(self, argv, *, cwd, env=None, timeout=30, cleanup_timeout=3,
                 input_limit=1048576, stdout_limit=1048576, stderr_limit=65536):
        self.spec = CommandWorker(argv, cwd=cwd, env=env, timeout=timeout,
                                  cleanup_timeout=cleanup_timeout,
                                  input_limit=input_limit, stdout_limit=stdout_limit,
                                  stderr_limit=stderr_limit)
        self.child = None
        self.selector = None
        self.buffer = bytearray()
        self.sent = self.received = self.errors = 0
        self.failed = self.closed = False

    def __enter__(self):
        if self.child is not None or self.closed:
            raise ValueError('session cannot be reused')
        if sys.platform != 'linux':
            raise WorkerTransportError('unsupported_worker_transport')
        self.deadline = time.monotonic() + self.spec.timeout
        self.selector = selectors.DefaultSelector()
        try:
            self.child = subprocess.Popen(self.spec.argv, cwd=self.spec.cwd, env=self.spec.env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, close_fds=True)
            for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
                os.set_blocking(stream.fileno(), False)
            for stream, name in ((self.child.stdout, 'stdout'), (self.child.stderr, 'stderr')):
                self.selector.register(stream, selectors.EVENT_READ, name)
        except BaseException:
            self.close()
            raise
        return self

    def _fail(self, reason):
        self.failed = True
        raise WorkerTransportError(reason) from None

    def _check(self):
        if self.closed or self.failed or self.child is None:
            raise WorkerTransportError('jsonl_session_unavailable')
        if time.monotonic() >= self.deadline:
            self._fail('jsonl_timeout')

    def _pump(self, pending=None):
        self._check()
        written = 0
        try:
            events = self.selector.select(max(0, min(0.05, self.deadline-time.monotonic())))
        except OSError:
            self._fail('jsonl_io_failed')
        for key, _ in events:
            if key.data == 'stdin':
                try:
                    written = os.write(key.fd, pending[:65536])
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    self._fail('jsonl_input_incomplete')
                except OSError:
                    self._fail('jsonl_io_failed')
                continue
            try:
                chunk = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                self._fail('jsonl_io_failed')
            if not chunk:
                try:
                    self.selector.unregister(key.fileobj)
                except (OSError, ValueError, KeyError):
                    self._fail('jsonl_io_failed')
                if key.data == 'stdout':
                    self._fail('jsonl_eof')
                continue
            if key.data == 'stderr':
                self.errors += len(chunk)
                if self.errors > self.spec.stderr_limit:
                    self._fail('jsonl_stderr_limit')
            else:
                self.received += len(chunk)
                if self.received > self.spec.stdout_limit:
                    self._fail('jsonl_stdout_limit')
                self.buffer.extend(chunk)
        return written

    def send(self, value):
        self._check()
        if not isinstance(value, dict):
            self._fail('jsonl_request_invalid')
        try:
            raw = (json.dumps(value, allow_nan=False, ensure_ascii=False,
                              separators=(',', ':'))+'\n').encode('utf-8')
            # Serialization rejects cycles before the iterative content walk.
            _validate_content(value)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._fail('jsonl_request_invalid')
        if self.sent + len(raw) > self.spec.input_limit:
            self._fail('jsonl_input_limit')
        try:
            self.selector.register(self.child.stdin, selectors.EVENT_WRITE, 'stdin')
        except (OSError, ValueError, KeyError):
            self._fail('jsonl_io_failed')
        offset = 0
        try:
            while offset < len(raw):
                count = self._pump(memoryview(raw)[offset:])
                offset += count
                self.sent += count
        finally:
            try:
                self.selector.unregister(self.child.stdin)
            except (OSError, ValueError, KeyError):
                # Preserve the original timeout/protocol failure, if any.
                if not self.failed:
                    self._fail('jsonl_io_failed')

    def receive(self):
        self._check()
        while b'\n' not in self.buffer:
            self._pump()
        self._check()
        raw, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        try:
            value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                               parse_constant=_constant)
            _validate_content(value)
            if not isinstance(value, dict):
                raise ValueError('object required')
        except (ValueError, UnicodeError, RecursionError):
            self._fail('jsonl_response_invalid')
        self._check()
        return value

    def poll(self):
        """Drain once; return one complete frame or None without renewing limits.

        Allows a host to send a cancellation before the total transport deadline.
        A partial frame is never returned. Transport errors still poison the session.
        """
        self._check()
        if b'\n' not in self.buffer:
            self._pump()
        return self.receive() if b'\n' in self.buffer else None

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.selector is not None:
            self.selector.close()
        if self.child is not None:
            # Do not poll/reap before signalling: reserve leader PID until cleanup.
            try:
                os.killpg(self.child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
                    stream.close()
                try:
                    self.child.wait(timeout=self.spec.cleanup_timeout)
                except subprocess.TimeoutExpired as exc:
                    raise WorkerTransportError('jsonl_cleanup_incomplete') from exc

    def __exit__(self, *exc):
        self.close()
