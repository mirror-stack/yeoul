# Read-only test-workspace workflow

Status: unreleased opt-in host integration. Implemented and tested with synthetic
file-backed sources and worker/provider adapters, including a real child-process
worker. Not an operational loader, live-model benchmark or installed service.

The optional [Linux isolation integration](WORKER_ISOLATION.md) additionally runs
the synthetic worker in namespaces with read-only input and private output, then
routes both correct and incorrect proposals through this workflow. It does not
activate a product launcher or commit any proposal.

`yeoul_mcp.shadow_workflow.run_shadow(task_id, load_snapshot, worker, providers)`
connects the existing Active Context extractor to provider-neutral review routing.
Yeoul orchestrates the task; an independently selected adapter performs checks.
Mirror, Mother and LaneStack are not dependencies. No Mirror API is assumed.

## Host contract

1. The host selects a complete authoritative snapshot loader, one worker and all
   required checks before the worker runs. Source text cannot select callbacks,
   providers or requirements. The initial snapshot/schema/policy is validated.
2. Only frozen model-facing bytes go to `worker(payload)`: required source bodies
   are included; noncontrolling history and validator-only bodies are excluded.
   Sources are reloaded and compared immediately before dispatch.
3. The worker returns at most 64 KiB of JSON bytes with exactly `input_sha256`
   and `proposal` (an object). Duplicate fields, nonfinite numbers and mismatched
   input hashes are refused. This echo binds a response to input, but is not proof
   of model consumption or truth. Sources are reloaded after the worker returns.
4. `providers` maps a required check ID to `(provider_id, callback)`. A trusted
   callback receives immutable full-snapshot, proposal and binding bytes. It
   returns exactly `status` and `evidence_ref`; it cannot replace the check ID,
   provider ID, task ID, target, revision or proposal hash. The host must authenticate
   any actual provider connection. A provider name alone proves no identity.
   Binding revision is the complete snapshot digest, not its public model-facing
   revision. Keep returned bindings/reports on the host side; do not feed private
   source fingerprints back to the proposing worker.
5. After all providers return, the source is reloaded again. Changed or unavailable
   sources hold the task. Matching sources and all passing required checks yield
   `ready_for_review`, never execution authority or business completion.

The return includes diagnostic stage events, exact submitted input byte count,
input hash and, after successful collection, bound proposal/reports and routing
reasons. These in-memory events are not an append-only audit log or execution
receipt. The application must persist them separately if required; the workflow
itself performs no state writes. Tokens, subscription debit and savings are not
inferred from the byte count.

## Failure and trust boundaries

- Invalid initial host input raises an exception before dispatch. The host must
  hold on exceptions. Invalid worker output, worker/provider exceptions and later
  snapshot failures produce `needs_review`; no automatic retry is performed.
- Worker timeout, provider timeout, output buffering and cancellation must be
  bounded by the host's transport adapter. A reply-size check after a callback
  returns does not prevent that callback from buffering excessive output first.
  The optional [bounded Linux command adapter](WORKER_TRANSPORT.md) now supplies
  streaming input/output and deadline checks for command workers. It does not
  impose those limits on arbitrary Python providers or activate a model connection.
- Callbacks are trusted code running with host permissions, not a sandbox. They
  can perform side effects if the host selects such implementations. The test
  adapters only read synthetic data and execute isolated synthetic calculations.
- The full snapshot is private to the host/provider side and may include excluded
  sources. Do not transmit it to a remote verifier without explicit data approval.
- A final check cannot prevent changes immediately after return. The result is
  point-in-time and must not be used as a reusable commit capability. Any future
  write integration must atomically enforce freshness and current permissions at
  the existing execution boundary; this module does not invoke workspace_execute.
- Provider retraction while a source stays unchanged is not discovered by source
  hashing. A real host must obtain current provider status for the review and
  invalidate it before any later commit when evidence is retracted.

The opt-in [prepared execution bridge](REVIEWED_EXECUTION.md#shadow-to-write-boundary)
requires fresh reports for the actual prepared operation. Connected synthetic tests
refuse reuse of a passing shadow report and block a newly retracted result before
the temporary business write. They do not authenticate a real provider connection.

## Reproduction without installation or a model

From the repository root, using existing development dependencies:

```sh
python -B mcp/tests/test_shadow_workflow.py
python -B mcp/tests/test_wheel_archive.py
```

The first creates a separate temporary workspace with a synthetic source file.
It covers a correct result, a wrong sum, missing policy, multiple required checks,
invalid replies, wrong bindings, provider failure/retraction, source changes before
dispatch/during work/during verification, preservation of the source, and direct
delivery to a child process through stdin. It does not use user business data.

The archive suite imports the workflow from the built wheel, checks its actual
import origin, and repeats the integration tests without package installation.
The installation-based distribution suite is updated too, but requires separate
permission to run where installation is prohibited.

`test_distribution_contract.py` also compares all packaged Python modules and
harness/template bytes, checks the actual import origin, and executes context,
freshness, review, shadow, product and runtime regressions from a temporary offline
installation. Installed tests do not activate the user's existing MCP connection.
