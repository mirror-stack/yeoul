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

> **v0.4.0: standalone workspace product.** Yeoul is independent of Mirror and LaneStack.
> See the [workspace guide (Korean)](docs/WORKSPACE_GUIDE.ko.md),
> [changelog](CHANGELOG.md) and [integrity boundaries](docs/INTEGRITY.md).

For stdio MCP permissions, durable retries and cross-process locking, see the
[runtime contract](docs/RUNTIME_CONTRACT.md). Managed mode is opt-in with
`YEOUL_MCP_ROOT`; without it, the server is a trusted local runner without managed
permission enforcement or cooperative concurrency controls.

## Install

```bash
pip install 'git+https://github.com/mirror-stack/yeoul@v0.4.0#subdirectory=mcp'
yeoul setup ./my-discussions --mode discuss
yeoul new example --workspace ./my-discussions
yeoul doctor --workspace ./my-discussions
yeoul connect --workspace ./my-discussions
```

Add the configuration printed by `yeoul connect` to your MCP client. No existing
client config is modified. Python 3.10+ and Bash (Git Bash on Windows) are required.
The checkout installer `setup/install.sh` also installs Yeoul alone;
`--with-mirror-stack` explicitly adds the independent Mirror product.
Linked ledgers may live in separate roots. Managed closures remain file-only and
do not invoke an external recorder. Raw checkout commands remain advanced,
trusted-local interfaces outside the managed product CLI/MCP lock.

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
