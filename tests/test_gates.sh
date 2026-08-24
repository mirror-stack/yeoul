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
# trivial evasion must be rejected (minimal-substance check) — keep the "← hint" so the
# answer-extraction (Unicode ← strip) is actually exercised, not eaten by the test.
sedi 's/(unfilled)/yes/g' "$SUM"
"$BIN/arc-close" "$ARC" "KILL — test" --stop=falsified >/dev/null 2>&1; assert "trivial 'yes' answers refused (hint preserved)" 5 $?
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

# --- the sealed anchor must not depend on the label the closing agent writes ---
# Regression: a `converged` close used to switch the injection off entirely, so a sealed arc could be
# closed as a PASS with the pre-registered bar never mentioned. The label is agent-written; the seal is not.
"$BIN/arc-open" pv --topic="sealed pass" --arcs-dir="$WS/arcs" >/dev/null 2>&1
PARC="$(ls -d "$WS"/arcs/*_pv)"
YEOUL_LEDGER="$LEDGER" "$BIN/arc-prereg" "$PARC" c1 >/dev/null 2>&1
"$BIN/arc-close" "$PARC" "converged — design settled" --stop=converged >/dev/null 2>&1   # draft
PSUM="$(ls "$PARC"/_SUMMARY_*.md)"
grep -qF "effect size d < 0.2 over >= 3 seeds" "$PSUM" \
  && echo "  ✓ sealed condition injected on a non-KILL close too" \
  || { echo "  ✗ non-KILL close skipped the sealed condition"; FAIL=1; }
sedi 's/- (fill in)/- concrete conclusion/' "$PSUM"
"$BIN/arc-close" "$PARC" "converged — design settled" --stop=converged >/dev/null 2>&1; assert "PASS close refuses while the cross-check is unfilled" 5 $?
sedi 's/(unfilled)/yes/' "$PSUM"
"$BIN/arc-close" "$PARC" "converged — design settled" --stop=converged >/dev/null 2>&1; assert "PASS close refuses a trivial cross-check answer" 5 $?
sedi 's/^- \*\*Result triggers.*/- **Result triggers the sealed condition?**: no — measured d = 0.61, well clear of the 0.2 bar/' "$PSUM"
sedi 's/^  > effect size.*/  > effect size d < 0.9 (widened)/' "$PSUM"
"$BIN/arc-close" "$PARC" "converged — design settled" --stop=converged >/dev/null 2>&1; assert "PASS close refuses a widened sealed line" 5 $?
sedi 's/^  > effect size.*/  > effect size d < 0.2 over >= 3 seeds/' "$PSUM"
"$BIN/arc-close" "$PARC" "converged — design settled" --stop=converged >/dev/null 2>&1; assert "PASS close seals once the cross-check is answered" 0 $?

# a .prereg that no longer resolves is a silent way around the gate — it must be refused, not skipped
"$BIN/arc-open" br --topic="broken anchor" --arcs-dir="$WS/arcs" >/dev/null 2>&1
BARC="$(ls -d "$WS"/arcs/*_br)"
printf 'c1\n%s\n' "$LEDGER" > "$BARC/.prereg"
"$BIN/arc-close" "$BARC" "converged — ok" --stop=converged >/dev/null 2>&1   # draft
BSUM="$(ls "$BARC"/_SUMMARY_*.md)"
sedi 's/- (fill in)/- concrete conclusion/' "$BSUM"
sedi 's/^- \*\*Result triggers.*/- **Result triggers the sealed condition?**: no — measured d = 0.61, clear of the bar/' "$BSUM"
printf 'c_typo\n%s\n' "$LEDGER" > "$BARC/.prereg"     # anchor now unresolvable
"$BIN/arc-close" "$BARC" "converged — ok" --stop=converged >/dev/null 2>&1; assert "broken .prereg anchor is refused, not silently skipped" 5 $?

# positive control: an arc with no seal at all still closes normally (we tightened, not bricked)
"$BIN/arc-open" ns --topic="no seal" --arcs-dir="$WS/arcs" >/dev/null 2>&1
NARC="$(ls -d "$WS"/arcs/*_ns)"
"$BIN/arc-close" "$NARC" "converged — design settled" --stop=converged >/dev/null 2>&1   # draft
NSUM="$(ls "$NARC"/_SUMMARY_*.md)"
sedi 's/- (fill in)/- concrete conclusion/' "$NSUM"
"$BIN/arc-close" "$NARC" "converged — design settled" --stop=converged >/dev/null 2>&1; assert "unsealed PASS close is unaffected" 0 $?

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
# decoy: an appended `verify: `true`` must NOT override a real failing first command (greedy-extraction bug)
T3="$WS/t3.md"
printf -- '- [x] decoy. verify: `false` verify: `true`\n' > "$T3"
"$BIN/verify-gate" "$T3" --revert >/dev/null 2>&1
grep -q '^- \[ \] decoy' "$T3" && echo "  ✓ decoy double-verify reverted (first block wins)" || { echo "  ✗ decoy passed (greedy bug)"; FAIL=1; }

# --- clause-deletion bypass: ticking a box after deleting `verify:` must not survive ---
# Regression: the gate keys on text the agent writes, so a checked item with the clause removed used
# to be invisible to it and passed silently. Observed, not hypothetical.
T4="$WS/t4.md"
printf -- '- [x] deleted its own verify clause\n' > "$T4"
"$BIN/verify-gate" "$T4" >/dev/null 2>&1; assert "clause-less checked item passes without --require-verify (compat)" 0 $?
"$BIN/verify-gate" "$T4" --revert --require-verify >/dev/null 2>&1; assert "clause-less checked item fails with --require-verify" 1 $?
grep -q '^- \[ \] deleted its own verify clause' "$T4" && echo "  ✓ clause-less box reverted to [ ]" || { echo "  ✗ clause-less box survived"; FAIL=1; }
# a genuine passing item must still survive under the same flag (no false positives)
printf -- '- [x] real. verify: `true`\n' > "$T4"
"$BIN/verify-gate" "$T4" --revert --require-verify >/dev/null 2>&1; assert "genuine checked item still passes under --require-verify" 0 $?
grep -q '^- \[x\] real' "$T4" && echo "  ✓ genuine box left checked" || { echo "  ✗ genuine box wrongly reverted"; FAIL=1; }
# ralph must refuse a TODO whose CHECKED item lacks a verify clause (was only checking unchecked ones)
printf -- '- [x] checked without verify\n- [ ] ok. verify: `true`\n' > "$WS/projects/p/dev/TODO.md"
"$BIN/ralph" p >/dev/null 2>&1; assert "ralph refuses a checked item without verify" 3 $?

# --- index-append: the conclusion must survive any list style, and a miss must be loud ---
# Regression: the extractor used to assume a `- ` bullet, so a numbered list silently indexed
# an empty conclusion while still logging success. Observed in the wild, not hypothetical.
IDX_ARC="$WS/idx_arc"; mkdir -p "$IDX_ARC"; export YEOUL_INDEX="$WS/KI.md"
idx_case() { # idx_case <desc> <first-line-of-section> <expected-substring>
  rm -f "$YEOUL_INDEX"
  printf '# close\n- **Closed**: 2026-01-01\n- **stop_reason**: converged\n- **Verdict**: v\n\n## What was closed\n%s\n\n## Evidence\n- none\n' \
    "$2" > "$IDX_ARC/_SUMMARY_idx_arc.md"
  "$BIN/index-append" "$IDX_ARC" >/dev/null 2>&1
  grep -qF "$3" "$YEOUL_INDEX" && echo "  ✓ index-append: $1" || { echo "  ✗ index-append: $1 — '$3' not indexed"; FAIL=1; }
}
idx_case "bullet list"        '- bullet conclusion'   '**Closed**: bullet conclusion'
idx_case "numbered list"      '1. numbered conclusion' '**Closed**: numbered conclusion'
idx_case "paren-numbered"     '1) paren conclusion'    '**Closed**: paren conclusion'
idx_case "bold-numbered kept" '**1. bold conclusion**' '**Closed**: **1. bold conclusion**'
idx_case "leading blockquote" '> note line
- after the quote'                                     '**Closed**: after the quote'
# a genuine miss must be visible in the output, not silent
rm -f "$YEOUL_INDEX"
printf '# close\n- **Closed**: 2026-01-01\n- **stop_reason**: converged\n- **Verdict**: v\n\n## Evidence\n- none\n' \
  > "$IDX_ARC/_SUMMARY_idx_arc.md"
"$BIN/index-append" "$IDX_ARC" 2>&1 | grep -q "could not extract" \
  && echo "  ✓ index-append warns loudly when extraction misses" \
  || { echo "  ✗ index-append failed silently"; FAIL=1; }
"$BIN/index-append" "$IDX_ARC" >/dev/null 2>&1; assert "index-append never blocks the close" 0 $?

# --- encoding damage must FAIL CLOSED (regression: 2026-08-24 Windows/CP949 field report) ---
# What happened: on Windows the UTF-8 bytes were decoded as CP949, so the `←` hint marker
# survived the strip. The answer "yes" then arrived as a 43-char string wearing the hint as
# its body — it matched no entry in the trivial list AND cleared the >=6 length check, so the
# arc SEALED. The block above already keeps a `←` hint to exercise extraction, but it runs in
# a UTF-8 locale, so it could never fire. We inject the damage directly: this now fails on any
# platform, not only on the one where it was found.
"$BIN/arc-open" enc --topic="encoding gate" --arcs-dir="$WS/arcs" >/dev/null 2>&1
EARC="$(ls -d "$WS"/arcs/*_enc)"
"$BIN/arc-close" "$EARC" "KILL — enc" --stop=falsified >/dev/null 2>&1
ESUM="$(ls "$EARC"/_SUMMARY_*.md)"
sedi 's/- (fill in)/- concrete conclusion here/' "$ESUM"
sedi 's/(unfilled)/yes/g' "$ESUM"
python3 - "$ESUM" <<'PYDAMAGE'
import sys
p = sys.argv[1]
out = []
for line in open(p, encoding="utf-8"):
    # only the answer lines get mis-decoded; ASCII structure survives CP949 either way
    if line.startswith("- **"):
        line = line.encode("utf-8").decode("cp949", "replace")
    out.append(line)
open(p, "w", encoding="utf-8").write("".join(out))
PYDAMAGE
# the damage must actually have landed — otherwise every check below passes vacuously
grep -q "$(printf '\357\277\275')" "$ESUM" \
  && echo "  ✓ damage injected (replacement chars present)" \
  || { echo "  ✗ damage did NOT land — the checks below would pass for the wrong reason"; FAIL=1; }
# run the gate ONCE and judge both the code and the reason from the same run
ENCOUT="$("$BIN/arc-close" "$EARC" "KILL — enc" --stop=falsified 2>&1)"; ENCRC=$?
assert "encoding damage fails closed (never seals)" 5 "$ENCRC"
ls -d "$WS/arcs/_archive"/*_enc >/dev/null 2>&1 \
  && { echo "  ✗ SEALED despite unreadable answers"; FAIL=1; } \
  || echo "  ✓ damaged arc not archived"
# and the refusal must say WHY — "could not judge" is not "refused on the merits"
case "$ENCOUT" in
  *"not readable as UTF-8"*) echo "  ✓ refusal names the encoding damage" ;;
  *) echo "  ✗ refused for another reason: $(printf '%s' "$ENCOUT" | tail -1)"; FAIL=1 ;;
esac

# --- substance check: the CLASS, not just the CP949 case (2026-08-24) ---
# The block above pinned one *case* (encoding damage). The class is wider: the substance check
# was `[ ${#vans} -ge 6 ]`, so ANY >=6-char non-answer sealed. Measured before the repair:
# 28 of 28 evasive answers sealed. These assertions pin the class in BOTH directions — a
# repair that only tightened would pass the top half and quietly reject real answers.
SUBSTANCE="$BIN/substance_check.py"
python3 "$SUBSTANCE" --selftest >/dev/null 2>&1; assert "substance checker passes its own positive control" 0 $?
echo "    $(python3 "$SUBSTANCE" --selftest 2>&1 | tail -1)"   # 🔴 print the denominator, not just green

subst_case() { # subst_case <desc> <answer> <expected-exit>
  "$BIN/arc-open" sc --topic="substance" --arcs-dir="$WS/arcs" >/dev/null 2>&1
  local A; A="$(ls -d "$WS"/arcs/*_sc)"
  "$BIN/arc-close" "$A" "KILL — sc" --stop=falsified >/dev/null 2>&1
  local S; S="$(ls "$A"/_SUMMARY_*.md)"
  sedi 's/- (fill in)/- concrete conclusion here/' "$S"
  # anchor/catalog have their own branches; drive the general branch with the candidate
  python3 - "$S" "$2" <<'PYFILL'
import sys, re
p, ans = sys.argv[1], sys.argv[2]
out = []
for line in open(p, encoding="utf-8"):
    if "(unfilled)" in line and line.startswith("- **"):
        label = re.match(r"^- \*\*([^*]+)\*\*", line).group(1)
        hint = " ←" + line.split("←", 1)[1].rstrip("\n") if "←" in line else ""
        if "Anchor" in label:    body = "anchor reproduced 3x (seal 84007e65)"
        elif "Catalog" in label: body = "vacuous_pass"
        else:                    body = ans
        out.append(f"- **{label}**: {body}{hint}\n"); continue
    out.append(line)
open(p, "w", encoding="utf-8").write("".join(out))
PYFILL
  "$BIN/arc-close" "$A" "KILL — sc" --stop=falsified >/dev/null 2>&1
  assert "$1" "$3" $?
  rm -rf "$A" "$WS/arcs/_archive/$(basename "$A")" 2>/dev/null
}
# must be REFUSED (5) — each cleared the old >=6-char bar and sealed
subst_case "evasive 'aaaaaa' refused"          'aaaaaa'          5
subst_case "evasive 'yes yes' refused"         'yes yes'         5
subst_case "evasive 'yes ok' refused"          'yes ok'          5
subst_case "evasive 'qwerty' refused"          'qwerty'          5
subst_case "evasive '......' refused"          '......'          5
subst_case "deferral 'TODO later' refused"     'TODO later'      5
# must still SEAL (0) — the counter-accident: raising a length bar would reject these
subst_case "short genuine answer still seals"  'd=0.05 < 0.2, under the sealed bar' 0
subst_case "genuine answer carrying a deferral CLAUSE still seals" \
           'not run — the face arm is absent so no anchor could be formed; recorded as verdict-void' 0

# --- the positive control must be LOAD-BEARING, not decorative ---
# A documented fallback is untested code. Sabotage the checker so it can never say no, then
# assert the gate REFUSES TO INTERPRET (exit 6) instead of sealing an evasive answer.
SBIN="$(mktemp -d)"; cp "$BIN"/* "$SBIN/" 2>/dev/null
python3 - "$SBIN/substance_check.py" <<'PYSAB'
import sys
p = sys.argv[1]; s = open(p, encoding="utf-8").read()
i = s.index("def judge(label, ans):")
s = s[:i] + 'def judge(label, ans):\n    return "OK", ans\n\ndef _judge_disabled(label, ans):\n' + s[i + len("def judge(label, ans):\n"):]
open(p, "w", encoding="utf-8").write(s)
PYSAB
# the sabotage must actually have landed, or every assertion below passes vacuously
python3 "$SBIN/substance_check.py" --selftest >/dev/null 2>&1 \
  && { echo "  ✗ sabotage did NOT land — the checks below would pass for the wrong reason"; FAIL=1; } \
  || echo "  ✓ sabotage landed (checker can no longer fail a planted violation)"
"$SBIN/arc-open" sb --topic="sabotage" --arcs-dir="$WS/arcs" >/dev/null 2>&1
SBARC="$(ls -d "$WS"/arcs/*_sb)"
"$SBIN/arc-close" "$SBARC" "KILL — sb" --stop=falsified >/dev/null 2>&1
SBSUM="$(ls "$SBARC"/_SUMMARY_*.md)"
sedi 's/- (fill in)/- concrete conclusion here/' "$SBSUM"
sedi 's/(unfilled)/yes ok/g' "$SBSUM"
"$SBIN/arc-close" "$SBARC" "KILL — sb" --stop=falsified >/dev/null 2>&1
assert "broken checker => gate refuses to interpret (does not seal)" 6 $?
ls -d "$WS/arcs/_archive"/*_sb >/dev/null 2>&1 \
  && { echo "  ✗ SEALED while the checker was broken"; FAIL=1; } \
  || echo "  ✓ nothing archived while the instrument was broken"
rm -rf "$SBIN"

echo
if [ "$FAIL" -eq 0 ]; then echo "✅ all gate tests passed"; else echo "⛔ gate tests FAILED"; fi
exit "$FAIL"
