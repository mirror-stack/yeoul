"""Local synthetic literal-search measurement; no model, network or installation."""
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


def timed(session, query, indexed, limit):
    started = time.perf_counter()
    result = session.context(query=query, recent_turns=1, search_event_limit=limit,
                             search_byte_limit=16777216, use_search_index=indexed)
    elapsed = time.perf_counter() - started
    body = json.loads(result['model_input'])
    return dict(seconds=elapsed, sha256=result['sha256'], snippets=body['snippets'],
                complete=body['search']['complete'], stats=result['search_stats'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--events', type=int, default=5000)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if not 10 <= args.events <= 9999 or not 1 <= args.repeats <= 20:
        raise SystemExit('benchmark sizes out of range')
    with tempfile.TemporaryDirectory(prefix='yeoul search benchmark ') as folder:
        path = Path(folder) / 'session.sqlite'
        started = time.perf_counter()
        with SessionContext.create(path) as session:
            source_turn = session.record('old UniqueNeedle source', origin='trace',
                                         expected_revision=0)
            for number in range(1, args.events):
                session.record('recent irrelevant %05d' % number, origin='trace',
                               expected_revision=session.revision)
            population_seconds = time.perf_counter() - started
            cases = []
            for label, query in (('old-hit', 'UniqueNeedle'), ('absence', 'AbsentNeedle')):
                timings = dict(indexed=[], scan=[])
                expected = None
                for number in range(args.repeats):
                    order = (True, False) if number % 2 == 0 else (False, True)
                    for indexed in order:
                        got = timed(session, query, indexed, args.events)
                        timings['indexed' if indexed else 'scan'].append(got['seconds'])
                        semantic = (got['sha256'], got['snippets'], got['complete'])
                        if expected is None:
                            expected = semantic
                        elif semantic != expected:
                            raise RuntimeError('indexed and scan results differ')
                        if indexed and got['stats']['strategy'] != 'fts5_trigram':
                            raise RuntimeError('index unavailable during benchmark')
                indexed_median = statistics.median(timings['indexed'])
                scan_median = statistics.median(timings['scan'])
                cases.append(dict(label=label, query=query, repeats=args.repeats,
                    indexed_seconds=timings['indexed'], scan_seconds=timings['scan'],
                    indexed_median_seconds=indexed_median, scan_median_seconds=scan_median,
                    median_speedup=(scan_median / indexed_median if indexed_median else None),
                    result_sha256=expected[0], matches=len(expected[1]), complete=expected[2]))
            output = dict(version=1, events=args.events, source_turn=source_turn,
                          population_seconds=population_seconds, warm_cache=True,
                          search_index=session.search_index_status(), cases=cases,
                          limitations=['single local machine', 'synthetic data',
                            'warm filesystem cache', 'one open connection',
                            'not semantic search, model token or answer quality evidence'])
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
