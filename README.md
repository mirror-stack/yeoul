# Yeoul

[![CI](https://github.com/mirror-stack/yeoul/actions/workflows/ci.yml/badge.svg)](https://github.com/mirror-stack/yeoul/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

*[Read in Korean →](README_KO.md)*

> *A riffle — the shallow stretch where a stream quickens over rocks — is where scattered ideas
> collide, speed up, and get honestly tested.*

**Yeoul is a file-based harness for running deliberation → pre-registration → autonomous work loops
with integrity gates that resist self-deception and premature closure.** It is the *practice layer*
on top of a measurement-discipline primitive (pre-registration + a tamper-evident ledger): the
primitive checks recorded evidence and integrity; Yeoul answers *"how do I run a disciplined idea loop end to end?"*

> **v0.3.0: integrity-contract hardening.** See the [changelog](CHANGELOG.md) and
> [trust boundaries, installation and migration guide](docs/INTEGRITY.md).

## Install

```bash
git clone https://github.com/mirror-stack/yeoul
cd yeoul
export PATH="$PWD/bin:$PATH"     # the CLI: yeoul-new, arc-open, arc-close, ralph, status, …
setup/install.sh                 # installs mirror-stack (sealing primitive) + yeoul-mcp, prints MCP config
```

Register both MCP servers with your client (Claude Desktop/Code — merge `setup/mcp-servers.json`):

```json
{ "mcpServers": {
    "mirror-stack": { "command": "mirror-stack-mcp" },
    "yeoul":        { "command": "yeoul-mcp" }
} }
```

mirror-stack is optional — without a recorder, discussion closes are explicitly file-only
(`setup/install.sh --no-mirror-stack`).

## Quickstart

Try it with no agent and no compute — just the structure and the gates:

```bash
examples/demo.sh       # full lifecycle: scaffold → arc → 2-phase KILL close → dev handoff → verify-gate
tests/test_gates.sh    # assertion-based smoke test of every gate
```

New to the method? Read [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md), then paste
[`docs/BOOTSTRAP_PROMPT.md`](docs/BOOTSTRAP_PROMPT.md) into your agent to configure the practice.

## What it is (and is not)

- **Is**: a small set of shell scripts + templates + a method for opening a multi-role deliberation arc,
  judging convergence under runaway guards, closing it honestly (blank-refusal + a KILL-defense checklist),
  and handing off to a machine-verified development loop.
- **Is not**: a novel multi-agent framework. The orchestration is deliberately unremarkable — the value is
  the *gates*, not the debate. Research shows more debate rounds do **not** improve answer quality; Yeoul's
  round/token/no-progress guards exist because deliberation *drifts*, not because it self-corrects.

## The gates (the actual value)

- **Gate-1 (prior-art)** — reject or re-frame an idea early if existing work already covers it.
- **Kill-condition first** — a spec without a falsifier is untestable; seal it before spending compute.
- **2-phase close** — closing drafts a summary; it only seals once the blanks are filled.
- **KILL-defense 5-check** — a "failed" verdict cannot be sealed until anchor-reproduction, ≥2 independent
  angles, implementation-defect ruled out, catalog cross-check, and verbatim kill-wording are all recorded.
- **Sealed-condition cross-check** — if a pre-registered kill-condition is linked to the arc, closing always
  has to answer it, *whatever the close is labelled*. Otherwise closing as `converged` would switch off the
  only signal the closing agent did not write. A seal that no longer resolves is refused, not skipped.
- **Verify-gated dev loop** — each automated development round advances one TODO item and may only check it
  off after its own machine verification command exits 0, re-run by the harness rather than reported by the
  agent. Items without a verify command are refused — including checked ones, so deleting the clause is not
  a way out. Original TODO criteria are pinned before work; changing commands or deleting items is refused.
  (Test adequacy and protection of the test implementations remain the supervisor's responsibility.)

## Layers

| Layer | What | Where |
|---|---|---|
| Primitive | pre-registration + tamper-evident ledger | *(optional dependency — the mirror-stack)* |
| Practice | deliberation arcs, gates, dev handoff | **this repo** |

Mirror is optional for discussion. Linked claims must still pass offline hash verification.
Use `arc-result` only for an explicit, supervisor-judged measurement result; discussion closure is not publication.

## Status / honesty notes

- The autonomous development loop ("Ralph"-style) is the **least-validated, most-commodity** part; its safety
  comes from the machine-verification gate, not the loop itself. Do not treat it as a proven technique.
- No claim here is that Yeoul improves research *outcomes*. The claim is narrower: it makes honest
  discipline explicit and mechanically checked in the supported paths. It is not an OS security boundary.
