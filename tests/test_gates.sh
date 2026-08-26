#!/usr/bin/env bash
set -uo pipefail
# test_gates.sh — assertion-based smoke test of the integrity gates.
#   Verifies (in a throwaway workspace, no agent/compute):
#     1. arc-close 2-phase: 1st drafts (0), blanks refuse (4), KILL-defense refuse (5), filled seals (0)
#     2. ralph verify-gate: unchecked item without `verify:` is refused (3)
#   Exit 0 = all gates behaved as specified.

# Resolve the interpreter by running one — `command -v python3` also finds the Windows Store stub.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"/_pybin.sh
PY="$(yeoul_pybin)" || yeoul_pybin_die

BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
WS="$(mktemp -d)"; trap 'rm -rf "$WS"' EXIT
cd "$WS"; export YEOUL_PROJECTS="$WS/projects"
FAIL=0
# 🔴 count what was collected. "all gate tests passed" is also what a run that collected ZERO
#    checks prints — the summary has to carry its own denominator, and an empty run has to fail.
CHECKS=0; PASSED=0
assert() { # assert <desc> <expected> <actual>
  CHECKS=$((CHECKS+1))
  if [ "$2" = "$3" ]; then PASSED=$((PASSED+1)); echo "  ✓ $1 (exit $3)"
  else echo "  ✗ $1 — expected $2, got $3"; FAIL=1; fi
}
ok()  { CHECKS=$((CHECKS+1)); PASSED=$((PASSED+1)); echo "  ✓ $1"; }
bad() { CHECKS=$((CHECKS+1)); echo "  ✗ $1"; FAIL=1; }
check() { # check <desc> <cmd...> — passes if the command succeeds
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi
}

# portable in-place edit (GNU + BSD/macOS)
sedi() { sed "$1" "$2" > "$2.t" && mv "$2.t" "$2"; }

fill_spec() { # fill_spec <spec.md> — write a real design into the four load-bearing fields
  $PY - "$1" <<'PYEOF'
import sys
p = sys.argv[1]
vals = {
    'Goal': 'measure whether a seal can attach to an arc whose spec was never filled in',
    'Success condition': 'a blank spec is refused and a filled spec links, both shown by running it',
    'Kill-condition (falsifier)': 'a blank spec still links a seal, or a filled spec is refused',
    'Constraints': 'shell only, no mirror-stack code touched, must run with no ledger present',
}
out = []
for ln in open(p, encoding='utf-8'):
    for k, v in vals.items():
        # prefix match: the internal copy labels this field `**Kill-condition (falsifier)**`,
        # and an exact match would silently leave it blank — then the gate's correct refusal
        # reads as a test failure.
        if ln.startswith('- **%s' % k):
            ln = ln.rstrip('\n').rstrip() + ' ' + v + '\n'
            break
    out.append(ln)
open(p, 'w', encoding='utf-8').write(''.join(out))
PYEOF
}


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
# A seal may no longer attach to an arc with a blank spec (see the DUAL KEY block below),
# so this setup fills the design first — the thing under test here is the seal link.
fill_spec "$SARC/0001_spec.md"
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
fill_spec "$PARC/0001_spec.md"
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
$PY - "$ESUM" <<'PYDAMAGE'
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
$PY "$SUBSTANCE" --selftest >/dev/null 2>&1; assert "substance checker passes its own positive control" 0 $?
echo "    $($PY "$SUBSTANCE" --selftest 2>&1 | tail -1)"   # 🔴 print the denominator, not just green

subst_case() { # subst_case <desc> <answer> <expected-exit>
  "$BIN/arc-open" sc --topic="substance" --arcs-dir="$WS/arcs" >/dev/null 2>&1
  local A; A="$(ls -d "$WS"/arcs/*_sc)"
  "$BIN/arc-close" "$A" "KILL — sc" --stop=falsified >/dev/null 2>&1
  local S; S="$(ls "$A"/_SUMMARY_*.md)"
  sedi 's/- (fill in)/- concrete conclusion here/' "$S"
  # anchor/catalog have their own branches; drive the general branch with the candidate
  $PY - "$S" "$2" <<'PYFILL'
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
$PY - "$SBIN/substance_check.py" <<'PYSAB'
import sys
p = sys.argv[1]; s = open(p, encoding="utf-8").read()
i = s.index("def judge(label, ans):")
s = s[:i] + 'def judge(label, ans):\n    return "OK", ans\n\ndef _judge_disabled(label, ans):\n' + s[i + len("def judge(label, ans):\n"):]
open(p, "w", encoding="utf-8").write(s)
PYSAB
# the sabotage must actually have landed, or every assertion below passes vacuously
$PY "$SBIN/substance_check.py" --selftest >/dev/null 2>&1 \
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

# ═══════════════════════════════════════════════════════════════════════════════
# Signals must say only what the code checked.
# Each block below reproduces a field-reported defect (first-use report, 2026-08-24) and asserts
# the repaired behaviour. Every one of these went red against the pre-fix binary — see
# `revert-to-red` in the PR body; a test that cannot go red is not evidence.
# ═══════════════════════════════════════════════════════════════════════════════
echo
echo "── signal/evidence agreement ──"
NEW="$WS/new"; mkdir -p "$NEW"

# YL-01 · a `/` in the topic used to abort sed and leave a half-built project behind.
( cd "$NEW" && YEOUL_PROJECTS="$NEW/projects" "$BIN/yeoul-new" slashed --topic='fast/medium/slow' ) \
  >/dev/null 2>&1
assert "[YL-01] topic containing / scaffolds" 0 $?
if grep -qF 'fast/medium/slow' "$NEW/projects/slashed/design/spec.md" 2>/dev/null; then
  ok "[YL-01] topic substituted literally (not parsed as a sed expression)"; else bad "[YL-01] topic not rendered literally"; fi
# command substitution in a topic must stay text
( cd "$NEW" && YEOUL_PROJECTS="$NEW/projects" "$BIN/yeoul-new" inj --topic='$(id -u)' ) >/dev/null 2>&1
if grep -qF '$(id -u)' "$NEW/projects/inj/design/spec.md" 2>/dev/null; then
  ok "[YL-01] topic is not evaluated as shell"; else bad "[YL-01] topic was evaluated"; fi

# YL-01 (atomicity) · a failure anywhere must leave no partial project to collide with a retry.
STUB="$WS/stubbin"; rm -rf "$STUB"; cp -r "$BIN" "$STUB"
printf '#!/usr/bin/env bash\nexit 7\n' > "$STUB/arc-open"; chmod +x "$STUB/arc-open"
ROLL="$WS/roll"; mkdir -p "$ROLL"
( cd "$ROLL" && YEOUL_PROJECTS="$ROLL/projects" "$STUB/yeoul-new" doomed --topic='a/b' ) >/dev/null 2>&1
assert "[YL-01] failed scaffold propagates the real exit code" 7 $?
if [ -z "$(ls -A "$ROLL/projects" 2>/dev/null)" ]; then
  ok "[YL-01] failed scaffold left nothing behind (retry starts clean)"; else bad "[YL-01] partial scaffold survived"; fi
rm -rf "$STUB"

# YL-02 · the JOIN prompt is an instruction someone runs from an unknown cwd.
JP="$(ls "$NEW"/projects/slashed/design/arcs/*/JOIN_PROMPTS.md 2>/dev/null | head -1)"
ATTACH_LINE="$(grep -m1 'arc-attach' "$JP" 2>/dev/null | sed 's/^ *//')"
case "$ATTACH_LINE" in
  /*|'"/'*) ok "[YL-02] JOIN prompt emits an absolute attach path" ;;
  *) bad "[YL-02] JOIN prompt still emits a relative path: $ATTACH_LINE" ;;
esac
# the emitted line must actually run — from a cwd that is not the workspace
if ( cd / && eval "$ATTACH_LINE" ) >/dev/null 2>&1; then
  ok "[YL-02] the emitted first-action line runs from a foreign cwd"; else bad "[YL-02] emitted attach line does not run from /"; fi

# YL-03 · exit code must report whether the handoff was built.
HO="$WS/ho"; mkdir -p "$HO"
( cd "$HO" && YEOUL_PROJECTS="$HO/projects" "$BIN/yeoul-new" hp --topic='handoff path' ) >/dev/null 2>&1
HARC="$(ls -d "$HO"/projects/hp/design/arcs/*_hp 2>/dev/null | head -1)"
( cd "$HO" && "$BIN/arc-close" "$HARC" "GO: build it" --stop=converged ) >/dev/null 2>&1
HSUM="$(ls "$HARC"/_SUMMARY_*.md 2>/dev/null | head -1)"
sedi 's/- (fill in)/- the phase-owned runtime boundary is settled and snapshots are taken at transition edges/' "$HSUM"
( cd "$HO" && "$BIN/arc-close" "$HARC" "GO: build it" --stop=converged ) >/dev/null 2>&1
( cd "$HO" && YEOUL_PROJECTS="$HO/projects" "$BIN/build-handoff" hp ) >/dev/null 2>&1
assert "[YL-03] build-handoff exits 0 on the SUCCESS path (closed arc found)" 0 $?
if [ -f "$HO/projects/hp/dev/TODO.md" ]; then ok "[YL-03] build-handoff produced dev/TODO.md"; else bad "[YL-03] no TODO.md"; fi
( cd "$HO" && YEOUL_PROJECTS="$HO/projects" "$BIN/build-handoff" hp ) >/dev/null 2>&1
assert "[YL-03] a real failure (already exists) still exits non-zero" 1 $?

# YL-06 · `--all` has to mean all.
ARCHN="$( cd "$HO" && YEOUL_PROJECTS="$HO/projects" "$BIN/arc-list" --all 2>/dev/null | grep -c '_archive' )"
if [ "$ARCHN" -ge 1 ]; then ok "[YL-06] arc-list --all includes archived arcs ($ARCHN)"; else bad "[YL-06] --all still hides the archive"; fi
OPENN="$( cd "$HO" && YEOUL_PROJECTS="$HO/projects" "$BIN/arc-list" 2>/dev/null | grep -c '_archive' )"
if [ "$OPENN" -eq 0 ]; then ok "[YL-06] default listing still shows open arcs only"; else bad "[YL-06] default listing leaked archived arcs"; fi

# YL-08 · omitting --tokens must not look like a measured zero.
LG="$WS/lg"; mkdir -p "$LG"
"$BIN/loop-guard" "$LG" init --max-rounds=99 --token-budget=1000 >/dev/null 2>&1
"$BIN/loop-guard" "$LG" tick >/dev/null 2>&1
if "$BIN/loop-guard" "$LG" status 2>/dev/null | grep -q 'unmeasured='; then
  ok "[YL-08] a tick with no token count is flagged unmeasured (with a denominator)"
else bad "[YL-08] unmeasured ticks are indistinguishable from a measured zero"; fi
LG2="$WS/lg2"; mkdir -p "$LG2"
"$BIN/loop-guard" "$LG2" init --max-rounds=99 --token-budget=1000 >/dev/null 2>&1
"$BIN/loop-guard" "$LG2" tick --tokens=400 >/dev/null 2>&1
"$BIN/loop-guard" "$LG2" tick --tokens=400 >/dev/null 2>&1
if "$BIN/loop-guard" "$LG2" tick --tokens=400 2>/dev/null | grep -q 'STOP:budget'; then
  ok "[YL-08] a reported budget still stops the loop"; else bad "[YL-08] budget guard did not fire"; fi
if "$BIN/loop-guard" "$LG2" status 2>/dev/null | grep -q 'unmeasured='; then
  bad "[YL-08] measured ticks wrongly flagged unmeasured"; else ok "[YL-08] measured ticks carry no warning"; fi

# YL-09 · the seal message must name the condition the code actually tested.
if grep -rq 'install mirror-stack for sealing' "$BIN"/arc-close "$BIN"/close-project 2>/dev/null; then
  bad "[YL-09] seal message still blames installation for a PATH test"
else ok "[YL-09] seal message names the tested condition (\`am\` on PATH), not an assumed cause"; fi

# ── interpreter resolution: a name that resolves is not an interpreter that runs ──────────────
# Windows ships a Microsoft Store stub that answers to `python3` and exits 49 without running
# anything. `command -v python3` is satisfied by it, so the whole gate suite scored 34/48 on two
# Windows machines — printed as `✗ expected 0, got 49`, which reads like a verdict and is actually
# the absence of a measurement. Reproduced here with a stub, so this is testable off Windows.
echo
echo "── interpreter resolution ──"
# Say which interpreter this run actually used. Without it a failure report from another machine
# cannot distinguish "resolved a different interpreter" from "the check itself is broken there".
# 🔴 print the PATH too, not just the name and version. Two machines reported different results
#    with the same name and the same version — the interpreter each had resolved was a *different
#    venv* that happened to sit ahead on PATH, and the name+version line could not show that.
echo "  ℹ resolved: $PY -> $($PY -c 'import sys,platform; print(sys.executable, platform.python_version(), sys.platform)' 2>&1 | head -1)"
STUBD="$WS/stub"; mkdir -p "$STUBD"
mkstub() { printf '#!/usr/bin/env bash\necho "Python" >&2\nexit 49\n' > "$STUBD/$1"; chmod +x "$STUBD/$1"; }

mkstub python3
if ( PATH="$STUBD:$PATH"; . "$BIN/_pybin.sh"; [ "$(yeoul_pybin)" != "python3" ] ) 2>/dev/null; then
  ok "[PY-01] a stub that answers to the name is rejected (resolved by running, not by lookup)"
else bad "[PY-01] the stub was accepted as an interpreter"; fi

# the second Windows machine had a perfectly good `python` on PATH the whole time
# 🔴 find the real interpreter by RUNNING candidates. `command -v python3` here would hand back
#    the stub when this suite is itself run under a stubbed PATH — using a name lookup to locate a
#    real interpreter, inside the test for that exact bug.
REALPY=""
for c in "$(command -v python3)" "$(command -v python)" /usr/bin/python3 /usr/bin/python; do
  [ -n "$c" ] && "$c" -c 'raise SystemExit(0)' >/dev/null 2>&1 && { REALPY="$c"; break; }
done
# 🔴 a wrapper, not a symlink. `ln -s` is the only symlink this suite would use, and MSYS/Git Bash
#    copies the target instead of linking unless winsymlinks is set — copying a Windows python.exe
#    produces a broken standalone, so this check would fail for a reason that has nothing to do with
#    what it is testing.
printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$REALPY" > "$STUBD/python"; chmod +x "$STUBD/python"
if ( PATH="$STUBD:$PATH"; . "$BIN/_pybin.sh"; P="$(yeoul_pybin)"; $P -c 'raise SystemExit(0)' ) 2>/dev/null; then
  ok "[PY-02] falls through to a working interpreter under another name"
else bad "[PY-02] did not find the working interpreter that was on PATH"; fi

# and when nothing runs, it must stop the run — not skip the step and let the skip read as a pass.
# 🔴 This block must first ESTABLISH "nothing runs", and then check that it was established. The
#    earlier version asserted it: it stubbed python3/python/py and assumed that covered every
#    candidate. It did not — $YEOUL_PYTHON is tried first and is not a PATH name at all, and on
#    Windows the .exe forms are separate files. With an interpreter still reachable the resolver
#    correctly succeeded and these two checks failed, blaming the product for the test's own gap.
#    (Reproduced by running the suite with YEOUL_PYTHON set: 50/52, the same score reported from a
#    Windows machine.) A precondition that is assumed instead of measured is the defect this whole
#    suite is about, so it is now measured — and if it cannot be met the checks report inconclusive
#    rather than passing or failing, because neither verdict would mean anything.
rm -f "$STUBD/python"
for n in python3 python py python3.exe python.exe py.exe; do mkstub "$n"; done
if ( unset YEOUL_PYTHON; PATH="$STUBD:$PATH"; . "$BIN/_pybin.sh"; yeoul_pybin >/dev/null 2>&1 ); then
  CHECKS=$((CHECKS+2))
  echo "  ? [PY-03] could not establish 'no interpreter reachable' — an interpreter survived the"
  echo "        stubbing, so neither PY-03 check is evidence here. Not counted as a pass."
  FAIL=1
else
  ok "[PY-03] no working interpreter => resolution fails"
  OUT="$( unset YEOUL_PYTHON; PATH="$STUBD:$PATH" bash "$BIN/status" 2>&1 )"; RC=$?
  if [ "$RC" -ne 0 ] && printf '%s' "$OUT" | grep -q 'no working Python interpreter'; then
    ok "[PY-03] a script stops with a named cause (exit $RC), it does not skip silently"
  else bad "[PY-03] script exited $RC without naming the missing interpreter"; fi
fi
rm -rf "$STUBD"

# ── the verdict channel must not depend on the console encoding ───────────────────────────────
# Measured on Windows 2026-08-25: two machines, same PR. On one, two checks failed with
# `could not run the substance checker` — the checker had finished judging and then died *writing
# its result back*, because the answer contained an em-dash and stdout was cp949. stdout came back
# empty, the gate refused (correctly: an unmeasured field is not a passing field), and a genuine
# answer was rejected with nothing in the refusal pointing at encoding.
#
# 🔴 The second machine passed, and that green was a coincidence: cp1252 happens to contain the
#    em-dash, cp949 does not. Neither contains Hangul, and our summaries are written in Korean — so
#    both machines carry the same defect and only one showed it. Testing one synthetic encoding
#    would repeat the mistake, so this runs the two real code pages and asserts on a payload built
#    to be lethal to both: U+2014 (absent from cp949) and U+AC00 (absent from cp1252).
echo
echo "── verdict channel encoding ──"
# built from escapes on purpose: a literal Hangul sample would be a personalization leak in an
# English-only repo and setup/pre-publish-check.sh rejects it, correctly. U+2014 em-dash (absent
# from cp949) and U+AC00 (absent from cp1252) — one character for each machine's code page.
NONASCII="$(printf '\u2014 \uac00')"
ENCLINE="- **Sealed-condition cross-check**: converged ${NONASCII} design settled, non-ascii included"
TAB_="$(printf '\t')"
for CP in ascii cp949 cp1252; do
  EOUT="$( printf '%s' "$ENCLINE" | env -u PYTHONUTF8 PYTHONIOENCODING="$CP" \
           $PY "$BIN/substance_check.py" --label 'Sealed-condition cross-check' 2>/dev/null )"
  if [ -n "$EOUT" ] && [ "${EOUT%%"$TAB_"*}" = "OK" ]; then
    ok "[ENC-01/$CP] a non-ASCII answer still returns its verdict"
  else bad "[ENC-01/$CP] verdict channel produced [$EOUT]"; fi
  # 🔴 surviving is not enough — the answer must come back INTACT. Pinning the stream with
  #    errors="replace" would keep the code alive and hand back an answer full of `?`: the gate
  #    would then judge, report, and quote mangled evidence. Writing UTF-8 bytes to stdout.buffer
  #    sidesteps the console code page entirely, so this asserts the characters are still there.
  if printf '%s' "${EOUT#*"$TAB_"}" | grep -qF "$NONASCII"; then
    ok "[ENC-02/$CP] the answer round-trips intact, not replaced with '?'"
  else bad "[ENC-02/$CP] answer came back mangled: [${EOUT#*"$TAB_"}]"; fi
  # and the checker's own positive control has to run through that same channel, or it vouches for
  # nothing — it scored 27/27 on the machine where every real call carrying an em-dash was dying.
  ESELF="$( env -u PYTHONUTF8 PYTHONIOENCODING="$CP" $PY "$BIN/substance_check.py" --selftest 2>&1 )"
  if printf '%s' "$ESELF" | grep -q 'selftest: [0-9]*/[0-9]*'; then
    ok "[ENC-03/$CP] the checker's positive control passes through the channel it vouches for"
  else bad "[ENC-03/$CP] selftest did not survive: $(printf '%s' "$ESELF" | tail -1)"; fi
done

# ─────────────────────────────────────────────────────────────────────────────────────────
# DUAL KEY — the lock, and the guarantee that it does not become an install requirement.
#
# Measured 2026-08-26, before any of this existed:
#   · `arc-prereg` attached a seal to a spec with EVERY field blank — exit 0, not a word printed.
#   · A KILL close wrote "UNSEALED" into its _SUMMARY; a GO close wrote nothing about the seal at
#     all (grep count 0). The notice lived inside the KILL branch, so the one label that OPENS the
#     next step was the silent one.
#   · The closing banner said "blanks & KILL-defense checked" on every close, as a fixed string,
#     including closes where no KILL-defense section was ever produced.
# ─────────────────────────────────────────────────────────────────────────────────────────
DK="$WS/dk"; mkdir -p "$DK"
printf '%s\n' '{"claim_id":"dk-1","kill_condition":"the dual-key gate lets a blank spec through"}' > "$DK/led.jsonl"

# --- the lock: a blank spec may not take a seal ---
"$BIN/arc-open" dkblank --arcs-dir="$DK/arcs" >/dev/null 2>&1
DKB="$(ls -d "$DK"/arcs/*dkblank)"
"$BIN/arc-prereg" "$DKB" dk-1 "$DK/led.jsonl" >/dev/null 2>&1
assert "[DK-01] blank spec cannot take a seal" 7 $?
if [ ! -f "$DKB/.prereg" ]; then ok "[DK-02] refusal wrote nothing (no .prereg left behind)"
else bad "[DK-02] refused but a .prereg exists anyway"; fi

# --- and the other direction: a gate that only ever refuses is not a gate ---
"$BIN/arc-open" dkfull --arcs-dir="$DK/arcs" >/dev/null 2>&1
DKF="$(ls -d "$DK"/arcs/*dkfull)"
fill_spec "$DKF/0001_spec.md"
"$BIN/arc-prereg" "$DKF" dk-1 "$DK/led.jsonl" >/dev/null 2>&1
assert "[DK-03] a filled spec still links (the lock can say yes)" 0 $?

# --- the declaring door: EVERY close records which keys were turned ---
"$BIN/arc-open" dkgo --arcs-dir="$DK/arcs" >/dev/null 2>&1
DKG="$(ls -d "$DK"/arcs/*dkgo)"
"$BIN/arc-close" "$DKG" "GO — dual key test" >/dev/null 2>&1
DKSUM="$(ls "$DKG"/_SUMMARY_*.md)"
# 🔴 GO, not KILL. This is the path that used to say nothing.
if grep -qF -- '**Second key (pre-registration)**: none' "$DKSUM"; then
  ok "[DK-04] a GO close records that it closed with one key only"
else bad "[DK-04] GO close is silent about the seal state again"; fi
sedi 's/- (fill in)/- concrete conclusion here/' "$DKSUM"
DKOUT="$("$BIN/arc-close" "$DKG" "GO — dual key test" 2>&1)"; assert "[DK-05] GO close still seals" 0 $?
# the banner must name the gates that RAN — a GO close has no KILL-defense section to check
if printf '%s' "$DKOUT" | grep -q 'gates run:' && ! printf '%s' "$DKOUT" | grep -q 'KILL-defense'; then
  ok "[DK-06] the closing banner does not claim a KILL-defense check that never ran"
else bad "[DK-06] banner still claims KILL-defense on a GO close"; fi
if grep -qF -- '**Sealed claim**: none' "${YEOUL_INDEX:-$WS/KNOWLEDGE_INDEX.md}" 2>/dev/null; then
  ok "[DK-07] the knowledge index says 'none' instead of dropping the promised column"
else bad "[DK-07] index row omits the Sealed claim column again"; fi

# --- the record is harness-owned: it cannot be edited into a nicer story ---
"$BIN/arc-open" dktamper --arcs-dir="$DK/arcs" >/dev/null 2>&1
DKT="$(ls -d "$DK"/arcs/*dktamper)"
fill_spec "$DKT/0001_spec.md"
"$BIN/arc-prereg" "$DKT" dk-1 "$DK/led.jsonl" >/dev/null 2>&1
"$BIN/arc-close" "$DKT" "GO — tamper test" >/dev/null 2>&1
DKTSUM="$(ls "$DKT"/_SUMMARY_*.md)"
sedi 's/^- \*\*Second key (pre-registration)\*\*: sealed.*/- **Second key (pre-registration)**: none — closed with one key only (no seal linked; attestation-only)/' "$DKTSUM"
sedi 's/- (fill in)/- concrete conclusion here/' "$DKTSUM"
sedi 's/^\(- \*\*Result triggers the sealed condition?\*\*\): (unfilled).*/\1: no. The run produced four rows and the sealed condition requires zero, so it is not met./' "$DKTSUM"
"$BIN/arc-close" "$DKT" "GO — tamper test" >/dev/null 2>&1
assert "[DK-08] a hand-edited second-key line is refused" 8 $?

# --- the OTHER spec shape: templates/spec.md, where the label is followed by a prompt ---
# Two shapes exist. arc-open writes `- **Goal**:`; templates/spec.md writes
# `- **Goal** — what do you want to learn / build (observable):`. substance_check's extractor only
# strips the first, so handing it a template line verbatim would give the JUDGE THE PROMPT as if it
# were the answer — a lock that opens on a spec nobody filled. DK-10 is that vacuity check.
"$BIN/arc-open" dktpl --arcs-dir="$DK/arcs" >/dev/null 2>&1
DKP="$(ls -d "$DK"/arcs/*dktpl)"
cp "$(dirname "$BIN")/templates/spec.md" "$DKP/0001_spec.md"
"$BIN/arc-prereg" "$DKP" dk-1 "$DK/led.jsonl" >/dev/null 2>&1
assert "[DK-10] an unfilled template spec is refused (the prompt is not read as the answer)" 7 $?
# …and the template must have somewhere to write each answer. Its Kill-condition line ended in
# "untestable." with no colon, so there was no slot at all for the one field the seal is about.
fill_spec "$DKP/0001_spec.md"
"$BIN/arc-prereg" "$DKP" dk-1 "$DK/led.jsonl" >/dev/null 2>&1
assert "[DK-11] a filled template spec links (every field has a slot to write in)" 0 $?

# --- 🔴 the guarantee: none of this may turn mirror-stack into an install requirement ---
# `arc-prereg` is the ONLY command that needs a ledger, and it is only ever called by someone who
# already has one. Everything else must still run with no mirror-stack anywhere on PATH.
DKN="$WS/nomirror"; mkdir -p "$DKN"
NOMIRROR_FAIL=""
run_bare() { # run_bare <name> <cmd...>
  local n="$1"; shift
  env PATH=/usr/bin:/bin YEOUL_INDEX="$DKN/index.md" YEOUL_PROJECTS="$DKN/projects" "$@" >/dev/null 2>&1 \
    || NOMIRROR_FAIL="$NOMIRROR_FAIL $n"
}
run_bare yeoul-new "$BIN/yeoul-new" probe
run_bare arc-open "$BIN/arc-open" probe --arcs-dir="$DKN/arcs"
NB="$(ls -d "$DKN"/arcs/*probe 2>/dev/null | head -1)"
run_bare arc-list "$BIN/arc-list" --arcs-dir="$DKN/arcs"
run_bare arc-roles "$BIN/arc-roles" "$NB"
run_bare build-handoff "$BIN/build-handoff" probe
run_bare verify-gate "$BIN/verify-gate" "$DKN/projects/probe/dev/TODO.md"
run_bare loop-guard "$BIN/loop-guard" "$NB"
run_bare arc-close-draft "$BIN/arc-close" "$NB" "GO — no mirror"
[ -n "$NB" ] && sedi 's/- (fill in)/- concrete conclusion here/' "$(ls "$NB"/_SUMMARY_*.md)"
run_bare arc-close-seal "$BIN/arc-close" "$NB" "GO — no mirror"
if [ -z "$NOMIRROR_FAIL" ]; then
  ok "[DK-09] with no mirror-stack on PATH, every other command still runs (9/9)"
else bad "[DK-09] the dual key blocked a yeoul-only user:$NOMIRROR_FAIL"; fi

echo
if [ "$CHECKS" -eq 0 ]; then
  echo "⛔ 0/0 — no checks were collected; an empty run is a failure, not a pass"
  exit 1
fi
if [ "$FAIL" -eq 0 ]; then echo "✅ $PASSED/$CHECKS gate checks passed"
else echo "⛔ gate checks FAILED — $PASSED/$CHECKS passed"; fi
exit "$FAIL"
