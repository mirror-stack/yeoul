#!/usr/bin/env bash
set -euo pipefail
# demo.sh — a runnable worked example of the Yeoul lifecycle (self-contained, temp workspace).
#   Shows: scaffold → open arc → 2-phase close with the KILL-defense gate → dev handoff → verify-gate.
#   No agent, no GPU, no sealing — just the structure and the gates. Safe to run anywhere.

BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
WS="$(mktemp -d)"; trap 'rm -rf "$WS"' EXIT
cd "$WS"
export YEOUL_PROJECTS="$WS/projects"

echo "### workspace: $WS"
echo
echo "### 1) scaffold a project + open a deliberation arc"
"$BIN/yeoul-new" widget-idea --topic="does batching speed up widget builds" >/dev/null
ARC="$(ls -d "$WS"/projects/widget-idea/design/arcs/*_widget-idea)"
echo "    arc: ${ARC#$WS/}"

echo
echo "### 2) try to close as KILL — the gate refuses until the 5-check is honestly filled"
"$BIN/arc-close" "$ARC" "KILL — batching showed no speedup" --stop=falsified >/dev/null   # draft
echo -n "    re-run with blanks: "; "$BIN/arc-close" "$ARC" "KILL" --stop=falsified >/dev/null 2>&1 && echo "sealed" || echo "REFUSED (as intended)"
SUM="$(ls "$ARC"/_SUMMARY_*.md)"
sed -i 's/- (fill in)/- batching gave no measurable speedup/' "$SUM"
sed -i 's/(unfilled)[^$]*/reproduced\/converged\/ruled-out (demo)/' "$SUM"
echo -n "    filled + re-run: "; "$BIN/arc-close" "$ARC" "KILL — no speedup" --stop=falsified >/dev/null 2>&1 && echo "SEALED + archived" || echo "still refused"

echo
echo "### 3) (parallel) a GO project → dev handoff → verify-gate"
"$BIN/yeoul-new" widget-go --topic="add a build cache" --no-arc >/dev/null
"$BIN/build-handoff" widget-go >/dev/null
echo -n "    ralph on default TODO (has non-verify items): "
"$BIN/ralph" widget-go >/dev/null 2>&1 && echo "ran" || echo "REFUSED (exit $?) — items need 'verify:' commands"

echo
echo "### 4) status"
"$BIN/status"
echo
echo "### done — the gates fired without any agent or compute."
