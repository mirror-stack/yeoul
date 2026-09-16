# Host-confirmed cancellation (unreleased, Linux)

`RecoveryActions` connects an interactive host confirmation flow to the existing
`WorkerTasks.cancel`. It is not an HTTP listener, MCP tool, browser form,
authentication service or proof that a human clicked a button.

```python
actions = RecoveryActions(tasks, principal=access.subject)
with access.connection(preview_socket):
    preview = actions.prepare_cancel(task_id, note=operator_note)
# Display the bound details and obtain an explicit operator decision.
# Handle the subsequent authenticated request with the same controller instance.
with access.connection(confirm_socket):
    observation = actions.confirm_cancel(submitted_token)
```

The trusted identity callback supplies the current account, never a request UID.
WorkerAccess.subject reads the kernel identity of the live UNIX connection. Preview
requires current inspect and cancel permissions. Its random opaque token binds
account, task, mapping SHA and note without cancellation writes or service calls.
Defaults: 120 seconds on CLOCK_BOOTTIME (including suspend), 128 retained tokens;
trusted host ranges: 1–300 seconds and 1–1024 tokens.

Confirmation requires the same account and unused/unexpired token. It consumes
the token under an in-process lock before host I/O; duplicate/concurrent submissions
and retries after failure do not dispatch again. WorkerTasks.cancel rechecks current
permission and mapping SHA under the workspace lock before writing. A changed
target is refused. Results are observations, never completed cancellation or retry
approval. Preview and confirmation do not authorize business-state changes.

Restart or another controller instance invalidates memory-only tokens. Used tokens
occupy capacity until expiry. Do not silently issue/confirm a replacement after a
lost response: inspect durable cancellation evidence and obtain a new operator
decision as needed. This is not a distributed replay cache.

The host still supplies authenticated transport, explicit user confirmation,
CSRF/origin/session protection and protected token delivery. Never place tokens
in URLs, logs or exported read-only snapshots. Same-UID apps share authority.
No production routes, listener or permission grants are installed. Exported recovery
HTML remains noninteractive; full UI route/security acceptance is outstanding.

Six tests cover preview effects, one-use/concurrent requests, other accounts,
expiry/restart, mapping changes, permission revocation and capacity. A separate
real socket test connects the controller to kernel account identity. The service
transport in these confirmation tests is synthetic.
