"""Yeoul MCP — gate-enforcing tools over the Yeoul harness.

The gates live in the bin/ scripts (arc-close blank/KILL-defense refusal, ralph verify-gate, loop-guard
bounds). This server is a thin, faithful wrapper: each tool shells out to a script and returns its output
and exit code, so an agent under pressure cannot talk past a gate — the tool returns the refusal.

Composes with the `mirror-stack` MCP (pre-registration + tamper-evident ledger). Run: `yeoul-mcp` (stdio).

Language rule (from the mirror discipline): a tool result is what the *script* reported. Do not present
your own judgment as a tool verdict.
"""
from __future__ import annotations
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DISCIPLINE = (
    "Yeoul practice layer. Gates are enforced by the underlying scripts (blank-refusal, KILL-defense "
    "5-check, verify-gate, loop-guard). Never automate pre-registration sealing, PASS/KILL judgment, "
    "graduation, or publishing. Seal kill-conditions before compute (via the mirror-stack MCP). "
    "Quote a gate refusal only when a tool actually returned one."
)

mcp = FastMCP("yeoul", instructions=DISCIPLINE)

# `FastMCP.__init__` takes no `version`, so `Server.version` stays None and the SDK substitutes its
# OWN version into `serverInfo`. Measured on this server before this line existed: it announced
# `{"name": "yeoul", "version": "1.27.2"}` — the installed `mcp` release, not `0.1.0`. A client
# reading serverInfo to tell yeoul builds apart was reading the SDK's number instead.
#   Source `__version__`, NOT `importlib.metadata.version("yeoul-mcp")`: under an editable install
#   the dist-info can carry a stale number, which would swap one wrong value for another.
try:  # installed, or imported as a package (console script, CI, tests)
    from yeoul_mcp import __version__
except ImportError:  # executed as a bare file: the package's parent isn't on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from yeoul_mcp import __version__
mcp._mcp_server.version = __version__

_BUNDLED = Path(__file__).resolve().parent / "_harness" / "bin"
BIN = Path(os.environ.get("YEOUL_BIN", _BUNDLED if _BUNDLED.is_dir()
                          else Path(__file__).resolve().parents[2] / "bin"))


def bash_command(platform: str | None = None) -> str:
    """Prefer Git Bash on Windows; System32/bash.exe is a WSL launcher, not this runtime."""
    if os.environ.get('YEOUL_BASH'):
        return os.environ['YEOUL_BASH']
    if (platform or sys.platform) != 'win32':
        return 'bash'
    candidates = []
    git = shutil.which('git')
    if git:
        candidates += [Path(git).parent.parent/'bin'/'bash.exe',
                       Path(git).parent.parent/'usr'/'bin'/'bash.exe']
    for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(key):
            base = Path(os.environ[key])
            candidates += [base/'Git'/'bin'/'bash.exe', base/'Programs'/'Git'/'bin'/'bash.exe']
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which('bash')
    if found and 'system32' not in found.lower() and 'windowsapps' not in found.lower():
        return found
    raise FileNotFoundError('Git Bash not found; install Git for Windows or set YEOUL_BASH to its bash.exe')


def _run(script: str, *args: str, cwd: str | None = None, stdin: str | None = None) -> dict:
    """Run a bin/ script and return {exit_code, stdout, stderr}. Never raises on non-zero exit."""
    path = BIN / script
    if not path.exists():
        return {"exit_code": 127, "stdout": "", "stderr": f"script not found: {path}"}
    try:
        interp = [bash_command()] if not script.endswith(".py") else [sys.executable]
    except OSError as exc:
        return {"exit_code": 127, "stdout": "", "stderr": str(exc)}
    cmd = [*interp, path.as_posix(), *args]
    # 🔴 stdin: never inherit the parent's. On an MCP STDIO server the parent's stdin IS the
    #    protocol pipe, and a child that inherits it steals protocol bytes — the tool then
    #    hangs until timeout (field report, Windows/Codex, 2026-08-24).
    # 🔴 encoding: pin UTF-8. The gate strips a `←` hint before judging an answer; under a
    #    non-UTF-8 default (CP949) the strip fails and a trivial "yes" arrives long enough to
    #    clear the substance checks. That is a gate-integrity bug, not a display bug.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if not script.endswith('.py'):
        env['YEOUL_BASH'] = interp[0]
    try:
        with subprocess.Popen(
            cmd, cwd=cwd or os.getcwd(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=env, start_new_session=os.name == "posix",
        ) as child:
            try:
                stdout, stderr = child.communicate(input=stdin if stdin is not None else "", timeout=120)
                return {"exit_code": child.returncode, "stdout": stdout, "stderr": stderr}
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    child.kill()
                child.communicate()
                return {"exit_code": 124, "stdout": "", "stderr": "timeout"}
    except (OSError, UnicodeError) as exc:
        return {"exit_code": 127, "stdout": "", "stderr": str(exc)}


@mcp.tool()
def yeoul_new(name: str, topic: str = "", roles: str = "analysis impl repro",
              backend: str = "both", no_arc: bool = False, workspace: str = ".") -> dict:
    """Scaffold a project (design/ + dev/ + spec) and open a deliberation arc. Set no_arc to scaffold only."""
    args = [name]
    if topic:
        args.append(f"--topic={topic}")
    args += [f"--roles={roles}", f"--backend={backend}"]
    if no_arc:
        args.append("--no-arc")
    return _run("yeoul-new", *args, cwd=workspace)


@mcp.tool()
def arc_open(slug: str, arcs_dir: str, topic: str = "", roles: str = "analysis impl repro",
             backend: str = "both", relay: str = "orchestrator", workspace: str = ".") -> dict:
    """Open a deliberation arc directly under arcs_dir (thread + ticket inboxes + roster + join prompts)."""
    args = [slug, f"--arcs-dir={arcs_dir}", f"--roles={roles}", f"--backend={backend}", f"--relay={relay}"]
    if topic:
        args.append(f"--topic={topic}")
    return _run("arc-open", *args, cwd=workspace)


@mcp.tool()
def arc_ticket(arc_dir: str, role: str, slug: str, body: str, ref: str = "") -> dict:
    """Issue a relay ticket to a role's inbox (deliberation rules baked in). Relay-only."""
    return _run("arc-ticket", arc_dir, role, slug, ref, stdin=body)


@mcp.tool()
def loop_guard_tick(arc_dir: str, tokens: int | None = None, progress: bool = True) -> dict:
    """Tick the runaway guard for a round. Returns CONTINUE or STOP:max-rounds/budget/no-progress."""
    args = [arc_dir, "tick", f"--progress={'yes' if progress else 'no'}"]
    if tokens is not None:
        args.append(f"--tokens={tokens}")
    return _run("loop-guard", *args)


@mcp.tool()
def loop_guard_init(arc_dir: str, max_rounds: int = 3, token_budget: int = 200000) -> dict:
    """Initialize the runaway guard (max rounds / token budget) for a loop."""
    return _run("loop-guard", arc_dir, "init",
                f"--max-rounds={max_rounds}", f"--token-budget={token_budget}")


@mcp.tool()
def arc_close(arc_dir: str, verdict: str, stop: str = "converged") -> dict:
    """Close an arc (2-phase, GATE-ENFORCED). 1st call drafts _SUMMARY; fill the blanks, then call again to seal.
    Extra sections are required depending on the close: a KILL close (stop=falsified, or KILL in the verdict) gets
    the 🛡️ 5-check; ANY close on an arc with a linked prereg seal gets the 🔒 sealed-condition cross-check —
    that one fires regardless of the label, so closing as `converged` does not switch the anchor off.
    Returns the script's refusal (exit 4 blanks / exit 5 gate) if not ready — that refusal is authoritative,
    do not override it."""
    return _run("arc-close", arc_dir, verdict, f"--stop={stop}")


@mcp.tool()
def build_handoff(name: str, workspace: str = ".") -> dict:
    """Generate a dev skeleton, NOT authorization to build. Missing/negative verdicts remain manual gates."""
    return _run("build-handoff", name, cwd=workspace)


@mcp.tool()
def ralph_gate_check(name: str, workspace: str = ".") -> dict:
    """Read-only eligibility check of ALL items, using the real CLI parser. No loop or verification runs."""
    return _run("ralph", name, "--check", cwd=workspace)


@mcp.tool()
def arc_prereg(arc_dir: str, claim_id: str, ledger: str = "", workspace: str = ".") -> dict:
    """Link a sealed pre-registration to an arc so arc_close injects its kill-condition VERBATIM instead of
    trusting an agent-typed field. Seal the claim first (mirror-stack). Without this, closes are UNSEALED."""
    args = [arc_dir, claim_id] + ([ledger] if ledger else [])
    return _run("arc-prereg", *args, cwd=workspace)


@mcp.tool()
def verify_gate(todo_path: str, revert: bool = True, require_verify: bool = True,
                workspace: str = ".", baseline_path: str = "") -> dict:
    """Re-run the `verify:` command of every checked TODO item and revert the boxes that do not pass. This is
    the harness half of the dev loop — backend A (in-session) MUST call it each round, or nothing has been
    verified but the agent's word. Requires a supervisor-created baseline (default TODO.verify-baseline.json).
    Changed criteria are refused BEFORE executing commands. Protect baseline and tests from worker writes."""
    args = [todo_path] + (["--revert"] if revert else []) + (["--require-verify"] if require_verify else [])
    if baseline_path:
        args.append(f"--baseline={baseline_path}")
    return _run("verify-gate", *args, cwd=workspace)


@mcp.tool()
def status(workspace: str = ".", md: bool = False) -> dict:
    """One line per active project: name · latest arc verdict · dev TODO progress."""
    return _run("status", *(["--md"] if md else []), cwd=workspace)


@mcp.tool()
def arc_list(workspace: str = ".", show_all: bool = False) -> dict:
    """List deliberation arcs (default: open/In-Progress only)."""
    return _run("arc-list", *(["--all"] if show_all else []), cwd=workspace)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
