"""Host-only bridge to prepared writes; never a verifier or an MCP approval tool.

The host callback must fetch current authenticated reports and explicit approval.
Only cooperating host processes are covered by the workspace lock. Hashes bind
content, not identity. A hostile same-account writer remains outside this boundary.
"""
from contextvars import ContextVar
import hashlib
import json
import re
import time
import uuid

from .review_decision import decide

_HOST = ContextVar('yeoul_review_host', default=None)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def check_review(review):
    if (not isinstance(review, dict) or set(review) != {'proposal', 'requirements'}
            or not isinstance(review['proposal'], dict) or len(_bytes(review)) > 65536):
        raise ValueError('invalid bounded host review contract')
    decide(dict(task_id='shape', target='shape', revision='shape',
                proposal_sha256=_digest(review['proposal'])), review['requirements'], [])


def binding(job):
    """Bind the actual prepared tool/arguments/snapshot AND host review contract."""
    check_review(job['review'])
    return dict(task_id=job['id'],
                target=_digest(dict(tool=job['tool'], arguments=job['arguments'])),
                revision=job['digest'], proposal_sha256=_digest(job['review']['proposal']))


def _save_audit(control, event):
    from . import runtime
    directory = control / 'reviews'
    runtime.safe_components(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    runtime.sync_dir(control)
    name = uuid.uuid4().hex + '.json'
    path = directory / name
    if path.exists():
        raise ValueError('review event ID collision; refusing overwrite')
    runtime.write_json(path, event)
    return dict(name=name, sha256=_digest(event))


def validate_audit(control, reference, request):
    """Check the retained approval record when reading a linked receipt."""
    from .workspace import read_json
    if (not isinstance(reference, dict) or set(reference) != {'name', 'sha256'}
            or not isinstance(reference['name'], str)
            or not re.fullmatch('[0-9a-f]{32}\\.json', reference['name'])
            or not isinstance(reference['sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', reference['sha256'])):
        raise ValueError('invalid review audit reference')
    event = read_json(control / 'reviews' / reference['name'])
    if (not isinstance(event, dict) or _digest(event) != reference['sha256']
            or set(event) != {'version', 'created_ns', 'binding', 'requirements',
                             'approved', 'reports', 'decision', 'error'}
            or type(event['version']) is not int or event['version'] != 1
            or type(event['created_ns']) is not int or event['created_ns'] <= 0
            or event['approved'] is not True or event['error'] is not None):
        raise ValueError('review audit missing or invalid; reconciliation required')
    expected = event['binding']
    decision = decide(expected, event['requirements'], event['reports'])
    # Actual argument defaults are checked against the job at dispatch; the audit
    # uses the prepared argument form, whose complete job digest is in the request.
    if (expected.get('task_id') != request['arguments']['operation_id']
            or expected.get('revision') != request.get('review_digest')):
        raise ValueError('review audit belongs to another task')
    if decision != event['decision'] or decision['state'] != 'ready_for_review':
        raise ValueError('review audit does not authorize this execution')


def authorize(job, control):
    host = _HOST.get()
    if host is None or host[0] != job['id']:
        raise ValueError('reviewed execution requires the trusted host approval callback')
    current = binding(job)
    # Immutable input; a callback cannot mutate the task or the runtime request.
    # Disable nested use of this capability, including recursive tool calls.
    token = _HOST.set(None)
    error = None
    result = None
    try:
        result = host[1](_bytes(dict(job=job, binding=current)))
        raw = _bytes(result)
        if len(raw) > 1024 * 1024:
            raise ValueError('oversized host response')
        result = json.loads(raw)
        if (not isinstance(result, dict) or set(result) != {'approved', 'reports'}
                or type(result['approved']) is not bool):
            raise ValueError('invalid host approval response')
        decision = decide(current, job['review']['requirements'], result['reports'])
    except Exception:
        # Do not retain arbitrary exception messages or malformed host payloads.
        error = 'host_review_unavailable_or_invalid'
        result = {'approved': False, 'reports': []}
        decision = decide(current, job['review']['requirements'], [])
    finally:
        _HOST.reset(token)
    reference = _save_audit(control, dict(version=1, created_ns=time.time_ns(),
        binding=current, requirements=job['review']['requirements'],
        approved=result['approved'], reports=result['reports'], decision=decision, error=error))
    if error or not result['approved'] or decision['state'] != 'ready_for_review':
        raise ValueError('approval absent or current verification does not pass')
    return reference


def execute_reviewed(workspace, root, task_id, host):
    """Call existing execution, checking fresh host reports inside its write lock.

    Callback receives immutable JSON {job, binding}; returns {approved: bool,
    reports: list}. Host must bound its own I/O, authenticate providers, and handle
    revocation ordering. This API is not exposed to workers or through MCP.
    """
    if not callable(host):
        raise ValueError('trusted host callback required')
    job = workspace.load_job(root, task_id)
    if job['schema'] != 3:
        raise ValueError('task is not review-bound')
    token = _HOST.set((task_id, host))
    try:
        return workspace.execute(root, task_id)
    finally:
        _HOST.reset(token)
