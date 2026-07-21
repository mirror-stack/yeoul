#!/usr/bin/env bash
set -uo pipefail
# test_gates.sh — assertion-based smoke test of the integrity gates.
#   Verifies (in a throwaway workspace, no agent/compute):
#     1. arc-close 2-phase: 1st drafts (0), blanks refuse (4), KILL-defense refuse (5), filled seals (0)
#     2. ralph verify-gate: unchecked item without `verify:` is refused (3)
#   Exit 0 = all gates behaved as specified.

BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
WS="$(mktemp -d)"; trap 'rm -rf "$WS"' EXIT
cd "$WS"; export YEOUL_PROJECTS="$WS/projects"
FAIL=0
assert() { # assert <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then echo "  ✓ $1 (exit $3)"; else echo "  ✗ $1 — expected $2, got $3"; FAIL=1; fi
}

# portable in-place edit (GNU + BSD/macOS)
sedi() { sed "$1" "$2" > "$2.t" && mv "$2.t" "$2"; }

# --- arc-close 2-phase KILL gate ---
"$BIN/arc-open" g --topic="gate test" --arcs-dir="$WS/arcs" >/dev/null 2>&1
ARC="$(ls -d "$WS"/arcs/*_g)"
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "1st run drafts" 0 $?
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "blanks refuse" 4 $?
SUM="$(ls "$ARC"/_SUMMARY_*.md)"
sedi 's/- (fill in)/- concrete conclusion here/' "$SUM"
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "KILL-defense refuse (unfilled)" 5 $?
# trivial evasion must be rejected (new minimal-substance check)
sedi 's/(unfilled)[^$]*/yes/' "$SUM"
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "trivial 'yes' answers refused" 5 $?
# per-field-valid answers seal
sedi 's/^- \*\*Anchor.*/- **Anchor (positive control) reproduced**: anchor reproduced over 3 runs/' "$SUM"
sedi 's/^- \*\*Independent.*/- **Independent angles converged**: 2 independent angles agreed/' "$SUM"
sedi 's/^- \*\*Implementation.*/- **Implementation defect ruled out**: mechanism reviewed, correct/' "$SUM"
sedi 's/^- \*\*Catalog.*/- **Catalog cross-check**: none/' "$SUM"
sedi 's/^- \*\*Kill wording.*/- **Kill wording match**: matches the sealed kill-condition verbatim/' "$SUM"
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "substantive answers seal+archive" 0 $?
[ -d "$WS/arcs/_archive"/*_g ] && echo "  ✓ archived" || { echo "  ✗ not archived"; FAIL=1; }
grep -q "UNSEALED" "$WS/arcs/_archive"/*_g/_SUMMARY_*.md && echo "  ✓ unsealed close stamped UNSEALED" || { echo "  ✗ missing UNSEALED stamp"; FAIL=1; }

# --- ① sealed kill-condition injection (harness injects verbatim; agent is not its author) ---
LEDGER="$WS/ledger.jsonl"
printf '%s\n' '{"claim_id":"c1","metric":"m","kill_condition":"effect size d < 0.2 over >= 3 seeds","kill_threshold":{}}' > "$LEDGER"
"$BIN/arc-open" s --topic="sealed gate" --arcs-dir="$WS/arcs" >/dev/null 2>&1
SARC="$(ls -d "$WS"/arcs/*_s)"
YEOUL_LEDGER="$LEDGER" "$BIN/arc-prereg" "$SARC" c1 >/dev/null 2>&1; assert "arc-prereg links a valid claim" 0 $?
"$BIN/arc-close" "$SARC" "KILL — sealed" --stop=falsified >/dev/null 2>&1   # draft (injects verbatim)
SSUM="$(ls "$SARC"/_SUMMARY_*.md)"
grep -qF "effect size d < 0.2 over >= 3 seeds" "$SSUM" && echo "  ✓ sealed kill-condition injected verbatim" || { echo "  ✗ verbatim not injected"; FAIL=1; }
grep -q "Kill wording match" "$SSUM" && { echo "  ✗ attestable Kill-wording field still present"; FAIL=1; } || echo "  ✓ attestable Kill-wording field replaced by injected reference"
sedi 's/- (fill in)/- concrete conclusion/' "$SSUM"     # clear the (fill in) blanks first
# now widening the sealed line must be refused
sedi 's/^  > effect size.*/  > effect size d < 0.9 (widened)/' "$SSUM"
"$BIN/arc-close" "$SARC" "KILL — sealed" --stop=falsified >/dev/null 2>&1; assert "editing the sealed condition is refused" 5 $?
# restore the verbatim + fill the fields → seals
sedi 's/^  > effect size.*/  > effect size d < 0.2 over >= 3 seeds/' "$SSUM"
sedi 's/^- \*\*Result triggers.*/- **Result triggers the sealed condition?**: yes, measured d = 0.05 < 0.2/' "$SSUM"
sedi 's/^- \*\*Anchor.*/- **Anchor (positive control) reproduced**: anchor reproduced over 3 runs/' "$SSUM"
sedi 's/^- \*\*Independent.*/- **Independent angles converged**: 2 angles agreed/' "$SSUM"
sedi 's/^- \*\*Implementation.*/- **Implementation defect ruled out**: mechanism reviewed, correct/' "$SSUM"
sedi 's/^- \*\*Catalog.*/- **Catalog cross-check**: none/' "$SSUM"
"$BIN/arc-close" "$SARC" "KILL — sealed" --stop=falsified >/dev/null 2>&1; assert "sealed close seals once verbatim intact + filled" 0 $?

# --- ralph verify-gate ---
"$BIN/yeoul-new" p --no-arc >/dev/null 2>&1
printf -- '- [ ] no verify command here\n' > "$WS/projects/p/dev/TODO.md"
"$BIN/ralph" p >/dev/null 2>&1; assert "ralph refuses ungated item" 3 $?
printf -- '- [ ] ok. verify: `true`\n' > "$WS/projects/p/dev/TODO.md"
# (loop would enter; we only assert the gate lets an eligible TODO past — check it does NOT exit 3)
"$BIN/ralph" p --agent-cmd="true" --max-rounds=1 >/dev/null 2>&1; rc=$?
[ "$rc" != "3" ] && echo "  ✓ ralph admits gated item (exit $rc ≠ 3)" || { echo "  ✗ ralph wrongly refused gated item"; FAIL=1; }

# --- harness-enforced verify-gate: a falsely-checked item is re-run and reverted ---
T2="$WS/t2.md"
printf -- '- [x] lie: claimed done but verify fails. verify: `false`\n- [x] honest. verify: `true`\n' > "$T2"
"$BIN/verify-gate" "$T2" --revert >/dev/null 2>&1; assert "verify-gate flags a failing checked item" 1 $?
grep -q '^- \[ \] lie' "$T2" && echo "  ✓ harness reverted the false [x] → [ ]" || { echo "  ✗ false [x] not reverted"; FAIL=1; }
grep -q '^- \[x\] honest' "$T2" && echo "  ✓ genuine [x] left intact" || { echo "  ✗ genuine [x] wrongly reverted"; FAIL=1; }

echo
if [ "$FAIL" -eq 0 ]; then echo "✅ all gate tests passed"; else echo "⛔ gate tests FAILED"; fi
exit "$FAIL"
