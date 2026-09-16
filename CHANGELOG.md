# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- Reopen the host-allowlisted candidate root after a bounded read and refuse the
  result if its pathname now identifies a different device, inode, mode or owner.
  Keep the descriptor-anchored read and leaf checks; document that a final recheck
  is not provenance or proof against a transient replace-and-restore attack.

- Add a runnable, no-model SessionContext example using a temporary database.
  Demonstrate explicit host review, terminal-state retention and bounded
  `REPLACE_CONTEXT` delivery without enabling a loader or granting authority.
  Exercise the installed example in Linux, macOS and Windows CI definitions.

- Add an Ubuntu/Python 3.10 installed-package job to the MCP matrix so the declared
  minimum Python version is continuously exercised alongside Python 3.12 and Windows.

- Add a no-model large-source benchmark for full replay and checkpoint reopening at
  700,000 and 7,000,000 synthetic words. Keep provider tokens, FTS scaling, model
  quality, cold storage and concurrent load explicitly outside its claims.

- Measure the literal FTS and bounded-scan paths at the same source sizes. Preserve
  the important 7,000,000-word result: the verified index completes an old hit and
  exact absence within the default DB cap, while the 16MiB fallback scan holds both
  as incomplete rather than inventing absence.

- Add a network-free publication gate for repository-local Markdown targets.
  Check inline, reference and image-wrapping destinations outside fenced/inline code, reject missing
  files, repository escapes and missing GitHub-style Markdown heading anchors while
  keeping remote URLs explicitly out of scope. Positive and negative controls prevent
  a silently empty link scan.

- Persist a 64MiB default filesystem free-space admission floor for new session
  journals. Recheck before source, checkpoint and index writes; expose read-only
  status and preserve older schemas without retroactive policy. This observation
  is not a reservation, hard filesystem quota or rollback-journal bound. Use a
  cross-platform capacity API and run the installed session state/extraction suites
  in the Linux/macOS/Windows CI definitions instead of depending on POSIX-only `statvfs`.
  Remove only a newly and exclusively created session path when SQLite initialization
  fails, avoiding a stranded partial database while preserving every pre-existing path.

- Add an optional, transactionally maintained case-sensitive FTS5 trigram projection
  for exact historical turn lookup. Re-read every hit from the source journal, verify
  ordered index content on full open, and fall back to bounded journal scan when the
  feature is unavailable, short, changed or unverified. This is not semantic search.
  Provide an explicit full-verified, revision-checked rebuild for page-capped journals;
  never rewrite source events or silently migrate older databases.

- Add an optional bounded session replay checkpoint. Keep default full-chain replay,
  preserve every source event, fall back to full replay on an invalid artifact and
  require full-prefix verification before replacing a fast-restored checkpoint.
  Fast restore is trusted-host acceleration, not independent integrity evidence.
  Exercise session context, extraction and runner regressions directly from the
  wheel archive in the narrower no-install package contract.

- Bound newly created session journals by persisted event, canonical payload and
  SQLite main-database page limits. Refuse appends atomically at quota, expose usage,
  reject persistent WAL outside the page cap, verify counters on reopen, and keep
  both older storage schemas readable without silent migration. Filesystem-wide
  quota, rollback-journal space, retention and checkpointing remain host concerns.

- Define terminal `done`/`revoked` entries as current authoritative facts in
  replacement context. Add optional host-selected, revision-bound answer review;
  contradictions and stale/failed reviews hold without returning answer text. Persist
  reviewer intent and normalized response (or a fixed sanitized failure) so interrupted
  attempts remain ambiguous instead of being silently replayable.

- Clarify semantic uncertainty versus procedural review in session extraction.
  Align incorrect integer offsets only for unique exact source quotations,
  reporting corrections while retaining raw audited replies and all review gates.
  Actual model behavior after these changes remains unevaluated.

- Connect bounded literal archive search to the session command protocol so a
  worker can discover source turn IDs before range retrieval. Search shares the
  retrieval/call budget and preserves explicit incomplete-result metadata.

- Add opt-in durable session extraction attempt journals: record intent before
  dispatch, preserve bounded raw replies and final outcomes, refuse reused paths,
  and propagate storage failures without returning an unrecorded candidate.

- Add an opt-in session command bridge with replacement-only input, bounded
  source-range rounds, durable request/response journals and stale-answer holds.
  Synthetic process checks do not establish actual provider history replacement
  or long-session performance. No default model or deployment is enabled.

- Return archive snippets around actual source-text matches with exact offsets,
  including escaped/newline queries. Bound archive decoding and explicitly report
  incomplete searches instead of treating limits as evidence of absence.

- Connect host-supplied session extraction to strict bounded candidates and
  explicit provider review/host approval, with final revision checks. Uncertainty
  and rejected proposals retain pending source turns. No default language model,
  semantic verifier or automatic operating integration is provided.

- Add an opt-in [persistent session context core](docs/SESSION_CONTEXT.md):
  append-only source history, host-reviewed current state, completion/revocation
  guards, bounded replacement input and source-range lookup. Natural-language
  extraction and operating model integration remain unimplemented; existing MCP
  tools and loaders are unchanged. No long-session token-savings claim is made.

- Prepare declared MCP runtime dependencies in the Linux/macOS CI job before
  host-composition and package regression tests. Mirror remains optional.

- Poison JSONL sessions on stdin selector registration/unregistration or output
  EOF unregistration failure;
  sanitize the error and preserve an earlier timeout instead of masking it with
  a cleanup error. Add fault-injection regressions; do not automatically resend.

- Add an opt-in [bounded duplex JSONL transport](docs/JSONL_TRANSPORT.md) with
  cumulative input/output limits, a whole-session deadline, strict framing and
  poisoned-session refusal after errors. Synthetic process tests cover blocked
  input, partial/malformed output and owned-group cleanup. This is not model-tool
  isolation, subscription enforcement or proof of remote cancellation.

- Replace the optional Mirror adapter's named temporary ledger copy with a sealed
  Linux memory file. Refuse unavailable sealing without a disk fallback and test
  write/truncate refusal, failure cleanup and owned-process SIGKILL. This does not
  claim secure erasure, swap/core-dump protection or isolation from the host account.

- Add an optional [Mirror registration-current adapter](docs/MIRROR_REGISTRATION_PROVIDER.md)
  over host-selected private snapshots. Use Mirror's actual integrity/claim scan;
  hold corruption, missing or ambiguous registration and observed withdrawal.
  This does not certify result truth, authenticate a provider or add a dependency.

- Add a host-selected [command verifier protocol](docs/COMMAND_PROVIDER.md) with
  fresh request IDs, exact input hashes, strict responses and per-process limits.
  Test LocalHost withholding approval on timeout/retraction before a fresh pass;
  no remote authentication, default verifier, sandbox or automatic retry is added.

- Add an opt-in [independent local host](docs/LOCAL_HOST.md) connecting current-file
  shadow review to persisted preparation and fresh reviewed execution. Require
  separate host approval and current sources; no model/provider transport, automatic
  workspace activation or production service is supplied.

- Separate FileSources public input revision/retrieval digests from nonpublic
  evidence fingerprints. Retain private host-selection binding and bind provider
  checks to the full snapshot so hidden-source changes still invalidate review.
- Add opt-in protected [host file manifests](docs/FILE_SOURCES.md) for current Active Context snapshots
  and ID-allowlisted, byte/request-bounded retrieval. Re-read sources around shadow
  review; no automatic source discovery, model call or loader activation is added.
- Add a host-only cancellation confirmation controller with bounded, expiring,
  account/target-bound one-use tokens and current authorization checks. No HTTP
  route, active exported HTML or automatic retry after uncertain responses is added.
- Add bounded read-only comparison of existing metadata copies using cooperative
  shared locks and the no-follow collector. Report missing/changed evidence without
  restoring files or promoting byte equality into execution authority.
- Add bounded, content-free metadata byte accounting and new-work admission at
  a host-configured high-water mark/free-space floor (256 MiB/64 MiB defaults).
  Preserve existing recovery paths; these observations are not hard disk quotas
  or reserved recovery capacity.
- Bound new logical-task admission by a trusted host retention count (default
  1000), without deleting evidence or blocking existing replay/recovery. Serialize
  last-slot admission under the workspace lock. This is not a disk-byte quota.
- Improve recovery-view layout for long IDs and narrow screens after real offline
  Chromium inspection; retain read-only semantics and Korean/English labels.
- Add a host-generated English/Korean read-only recovery view: explicitly selected
  authorized tasks, safe attention states, no raw evidence or active controls.
  No HTTP listener, automatic publication or operational retention policy is added.
- Connect trusted WorkerAccess execute-grant removal and owner transfer to retained
  task/unit launch revocation before policy replacement. Preserve partial-failure
  holds and never rearm old task IDs on permission restoration. No automatic stop
  service, external policy watcher or production configuration is installed.
- Add an explicitly opted-in real-service host-death recovery test: identify the
  running synthetic worker, kill only its fixture host, confirm service survival,
  then reopen retained state and stop the exact unit without relaunch or record loss.
- Diagnose missing/bound launch revocation markers and verify restart recovery
  after real SIGKILL at four cancellation persistence boundaries. Preserve prior
  evidence and execution denial; this does not certify real-child cleanup.
- Bind new logical worker runs to a version-3 host-owned launch permit checked
  by the real service bootstrap. Explicit cancellation persists revocation before
  stop; the worker does not receive the gate mount. No automatic policy subscription
  or proof of completed cancellation is added; historical records remain readable.
- Expose read-only cancellation recovery evidence: distinguish missing outcomes,
  malformed/orphan records and retained observations without permitting retry.
  Enforce the 64-attempt bound even when observation persistence was interrupted.
- Add separately authorized worker cancellation requests: persist result/dispatch
  revocation before exact-unit stop, retain bounded request/observation attempts,
  and report uncertainty without claiming completed cancellation or safe retry.
- Bind new version-2 worker manifests to a five-second boot-specific start ticket;
  validate at host reservation and service bootstrap. Preserve legacy records.
  This is partial stale-start protection, not atomic cancellation or retry approval.
- Preserve bounded cleanup-stage diagnostics when isolated service cleanup is
  unconfirmed, without raw exception/input/output data or weakening result holds.
  Continue reading historical lifecycle records without the diagnostic field.
- Add optional Linux WorkerAccess: kernel UNIX connection credentials, explicit
  per-task UID/action grants, revision-checked policy updates and retained policy
  history. Revocation is checked before dispatch and delivery. No listener or
  production authorization configuration is installed.
- Add host logical WorkerTasks mapping, current per-action authorization checks,
  completed-output redelivery and preserved operator retirement. Recheck at
  dispatch and delivery; uncertain tasks never silently receive a new unit.
- Add local WorkerJournal and ProfileBroker: retained hash-linked lifecycle
  records, bounded output replay, durable one-dispatch reservations, exact host
  profile/input matching and same-profile stop control. No administrative daemon,
  account authentication policy or production installation is activated.
- Add opt-in host-only isolated worker adapter with fixed resource manifests,
  actual kernel-limit preflight, bounded broker contract, durable host event sink
  and explicit transient-unit cleanup. Connect to shadow review without granting
  commit authority; production broker/configuration remains a separate integration.
- Add explicitly approved, opt-in transient Linux service tests for actual CPU,
  memory, process and tmpfs-output limits, plus combined Bubblewrap isolation.
  Test payloads run non-root; generated units are collected. No production broker,
  installation or existing user delegation changes are introduced.
- Make read-only recovery diagnosis and task inventory retain visible error rows
  for unreadable evidence instead of hiding other tasks. Keep strict execution and
  acknowledged recovery checks; diagnosis never grants retry authority.
- Add POSIX real SIGKILL/restart checks at five reviewed persistence boundaries
  and after an actual archive move in a private instrumented script copy. Preserve
  incomplete business state during operator reconciliation; no automatic repair.
- Exercise reviewed execution across all nine managed mutators with real synthetic
  business writes, review denial and retained interruption/reconciliation records.
  Add reviewed two-process contention and final archive response-loss scenarios.
- Add host-only schema-3 reviewed preparation and execution, binding the actual
  tool, arguments, snapshot and required providers. Check current host approval
  and reports before new writes; retain completed replay and legacy behavior.
  Retain separate bounded host review decisions before writes, including denials;
  new reviewed receipts require a validated audit link. Provider authentication and production hookup remain
  integration work; no MCP approval capability is exposed.
- Add opt-in Linux candidate byte collection using descriptor-relative, no-follow
  paths, bounded reads and identity checks. No automatic file import or execution.
- Add opt-in Linux bounded worker transport with streaming byte limits, deadlines,
  explicit environment and process-group cleanup. Connect named transport failures
  to shadow holds; no automatic fallback or operational model connection.
- Extend offline temporary-install parity checks to all Python module bytes and
  installed product/runtime regressions, including strict-mode stdio reconnection.
  Confirm import origin and keep child processes on the installed package path.
- Add an explicit opt-in [Linux worker-isolation capability test](docs/WORKER_ISOLATION.md)
  using existing Bubblewrap. It checks synthetic read-only inputs, private output
  and host access denial; no runtime launcher or operational isolation is enabled.
- Connect Active Context, one worker proposal and host-selected provider checks in
  an opt-in read-only [shadow workflow](docs/SHADOW_WORKFLOW.md). Recheck sources
  before dispatch, after work and after verification; never authorize execution.
  File-backed synthetic and child-process tests do not imply operational adoption.
- Add opt-in `prepared_only` write policy to setup/configure and managed execution.
  Refuse new unprepared/legacy writes while preserving completed replay, permission
  checks, pending reconciliation and original records. Existing profiles default
  to compatible behavior; running installations are not automatically changed.
- Bound preregistration metadata reads during freshness target discovery, including
  growth after the size check; reject oversize input before snapshot traversal.
- Stop Ralph after interrupted post-worker verification; do not accept completion
  or launch another round. Ordinary failed checks remain retryable after reversion.
- New managed prepared mutations bind target snapshots and reject stale state
  under the execution lock. Preserve completed replay and unchanged legacy records;
  see [prepared freshness](docs/PREPARED_FRESHNESS.md) for low-level/raw-call limits.
- Add an experimental [read-only context shadow](docs/CONTEXT_SHADOW.md), separate
  from production loading, permissions, model calls and semantic validation.
- Compare packaged harness bytes and run regressions against a temporary wheel
  installation, including context and prepared-target contracts.
- Add opt-in, provider-neutral review routing: missing, stale, conflicting or
  non-passing reports require review. Passing reports do not authorize execution.
  Keep arithmetic verification in a standalone example, outside the package;
  see the [review contract and adapter boundaries](docs/VERIFIED_TASKS.md).
- Add an offline wheel-archive parity check with direct, origin-checked imports
  and context/review regressions; no installation is needed for this narrower check.

## [0.4.0] — 2026-09-10

- Independent `yeoul` setup/new/status/doctor/connect/serve CLI with observe,
  discuss and develop modes; Mirror installation is now explicit opt-in.
- CLI/MCP task preparation, durable replay, workspace permissions and cooperative
  cross-process locks. Three new workspace MCP tools; twelve business tools retained.
- Operator-only audited recovery, retired interrupted IDs, reviewed and hash-pinned
  verification baselines, config history and explicit external read-ledger grants.
- Managed closures do not invoke an external action recorder. Separate product roots
  are supported; no LaneStack dependency or cross-product transaction is implied.
- Atomic arc directory allocation, no silent loop-state reset, and conservative
  interrupted verification handling. Wheels/sdists bundle the changed harness.
- See [workspace guide](docs/WORKSPACE_GUIDE.ko.md) and [runtime contract](docs/RUNTIME_CONTRACT.md).

## [0.3.0] — 2026-09-09

### Integrity contracts and compatibility changes

- Verify every ledger hash/link and pin the first registration; reject unsealed,
  tampered, malformed, duplicate-key, removed and changed bindings. Legacy links
  require an explicit verified upgrade; existing archives/ledgers are untouched.
- Freeze original TODO criteria, reject command replacement/item deletion before
  executing verification, and share CLI/MCP eligibility. Standalone verification
  now requires a supervisor baseline; `--current-only` is a labelled manual diagnostic.
- Keep closure drafts pending until archival; reject deleted defense fields,
  mismatched verdict metadata, concurrent closes and archive collisions. Record
  archive-recording state separately, and show active arcs before historical verdicts.
- Bound Ralph rounds without an extra invocation; add timeouts and stop on unknown
  token usage. Budgets remain between-round controls, not hard provider caps.
- Add an explicit `arc-result` bridge to Mirror's bound result contract. It records
  the supplied status/evidence and reports a publication gate, but never publishes.
- Bundle harness/templates in wheels and sdists, isolate tests from production
  ledgers/indexes, and test installation away from the checkout.
- Prefer Git Bash on Windows over the System32 WSL launcher. Keep per-run logs
  without overwriting older evidence; require defense answers inside their checked section.
- Refresh active docs, command references, installation failure handling and migration
  guidance. See [INTEGRITY.md](docs/INTEGRITY.md) for limitations and upgrade steps.

## [0.2.0] — 2026-08-28

**The first tagged release.** `0.1.0` was never cut: the section below has sat marked *unreleased*
since the first commit on 2026-07-21 while eighteen more went in, so until now no version number
identified a build.
That mattered more than it looked, because of the first fix in this release.

### Fixed
- **`yeoul-mcp` announced the wrong package's version.** `FastMCP.__init__` takes no `version`, so
  `Server.version` stayed `None` and the SDK substituted its own release into `serverInfo`: this
  server reported `{"name": "yeoul", "version": "1.27.2"}` — the installed `mcp`, not yeoul-mcp.
  The announced number therefore moved with whatever SDK a machine happened to have and never with
  this package. Now set from the source `__version__` (deliberately not `importlib.metadata`, whose
  dist-info can be stale under an editable install). (#9)
- **Nothing read the handshake.** The `mcp` CI job imported the module and counted tools, which
  proves the module loads. `mcp/tests/test_serverinfo_version.py` launches the server and reads what
  it actually says, with a negative control (an unpatched `FastMCP` must still show `version is
  None`) so the file cannot go green while asserting nothing. (#9)
- **The version is written in two files and only one reached `serverInfo`.** `pyproject.toml` is
  what packaging records; `__init__.py` is what the server speaks. They could drift silently — with
  pyproject set to a different number the suite still passed 6/6. A check now fails when they
  disagree, because cutting a release means bumping both.

### Added — the second key (#10)
Yeoul and mirror-stack are meant to be two keys: yeoul decides the design, mirror-stack seals the
kill-condition before compute. One side had no lock and the other had no record.

- **`arc-prereg` refuses a spec with no design in it.** It attached a seal to an arc whose Goal,
  Success condition, Kill-condition and Constraints were all blank — exit 0, nothing printed. The
  four fields are now judged by the same `substance_check.py` the close gate uses, with its positive
  control run first: an instrument is trusted because it just proved it can still say no.
- **Every close now records which keys were turned.** A KILL close wrote `⚠️ UNSEALED` into its
  `_SUMMARY`; a GO close wrote nothing about the seal at all — and GO is the label that opens the
  next step. Each close carries a harness-owned `Second key (pre-registration)` line, required
  verbatim on the sealing run, so "closed with one key" cannot be edited into "closed with two".
- **The closing banner named a gate that had not run.** It said `blanks & KILL-defense checked` as a
  fixed string on every successful close, including closes where no KILL-defense section existed. It
  now names the gates that actually ran.
- **The knowledge index dropped a column it promised.** The `Sealed claim` row was printed only when
  a claim existed, so an unsealed close was indistinguishable from an old row or a failed write. It
  now says `none (closed with one key only)`.
- **`templates/spec.md`** had no colon on the Kill-condition line — nowhere to write the one field
  the seal is about.

**Compatibility.** The lock lives only in `arc-prereg`, which is only ever called by someone who
already has a ledger. Measured before and after: with no mirror-stack anywhere on `PATH`, every
other command still runs — `yeoul-new`, `arc-open`, `arc-list`, `status`, `arc-roles`,
`build-handoff`, `verify-gate`, `loop-guard`, and a full `arc-close` round trip. mirror-stack is not
an install requirement. If you *do* use both, an arc with a blank spec will now refuse the seal.

### Also
- **Interpreter resolution** (#8): Windows ships a Store stub answering to `python3` that exits 49
  without running anything, so `command -v python3` was satisfied by it and every python-backed gate
  received a 49 that printed like a verdict. Interpreters are now resolved by executing one.
- **Signals say only what the code checked** (#7).

Gate suite 72/72 (61 before this release). Tested on Linux, macOS and Windows; the bash gate suite
runs on the unix matrix only.

## [0.1.0] — never released (2026-07-21, superseded by 0.2.0)

Initial extraction of the Yeoul harness (de-personalized structure only).

- **Deliberation engine**: `arc-open`/`arc-close` (2-phase close with blank-refusal + KILL-defense 5-check
  + a label-independent sealed-condition cross-check whenever a prereg seal is linked),
  ticket/attach/watch/list/roles/join relay helpers, `loop-guard` (round/token/no-progress bounds).
- **Lifecycle**: `yeoul-new`, `build-handoff` (verify-gated TODO), `ralph` (autonomous dev loop with a
  verify-gate), `graduate`, `close-project`, `status`.
- **Method**: `docs/METHODOLOGY.md` (runtime-independent) + `docs/BOOTSTRAP_PROMPT.md`.
- **MCP**: `yeoul-mcp` — gate-enforcing tools over the scripts; composes with `mirror-stack`.
- **Setup**: `setup/install.sh` (installs alongside mirror-stack), `setup/mcp-servers.json` (registers both
  servers), `setup/pre-publish-check.sh` (leak + over-claim + empty-scaffold gate).
- **Example**: `examples/demo.sh` (full lifecycle, no agent/compute needed).
- **Tests**: `tests/test_gates.sh` (assertion-based smoke test of the integrity gates).
- **Localization**: `README_KO.md` (Korean).

### Added
- **Auto-growing knowledge index** (`bin/index-append`, called by `arc-close`): every close appends a
  cross-linked row (verdict · stop · sealed claim · one-line conclusion · source) to `KNOWLEDGE_INDEX.md`.
  Hands-off, sourced only from the sealed _SUMMARY — it can't rot the way a hand-maintained wiki does.

### Audit fixes (2026-08-05 — found by auditing docs against code)
- **Verify-gate bypass closed.** The gate keyed on the `verify:` clause, which lives in a file the agent
  edits: deleting the clause while ticking the box made the item invisible to the gate and it survived
  unverified. `verify-gate --require-verify` now treats a checked item with no verify clause as a failure,
  `ralph` passes the flag and refuses a TODO where *any* item (checked or not) lacks the clause. The docs
  that claimed "a checkbox survives only if its verify command passes" were corrected to state what is
  actually enforced — and what is not (a verify command that cannot fail is still on the author).
- **The two strongest gates reached MCP.** `arc_prereg` (link a seal so `arc_close` injects the
  kill-condition verbatim) and `verify_gate` (re-run a round's verify commands) had no MCP tool, so an
  agent driving Yeoul purely through MCP — the setup the README prescribes — could run neither. Added;
  tool surface 10 → 12.
- **Docs**: `bin/yeoul-graduate` → `bin/graduate` (the referenced command did not exist); backend A's
  obligation to run the verify gate itself made explicit in METHODOLOGY and the bootstrap prompt.
- **`index-append`**: numbered lists no longer index an empty conclusion, and a failed extraction warns
  instead of passing silently (see below).
- **`mcp<2` pin**: an unbounded floor let CI install a breaking major (`mcp.server.fastmcp` moved).

### Review fixes
- **Portability**: replaced GNU-only `sed -i` with a portable temp-file edit (was silently failing the
  In-Progress→Closed status update on macOS/BSD sed, which the README targets).
- **Harness-enforced verify gate**: new `bin/verify-gate` — after each round the harness *re-runs* each
  checked item's `verify:` command and reverts any that don't exit 0 (`ralph` calls it automatically).
  The agent's claim is no longer trusted; this makes "resists self-deception" enforced, not requested.
- **KILL-defense substance check**: `arc-close` now rejects self-evident evasions in the 5-check (a bare
  "yes"/"."), and requires the catalog field to be an id or `none` and the anchor field to reference a
  number or a seal/reproduction.
- **Sealed kill-condition injection** (`bin/arc-prereg` + `arc-close`): when a pre-registration seal is
  linked to an arc, the harness injects the sealed kill-condition *verbatim* from the ledger instead of
  trusting an agent-typed field, and refuses the close if that line is edited — closing the post-hoc
  goalpost-moving hole structurally. Unsealed closes are stamped `⚠️ UNSEALED` (attestation-only). Scope:
  this fixes the condition by reference; whether the result triggers it remains a judgment (not automated).
