#!/usr/bin/env bash
# Resolve a Python interpreter by RUNNING one — not by finding a name.
#
# 🔴 `command -v python3` is satisfied by the Microsoft Store stub that ships on Windows: the name
#    resolves, and the "interpreter" then exits 49 without running anything. Existence is not
#    execution. Measured on two Windows machines (2026-08-25): the gate suite scored 34/48 on both,
#    and on the second one a perfectly good `python` 3.11.15 was on PATH the whole time — the only
#    blocking name was `python3`. The failures printed as `✗ expected 0, got 49`, which reads like a
#    verdict but is the absence of a measurement.
#
# Usage — source it, then use $PY unquoted (the value may carry an argument, e.g. `py -3`):
#     . "$(dirname "${BASH_SOURCE[0]}")/_pybin.sh"
#     PY="$(yeoul_pybin)" || yeoul_pybin_die
#     $PY script.py
#
# Override with YEOUL_PYTHON if you need a specific interpreter.

yeoul_pybin() {
  local c
  for c in ${YEOUL_PYTHON:+"$YEOUL_PYTHON"} python3 python "py -3"; do
    # word-splitting on $c is intentional: "py -3" is a command plus an argument.
    # shellcheck disable=SC2086
    if $c -c 'import sys; raise SystemExit(0)' >/dev/null 2>&1; then
      printf '%s' "$c"
      return 0
    fi
  done
  return 1
}

# Fail loudly. A missing interpreter must stop the run, not quietly skip the step it powers —
# a skipped check that reads as a pass is how this stayed invisible on Windows.
yeoul_pybin_die() {
  echo "no working Python interpreter found." >&2
  echo "  tried: ${YEOUL_PYTHON:+$YEOUL_PYTHON, }python3, python, py -3 — each by running \`-c 'import sys'\`," >&2
  echo "  not by looking it up. On Windows the Microsoft Store stub answers to \`python3\` and exits 49." >&2
  echo "  Install Python, or point YEOUL_PYTHON at a real interpreter." >&2
  exit 127
}
