# Prepared target freshness

New managed mutating tasks prepared through `workspace_prepare` (or the product
CLI prepare command) bind the current target state. Preparation does not execute
business work. The existing runtime lock compares state again immediately before
the first execution. A mismatch returns `stale_precondition` without launching
the harness or creating an execution receipt. Review the changed state before
preparing a replacement task.

## What is bound

| Tool | Read/write dependency envelope |
|---|---|
| yeoul_new | Named project destination and closed-question registry |
| build_handoff | Named project, including design, archives and dev files |
| arc_open | Requested arcs directory and closed-question registry |
| arc_ticket, loop_guard_init, loop_guard_tick | Arc subtree and any linked preregistration ledger |
| arc_close | Arc subtree, linked ledger, archive destination and shared index |
| arc_prereg | Arc subtree, existing linked ledger and requested ledger |
| verify_gate | Workspace business tree, including approved verification files |

Each envelope also includes the workspace profile. The runtime's private control
directory is excluded; preparing another task must not itself invalidate business
state. File hashes and filesystem identity/change metadata detect content changes
and ordinary replacements. Directory membership is included, not parent directory
timestamps. A newly created unrelated project does not invalidate another named
project's preparation. Operations sharing an index or arc directory can conflict.

Snapshots have bounded cost: at most 20,000 queued/visited entries, 64 MiB of file
input and a five-second scan deadline. Actual read bytes are charged as well as
checking declared sizes before reading. Oversize or inconsistent snapshots are
refused, not truncated. This is conservative; large projects may need a reviewed
narrower dependency contract before adopting prepared execution.

Before the tree scan, linked-ledger discovery checks `.prereg` path components
and reads at most 64 KiB plus one overflow-detection byte. Oversize metadata is
rejected rather than silently truncated. This separate bounded read is additional
to the tree-scan budget. Scan deadlines are cooperative checks between filesystem
operations, not a hard timeout for blocked filesystem I/O. Existing same-user
external-writer race limitations still apply.

## Retry, legacy and failure behavior

- New mutating task records use schema 2 with a hashed precondition. Existing
  schema-1 records are read unchanged and retain their original, unbound behavior.
- Task inspection distinguishes `target_snapshot` from legacy/read-only records.
- Completed receipts are replayed before requiring current business-state equality.
  Replaying a historical response does not claim the current workspace still matches.
- Permission/path validation still applies to replay. Interrupted or ambiguous
  operations remain pending and require operator reconciliation, not automatic retry.
- Direct managed calls using an existing prepared ID must match its recorded tool,
  arguments and precondition. Omitting workspace_execute does not discard that binding.
- Direct calls with a new unprepared ID retain the existing low-level contract;
  raw scripts and older installed releases do not acquire this new freshness contract.
  A characterization test demonstrates this explicitly: after a workspace-profile
  change rejects a prepared request, a permitted direct call with a new ID can
  execute. This passing test documents a limitation, not universal freshness
  enforcement. The opt-in strict policy below changes this expectation only when selected.

## Opt-in prepared-only writes

Local implementation; no existing installation or profile is automatically changed.
An operator can select `--write-policy prepared_only` with `setup` or `configure`.
The default for profiles without this optional field remains `compatible`. Mode
changes retain the selected write policy; `configure` still revokes shell approval
and archives the previous profile. `doctor` reports the configured write policy,
not the policy of an already connected process. Reconnect is required to apply it.

Example for a separately approved test workspace:

```sh
yeoul configure ./test-workspace --mode discuss --write-policy prepared_only --yes
```

The profile supplies `YEOUL_MCP_REQUIRE_PREPARED=1` to the managed runner. Advanced
host integrations may supply that setting directly; values other than `0`/`1`, or
strict mode without a managed root, are refused. MCP workers cannot change the
profile through this feature. A host controlling the process environment can
disable it, so this remains a host-enforced policy, not an OS sandbox.

Inside the existing execution lock, every new mutating execution requires a
matching schema-2 prepared record and fresh target snapshot. Unprepared IDs and
unexecuted schema-1 jobs return `preparation_required`, without a new execution
receipt or business mutation. Old jobs are preserved; prepare a new task after
review instead of rewriting them. Read-only operations are unchanged.

Existing completed responses remain replayable, including pre-policy direct
operations, after current permission/path checks. Pending, retired and ambiguous
operations still require reconciliation. The policy flag is excluded from receipt
fingerprints, like existing permission flags, to preserve replay across policy
changes; it is nevertheless checked before every new execution. The original
policy checks and target freshness check cannot be bypassed by selecting strict
mode. No new approval, automatic retry or recovery bypass is introduced.

## Exact limits of the claim

An opt-in [Linux worker isolation capability test](WORKER_ISOLATION.md) separately
checks read-only source mounts and host access denial. It does not automatically
isolate any caller of the managed runtime or change the limits below.

This is a cooperative prepared-task single-execution boundary, not universal
Worker permission isolation or an atomic transaction over all files. Authorized
callers in compatible mode can still invoke low-level tools with new IDs. Same-user raw writers do not
honor the lock. A malicious actor able to rewrite task records and receipts is
outside the trust boundary. Hashes are not authentication or semantic validation.

Verification commands have arbitrary approved capabilities. The workspace envelope
does not discover their external dependencies or make external effects transactional.
Arc close can partially change multiple files; interruption uses the existing
pending/reconciliation contract, not rollback. Shared dependencies are conservatively
included; unrelated workers may investigate concurrently, while writes still use
the existing workspace lock. This change does not add parallel writer scheduling.

The read-only context shadow is a separate experimental API. Binding its packet to
the actual model transport, constraining Worker credentials, and operational canaries
remain separate integration work. Do not claim full parallel-investigation/single-
commit enforcement across every execution path from these tests alone.

Test: `python -B mcp/tests/test_freshness.py`. Includes two actual processes racing
on one target, independent projects, stale arc/ledger/index/policy, completed replay,
legacy records, scan limits and interrupted execution. Distribution tests repeat the
new contracts against a temporary wheel installation outside the checkout.
