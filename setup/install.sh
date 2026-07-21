#!/usr/bin/env bash
set -euo pipefail
# install.sh — set up Yeoul together with its discipline primitive (mirror-stack).
#   Yeoul is the practice layer; mirror-stack is the pre-registration + tamper-evident ledger it seals into.
#   Installing both is recommended so sealing is real, not a no-op fallback.
#
# usage: setup/install.sh [--no-mirror-stack] [--print-config]
#   --no-mirror-stack : skip installing mirror-stack (Yeoul runs; sealing degrades to no-op)
#   --print-config    : just print the mcpServers block to merge into your MCP client config

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WITH_MIRROR=1; PRINT_ONLY=0
for a in "$@"; do case "$a" in
  --no-mirror-stack) WITH_MIRROR=0 ;;
  --print-config)    PRINT_ONLY=1 ;;
esac; done

if [ "$PRINT_ONLY" -eq 1 ]; then
  cat "$SCRIPT_DIR/mcp-servers.json"
  exit 0
fi

echo "── Yeoul setup ──"
echo "1) Yeoul CLI scripts: $REPO/bin  (add to PATH, or call by path)"
echo "   e.g.  export PATH=\"$REPO/bin:\$PATH\""

if [ "$WITH_MIRROR" -eq 1 ]; then
  echo "2) mirror-stack (discipline primitive: pre-registration + ledger)"
  if command -v pip >/dev/null 2>&1; then
    echo "   installing mirror-stack-mcp ..."
    pip install "git+https://github.com/mirror-stack/mirror-stack-mcp" || {
      echo "   ⚠️ pip install failed — install manually: pip install git+https://github.com/mirror-stack/mirror-stack-mcp"
    }
  else
    echo "   ⚠️ pip not found. Install manually: pip install git+https://github.com/mirror-stack/mirror-stack-mcp"
  fi
else
  echo "2) mirror-stack: SKIPPED (--no-mirror-stack). Sealing will be a no-op fallback."
fi

echo "3) MCP client config — merge this into your mcpServers (Claude Desktop/Code):"
echo
sed 's/^/     /' "$SCRIPT_DIR/mcp-servers.json"
echo
echo "   (If you skipped mirror-stack, remove its entry — Yeoul still runs without it.)"
echo "── done ──"
