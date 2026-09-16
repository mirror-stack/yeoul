"""Opt-in host-only Linux execution adapter; no MCP/admin endpoint or sudo policy.

The host supplies an authenticated, bounded broker and durable event sink. Worker
input cannot select that broker, service properties, UID, mounts or audit policy.
"""
import hashlib
import json
import os
import re
from pathlib import PurePosixPath
from pathlib import Path
import sys
import time
import uuid

from .worker_transport import WorkerTransportError


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


# One fixed source is used by the host and the standalone service bootstrap.
# This is product code, never generated from request/proposal content.
_START_GUARD = r'''
def check_start(ticket):
    import re, time
    from pathlib import Path
    if (not isinstance(ticket, dict) or set(ticket) != {'boot_id', 'issued_ns', 'expires_ns'}
            or not isinstance(ticket['boot_id'], str)
            or not re.fullmatch('[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', ticket['boot_id'])
            or type(ticket['issued_ns']) is not int or type(ticket['expires_ns']) is not int
            or ticket['issued_ns'] < 0 or ticket['expires_ns'] - ticket['issued_ns'] != 5_000_000_000):
        raise ValueError('invalid worker start ticket')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != ticket['boot_id']:
        raise ValueError('worker start ticket belongs to another boot')
    now = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    if not ticket['issued_ns'] <= now < ticket['expires_ns']:
        raise ValueError('worker start ticket expired or not yet valid')

def check_launch(manifest, directory='/run/yeoul-launch'):
    import hashlib, json, os, stat
    if manifest.get('version') != 3:
        return  # Historical/standalone ticket-only interface, not a revocation gate.
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('launch gate ownership differs')
        try:
            os.stat('launch.revoked.json', dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('worker launch revoked')
        permit_fd = os.open('launch.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(permit_fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('invalid launch permit file')
            raw = stream.read(4097)
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate launch permit key')
                result[key] = value
            return result
        permit = json.loads(raw, object_pairs_hook=unique) if len(raw) <= 4096 else None
        if (not isinstance(permit, dict) or type(permit.get('version')) is not int
                or permit != dict(version=1, unit=manifest['unit'], manifest_sha256=digest)):
            raise ValueError('launch permit binding differs')
    finally:
        os.close(fd)
'''
_guard_namespace = {}
exec(_START_GUARD, _guard_namespace)
check_start = _guard_namespace['check_start']
check_launch = _guard_namespace['check_launch']


def start_ticket():
    issued = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                issued_ns=issued, expires_ns=issued + 5_000_000_000)


# Runs as the configured non-root user, before any worker code. The broker may
# not claim resources merely from accepted service properties: check the kernel.
_BOOTSTRAP = _START_GUARD + r'''
import json, os, sys
from pathlib import Path
m = json.loads(sys.argv[1])
check_start(m['start_ticket'])
check_launch(m)
assert os.getuid() == m['uid'] != 0 and os.getgid() == m['gid'] != 0
relative = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                if line.startswith('0::'))
group = Path('/sys/fs/cgroup') / relative.lstrip('/')
assert group.name == m['unit'], 'unexpected cgroup'
assert (group/'cpu.max').read_text().split() == ['50000', '100000'], 'CPU limit not active'
assert int((group/'memory.max').read_text()) == 134217728, 'memory limit not active'
assert int((group/'memory.swap.max').read_text()) == 0, 'swap limit not active'
assert int((group/'pids.max').read_text()) == 16, 'process limit not active'
fs = os.statvfs('/tmp')
assert fs.f_blocks * fs.f_frsize == 16777216, 'output filesystem is not bounded'
command = ['/usr/bin/bwrap', '--unshare-user', '--unshare-pid', '--unshare-net',
    '--unshare-ipc', '--unshare-uts', '--die-with-parent', '--new-session',
    '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
    '--setenv', 'LANG', 'C.UTF-8', '--ro-bind', '/usr', '/usr',
    '--ro-bind', '/lib', '/lib', '--symlink', 'usr/bin', '/bin',
    '--proc', '/proc', '--dev', '/dev', '--bind', '/tmp', '/work', '--chdir', '/work']
if Path('/lib64').exists():
    command += ['--ro-bind', '/lib64', '/lib64']
command += ['--'] + m['argv']
check_start(m['start_ticket'])
check_launch(m)
os.execv(command[0], command)
'''


def service_command(manifest):
    """Canonical request shared with the host's allowlist broker."""
    properties = ['CPUQuota=50%', 'CPUQuotaPeriodSec=100ms', 'MemoryMax=128M',
        'MemorySwapMax=0', 'TasksMax=16', 'RuntimeMaxSec=' + str(manifest['limits']['runtime_seconds']) + 's',
        'TimeoutStopSec=3s', 'KillMode=control-group', 'OOMPolicy=stop',
        'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=yes',
        'ProtectControlGroups=yes', 'PrivateNetwork=yes',
        'TemporaryFileSystem=/tmp:rw,size=16M,mode=1777', 'UMask=0077']
    if manifest['version'] == 3:
        properties.append('BindReadOnlyPaths=' + manifest['launch_directory'] + ':/run/yeoul-launch')
    command = ['/usr/bin/systemd-run', '--no-ask-password', '--quiet', '--wait', '--pipe',
        '--collect', '--service-type=exec', '--unit=' + manifest['unit'], '--uid=' + str(manifest['uid']),
        '--gid=' + str(manifest['gid']), '--working-directory=/tmp']
    command += ['--property=' + value for value in properties]
    command += ['--', '/usr/bin/python3', '-I', '-B', '-c', _BOOTSTRAP, _encoded(manifest).decode()]
    return tuple(command)


class IsolatedWorker:
    """Callable for run_shadow with fixed resources and stdout-only proposals.

    broker(argv_tuple, input_bytes, timeout_seconds) -> bytes must execute only
    host-authorized commands with bounded pipes and raise on nonzero exit. The
    only commands requested here are systemd-run and systemctl for a fresh unit.
    record_event(json_bytes) must durably store each event before returning.
    Neither callback is trusted merely because it implements this interface.
    """
    def __init__(self, argv, *, broker, record_event, uid=None, gid=None, timeout=60):
        if sys.platform != 'linux':
            raise ValueError('isolated service adapter requires Linux')
        uid, gid = os.getuid() if uid is None else uid, os.getgid() if gid is None else gid
        if (type(uid) is not int or type(gid) is not int or not 1 <= uid < 2**31
                or not 1 <= gid < 2**31):
            raise ValueError('host must select a non-root user and group')
        if not callable(broker) or not callable(record_event):
            raise ValueError('host broker and durable event sink required')
        if (not isinstance(argv, (list, tuple)) or not argv or len(argv) > 128
                or any(not isinstance(v, str) or '\0' in v for v in argv)
                or len(_encoded(argv)) > 65536):
            raise ValueError('invalid bounded worker command')
        executable = PurePosixPath(argv[0])
        if (not executable.is_absolute() or '..' in executable.parts
                or not executable.is_relative_to('/usr/bin')):
            raise ValueError('worker executable must be under the mounted /usr/bin')
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError('invalid worker runtime limit')
        self.argv, self.broker, self.record_event = tuple(argv), broker, record_event
        self.uid, self.gid, self.timeout = uid, gid, timeout

    def _call(self, argv, payload=b'', timeout=5):
        try:
            value = self.broker(tuple(argv), payload, timeout)
        except WorkerTransportError:
            raise
        except Exception as exc:
            raise WorkerTransportError('isolation_broker_failed') from exc
        if not isinstance(value, bytes) or len(value) > 65536:
            raise WorkerTransportError('isolation_broker_invalid_output')
        return value

    def __call__(self, payload):
        return self.run(payload)

    def run(self, payload, *, unit=None, launch_directory=None):
        """Host-selected stable unit is used only with retained task mapping."""
        if sys.platform != 'linux':
            raise WorkerTransportError('unsupported_isolated_worker')
        if not isinstance(payload, bytes) or len(payload) > 4*1024*1024:
            raise WorkerTransportError('worker_input_limit')
        if unit is None:
            unit = 'yeoul-worker-' + uuid.uuid4().hex + '.service'
        if not isinstance(unit, str) or not re.fullmatch(r'yeoul-worker-[0-9a-f]{32}\.service', unit):
            raise WorkerTransportError('invalid_isolated_unit')
        manifest = dict(version=2, unit=unit, uid=self.uid, gid=self.gid, argv=list(self.argv),
            start_ticket=start_ticket(),
            input_sha256=hashlib.sha256(payload).hexdigest(), input_bytes=len(payload),
            limits=dict(cpu_max=[50000, 100000], memory_bytes=134217728, swap_bytes=0,
                        tasks=16, output_bytes=16777216, runtime_seconds=self.timeout,
                        stdout_bytes=65536, stderr_bytes=65536))
        if launch_directory is not None:
            directory = str(launch_directory)
            if (not re.fullmatch(r'/[A-Za-z0-9_./-]+', directory)
                    or '..' in PurePosixPath(directory).parts or directory == '/'):
                raise ValueError('unsupported host launch directory')
            manifest.update(version=3, launch_directory=directory)
        manifest_bytes = _encoded(manifest)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        sequence = 0

        def event(state, **details):
            nonlocal sequence
            sequence += 1
            try:
                self.record_event(_encoded(dict(version=1, unit=unit, sequence=sequence,
                    state=state, manifest_sha256=manifest_hash, **details)))
            except Exception as exc:
                raise WorkerTransportError('isolation_audit_failed') from exc

        show = ['/usr/bin/systemctl', 'show', unit, '--property=LoadState', '--value']
        # Do not touch an existing unit, even if a test or broken UUID source repeats.
        if self._call(show).strip() != b'not-found':
            raise WorkerTransportError('isolation_unit_collision')
        event('prepared', manifest=manifest)
        command = service_command(manifest)
        result, failure = None, None
        event('start_requested')
        try:
            result = self._call(command, payload, self.timeout + 5)
        except WorkerTransportError as exc:
            failure = exc
        finally:
            # Client process-group cleanup alone does not stop systemd-owned jobs.
            # A proposal is withheld until service cleanup has been confirmed.
            stage = 'initial_show'
            try:
                state = self._call(show).strip()
                if state != b'not-found':
                    stage = 'stop'
                    self._call(['/usr/bin/systemctl', '--no-ask-password', 'stop', unit], timeout=8)
                stage = 'final_show'
                if self._call(show).strip() != b'not-found':
                    stage = 'still_loaded'
                    raise WorkerTransportError('isolation_cleanup_incomplete')
            except Exception as exc:
                # Fixed stage only: no exception text, credentials or proposal content.
                event('cleanup_unconfirmed', cleanup_stage=stage)
                raise WorkerTransportError('isolation_cleanup_incomplete') from exc
            # With a failed client call, absence is an observation, not proof that
            # no delayed start request remains in the host's service manager.
            event('cleanup_confirmed' if failure is None else 'cleanup_absence_observed')
        if failure:
            event('held', reason=failure.reason)
            raise failure
        event('returned', output_sha256=hashlib.sha256(result).hexdigest(), output_bytes=len(result))
        return result
