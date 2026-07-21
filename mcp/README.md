# yeoul-mcp

Gate-enforcing MCP tools over the Yeoul harness. The gates live in the `bin/` scripts; this server is a thin
wrapper that shells out to them, so a gate refusal (e.g. `arc_close` returning the blank/KILL-defense refusal,
`ralph_gate_check` refusing an ungated TODO) is returned as the tool result — it cannot be talked past.

Composes with the [`mirror-stack`](https://github.com/mirror-stack/mirror-stack-mcp) MCP (pre-registration +
tamper-evident ledger). Register both together — see `../setup/mcp-servers.json`.

## Install

```bash
pip install git+https://github.com/mirror-stack/yeoul#subdirectory=mcp
```

## Run

```bash
yeoul-mcp        # stdio server
```

Set `YEOUL_BIN` if the `bin/` scripts are not adjacent to the package.

## Tools

`yeoul_new`, `arc_open`, `arc_ticket`, `loop_guard_init`, `loop_guard_tick`, `arc_close`, `build_handoff`,
`ralph_gate_check`, `status`, `arc_list`.

Each returns `{exit_code, stdout, stderr}`. A non-zero `exit_code` on `arc_close` (4 = blanks, 5 = KILL-defense)
or `ralph_gate_check` (3 = ungated item) is an enforced gate, not an error to route around.

## Language rule

A tool result is what the *script* reported. Do not present your own judgment as a tool verdict — say "a gate
refused X" only when a tool returned it.
