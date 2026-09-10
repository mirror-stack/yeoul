# yeoul-mcp

Gate-enforcing MCP tools over the Yeoul harness. The gates live in the `bin/` scripts; this server is a thin
wrapper that shells out to them, so a gate refusal (e.g. `arc_close` returning the blank/KILL-defense refusal,
`ralph_gate_check` refusing an ungated TODO) is returned as the tool result — it cannot be talked past.

Composes with the [`mirror-stack`](https://github.com/mirror-stack/mirror-stack-mcp) MCP (pre-registration +
tamper-evident ledger) optionally. Neither Mirror nor LaneStack is required.
See the [standalone workspace guide](../docs/WORKSPACE_GUIDE.ko.md).

## Install

```bash
pip install 'git+https://github.com/mirror-stack/yeoul@v0.4.0#subdirectory=mcp'
```

## Run

```bash
yeoul setup ./my-discussions --mode discuss
yeoul doctor --workspace ./my-discussions
yeoul connect --workspace ./my-discussions  # prints managed client config
yeoul serve --workspace ./my-discussions   # stdio server
```

For opt-in managed permissions, operation IDs, durable receipts and workspace
locking, read the [runtime contract](../docs/RUNTIME_CONTRACT.md). An existing
absolute `YEOUL_MCP_ROOT` enables managed mode; writes require
`YEOUL_MCP_ALLOW_WRITE=1` and an `operation_id`. Optional
`YEOUL_MCP_WRITE_TOOLS` restricts mutations by name. Arbitrary verification also
requires `YEOUL_MCP_ALLOW_EXEC=1` and a supervisor-configured
`YEOUL_MCP_VERIFY_BASELINE` under `ROOT/.yeoul-approved/`, protected from worker
writes. Without a root, this is trusted local mode without managed concurrency
controls. The new `yeoul` product CLI shares the MCP lock; raw checkout scripts
and older servers do not. Bare `yeoul-mcp` remains the advanced compatibility entrypoint.

v0.3.0 wheels and sdists bundle the harness and templates. Python >=3.10 and Bash
(Git Bash on Windows) are required. `YEOUL_BIN` overrides the bundled scripts only
when explicitly pointing to a custom checkout. No checkout is needed for the default MCP setup.

## Tools

`yeoul_new`, `arc_open`, `arc_ticket`, `loop_guard_init`, `loop_guard_tick`, `arc_close`, `arc_prereg`,
`build_handoff`, `ralph_gate_check`, `verify_gate`, `status`, `arc_list`.

Three additional workspace tools bring the total to 15: `workspace_prepare`,
`workspace_execute`, `workspace_tasks`. Prepare persists a task without running
it; execute uses its stable ID; tasks inspects receipts. No setup, command approval,
or recovery mutation is exposed as a worker MCP tool.

`arc_prereg` and `verify_gate` are the two enforcement halves that used to be reachable only from the shell:
linking a seal (so `arc_close` injects the kill-condition verbatim) and re-running a round's verify commands.
An agent driving Yeoul purely through MCP could not run either — so neither gate held on that path.

Each business tool returns `{exit_code, stdout, stderr}`. Always inspect `exit_code`; a delivered MCP response is not a passing gate.
A non-zero `exit_code` on `arc_close` (4 = blanks, 5 = defense/binding, 8 = record mismatch, 9 = close/archive conflict)
or `ralph_gate_check` (3 = ungated item) is an enforced gate, not an error to route around.

`ralph_gate_check` is read-only and calls the same CLI eligibility path. `verify_gate`
requires a supervisor-created baseline (in trusted mode, optional `baseline_path`; default
`TODO.md.verify-baseline.json`). Create it with the CLI `verify-baseline` before work.
It is deliberately not a worker-facing MCP approval tool. Missing token counts in
`loop_guard_tick` stay unmeasured rather than becoming zero.

See [integrity and migration](../docs/INTEGRITY.md) for the complete contract and
the explicit `arc-result` CLI bridge to Mirror. Closing an arc never publishes a result.

## Language rule

A tool result is what the *script* reported. Do not present your own judgment as a tool verdict — say "a gate
refused X" only when a tool returned it.
