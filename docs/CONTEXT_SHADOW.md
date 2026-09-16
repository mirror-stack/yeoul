# Read-only worker context shadow

Status: experimental local comparison API, not an active loader or a new authority.
No consumer application, model service or Mirror installation is required.

`yeoul_mcp.context_shadow` builds a deterministic read-only worker input from a
host-supplied snapshot. It does not discover authoritative files, run a worker,
write state, grant permissions or commit results. Existing MCP tools are unchanged.

The snapshot contains `target`, `revision`, and `sources`. Each source has an `id`,
`role`, `category`, and text `body`. Unique roles `goal`, `status`, `action`, `policy`,
and `constraints` must all be `REQUIRED_ACTIVE`. The host must supply the complete,
current policy set: a plausible but incomplete policy body cannot be detected here.

| Category | Worker-facing handling |
|---|---|
| REQUIRED_ACTIVE | Include full body; no silent truncation |
| RETRIEVABLE_ON_DEMAND | Include pointer; retrieve only after fresh validation |
| VALIDATOR_ONLY | Exclude body from worker input |
| NONCONTROLLING_HISTORY | Exclude body from worker input; preserve in source snapshot |

`extract(snapshot)` returns separate `model` and `binding` objects. Only `model`
is a candidate worker input; do not send the whole result or snapshot to a model.
`validate(packet, current_snapshot)` compares against a freshly obtained source
set, not merely the packet's own hash. `retrieve` permits only listed optional
sources and repeats validation. `compare` reports UTF-8 byte counts, not tokens,
latency savings, truth, or task accuracy. Retrieval adds input bytes and must be
counted by any future host integration.

`model_input(packet, current_snapshot)` validates a frozen copy and returns only
the model-facing UTF-8 bytes. Later edits to the caller's packet cannot alter that
payload. A local receiver fixture checks byte equality across a child-process pipe;
this is not a model-provider receipt and does not prove an actual model consumed it.

The output always has `READ_ONLY` mode, `NONE` authority and `proposal` output kind.
Those labels describe the contract; they do not sandbox a model or authenticate
sources. Hash equality is not provenance. An execution plan is not an execution
receipt. A caller that validates against an old snapshot still has an old view.

## Boundaries and adoption

For the separate opt-in persistent state and bounded replacement-input core, see
[Session context](SESSION_CONTEXT.md). It is experimental, does not change this API,
and does not yet provide automatic natural-language extraction or model integration.

For the opt-in file-backed test-host connection from input extraction through
provider checks to review routing, see [Shadow workflow](SHADOW_WORKFLOW.md).
The operational loader and write path remain unchanged.

For a standalone example of structured single-task input and an independent
verification adapter, see [Verification adapter example](VERIFIED_TASKS.md).
It is not a packaged Yeoul verification API, does not change this legacy
extractor, and does not activate an operational loader.

- No automatic model call, fallback execution, source change or commit exists.
- Unknown/duplicate schema fields, missing required roles and altered packets fail.
- The 4 MiB source limit rejects input instead of truncating required information.
- Changes anywhere in the supplied snapshot invalidate its old binding. This is
  deliberately conservative for shadow comparisons, not a scalable history cache.
- Concurrent commit prevention and transport-to-model identity are not implemented
  by this module. They require host integration and separate approval/testing.
- Start with synthetic read-only investigations. Operational loading and actual
  model canaries require approval, source ownership and measured comparisons.

Tests: `python -B mcp/tests/test_context_shadow.py`. Packaged harness parity:
`python -B mcp/tests/test_distribution_contract.py` (offline build prerequisites:
pip, setuptools and wheel). The latter builds in temporary storage and runs the
existing harness regressions against the wheel contents outside the checkout.
