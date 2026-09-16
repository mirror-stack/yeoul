# Existing metadata copy comparison (unreleased, Linux)

`compare_evidence(reference_root, candidate_root)` compares `.yeoul-mcp` files in
two existing, distinct, non-nested project folders. It reuses the existing layout;
it does not create a backup format, copy data, extract an archive or restore files.
Existing business archives under `arcs/_archive` remain unchanged and are outside
this metadata-only comparison. A complete project backup needs separate coverage
of business data, configuration and relevant external state.

```python
from yeoul_mcp.evidence_compare import compare_evidence

# Trusted operator code must authorize both paths before calling this helper.
report = compare_evidence(reference_project, offline_copy_project)
assert report["restore_authorized"] is False
assert report["execute_authorized"] is False
```

Both trees must already contain `.yeoul-mcp/workspace.lock`. The helper acquires
shared locks in stable path order, opens them read-only and never initializes a
workspace or repairs a missing lock. It uses the existing no-follow candidate
collector for file bytes and compares sizes/SHA-256 values. Locks coordinate only
with cooperating writers. File/directory identity checks catch observed changes;
they are not a defense against a privileged or same-account malicious writer.

Bounds per tree: 4096 entries, depth 16, 4 MiB per file and 32 MiB total. The overall
cooperative deadline is 30 seconds. Link/special-file/limit/read/change failures
refuse the comparison instead of truncating a result. Underlying kernel/filesystem
I/O is not forcibly interruptible by this synchronous deadline. The lock's contents
are excluded from comparison; it is a synchronization inode, not restorable evidence.

Results list missing, extra and changed relative names plus total compared bytes.
Raw contents are not returned, but names can still be sensitive: this is a host
operator helper, not an authenticated MCP/HTTP endpoint. The host must protect the
report and authorize access to both copies.

`byte_identical=True` proves only that the compared files matched during this
bounded read. It does not prove provenance, semantic validity, completeness of an
entire backup, absence of missing history in both copies, or freshness against
an external authority. A reference chosen from an old snapshot can also be stale.
Never promote a copied permission file, receipt or cancellation history into active
authority solely from this result. Restore/execution authorization is always false.

Tests cover exact-copy byte preservation, missing revocation, changed policy,
extra records, missing/link locks, mutation during reading and identical-root
refusal. They use synthetic copies only. Encryption/export transport, an approved
restoration workflow and operational reauthorization remain separate work.
