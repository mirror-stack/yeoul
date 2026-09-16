# Authorized recovery view (unreleased)

`yeoul_mcp.recovery_view.recovery_view` renders an English or Korean read-only HTML
snapshot from a trusted WorkerTasks instance and at most 100 explicitly selected
logical task IDs. It does not enumerate the workspace or create an HTTP listener.

```python
from yeoul_mcp.recovery_view import recovery_view

# Inside the host's authenticated request context, for example:
with access.connection(accepted_socket):
    html = recovery_view(tasks, host_selected_task_ids, language="ko")
# The host must securely deliver/protect this HTML; there is no automatic publishing.
```

Inspection permission is checked before/after each read and again before rendering.
Denied IDs are omitted without a denied-task count. Damaged authorized records get
a generic review-required row without raw errors, paths, input, output or notes.
The view shows separate states for missing launch revocation, unconfirmed stop,
observed absence, cancellation intent, operator retirement and retained output.
No state implies business completion, retry approval or completed cancellation.

HTML has a timestamp, language metadata, semantic headings/table, escaped values,
no scripts, external resources, links, forms or action controls, and a restrictive
CSP. Generation calls no service broker and does not modify execution records.
This is a host integration view, not a deployed recovery application. Synthetic
states were visually inspected in installed Chromium 152 at 1100px (Korean) and
390px (Korean/English). Fixed desktop columns prevent long task IDs squeezing
status text; below 600px the table uses labeled vertical rows. Tests still cover
the content/security structure. This is not a screen-reader, other-browser or
full accessibility audit. The synthetic stdout fixture is
`mcp/tests/recovery_view_fixture.py`; it never reads real task records.

Saved snapshots may become stale and cannot be revoked after disclosure. The host
must protect storage/delivery; do not publish them, attach them to public issues or
assume that removing a grant deletes already downloaded HTML. This API neither
writes report files nor chooses a retention policy. The optional
[host confirmation controller](RECOVERY_ACTIONS.md) handles cancellation but is not
embedded in exported HTML. Interactive UI route/security integration and operational
record retention remain separate work. The five contract tests cover read-only
behavior, denied-ID/private-data exclusion, safe corrupted-record display,
revocation during collection, and bounded IDs/languages.
