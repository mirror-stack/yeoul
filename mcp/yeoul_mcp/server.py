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
import shlex
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DISCIPLINE = (
    "Yeoul practice layer. Gates are enforced by the underlying scripts (blank-refusal, KILL-defense "
    "5-check, verify-gate, loop-guard). Never automate pre-registration sealing, PASS/KILL judgment, "
    "graduation, or publishing. Seal kill-conditions before compute (via the mirror-stack MCP). "
    "Quote a gate refusal only when a tool actually returned one."
)

mcp = FastMCP("yeoul", instructions=DISCIPLINE)

BIN = Path(os.environ.get("YEOUL_BIN", Path(__file__).resolve().parents[2] / "bin"))


def _run(script: str, *args: str, cwd: str | None = None, stdin: str | None = None) -> dict:
    """Run a bin/ script and return {exit_code, stdout, stderr}. Never raises on non-zero exit."""
    path = BIN / script
    if not path.exists():
        return {"exit_code": 127, "stdout": "", "stderr": f"script not found: {path}"}
    cmd = ["bash", str(path), *args] if not script.endswith(".py") else ["python3", str(path), *args]
    try:
        p = subprocess.run(
            cmd, cwd=cwd or os.getcwd(), input=stdin,
            capture_output=True, text=True, timeout=120,
        )
        return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "stderr": "timeout"}


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
def loop_guard_tick(arc_dir: str, tokens: int = 0, progress: bool = True) -> dict:
    """Tick the runaway guard for a round. Returns CONTINUE or STOP:max-rounds/budget/no-progress."""
    return _run("loop-guard", arc_dir, "tick", f"--tokens={tokens}",
                f"--progress={'yes' if progress else 'no'}")


@mcp.tool()
def loop_guard_init(arc_dir: str, max_rounds: int = 3, token_budget: int = 200000) -> dict:
    """Initialize the runaway guard (max rounds / token budget) for a loop."""
    return _run("loop-guard", arc_dir, "init",
                f"--max-rounds={max_rounds}", f"--token-budget={token_budget}")


@mcp.tool()
def arc_close(arc_dir: str, verdict: str, stop: str = "converged") -> dict:
    """Close an arc (2-phase, GATE-ENFORCED). 1st call drafts _SUMMARY; fill blanks (+ KILL-defense 5-check
    if stop=falsified) then call again to seal. Returns the script's refusal (exit 4 blanks / exit 5 KILL-defense)
    if not ready — that refusal is authoritative, do not override it."""
    return _run("arc-close", arc_dir, verdict, f"--stop={stop}")


@mcp.tool()
def build_handoff(name: str, workspace: str = ".") -> dict:
    """Generate dev-plan.md + TODO.md from the spec + closed-arc verdict (GO handoff)."""
    return _run("build-handoff", name, cwd=workspace)


@mcp.tool()
def ralph_gate_check(name: str, workspace: str = ".") -> dict:
    """Dry check: does dev/TODO.md qualify for the autonomous loop? Refuses (exit 3) if any unchecked item
    lacks a `verify:` command. (Does NOT run the loop — the unattended loop must be launched from a terminal.)"""
    # loop-eligibility is the first thing ralph checks; surface it without running rounds.
    todo = Path(workspace) / "projects" / name / "dev" / "TODO.md"
    if not todo.exists():
        return {"exit_code": 1, "stdout": "", "stderr": f"no TODO: {todo}"}
    bad = [ln for ln in todo.read_text(encoding="utf-8").splitlines()
           if ln.startswith("- [ ]") and "verify:" not in ln]
    if bad:
        return {"exit_code": 3, "stdout": "", "stderr": "not loop-eligible (missing verify: commands):\n"
                + "\n".join("    " + b for b in bad)}
    return {"exit_code": 0, "stdout": "loop-eligible: all unchecked items have verify commands", "stderr": ""}


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
