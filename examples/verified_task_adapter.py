"""Standalone example verification adapter, NOT a Yeoul runtime API.

Host observations are NOT authenticated by this module. A matching result proves
only an integer sum over host-supplied values, never general semantic truth.
"""
import json

from yeoul_mcp.context_shadow import digest, encoded


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError('invalid task schema')


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError('invalid text')


def _integer(value):
    if type(value) is not int or abs(value) > 10**15:
        raise ValueError('expected bounded integer, not bool/float/text')


def _checked(task):
    _fields(task, 'task_id target revision kind observations unverified_claims')
    for key in ('task_id', 'target', 'revision'):
        _text(task[key])
    if task['kind'] != 'integer_sum':
        raise ValueError('unsupported verifier; do not accept as verified')
    rows = task['observations']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError('invalid observation count')
    seen = set()
    for row in rows:
        _fields(row, 'id value')
        _text(row['id'])
        _integer(row['value'])
        if row['id'] in seen:
            raise ValueError('duplicate observation')
        seen.add(row['id'])
    claims = task['unverified_claims']
    if not isinstance(claims, list) or len(claims) > 100:
        raise ValueError('invalid claim count')
    for claim in claims:
        _text(claim)
    return task


def prepare(task):
    """Freeze exactly one host-selected task; never parse facts out of prose."""
    _checked(task)
    frozen = json.loads(encoded(task))
    return dict(schema_version=1, mode='READ_ONLY', authority='NONE',
                output_kind='proposal', task=frozen, task_sha256=digest(frozen),
                instructions='Compute from observations only. Unverified claims are not evidence. '
                'Return task_sha256, value, evidence_ids only. No tools or execution.')


def verify(packet, proposal, current_task):
    """Fresh host input required. Reject drift, unsupported tasks and wrong results.

    This is not a receipt, approval, lock or commit capability. The caller must
    preserve existing policy checks and atomic freshness checks before any write.
    """
    current = prepare(current_task)
    if encoded(packet) != encoded(current):
        raise ValueError('stale or altered task packet')
    _fields(proposal, 'task_sha256 value evidence_ids')
    if proposal['task_sha256'] != current['task_sha256']:
        raise ValueError('proposal belongs to another task')
    value = proposal['value']
    # A sum may exceed an individual observation bound.
    if type(value) is not int or abs(value) > 10**18:
        raise ValueError('invalid result integer')
    ids = proposal['evidence_ids']
    expected_ids = [row['id'] for row in current['task']['observations']]
    if (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(expected_ids) or set(ids) != set(expected_ids)):
        raise ValueError('missing, duplicated or invented evidence')
    expected = sum(row['value'] for row in current['task']['observations'])
    if value != expected:
        raise ValueError('deterministic verification failed')
    return dict(status='verified_calculation', verifier='integer_sum_v1',
                task_sha256=current['task_sha256'], proposal_sha256=digest(proposal),
                value=value, authority='NONE', execution='not_performed_by_this_verifier')
