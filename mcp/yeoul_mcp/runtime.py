"""Cooperative MCP boundary; business state remains in the harness files.

This is not an OS sandbox. See docs/RUNTIME_CONTRACT.md for trust and recovery.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import errno
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid

CONTEXT = ContextVar('yeoul_runtime', default=None)
LOCK_TIMEOUT = 5.0
SCAN_LIMIT = 20000
_THREAD_LOCK = threading.Lock()
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_RESERVED = {'.yeoul-mcp', '.yeoul-approved'}
WRITE_TOOLS = {'yeoul_new', 'arc_open', 'arc_ticket', 'loop_guard_tick', 'loop_guard_init',
               'arc_close', 'build_handoff', 'arc_prereg', 'verify_gate'}


class Refusal(ValueError):
    pass


def refused(message, code='permission_denied'):
    return dict(exit_code=2, stdout='', stderr=message, runtime_status=code)


def safe_components(path):
    """Reject links (including Windows junctions), special files and hardlink aliases."""
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise Refusal(f'linked path refused: {part}')
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise Refusal(f'special file refused: {part}')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise Refusal(f'hardlinked file refused: {part}')


def sync_dir(path):
    # Windows stdlib cannot fsync a directory. File contents are still flushed.
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, data):
    safe_components(path)
    temp = path.with_name('.tmp-' + uuid.uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal('duplicate receipt key; reconciliation required')
        result[key] = value
    return result


def reject_constant(value):
    raise Refusal('nonfinite receipt value; reconciliation required')


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        reject_constant(value)
    return result


def read_json(path):
    safe_components(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise Refusal('oversized receipt; reconciliation required')
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                      parse_constant=reject_constant, parse_float=finite_float)
    valid = isinstance(data, dict)
    if path.name == 'active.json':
        valid = valid and set(data) == {'receipt'} and isinstance(data['receipt'], str)
        valid = valid and bool(re.fullmatch(r'[0-9a-f]{64}\.json', data['receipt']))
    else:
        required = {'version', 'operation_id', 'fingerprint', 'request', 'state'}
        valid = valid and required <= data.keys() and data.keys() <= required | {'response'}
        if valid:
            valid = (type(data['version']) is int and data['version'] == 1
                     and isinstance(data['operation_id'], str) and bool(_ID.fullmatch(data['operation_id']))
                     and isinstance(data['fingerprint'], str)
                     and isinstance(data['state'], str) and data['state'] in ('pending', 'complete')
                     and isinstance(data['request'], dict))
        if valid:
            request = data['request']
            valid = (set(request) == {'version', 'tool', 'arguments', 'root', 'cwd', 'environment'}
                     and type(request['version']) is int and request['version'] == 1
                     and isinstance(request['tool'], str) and request['tool'] in WRITE_TOOLS
                     and isinstance(request['arguments'], dict)
                     and isinstance(request['root'], str) and isinstance(request['cwd'], str)
                     and isinstance(request['environment'], dict)
                     and all(isinstance(v, str) for v in request['environment'].values())
                     and request['arguments'].get('operation_id') == data['operation_id'])
            if valid:
                digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
                                                   allow_nan=False).encode('utf-8')).hexdigest()
                valid = (data['fingerprint'] == digest and path.name ==
                         hashlib.sha256(data['operation_id'].encode()).hexdigest() + '.json')
        if valid and data['state'] == 'complete':
            response = data.get('response')
            valid = (isinstance(response, dict) and {'exit_code', 'stdout', 'stderr'} <= response.keys()
                     and response.keys() <= {'exit_code', 'stdout', 'stderr', 'output_truncated'}
                     and type(response['exit_code']) is int and isinstance(response['stdout'], str)
                     and isinstance(response['stderr'], str)
                     and type(response.get('output_truncated', False)) is bool)
        elif valid:
            valid = 'response' not in data
    if not valid:
        raise Refusal('invalid receipt schema/integrity; reconciliation required')
    return data


@contextmanager
def workspace_lock(root):
    """One persistent inode, kernel locking, bounded wait; never delete a stale PID lock."""
    deadline = time.monotonic() + LOCK_TIMEOUT
    if not _THREAD_LOCK.acquire(timeout=LOCK_TIMEOUT):
        raise Refusal('workspace busy; lock wait expired')
    try:
        control = root / '.yeoul-mcp'
        safe_components(control)
        control.mkdir(exist_ok=True, mode=0o700)
        info = control.stat()
        if os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise Refusal('control directory must be owned by the server user with mode 0700')
        sync_dir(root)
        path = control / 'workspace.lock'
        safe_components(path)
        with path.open('a+b') as stream:
            if not path.stat().st_size:
                stream.write(b'\0')
                stream.flush()
            locked = False
            try:
                while not locked:
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if time.monotonic() >= deadline:
                            raise Refusal('workspace busy; lock wait expired') from exc
                        time.sleep(0.025)
                yield control
            finally:
                if locked:
                    if os.name == 'nt':
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        _THREAD_LOCK.release()


class Policy:
    def __init__(self, values):
        raw = os.environ.get('YEOUL_MCP_ROOT')
        self.managed = raw is not None
        self.env = dict(os.environ)
        if self.managed:
            if not raw or not Path(raw).is_absolute() or '..' in Path(raw).parts:
                raise Refusal('YEOUL_MCP_ROOT must be an explicit absolute existing directory')
            self.root = Path(raw)
            safe_components(self.root)
            if not self.root.is_dir():
                raise Refusal('YEOUL_MCP_ROOT must be an existing directory')
            self.root = self.root.resolve()
            if self.root.parent == self.root:
                raise Refusal('filesystem root cannot be a managed workspace')
            self.cwd = self.path(values.get('workspace', '.'))
            if not self.cwd.is_dir():
                raise Refusal('workspace must be an existing directory within YEOUL_MCP_ROOT')
        else:
            self.cwd = Path(values.get('workspace', os.getcwd())).absolute()
            self.root = Path.cwd().resolve()

    def path(self, raw, *, base=None, approved=False, external_read=False):
        if not raw or any(ord(c) < 32 for c in raw) or '\\' in raw:
            # Accept native Windows absolute paths, but never ambiguous relative backslash paths.
            if not (os.name == 'nt' and Path(raw).is_absolute()
                    and not any(ord(c) < 32 for c in raw)):
                raise Refusal('empty, control-character or ambiguous path refused')
        path = Path(raw)
        if '..' in path.parts or (os.name != 'nt' and ':' in raw):
            raise Refusal('path traversal or alternate path syntax refused')
        path = path if path.is_absolute() else (base or self.root) / path
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            if external_read:
                grants = json.loads(self.env.get('YEOUL_MCP_READ_LEDGERS', '[]'))
                if (not isinstance(grants, list) or len(grants) > 100 or
                        any(not isinstance(p, str) or not Path(p).is_absolute() for p in grants)):
                    raise Refusal('invalid external ledger grants')
                if str(path) in grants:
                    safe_components(path)
                    if path.is_file():
                        return path
            raise Refusal('path outside YEOUL_MCP_ROOT') from exc
        for part in relative.parts:
            if ':' in part or part.endswith((' ', '.')):
                raise Refusal('ambiguous path component refused')
        if '.yeoul-workspace.json' in relative.parts:
            raise Refusal('workspace profile is not a business target')
        if any(p in _RESERVED for p in relative.parts) and not approved:
            raise Refusal('reserved runtime/approval path refused')
        safe_components(path)
        return path

    def validate(self, tool, values):
        if not self.managed:
            return
        for key in ('name', 'slug', 'role', 'relay'):
            if key in values and not _NAME.fullmatch(values[key]):
                raise Refusal(f'{key} must be 1-128 ASCII letters/digits/underscore/hyphen, starting alphanumeric')
        if 'roles' in values and (not values['roles'].split(' ') or
                any(not _NAME.fullmatch(role) for role in values['roles'].split(' '))):
            raise Refusal('roles must be space-separated safe names')
        for key, choices in [('backend', {'a', 'b', 'both'}),
                             ('stop', {'converged', 'falsified', 'no-progress'})]:
            if key in values and values[key] not in choices:
                raise Refusal(f'invalid {key}')
        for key in ('arc_dir', 'arcs_dir', 'todo_path', 'ledger'):
            if values.get(key):
                values[key] = str(self.path(values[key], base=self.cwd, external_read=key == 'ledger'))
        if tool == 'arc_close':
            arc = Path(values['arc_dir'])
            self.path(str(arc.parent / '_archive' / arc.name))
        if 'workspace' in values:
            values['workspace'] = str(self.cwd)
        # Defaults must not fall back to package paths or the server's launch cwd.
        defaults = {'YEOUL_PROJECTS': 'projects', 'YEOUL_INDEX': 'KNOWLEDGE_INDEX.md',
                    'YEOUL_CLOSED_REGISTRY': 'registry/closed_questions.jsonl'}
        for key, default in defaults.items():
            self.env[key] = str(self.path(self.env.get(key) or default, base=self.cwd))
        if self.env.get('YEOUL_LEDGER'):
            self.env['YEOUL_LEDGER'] = str(self.path(self.env['YEOUL_LEDGER'], base=self.cwd, external_read=True))
        # Fixed harness code may run; arbitrary shell commands have a separate capability.
        self.env['YEOUL_MCP_MANAGED'] = '1'
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        for key in ('BASH_ENV', 'ENV', 'CDPATH', 'PYTHONPATH', 'PYTHONSTARTUP',
                    'SHELLOPTS', 'BASHOPTS', 'GLOBIGNORE', 'IFS'):
            self.env.pop(key, None)
        self.env = {k: v for k, v in self.env.items() if not k.startswith('BASH_FUNC_')}
        if tool == 'verify_gate':
            if self.env.get('YEOUL_MCP_ALLOW_EXEC') != '1':
                raise Refusal('verification executes arbitrary commands; YEOUL_MCP_ALLOW_EXEC=1 required')
            approved = self.env.get('YEOUL_MCP_VERIFY_BASELINE', '')
            if not approved or not Path(approved).is_absolute():
                raise Refusal('supervisor must configure absolute YEOUL_MCP_VERIFY_BASELINE')
            baseline = self.path(approved, approved=True)
            if not baseline.is_relative_to(self.root / '.yeoul-approved') or not baseline.is_file():
                raise Refusal('approved baseline must be an existing file under root/.yeoul-approved')
            approved_hash = self.env.get('YEOUL_MCP_VERIFY_BASELINE_SHA256')
            if approved_hash is not None and hashlib.sha256(baseline.read_bytes()).hexdigest() != approved_hash:
                raise Refusal('approved baseline changed; operator re-approval required')
            if values.get('baseline_path') and self.path(values['baseline_path'], base=self.cwd,
                                                        approved=True) != baseline:
                raise Refusal('baseline differs from supervisor-approved baseline')
            values['baseline_path'] = str(baseline)
        # A bounded conservative scan covers implicit script globs, archive destinations,
        # .prereg references, and children of explicit paths. No symlink following.
        deadline = time.monotonic() + 5
        stack, count = [self.root], 0
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > SCAN_LIMIT or time.monotonic() > deadline:
                        raise Refusal('workspace safety scan limit exceeded (20000 entries / 5 seconds)')
                    path = Path(entry.path)
                    safe_components(path)
                    if path == self.root / '.yeoul-mcp':
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if path.name == '.yeoul-mcp':
                            raise Refusal('overlapping managed workspace roots refused')
                        stack.append(path)
                    elif path.name == '.prereg':
                        if path.stat().st_size > 65536:
                            raise Refusal('oversized .prereg')
                        lines = path.read_text(encoding='utf-8').splitlines()
                        if len(lines) >= 2:
                            self.path(lines[1], base=self.cwd, external_read=True)
        for ancestor in self.root.parents:
            if (ancestor / '.yeoul-mcp').exists():
                raise Refusal('overlapping managed workspace roots refused')


def boundary(*, mutating=False):
    """Preserve the actual tool signature so FastMCP exposes operation_id."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = dict(bound.arguments)
            operation_id = values.get('operation_id')
            armed = False
            checking_receipts = False
            try:
                policy = Policy(values)
                if mutating and policy.managed:
                    if policy.env.get('YEOUL_MCP_ALLOW_WRITE') != '1':
                        raise Refusal('YEOUL_MCP_ALLOW_WRITE=1 required')
                    if not operation_id:
                        raise Refusal('operation_id required for managed mutations')
                    if function.__name__ == 'verify_gate' and policy.env.get('YEOUL_MCP_ALLOW_EXEC') != '1':
                        raise Refusal('YEOUL_MCP_ALLOW_EXEC=1 required for verification')
                    allowlist = policy.env.get('YEOUL_MCP_WRITE_TOOLS')
                    if allowlist is not None:
                        allowed = {name.strip() for name in allowlist.split(',') if name.strip()}
                        if allowed - WRITE_TOOLS or function.__name__ not in allowed:
                            raise Refusal('tool denied by YEOUL_MCP_WRITE_TOOLS (comma-separated tool names)')
                if operation_id is not None and not _ID.fullmatch(operation_id):
                    raise Refusal('invalid operation_id (1-128 ASCII identifier characters)')
                if not policy.managed:
                    if operation_id is not None:
                        raise Refusal('operation_id requires managed mode (YEOUL_MCP_ROOT)')
                    return function(**values)
                request = dict(version=1, tool=function.__name__, arguments=dict(values),
                               root=str(policy.root), cwd=str(policy.cwd),
                               environment={k: v for k, v in policy.env.items()
                                            if k.startswith('YEOUL_') and k not in
                                            ('YEOUL_MCP_ALLOW_WRITE', 'YEOUL_MCP_ALLOW_EXEC',
                                             'YEOUL_MCP_WRITE_TOOLS')})
                encoded = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
                if len(encoded) > 1024 * 1024:
                    raise Refusal('operation arguments/context exceed 1 MiB')
                fingerprint = hashlib.sha256(encoded).hexdigest()
                with workspace_lock(policy.root) as control:
                    # Recheck current paths/approvals even for a completed replay. Paths may be
                    # absent after archive; validate containment and links, not business existence.
                    policy.validate(function.__name__, values)
                    checking_receipts = True
                    receipt = control / (hashlib.sha256(operation_id.encode()).hexdigest() + '.json') if operation_id else None
                    if receipt and (control / 'recovery' / receipt.name).exists():
                        return refused('retired operation cannot be retried', 'reconciliation_required')
                    if receipt and receipt.exists():
                        old = read_json(receipt)
                        if old['fingerprint'] != fingerprint:
                            return refused('operation_id already used with different arguments/context', 'operation_conflict')
                        if old['state'] == 'complete':
                            return old['response']
                        return refused('operation pending/ambiguous; reconciliation required; do not retry with a new ID',
                                       'reconciliation_required')
                    active = control / 'active.json'
                    if active.exists():
                        marker = read_json(active)
                        active_id = marker['receipt']
                        if not re.fullmatch(r'[0-9a-f]{64}\.json', active_id):
                            raise Refusal('invalid active receipt; reconciliation required')
                        if read_json(control / active_id)['state'] != 'complete':
                            return refused('workspace has a pending/ambiguous operation; reconciliation required',
                                           'reconciliation_required')
                    checking_receipts = False
                    if receipt:
                        record = dict(version=1, operation_id=operation_id, fingerprint=fingerprint,
                                      request=request, state='pending')
                        armed = True
                        # Active first: even a crash before receipt creation blocks new IDs.
                        # A pointer to a missing receipt requires supervisor reconciliation.
                        write_json(active, {'receipt': receipt.name})
                        write_json(receipt, record)
                    token = CONTEXT.set(policy)
                    try:
                        response = function(**values)
                    finally:
                        CONTEXT.reset(token)
                    # A killed/timed-out child may have committed part of its work. Never retry it.
                    if receipt and (response['exit_code'] < 0 or response['exit_code'] >= 128
                                    or response['exit_code'] in (124, 127)
                                    or response.get('runtime_status') == 'ambiguous'):
                        return refused('operation interrupted or launch outcome uncertain; reconciliation required',
                                       'reconciliation_required')
                    if receipt:
                        # Match FastMCP's text serialization on the first response and replay.
                        response = json.loads(json.dumps(response, sort_keys=True, ensure_ascii=False,
                                                         allow_nan=False))
                        record.update(state='complete', response=response)
                        write_json(receipt, record)
                    return response
            except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                return refused(str(exc) + '; inspect pending receipts before retrying',
                               'reconciliation_required' if armed or checking_receipts else 'permission_denied')
        return wrapped
    return decorate
