#!/usr/bin/env python3
"""Explicit, human-judged result adapter for mirror-stack-mcp >=0.2.14.

Requires status, evidence summary file, and an explicit action ledger. Never
publishes anything or infers scientific success from a deliberation verdict.
"""
import argparse
import json
import sys
from pathlib import Path
from prereg_check import resolve, read_verified


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('arc', type=Path)
    p.add_argument('--status', required=True, choices=['pass', 'fail', 'inconclusive'])
    p.add_argument('--summary-file', required=True, type=Path)
    p.add_argument('--am-ledger', required=True, type=Path)
    a = p.parse_args()
    try:
        from actmirror import am
        from mirror_stack_mcp.gate import decide
        from mirror_stack_mcp.integrity import read_verified as mirror_read_verified
        binding, _ = resolve(a.arc)
        if not binding:
            raise ValueError('a verified pinned preregistration is required')
        summary = a.summary_file.read_text(encoding='utf-8').strip()
        if not summary:
            raise ValueError('empty result summary')
        if a.am_ledger.resolve() == Path(binding['ledger']).resolve():
            raise ValueError('claims and actions must use separate ledgers')
        if a.am_ledger.exists():
            read_verified(a.am_ledger)
        entry = am.record(str(a.am_ledger), agent='yeoul', action='result',
                          target=binding['claim_id'],
                          payload={'status': a.status, 'summary': summary,
                                   'prereg_seal': binding['seal']}, content=summary)
        entries, error = mirror_read_verified(a.am_ledger)
        if error or not any(e.get('seal') == entry['seal'] for e in entries):
            raise ValueError(f'result was written but could not be verified: {error}')
        decision = decide(binding['ledger'], binding['claim_id'], gate='publish',
                          am_ledger=str(a.am_ledger))
        print(json.dumps({'result_seal': entry['seal'], 'publication_gate': decision,
                          'published': False}, ensure_ascii=False))
        return 0 if decision['decision'] == 'GO' else 1
    except (ImportError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f'result recording refused: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
