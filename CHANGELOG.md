# Changelog

All notable changes to this project are documented here.

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
