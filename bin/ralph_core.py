#!/usr/bin/env python3
"""Bounded dev loop. No measurement, sealing or publication is performed here."""
import argparse
import json
import math
import os
import shlex
import sys
import uuid
from pathlib import Path
from verify_core import canonical, eligible, execute, verify, atomic_write


def pending(text):
    return sum(line.startswith('- [ ] ') for line in text.splitlines())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name')
    p.add_argument('--check', action='store_true', help='read-only CLI/MCP eligibility check')
    p.add_argument('--max-rounds', type=int, default=4)
    p.add_argument('--token-budget', type=int, default=300000)
    p.add_argument('--round-timeout', type=float, default=120)
    p.add_argument('--verify-timeout', type=float, default=120)
    p.add_argument('--model', default='')
    p.add_argument('--agent-cmd', default=os.environ.get('YEOUL_AGENT_CMD',
                   'claude -p --output-format json --permission-mode acceptEdits'))
    a = p.parse_args()
    try:
        todo = Path(os.environ.get('YEOUL_PROJECTS', './projects')) / a.name / 'dev' / 'TODO.md'
        baseline = todo.read_text(encoding='utf-8')
        if not eligible(baseline):
            print('not loop-eligible: require at least one item; ALL items need a nonempty verify command')
            return 3
        if a.check:
            print('loop-eligible: all items have verify commands (criteria not judged)')
            return 0
        if any(not math.isfinite(n) or n <= 0 for n in
               (a.max_rounds, a.token_budget, a.round_timeout, a.verify_timeout)):
            raise ValueError('limits must be positive')
        # Original criteria stay in parent memory, never reloaded from a worker-writable snapshot.
        if verify(todo, baseline=baseline, revert=True, require=True, timeout=a.verify_timeout):
            return 3
        if pending(todo.read_text(encoding='utf-8')) == 0:
            print('RALPH_DONE: existing checked items re-verified')
            return 0
        # Re-running a project must not overwrite previous round evidence.
        log = todo.parent / 'ralph_log' / ('run-'+uuid.uuid4().hex)
        log.mkdir(parents=True)
        used = no_progress = 0
        for round_no in range(1, a.max_rounds + 1):
            text = todo.read_text(encoding='utf-8')
            if canonical(text) != canonical(baseline):
                print('STOP: criteria changed between rounds')
                return 3
            before = pending(text)
            prompt = (f'Implement ONLY the first unchecked item in {todo.resolve()}.\n{text}\n'
                      'Only change its checkbox in TODO; do not edit criteria or verify commands. '
                      'Run its verify command before checking it. No measurement/GPU runs, sealing, '
                      'PASS/KILL judgments, publishing or background processes. '
                      'Return JSON with usage.input_tokens and usage.output_tokens as nonnegative integers.')
            args = shlex.split(a.agent_cmd)
            if a.model:
                args += ['--model', a.model]
            args.append(prompt)
            out = log / f'round_{round_no}.json'
            with out.open('w', encoding='utf-8') as stdout, (log/f'round_{round_no}.err').open('w', encoding='utf-8') as stderr:
                rc = execute(args, timeout=a.round_timeout, stdout=stdout, stderr=stderr)
            if rc:
                atomic_write(todo, text)
                print(f'STOP: agent failed/timeout (exit {rc}); no completion accepted')
                return 124 if rc == 124 else 2
            rc = verify(todo, baseline=baseline, revert=True, require=True, timeout=a.verify_timeout)
            if rc == 3:
                return 3
            try:
                usage = json.loads(out.read_text(encoding='utf-8'))['usage']
                counts = [usage['input_tokens'], usage['output_tokens']]
                if any(type(n) is not int or n < 0 for n in counts):
                    raise ValueError('invalid token count')
                used += sum(counts)
            except (ValueError, TypeError, KeyError):
                print('STOP:unmeasured — missing/invalid usage is not zero tokens')
                return 2
            remaining = pending(todo.read_text(encoding='utf-8'))
            no_progress = no_progress + 1 if remaining >= before else 0
            print(f'round={round_no}/{a.max_rounds} tokens_used={used}/{a.token_budget} unchecked={remaining}')
            print(f'log={log}')
            if used > a.token_budget:
                print('STOP:budget — reported usage exceeded budget in this round')
                return 2
            if remaining == 0:
                print('RALPH_DONE: all items verified against the original criteria')
                return 0
            if used >= a.token_budget or no_progress >= 2:
                print('STOP:budget' if used >= a.token_budget else 'STOP:no-progress')
                return 2
        print('STOP:max-rounds — no extra round launched')
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print(f'BLOCK: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
