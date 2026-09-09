#!/usr/bin/env python3
"""MIRROR-SPEC hash verification and first-write arc binding (stdlib only).

Hash integrity is not identity, external time, or content truth. Local bindings
detect drift; they are not a security boundary against an owner rewriting all files.
The wire algorithm matches mirror-stack-mcp.integrity; interoperability is tested.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate JSON key: {key}')
        obj[key] = value
    return obj


def read_verified(path):
    entries = [json.loads(line, object_pairs_hook=unique_object)
               for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not entries:
        raise ValueError('empty ledger')
    previous = 'genesis'
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError('ledger entry must be an object')
        link, seal = entry.get('prev_seal'), entry.get('seal')
        if not isinstance(link, str) or (link.lower() != 'genesis' if index == 0 else link != previous):
            raise ValueError('ledger linkage broken')
        if not isinstance(seal, str) or len(seal) not in (16, 64):
            raise ValueError('missing or invalid seal')
        body = {k: v for k, v in entry.items() if k not in ('seal', 'sig')}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                          allow_nan=False).encode('utf-8')).hexdigest()
        if seal != digest[:len(seal)]:
            raise ValueError('seal mismatch: ledger content changed')
        previous = seal
    return entries


def claim(ledger, claim_id):
    # Read and hash once; choose from exactly that verified snapshot. First write wins.
    entries = read_verified(ledger)
    entry = next((e for e in entries if e.get('claim_id') == claim_id
                  and e.get('_type') is None and e.get('metric') != 'protocol_amendment'), None)
    if entry is None:
        raise ValueError('no first registration for this claim')
    condition = entry.get('kill_condition')
    if not isinstance(condition, str) or not condition.strip():
        threshold = entry.get('kill_threshold')
        if not isinstance(threshold, dict) or not threshold:
            raise ValueError('first registration has no kill-condition')
        condition = json.dumps(threshold, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return entry, ' '.join(condition.split())


def anchors(arc):
    state = arc / 'STATE.md'
    if not state.exists():
        return []
    return [json.loads(line.removeprefix('PREREG_BOUND '), object_pairs_hook=unique_object)
            for line in state.read_text(encoding='utf-8').splitlines()
            if line.startswith('PREREG_BOUND ')]


def resolve(arc):
    arc = Path(arc)
    link = arc / '.prereg'
    records = anchors(arc)
    if not link.exists():
        if records:
            raise ValueError('linked preregistration was removed; restore .prereg')
        return None, None
    lines = link.read_text(encoding='utf-8').splitlines()
    if len(lines) != 3 or not records:
        raise ValueError('legacy/unbound .prereg: explicitly re-link with arc-prereg after verification')
    binding = dict(claim_id=lines[0], ledger=lines[1], seal=lines[2])
    if any(record != binding for record in records):
        raise ValueError('preregistration binding changed from its first anchor')
    entry, condition = claim(binding['ledger'], binding['claim_id'])
    if entry['seal'] != binding['seal']:
        raise ValueError('first registration no longer matches the pinned seal')
    return binding, condition


def bind(arc, claim_id, ledger):
    arc = Path(arc)
    ledger = str(Path(ledger).resolve(strict=True))
    if any(c in claim_id + ledger for c in '\r\n'):
        raise ValueError('claim and ledger must be single-line values')
    entry, condition = claim(ledger, claim_id)
    binding = dict(claim_id=claim_id, ledger=ledger, seal=entry['seal'])
    records = anchors(arc)
    if records and any(record != binding for record in records):
        raise ValueError('refusing to replace the first bound registration; open a new arc')
    link = arc / '.prereg'
    if link.exists():
        old = link.read_text(encoding='utf-8').splitlines()
        if len(old) not in (2, 3) or old[0] != claim_id or str(Path(old[1]).resolve()) != ledger:
            raise ValueError('existing .prereg identifies another claim; open a new arc')
        if len(old) == 3 and old[2] != entry['seal']:
            raise ValueError('existing pinned seal changed')
    # Anchor first: interruption fails closed instead of silently downgrading to unbound.
    if not records:
        with (arc / 'STATE.md').open('a', encoding='utf-8') as stream:
            stream.write('\nPREREG_BOUND ' + json.dumps(binding, ensure_ascii=False) + '\n')
    temp = arc / '.prereg.tmp'
    temp.write_text(f'{claim_id}\n{ledger}\n{entry["seal"]}\n', encoding='utf-8')
    temp.replace(link)
    return condition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['claim', 'bind', 'resolve'])
    parser.add_argument('args', nargs='+')
    args = parser.parse_args()
    try:
        if args.mode == 'claim':
            _, condition = claim(*args.args)
            print(condition)
        elif args.mode == 'bind':
            print(bind(*args.args))
        else:
            binding, condition = resolve(*args.args)
            if binding:
                print(binding['claim_id'])
                print(binding['ledger'])
                print(condition)
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        print(f'preregistration verification refused: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
