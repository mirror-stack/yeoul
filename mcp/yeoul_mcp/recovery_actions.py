"""Host confirmation boundary for cancellation; no HTTP server or action HTML."""
import secrets
import threading
import time

from . import runtime
from .worker_transport import WorkerTransportError


def _now():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


class RecoveryActions:
    def __init__(self, tasks, *, principal, ttl_seconds=120, max_pending=128):
        if (not callable(principal) or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300
                or type(max_pending) is not int or not 1 <= max_pending <= 1024):
            raise ValueError('trusted identity callback and bounded confirmation policy required')
        self.tasks, self.principal = tasks, principal
        self.ttl_seconds, self.max_pending = ttl_seconds, max_pending
        self._pending, self._lock = {}, threading.Lock()

    def _subject(self):
        try:
            uid = self.principal()
            if type(uid) is not int or not 0 <= uid < 2**31:
                raise ValueError('invalid authenticated account')
            return uid
        except Exception:
            raise WorkerTransportError('recovery_identity_required') from None

    def prepare_cancel(self, task_id, *, note):
        uid = self._subject()
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4096:
            raise ValueError('bounded operator note required')
        with runtime.workspace_lock(self.tasks.root):
            self.tasks._permit(task_id, 'inspect')
            self.tasks._permit(task_id, 'cancel')
            row = self.tasks._load(task_id)
            self.tasks._binding(row, {'events': [r['event'] for r in self.tasks.journal._read(row['unit'])]})
        with self._lock:
            now = _now()
            self._pending = {token: value for token, value in self._pending.items() if now < value['expires']}
            if len(self._pending) >= self.max_pending:
                raise WorkerTransportError('recovery_confirmation_capacity')
            token = secrets.token_urlsafe(32)
            self._pending[token] = dict(uid=uid, task_id=task_id, note=note.strip(),
                mapping=row['sha256'], expires=now + self.ttl_seconds, used=False)
        return dict(action='cancel', task_id=task_id, unit=row['unit'], note=note.strip(), token=token,
                    expires_in_seconds=self.ttl_seconds, requires_confirmation=True, execution_performed=False)

    def confirm_cancel(self, token):
        uid = self._subject()
        if not isinstance(token, str) or len(token) > 128:
            raise WorkerTransportError('recovery_confirmation_invalid')
        with self._lock:
            row = self._pending.get(token)
            if not row or row['uid'] != uid or row['used'] or _now() >= row['expires']:
                raise WorkerTransportError('recovery_confirmation_invalid')
            # Consume before host I/O, including failures; never silently repeat an
            # uncertain operation on a browser double submit or lost response.
            row['used'] = True
            bound = dict(row)
        return self.tasks.cancel(bound['task_id'], note=bound['note'],
                                 expected_mapping_sha256=bound['mapping'])
