#!/usr/bin/env python3
"""Large-source literal-index measurement; synthetic words, no model calls."""
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.session_context import SessionContext


def query(session, text, indexed):
    started = time.perf_counter()
    packet = session.context(query=text, recent_turns=1,
        search_event_limit=10000, search_byte_limit=16777216,
        use_search_index=indexed)
    elapsed = time.perf_counter() - started
    body = json.loads(packet['model_input'])
    return dict(seconds=elapsed, model_sha256=packet['sha256'],
                matches=len(body['snippets']), complete=body['search']['complete'],
                stats=packet['search_stats'])


def measure(word_count, repeats=3):
    with tempfile.TemporaryDirectory(prefix='yeoul-search-scale-') as folder:
        path = Path(folder) / 'session.sqlite'
        accepted = 0
        started = time.perf_counter()
        with SessionContext.create(path) as session:
            refusal = None
            while accepted < word_count:
                count = min(40000, word_count - accepted)
                prefix = 'UniqueNeedle ' if accepted == 0 else ''
                try:
                    session.record(prefix + ('word ' * count), origin='trace',
                                   expected_revision=session.revision)
                except ValueError as exc:
                    refusal = str(exc)
                    break
                accepted += count
            population_seconds = time.perf_counter() - started
            usage = session.journal_usage()
            status = session.search_index_status()
            base = dict(requested_synthetic_words=word_count,
                        accepted_synthetic_words=accepted,
                        accepted_source_bytes=accepted * len('word '.encode()),
                        population_seconds=population_seconds,
                        refusal=refusal, usage=usage, search_index=status)
            if refusal is not None:
                assert session.revision == usage['event_count']
                return base
            cases = []
            for label, text in (('old-hit', 'UniqueNeedle'),
                                ('absence', 'AbsentNeedle')):
                samples = {'index': [], 'scan': []}
                observations = {}
                for repeat in range(repeats):
                    order = (True, False) if repeat % 2 == 0 else (False, True)
                    for indexed in order:
                        result = query(session, text, indexed)
                        key = 'index' if indexed else 'scan'
                        samples[key].append(result['seconds'])
                        observations[key] = {name: result[name] for name in
                            ('model_sha256', 'matches', 'complete', 'stats')}
                cases.append(dict(label=label, query=text, samples=samples,
                    index_median_seconds=statistics.median(samples['index']),
                    scan_median_seconds=statistics.median(samples['scan']),
                    observations=observations))
            base['cases'] = cases
            return base


def main():
    output = dict(version=1, meaning=(
        'Synthetic whitespace-delimited words and UTF-8 bytes; not provider tokens, '
        'semantic search, model quality, cold-storage SLA, or concurrent load.'),
        platform=platform.platform(), python=platform.python_version(), repeats=3,
        limits=dict(database_bytes=268435456, payload_bytes=67108864,
                    scan_decoded_bytes=16777216),
        results=[measure(words) for words in (700000, 7000000)])
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
