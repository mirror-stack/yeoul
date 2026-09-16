# Host-selected current files (unreleased, Linux)

FileSources connects a protected host manifest to Active Context/shadow. It does
not discover files, infer policy from prose, choose a model, alter a loader or write
configuration. The host provisions `.yeoul-mcp/source-manifest.json` and authorizes
the sources; completeness of that selection remains the host's responsibility.

Example manifest, with paths relative to the selected project root:

```json
{"version":1,"target":"synthetic-ticket","sources":[
  {"id":"goal","role":"goal","category":"REQUIRED_ACTIVE","path":"goal.md"},
  {"id":"status","role":"status","category":"REQUIRED_ACTIVE","path":"status.md"},
  {"id":"action","role":"action","category":"REQUIRED_ACTIVE","path":"action.md"},
  {"id":"policy","role":"policy","category":"REQUIRED_ACTIVE","path":"policy.md"},
  {"id":"constraints","role":"constraints","category":"REQUIRED_ACTIVE","path":"constraints.md"},
  {"id":"detail","role":"detail","category":"RETRIEVABLE_ON_DEMAND","path":"detail.md"}
]}
```

The control directory must be host-owned/private and the manifest host-owned/not
group- or world-writable. Required roles appear exactly once as REQUIRED_ACTIVE.
Bounds: 64 files, 64 KiB manifest, 1 MiB/file, 4 MiB raw/collection and 4 MiB encoded
snapshot. The existing no-follow collector rejects unsafe paths. Empty, missing or
oversized sources are refused, never silently omitted.

load_snapshot re-reads manifest/files to detect observed interleaved changes and
derives its public revision only from active content and retrieval pointer IDs/roles.
Collection uses a cooperative 30-second
deadline, not forcibly interruptible kernel I/O. Repeated reads add I/O cost; this is
not an atomic filesystem snapshot or defense against malicious host writers.

```python
sources = FileSources(project_root)
result = run_shadow(task_id, sources.load_snapshot, host_worker, host_providers)
```

retrieval_session(packet, max_requests=8, max_bytes=256*1024) freezes a host packet.
request(source_id) accepts allowlisted IDs, not paths, then freshly loads/validates
the selected snapshot. It returns encoded JSON bytes containing id, body and the
public model input digest (`model_sha256`), not a digest of private source contents.
Only RETRIEVABLE_ON_DEMAND IDs qualify. Changed/reclassified sources
invalidate old packets. Requests are serialized; denied attempts count toward the
request limit. delivered_bytes counts exact returned JSON bytes, not tokens/billing.
Oversized responses are refused rather than truncated.

The host snapshot includes a reserved VALIDATOR_ONLY selection record
`__yeoul_host_selection__`, binding manifest paths/classification without exposing
them through public revision/pointers. Manifests cannot supply that reserved ID.
Private/history/unretrieved body changes leave public model bytes unchanged but
invalidate the full host binding. Shadow provider binding revision uses the full
snapshot digest, so nonpublic updates cannot reuse a provider revision. Never send
that host binding/raw provider metadata back to the proposing worker.

Categories are not encryption, timing-channel protection or secret storage. Never
put credentials in the selected files. Production
source provisioning, authenticated model/provider integration and loader activation
still need separate evidence/approval. ready_for_review grants no execution authority.

Eleven synthetic-file tests cover deterministic read-only loading, private/history
exclusion, retrieval bounds, source changes/reclassification, required roles,
manifest protection, edits/links and a successful current-file→query→shadow path.
They also cover unchanged public bytes across private updates, changed host/provider
bindings, private path changes and reserved-selection-ID refusal.
