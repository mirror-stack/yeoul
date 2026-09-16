# Session command bridge

`yeoul_mcp.session_runner.run_session(session, worker, audit_path)` is an opt-in
host library. It connects the [session state](SESSION_CONTEXT.md) to a host-fixed
`CommandWorker`. It is not an MCP write endpoint or an enabled model integration.
The command transport is Linux-only. Its process tests are explicitly skipped
on other platforms; this is not evidence of macOS transport support.

Each invocation creates an exclusive audit SQLite file (parent must exist).
Requests contain current state, pending turns and bounded retrieved source ranges,
not previous model answers. Every round starts a fresh local process. The host
must separately ensure its remote provider does not append hidden thread history;
a fresh process and a `REPLACE_CONTEXT` label cannot prove that property.

The input envelope has `input_sha256` and `request`. The digest covers canonical
`context_shadow.encoded(request)`, not the whole envelope. The worker returns
exactly one JSON object with that digest and either:

- `kind: "answer"`, `text`: a nonempty answer candidate; or
- `kind: "retrieve"`, `turn`, `start`, `limit`: one original turn range, using
  Unicode offsets with a maximum of 4000 codepoints; or
- `kind: "search"`, `query`: discover historical turn IDs and source offsets
  using a nonempty, case-sensitive literal query of at most 256 characters.

Search returns at most three source snippets through the same `retrieved` list.
Each search scans at most 1024 events / 4MiB of decoded payloads, not an I/O or
whole-journal replay limit. Current pending turns are already mandatory input and
are excluded from archive snippets. Search replies include `search.complete` and
scan statistics. Limits, omitted matches or unscanned older history cannot be
interpreted as proof that a fact is absent. Snippets identify historical text,
not current instructions. This is literal lookup, not semantic search.

There is no worker-controlled executable, path, permission, provider, or tool
dispatch. Source text and responses confer no authority. Host-selected commands
still need suitable isolation: `CommandWorker` is not a sandbox.

Default limits are three calls, 32768 bytes per full request and 8192 aggregate
retrieved bytes (including range and search metadata). Search and range replies
share that cumulative budget and the call count. Retrieved evidence persists
within the bounded request; repeated exact ranges/queries, stale revisions, malformed responses,
unavailable sources and exhausted budgets cause a hold. Retrieval in the last
allowed call is refused. Each process has the transport's independent deadline;
there is no separately enforced wall-clock deadline across SQLite and all calls.

Before dispatch, the journal commits exact input bytes and intent. Returned raw
bytes are recorded as hex before interpretation, including malformed replies.
Transport failures may have partial output that the transport does not return;
those bytes are unavailable, not asserted to be zero. Input/output byte totals are
observed payloads, not billable tokens. Model tokens remain unknown. An interrupted
intent is ambiguous: never automatically retry it. Existing audit files are never
overwritten. Audit creation/write failures propagate; no dispatch follows a failed
intent write. Journals contain source content and need host retention/access rules.

A returned answer is a candidate bound to a revision, not verified truth or an
authorized state change. A later consuming host must recheck that revision inside
its own atomic commit. The runner does not update session state or approve answers.
The request explicitly defines `retired` as current terminal facts. Consumers must
render `done` as completed, not unknown, and `revoked` as revoked, not active.

Hosts that need answer consistency can pass `answer_reviewers`, a mapping from
host-selected check IDs to `(provider_id, callback)`. Each callback receives frozen
current-context bytes, `{text}` candidate bytes and binding bytes, then returns
exactly `status` and `evidence_ref`. Every required report must pass for the same
session revision and answer hash. A failure, malformed report, callback exception,
or concurrent state change returns a hold without answer text. A pass still yields
only `answer_candidate` with `authority=NONE`; it is not publication or execution
authorization. Callbacks are trusted ordinary host code and need separately bounded
transport, authentication, retention and complete requirement selection.
Before each callback, the runner durably records its host-selected check, provider and
answer/session binding. A valid normalized response is recorded before it can contribute
to a returned candidate. Callback exceptions or malformed reports record only a fixed
failure reason, never provider exception text. An intent without a response is ambiguous
and must not be automatically replayed. Audit-write failure before intent prevents the
callback; failure after callback prevents the answer candidate and leaves the intent.
[Extraction review](SESSION_EXTRACTION.md) remains a separate host-controlled step.
Actual provider usage reporting, remote cancellation confirmation, reviewer
transport authentication, storage quotas and end-to-end model evaluation remain separate
integration work. No performance advantage is established by the process tests.
