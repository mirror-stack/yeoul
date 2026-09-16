"""Host logical task mapping: durable reservation, result delivery and retirement.

Authorization callback is required for each action, including retained delivery.
No listener, privileged transport, automatic retry, or business approval is added.
"""
import hashlib
import re
import time
import uuid

from . import runtime
from .isolated_worker import IsolatedWorker
from .worker_host import WorkerJournal, ProfileBroker, UNIT, _sha
from .worker_transport import WorkerTransportError
from .worker_storage import admit_storage
from .workspace import checked_path, read_json, write_json, sync_dir


def mapping_path(root, task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', task_id):
        raise ValueError('invalid logical worker task ID')
    name = hashlib.sha256(task_id.encode()).hexdigest() + '.json'
    return checked_path(root / '.yeoul-mcp' / 'worker-tasks' / name)


def load_mapping(root, task_id):
    row = read_json(mapping_path(root, task_id))
    fields = {'version','task_id','unit','profile_sha256','input_sha256','input_bytes','created_ns','sha256'}
    if (not isinstance(row, dict) or set(row) != fields
            or type(row['version']) is not int or row['version'] != 1
            or row['task_id'] != task_id or not isinstance(row['unit'], str) or not UNIT.fullmatch(row['unit'])
            or type(row['created_ns']) is not int or row['created_ns'] <= 0
            or type(row['input_bytes']) is not int or not 0 <= row['input_bytes'] <= 4*1024*1024
            or any(not isinstance(row[k], str) or not re.fullmatch('[0-9a-f]{64}', row[k])
                   for k in ('profile_sha256','input_sha256','sha256'))
            or row['sha256'] != _sha({k:v for k,v in row.items() if k != 'sha256'})):
        raise ValueError('invalid worker task mapping; preserve for inspection')
    return row


def persist_revocation(root, row, note):
    """Trusted host only, under workspace lock; never calls an execution broker."""
    intent = mapping_path(root, row['task_id']).with_suffix('.cancel.json')
    binding = dict(version=1, task_id=row['task_id'], unit=row['unit'], mapping_sha256=row['sha256'])
    if intent.exists():
        previous = read_json(intent)
        if (not isinstance(previous, dict) or set(previous) != set(binding) | {'created_ns', 'note'}
                or type(previous.get('version')) is not int
                or any(previous.get(k) != v for k, v in binding.items())
                or type(previous['created_ns']) is not int or previous['created_ns'] <= 0
                or not isinstance(previous['note'], str) or not 1 <= len(previous['note'].strip()) <= 4096):
            raise ValueError('invalid retained revocation intent')
    else:
        write_json(intent, dict(binding, created_ns=time.time_ns(), note=note))
    gate = WorkerJournal(root).directory(row['unit'])
    gate.parent.mkdir(mode=0o700, exist_ok=True)
    sync_dir(gate.parent.parent)
    gate.mkdir(mode=0o700, exist_ok=True)
    sync_dir(gate.parent)
    marker = gate / 'launch.revoked.json'
    if marker.exists():
        previous = read_json(marker)
        if not isinstance(previous, dict) or type(previous.get('version')) is not int or previous != binding:
            raise ValueError('invalid retained launch revocation')
    else:
        write_json(marker, binding)


class WorkerTasks:
    def __init__(self, root, invoke, *, argv, uid, gid, authorize, timeout=60, max_retained_tasks=1000,
                 metadata_high_water_bytes=256*1024*1024, min_free_bytes=64*1024*1024):
        if not callable(authorize):
            raise ValueError('current host authorization callback required')
        if type(max_retained_tasks) is not int or not 1 <= max_retained_tasks <= 10000:
            raise ValueError('retained task limit must be an integer from 1 to 10000')
        self.max_retained_tasks = max_retained_tasks
        if (type(metadata_high_water_bytes) is not int or not 1 <= metadata_high_water_bytes <= 2**40
                or type(min_free_bytes) is not int or not 0 <= min_free_bytes <= 2**40):
            raise ValueError('invalid host storage admission thresholds')
        self.metadata_high_water_bytes, self.min_free_bytes = metadata_high_water_bytes, min_free_bytes
        self.journal = WorkerJournal(root)
        self.root, self.authorize = self.journal.root, authorize
        self.invoke = invoke
        self.profile = dict(version=1, argv=list(argv), uid=uid, gid=gid, timeout=timeout)
        self.broker = ProfileBroker(self.journal, invoke, argv=argv, uid=uid, gid=gid, timeout=timeout)
        self.worker = IsolatedWorker(argv, broker=self.broker, record_event=self.journal,
                                     uid=uid, gid=gid, timeout=timeout)

    def _permit(self, task_id, action):
        try:
            allowed = self.authorize(task_id, action)
        except Exception as exc:
            raise WorkerTransportError('worker_task_permission_denied') from exc
        if allowed is not True:
            raise WorkerTransportError('worker_task_permission_denied')

    def _path(self, task_id):
        return mapping_path(self.root, task_id)

    def _load(self, task_id):
        return load_mapping(self.root, task_id)

    def _admit_new_task(self, directory):
        """Bound retained logical identities, never delete evidence for capacity.

        Caller holds the workspace lock. This is not a filesystem byte quota.
        All trusted hosts sharing a workspace must use the same admission policy.
        """
        admit_storage(self.root, high_water_bytes=self.metadata_high_water_bytes, min_free_bytes=self.min_free_bytes)
        if not directory.exists():
            return
        retained = set()
        for index, entry in enumerate(directory.iterdir()):
            if index >= self.max_retained_tasks * 4:
                raise WorkerTransportError('worker_retention_limit')
            match = re.fullmatch(r'([0-9a-f]{64})(\.json|\.retired\.json|\.cancel\.json|\.cancellations)', entry.name)
            if not match:
                raise WorkerTransportError('worker_storage_needs_attention')
            checked_path(entry, existing=True)
            if ((match[2] == '.cancellations' and not entry.is_dir())
                    or (match[2] != '.cancellations' and not entry.is_file())):
                raise WorkerTransportError('worker_storage_needs_attention')
            retained.add(match[1])
            if len(retained) >= self.max_retained_tasks:
                raise WorkerTransportError('worker_retention_limit')

    def _retired(self, task_id):
        # Presence alone blocks execution, even if the attestation needs repair.
        return self._path(task_id).with_suffix('.retired.json').exists()

    def _cancelled(self, task_id):
        # Corrupt intent still blocks execution; inspection must preserve it.
        return self._path(task_id).with_suffix('.cancel.json').exists()

    def _cancellation(self, task_id, row):
        """Read-only bounded evidence check; caller holds the workspace lock."""
        path = self._path(task_id)
        intent_path = path.with_suffix('.cancel.json')
        directory = checked_path(path.with_suffix('.cancellations'))
        if not intent_path.exists():
            if directory.exists():
                raise ValueError('cancellation observations without intent')
            return None
        common = {'version', 'task_id', 'unit', 'mapping_sha256', 'created_ns'}
        def validate(value, fields):
            if (not isinstance(value, dict) or set(value) != fields
                    or type(value['version']) is not int or value['version'] != 1
                    or value['task_id'] != task_id or value['unit'] != row['unit']
                    or value['mapping_sha256'] != row['sha256']
                    or type(value['created_ns']) is not int or value['created_ns'] <= 0):
                raise ValueError('invalid cancellation evidence binding')
        intent = read_json(intent_path)
        validate(intent, common | {'note'})
        if not isinstance(intent['note'], str) or not 1 <= len(intent['note'].strip()) <= 4096:
            raise ValueError('invalid cancellation note')
        revoked = self.journal.directory(row['unit']) / 'launch.revoked.json'
        marker = 'missing'
        if revoked.exists():
            value = read_json(revoked)
            expected = dict(version=1, task_id=task_id, unit=row['unit'], mapping_sha256=row['sha256'])
            if (not isinstance(value, dict) or type(value.get('version')) is not int or value != expected):
                raise ValueError('invalid launch revocation evidence')
            marker = 'present'
        attempts = {}
        if directory.exists():
            for index, entry in enumerate(directory.iterdir()):
                match = re.fullmatch(r'([0-9a-f]{32})\.(request|result)\.json', entry.name)
                if index >= 128 or not match:
                    raise ValueError('unexpected or excessive cancellation evidence')
                attempt, kind = match.groups()
                value = read_json(entry)
                fields = common | {'attempt', 'state'}
                if kind == 'result':
                    fields |= {'stage', 'retry_authorized', 'cancellation_complete'}
                validate(value, fields)
                if value['attempt'] != attempt:
                    raise ValueError('cancellation attempt identity differs')
                if kind == 'request':
                    if value['state'] != 'stop_requested':
                        raise ValueError('invalid cancellation request state')
                elif (value['state'] not in ('unconfirmed', 'dispatch_not_reserved', 'absence_observed')
                        or value['stage'] not in ('journal', 'initial_show', 'stop', 'final_show')
                        or value['retry_authorized'] is not False or value['cancellation_complete'] is not False
                        or value['state'] == 'dispatch_not_reserved' and value['stage'] != 'journal'
                        or value['state'] == 'absence_observed' and value['stage'] != 'final_show'):
                    raise ValueError('invalid cancellation observation')
                attempts.setdefault(attempt, {})[kind] = value
        if len(attempts) > 64 or any('request' not in pair for pair in attempts.values()):
            raise ValueError('orphan or excessive cancellation attempts')
        summary = [dict(attempt=attempt,
                        state=pair['result']['state'] if 'result' in pair else 'observation_missing',
                        stage=pair['result']['stage'] if 'result' in pair else None)
                   for attempt, pair in sorted(attempts.items())]
        return dict(status='observations_retained' if summary else 'intent_only', attempts=summary,
                    revocation_marker=marker,
                    unresolved_attempts=sum(a['state'] in ('observation_missing', 'unconfirmed') for a in summary),
                    cancellation_complete=False, retry_authorized=False, read_only=True)

    def _binding(self, row, report):
        if row['profile_sha256'] != _sha(self.profile):
            raise WorkerTransportError('worker_task_profile_changed')
        if report['events']:
            m = report['events'][0]['manifest']
            if (m.get('input_sha256') != row['input_sha256'] or m.get('input_bytes') != row['input_bytes']
                    or m.get('argv') != self.profile['argv'] or m.get('uid') != self.profile['uid']
                    or m.get('gid') != self.profile['gid']
                    or m.get('limits', {}).get('runtime_seconds') != self.profile['timeout']):
                raise ValueError('task mapping and worker evidence differ')

    def _deliver(self, task_id, row, output):
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'execute')
            if self._retired(task_id) or self._cancelled(task_id) or self._load(task_id) != row:
                raise WorkerTransportError('worker_task_retired_or_changed')
            return output

    def execute(self, task_id, payload):
        path = self._path(task_id)
        if not isinstance(payload, bytes) or len(payload) > 4*1024*1024:
            raise WorkerTransportError('worker_input_limit')
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'execute')
            if self._cancelled(task_id):
                raise WorkerTransportError('worker_task_cancel_requested')
            if self._retired(task_id):
                raise WorkerTransportError('worker_task_retired')
            existing = path.exists()
            if existing:
                row = self._load(task_id)
                if (row['profile_sha256'] != _sha(self.profile)
                        or row['input_sha256'] != hashlib.sha256(payload).hexdigest()
                        or row['input_bytes'] != len(payload)):
                    raise WorkerTransportError('worker_task_conflict')
            else:
                self._admit_new_task(path.parent)
                row = dict(version=1, task_id=task_id,
                    unit='yeoul-worker-' + uuid.uuid4().hex + '.service',
                    profile_sha256=_sha(self.profile), input_sha256=hashlib.sha256(payload).hexdigest(),
                    input_bytes=len(payload), created_ns=time.time_ns())
                row['sha256'] = _sha(row)
                path.parent.mkdir(mode=0o700, exist_ok=True)
                sync_dir(path.parent.parent)
                write_json(path, row)
        if existing:
            report = self.journal.inspect(row['unit'])
            self._binding(row, report)
            if report['state'] != 'returned' or report['needs_attention']:
                raise WorkerTransportError('worker_task_needs_attention')
            return self._deliver(task_id, row, self.journal.read_output(row['unit']))
        def guard(unit, manifest):
            # Called under the same lock as dispatch reservation. Retirement before
            # reservation cannot race past this gate; already sent work is different.
            self._permit(task_id, 'execute')
            if self._retired(task_id) or self._cancelled(task_id) or self._load(task_id) != row or unit != row['unit']:
                raise WorkerTransportError('worker_task_retired_or_changed')
        broker = ProfileBroker(self.journal, self.invoke, argv=self.profile['argv'], uid=self.profile['uid'],
            gid=self.profile['gid'], timeout=self.profile['timeout'], dispatch_guard=guard)
        worker = IsolatedWorker(self.profile['argv'], broker=broker, record_event=self.journal,
            uid=self.profile['uid'], gid=self.profile['gid'], timeout=self.profile['timeout'])
        return self._deliver(task_id, row, worker.run(payload, unit=row['unit'],
                             launch_directory=self.journal.directory(row['unit'])))

    def inspect(self, task_id):
        self._path(task_id)
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'inspect')
            row = self._load(task_id)
            retired = self._retired(task_id)
            cancelled = self._cancelled(task_id)
        report = self.journal.inspect(row['unit'])
        self._binding(row, report)
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'inspect')
            if self._load(task_id) != row:
                raise ValueError('task changed during inspection')
            retired, cancelled = self._retired(task_id), self._cancelled(task_id)
            try:
                cancellation = self._cancellation(task_id, row)
            except (OSError, ValueError, TypeError):
                cancellation = dict(status='evidence_unreadable', read_only=True,
                                    cancellation_complete=False, retry_authorized=False)
        return dict(task_id=task_id, unit=row['unit'],
                    state='cancel_requested' if cancelled else ('retired' if retired else report['state']),
                    needs_attention=cancelled or retired or cancellation is not None or report['needs_attention'],
                    retry_authorized=False, cancellation=cancellation,
                    scope='retained worker execution only; not business completion or approval')

    def cancel(self, task_id, *, note, expected_mapping_sha256=None):
        """Persist delivery/dispatch revocation, then request exact-unit stop.

        Absence is an observation, not a fence against an already queued start.
        Repeated calls may repeat stop/observation, never launch or reuse the ID.
        """
        path = self._path(task_id)
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4096:
            raise ValueError('bounded cancellation note required')
        if expected_mapping_sha256 is not None and (not isinstance(expected_mapping_sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', expected_mapping_sha256)):
            raise ValueError('invalid expected cancellation target binding')
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'cancel')
            row = self._load(task_id)
            if expected_mapping_sha256 is not None and row['sha256'] != expected_mapping_sha256:
                raise WorkerTransportError('worker_cancellation_target_changed')
            rows = self.journal._read(row['unit'])
            self._binding(row, {'events': [r['event'] for r in rows]})
            retained = self._cancellation(task_id, row)
            persist_revocation(self.root, row, note.strip())
            directory = checked_path(path.with_suffix('.cancellations'))
            directory.mkdir(mode=0o700, exist_ok=True)
            sync_dir(directory.parent)
            if retained is not None and len(retained['attempts']) >= 64:
                raise ValueError('cancellation observation limit; operator inspection required')
            attempt = uuid.uuid4().hex
            request = dict(version=1, task_id=task_id, unit=row['unit'], attempt=attempt,
                mapping_sha256=row['sha256'], created_ns=time.time_ns(), state='stop_requested')
            write_json(directory / (attempt + '.request.json'), request)
        state, stage = 'unconfirmed', 'journal'
        try:
            report = self.journal.inspect(row['unit'])
            self._binding(row, report)
            if not report['dispatch_reserved']:
                state = 'dispatch_not_reserved'
            else:
                show = ['/usr/bin/systemctl', 'show', row['unit'], '--property=LoadState', '--value']
                stage = 'initial_show'
                if self.worker._call(show).strip() != b'not-found':
                    stage = 'stop'
                    self.worker._call(['/usr/bin/systemctl', '--no-ask-password', 'stop', row['unit']], timeout=8)
                stage = 'final_show'
                if self.worker._call(show).strip() == b'not-found':
                    state = 'absence_observed'
        except Exception:
            # Do not persist arbitrary broker exception text or return a proposal.
            state = 'unconfirmed'
        result = dict(version=1, task_id=task_id, unit=row['unit'], attempt=attempt,
            mapping_sha256=row['sha256'], created_ns=time.time_ns(), state=state, stage=stage,
            retry_authorized=False, cancellation_complete=False)
        with runtime.workspace_lock(self.root):
            if self._load(task_id) != row:
                raise ValueError('task changed during cancellation; preserve request')
            write_json(directory / (attempt + '.result.json'), result)
            # Retain the outcome even if the operator lost access during the call.
            self._permit(task_id, 'cancel')
        return result

    def retire(self, task_id, *, note, children_stopped=False):
        self._path(task_id)
        if children_stopped is not True or not isinstance(note, str) or not 1 <= len(note.strip()) <= 4096:
            raise ValueError('bounded inspection note and stopped-child attestation required')
        with runtime.workspace_lock(self.root):
            self._permit(task_id, 'retire')
            row = self._load(task_id)
            path = self._path(task_id).with_suffix('.retired.json')
            if path.exists():
                return {'task_id': task_id, 'state': 'retired', 'changed': False}
            rows = self.journal._read(row['unit'])
            if rows and rows[-1]['event']['state'] == 'returned':
                raise ValueError('completed result is not an interrupted task to retire')
            write_json(path, dict(version=1, task_id=task_id, unit=row['unit'],
                mapping_sha256=row['sha256'], created_ns=time.time_ns(), note=note.strip(),
                children_stopped_attested=True, scope='operator attestation; no automatic service stop or repair'))
            return {'task_id': task_id, 'state': 'retired', 'changed': True}
