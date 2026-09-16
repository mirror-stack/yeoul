#!/usr/bin/env python3
"""Minimal opt-in SessionContext example; no model, network, or product writes."""
import json
import os
from pathlib import Path
import sys
import tempfile

# Source users may have an older installed Yeoul that lacks this unreleased API.
# CI explicitly selects the freshly installed package instead.
if not os.environ.get('PRODUCT_TEST_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp'))
from yeoul_mcp.session_context import SessionContext


def reviewed(text, *, kind, key, status, evidence=''):
    return dict(kind=kind, key=key, text=text, status=status,
                start=0, end=len(text), quote=text,
                evidence=evidence, reopen=False)


def main():
    with tempfile.TemporaryDirectory(prefix='yeoul-session-demo-') as folder:
        with SessionContext.create(Path(folder) / 'session.sqlite') as session:
            goal = 'Review the importer schema before implementation.'
            turn = session.record(goal, origin='user', expected_revision=0)
            session.review(turn, [reviewed(goal, kind='goal', key='main', status='active')],
                           expected_revision=1, reason='explicit host review')

            completed = 'Schema review passed the local fixture.'
            turn = session.record(completed, origin='tool', expected_revision=2)
            session.review(turn, [reviewed(completed, kind='task', key='schema-review',
                                           status='done', evidence='fixture:schema-review')],
                           expected_revision=3, reason='verified tool result')

            packet = session.context(recent_turns=0)
            context = json.loads(packet['model_input'])
            assert packet['state'] == 'ready'
            assert context['delivery'] == 'REPLACE_CONTEXT'
            assert context['authority'] == 'NONE'
            assert context['active'][0]['text'] == goal
            assert context['retired'][0]['status'] == 'done'
            print(json.dumps(dict(delivery=context['delivery'], authority=context['authority'],
                                  revision=context['revision'], active=len(context['active']),
                                  retired=len(context['retired']), utf8_bytes=packet['utf8_bytes']),
                             sort_keys=True))


if __name__ == '__main__':
    main()
