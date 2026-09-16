# Session extraction and explicit review bridge (experimental)

`yeoul_mcp.session_extraction` connects a host-selected extraction worker to the
[persistent session core](SESSION_CONTEXT.md). It has no default model or
credentials, does not modify an operating loader, and is not a public MCP write
endpoint. It does not yet implement a production language model adapter.

## Flow

1. The host records a source turn in `SessionContext`.
2. `extract_changes(session, turn, worker, byte_budget=32768)` builds a bounded
   request containing current state, pending source text and an extraction schema.
   The selected turn is explicit. Instructions require source-bound changes and
   explicit uncertainty rather than unsupported inferences.
3. A host-owned `worker(bytes) -> bytes` receives the immutable request envelope.
   It returns exactly `input_sha256`, `changes`, and `unresolved`. The input SHA
   binds the inner request; reported input bytes include the outer envelope too.
4. Malformed/oversized replies, missing/ambiguous source quotes, origin/status violations,
   uncertain interpretations and changed session revisions cannot become candidates.
   Validation uses the same core review logic in read-only dry-run mode.
5. The trusted host explicitly calls `commit_changes(session, proposal, reviewers,
   approve)`. Every host-required reviewer must pass for the exact proposal and
   current session. The host approval callback must separately return exactly True.
6. A final revision compare-and-swap applies the reviewed change atomically. The
   journal reason records proposal binding and provider evidence references.

The returned candidate has `authority=NONE`. Extraction cannot approve itself.
Empty changes still require review/approval because dismissing a pending turn can
lose important context. An unresolved response leaves the pending turn untouched.

## Trusted host callbacks

Extraction instructions distinguish procedural pending review from uncertainty
about source meaning. Clear user instructions can become proposals without being
authorized execution. This is a prompt clarification, not evidence that a model
will interpret it correctly. The host never deletes entries from `unresolved` to
force a candidate through. User-origin completion updates are still rejected.

When integer offsets disagree with an exact quote, the bridge may align the span
only if that quote occurs exactly once in the selected source. It never applies
fuzzy matching, guesses among repeated occurrences, or changes the proposed
meaning, key, status, evidence, or authority. Already-valid offsets remain intact.
`span_corrections` records old/new offsets in the result; an enabled attempt journal
also preserves original model bytes. The normalized proposal still needs all
origin/status checks, provider review, host approval and final revision checks.
If normalization or any later check fails, the source remains pending. Quotes
bind source locations, not semantic correctness. Updating extraction instructions
changes the input binding; previously produced candidates may require fresh review
and extraction rather than being accepted under a different prompt contract.

`reviewers` maps check IDs to `(provider_id, verify)` tuples.
`verify(request_bytes, proposal_bytes, binding_bytes)` returns exactly `status`
and `evidence_ref`, using the existing review decision contract. `approve` receives
frozen binding and report bytes. Callback implementations and the completeness of
the required reviewer set are host responsibilities, not worker-selected settings.

There is no built-in semantic verifier: a passing fake callback proves wiring only.
Hashes and matching quotes do not establish semantic accuracy, source authority or
test completion. Provider normalization/authentication and approval revocation must
be implemented by an operating host. Revocation after an approval callback returns
is not automatically detectable here; only session changes are fenced by the CAS.

## Bounds and unfinished integration

For durable attempt records, pass `audit_path` to `extract_changes`. The path must
be new, with an existing trusted parent. This opt-in mode limits the input budget
to64KiB and creates a separate exclusive SQLite journal; it never changes the
session's source/review journal. The exact request and binding are committed before
calling the worker. Returned bytes up to64KiB, even invalid UTF-8, are recorded as
hex before validation. Oversized returned bytes get a hash/count and an explicit
raw omission marker; non-byte returns get an invalid-type marker. Partial output
lost inside a failed transport cannot be recovered here. Final results preserve
uncertainty or candidates without automatically accepting either.

Storage failures propagate: an intent-write failure prevents dispatch, and a
response/result-write failure prevents a successful return. An interruption can
leave only an intent. That means the outcome is unknown, not safe to retry.
Reusing the same audit path is refused, but a host can create another path; this
does not prevent duplicate requests across the account. Hosts must not replay
an ambiguous attempt. Without `audit_path`, the original non-persistent callback
API remains available. Operating integrations must explicitly enable retention
and protect journals, which contain source text. Review callbacks and their
failed attempts still need separate auditing and actual usage accounting.

- A worker is called at most once per extraction; there is no automatic retry.
- Reply size is at most64KiB. Full mandatory context and request envelope must fit
  the caller's budget; oversized requests are refused before calling the worker.
- Worker/provider callbacks are ordinary trusted Python calls, not sandboxed or
  deadline-enforced here. Supply bounded transports with independently verified
  credentials, resource limits, cancellation and output caps for actual models.
- Reported input/output bytes are not model tokens. `model_tokens` remains unknown.
  An operating adapter must supply actual usage and review costs; the opt-in
  journal records observed extraction payloads, not provider billing.
- Actual natural-language extraction accuracy, model context replacement, semantic
  search and long-session model performance remain unfinished. Bounded source
  range retrieval is available separately in [Session runner](SESSION_RUNNER.md).
  No external calls, installation or production rollout are implicit.

Tests: `python -B mcp/tests/test_session_extraction.py`. Synthetic controls
exercise extraction/review/approval composition, uncertainty preservation, source
binding, duplicate fields, staleness, denial, callback failure and budget refusal.
They also cover durable intent-before-callback, malformed reply retention,
oversize omission, storage failures and interrupted-attempt reuse refusal.
A POSIX test also kills an owned extraction process after the intent is committed,
reopens the journal, and checks pending-source preservation and same-path replay
refusal. This covers that one interruption boundary, not every write boundary,
power loss, remote cancellation, or natural-language accuracy.
