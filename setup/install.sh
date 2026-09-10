#!/usr/bin/env bash
set -euo pipefail
# Install independent Yeoul. Mirror is opt-in; requested failures are fatal.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WITH_MIRROR=0; PRINT_ONLY=0
for a in "$@"; do case "$a" in
  --no-mirror-stack) WITH_MIRROR=0 ;;
  --with-mirror-stack) WITH_MIRROR=1 ;;
  --print-config) PRINT_ONLY=1 ;;
  *) echo "unknown option: $a" >&2; exit 2 ;;
esac; done
if [ "$PRINT_ONLY" -eq 1 ]; then
  cat "$SCRIPT_DIR/mcp-servers.json"
  exit 0
fi
. "$REPO/bin/_pybin.sh"
PY="$(yeoul_pybin)" || yeoul_pybin_die
"$PY" -m pip --version >/dev/null
if [ "$WITH_MIRROR" -eq 1 ]; then
  "$PY" -m pip install "git+https://github.com/mirror-stack/mirror-stack-mcp@v0.3.0"
else
  echo "Mirror installation skipped: discussion closes remain explicitly file-only without a recorder."
fi
"$PY" -m pip install "$REPO/mcp"
echo "Installed yeoul-mcp (bundled harness). Bash must be available on PATH."
echo "Start with: yeoul setup"
echo "Then: yeoul doctor --workspace FOLDER"
echo "Generate your managed client configuration: yeoul connect --workspace FOLDER"
echo "No existing client configuration or business data was changed."
