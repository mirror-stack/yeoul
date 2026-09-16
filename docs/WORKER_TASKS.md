# Logical worker tasks and restart handling (unreleased)

`yeoul_mcp.worker_tasks.WorkerTasks` connects a host-assigned logical task ID to
one retained isolated-worker unit. This supplements the per-unit reservation in
[WorkerJournal/ProfileBroker](HOST_WORKER.md). It is not a listener, installed
service, account-authentication implementation or business execution approval.

## Contract

The host supplies the workspace root, fixed command/UID/GID/runtime profile,
bounded authorized invocation transport and `authorize(task_id, action)` callback.
Actions are `execute`, `inspect`, `retire` and `cancel`; the callback must return the boolean
True for the current caller/policy. The callback must authenticate the caller
outside this module and must not trust an identity field from a model or request.

`execute(task_id, payload_bytes)`:

- Under the workspace lock, checks authorization and persists a task-to-unit
  mapping before any worker launch. The mapping binds task ID, profile digest,
  input SHA/size and unit; its record is preserved under `.yeoul-mcp/worker-tasks`.
- Rechecks authorization and retirement inside the dispatch-reservation lock.
  Retirement before that reservation prevents a launch. Authorization is checked
  again immediately before result delivery.
- With an existing matching completed task, validates the journal/output and
  delivers identical retained bytes without another broker/service invocation.
  A changed input or profile conflicts; revoked authorization denies delivery.
- With a held, pending, mapping-only or damaged attempt, does not generate a new
  unit or automatically retry. Two processes sharing a logical task cannot both
  create its first execution; a concurrent reader may be held until completion.

`inspect(task_id)` checks current authorization and returns retained status. It
never approves retry or certifies business completion. Missing/corrupt metadata
is not interpreted as permission to execute.

`retire(task_id, note=..., children_stopped=True)` requires separate current
authorization and an operator inspection attestation. It retains a tombstone
without editing the original mapping, journal or candidate. Completed delivery
is not an interrupted task to retire. A retired logical ID cannot be reused.

Retirement is **not cancellation or repair**. It does not stop a service or fence
an already dispatched/queued start request. If work returns after retirement,
its retained result is not delivered through that logical task. The operator
must actually inspect services/children before attesting that they stopped.

## Integration example

New-work admission defaults to 1000 retained logical tasks per workspace. See
[retention and its limits](WORKER_RETENTION.md) for trusted host configuration,
capacity rejection and preservation of existing recovery operations.

For a human-readable, read-only authorized snapshot, see the
[recovery view](RECOVERY_VIEW.md). It does not expose cancellation actions or deploy a server.

The host chooses all configuration and the stable task ID; the model does not:

```python
tasks = WorkerTasks(workspace_root, host_invoke, argv=host_command,
                    uid=worker_uid, gid=worker_gid, authorize=host_authorize)
result_bytes = tasks.execute("ticket-123-worker", frozen_input_bytes)
status = tasks.inspect("ticket-123-worker")
```

The same call after a host restart returns the retained result if it completed
and policy/input/profile still match. Original input bytes are not stored by this
mapping layer; the host must retain or reconstruct them for matching delivery.
This is not source freshness: when used through `run_shadow`, the existing fresh
source/provider checks still run before review promotion. Historical output is
never automatically applied to business state.

## Explicit cancellation request

`cancel(task_id, note=...)` requires the separate `cancel` permission; execution,
inspection and retirement grants do not imply it. It first persists a cancellation
intent under the workspace lock. That intent blocks future dispatch reservation,
execution and retained-result delivery for the logical ID, including after restart.
It does not delete the mapping, journal, proposals or retirement records.

Only a unit bound to this task/profile and a durable dispatch reservation may be
stopped through the existing allowlist broker. Each attempt writes a request before
host I/O and a separate result afterward; up to 64 attempts are retained. A failed
record write before host I/O prevents the stop request; interrupted requests remain
visible on disk. Arbitrary broker error strings are not retained. Repeated explicit
calls can observe/stop again but cannot start work or clear the cancellation intent.

Results distinguish `dispatch_not_reserved`, `absence_observed` and `unconfirmed`,
with a bounded stage label. Every result has `cancellation_complete=False` and
`retry_authorized=False`. Inspection shows `cancel_requested` and needs attention.
Absence is not proof that an already dispatched late start cannot arrive. This is
not a live per-worker revocation handshake, completed reconciliation or business
rollback. Cancellation can also withhold future delivery of already completed
output; it cannot retract bytes already delivered to a caller.

`inspect` includes a read-only `cancellation` report. It validates the intent,
task/profile mapping identity, filenames, request/result pairing, schemas and
closed state vocabulary under the workspace lock. Missing result files appear as
`observation_missing`; an intent with no attempts is `intent_only`. Corrupt records,
orphan results and unexpected/excessive files appear as `evidence_unreadable` with
needs-attention status, not completed cancellation. Raw notes/errors are omitted.
The report neither calls the broker nor edits evidence. It lists all attempts
without treating wall-clock order as reliable proof of the latest result. A later
absence observation does not erase an earlier unresolved attempt.

The report also distinguishes a `present` versus `missing` bound revocation marker.
A missing marker after a stored intent identifies an interruption before live launch
revocation; result delivery remains blocked by the intent. A marker with a different
task/unit/mapping or invalid schema is unreadable evidence, not a valid completion.
Marker presence proves retained local evidence only, not that every running process
has consumed it or stopped.

Malformed retained cancellation evidence blocks further stop attempts until an
operator investigates it. The 64-attempt limit counts requests, including those
with no result; crashes cannot double the advertised limit. Permission is checked
again before inspection returns. This is a diagnostic interface, not yet a recovery UI
or permission to delete/repair records.

```python
observation = tasks.cancel("ticket-123-worker", note="Operator requested stop")
# Keep observing/reconciling; do not equate absence_observed with safe retry.
```

## Evidence and remaining limits

Twenty-five Linux contract tests cover restart delivery, changed input/profile,
authorization revocation, uncertain start, mapping-only interruption, operator
retirement and its race with dispatch/result delivery, and two real host processes
sharing one task, cancellation before/after dispatch, failed observations, persistence
failure and explicit cancellation permission. The opt-in service integration connects an actual isolated
synthetic task to shadow review and reopens its mapping for no-new-call delivery.
Additional recovery cases cover missing observation after persistence failure,
read-only restart diagnosis, corrupt/orphan observations and 64 incomplete attempts.
New task executions use the [version-3 live launch gate](ISOLATED_WORKER.md#task-bound-launch-revocation-version-3).
Explicit cancellation writes the unit's persistent revocation marker before host
stop I/O. Tests run the gate in a real process before/after cancellation and reject
missing/changed permits. This does not turn absence observations into completion.
A four-case real SIGKILL test terminates a synthetic host process immediately after
the durable intent, revocation marker, request or result write. Reopening reports
the interruption, denies execution and permits separately authorized re-observation
without overwriting prior bytes. This test uses a fake service transport: it does
not claim host-death cleanup of real systemd children or power-loss durability.
Separately, the opt-in [real host-death service test](ISOLATED_WORKER.md#real-host-death-recovery-evidence)
does exercise a surviving synthetic worker, reopened-host execution denial and
exact-unit stop without changing historical records. Its narrower evidence does
not imply power-loss durability or completed reconciliation.

In-process callbacks are trusted code. The optional [WorkerAccess](WORKER_ACCESS.md)
adapter supplies Linux local connection identity and per-task account/action grants.
Neither layer deploys a listener, remote authentication, an operational policy or
a recovery UI. Host callback I/O is synchronous and not forcibly time-bounded here.
Same-account metadata rewriting and logical duplication under deliberately new
task IDs are outside this layer's protection. Resource-policy versioning, late-start
fencing, storage policy and operational lifecycle integration remain to be completed.
