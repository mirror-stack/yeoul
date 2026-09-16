"""Pure, opt-in review routing; no verifier, authority, execution or persistence.

The host must authenticate/normalize provider reports, supply the complete check
requirements and fresh binding, and enforce permissions at the execution boundary.
This function does not trust a worker to select its own reviewers or requirements.
"""
import re


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1024


def _binding(value):
    return (isinstance(value, dict)
            and set(value) == {'task_id', 'target', 'revision', 'proposal_sha256'}
            and all(_text(v) for v in value.values())
            and re.fullmatch('[0-9a-f]{64}', value['proposal_sha256']) is not None)


def decide(binding, requirements, reports):
    """Return ready_for_review only if every required, host-selected check passes.

    requirements maps check IDs to provider IDs. Reports must be the host's latest
    authoritative set, not a worker-selected subset or append-only event history.
    Duplicates are ambiguous and held, never resolved by input ordering. Unknown
    checks also hold: silently dropping them could conceal a host routing error.
    Malformed input raises ValueError. No outcome means authorized or completed.
    """
    if not _binding(binding):
        raise ValueError('invalid current review binding')
    if (not isinstance(requirements, dict) or not 1 <= len(requirements) <= 100
            or not all(_text(k) and _text(v) for k, v in requirements.items())):
        raise ValueError('required checks must be supplied by host')
    if not isinstance(reports, list) or len(reports) > 100:
        raise ValueError('invalid report set')
    reasons, seen = set(), set()
    for report in reports:
        if (not isinstance(report, dict)
                or set(report) != {'check_id', 'provider_id', 'binding', 'status', 'evidence_ref'}
                or not _text(report['check_id']) or not _text(report['provider_id'])
                or not _binding(report['binding'])
                or not isinstance(report['status'], str)
                or report['status'] not in {'pass', 'fail', 'unknown', 'retracted'}
                or not _text(report['evidence_ref'])):
            raise ValueError('invalid normalized verification report')
        check = report['check_id']
        if check in seen:
            reasons.add('duplicate_check')
        seen.add(check)
        if check not in requirements:
            reasons.add('unexpected_check')
        elif report['provider_id'] != requirements[check]:
            reasons.add('provider_mismatch')
        if report['binding'] != binding:
            reasons.add('stale_or_different_proposal')
        if report['status'] != 'pass':
            reasons.add('verification_' + report['status'])
    if set(requirements) - seen:
        reasons.add('missing_check')
    return dict(state='needs_review' if reasons else 'ready_for_review',
                reasons=sorted(reasons), authority='NONE', execution='NOT_PERFORMED')
