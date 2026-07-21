#!/usr/bin/env bash
set -uo pipefail
# pre-publish-check.sh — the "not embarrassing" gate. Run before making the repo public.
#   1) personalization leak scan (Korean persona / family / private paths / internal names)
#   2) over-claim copy scan (marketing superlatives the discipline forbids)
#   3) empty-scaffolding guard (a runnable worked example must exist)
# Exit 0 = clean · non-zero = issues found (do not publish yet).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
FAIL=0

echo "── 1) personalization leak scan ──"
# Generic de-personalization checks (no internal codenames are enumerated here, so this file ships clean):
#   (a) any Hangul — this repo is English-only, so any Korean text is a leak;
#   (b) private absolute paths (/home/... or /data/...) that must not ship.
# Intentional localizations are allowed (e.g. README_KO.md, *.ko.md, docs/ko/); Hangul anywhere else is a leak.
LEAKS="$( { grep -rlP '\p{Hangul}' "$REPO" --exclude-dir=.git --exclude-dir=ko --exclude='*_KO.md' --exclude='*.ko.md' 2>/dev/null; \
            grep -rlE '(/home|/data)/[A-Za-z]' "$REPO" --include='*.sh' --include='*.py' --include='*.md' --include='*.json' --exclude-dir=.git 2>/dev/null; } | sort -u )"
if [ -n "$LEAKS" ]; then
  echo "$LEAKS" | sed 's/^/    /'
  echo "  ✗ personalization leaks found (Hangul or private absolute path)"
  FAIL=1
else
  echo "  ✓ clean"
fi

echo "── 2) over-claim copy scan ──"
# Superlatives / unfalsifiable marketing the discipline forbids in our own docs.
CLAIM_RE='revolutionary|world.?first|state.of.the.art|SOTA|guarantee[sd]?|never fails|solves? (the )?reproducibility|best.in.class|game.?chang|unprecedented|10x|breakthrough'
if CLAIMS="$(grep -rInE -i "$CLAIM_RE" "$REPO" --include='*.md' --exclude-dir=.git 2>/dev/null \
             | grep -vE '/setup/pre-publish-check\.sh')"; then
  echo "$CLAIMS" | sed 's/^/    /'
  echo "  ✗ over-claim copy found (rewrite to bounded, honest wording)"
  FAIL=1
else
  echo "  ✓ clean"
fi

echo "── 3) empty-scaffolding guard ──"
if [ -d "$REPO/examples" ] && [ -n "$(find "$REPO/examples" -type f 2>/dev/null | head -1)" ]; then
  echo "  ✓ examples/ present"
else
  echo "    examples/ is empty — add a runnable worked example so the repo isn't empty scaffolding"
  echo "  ✗ no worked example"
  FAIL=1
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "✅ pre-publish check PASSED — no leaks, no over-claims, worked example present."
else
  echo "⛔ pre-publish check FAILED — resolve the above before publishing."
fi
exit "$FAIL"
