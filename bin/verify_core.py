#!/usr/bin/env python3
"""Shared CLI/MCP/Ralph verification. Baselines belong to the supervisor.

Only checkbox state may change. This is workflow integrity, not an OS sandbox.
Protect standalone baseline files and test implementations from worker writes.
"""
import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ITEM = re.compile(r'^- \[([ x])\] (.*)$')
VERIFY = re.compile(r'verify:\s*`([^`]+)`')


def canonical(text):
    return re.sub(r'(?m)^- \[[ x]\]', '- [ ]', text)


def eligible(text):
    rows = [line for line in text.splitlines() if ITEM.match(line)]
    malformed = any(line.startswith('- [') and not ITEM.match(line) for line in text.splitlines())
    return bool(rows) and not malformed and all(VERIFY.search(line) for line in rows)


def atomic_write(path, text):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.'+path.name, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(text)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def execute(args, *, cwd=None, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
    # POSIX timeout kills this child group only. Windows falls back to direct-child termination.
    with subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                          start_new_session=os.name == 'posix') as child:
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            child.wait()
            return 124


def verify(todo, *, baseline=None, revert=False, require=False, timeout=120):
    path = Path(todo)
    text = path.read_text(encoding='utf-8')
    if baseline is not None and canonical(text) != canonical(baseline):
        print('BLOCK: TODO criteria/commands/items changed from the approved baseline', file=sys.stderr)
        if revert:
            atomic_write(path, canonical(baseline))
        return 3
    failed = False
    output = []
    for line in text.splitlines(keepends=True):
        item = ITEM.match(line.rstrip('\r\n'))
        command = VERIFY.search(line)
        if item and item[1] == 'x' and (command or require):
            rc = execute(['bash', '-c', command[1]], timeout=timeout) if command else 1
            if rc:
                print(f'verify failed (exit {rc}): {line.strip()}', file=sys.stderr)
                failed = True
                if revert:
                    line = line.replace('- [x]', '- [ ]', 1)
        output.append(line)
    if path.read_text(encoding='utf-8') != text:
        print('BLOCK: TODO changed during verification', file=sys.stderr)
        return 3
    if revert and failed:
        atomic_write(path, ''.join(output))
    return int(failed)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['check', 'baseline', 'verify'])
    p.add_argument('todo', type=Path)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--current-only', action='store_true', help='manual diagnostic; no criterion protection')
    p.add_argument('--require-verify', action='store_true')
    p.add_argument('--revert', action='store_true')
    p.add_argument('--timeout', type=float, default=120)
    a = p.parse_args()
    try:
        if not math.isfinite(a.timeout) or a.timeout <= 0:
            raise ValueError('timeout must be positive')
        text = a.todo.read_text(encoding='utf-8')
        if a.mode == 'check':
            if not eligible(text):
                print('not loop-eligible: require at least one item, each with a nonempty backtick verify command')
                return 3
            print('loop-eligible: all items have verify commands (criteria not judged)')
            return 0
        bp = a.baseline or Path(str(a.todo)+'.verify-baseline.json')
        if a.mode == 'baseline':
            if not eligible(text):
                raise ValueError('cannot approve an empty or ungated TODO')
            with bp.open('x', encoding='utf-8') as stream:
                json.dump({'version': 1, 'todo': str(a.todo.resolve()), 'text': canonical(text)}, stream)
            print(f'baseline created: {bp}; keep it outside the worker write scope')
            return 0
        baseline = None
        if a.current_only:
            print('scope: current commands only; criterion changes NOT checked', file=sys.stderr)
        else:
            data = json.loads(bp.read_text(encoding='utf-8'))
            if data.get('version') != 1 or data.get('todo') != str(a.todo.resolve()):
                raise ValueError('baseline version/path mismatch')
            baseline = data['text']
            if not isinstance(baseline, str) or not eligible(baseline):
                raise ValueError('invalid baseline')
        return verify(a.todo, baseline=baseline, revert=a.revert,
                      require=a.require_verify, timeout=a.timeout)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'BLOCK: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
