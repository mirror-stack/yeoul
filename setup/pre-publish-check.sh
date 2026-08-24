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

# 🔴 Scope the scans to what would actually ship. These used to walk/grep the whole working tree,
#    so a gitignored runtime artifact (KNOWLEDGE_INDEX.md, written by every arc close) made the guard
#    report "personalization leaks found" about a file git will never publish. A red that does not
#    mean what it says gets ignored, which is worse than no guard.
publishable_files() { # publishable_files [-z]
  if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$REPO" ls-files ${1:+-z}
  else
    if [ "${1:-}" = "-z" ]; then (cd "$REPO" && find . -type f -not -path './.git/*' -print0)
    else (cd "$REPO" && find . -type f -not -path './.git/*'); fi
  fi
}

echo "── 1) personalization leak scan ──"
# Generic de-personalization checks (no internal codenames are enumerated here, so this file ships clean):
#   (a) any Hangul — this repo is English-only, so any Korean text is a leak;
#   (b) private absolute paths (/home/... or /data/...) that must not ship.
# Intentional localizations are allowed (README_KO.md, *.ko.md, docs/ko/); Hangul anywhere else is a leak.
# Hangul detection via python (portable — GNU grep's -P is unavailable on macOS/BSD).
# NB: the file list goes through a temp file, not a pipe. `python3 - <<PY` makes the heredoc
#     itself stdin, so a piped list never arrives and the scan silently reads nothing —
#     a guard that inspected zero files and still reported "clean" (caught by its positive control).
FILELIST="$(mktemp)"; publishable_files > "$FILELIST"
# 🔴 the denominator, enforced in the shell. A scan over zero files reports "clean" for every
#    section, so an empty list has to fail the run outright — not merely print a note that the
#    surrounding `if [ -n "$LEAKS" ]` then treats as clean.
SCANNED="$(grep -c . "$FILELIST" || true)"
if [ "${SCANNED:-0}" -eq 0 ]; then
  echo "  ✗ scanned 0 files — an empty scan is a failure, not a pass"
  FAIL=1
fi
HANGUL="$(python3 - "$REPO" "$FILELIST" <<'PY'
import os, re, sys
root = sys.argv[1]; h = re.compile('[\uac00-\ud7a3]')  # Hangul syllables (escaped → this file stays Hangul-free)
rels = [x.rstrip('\n') for x in open(sys.argv[2], encoding='utf-8') if x.strip()]
if not rels: sys.exit('pre-publish: file list is empty - refusing to report clean')
for rel in rels:
    if rel.endswith(('_KO.md', '.ko.md')) or rel.startswith('ko/') or '/ko/' in rel: continue
    p = os.path.join(root, rel)
    try:
        if h.search(open(p, encoding='utf-8', errors='ignore').read()): print(p)
    except Exception: pass
PY
)"
PATHS="$( (cd "$REPO" && tr '\n' '\0' < "$FILELIST" | xargs -0 -r grep -lE '(/home|/data)/[A-Za-z]' --include='*.sh' --include='*.py' --include='*.md' --include='*.json' -- ) 2>/dev/null || true)"
LEAKS="$(printf '%s\n%s\n' "$HANGUL" "$PATHS" | grep -v '^$' | sort -u)"
if [ -n "$LEAKS" ]; then
  echo "$LEAKS" | sed 's/^/    /'
  echo "  ✗ personalization leaks found (Hangul or private absolute path)"
  FAIL=1
else
  echo "  ✓ clean ($SCANNED files scanned)"
fi

echo "── 2) over-claim copy scan ──"
# Superlatives / unfalsifiable marketing the discipline forbids in our own docs.
CLAIM_RE='revolutionary|world.?first|state.of.the.art|SOTA|guarantee[sd]?|never fails|solves? (the )?reproducibility|best.in.class|game.?chang|unprecedented|10x|breakthrough'
if CLAIMS="$( (cd "$REPO" && tr '\n' '\0' < "$FILELIST" | xargs -0 -r grep -InE -i "$CLAIM_RE" --include='*.md' -- ) 2>/dev/null \
             | grep -vE '(^|/)setup/pre-publish-check\.sh')"; then
  echo "$CLAIMS" | sed 's/^/    /'
  echo "  ✗ over-claim copy found (rewrite to bounded, honest wording)"
  FAIL=1
else
  echo "  ✓ clean"
fi

rm -f "$FILELIST"

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
