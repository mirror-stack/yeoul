# Yeoul methodology

Yeoul is a **practice**, not just scripts. The scripts make the practice cheap and hard to skip; this
document is the runtime-independent method any agent (or human) can follow. If you only run the scripts
without honoring the gates, you get empty scaffolding — the value is the discipline.

## The shape

```
① topic  →  ② spec interview  →  ③ deliberation arc  →  ④ convergence  →  dev handoff  →  ⑤ dev loop
                (goal/success/kill/prior-art)   (roles, rounds, tickets)   (guards)     (GO gates)   (verify-gated)
```

Coupled throughout with a discipline primitive (pre-registration + a tamper-evident ledger — the
optional `mirror-stack` dependency). Seal the kill-condition *before* spending compute; record negatives indelibly.

## ① Topic
Pick a seed idea. Output: `{ topic, one-line framing, why now }`.

## ② Spec interview
Ask one item at a time (`bin/yeoul-new` scaffolds `design/spec.md`). Put **cheap rejections first**:
1. **Goal** — what to learn/build (observable).
2. **Prior art (Gate-1)** ★early — is this a closed question or an existing tool? Grade the delta:
   `wedge` / `footnote` / `none`. If **none**, STOP and confirm [reject / re-frame / proceed]. Don't
   interview a dead idea to the end. (`bin/closed_check.py` warns against a local registry if present.)
3. **Success condition** — what "it worked" looks like (observable).
4. **Kill-condition (falsifier)** — what "no/wrong" looks like. **No falsifier = untestable.**
5. **Constraints** — resources, substrate, time, out-of-scope.
6. **Roles** — which stances debate (default: analysis[red-team] · impl · repro).

Optionally seal the kill-condition now (mirror-stack pre-registration).

## ③ Deliberation arc
`bin/arc-open` (or `bin/yeoul-new` which wraps it) creates the arc: a thread, per-role ticket inboxes,
roster, join prompts. Two backends:

- **(A) in-session subagents** — spawn one agent per role via your runtime. Fast, synchronous.
  🧬 Spawn the **analysis (red-team) role on a *different model*** than the relay where possible —
  same-model debate shares blind spots (correlated errors) and weakens rebuttal.
- **(B) file-relay** — paste each role's join prompt into external agent tabs; each runs `bin/arc-attach`
  and works its ticket inbox. The **relay is the sole author of the thread**; roles answer only in their tickets.

**Rules (injected into every role):** no praise-first · verify before agreeing · ≥1 rebuttal/blind-spot ·
self-critique your own proposal · run the 7-check before concluding · don't close on a single negative.

## ④ Convergence
Each round, the relay summarizes and judges. **Every round summary must include 3 lines:**
- **Re-anchor** — still consistent with the spec's success- and kill-conditions? (deliberation drifts 76–89%)
- **Flip log** — who changed position, which direction (right→wrong / wrong→right)? (sycophantic flips are mostly right→wrong)
- **Consensus quality** — unanimity with no initial disagreement is an **⚠️ alarm** (suspected sycophancy),
  not a convergence credit; overturning a *wrong* consensus is a credit.

`bin/loop-guard` bounds runaway (max-rounds / token-budget / no-progress). Convergence itself is a semantic
call, not the guard's job. **More rounds do not improve quality** — the guards exist because debate drifts.

Close with `bin/arc-close` (2-phase): it drafts a summary; you fill the blanks; re-running seals only when
they're filled. A **falsified/KILL** close additionally requires the **🛡️ KILL-defense 5-check**:
anchor (positive control) reproduced · ≥2 independent angles converged · implementation defect ruled out ·
catalog cross-check · verbatim kill-wording. This is the anti-premature-closure gate.

**Sealed kill-condition injection.** If you sealed the kill-condition (mirror-stack `mm_preregister`) and
linked it to the arc (`bin/arc-prereg <arc_dir> <claim_id> [ledger]`), the KILL-defense check no longer asks
the agent to *type* whether the verdict matches the pre-registration. Instead the harness reads the sealed
kill-condition from the ledger and **injects it verbatim** into the record; on close it refuses if that line
was edited. The agent is not the author of the condition, so it cannot be silently widened at close.
Scope, honestly: this fixes the *condition* by reference — whether the result actually triggers it remains a
judgment the agent asserts, and this is **not** "machine-verified honesty", only a removed goalpost. Without a
linked seal the field stays attestation-only and the close is stamped `⚠️ UNSEALED` — the missing seal is itself
the signal.

## ⑤ Dev handoff + loop
On GO, `bin/build-handoff` generates `dev/dev-plan.md` + `dev/TODO.md` inheriting the spec + verdict.
**Translate the verdict into TODO items, each ending with `verify: <exit-0 command>`.** Items without a
verify command are refused by the loop and stay manual.

> **Verify-command cwd**: verify commands run with the working directory set to where you launch the loop
> (the workspace root, i.e. where `projects/` lives) — **not** the project's `dev/` folder. So write paths
> as workspace-relative (`scripts/foo.sh`), and decide up front where built artifacts live. Ambiguous
> relative paths are the most common way a verify command passes in one place and fails in another.

Run the dev loop two ways (Ralph pattern):
- **(A) in-session** — the session drives each round with a subagent: implement the top item → run its
  `verify:` command → check off only on exit 0 → re-verify prior items. Preferred; no nesting.
- **(B) unattended** — `bin/ralph <name>` from a terminal (it shells out to a headless agent CLI, so it
  can't run inside that same agent). Bounded by loop-guard.

**Loop-forbidden (belongs to the human/session):** measurement runs, sealing, PASS/KILL judgment. The loop's
safety comes from the machine-verification gate, not from the loop — it is only as good as your verify commands.

The gate is **harness-enforced, not requested**: after each round the harness runs `bin/verify-gate <TODO> --revert`,
which independently re-runs the `verify:` command of every checked item and flips any that don't exit 0 back to
`[ ]`. `ralph` does this automatically; in backend A, the session must run it too. A checkbox survives only if
its verify command actually passes when the *harness* runs it — the agent's word is not trusted.

## Exits
- **graduate** (success): `bin/yeoul-graduate` → moves the project out of the incubator, leaves a pointer.
- **close-project** (retire/reject): `bin/close-project` → archives with a `_CLOSED.md`, freezes open arcs,
  optionally seals the closure. History is preserved — no silent deletion.

## Invariant checkpoints (never automate)
Graduation, closing, and any irreversible/outward action are human confirmations. The loop runtimes are
borrowed; the honesty gates are yours.
