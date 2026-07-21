# Yeoul

[![CI](https://github.com/mirror-stack/yeoul/actions/workflows/ci.yml/badge.svg)](https://github.com/mirror-stack/yeoul/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

*[Read in Korean →](README_KO.md)*

> *A riffle — the shallow stretch where a stream quickens over rocks — is where scattered ideas
> collide, speed up, and get honestly tested.*

**Yeoul is a file-based harness for running deliberation → pre-registration → autonomous work loops
with integrity gates that resist self-deception and premature closure.** It is the *practice layer*
on top of a measurement-discipline primitive (pre-registration + a tamper-evident ledger): the
primitive answers *"is this claim honest?"*; Yeoul answers *"how do I run a disciplined idea loop end to end?"*

> ⚠️ **Work in progress — not yet released.** This README is a positioning draft, not a launch page.

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

mirror-stack is optional — without it, sealing degrades to a no-op and everything else still runs
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
- **Verify-gated dev loop** — each automated development round advances one TODO item and may only check it
  off after its own machine verification command exits 0. Items without a verify command are refused.

## Layers

| Layer | What | Where |
|---|---|---|
| Primitive | pre-registration + tamper-evident ledger | *(optional dependency — the mirror-stack)* |
| Practice | deliberation arcs, gates, dev handoff | **this repo** |

The mirror-stack dependency is optional: without it, sealing degrades to a no-op and everything else runs.

## Status / honesty notes

- The autonomous development loop ("Ralph"-style) is the **least-validated, most-commodity** part; its safety
  comes from the machine-verification gate, not the loop itself. Do not treat it as a proven technique.
- No claim here is that Yeoul improves research *outcomes*. The claim is narrower: it makes honest
  discipline the **default and hard-to-skip**, which is exactly what current autonomous-research systems lack.
