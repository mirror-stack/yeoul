# Independent local host composition (unreleased, Linux)

`yeoul_mcp.local_host.LocalHost` connects current files, read-only shadow review,
prepared operations and fresh host approval. It requires neither Mother nor
LaneStack nor Mirror. It is an opt-in Python host API, not a new MCP tool, daemon,
model client, production loader or end-user setup wizard.

## Explicit host inputs

The host must supply an existing managed workspace, its protected
[source manifest](FILE_SOURCES.md), a worker callback, required provider callbacks,
and an explicit tool allowlist. No defaults choose a provider or approve work.
The caller must already have activated the managed workspace at host startup.
LocalHost does not change environment variables, install services or activate
permissions. Existing startup activation uses process-global environment; do not
switch multiple workspaces concurrently in one process.

```python
from yeoul_mcp.local_host import LocalHost

# Run inside the caller's already configured, managed host process.
host = LocalHost(project_root, worker=worker,
    providers={"required-check": ("selected-provider", shadow_check, prepared_check)},
    allowed_tools={"yeoul_new"})
prepared = host.prepare("host-task-label", "yeoul_new",
                        {"name": "synthetic", "no_arc": True})
# Only on an explicit later host action, never automatically after shadow success:
if prepared["state"] == "prepared":
    result = host.commit(prepared["task_id"], approve=ask_host_approval)
```

Callbacks above are supplied by the embedding host, not implemented by this example.
The worker and shadow-check signatures follow [shadow workflow](SHADOW_WORKFLOW.md).
`prepared_check(request_bytes, snapshot_bytes)` must evaluate the exact current job
and returns `{status, evidence_ref}`. `request_bytes` contains `{job, binding}`;
the job includes actual tool, arguments and the persisted candidate/source digest.
The host supplies the normalized check/provider IDs and binding, but this does not
make an old or unrelated verdict valid. Provider implementations must actually
assess that operation and current evidence. `ask_host_approval(request_bytes)` must
return a literal boolean after an authorized decision, not a truthy string.

## Two distinct stages

Preparation passes only model-safe context to the worker. Its reply cannot select
the tool, arguments, provider identities or required checks. A failed shadow check
creates no prepared job. A successful preparation stores the candidate together
with the full host-only source digest, including nonpublic source changes.
Preparation writes task metadata, not business files, and returns no authority.

Commit uses the existing [reviewed execution](REVIEWED_EXECUTION.md) write lock.
It checks the current host contract and sources, obtains new prepared-operation
reports, checks sources again, asks for separate approval only after passing review,
and checks sources once more. Errors, changed sources, changed provider IDs,
retractions and nonboolean approvals do not authorize business writes. Existing
audit and receipt handling persists approval/denial and ambiguous execution states.
A newly constructed host can load an existing prepared task. A completed task
replays its receipt without rerunning providers, approval or the business command.

## Evidence and limits

Twelve synthetic local tests cover actual project creation, denial then approval,
completed replay, a new host instance loading a task, private-source changes,
retraction, source changes during verification/approval, changed provider identity,
tool allowlisting, failed shadow, and refusal in an unconfigured host context.
These fixtures authenticate no remote service and call no model. Reconstructing a
host object is not a full process-crash or operating-system restart test.
The [command verifier adapter](COMMAND_PROVIDER.md) adds per-process time/output
bounds; its synthetic LocalHost test covers timeout and retraction before a fresh
passing check. It does not supply remote provider authentication.

Trusted Python callbacks are not sandboxed or time-bounded by LocalHost. Use
separately authenticated and bounded adapters; provider names are not identities.
Source rereads do not form a transaction with remote withdrawal or hostile writers.
Approval presentation, user identity, policy completeness, retention, actual model
transport, source provisioning and production activation remain integration work.
Never send prepared host requests or full snapshots back to the proposing worker.
