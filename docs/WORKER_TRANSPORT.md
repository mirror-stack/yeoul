# Bounded worker command transport

For interactive request/response exchanges, see the separate
[bounded duplex JSONL transport](JSONL_TRANSPORT.md). Neither transport proves
remote model cancellation or disables model tools on its own.

Status: unreleased, opt-in Linux transport layer. No operational loader, live model
or credential connection is configured automatically. This is not an OS sandbox.

`yeoul_mcp.worker_transport.CommandWorker(argv, cwd=..., env=...)` is a callable
adapter for `shadow_workflow.run_shadow`. The host selects the absolute executable,
argument list, existing absolute working directory and explicit environment. No
shell interpolation or ambient environment inheritance is used. Source text must
never select these arguments. An empty environment is the default.

## Implemented limits

Defaults: 60-second wall deadline, 5-second leader-reap allowance, 64 KiB each for
stdout/stderr and 4 MiB input. Byte limits are checked while streaming nonblocking
pipes, not after unbounded `communicate`. Oversize output is rejected rather than
truncated into an accepted proposal. Input is immutable bytes and must fit before
process launch. Input write, stdout and stderr draining proceed concurrently.

Only a zero-exit process with supplied input yields stdout bytes. A broken input
pipe, timeout, excess output, failed exit or launch failure raises a named
`WorkerTransportError`. The shadow workflow translates that reason to needs_review;
it does not retry, invoke a fallback, or verify a partial proposal. Format/schema
checks remain the separate shadow reply parser's responsibility.

The process starts in a new session with inherited descriptors closed. On normal
completion and failure the adapter sends SIGKILL to its process group, then reaps
the leader within the cleanup allowance. Linux `waitid(WNOWAIT)` observes exit
without reaping first, keeping the leader PID reserved until group signalling.
Failure to reap is reported as worker_cleanup_incomplete, not successful work.
Rejected stdout/stderr are not exposed as diagnostic text, which avoids leaking
arbitrary child output through error messages. Durable diagnosis is still host work.

## Limits that remain

- No CPU, memory, process count, disk quota or syscall restrictions are supplied.
  This layer alone is not the completed resource/isolation launcher in the plan.
- A descendant that deliberately leaves the process group can escape group cleanup.
  Use a reviewed isolation launcher; do not claim arbitrary-process containment.
  The tested Bubblewrap fixture uses its own namespace and die-with-parent controls.
- `Popen`/kernel operations themselves are not forcibly interruptible by this
  synchronous deadline. This deadline does not bound blocked kernel I/O or a host
  process that another component independently reaps.
- The cleanup deadline proves leader reaping only. The tests observe suppression
  of delayed side effects by same-group children, not universal child enumeration.
- Python provider callbacks remain trusted synchronous callbacks with their own
  host-enforced timeout needs. This adapter bounds command workers, not every
  callable accepted by the workflow.
- Other platforms fail with unsupported_worker_transport. The rest of Yeoul is not
  silently switched to a different launcher; skipped tests are not support proof.
- No audit store, safe filesystem candidate importer, approval or commit integration
  is added here. Readiness remains point-in-time and non-authoritative.

## Verification

`python -B mcp/tests/test_worker_transport.py` covers exact multi-chunk input/output,
both output bounds, no input consumer, no response, failed exit, missing executable,
invalid limits, no ambient environment and delayed same-group child effects after
timeout and normal leader exit. It creates only temporary synthetic workspaces.

The optional [isolation test](WORKER_ISOLATION.md) uses this transport to launch its
synthetic Bubblewrap worker and route correct/incorrect replies through shadow.
Wheel archive and temporary-install tests include the transport suite. Running
the latter still requires installation approval where applicable.
