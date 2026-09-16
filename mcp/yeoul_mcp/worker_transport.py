"""Bounded Linux command transport. Host-selected commands only; NOT a sandbox.

No model selection, credential discovery, installation or automatic retry.
Use a separately configured isolation launcher for untrusted commands. Process
groups cannot contain descendants that deliberately create a different session.
"""
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


class WorkerTransportError(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class CommandWorker:
    """Callable byte transport with host-fixed command, environment and limits.

    stdout/stderr are bounded independently while draining, not after communicate.
    Only stdout from a successful, fully supplied process is returned. Output is
    never executed or published. Rejected output is not returned as a proposal.
    """
    def __init__(self, argv, *, cwd, env=None, timeout=60, cleanup_timeout=5,
                 stdout_limit=65536, stderr_limit=65536, input_limit=4*1024*1024):
        if (not isinstance(argv, (list, tuple)) or not argv
                or any(not isinstance(a, str) or '\0' in a for a in argv)
                or not Path(argv[0]).is_absolute()):
            raise ValueError('host must select an absolute executable and argument list')
        if not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise ValueError('host must select an existing absolute cwd')
        for limit in (stdout_limit, stderr_limit, input_limit):
            if type(limit) is not int or not 1 <= limit <= 16*1024*1024:
                raise ValueError('invalid byte limit')
        for seconds in (timeout, cleanup_timeout):
            if type(seconds) not in (int, float) or not 0 < seconds <= 3600:
                raise ValueError('invalid time limit')
        if env is not None and (not isinstance(env, dict) or
                any(not isinstance(k, str) or not isinstance(v, str) or not k
                    or '=' in k or '\0' in k or '\0' in v for k, v in env.items())):
            raise ValueError('invalid explicit environment')
        self.argv, self.cwd, self.env = tuple(argv), str(cwd), dict(env or {})
        self.timeout, self.cleanup_timeout = timeout, cleanup_timeout
        self.stdout_limit, self.stderr_limit, self.input_limit = stdout_limit, stderr_limit, input_limit

    def __call__(self, payload):
        if sys.platform != 'linux' or not hasattr(os, 'WNOWAIT'):
            raise WorkerTransportError('unsupported_worker_transport')
        if not isinstance(payload, bytes) or len(payload) > self.input_limit:
            raise WorkerTransportError('worker_input_limit')
        deadline = time.monotonic() + self.timeout
        try:
            child = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
        except OSError as exc:
            raise WorkerTransportError('worker_launch_failed') from exc
        out, err, sent = bytearray(), bytearray(), 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream, label in ((child.stdout, 'stdout'), (child.stderr, 'stderr')):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, label)
                if payload:
                    os.set_blocking(child.stdin.fileno(), False)
                    selector.register(child.stdin, selectors.EVENT_WRITE, 'stdin')
                else:
                    child.stdin.close()
                while True:
                    # Observe without reaping: the leader PID stays reserved until
                    # process-group cleanup, avoiding signalling a recycled PID.
                    exited = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                    if exited is not None and not selector.get_map():
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WorkerTransportError('worker_timeout')
                    for key, _ in selector.select(min(remaining, 0.05)):
                        stream, label = key.fileobj, key.data
                        if label == 'stdin':
                            try:
                                sent += os.write(stream.fileno(), payload[sent:sent+65536])
                            except BrokenPipeError as exc:
                                raise WorkerTransportError('worker_input_incomplete') from exc
                            except BlockingIOError:
                                continue
                            if sent == len(payload):
                                selector.unregister(stream)
                                stream.close()
                        else:
                            buffer = out if label == 'stdout' else err
                            limit = self.stdout_limit if label == 'stdout' else self.stderr_limit
                            try:
                                chunk = os.read(stream.fileno(), min(65536, limit-len(buffer)+1))
                            except BlockingIOError:
                                continue
                            if not chunk:
                                selector.unregister(stream)
                                stream.close()
                            elif len(buffer) + len(chunk) > limit:
                                raise WorkerTransportError('worker_' + label + '_limit')
                            else:
                                buffer.extend(chunk)
                if sent != len(payload):
                    raise WorkerTransportError('worker_input_incomplete')
                if exited.si_code != os.CLD_EXITED or exited.si_status != 0:
                    raise WorkerTransportError('worker_exit_failed')
        finally:
            # Includes successful leaders with lingering same-group descendants.
            # No raw-execution fallback if launch/transport/cleanup fails.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if not stream.closed:
                        stream.close()
                try:
                    child.wait(timeout=self.cleanup_timeout)
                except subprocess.TimeoutExpired as exc:
                    raise WorkerTransportError('worker_cleanup_incomplete') from exc
        return bytes(out)
