"""Opt-in read-only workflow for a host-owned test workspace.

Worker and verification adapters are supplied by the host, not by source text.
No default model, file discovery, execution, persistence or production loader.
Callbacks are trusted Python code, not sandboxed by this module.
"""
import hashlib
import json

from .context_shadow import encoded, extract, model_input, validate, digest
from .review_decision import decide
from .worker_transport import WorkerTransportError

MAX_REPLY_BYTES = 64 * 1024


def _json(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_REPLY_BYTES:
        raise ValueError('invalid or oversized worker reply')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON field')
            value[key] = item
        return value
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    encoded(value)  # Reject nonfinite numbers, including overflowed JSON floats.
    return value


def run_shadow(task_id, load_snapshot, worker, providers):
    """Connect one current source snapshot, one proposal and host-selected checks.

    load_snapshot() must freshly read the complete authoritative source set.
    worker(model_bytes) returns JSON bytes: {input_sha256, proposal: object}.
    providers maps check_id to (provider_id, callback). Each callback receives
    immutable (snapshot_bytes, proposal_bytes, binding_bytes) and returns a
    normalized {status, evidence_ref}. The host authenticates those callbacks.

    All checks run once; no fallback, retry, write or commit is authorized. Returned
    ready_for_review is a point-in-time routing result, never a reusable approval.
    """
    if not isinstance(providers, dict) or not 1 <= len(providers) <= 100:
        raise ValueError('host must select required providers')
    selected = []
    for check, spec in providers.items():
        if not isinstance(spec, tuple) or len(spec) != 2 or not callable(spec[1]):
            raise ValueError('invalid host provider')
        selected.append((check, spec[0], spec[1]))
    requirements = {check: name for check, name, _ in selected}
    snapshot = json.loads(encoded(load_snapshot()))
    packet = extract(snapshot)
    initial_binding = dict(task_id=task_id, target=snapshot['target'],
                           revision=packet['binding']['source_sha256'], proposal_sha256='0'*64)
    # Provider binding is host-only: public model revision may deliberately hide
    # changes to nonpublic sources, which must still invalidate verification.
    decide(initial_binding, requirements, [])  # Validate host policy before worker call.
    payload = model_input(packet, snapshot)
    input_hash = hashlib.sha256(payload).hexdigest()
    events = ['context_prepared']

    def held(reason):
        return dict(state='needs_review', reasons=[reason], authority='NONE',
                    execution='NOT_PERFORMED', events=list(events), input_sha256=input_hash,
                    input_utf8_bytes=len(payload))

    def fresh():
        current = json.loads(encoded(load_snapshot()))
        validate(packet, current)
        return current

    try:
        fresh()  # Recheck immediately before delivery, not only after work.
    except (ValueError, TypeError, OSError):
        return held('source_unavailable_or_changed')
    try:
        raw = worker(payload)
    except WorkerTransportError as exc:
        return held(exc.reason)
    except Exception:
        return held('worker_error')
    events.append('worker_returned')
    try:
        reply = _json(raw)
        if (not isinstance(reply, dict) or set(reply) != {'input_sha256', 'proposal'}
                or reply['input_sha256'] != input_hash or not isinstance(reply['proposal'], dict)):
            raise ValueError('proposal not bound to delivered input')
        proposal = encoded(reply['proposal'])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return held('invalid_worker_reply')
    try:
        current = fresh()
    except (ValueError, TypeError, OSError):
        return held('source_unavailable_or_changed')
    binding = dict(initial_binding, proposal_sha256=digest(reply['proposal']))
    reports = []
    for check, name, verify in selected:
        try:
            report = verify(encoded(current), proposal, encoded(binding))
            if not isinstance(report, dict) or set(report) != {'status', 'evidence_ref'}:
                raise ValueError('invalid provider result')
            normalized = dict(check_id=check, provider_id=name, binding=dict(binding), **report)
            # Validate provider fields without letting it replace identity/binding.
            decide(binding, {check: name}, [normalized])
            reports.append(normalized)
        except Exception:
            return held('provider_error')
    events.append('providers_returned')
    try:
        fresh()  # Never promote a review of a source that changed during verification.
    except (ValueError, TypeError, OSError):
        return held('source_unavailable_or_changed')
    result = decide(binding, requirements, reports)
    return dict(result, events=events + ['review_routed'], binding=binding,
                input_sha256=input_hash, input_utf8_bytes=len(payload),
                proposal=reply['proposal'], reports=reports)
