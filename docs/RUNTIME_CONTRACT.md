# Yeoul stdio MCP runtime contract

Yeoul keeps its 12 business tools and adds 3 workspace tools in v0.4.0; it delegates business decisions to the existing
harness. Projects, arcs, tickets, summaries, bindings and loop state remain files.
The MCP boundary adds permission checks, cooperative serialization and durable
operation receipts. Receipts are control metadata, not a business ledger.

Start with the [workspace guide](WORKSPACE_GUIDE.ko.md): `yeoul setup` saves an
independent product profile; `yeoul serve` applies it. Mirror and LaneStack are optional.

## Modes and capabilities

Without `YEOUL_MCP_ROOT`, the server remains a **trusted local tool runner** and
prints a warning to stderr at startup. Existing calls without an operation ID keep
working. Paths and subprocesses have the server account's authority. There are no
managed permission, retry or concurrency controls in this mode. Supplying an
`operation_id` without managed mode is refused.

Managed mode is opt-in through the server's environment:

| Variable | Contract |
| --- | --- |
| `YEOUL_MCP_ROOT` | Explicit absolute existing workspace directory; filesystem roots, traversal and linked roots are refused. Empty is an error, not trusted mode. |
| `YEOUL_MCP_ALLOW_WRITE=1` | Enables mutations. Unset or any other value denies them. |
| `YEOUL_MCP_WRITE_TOOLS` | Optional comma-separated allowlist of mutating tool names. Unset permits all nine when writes are enabled; empty denies all; unknown names are refused. |
| `YEOUL_MCP_ALLOW_EXEC=1` | Separately enables arbitrary verification commands; still requires write permission, an allowed tool, an operation ID and an approved baseline. |
| `YEOUL_MCP_VERIFY_BASELINE` | Supervisor-configured absolute existing baseline JSON under `ROOT/.yeoul-approved/`. Required for managed verification. |
| `YEOUL_MCP_VERIFY_BASELINE_SHA256` | Hash checked at every verification. Set by product approval; optional only for legacy environment configuration. |
| `YEOUL_MCP_READ_LEDGERS` | JSON array of exact absolute ledger files, granting read-only ledger inputs, not external writes or arbitrary command authority. |

The nine mutations are `yeoul_new`, `arc_open`, `arc_ticket`, `loop_guard_init`,
`loop_guard_tick`, `arc_close`, `arc_prereg`, `build_handoff` and `verify_gate`.
Each has an optional `operation_id: str | None` in its MCP schema for compatibility;
managed mode requires it at runtime. `verify_gate(revert=False)` is still a mutation
because verification executes commands. IDs are 1–128 ASCII letters, digits,
underscores, dots, colons or hyphens, starting with a letter or digit.

`status`, `arc_list` and `ralph_gate_check` are read-only business operations. They
may create `.yeoul-mcp/` and its persistent lock file; they do not create receipts,
execute TODO verification, initialize loops, or write business state. Managed
Python children have bytecode caching disabled. Fixed, trusted harness subprocesses
are necessary for these tools and do not require `ALLOW_EXEC`.

Configuration belongs to the supervisor. These switches are not per-caller
identity or role authentication: everyone using one server has its capabilities.
This change does not activate managed mode or modify client configuration.

## Path and execution scope

Managed relative paths resolve against the selected workspace; `workspace="."`
means `YEOUL_MCP_ROOT`, independently of the server's launch directory. Workspaces
must already exist inside the root. Names, slugs, roles and relay names use a
restricted ASCII identifier alphabet, preventing path and option injection.

Explicit paths and `YEOUL_PROJECTS`, `YEOUL_INDEX`, `YEOUL_LEDGER`, and
`YEOUL_CLOSED_REGISTRY` paths are checked. Managed defaults stay inside the selected
workspace, including the closed-question registry. `.prereg` ledger references,
archive destinations, and paths selected through script globs are covered by a
conservative workspace scan. External ledger references require an explicit exact-file
read grant; there is no implicit exception for a nearby Mirror workspace. `arc_close` disables its optional
external `am record` hook in managed mode, even if `am` is on PATH. Its local
knowledge-index update remains part of the locked operation.

The scan rejects symlinks, Windows reparse points/junctions, hardlinked files and
special files. `..`, control characters and ambiguous alternate path syntax are
refused. This deliberately includes unrelated linked files anywhere in the managed
workspace. The scan stops and refuses at 20,000 entries or five seconds; choose a
small dedicated workspace. The control directory is checked separately rather than
recursively scanning historical receipts. Nested managed roots are refused when
their control directories are present; provision non-overlapping roots.

`.yeoul-mcp`, `.yeoul-approved` and `.yeoul-workspace.json` are reserved from tool-selected business paths.
On POSIX the control directory must belong to the server UID and have no group or
other permissions (created as 0700). On Windows, the supervisor must provide
equivalent restrictive ACLs; the Python stdlib cannot verify those ACLs here.

Runtime code, Python/Bash, `YEOUL_BIN`, interpreter overrides, executable search
paths and installed dependencies must be supervisor-controlled. Managed children
remove shell startup injection variables, exported Bash functions, and Python path
injection variables. That is defense in depth, not an executable allowlist or an
OS sandbox. The worker must not be able to rewrite the runtime or its environment.

For verification, the supervisor creates and reviews a baseline using the existing
`verify-baseline` CLI and configures its approved path. An explicit `baseline_path`
argument must match that configured file. Baseline content/path and TODO criteria
are checked by the existing verification gate before commands execute. Keep the
baseline **and test implementations outside worker write permissions**, using OS
permissions or separate identities. The reserved directory prevents ordinary MCP
path selection; it cannot constrain arbitrary shell commands. Baseline approval
does not itself validate that a command is safe. Commands run with the server
account's full filesystem/network/process authority, and may contain indirect
paths. Review their dependencies and forbid detached/background work operationally.

## Locking and retry protocol

Every managed call holds an exclusive workspace lock through validation, script
execution and receipt completion. The lock uses `fcntl.flock` on POSIX and
`msvcrt.locking` on Windows, plus an in-process mutex. Acquisition waits at most
five seconds. A persistent lock file is never deleted based on a PID or age.
Kernel locks release when the owning process exits. The existing `.close.lock`
directory and gate behavior are preserved.

Mutations follow this sequence:

1. Check current capabilities, safe paths and approval configuration under the lock.
2. Compare the operation ID with the journal in `.yeoul-mcp/`. Its SHA-256 filename
   is only a safe lookup key, not authentication. The request fingerprint includes
   the tool, default-expanded arguments, root, workspace and relevant Yeoul
   environment; permission switches are checked separately on every call.
3. Persist an active-operation pointer, then its pending receipt, flushing both
   before launching the harness. A crash between these writes leaves a missing
   receipt that blocks all subsequent calls for reconciliation. JSON writes use temporary files and atomic replacement;
   POSIX also fsyncs parent directories. Failure here prevents execution.
4. Persist the completed response after the harness returns an ordinary exit code.
   Ordinary gate refusals are completed responses too. The initial and replayed
   response use the same key order for identical MCP text content.

Same ID and same request return the recorded completed response without rerunning
the harness. Changed arguments, tool or fingerprinted configuration return
`operation_conflict`. Current security checks still apply to replay; an archived
original path may be absent, but a newly introduced unsafe link or revoked
capability causes refusal. The response is historical, not a fresh state check.
Use a new ID for each intentional phase of two-phase `arc_close`, and for a new
attempt after editing a summary that received a completed gate refusal.

A pending receipt is never retried automatically, even if no effect is visible.
Timeout, launch uncertainty, signal exit, failure to persist completion or process
crash can leave partial effects. They require reconciliation. A pending active
operation blocks other IDs **and read tools**, since a surviving child may still
be writing. Receipts reject duplicate keys, nonfinite JSON numbers, malformed
schemas and mismatched request fingerprints. Damaged metadata fails closed.

The outer script deadline is 120 seconds, with a bounded five-second pipe cleanup
after timeout. POSIX kills the outer process group; Windows kills the direct child.
Nested process groups and escaped descendants may survive, including subprocesses
started by an approved verification command. Verification interruption now returns
124 immediately without executing later commands or rewriting TODO checkboxes.
Output fields are capped at 65,536 characters with `output_truncated`; capture in
memory itself is not byte-bounded. Request/context JSON is limited to 1 MiB and
receipt reads to 4 MiB. Historical receipts are not automatically pruned.

These are cooperative local-filesystem contracts, **not exactly-once execution**.
POSIX receipt fsync improves crash durability, but business scripts do not form a
transaction with the receipt. Power loss, storage failures, restored backups and
filesystems with unreliable locking/rename semantics require reconciliation.
Windows directory-entry durability is weaker because stdlib directory fsync is
unavailable. Use one intact control directory shared by all cooperating instances.

## Reconciliation and limits

There is deliberately no worker-facing unlock, retry-pending, reset or receipt
editing tool. On `reconciliation_required`, stop issuing mutations and do not
invent a fresh ID to bypass the receipt. A supervisor must stop affected servers,
identify and stop surviving children, inspect the pending receipt and actual files
(including `.close.lock`, archive, index and any command effects), and restore a
consistent state from evidence. Keep the pending receipt as evidence. Only after
that investigation may the supervisor clear the active pointer to resume unrelated
work; the pending ID must remain non-retriable. Corrupt metadata needs restoration
from a trusted copy or a separately audited migration. Do not delete the lock file
while a process might hold it.

The new `yeoul` product CLI dispatches business operations through the same boundary
as MCP. Raw checkout shell/CLI tools, older MCP servers, trusted-mode servers, other software
(including Mirror) and editors **do not participate in the Yeoul MCP lock**.
There is no cross-product transaction or shared Yeoul/Mirror lock. Concurrent
out-of-band changes, symlink swaps after validation, mutable hardlink aliases,
mount/bind aliases, and a hostile owner rewriting receipts are outside this
cooperative boundary. Protect the workspace and control directory accordingly.

The workspace tools are `workspace_prepare` (persist a task), `workspace_execute`
(execute/replay its ID), and `workspace_tasks` (inspect). They cannot configure
permissions, approve commands or recover interrupted work. CLI-only `yeoul recover`
defaults to inspection; explicit acknowledgement requires an audit note and
stopped-children attestation. It persists a tombstone before clearing the active
pointer, including when the old receipt was never written. The old ID cannot execute
again. This records an operator judgment, not automatic proof of consistency.

Two small harness fixes also apply to direct CLI use: `loop-guard init` refuses to
reset existing state; `arc-open` reserves its directory atomically and chooses a
unique suffix on same-second collisions. Those fixes do not make the other CLI
mutations concurrent-safe or put them under the MCP lock.

## Verification

Run `python mcp/tests/test_runtime_contract.py` for managed permissions, strict
receipt parsing, policy rechecks, real simultaneous processes, replay/conflict,
crash-before/after-effect, timeout, bounded lock contention, links, approved
verification, and actual stdio tool schemas/calls. The stdio test has a 30-second
deadline; a hang is a failure, not a skipped pass. In environments that block SDK
stdio/event-loop wakeups, run the same test outside that sandbox.

Also run `python tests/test_hardening.py`, `bash tests/test_gates.sh`, and the three
existing scripts in `mcp/tests/`. Python >=3.10 and the existing `mcp/setup.py`
wheel/sdist harness bundling remain unchanged. Windows locking code needs native
Windows validation; POSIX execution cannot certify Windows behavior.

Implementation validation on Linux/Python 3.10: 21/21 new runtime tests (including
real stdio on the host), 26/26 existing hardening tests, 72/72 shell gate checks,
5/5 CLI/MCP integration tests, 8/8 subprocess checks, and 8/8 server-version checks
passed. The existing `setup.py` built an sdist and then a wheel from that sdist;
the extracted wheel ran managed scaffolding and identical replay away from the
checkout without installation. The explicit MCP CI job now invokes the runtime
suite on its Linux/Windows matrix. Native Windows results are not claimed here.
