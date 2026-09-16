# Example: independent verification adapter

Status: standalone example, not a packaged Yeoul API and not connected to the operational loader, MCP
execution, or commit path. No installation, permissions, or deployment changes.
Yeoul remains independent of Mother, Lane Stack and Mirror.

## Implemented boundary

`examples/verified_task_adapter.py` demonstrates `prepare(task)` for exactly one host-selected task.
It separates structured `observations` from `unverified_claims`, freezes a copy,
and binds its target, revision and contents. It does not extract trustworthy facts
from natural language or authenticate the host. Consumers must construct these
fields from their actual source of record, not promote model prose to facts.

The initial supported kind is deliberately narrow: `integer_sum`. Each observation
has a unique `id` and integer `value`. A proposal contains only `task_sha256`,
`value`, and `evidence_ids`. `verify(packet, proposal, current_task)` recomputes
the sum without a model and requires all observation references exactly once.
Wrong values, bools/floats, stale inputs, invented references, altered packets,
extra fields and unsupported kinds fail closed with `ValueError`.

The result is `verified_calculation`, never general task success, execution proof,
or permission. The host must handle rejection as hold/review, not auto-execution
or an unbounded retry. Existing authority checks and atomic commit freshness
checks remain mandatory. A caller supplying old or false observations can still
obtain a mathematically correct result over wrong data. Hashes do not solve that.

This example is separate from legacy context extraction: no existing schema or
consumer changes silently. Single-task enforcement applies only to this API.
No claim of improved real-model accuracy or operational enforcement is made.

## Minimal host-side example (no model or tool execution)

```python
# From the repository root with PYTHONPATH=mcp:examples (Unix).
# This adapter is a repository example, not included in the installed package.
from verified_task_adapter import prepare, verify

task = dict(task_id='sum-1', target='example', revision='r1', kind='integer_sum',
            observations=[dict(id='a', value=4), dict(id='b', value=7),
                          dict(id='c', value=6)],
            unverified_claims=['Worker claims total 18'])
packet = prepare(task)
proposal = dict(task_sha256=packet['task_sha256'], value=17,
                evidence_ids=['a', 'b', 'c'])
# Real integrations must freshly reload observations/revision before verification.
result = verify(packet, proposal, task)
# Changing value to 18 raises ValueError, even if the worker says it is verified.
```

## Reliability roadmap: proposals carry checkable evidence

### Product ownership

Yeoul owns task routing, state transitions, bounded recovery and completion
conditions. It consumes verification outcomes without claiming to establish their
truth. Mirror can independently provide evidence management and verification;
existing test tools or another adapter can also supply verification. Mirror must
not become a required dependency of Yeoul. The example's arithmetic logic belongs
to the adapter, not to Yeoul's scheduling or runtime core. No Mirror API shape is
asserted here, and no common runtime integration has been implemented yet.

### Yeoul review-routing contract

The [read-only shadow workflow](SHADOW_WORKFLOW.md) now connects this function to
Active Context in a synthetic test host. It is not connected to production loading
or execution and does not authenticate a real remote provider.

`yeoul_mcp.review_decision.decide(binding, requirements, reports)` is an opt-in,
pure decision function. It does not perform verification. The trusted host supplies
the current task ID, target, revision and proposal SHA; required check IDs mapped
to selected providers; and the latest normalized provider reports. Each report
contains `check_id`, `provider_id`, `binding`, `status` (`pass`, `fail`, `unknown`,
or `retracted`) and a nonempty `evidence_ref`.

Every required check must pass against the exact current binding. Missing,
duplicate, unexpected, stale, retracted or mismatched-provider reports yield
`needs_review`, with stable reason codes. All passing yields `ready_for_review`,
not completion or permission. Invalid schemas raise `ValueError`; the host must
hold on errors. Results never trigger execution, retries or state writes.

Provider names and evidence references are labels, not authentication. The host
must obtain reports through its trusted provider connection, enforce latest
retraction state, and prevent workers from selecting requirements or forging the
report set. A fabricated matching report can fool this pure function. It is not
a security boundary, signature verifier, receipt store, or Mirror adapter.
Operating callers must still perform approval/freshness checks at commit time.
There is no MCP/loader integration or automatic promotion of existing tasks.

See the [provider integration checklist](PROVIDER_INTEGRATION.md) for result-scope
separation and the inspected Mirror compatibility boundary. In particular, permission
to publish a negative result must not become a passing claim-validity check.

Test: `python -B mcp/tests/test_review_decision.py`.

Package-level check without installation: `python -B mcp/tests/test_wheel_archive.py`.
It builds a wheel offline in temporary storage using existing build dependencies,
compares package/harness source bytes, excludes the arithmetic example from the
package, and runs context/review tests via direct archive imports in an isolated
Python process. It verifies import origin so an installed copy cannot substitute
for the archive. It does not test installed entrypoints, executable permissions,
live MCP connections or operational provider authentication. The separate
`test_distribution_contract.py` installation regression remains required before
claiming installed-package parity; it is not replaced by this check.

The ideas below span these boundaries: verifiers and evidence invalidation belong
to the evidence provider; Yeoul reacts to invalidation by reconsidering affected
tasks. Approval, freshness and duplicate-execution prevention remain execution
boundary responsibilities. This is not a plan to copy Mirror inside Yeoul.

1. **Typed verification, not self-certified PASS.** Add bounded, task-specific
   verifiers for structured data and artifact properties. Do not use arbitrary
   shell commands or model-generated verifier code as trusted checks. Calculations
   already implement this approach; other task kinds remain unsupported here.
2. **Risk-dependent verification.** Cheap deterministic checks first. Ambiguous
   reasoning goes to an independent review with explicit uncertainty; sensitive
   changes require existing user approval. Multiple agreeing models are not proof.
3. **Counterexample-first review.** For non-deterministic tasks, ask a reviewer to
   find a concrete contradiction against source evidence, initially without the
   worker's conclusion. Evaluate whether this reduces anchoring before adoption.
4. **Dependency-aware invalidation.** Eventually bind verified conclusions to
   specific source revisions; retract dependent conclusions when those sources
   change. Avoid invalidating all independent work. This dependency graph is not
   implemented by the current whole-task digest.
5. **Verified proposal is not a commit ticket.** A future host integration must
   recheck authority and freshness atomically at the write boundary, deduplicate
   execution, and distinguish an execution receipt from business success. Reuse
   existing freshness/receipt mechanisms; do not create a bypass or global lock.

For ordinary users, present three states: checking, ready for review, needs help.
Show reasons and evidence on demand. Hide configuration complexity, not uncertainty
or permission boundaries. These UI states are proposed, not implemented.

## Evaluation and adoption

Historical v1 fixtures, scores and recorded model responses are preserved.
`score_v2` in the canary test module separately reports action and evidence-pair
matches: a missing receipt means unverified, not proven non-execution. Safe stale
candidate alternatives and ambiguous old-next labels are explicitly enumerated.
This rubric is for future evaluations, not a retroactive claim of improvement.

Before operational adoption, predeclare cases, rubric, supported task kinds and
failure limits; run paired repeated model trials, including misleading claims,
source changes, unsupported tasks and missing evidence. Measure false acceptance,
false rejection, completion, end-to-end latency, and exposed usage independently.
Report sample sizes and uncertainty: zero observed errors is not zero risk.
The new deterministic tests do not replace these trials or host integration tests.
Input bytes alone are not token usage, subscription debit, or monetary savings.

Tests (no external dependencies or model calls):

```sh
python -B mcp/tests/test_verified_task.py
python -B mcp/tests/test_context_canary.py
python -B mcp/tests/test_context_shadow.py
```
