#!/usr/bin/env python3
"""Contract test: the server announces ITS OWN version in `serverInfo`, not the SDK's.

Why this file exists
--------------------
`FastMCP.__init__` takes no `version`, so `Server.version` stays None, and the SDK fills
`serverInfo` with the version of the installed `mcp` package instead:

    server_version = self.version if self.version else pkg_version("mcp")   # mcp/server/lowlevel/server.py

Measured on this server before the fix: it announced `{"name": "yeoul", "version": "1.27.2"}`
-- the `mcp` release that happened to be installed, not yeoul-mcp's `0.1.0`. A client reading
`serverInfo` to tell yeoul builds apart was reading a number that changes with the SDK and not
with this package, so the same yeoul build reports a different version on every machine.

This is a default, not a typo, which is why a test is worth more than the one-line fix: nothing
else in CI reads `serverInfo` at all -- the `mcp` job imports the module and counts tools, which
proves the module loads, not that the handshake says anything true.

The negative control matters
----------------------------
`test_unversioned_fastmcp_is_the_broken_shape` builds a bare `FastMCP` and requires it to show
the BROKEN shape (`version is None`). Without that arm this file could pass while asserting
nothing: an assertion that only ever sees the fixed shape cannot tell a working check from a
check that stopped looking.
"""
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yeoul_mcp import __version__ as OWN_VERSION  # noqa: E402
from yeoul_mcp import server  # noqa: E402

FAIL = []
RAN = []
SKIPPED = []
REASON = []
EXPECTED_CHECKS = 8  # every check below, whether it runs or declares itself skipped


def skip(desc, why):
    """A check that deliberately did not run. Declared, never silent.

    Without this the denominator just shrinks: when the handshake died, this file printed
    "3/4 checks passed" -- two checks had vanished and the summary read almost healthy.
    """
    SKIPPED.append(desc)
    print("  skip " + desc + "  -- " + why)


def check(desc, cond, detail=""):
    RAN.append(desc)
    print(("  ok   " if cond else "  FAIL ") + desc + (("  -- " + detail) if detail and not cond else ""))
    if not cond:
        FAIL.append(desc)


def sdk_version():
    """The version the SDK would substitute if `Server.version` were left unset."""
    try:
        from importlib.metadata import version
        return version("mcp")
    except Exception:
        return None


PKG_PARENT = str(Path(__file__).resolve().parents[1])


def child_env():
    """Make the package importable in the CHILD regardless of where this file was run from.

    `sys.path.insert` above only fixes THIS process. `python -c` puts the caller's cwd on the
    child's path, so the handshake passed from `mcp/` and died from the repo root -- which is
    exactly where CI runs it. Pin PYTHONPATH instead of inheriting a working directory.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = PKG_PARENT + os.pathsep + env.get("PYTHONPATH", "")
    return env


def initialize(cmd, timeout=25.0):
    """Start the server over stdio, send one `initialize`, return its `serverInfo` (or None).

    A dead server must come back as None, not as an empty dict -- an empty dict reads as green.
    """
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                      "clientInfo": {"name": "yeoul-selftest", "version": "0"}}}
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1, env=child_env())
    box = []
    reader = threading.Thread(target=lambda: box.append(p.stdout.readline()), daemon=True)
    try:
        p.stdin.write(json.dumps(req) + "\n")
        p.stdin.flush()
        reader.start()
        reader.join(timeout)
        if not box or not box[0].strip():
            p.terminate()
            err = (p.stderr.read() or "").strip().splitlines()
            REASON.append(err[-1] if err else "no stdout and no stderr (rc=%s)" % p.poll())
            return None
        return json.loads(box[0]).get("result", {}).get("serverInfo")
    except Exception as e:
        REASON.append("%s: %s" % (type(e).__name__, e))
        return None
    finally:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            p.kill()


def test_handshake_announces_own_version():
    """The real product path: launch the server and read what it actually says on the wire."""
    info = initialize([sys.executable, "-c", "from yeoul_mcp.server import main; main()"])
    check("initialize returned a serverInfo", info is not None,
          "server did not answer -- %s" % (REASON[-1] if REASON else "no reason captured"))
    if info is None:
        skip("serverInfo carries this package's version", "no handshake to read")
        skip("serverInfo is not the mcp SDK's version", "no handshake to read")
        return
    announced = info.get("version")
    check("serverInfo carries this package's version",
          announced == OWN_VERSION, "announced %r, package is %r" % (announced, OWN_VERSION))
    sdk = sdk_version()
    if sdk is not None and sdk != OWN_VERSION:
        check("serverInfo is not the mcp SDK's version",
              announced != sdk, "announced the SDK version %r" % (sdk,))
    else:
        skip("serverInfo is not the mcp SDK's version",
             "SDK version %r is unusable as a contrast (equals ours, or unreadable)" % (sdk,))


def test_version_is_set_on_the_low_level_server():
    """The root cause in one attribute: None here is what makes the SDK substitute its own."""
    check("Server.version is set at import time",
          server.mcp._mcp_server.version is not None, "still None -- the SDK will substitute")
    check("Server.version equals the package version",
          server.mcp._mcp_server.version == OWN_VERSION,
          "%r != %r" % (server.mcp._mcp_server.version, OWN_VERSION))


def test_the_two_version_strings_agree():
    """The version is written in TWO files, and only one of them reaches `serverInfo`.

    `yeoul_mcp/__init__.py` is what the server announces; `pyproject.toml` is what the *packaging*
    records — what `pip` stores, what `importlib.metadata` returns, what a release is cut from.
    Every check above compares the server against `__init__.py`, so the two could drift and this
    file would stay green: measured 2026-08-28, setting pyproject to 9.9.9 alone kept it at 6/6.

    That drift is the same defect this module exists to prevent, arriving through the packaging
    door instead of the SDK one — the number a user sees would stop matching the number the server
    speaks. Bumping a release means bumping both, so the check belongs here rather than in a
    release checklist nobody runs.
    """
    toml = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = toml.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    check("pyproject.toml declares a version", m is not None, "no top-level version = \"...\" found")
    if m is None:
        return
    check("pyproject.toml and __init__.py carry the same version",
          m.group(1) == OWN_VERSION,
          "pyproject says %r, package says %r -- a release cut now would ship two different numbers"
          % (m.group(1), OWN_VERSION))


def test_unversioned_fastmcp_is_the_broken_shape():
    """Negative control: a FastMCP nobody patched must still show the defect.

    If this ever passes a `version is not None`, the SDK grew a default and the two checks
    above stopped discriminating -- they would go green on an unpatched server too.
    """
    from mcp.server.fastmcp import FastMCP
    bare = FastMCP("yeoul-negative-control")
    check("an unpatched FastMCP leaves Server.version unset",
          bare._mcp_server.version is None,
          "got %r -- the SDK changed; re-derive this contract" % (bare._mcp_server.version,))


def main():
    print("mcp serverInfo version contract tests")
    test_handshake_announces_own_version()
    test_version_is_set_on_the_low_level_server()
    test_the_two_version_strings_agree()
    test_unversioned_fastmcp_is_the_broken_shape()
    # Print what was counted. A run that collected zero checks also prints "0 failed".
    if not RAN:
        print("\nSERVERINFO TESTS FAILED: no checks ran at all -- an empty run is not a pass")
        return 1
    accounted = len(RAN) + len(SKIPPED)
    if accounted != EXPECTED_CHECKS:
        print("\nSERVERINFO TESTS FAILED: %d checks accounted for, %d expected -- one vanished "
              "without declaring itself" % (accounted, EXPECTED_CHECKS))
        return 1
    print("\n%s: %d/%d checks passed%s"
          % ("all serverInfo contract tests passed" if not FAIL else "SERVERINFO TESTS FAILED",
             len(RAN) - len(FAIL), len(RAN),
             (" (+%d declared skips)" % len(SKIPPED)) if SKIPPED else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
