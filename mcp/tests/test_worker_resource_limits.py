"""Opt-in host resource tests; temporary systemd units, synthetic code only.

Requires explicit approval to configure transient services. Never change existing
units, controller delegation, host file modes, accounts, packages or production.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid


PAYLOAD = r'''
import errno, json, os, signal, sys, time, subprocess, socket
from pathlib import Path
case = sys.argv[1]
relative = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                if line.startswith('0::'))
group = Path('/sys/fs/cgroup') / relative.lstrip('/')
assert group.name.startswith('yeoul-resource-test-') and group.name.endswith('.service'), relative
assert os.getuid() != 0, 'test payload must not run as root'
quota, period = map(int, (group/'cpu.max').read_text().split())
assert quota / period == 0.5, (quota, period)
assert int((group/'memory.max').read_text()) == 128*1024*1024
assert int((group/'memory.swap.max').read_text()) == 0
assert int((group/'pids.max').read_text()) == 16
def counters(name):
    return {k: int(v) for k,v in (line.split() for line in (group/name).read_text().splitlines())}
result = dict(case=case, cgroup=relative, uid=os.getuid(), cpu_max=[quota, period],
              memory_max=128*1024*1024, swap_max=0, pids_max=16)
if case == 'cpu':
    before = counters('cpu.stat')
    started = time.monotonic()
    until = time.process_time() + 0.8
    while time.process_time() < until:
        pass
    after = counters('cpu.stat')
    result.update(wall_seconds=time.monotonic()-started,
                  throttled_periods=after['nr_throttled']-before['nr_throttled'],
                  throttled_usec=after['throttled_usec']-before['throttled_usec'])
    assert result['throttled_periods'] > 0 and result['throttled_usec'] > 0, result
elif case == 'memory':
    before = counters('memory.events')
    pid = os.fork()
    if pid == 0:
        # Touch pages; virtual address reservation alone would not test memory.max.
        chunks = []
        while True:
            chunks.append(bytearray(4*1024*1024))
    _, status = os.waitpid(pid, 0)
    after = counters('memory.events')
    result.update(child_signal=os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
                  oom_kills=after['oom_kill']-before['oom_kill'])
    assert result['child_signal'] == signal.SIGKILL and result['oom_kills'] >= 1, result
elif case == 'pids':
    before = counters('pids.events')
    children = []
    read_fd, write_fd = os.pipe()
    try:
        for _ in range(32):
            try:
                pid = os.fork()
            except OSError as exc:
                assert exc.errno == errno.EAGAIN, exc
                result['fork_denied'] = True
                break
            if pid == 0:
                os.close(write_fd)
                os.read(read_fd, 1)
                os._exit(0)
            children.append(pid)
        else:
            raise AssertionError('pids limit was not enforced')
        result.update(children_started=len(children), pids_current=int((group/'pids.current').read_text()),
                      limit_events=counters('pids.events')['max']-before['max'])
        assert result['pids_current'] <= 16 and result['limit_events'] > 0, result
    finally:
        os.close(write_fd)
        os.close(read_fd)
        for pid in children:
            os.waitpid(pid, 0)
elif case == 'disk':
    fs = os.statvfs('/tmp')
    result['tmpfs_capacity'] = fs.f_blocks * fs.f_frsize
    assert result['tmpfs_capacity'] == 16*1024*1024, result
    written = 0
    try:
        with open('/tmp/synthetic-fill', 'wb', buffering=0) as stream:
            for _ in range(24):
                written += stream.write(b'x' * (1024*1024))
        raise AssertionError('tmpfs capacity was not enforced')
    except OSError as exc:
        assert exc.errno == errno.ENOSPC, exc
        result.update(write_denied=True, bytes_written=written)
    finally:
        Path('/tmp/synthetic-fill').unlink(missing_ok=True)
elif case == 'isolation':
    for name in ('input', 'output', 'hidden'):
        Path('/tmp', name).mkdir()
    source = Path('/tmp/input/observations.json')
    source.write_text('[4,7,6]')
    secret = Path('/tmp/hidden/marker')
    secret.write_text('synthetic-private')
    inner = """
import json, os, socket, sys
from pathlib import Path
assert Path('/limits/memory.max').read_text().strip() == '134217728'
assert Path('/limits/pids.max').read_text().strip() == '16'
assert Path('/limits/cpu.max').read_text().strip() == '50000 100000'
assert not Path('/tmp/hidden/marker').exists()
assert not Path('/home').exists()
assert os.readlink('/proc/self/ns/net') != sys.argv[2]
try:
    Path('/input/observations.json').write_text('changed')
except OSError:
    pass
else:
    raise AssertionError('source must be read-only')
assert os.statvfs('/work').f_blocks * os.statvfs('/work').f_frsize == 16*1024*1024
with socket.socket() as sock:
    sock.settimeout(0.1)
    try:
        sock.connect(('127.0.0.1', int(sys.argv[1])))
    except OSError:
        pass
    else:
        raise AssertionError('unexpected endpoint')
proposal = dict(total=sum(json.loads(Path('/input/observations.json').read_text())))
Path('/work/proposal.json').write_text(json.dumps(proposal))
print(json.dumps(proposal))
"""
    command = ['/usr/bin/bwrap', '--unshare-user', '--unshare-pid', '--unshare-net',
        '--unshare-ipc', '--unshare-uts', '--die-with-parent', '--new-session',
        '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
        '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib',
        '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev',
        '--ro-bind', str(group), '/limits', '--ro-bind', '/tmp/input', '/input',
        '--bind', '/tmp/output', '/work', '--chdir', '/work']
    if Path('/lib64').exists():
        command += ['--ro-bind', '/lib64', '/lib64']
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        command += ['--', '/usr/bin/python3', '-I', '-B', '-c', inner,
                    str(listener.getsockname()[1]), os.readlink('/proc/self/ns/net')]
        isolated = subprocess.run(command, capture_output=True, text=True, timeout=8)
    assert isolated.returncode == 0, isolated.stdout + isolated.stderr
    assert json.loads(isolated.stdout) == {'total': 17}
    assert json.loads(Path('/tmp/output/proposal.json').read_text()) == {'total': 17}
    assert source.read_text() == '[4,7,6]' and secret.read_text() == 'synthetic-private'
    result.update(isolated_proposal=17, source_preserved=True, output_capacity=16*1024*1024)
else:
    raise AssertionError('unknown case')
print(json.dumps(result), flush=True)
'''


@unittest.skipUnless(os.environ.get('YEOUL_RUN_RESOURCE_TESTS') == '1',
                     'requires explicit transient resource-test approval')
class ResourceLimits(unittest.TestCase):
    def test_actual_cpu_memory_process_and_storage_enforcement(self):
        if sys.platform != 'linux' or any(shutil.which(name) is None for name in ('systemd-run', 'systemctl', 'sudo')):
            self.skipTest('requires existing Linux systemd and sudo')
        self.assertNotEqual(os.getuid(), 0, 'invoke test as the normal approved user')
        self.assertTrue(Path('/usr/bin/python3').is_file())
        self.assertTrue(Path('/usr/bin/bwrap').is_file())
        for case in ('cpu', 'memory', 'pids', 'disk', 'isolation'):
            with self.subTest(case=case):
                unit = 'yeoul-resource-test-' + uuid.uuid4().hex + '.service'
                properties = ['CPUQuota=50%', 'CPUQuotaPeriodSec=100ms', 'MemoryMax=128M',
                    'MemorySwapMax=0', 'TasksMax=16', 'RuntimeMaxSec=15s', 'TimeoutStopSec=3s',
                    'KillMode=control-group', 'OOMPolicy=continue', 'NoNewPrivileges=yes',
                    'ProtectSystem=strict', 'ProtectHome=yes', 'ProtectControlGroups=yes', 'PrivateNetwork=yes',
                    'TemporaryFileSystem=/tmp:rw,size=16M,mode=1777', 'UMask=0077']
                command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                           '--service-type=exec', '--unit=' + unit, '--uid=' + str(os.getuid()),
                           '--gid=' + str(os.getgid()), '--working-directory=/tmp']
                for value in properties:
                    command += ['--property=' + value]
                command += ['/usr/bin/python3', '-I', '-B', '-c', PAYLOAD, case]
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=25)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    report = json.loads(result.stdout)
                    self.assertEqual(report['case'], case)
                    self.assertEqual(report['uid'], os.getuid())
                    print(json.dumps(report, sort_keys=True), flush=True)
                finally:
                    # Exact newly generated unit only. No reset/stop of existing units.
                    state = subprocess.run(['systemctl', 'show', unit, '--property=LoadState', '--value'],
                                           capture_output=True, text=True, timeout=5)
                    if state.stdout.strip() != 'not-found':
                        stopped = subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit],
                                                 capture_output=True, text=True, timeout=8)
                        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
                    state = subprocess.run(['systemctl', 'show', unit, '--property=LoadState', '--value'],
                                           capture_output=True, text=True, timeout=5)
                    self.assertEqual(state.stdout.strip(), 'not-found', state.stdout + state.stderr)


if __name__ == '__main__':
    unittest.main()
