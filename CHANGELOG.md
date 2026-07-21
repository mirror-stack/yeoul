# Changelog

All notable changes to this project are documented here.

## [0.1.0] — unreleased

Initial extraction of the Yeoul harness (de-personalized structure only).

- **Deliberation engine**: `arc-open`/`arc-close` (2-phase close with blank-refusal + KILL-defense 5-check),
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

### Review fixes
- **Portability**: replaced GNU-only `sed -i` with a portable temp-file edit (was silently failing the
  In-Progress→Closed status update on macOS/BSD sed, which the README targets).
- **Harness-enforced verify gate**: new `bin/verify-gate` — after each round the harness *re-runs* each
  checked item's `verify:` command and reverts any that don't exit 0 (`ralph` calls it automatically).
  The agent's claim is no longer trusted; this makes "resists self-deception" enforced, not requested.
- **KILL-defense substance check**: `arc-close` now rejects self-evident evasions in the 5-check (a bare
  "yes"/"."), and requires the catalog field to be an id or `none` and the anchor field to reference a
  number or a seal/reproduction.
