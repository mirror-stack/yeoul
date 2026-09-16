"""Durable local execution journal and request allowlist for a trusted host.

No sudo rules, server, account authentication, automatic retry or installation.
The host owns this metadata outside the worker namespace and supplies authority.
"""
import hashlib
import base64
import json
from pathlib import Path
import re
import time

from . import runtime
from .isolated_worker import IsolatedWorker, _encoded, service_command, check_start
from .workspace import checked_path, read_json, write_json, sync_dir

UNIT = re.compile(r'yeoul-worker-[0-9a-f]{32}\.service\Z')
TRANSITIONS = {None: {'prepared'}, 'prepared': {'start_requested'},
    'start_requested': {'cleanup_confirmed', 'cleanup_absence_observed', 'cleanup_unconfirmed'},
    'cleanup_confirmed': {'returned'}, 'cleanup_absence_observed': {'held'},
    'cleanup_unconfirmed': set(), 'returned': set(), 'held': set()}


def _sha(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _event(value):
    fields = {'version', 'unit', 'sequence', 'state', 'manifest_sha256'}
    # Historical events without a diagnostic remain readable; new diagnostics
    # are a closed vocabulary and never confer cleanup/retry authority.
    if isinstance(value, dict) and value.get('state') == 'cleanup_unconfirmed' and 'cleanup_stage' in value:
        if value['cleanup_stage'] not in ('initial_show', 'stop', 'final_show', 'still_loaded'):
            raise ValueError('invalid worker cleanup stage')
        fields = fields | {'cleanup_stage'}
    extras = {'prepared': {'manifest'}, 'returned': {'output_sha256', 'output_bytes'}, 'held': {'reason'}}
    if (not isinstance(value, dict) or not isinstance(value.get('state'), str)
            or value['state'] not in TRANSITIONS or value['state'] is None
            or set(value) != fields | extras.get(value['state'], set())
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['unit'], str) or not UNIT.fullmatch(value['unit'])
            or type(value['sequence']) is not int or not 1 <= value['sequence'] <= 16
            or not isinstance(value['manifest_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', value['manifest_sha256'])):
        raise ValueError('invalid worker lifecycle event')
    if value['state'] == 'prepared':
        m = value['manifest']
        if (not isinstance(m, dict) or m.get('unit') != value['unit']
                or _sha(m) != value['manifest_sha256']):
            raise ValueError('invalid prepared manifest binding')
    if value['state'] == 'returned':
        if (type(value['output_bytes']) is not int or not 0 <= value['output_bytes'] <= 65536
                or not isinstance(value['output_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', value['output_sha256'])):
            raise ValueError('invalid returned output identity')
    if value['state'] == 'held' and (not isinstance(value['reason'], str) or not 1 <= len(value['reason']) <= 1024):
        raise ValueError('invalid held reason')


class WorkerJournal:
    def __init__(self, root):
        self.root = checked_path(root, existing=True)

    def directory(self, unit):
        if not isinstance(unit, str) or not UNIT.fullmatch(unit):
            raise ValueError('invalid worker unit')
        return checked_path(self.root / '.yeoul-mcp' / 'worker-runs' / unit)

    def _read(self, unit):
        directory = self.directory(unit)
        if not directory.exists():
            return []
        paths = []
        for path in directory.iterdir():
            if path.name in ('dispatch.json', 'output.json', 'launch.json', 'launch.revoked.json'):
                continue
            if not re.fullmatch(r'[0-9]{6}\.json', path.name) or len(paths) >= 16:
                raise ValueError('unexpected worker journal entry; preserve for inspection')
            paths.append(path)
        rows, previous, state, manifest_hash = [], 'genesis', None, None
        for index, path in enumerate(sorted(paths), 1):
            row = read_json(path)
            if (path.name != f'{index:06d}.json' or not isinstance(row, dict)
                    or set(row) != {'version', 'created_ns', 'event', 'previous', 'sha256'}
                    or type(row['version']) is not int or row['version'] != 1
                    or type(row['created_ns']) is not int or row['created_ns'] <= 0
                    or row['previous'] != previous
                    or row['sha256'] != _sha({k: v for k,v in row.items() if k != 'sha256'})):
                raise ValueError('worker journal sequence/integrity failure')
            event = row['event']
            _event(event)
            manifest_hash = manifest_hash or event['manifest_sha256']
            if (event['sequence'] != index or event['unit'] != unit
                    or event['state'] not in TRANSITIONS[state]
                    or event['manifest_sha256'] != manifest_hash):
                raise ValueError('worker journal state/binding failure')
            rows.append(row)
            state, previous = event['state'], row['sha256']
        return rows

    def __call__(self, raw):
        if not isinstance(raw, bytes) or len(raw) > 1024*1024:
            raise ValueError('worker event exceeds limit')
        event = json.loads(raw, object_pairs_hook=runtime.unique_object,
                           parse_constant=runtime.reject_constant)
        _event(event)
        with runtime.workspace_lock(self.root):
            rows = self._read(event['unit'])
            sequence = event['sequence']
            if sequence <= len(rows):
                if rows[sequence-1]['event'] == event:
                    sync_dir(self.directory(event['unit']))
                    return  # Durable delivery retry, never overwrite.
                raise ValueError('worker event conflicts with retained history')
            state = rows[-1]['event']['state'] if rows else None
            if (sequence != len(rows)+1 or event['state'] not in TRANSITIONS[state]
                    or rows and event['manifest_sha256'] != rows[0]['event']['manifest_sha256']):
                raise ValueError('worker event out of order or changed binding')
            directory = self.directory(event['unit'])
            directory.parent.mkdir(mode=0o700, exist_ok=True)
            sync_dir(directory.parent.parent)
            directory.mkdir(mode=0o700, exist_ok=True)
            sync_dir(directory.parent)
            row = dict(version=1, created_ns=time.time_ns(), event=event,
                       previous=rows[-1]['sha256'] if rows else 'genesis')
            row['sha256'] = _sha(row)
            write_json(directory / f'{sequence:06d}.json', row)

    def inspect(self, unit):
        with runtime.workspace_lock(self.root):
            rows = self._read(unit)
            state = rows[-1]['event']['state'] if rows else 'not_recorded'
            path = self.directory(unit) / 'dispatch.json'
            dispatch = read_json(path) if path.exists() else None
            if dispatch is not None:
                if (not rows or not isinstance(dispatch, dict)
                        or set(dispatch) != {'version', 'unit', 'manifest_sha256', 'created_ns'}
                        or type(dispatch['version']) is not int or dispatch['version'] != 1
                        or dispatch['unit'] != unit or type(dispatch['created_ns']) is not int
                        or dispatch['manifest_sha256'] != rows[0]['event']['manifest_sha256']):
                    raise ValueError('invalid dispatch reservation')
            if state == 'returned':
                self._output(unit, rows)
            return dict(unit=unit, state=state, events=[r['event'] for r in rows],
                        dispatch_reserved=dispatch is not None, retry_authorized=False,
                        needs_attention=state != 'returned' or dispatch is None)

    def _output(self, unit, rows):
        if not rows or rows[-1]['event']['state'] != 'returned':
            raise ValueError('output is not available from a completed delivery')
        value = read_json(self.directory(unit) / 'output.json')
        if (not isinstance(value, dict) or set(value) != {'version','unit','manifest_sha256','base64','sha256','bytes'}
                or type(value['version']) is not int or value['version'] != 1
                or value['unit'] != unit or value['manifest_sha256'] != rows[0]['event']['manifest_sha256']
                or not isinstance(value['base64'], str) or len(value['base64']) > 87384
                or type(value['bytes']) is not int or not 0 <= value['bytes'] <= 65536):
            raise ValueError('invalid retained worker output')
        data = base64.b64decode(value['base64'], validate=True)
        last = rows[-1]['event']
        if (len(data) != value['bytes'] or hashlib.sha256(data).hexdigest() != value['sha256']
                or value['sha256'] != last['output_sha256'] or len(data) != last['output_bytes']):
            raise ValueError('retained output differs from the completed event')
        return data

    def read_output(self, unit):
        """Return retained bytes, not renewed approval, source freshness or a rerun."""
        with runtime.workspace_lock(self.root):
            return self._output(unit, self._read(unit))

    def save_output(self, unit, manifest, data):
        if not isinstance(data, bytes) or len(data) > 65536:
            raise ValueError('invalid bounded worker result')
        with runtime.workspace_lock(self.root):
            rows = self._read(unit)
            if (not rows or rows[-1]['event']['state'] != 'start_requested'
                    or rows[0]['event']['manifest'] != manifest
                    or not (self.directory(unit) / 'dispatch.json').exists()):
                raise ValueError('output is not bound to an active dispatch reservation')
            path = self.directory(unit) / 'output.json'
            value = dict(version=1, unit=unit, manifest_sha256=_sha(manifest),
                         base64=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            if path.exists():
                if read_json(path) != value:
                    raise ValueError('retained output conflict; refusing overwrite')
                sync_dir(path.parent)
                return
            write_json(path, value)

    def reserve(self, unit, manifest, guard=None):
        with runtime.workspace_lock(self.root):
            rows = self._read(unit)
            if not rows or rows[-1]['event']['state'] != 'start_requested' or rows[0]['event']['manifest'] != manifest:
                raise ValueError('dispatch requires the current retained start request')
            path = self.directory(unit) / 'dispatch.json'
            if path.exists():
                raise ValueError('dispatch already reserved; do not retry uncertain execution')
            if guard is not None:
                guard(unit, manifest)
            if manifest.get('version') == 3:
                if (self.directory(unit) / 'launch.revoked.json').exists():
                    raise ValueError('launch already revoked')
                permit = self.directory(unit) / 'launch.json'
                if permit.exists():
                    raise ValueError('launch permit already retained; inspect interrupted dispatch')
                write_json(permit, dict(version=1, unit=unit, manifest_sha256=_sha(manifest)))
            write_json(path, dict(version=1, unit=unit, manifest_sha256=_sha(manifest), created_ns=time.time_ns()))


class ProfileBroker:
    """In-process allowlist, not OS authentication or a privileged daemon."""
    def __init__(self, journal, invoke, *, argv, uid, gid, timeout=60, dispatch_guard=None):
        # Use the same platform/command/identity validation as the worker adapter.
        IsolatedWorker(argv, uid=uid, gid=gid, timeout=timeout, broker=invoke, record_event=journal)
        self.journal, self.invoke = journal, invoke
        self.argv, self.uid, self.gid, self.timeout = tuple(argv), uid, gid, timeout
        if dispatch_guard is not None and not callable(dispatch_guard):
            raise ValueError('invalid dispatch authorization guard')
        self.dispatch_guard = dispatch_guard

    def __call__(self, command, payload, timeout):
        if (not isinstance(command, tuple) or not all(isinstance(v, str) for v in command)
                or not isinstance(payload, bytes)):
            raise ValueError('invalid host request')
        if (len(command) == 5 and command[:2] == ('/usr/bin/systemctl', 'show')
                and command[3:] == ('--property=LoadState', '--value')
                and UNIT.fullmatch(command[2]) and payload == b'' and timeout == 5):
            return self.invoke(command, payload, timeout)
        if (len(command) == 4 and command[:3] == ('/usr/bin/systemctl', '--no-ask-password', 'stop')
                and UNIT.fullmatch(command[3]) and payload == b'' and timeout == 8):
            report = self.journal.inspect(command[3])
            manifest = report['events'][0].get('manifest') if report['events'] else None
            if (not report['dispatch_reserved'] or not manifest
                    or manifest.get('argv') != list(self.argv) or manifest.get('uid') != self.uid
                    or manifest.get('gid') != self.gid
                    or manifest.get('limits', {}).get('runtime_seconds') != self.timeout):
                raise ValueError('cannot stop a unit not dispatched by this journal')
            return self.invoke(command, payload, timeout)
        if not command or command[0] != '/usr/bin/systemd-run':
            raise ValueError('host operation is not allowed')
        if not isinstance(command[-1], str) or len(command[-1].encode()) > 1024*1024:
            raise ValueError('invalid service manifest')
        manifest = json.loads(command[-1], object_pairs_hook=runtime.unique_object,
                              parse_constant=runtime.reject_constant)
        expected_limits = dict(cpu_max=[50000,100000], memory_bytes=134217728, swap_bytes=0,
            tasks=16, output_bytes=16777216, runtime_seconds=self.timeout, stdout_bytes=65536, stderr_bytes=65536)
        fields = {'version','unit','uid','gid','argv','input_sha256','input_bytes','limits','start_ticket'}
        if isinstance(manifest, dict) and manifest.get('version') == 3:
            fields.add('launch_directory')
            if manifest.get('launch_directory') != str(self.journal.directory(manifest.get('unit'))):
                raise ValueError('launch directory differs from retained host unit')
        if (not isinstance(manifest, dict) or set(manifest) != fields
                or type(manifest['version']) is not int or manifest['version'] not in (2, 3)
                or type(manifest['uid']) is not int or manifest['uid'] != self.uid
                or type(manifest['gid']) is not int or manifest['gid'] != self.gid
                or manifest['argv'] != list(self.argv) or _encoded(manifest['limits']) != _encoded(expected_limits)
                or type(manifest['input_bytes']) is not int or manifest['input_bytes'] != len(payload)
                or len(payload) > 4*1024*1024 or manifest['input_sha256'] != hashlib.sha256(payload).hexdigest()
                or command != service_command(manifest) or timeout != self.timeout+5):
            raise ValueError('service request differs from the host-approved profile/input')
        def guarded_dispatch(unit, retained_manifest):
            if self.dispatch_guard is not None:
                self.dispatch_guard(unit, retained_manifest)
            check_start(retained_manifest['start_ticket'])
        self.journal.reserve(manifest['unit'], manifest, guarded_dispatch)
        output = self.invoke(command, payload, timeout)
        self.journal.save_output(manifest['unit'], manifest, output)
        return output
