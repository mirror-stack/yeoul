#!/usr/bin/env python3
"""Large-source replay/checkpoint measurement; synthetic words, no model calls."""
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.session_context import SessionContext


def change(text):
    return dict(kind='goal', key='main', text=text, status='active',
                start=0, end=len(text), quote=text, evidence='', reopen=False)


def timed_open(path, *, checkpoint, expected_hash):
    started = time.perf_counter()
    with SessionContext(path, use_checkpoint=checkpoint) as session:
        packet = session.context(recent_turns=0)
        assert packet['state'] == 'ready' and packet['sha256'] == expected_hash
        status = session.replay_status()
    return time.perf_counter() - started, status


def measure(word_count, repeats=3):
    with tempfile.TemporaryDirectory(prefix='yeoul-session-scale-') as folder:
        path = Path(folder).resolve() / 'session.sqlite'
        created = SessionContext.create(path)
        created.close()
        # This benchmark isolates source replay/checkpoint scaling. Literal-search
        # index scaling has a separate benchmark and would dominate repeated text.
        db = sqlite3.connect(path)
        db.execute('DROP TABLE IF EXISTS turn_search')
        db.execute('DROP TABLE IF EXISTS search_meta')
        db.commit()
        db.close()

        started = time.perf_counter()
        with SessionContext(path) as session:
            goal = 'Preserve this reviewed goal while historical trace grows.'
            turn = session.record(goal, origin='user', expected_revision=0)
            session.review(turn, [change(goal)], expected_revision=1,
                           reason='benchmark host review')
            remaining = word_count
            while remaining:
                count = min(40000, remaining)
                session.record('word ' * count, origin='trace',
                               expected_revision=session.revision)
                remaining -= count
            population_seconds = time.perf_counter() - started
            usage = session.journal_usage()
            packet = session.context(recent_turns=0)
            expected_hash = packet['sha256']
            context_bytes = packet['utf8_bytes']
            checkpoint = session.write_checkpoint(expected_revision=session.revision)

        full, fast = [], []
        for _ in range(repeats):
            elapsed, status = timed_open(path, checkpoint=False,
                                         expected_hash=expected_hash)
            assert status['mode'] == 'full' and status['full_prefix_verified']
            full.append(elapsed)
            elapsed, status = timed_open(path, checkpoint=True,
                                         expected_hash=expected_hash)
            assert status['mode'] == 'checkpoint' and not status['full_prefix_verified']
            fast.append(elapsed)
        source_bytes = word_count * len('word '.encode())
        return dict(synthetic_words=word_count, synthetic_source_bytes=source_bytes,
                    event_count=usage['event_count'], payload_bytes=usage['payload_bytes'],
                    database_bytes=usage['database_bytes'], context_bytes=context_bytes,
                    checkpoint_bytes=checkpoint['checkpoint_bytes'],
                    population_seconds=population_seconds,
                    full_open_seconds=full, checkpoint_open_seconds=fast,
                    full_open_median_seconds=statistics.median(full),
                    checkpoint_open_median_seconds=statistics.median(fast),
                    speedup_ratio=(statistics.median(full) / statistics.median(fast)))


def main():
    results = [measure(words) for words in (700000, 7000000)]
    print(json.dumps(dict(version=1, meaning=(
        'Synthetic whitespace-delimited words and UTF-8 bytes; not provider tokens, '
        'model quality, search-index scaling, cold-storage SLA, or concurrent load.'),
        platform=platform.platform(), python=platform.python_version(),
        sqlite=sqlite3.sqlite_version, repeats=3, results=results),
        sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
