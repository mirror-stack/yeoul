#!/usr/bin/env python3
"""Contract tests for `server._run` — the two field-report P0s, pinned.

Why this file exists
--------------------
Both defects fixed for the 2026-08-24 Windows/Codex field report live in `_run`, and NOTHING
exercised them: the `mcp` CI job installed the package and imported it, which proves the module
loads, not that the subprocess contract holds. A documented fix with no test is a promise.

The two contracts:

  1. **stdin is never inherited.** On an MCP STDIO server the parent's stdin IS the protocol
     pipe. A child that inherits it steals protocol bytes and the tool hangs until timeout.
  2. **UTF-8 is pinned regardless of the ambient locale.** Under a non-UTF-8 default (CP949 on
     the reporter's machine) the gate's `←` hint strip failed, so a trivial "yes" arrived long
     enough to clear the substance checks. That is gate integrity, not display.

Contract 2 is the *mechanism* that was reported on Windows, reproduced portably: we run the
child under a deliberately non-UTF-8 ambient locale and require the round-trip to survive.
Run this on Windows too — the origin environment is the one the rest of CI does not cover.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp import server  # noqa: E402

FAIL = []


def check(desc, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + desc + (("  -- " + detail) if detail and not cond else ""))
    if not cond:
        FAIL.append(desc)


def _install(tmp, name, body):
    """Put a throwaway script where _run looks for it (server.BIN), and return its name."""
    p = Path(server.BIN) / name
    p.write_text(body, encoding="utf-8")
    return name, p


def test_stdin_not_inherited(tmp):
    """The child must see EOF on stdin, not the parent's protocol bytes."""
    # A .py helper, not .sh: _run dispatches .py through sys.executable, so this test runs
    # identically on Windows — the very platform the field report came from. A bash helper
    # would quietly skip there, and a skip that reads as a pass is how this hole got in.
    name, p = _install(tmp, "_t_stdin.py",
                       'import sys\nsys.stdout.write(sys.stdin.read())\nprint("CHILD_DONE")\n')
    try:
        # Drive it through a parent whose OWN stdin carries sentinel bytes. If _run leaks the
        # parent's stdin to the child, `cat` echoes the sentinel — that is the protocol theft.
        driver = (
            "import sys, os; sys.path.insert(0, %r);\n"
            "from yeoul_mcp import server\n"
            "r = server._run(%r)\n"
            "sys.stdout.write('RC=%%s|OUT=%%s' %% (r['exit_code'], r['stdout'].replace(chr(10), ' ')))\n"
            % (str(Path(server.__file__).resolve().parents[1]), name)
        )
        d = subprocess.run(
            [sys.executable, "-c", driver],
            input="SENTINEL_PROTOCOL_BYTES\n", capture_output=True, text=True, timeout=60,
        )
        out = d.stdout
        check("child does not inherit the parent's stdin", "SENTINEL_PROTOCOL_BYTES" not in out, out[:200])
        check("child still ran to completion", "CHILD_DONE" in out, out[:200])
        check("no hang / timeout", "RC=0" in out, out[:200])
    finally:
        p.unlink(missing_ok=True)


def test_utf8_pinned_under_hostile_locale(tmp):
    """Non-ASCII must survive even when the ambient locale is not UTF-8 (the CP949 mechanism)."""
    # The gate strips everything after `←`; if the decode is wrong that marker survives and the
    # answer arrives wearing the hint as its body.
    name, p = _install(tmp, "_t_enc.py",
                       'import sys\nsys.stdout.buffer.write(b"ANSWER \\xe2\\x86\\x90 HINT\\n")\n')
    try:
            # 🔴 `LC_ALL=C` ALONE IS NOT HOSTILE on modern Linux — PEP 538/540 coerce the C
        #    locale back to UTF-8, so the default encoding stays UTF-8 and this test would
        #    pass with the fix REMOVED. Verified: it did. PYTHONCOERCECLOCALE=0 plus
        #    PYTHONUTF8=0 is what actually yields an ASCII default, which is the portable
        #    stand-in for the reporter's CP949 machine.
        hostile = {k: v for k, v in os.environ.items()
                   if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        hostile.update({"LC_ALL": "C", "LANG": "C",
                        "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})
        d = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from yeoul_mcp import server\n"
             "r = server._run(%r)\n"
             "sys.stdout.buffer.write(r['stdout'].encode('utf-8'))\n"
             % (str(Path(server.__file__).resolve().parents[1]), name)],
            capture_output=True, env=hostile, timeout=60,
        )
        got = d.stdout.decode("utf-8", "replace")
        check("hostile-locale run succeeded", d.returncode == 0, d.stderr.decode("utf-8", "replace")[:200])
        check("the arrow round-trips under a non-UTF-8 ambient locale", "←" in got, repr(got)[:200])
        # 🔴 Guard this one against passing on EMPTY output: if the run died, "" contains no
        #    replacement chars and this check would go green for the wrong reason (observed).
        check("no replacement characters (nothing was mis-decoded)",
              bool(got.strip()) and "�" not in got, repr(got)[:200])
    finally:
        p.unlink(missing_ok=True)


def test_missing_script_is_not_a_pass(tmp):
    """A script that isn't there must report 127, not a silent success."""
    r = server._run("_t_does_not_exist.py")
    check("missing script reports 127", r["exit_code"] == 127, str(r)[:200])
    check("missing script is not reported as OK", r["exit_code"] != 0)


def main():
    print("mcp _run contract tests")
    with tempfile.TemporaryDirectory() as tmp:
        test_stdin_not_inherited(tmp)
        test_utf8_pinned_under_hostile_locale(tmp)
        test_missing_script_is_not_a_pass(tmp)
    print("\n%s (%d failed)" % ("all _run contract tests passed" if not FAIL else "CONTRACT TESTS FAILED", len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
