"""Independent product entrypoint; no consumer application dependency."""
import os
from .workspace import Workspace

workspace = Workspace(
    product="yeoul", prefix="YEOUL",
    control=".yeoul-mcp", package="yeoul_mcp",
    modes={"observe":[],"discuss":["yeoul_new","arc_open","arc_ticket","loop_guard_tick","loop_guard_init","arc_close","build_handoff","arc_prereg"],"develop":["yeoul_new","arc_open","arc_ticket","loop_guard_tick","loop_guard_init","arc_close","build_handoff","arc_prereg","verify_gate"]}, defaults={"new":["yeoul_new","name","example"],"status":["status","workspace","."],"verify":["verify_gate","todo_path","TODO.md"]},
)

def root():
    value = os.environ.get("YEOUL_MCP_ROOT")
    if not value:
        raise ValueError("Use yeoul setup, then yeoul serve --workspace FOLDER.")
    return workspace.root(value)

def main():
    raise SystemExit(workspace.cli())

if __name__ == "__main__":
    main()
