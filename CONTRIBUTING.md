# Contributing

Yeoul is part of the mirror-stack family. The whole point is honest, hard-to-skip discipline, so the
contribution bar is the same discipline applied to the code itself.

## Before you open a PR
- **Verify, don't assert.** Exercise the behavior you changed (run `examples/demo.sh`, drive the affected
  script) and say what you observed. "Tests pass" is not the same as "I ran it and saw X".
- **No over-claim copy.** Docs and comments stay bounded and falsifiable — no superlatives, no "solves X".
  Run `setup/pre-publish-check.sh` locally; it scans for over-claim wording and personalization leaks and
  must exit 0.
- **Keep the gates.** The value is in the gates (blank-refusal, KILL-defense, verify-gate, loop-guard).
  Don't add a path that lets a caller skip them silently.
- **Match the layer boundary.** Yeoul is the *practice* layer; pre-registration and the ledger live in
  `mirror-stack`. Don't fold primitive concerns into Yeoul or vice versa.

## Scope
Yeoul ships *structure*, not anyone's research content. Keep it de-personalized: no private paths, personas,
or workspace-specific names (the pre-publish check enforces this).

## License
By contributing you agree your contributions are licensed under Apache-2.0 (see `LICENSE`).
