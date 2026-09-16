"""Print nonsensitive synthetic recovery HTML for offline browser inspection."""
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp.recovery_view import recovery_view

reports = {
    'synthetic-records': dict(state='cancel_requested', cancellation={'status': 'evidence_unreadable'}),
    'synthetic-marker': dict(state='cancel_requested', cancellation={'status': 'intent_only', 'revocation_marker': 'missing'}),
    'synthetic-stop': dict(state='cancel_requested', cancellation={'status': 'observations_retained', 'unresolved_attempts': 1}),
    'synthetic-absence': dict(state='cancel_requested', cancellation={'status': 'observations_retained', 'attempts': [{'state': 'absence_observed'}]}),
    'synthetic-cancel': dict(state='cancel_requested', cancellation={'status': 'intent_only', 'revocation_marker': 'present'}),
    'synthetic-retired': dict(state='retired', cancellation=None),
    'synthetic-output': dict(state='returned', needs_attention=False, cancellation=None),
    'synthetic-' + 'long-task-' * 11: dict(state='start_requested', cancellation=None),
}
host = Mock()
host.inspect.side_effect = reports.__getitem__
print(recovery_view(host, list(reports), language=sys.argv[1] if len(sys.argv) > 1 else 'ko'))
