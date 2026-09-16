# Durable host execution records and profile allowlist (unreleased)

`yeoul_mcp.worker_host` provides local host components for `IsolatedWorker`.
Nothing is installed or activated automatically. The worker namespace cannot see
the host workspace or `.yeoul-mcp` metadata. No administrative MCP tool, sudo rule,
network service or user/account authentication endpoint is added.

## Components

`WorkerJournal(workspace_root)` is the durable event sink. It writes under
`.yeoul-mcp/worker-runs/<unit>/` using the existing cooperative process lock,
atomic JSON writes and file/directory flushing helpers. Each event has its own
numbered file, previous-record digest and timestamp. Schema, sequence, state
transition and manifest binding are checked on both append and reopen. Identical
delivery retries do not overwrite history; changed, missing, unexpected or
out-of-order records are refused. Retention is explicit: there is no automatic
history deletion or archive repair.

`ProfileBroker(journal, invoke, argv=..., uid=..., gid=..., timeout=...)` compares
each launch to a fixed host profile and the exact canonical service request.
Command, identity, resource properties, runtime, input length and input SHA must
match. It rejects arbitrary administrative commands and changed flags. Stop
requests require a retained dispatch from the same profile. LoadState-only probes
are restricted to the generated Yeoul worker name format.

Before calling `invoke`, the broker durably reserves that unit's dispatch. A
second process or restarted host cannot dispatch the same reservation again.
A crash after reservation but before sending the request is intentionally
ambiguous: the record is not proof that execution began, and it is not permission
to retry. This local reservation does not fence late system-manager start requests
or prevent a host from deliberately creating a new unit for the same logical task.

The broker stores up to 64 KiB of raw result bytes separately, bound to the
manifest and output digest, before delivering the result to `IsolatedWorker`.
Only after the adapter records successful cleanup and `returned` may
`journal.read_output(unit)` read them back. Reopening validates the event chain
and output identity. Held or unfinished attempts cannot replay a saved candidate.
Reading old bytes is not current source validation, review approval or another
execution. Output storage failures withhold the result. Stored bytes are base64
encoded, not encrypted; they may contain sensitive material in non-test use.

`journal.inspect(unit)` reports retained state and whether a dispatch was reserved.
It never launches or repairs a task, and `retry_authorized` is always false.
Coordination uses the workspace lock, so first use can create lock metadata.
Malformed evidence raises for operator investigation rather than being marked
complete. A `held` result still needs review; there is no automatic retry path.

## Host wiring

For stable logical IDs across host restarts, use [WorkerTasks](WORKER_TASKS.md).
It adds task-to-unit mapping, current per-action authorization checks and explicit
retirement; raw per-unit broker invocation alone does not provide that behavior.

These variables must come from trusted operator configuration, never model output:

```python
journal = WorkerJournal(workspace_root)
broker = ProfileBroker(journal, host_invoke, argv=host_command,
                       uid=worker_uid, gid=worker_gid, timeout=60)
worker = IsolatedWorker(host_command, broker=broker, record_event=journal,
                        uid=worker_uid, gid=worker_gid, timeout=60)
```

`host_invoke` must authenticate/authorize administrative execution and enforce the
bounded streaming/deadline contract from [IsolatedWorker](ISOLATED_WORKER.md).
The allowlist is in-process request validation, not an OS privilege boundary or
authentication service. A hostile same-account writer or host callback can rewrite
records/configuration or bypass Python entirely; hashes do not solve that threat.
Do not grant the worker access to the broker, metadata, sudo or service manager.

## Evidence and remaining scope

Eleven local tests cover reopen/result replay, duplicate dispatch rejection,
command/input/identity tampering, persistence failures, uncertain start reservation,
history/output damage, idempotent event delivery, two-process reservation and
cross-profile stop denial. An explicitly approved temporary-service integration
uses these components for successful shadow review, output overflow and runtime
expiry; the successful result is read through a new journal instance.

Still needed for operational adoption: authenticated host transport and deployment
configuration, logical task-to-run mapping/reconciliation UI, storage access and
retention policy, bounded host filesystem I/O, stronger crash/fault coverage, live
model/provider connection and late-start cancellation fencing. These additions
do not declare all of stage 1 complete or weaken later adoption criteria.
