# Opt-in isolated worker adapter (unreleased)

`yeoul_mcp.isolated_worker.IsolatedWorker` is a host-only callable compatible with
`run_shadow`. No MCP tool, default loader, privileged daemon or operating-system
configuration is installed or enabled. Yeoul remains independent of Mirror,
Mother and LaneStack.

## Host interface and trust

The optional [durable journal and profile broker](HOST_WORKER.md) now supply local
event/result persistence and exact request allowlisting. They still require an
authenticated, authorized host transport; they do not install a privileged daemon.

Construct with a fixed worker argument list under `/usr/bin`, a non-root UID/GID,
an authenticated `broker(argv_tuple, payload_bytes, timeout_seconds) -> bytes`,
and `record_event(json_bytes)`. The broker must bound stdout/stderr to 64 KiB each,
apply the passed deadline and raise on nonzero exit. It receives only the fixed
systemd-run/systemctl requests constructed by this adapter. The event sink must
durably retain each event before returning. Both are trusted host integrations,
not interfaces to hand to the worker or to accept from a model response.

The library does not implement sudo authentication or a security boundary around
arbitrary Python callbacks. The opt-in integration test supplies a privileged test
broker using existing administrator access. Do not publish that generic sudo
bridge as a production API; production still requires a narrowly authorized broker.

## Execution contract

1. Reject unsupported platform, root identity, unmounted executable and oversize
   command/input. Mint a unique service name and refuse collisions without stopping
   the existing unit.
2. Persist a manifest and start-request event. The manifest binds command, UID/GID,
   input SHA/length and fixed resource limits. Worker bytes are not stored in the
   events. Command arguments are stored, so they must not contain credentials.
3. Ask the host to start a transient non-root service: CPU 0.5 core, memory 128 MiB,
   swap zero, tasks 16, temporary storage 16 MiB, runtime 60 seconds by default
   (explicit host integer 1–300 seconds), stop timeout three seconds.
4. Before executing the worker, trusted bootstrap code checks UID/GID, actual
   cgroup CPU/memory/swap/tasks values and filesystem capacity. Missing or different
   limits fail; accepted systemd properties alone are not considered proof.
5. Execute Bubblewrap with separate namespaces, dropped capabilities, cleared
   environment, read-only software and private proc/dev. Only the bounded tmpfs
   is writable at `/work`. Home, workspace, credentials, host sockets and cgroup
   control paths are not mounted. Input arrives through stdin; output proposals
   use stdout. Files in `/work` are ephemeral and are not imported.
6. On success or failure inspect the specific unit, stop it if still present and
   observe its removal. Persist lifecycle/output-hash or held events. Return bytes
   only after successful execution, confirmed cleanup and successful audit writes.

When the client call failed, `cleanup_absence_observed` is deliberately weaker
than `cleanup_confirmed`: seeing no unit does not fence an already queued manager
request. No proposal is returned in that case. An uncertain cleanup becomes
`isolation_cleanup_incomplete` and must be investigated; do not auto-retry.
There is no raw-execution fallback. Resource errors, output overflow, audit failure
and failed cleanup route to `needs_review` through the existing shadow flow.

`ready_for_review` remains NONE authority and NOT_PERFORMED business execution.
This adapter does not approve a proposal or bypass the [reviewed write contract](REVIEWED_EXECUTION.md).

## Verification and remaining work

- Nine default contract tests cover manifest/limits, audit-before-launch, timeout
  stop request, uncertain cleanup, collision, invalid identity/executable and
  durable stage diagnostics (including legacy record compatibility).
- The first opt-in host integration test covers three original scenarios: isolated
  synthetic [4,7,6] proposal through shadow verification, output overflow hold,
  and service runtime-limit hold. Host events are durably written in a temporary
  test directory. No live model, provider server or real business data is used.
  A fourth scenario now adds [logical task mapping](WORKER_TASKS.md), shadow review
  and reopening the host mapping to deliver the retained result without a new call.
- A second opt-in test observes a loaded synthetic service, requests cancellation
  through WorkerTasks, observes absence and verifies withheld delivery. This is
  evidence for exact-unit stop integration, not queued-start fencing.
- Offline wheel/temporary-install checks include the module and nonprivileged
  contracts. Privileged integration skips unless explicitly approved and enabled
  with `YEOUL_RUN_RESOURCE_TESTS=1`; regular CI does not enable it.

Still incomplete: production host transport authentication/authorization, real model and
source/provider integration, operational storage configuration/recovery UI, queued
start fencing, broader malicious-child/host-death scenarios and other platforms.
The callback broker must genuinely enforce streaming limits; post-return size
checks cannot protect against an unbounded broker. Host event-sink I/O has no
forced timeout in this synchronous API. Read-only software mounts are not a kernel
exploit defense or an immutable software supply chain. See the separate
[resource-limit evidence](WORKER_RESOURCE_LIMITS.md).

An unconfirmed cleanup now retains a closed-vocabulary `cleanup_stage`:
`initial_show`, `stop`, `final_show`, or `still_loaded`. It contains no raw
exception text or worker data. Historical records without this field remain
readable. All these states still withhold proposals and never authorize retry.
The integration harness also reports bounded control-operation observations on
overflow assertion failure; it never includes proposal/input bytes in this trace.
The previously observed intermittent cleanup failure remains unresolved unless
its cause is reproduced and specifically verified; repeated passes alone do not
prove resolution.

## Expiring start tickets (partial late-start protection)

New execution manifests use version 2 and include a host-created `start_ticket`:
the Linux boot ID, issuance on CLOCK_BOOTTIME and expiry exactly five seconds
later. The clock includes suspend and does not depend on adjustable wall time.
The host checks it inside the dispatch-reservation lock; the fixed service
bootstrap checks it before resource checks and again before launching Bubblewrap.
Invalid, future, expired and other-boot tickets fail closed. There is no refresh
or retry of a reserved logical task. Slow startup can therefore hold valid work;
five seconds is an initial conservative policy, not a measured universal optimum.

For standalone version-2 requests this bounds acceptance of stale requests,
**not an atomic cancellation fence**.
A process paused after its last check can still resume into exec; retirement or
revocation inside the valid window does not revoke a dispatched ticket. It is not
proof that a queued request is absent or children stopped. A host-owned live
launch/revocation handshake and lifecycle reconciliation remain required before
claiming full late-start protection. Legacy manifests remain inspectable and
completed retained outputs remain readable, but the broker does not launch a new
version-1 request. Old records are not upgraded or overwritten.

Tests cover exact expiry, future issuance, boot mismatch, malformed/extended
tickets, wall-clock independence, a real standalone bootstrap refusing an expired
ticket before payload setup, and expiry before durable reservation. The opt-in
service test adds a fifth scenario delaying dispatch by 5.1 seconds and checking
failure/no returned result. That last outcome alone is not proof of its error cause.

## Task-bound launch revocation (version 3)

New WorkerTasks executions add a `launch_directory` fixed by the host journal's
unit directory. The broker rejects a different directory and stores a manifest-bound
`launch.json` before dispatch. The service binds only that directory read-only at
`/run/yeoul-launch`; the eventual Bubblewrap worker cannot access that mount.
The fixed bootstrap checks the permit and `launch.revoked.json` both before resource
checks and immediately before exec. Missing, changed, unreadable or revoked permits
deny launch. Reads are size-bounded, no-follow and reject nonregular permit files.

Explicit `WorkerTasks.cancel` preserves its logical cancellation intent, then
durably creates the unit revocation marker before stop/observation I/O. Thus a
late service reaching the gate after cancellation is denied even within the
five-second ticket window. A service already past the gate requires the exact-unit
stop path; the marker alone does not kill it. Crashes between intent, marker and
stop remain uncertain and never receive `cancellation_complete=True`. Repeated
operator cancellation can finish writing the marker and retry observation.

Current gate ownership requires the same host and bootstrap UID. Other worker
accounts, unsupported path characters (including spaces), hidden/unreadable host
roots or unavailable bind support fail closed; no permissions are changed to
make them work. The host and its files are trusted, not protected against a
same-account attacker. This is local filesystem revocation, not a remote service,
continuous authorization subscription. The trusted [WorkerAccess configure API](WORKER_ACCESS.md#policy-changes-and-existing-execution)
now persists revocation on execute-grant removal/owner transfer, but does not
automatically stop a running service or watch external file edits.
Standalone v2 calls keep their narrower ticket-only contract;
historical records remain readable. Full cancellation/reconciliation acceptance,
host-death races and the recovery UI remain outstanding.

## Real host-death recovery evidence

An additional opt-in integration test launches a synthetic sleeping Python worker
in its actual restricted transient service. It identifies the exact worker argv
inside that unit's cgroup, SIGKILLs only the fixture host process, and confirms the
service remains active afterward. A reopened WorkerTasks host sees the retained
`start_requested` state, refuses to launch again, records cancellation and stops
that same validated unit. Existing evidence bytes remain unchanged and final
LoadState is `not-found`. The fixture also attempts exact-unit cleanup on failure.

This tests one Linux host-death point with a real surviving worker, not power loss,
all instruction-level races, escaped children, kernel attacks or disappearance of
every possible queued start. Cancellation remains explicitly incomplete pending
the broader acceptance/reconciliation contract. The test is disabled without the
existing explicit resource-test opt-in; it changes no installed service or policy.
