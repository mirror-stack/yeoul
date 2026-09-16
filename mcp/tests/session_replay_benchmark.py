"""Local synthetic replay measurement; no model, network, install or operating data."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.session_context import SessionContext


def _change(text, key):
    return dict(kind='task', key=key, text=text, status='open', start=0,
                end=len(text), quote=text, evidence='', reopen=False)


def _open(path, fast):
    started = time.perf_counter()
    with SessionContext(path, use_checkpoint=fast) as session:
        packet = session.context(byte_budget=1048576, recent_turns=0)
        if packet['state'] != 'ready':
            raise RuntimeError('synthetic projection exceeded benchmark budget')
        result = dict(seconds=time.perf_counter() - started,
                      sha256=packet['sha256'], status=session.replay_status())
    return result


def measure(label, populate, repeats):
    with tempfile.TemporaryDirectory(prefix='yeoul replay benchmark ') as folder:
        path = Path(folder) / 'session.sqlite'
        started = time.perf_counter()
        with SessionContext.create(path) as session:
            populate(session)
            population_seconds = time.perf_counter() - started
            checkpoint = session.write_checkpoint(expected_revision=session.revision)
        timings = dict(full=[], checkpoint=[])
        hashes = set()
        statuses = []
        for number in range(repeats):
            order = (False, True) if number % 2 == 0 else (True, False)
            for fast in order:
                result = _open(path, fast)
                timings['checkpoint' if fast else 'full'].append(result['seconds'])
                hashes.add(result['sha256'])
                statuses.append(result['status'])
        if len(hashes) != 1:
            raise RuntimeError('full and checkpoint projections differ')
        full = statistics.median(timings['full'])
        fast = statistics.median(timings['checkpoint'])
        checkpoint_statuses = [row for row in statuses if row['mode'] == 'checkpoint']
        if len(checkpoint_statuses) != repeats or any(row['replayed_events'] for row in checkpoint_statuses):
            raise RuntimeError('checkpoint benchmark unexpectedly replayed a suffix')
        return dict(label=label, source_events=checkpoint['source_events_preserved'],
                    checkpoint_bytes=checkpoint['checkpoint_bytes'],
                    population_seconds=population_seconds, repeats=repeats,
                    full_seconds=timings['full'], checkpoint_seconds=timings['checkpoint'],
                    full_median_seconds=full, checkpoint_median_seconds=fast,
                    median_speedup=(full / fast if fast else None), projection_sha256=hashes.pop())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace-events', type=int, default=5000)
    parser.add_argument('--state-items', type=int, default=1000)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.trace_events <= 50000 or not 1 <= args.state_items <= 5000:
        raise SystemExit('benchmark sizes out of range')
    if not 1 <= args.repeats <= 20:
        raise SystemExit('repeats out of range')

    def traces(session):
        for number in range(args.trace_events):
            session.record('trace-%05d synthetic diagnostic' % number, origin='trace',
                           expected_revision=session.revision)

    def state(session):
        for number in range(args.state_items):
            text = 'Synthetic open task %05d' % number
            turn = session.record(text, origin='user', expected_revision=session.revision)
            session.review(turn, [_change(text, 'task-%05d' % number)],
                           expected_revision=session.revision, reason='synthetic benchmark')

    result = dict(version=1, clock='time.perf_counter', warm_cache=True,
                  cases=[measure('trace-heavy', traces, args.repeats),
                         measure('state-heavy', state, args.repeats)],
                  limitations=['single local machine', 'synthetic data', 'warm filesystem cache',
                               'no concurrent writer', 'not model token or answer quality evidence'])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
