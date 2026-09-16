"""Linux local-peer identity and host-owned per-task access policy.

This is a connection boundary, not a listener, sudo policy or deployed service.
Only a trusted host may configure grants; request data never supplies identity.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import socket
import struct
import sys
import uuid

from . import runtime
from .workspace import checked_path, read_json, write_json, sync_dir, canonical
from .worker_tasks import mapping_path, load_mapping, persist_revocation

ACTIONS = frozenset(('execute', 'inspect', 'retire', 'cancel'))
TASK = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')


def _grants(grants):
    if not isinstance(grants, dict) or len(grants) > 1000:
        raise ValueError('invalid bounded worker grants')
    for task, row in grants.items():
        if (not isinstance(task, str) or not TASK.fullmatch(task)
                or not isinstance(row, dict) or set(row) != {'uid', 'actions'}
                or type(row['uid']) is not int or not 0 <= row['uid'] < 2**31
                or not isinstance(row['actions'], list) or not 1 <= len(row['actions']) <= len(ACTIONS)
                or any(not isinstance(a, str) or a not in ACTIONS for a in row['actions'])
                or len(set(row['actions'])) != len(row['actions'])):
            raise ValueError('invalid worker task owner/action grant')
    if len(canonical(grants).encode()) > 1024*1024:
        raise ValueError('worker grants exceed size limit')


class WorkerAccess:
    def __init__(self, root):
        self.root = checked_path(root, existing=True)
        self.control = self.root / '.yeoul-mcp'
        self.path = self.control / 'worker-access.json'
        self._lease = ContextVar('yeoul_worker_access_' + uuid.uuid4().hex, default=None)

    def _read(self):
        checked_path(self.path, existing=True)
        control, info = self.control.stat(), self.path.stat()
        if (sys.platform != 'linux' or control.st_uid != os.geteuid()
                or control.st_mode & 0o077 or info.st_uid != os.geteuid() or info.st_mode & 0o022
                or info.st_size > 1024*1024):
            raise ValueError('worker access policy must be owned/protected by the host account')
        value = read_json(self.path)
        if (not isinstance(value, dict) or set(value) != {'version','revision','grants'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['revision'], str) or not re.fullmatch('[0-9a-f]{32}', value['revision'])):
            raise ValueError('invalid worker access policy')
        _grants(value['grants'])
        return value

    def configure(self, grants, *, expected_revision=None):
        """Trusted operator action only; never expose through the worker connection."""
        if sys.platform != 'linux':
            raise ValueError('worker peer access requires Linux')
        _grants(grants)
        with runtime.workspace_lock(self.root):
            old = self._read() if self.path.exists() else None
            if expected_revision != (old['revision'] if old else None):
                raise ValueError('worker access revision changed; re-read before configuring')
            if old:
                history = checked_path(self.control / 'history')
                history.mkdir(mode=0o700, exist_ok=True)
                sync_dir(self.control)
                saved = history / ('worker-access-' + old['revision'] + '.json')
                if saved.exists():
                    if read_json(saved) != old:
                        raise ValueError('worker access history conflict; preserve evidence')
                else:
                    write_json(saved, old)
                affected = []
                for task, before in old['grants'].items():
                    after = grants.get(task)
                    if ('execute' in before['actions'] and
                            (after is None or after['uid'] != before['uid'] or 'execute' not in after['actions'])
                            and mapping_path(self.root, task).exists()):
                        affected.append(load_mapping(self.root, task))
                # Write revocation before replacing policy. Partial failure leaves
                # conservative retained holds, never silently re-arms a task.
                for row in affected:
                    persist_revocation(self.root, row, 'Execution withdrawn from host policy revision ' + old['revision'])
            value = dict(version=1, revision=uuid.uuid4().hex, grants=grants)
            write_json(self.path, value)
            return value['revision']

    @staticmethod
    def _identity(connection):
        if (sys.platform != 'linux' or not isinstance(connection, socket.socket)
                or connection.family != socket.AF_UNIX
                or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
            raise ValueError('connected Linux UNIX stream socket required')
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
        pid, uid, gid = struct.unpack('3i', raw)
        if pid <= 0 or uid < 0 or gid < 0:
            raise ValueError('invalid kernel peer credentials')
        return pid, uid, gid

    @contextmanager
    def connection(self, connection):
        """Scope a host request to kernel-established connection credentials."""
        lease = dict(connection=connection, identity=self._identity(connection), active=True)
        token = self._lease.set(lease)
        try:
            yield  # No caller-controlled UID or identity override.
        finally:
            lease['active'] = False  # Also invalidates copies held by copied contexts.
            self._lease.reset(token)

    def authorize(self, task_id, action):
        lease = self._lease.get()
        if not lease or not lease['active'] or action not in ACTIONS:
            return False
        try:
            identity = self._identity(lease['connection'])
            if identity != lease['identity']:
                return False
            grant = self._read()['grants'].get(task_id)
            return bool(grant and grant['uid'] == identity[1] and action in grant['actions'])
        except (OSError, ValueError, TypeError):
            return False

    def subject(self):
        """Host-only authenticated account identity for a live connection scope."""
        lease = self._lease.get()
        if not lease or not lease['active']:
            raise ValueError('no authenticated worker connection')
        identity = self._identity(lease['connection'])
        if identity != lease['identity']:
            raise ValueError('worker connection identity changed')
        return identity[1]
