# Integrity contract and v0.3 migration

Yeoul is a supervised deliberation/development harness, not a proof of scientific
truth or a security sandbox. A passed command proves only what that command tests.
Different role names do not establish independent evidence or independent models.

## Deliberation and measurement are different

Unbound discussion arcs remain supported. They close as **attestation-only**, not
as verified research. There is no preregistration-attachment quota for discussion.
Measurement requires its own preregistration and explicit result evidence.

## Preregistration binding

`arc-prereg ARC CLAIM LEDGER` first checks the four substantive spec fields, then
records a binding after verifying a complete ledger snapshot. The ledger is also
checked before the spec is judged; invalid input never acquires a link.

- Every record's MIRROR-SPEC SHA-256 content hash and `prev_seal` link is checked.
- Missing, empty, malformed, duplicate-key and tampered ledgers are refused.
- The first registration wins. A later duplicate cannot repair or replace it.
- Text `kill_condition` or a nonempty structured `kill_threshold` is supported.
- `.prereg` contains claim ID, absolute ledger path and the first registration seal.
  `STATE.md` records `PREREG_BOUND` with the same binding. Later valid ledger entries
  are allowed; replacing the registration or removing the link is refused.
- `arc-close` rechecks the ledger and binding on every call. Legacy 16-hex hashes
  are accepted for compatibility but have weaker collision resistance.

**Scope:** hash integrity and local binding only. Identity signatures, external
time, content truth and independent reproduction are not verified by Yeoul.
An owner who can rewrite the entire ledger AND all arc files can rewrite local
history. Keep an external anchor/access boundary when that threat matters.

### Existing arcs

No existing arc or ledger is rewritten automatically. An old two-line `.prereg`
is **unbound**, not newly certified. Review the original ledger and explicitly run
`arc-prereg ARC SAME_CLAIM SAME_LEDGER` to verify and pin it. If the ledger fails
verification, recover the original evidence; do not rehash damaged data as a repair.
A genuinely different registration belongs in a new arc. Previously archived
records keep their historical meaning; this release does not retroactively certify them.

## Closure lifecycle

`In-Progress` -> `Close-Pending` (draft) -> `Closed` (archived).

A refusal stays pending. Drafting is not closure. Required defense fields cannot
be deleted to evade checks; verdict/stop metadata must match the requested close.
The archive destination must be absent, and a close lock prevents concurrent calls
on the same active arc. After an interrupted call, inspect `.close.lock` before
removing the stale lock and retrying. Do not edit a live call's lock.

`STATE.md` separately records `ARCHIVE_RECORD recorded|file-only|record-failed`.
Optional `am` recording is best-effort and does not decide the discussion verdict.
`recorded` means the recorder returned success, not independently reproduced truth.
`status` shows active arcs ahead of historical archived verdicts; TODO counts are
checkbox counts, not a new verification run. The knowledge index is a derived
view, not an authoritative proof store. Default index: current workspace's
`KNOWLEDGE_INDEX.md`; override with `YEOUL_INDEX`.

## Development verification

Supervisor setup, **before** handing the TODO to a worker:

```bash
mkdir -p supervisor
verify-baseline projects/example/dev/TODO.md --baseline=supervisor/example-baseline.json
```

After each worker round:

```bash
verify-gate projects/example/dev/TODO.md --baseline=supervisor/example-baseline.json --revert --require-verify
```

Only checkbox state may change. Modified commands, reordered/deleted/added items
or changed criteria are refused **before** command execution. On `--revert`, a
criterion mismatch restores the original TODO with its boxes unchecked. Default
baseline path is `TODO.md.verify-baseline.json`; creating an existing baseline is
refused. Baseline approval is a supervisor action, not an automatic MCP tool.
Criteria changes require explicit review and a new baseline path.

Ordinary failed verification commands revert their checked boxes when `--revert`
is enabled. An interrupted or timed-out command instead makes `verify-gate`
return **124**, stops later commands, and leaves the TODO unchanged for
reconciliation. A surviving checked box is **not evidence of successful
verification**. Inspect partial command effects and surviving children before
resuming; managed MCP leaves the operation pending and refuses automatic retry.
See the [stdio runtime contract](RUNTIME_CONTRACT.md) for managed permissions,
approved baseline locations, receipt recovery and concurrency limits. The baseline
paths above describe direct CLI/trusted usage; managed MCP requires its configured
baseline under `YEOUL_MCP_ROOT/.yeoul-approved/`.

Keep the standalone baseline and verification implementations outside the worker's
write permissions. A directory name alone does not enforce that boundary.
`--current-only` is an explicit manual diagnostic that prints its weaker scope;
it is not protected verification and is not exposed by the MCP verification tool.

Ralph captures the approved TODO in **parent process memory**, checks already
checked items, and uses that same snapshot through all rounds. `ralph NAME --check`
is read-only: it checks every item's syntax but runs no agent or verification
command. The MCP eligibility tool calls this exact path, including `YEOUL_PROJECTS`.

Ralph never launches an extra round beyond `--max-rounds`. Logs live in a unique
`dev/ralph_log/run-*` directory per invocation; reruns do not overwrite earlier evidence.
Agent and verification
commands have `--round-timeout` and `--verify-timeout` limits (seconds, default 120).
Token usage is counted from the backend's JSON `usage.input_tokens/output_tokens`;
missing/invalid counts stop as **unmeasured**, not zero. The token budget is a
between-round limit, not a hard provider spending cap: one round can exceed it.
Backend-reported usage is not an independently audited bill. POSIX timeouts kill
the child process group; Windows fallback terminates the direct child only.

## Explicit Mirror result handoff

Ordinary `arc-close` records remain discussion events. They are not automatically
converted into results and do not satisfy Mirror's publication gate.

With `mirror-stack-mcp >=0.2.14` and its compatible `action-mirror` installed:

```bash
arc-result ARC --status=fail --summary-file=observations/result.md --am-ledger=actions.jsonl
```

The supervisor must choose `pass`, `fail` or `inconclusive` and provide evidence.
This writes `action=result`, `target=claim_id`, and payload `status`, `summary`,
`prereg_seal`; it verifies the recorded chain and reports Mirror's publish decision.
It does **not** publish anything. A negative result may legitimately receive
publication GO; GO does not mean the hypothesis succeeded. Records are append-only:
if a post-write check fails, inspect the reported error and ledger before retrying.

## Installation and verification

Python >=3.10 and Bash are required (Windows: install Git Bash). The MCP server
uses Git Bash rather than the Windows System32 WSL launcher. Set `YEOUL_BASH` to a
custom Bash executable if discovery is insufficient. Wheels and sdists
include the scripts and spec templates; `YEOUL_BIN` is only an explicit override
for a custom checkout. Test an installed wheel from outside the source directory.
Both source and packaged paths are covered in CI. Commands execute with the
caller's workspace as cwd. CLI scripts are available from a checkout's `bin/`;
installing the Python package provides `yeoul-mcp`, not every CLI name on PATH.

```bash
bash tests/test_gates.sh
python3 tests/test_hardening.py
python3 mcp/tests/test_run_contract.py
python3 mcp/tests/test_serverinfo_version.py
python3 mcp/tests/test_surface_contract.py  # requires the compatible Mirror installation
```

Tests use temporary projects, indexes and action ledgers. Never use production
ledgers as fixtures. Cross-platform CI results should be read per platform;
a local Linux pass does not establish Windows/macOS behavior.
