# Worker evidence retention and admission (unreleased)

Policy: preserve evidence, and stop admitting new logical work before unbounded
task-count growth. There is no automatic expiry, deletion, compaction or recycling
of a logical ID. Completed, cancelled and retired tasks all remain retained.

`WorkerTasks(..., max_retained_tasks=1000)` accepts an integer from 1 to 10000.
This is trusted host configuration, not a worker/client-controlled field. Every
host sharing a workspace must use the same value. No policy file or running host
configuration is changed automatically by the library.

Under the same workspace lock as new mapping creation, admission counts distinct
task identities represented by mappings, cancellation/retirement files or attempt
directories. Tombstone-only identities still occupy capacity. Unexpected names,
wrong file kinds, unsafe paths and excess entries fail closed. The scan is bounded;
at capacity, a new execution raises `worker_retention_limit` before creating its
mapping or invoking any broker. Unrecognized storage raises
`worker_storage_needs_attention`. Two same-policy hosts cannot consume the final
slot twice because the check and mapping write share one lock.

Existing task replay, inspection, cancellation and retirement bypass *new-work*
admission. Lowering a host's limit below existing use does not delete records or
disable recovery. Other identity/permission/integrity checks still apply. A
cancelled or retired task never frees a slot or becomes eligible for automatic
reuse. An operator must not delete tombstones to get around this boundary.

This is a **task-count limit, not a disk-byte quota or reserved recovery space**.
It does not limit unrelated files, direct standalone WorkerJournal use, policy
history or review history. Permission checks and per-record limits are not a
substitute for total storage accounting. Different host configurations can weaken
the effective admission bound; configuration consistency is the trusted host's
responsibility, not an enforced distributed policy service.

## Byte accounting and free-space admission

New-work admission also checks all regular files beneath `.yeoul-mcp`, including
worker, review and policy history. `metadata_usage` returns only logical bytes,
entry count and filesystem free bytes; it does not read file contents or expose
paths. Traversal is bounded to 50,000 entries and depth 16 by default. Symlinks,
hardlinks, special files and unreadable or oversized scans deny new admission.
The scan runs under the same cooperative workspace lock as new mapping creation.

Trusted host constructor settings are `metadata_high_water_bytes` (default 256 MiB)
and `min_free_bytes` (default 64 MiB). At/above the byte high-water mark or below
the free-space floor, a new task is rejected before mapping or broker invocation.
These are observations/admission thresholds, **not allocation reservations or
hard quotas**: an admitted task may subsequently exceed the high-water mark, and
other applications can consume free space immediately after inspection. Logical
file lengths do not equal physical block allocation or include directory overhead.

Existing replay, inspection and cancellation are not additionally blocked by this
admission check. They can still fail from genuine I/O errors or a full disk; the
check does not reserve space for recovery. Whole-project files outside
`.yeoul-mcp`, direct standalone journal writes and noncooperating writers are not
constrained. Cross-host policy consistency, protected archival/restoration and a
real recovery-space reservation remain outstanding. No preallocation, OS quota,
filesystem permission change or automatic cleanup is installed by this feature.

At capacity, reject new work and ask an operator to review capacity/retention.
Do not automatically raise the limit, erase evidence or begin a new task to retry
uncertain work. Protected archival/export, total byte accounting, recovery headroom,
integrity verification after restoration and any approved cleanup mechanism remain
outstanding. No existing records were purged to implement or test this policy.

Regression evidence: existing replay/recovery at capacity, cancelled-slot retention,
no new mapping/broker on rejection, invalid policy values and unknown storage,
and two actual host processes competing for the last slot. These tests use a
synthetic transport; the separate opt-in service suite covers real execution.

Existing metadata copies can be [compared read-only](EVIDENCE_COMPARE.md) before an
operator plans restoration. This does not create, encrypt, restore or authorize a
backup, and it does not validate the separate business archive's contents.
