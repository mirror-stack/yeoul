"""Read-only aggregation of trusted host records; no model calls or adoption authority."""
import math
import statistics

from comparison_design import design
from comparison_grading import grade


def summarize(records):
    """Keep all 36 planned samples per arm, including missing/failed runs.

    Each record has run_id, delivered_prompt, messages, transport_status,
    elapsed_ms (whole run including retrieval, or None), and requests (one usage
    object per attempted request, each with input_tokens/output_tokens or None).
    Usage counts are host-reported; this function does not authenticate receipts.
    """
    frozen = design()
    planned = {r['run_id']: r for r in frozen['runs']}
    if not isinstance(records, list) or len(records) > len(planned):
        raise ValueError('invalid record collection')
    seen = set()
    grouped = {arm: [] for arm in ('full', 'active')}
    details = []
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'run_id', 'delivered_prompt',
                'messages', 'transport_status', 'elapsed_ms', 'requests'}
                or not isinstance(record['run_id'], str) or record['run_id'] not in planned
                or record['run_id'] in seen):
            raise ValueError('unknown, duplicate or malformed run record')
        seen.add(record['run_id'])
        run = planned[record['run_id']]
        status, elapsed, requests = record['transport_status'], record['elapsed_ms'], record['requests']
        if not isinstance(status, str) or status not in {'complete', 'error', 'interrupted'}:
            raise ValueError('invalid transport status')
        if elapsed is not None and (type(elapsed) not in (int, float)
                or elapsed < 0 or elapsed > 10**12 or not math.isfinite(elapsed)):
            raise ValueError('invalid elapsed time')
        if (not isinstance(requests, list) or not 1 <= len(requests) <= 2
                or len(requests) == 2 and run['case_id'] != 'retrieval'):
            raise ValueError('request count outside fixed design')
        for usage in requests:
            if not isinstance(usage, dict) or set(usage) != {'input_tokens', 'output_tokens'}:
                raise ValueError('invalid usage record')
            if any(v is not None and (type(v) is not int or not 0 <= v <= 10**12)
                   for v in usage.values()):
                raise ValueError('invalid token observation')
        messages = record['messages']
        if not isinstance(messages, list) or len(messages) > 3:
            raise ValueError('invalid transcript record')
        replies = sum(isinstance(m, dict) and m.get('role') == 'assistant' for m in messages)
        if replies > len(requests) or status == 'complete' and replies != len(requests):
            raise ValueError('response count disagrees with attempted requests')
        result = grade(run['run_id'], record['delivered_prompt'], messages)
        if status != 'complete':
            result = dict(result, action_correct=False, evidence_correct=False,
                          task_success=False, reason='transport_'+status)
        details.append(result)
        grouped[run['arm']].append((record, result))
    arms = {}
    for arm, rows in grouped.items():
        times = [r['elapsed_ms'] for r, _ in rows if r['elapsed_ms'] is not None]
        usage = [u for r, _ in rows for u in r['requests']]
        tokens = {}
        for field in ('input_tokens', 'output_tokens'):
            observed = [u[field] for u in usage if u[field] is not None]
            tokens[field] = dict(observed_sum=sum(observed) if observed else None,
                measured_requests=len(observed), attempted_requests=len(usage),
                complete_total=sum(observed) if len(rows) == 36 and len(observed) == len(usage) else None)
        arms[arm] = dict(planned=36, recorded=len(rows), missing=36-len(rows),
            transport_failed=sum(r['transport_status'] != 'complete' for r, _ in rows),
            task_success=sum(s['task_success'] for _, s in rows),
            action_correct=sum(s['action_correct'] for _, s in rows),
            evidence_correct=sum(s['evidence_correct'] for _, s in rows),
            task_success_rate=sum(s['task_success'] for _, s in rows)/36,
            unsafe_recommendations=sum(s['unsafe_recommendation'] is True for _, s in rows),
            safety_unclassified=36-sum(type(s['unsafe_recommendation']) is bool for _, s in rows),
            elapsed_observations=len(times), median_elapsed_ms=statistics.median(times) if times else None,
            max_elapsed_ms=max(times) if times else None, tokens=tokens)
    complete = len(records) == 72
    full, active = arms['full'], arms['active']
    timing_complete = complete and all(a['elapsed_observations'] == 36 and a['transport_failed'] == 0
                                       for a in arms.values())
    ratio = (active['median_elapsed_ms']/full['median_elapsed_ms']
             if timing_complete and full['median_elapsed_ms'] > 0 else None)
    return dict(design_sha256=frozen['design_sha256'], arms=arms, runs=details,
        missing_run_ids=[r for r in planned if r not in seen], all_runs_recorded=complete,
        success_count_not_lower=active['task_success'] >= full['task_success'] if complete else None,
        latency_ratio=ratio, latency_within_1_25=ratio <= 1.25 if ratio is not None else None,
        adoption='NOT_EVALUATED', cost_savings='UNMEASURED',
        note='Token observations are not subscription debit, safety evidence or provider authentication.')
