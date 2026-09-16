# Reviewed prepared execution (unreleased, opt-in)

Yeoul now has a host-only Python bridge into its existing managed write boundary.
This is not an MCP approval endpoint, a verifier, or an enabled production loader.
Existing schema-1/2 jobs and profiles are unchanged.

## Contract

The trusted host calls `workspace.prepare(root, tool, arguments,
review={"proposal": proposal_object, "requirements": check_to_provider_map})`.
Preparation writes a schema-3 record atomically under the existing workspace lock;
there is no intermediate executable unreviewed task. The host selects the actual
tool, arguments and complete requirements. Proposal text is never executed.

The host then calls `execute_reviewed(workspace, root, task_id, host_callback)`
from `yeoul_mcp.reviewed_execution`. The callback receives immutable JSON bytes
containing `job` and `binding`. Binding includes task ID, a tool/arguments digest,
the whole unsigned job digest (including snapshot and requirements), and proposal
digest. Reports from a different shadow binding cannot be silently reused: obtain
verification for this prepared binding, including the actual requested operation.

The callback returns exactly `{approved: boolean, reports: list}`. Reports use the
[review decision schema](VERIFIED_TASKS.md). Passing reports alone do not approve
execution. The callback must obtain the current authenticated complete report set
and explicit host approval, not echo a worker's selected evidence or an old cache.

For a new write, under the workspace lock, Yeoul checks the trusted callback's
decision, then recaptures target freshness before recording pending state and
calling the existing business tool. Missing approval, missing/retracted/mismatched
reports or callback failure refuse execution without creating an execution receipt.
Normal/direct calls using a schema-3 task ID cannot omit the review gate.
Existing permission, pending-reconciliation and completed-response replay rules
remain: replay of an already completed operation does not perform another write
or obtain new approval. Revocation cannot undo an already completed operation.

## Retained review decisions

Each completed host review attempt stores a separate event under
`.yeoul-mcp/reviews/`: timestamp, prepared binding, required providers, normalized
reports (including evidence references), approval boolean and routing decision.
Denials are retained rather than overwritten by later approval. Invalid/unavailable
host responses produce a sanitized failure event, without arbitrary payloads or
exception text. Normalized evidence references must not contain credentials.

The event is flushed before pending state or business writes. If audit persistence
fails, execution is refused. A successful review is not proof that execution began:
freshness failure or a crash can leave an unlinked review event. New reviewed
receipts use version 2 and require the event name and content digest. Receipt reads
validate the linked decision; missing or changed evidence requires reconciliation,
not another write. Completed replay adds no new review event. Earlier version-1
receipts remain readable without inventing retroactive evidence.

These are local durable records, not a tamper-proof external ledger. File and
directory flushing uses existing platform helpers (directory fsync on POSIX).
There is no automatic deletion, retention quota or cryptographic identity proof.
Abrupt termination inside the callback can leave no review event, but cannot have
started the business write through this boundary. Global failure/power-loss and
same-account malicious rewriting are not solved by event hashes.

## Limits and remaining work

- This is per-task opt-in. `prepared_only` still permits ordinary schema-2 tasks;
  it is not an installation-wide require-review policy. A trusted host must decide
  which tasks require review. No production profile has been changed.
- Provider authentication, live withdrawal discovery and approval UI belong to
  the host integration. The callback is trusted code, not an untrusted plugin.
  Hashes do not authenticate a same-account writer. Do not expose the metadata
  directory or this host capability to an isolated worker.
- Callback I/O must be bounded by the host. A synchronous callback has no forced
  deadline here. External withdrawal racing after the callback is not transactionally
  ordered with local writes. Workspace locking covers cooperating writers only.
- Audit records preserve normalized host claims, not the underlying provider
  evidence itself. Comprehensive new-boundary crash/recovery injection remains
  unfinished. Existing ambiguous
  receipt handling is retained; no global rollback/atomicity is claimed.
- Temporary real `yeoul_new` tests cover approval, denial, changed binding and
  arguments, changed target during review, provider failure and completed replay.
  Additional injected timeout, pending-record failure and completion-record failure
  cases check preserved ambiguity and refusal to execute again. These are local
  exception/response injections, not power-loss or all-tool recovery proofs.
  They are not proof of actual Mirror/Luna/production connectivity.

## Nine-tool integration matrix

### Shadow-to-write boundary

Three connected synthetic cases in `test_reviewed_execution.py` run the actual
shadow workflow before entering prepared execution. A passing shadow report reused
unchanged is refused and its mismatched binding is retained in the denial audit.
A freshly queried synthetic withdrawal for the prepared binding blocks project
creation despite the earlier pass. Fresh prepared verification with explicit host
approval creates the temporary project once; completed replay neither consults the
provider again nor appends another approval event.

These cases use trusted in-process fixture callbacks, not authenticated Mirror
connections. They prove binding separation and consumption of a current withdrawal,
not withdrawal discovery, network failure handling, or ordering of a remote
withdrawal racing after the callback. The host must verify the actual prepared
operation; relabeling an old shadow report with a new binding is not verification.

`mcp/tests/test_reviewed_tools.py` enumerates the runtime's exact nine mutators
and uses real temporary business commands, without installing or requiring Mirror.
For each tool it checks successful execution with changed business files, completed
replay without another invocation, and review denial with identical business bytes.
An injected interrupted response checks pending state, retry refusal, explicit
operator reconciliation, retained original receipts/audit events and retired IDs.
These injected interruptions do not model each tool's internal partial-write point.

`arc_prereg` uses a locally synthesized hash-valid ledger and substantive synthetic
spec; this tests the wire contract, not independent identity or truth. `verify_gate`
uses a supervisor-approved temporary command writing a fixed marker inside the
fixture. No production command or approval is changed.

`arc_close` is checked separately for draft generation and final archive. A real
successful final archive followed by an injected lost response leaves an ambiguous
receipt, preserves the archived business state and forbids repeating the operation.
This is not a mid-archive crash or rollback proof. For each of the nine mutators,
two separate processes prepare to execute jobs from the same predecessor. The
parent waits for both workers to be ready before releasing them. Exactly one job
completes and the other is held as stale, with one complete receipt and one
unrecorded receipt. Readiness uses bounded queue waits and child pipe-reader
threads rather than pipe selectors so the harness can run in the Windows CI job.
Current local execution evidence is POSIX only, not a Windows pass or exhaustive scheduling
coverage. In addition to the `arc_close` draft race, a separate final-archive race
checks that the source directory is moved, only one archive record and one closure
timestamp are written, and the substantive summary survives its expected title
and timestamp update. Replaying both jobs preserves all business-file bytes: the
winner returns its completed result, while the loser stays stale without a command
invocation. This does not prove rollback or atomicity across internal archive
steps. The separate test below covers the after-move checkpoint.

## Actual process death and partial archive evidence

`mcp/tests/test_reviewed_crashes.py` sends SIGKILL to its own temporary POSIX
executor after five actual persistence boundaries: review event, active pointer,
pending receipt, completed business command, and completed receipt. A fresh
process retries the same ID. An audit-only interruption can obtain fresh approval
and execute; active/pending/after-effect interruptions require reconciliation;
completed receipts replay without rewriting. Original evidence remains intact.

Three archive cases run private copies of the real `arc-close` script with one
SIGKILL checkpoint per case: immediately after moving the directory, after updating
the summary title, and after writing the archive record. After the move, thread
status remains Close-Pending and the archive record is absent. At the later points,
the thread and summary already say Closed; the last case even has an archive record.
None of these business markers is treated as proof that the invocation completed.
All three retain a pending receipt and the close lock; fresh-process retry is refused.
Explicit operator reconciliation retires the ID without changing archived files,
the original receipt or review events, or silently clearing the business lock.

For this condition, preserve the receipt, review events, source/destination trees,
summary, STATE, thread status and index before deciding how to repair. Confirm
children have stopped. Reconciliation is an operator attestation that prevents
re-execution, **not archive repair or verification success**. Restoring a known
pre-operation backup or finishing an incomplete archive needs separately reviewed
business repair work; do not run arc-close again with a new ID or remove its lock
just to make it proceed. No automatic partial-archive repair command is supplied.

Read-only `yeoul recover` diagnoses unreadable evidence, interrupted operations,
or absence of a detected active interruption. It separately flags pending task
receipts without an active marker; this is not a safe new-ID retry condition.
A corrupt task/receipt no longer
hides other inventory rows. Diagnosis does not authorize retries or relax the
strict acknowledged-recovery path. Missing review evidence still blocks that
path until restored and validated. Inventory is a point-in-time, limited view,
not a completeness or business-success certificate.

These tests cover identified process-death points on the tested POSIX host. They
do not establish power-loss persistence, Windows termination handling, every shell
instruction, escaped child cleanup after supervisor death, or external transactions.
