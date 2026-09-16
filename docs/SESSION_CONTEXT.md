# Persistent session context core (experimental)

`yeoul_mcp.session_context.SessionContext` is a host-owned, opt-in library.
It adds an append-only SQLite history, current-state projection, bounded replacement
input and source-range retrieval. No existing MCP operation or default loader is
changed. It has no dependency on a consumer application or evidence provider.

`SessionContext.create` persists default limits of100,000 journal events,64MiB
of canonical event payload bytes,256MiB for SQLite main-database pages and a64MiB
filesystem free-space admission floor. Hosts may
choose create-time values from1..1,000,000 events,1KiB..1GiB payload and1MiB..4GiB
main database; the database limit must be at least the payload limit. A nonnegative
`min_free_bytes` may override the floor; zero disables it. Event/payload
limits are checked in the same immediate write transaction before insertion, while
SQLite's page ceiling enforces the main-database limit. Refusal leaves revision and
counters unchanged. `journal_usage()` reports payload and allocated main-database
page bytes.

The main-database cap requires SQLite `DELETE` journal mode so a persistent WAL cannot
grow outside it. It still excludes the transient rollback journal, temporary files,
filesystem metadata, sparse-file allocation behavior and free-space reserved for
recovery. Hosts therefore still need a filesystem quota/free-space policy. Reaching
any limit never deletes, rotates or silently summarizes source text.

Before source append, checkpoint replacement and index rebuild, the library observes
the filesystem's currently available bytes and refuses below the persisted floor.
The observation uses Python's cross-platform filesystem capacity interface and is
covered by installed-package Linux/macOS/Windows CI definitions; it does not require
POSIX `statvfs` from callers. A CI definition is not itself proof that a remote run passed.
`storage_status()` exposes the observation and explicitly reports that no bytes are
reserved and no hard filesystem/rollback-journal quota exists. Another process can
consume space immediately after the check, so this is admission protection rather
than allocation, recovery headroom or a substitute for OS/project quotas.

Earlier version-1 databases without the additive limits table remain readable and
report `bounded=false`; they are not silently migrated or assigned retroactive limits.
The first four-column limits schema and later five-column main-database schema remain
readable without retroactive database/free-space policy. Hosts should explicitly export/review old data
into a newly bounded session. New bounded databases verify counters against their log
on open. This detects accidental inconsistency, not malicious rewriting by the trusted
database owner.

This is the first storage/state-management layer for long sessions, **not a
completed automatic conversation summarizer**. Natural-language extraction,
semantic adjudication, actual model context replacement and operating integration
remain to be implemented and measured. Do not infer token savings from byte sizes.

## Minimal no-model example

From a source checkout, run
`python examples/session_context_demo.py`. It creates only a temporary journal,
records one user goal and one evidenced tool completion, applies explicit host
reviews, and prints bounded packet metadata. It does not call a model, infer changes,
activate a loader, or grant execution authority. The assertions make the example a
CI regression for `REPLACE_CONTEXT`, `authority=NONE`, and done-state retention.
The checkout command deliberately uses checkout code even if an older Yeoul is
installed; CI separately sets `PRODUCT_TEST_INSTALLED=1` to exercise the built package
in the Linux, macOS and Windows job definitions. Those definitions do not by themselves
claim a remote runner passed. The installed-package matrix also includes Ubuntu on
Python 3.10, the declared minimum supported version.

## State lifecycle

1. The host records each turn with `record(text, origin=..., expected_revision=...)`.
   User/tool/assistant turns remain pending. A trusted host may designate diagnostic
   output as `trace`; source text cannot grant itself that classification.
2. The host reviews an extraction proposal using `review(turn, changes, reason=...,
   expected_revision=...)`. Exact source offsets and quotes are required. Accepting
   zero changes explicitly dismisses a turn from pending, but preserves its text.
3. The current projection updates goal, policy, constraint, decision, task and blocker
   keys. New values supersede the current value; original changes remain in the log.
4. `context(byte_budget=..., query=..., recent_turns=...)` automatically selects all
   mandatory current state and pending turns, compact done/revoked key guards and
   optional recent/literal-query-matching historical snippets.
5. `retrieve(turn, start=..., limit=..., expected_revision=...)` returns a bounded
   source range with a source hash. No whole-history retrieval is required.

The caller must use ready `model_input` **instead of** accumulated context, not
append another summary to an existing unbounded model conversation. The library
returns `delivery=REPLACE_CONTEXT` and `authority=NONE`; these are protocol labels,
not proof that a model adapter used replacement or that a worker is sandboxed.

Pending text may contain competing claims or instructions. It is not promoted to
approved state. A model consuming pending text must produce a proposal for review,
not perform unchecked work. This module alone does not enforce worker permissions.

## Host review contract

A change contains exactly `kind`, `key`, `text`, `status`, `start`, `end`, `quote`,
`evidence`, and `reopen`. Source offsets are Python Unicode codepoint indices.
Kinds other than `task` use `active`/`revoked`; tasks use `open`/`done`/`failed`.
Both `active` and `retired` are current authoritative projections. `retired` is a
compact terminal-state collection, not discarded or unknown history: `done` means
currently completed and `revoked` means currently revoked. `state_semantics` carries
these meanings explicitly for consumers. Historical snippets cannot override them.
Nonempty evidence references and a tool-origin turn are required for `done`.
A done task can become open only through explicit user-origin `reopen=True`.
Assistant-origin proposals cannot change approved state. Policies, constraints,
goals and decisions require user-origin turns; tool results cannot rewrite them.

These origin labels are assigned by the trusted host, not authenticated by this
library. An evidence reference is not proof of external test success. An exact
quote is not proof that the proposed interpretation is true. The existing review
and evidence-provider boundaries must be used by a future operating adapter.

## Persistence and limits

- `create(path)` refuses an existing file; `SessionContext(path)` reopens it.
  The caller supplies a private trusted directory; no automatic installation or
  operating database migration is performed. If SQLite initialization of a path
  exclusively created by that call fails, the unusable new placeholder is removed
  so a corrected retry is possible; a pre-existing path is never in that cleanup scope.
- SQLite commits event append atomically under `BEGIN IMMEDIATE`; stale expected
  revisions fail. State is rebuilt from the journal on open and refreshed from
  new events on subsequent access. Separate host processes see committed state.
- Hash chaining detects altered loaded events. Triggers reject ordinary journal
  updates/deletes. This is not authentication or protection from the database owner
  replacing files/removing triggers. Path prechecks do not secure an adversarial
  writable parent directory against every race.
- The model-facing budget is UTF-8 bytes, not tokens. Mandatory state is never
  silently cut: an over-budget result has `state=needs_review`, no model input.
- Each event is at most256KiB. New journals cap main-database pages as described
  above, but have no automatic retention and do not bound all filesystem usage.
  Opening replays history. Archive search decodes at most1024 index candidates or
  journal events and4MiB of source payload by default (`search_event_limit`,
  `search_byte_limit`). These are per-search decoding bounds, not hard SQLite I/O,
  total replay time or disk quotas.
  This is not a measured million-token-scale indexing solution.
- Optional snippets are at most1000 codepoints and explicitly marked historical
  and truncated when applicable. Queries are exact, case-sensitive Unicode text
  matches against original turn text, not JSON metadata. The window surrounds
  the first match in each turn and includes exact start/end codepoint offsets.
  Empty queries select recent history. At most one snippet is returned per turn.
  `search.complete` is false when an event/byte/snippet limit or output budget
  prevents considering all eligible turns. `search_stats` describes the stop
  reason and decoding counts. Completion does not imply semantic exhaustiveness
  or coverage of every occurrence inside a turn. Exact source-range retrieval is at most4000
  codepoints per call; the caller must account for all returned bytes/tokens and
  enforce an aggregate retrieval budget.
- Done/revoked key guards are retained, not silently discarded. Very many keys or
  unresolved pending turns can exhaust the mandatory budget and need review.

## Large-source measurement

[`mcp/tests/session_scale_benchmark.py`](../mcp/tests/session_scale_benchmark.py)
provides a no-model source-replay measurement. On one Tegra/aarch64 warm-cache run,
700,000 and 7,000,000 repeated synthetic words (3.5MB and 35MB source text) both
produced the same replacement hash through full replay and checkpoint reopen.
The 7,000,000-word case produced a 1,100-byte replacement packet; median full open
was 0.429s and checkpoint open 0.0193s across three runs. The benchmark deliberately
removes the optional FTS projection so it measures journal replay/checkpoint scaling,
not search-index scaling.

[`mcp/tests/session_search_scale_benchmark.py`](../mcp/tests/session_search_scale_benchmark.py)
measures that separate index path under the default 64MiB payload, 256MiB main-DB and
16MiB fallback-decode limits. In the same local environment, 7,000,000 synthetic words
used a 106,708,992-byte database. The verified index found the old exact hit completely
in a 0.00104s median and established exact absence in 0.000275s. The bounded scan reached
its 16MiB limit after 83 events, returned no old hit, and correctly marked both results
incomplete. Since the scan did not complete the same task, its timing is not used as an
equivalent-result speed ratio.

Synthetic whitespace-delimited words are not provider tokens. This one-machine result
does not demonstrate model quality, billed-token savings, search behavior, cold storage,
concurrent writers or an operating SLA. Run the script on the intended host and retain
raw output rather than treating these figures as a supported performance commitment.

## Optional literal-search index

On SQLite builds that provide case-sensitive FTS5 trigram support, newly created
journals maintain a derived turn index in the same append transaction. Exact matches
are always re-read from the source log before a snippet is returned. Queries of three
or more Unicode codepoints may use it; shorter queries and unavailable/invalid indexes
use the existing bounded journal scan. `use_search_index=False` forces that fallback.

The full-open path compares the index's ordered source digest, row count, revision and
log head with the replayed journal before `search.complete=true` can rely on it.
Missing, changed or query-failing index data is disabled and falls back to source scan.
`search_index_status()` reports availability and verification. A checkpoint fast-open
does not claim verified index absence until `verify_full()` has checked the prefix;
positive candidates are still source-checked and incomplete status is explicit.

`search_event_limit` bounds decoded index candidates or journal events and
`search_byte_limit` bounds source payload bytes decoded after selection. They do not
hard-bound SQLite's internal FTS CPU/page reads. The index consumes the persisted
main-database page budget and may therefore cause an append to refuse before the
payload-only quota. It is exact case-sensitive literal lookup, not semantic search,
stemming, ranking, authority or evidence validation. Older databases are not silently
migrated and continue to use bounded source scans.

After a full replay, `rebuild_search_index(expected_revision=...)` may explicitly
replace only this derived projection. It requires a persisted main-database page cap,
checks revision before dropping anything, rebuilds in one immediate transaction and
verifies the result. Failure rolls back; source `log` rows and journal revision are
unchanged. This is an operator-requested maintenance action, not automatic migration.

## Optional replay checkpoint

Default `SessionContext(path)` still replays and hash-checks every source event.
After a full replay, a host may call
`write_checkpoint(expected_revision=...)` to replace one derived projection artifact.
This does not append, delete, rotate or summarize source events, and it does not
change the journal revision or event/payload counters. The checkpoint is capped at
8MiB and remains subject to the SQLite main-database page limit.

`SessionContext(path, use_checkpoint=True)` may restore the projection at the bound
revision and replay only later events. The artifact binds session ID, source revision,
log head and canonical projection. Missing or malformed artifacts fall back to full
replay. `replay_status()` reports whether a checkpoint was used, its revision, suffix
events replayed and whether the complete prefix was verified in this open session.

Fast restore deliberately does **not** reread and hash every pre-checkpoint payload;
doing so would remove the replay-cost benefit. It therefore belongs only inside the
same trusted host/database-owner boundary and cannot detect an old source-page change
on every fast open. Call `verify_full()` periodically or before replacing a checkpoint;
it rebuilds the complete chain/projection and fails on a mismatch. A fast-restored
object cannot write another checkpoint until this full verification succeeds. The
checkpoint is acceleration metadata, never source truth, authentication, retention,
backup, rollback protection or proof of model-context correctness.

## Verification

`python -B mcp/tests/test_session_context.py` uses synthetic local fixtures, actual
SQLite transactions and a separate Python process for restore. It covers512 trace
turns, goal supersession, policy boundaries, source-quote mismatch, atomic rejection,
completion/reopen, two-connection stale writes, mandatory overflow, source-range
retrieval, serialization across a process boundary, archive preservation, persisted
event/payload/main-database limits, Python3.10 full-database handling, WAL refusal,
persisted free-space admission, both older storage schemas, checkpoint/suffix restore, corrupt-artifact fallback,
full-prefix revalidation, indexed old hits/exact absence and changed-index fallback.
Explicit rebuild, stale-rebuild refusal and source-row preservation are covered too.
Late matches, escaped text and explicit incomplete-search reporting are covered.
It does not establish natural-language extraction accuracy, real model behavior,
crash-at-every-instruction safety, every-platform behavior or operating token savings.

The legacy [context shadow](CONTEXT_SHADOW.md) remains available and unchanged.

An opt-in [extraction and explicit review bridge](SESSION_EXTRACTION.md) is also
available. It uses `review(..., dry_run=True)` for the same source/status validation
without appending events, then requires fresh reviews and host approval to commit.
Its synthetic tests do not establish natural-language extraction accuracy.

## Replacement transport

The opt-in [session command bridge](SESSION_RUNNER.md) supplies bounded current
context and source-range retrieval to a host-selected command. It is not a
default model integration or evidence of long-session token savings.
