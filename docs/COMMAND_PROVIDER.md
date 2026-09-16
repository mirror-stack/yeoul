# Host-selected command verifier (unreleased, Linux)

`CommandProvider` connects a trusted local verifier process to LocalHost's shadow
and prepared checks. It launches no default program, discovers no credentials and
does not connect Mirror or a model automatically. This is a bounded local protocol,
not remote authentication, a verifier implementation or a sandbox.

```python
from yeoul_mcp.command_provider import CommandProvider

provider = CommandProvider("required-check", "host-selected-provider",
    verifier_argv, cwd=verifier_directory, env=explicit_environment, timeout=5)
# Supply to LocalHost at host startup:
providers = {"required-check": ("host-selected-provider", provider.shadow, provider.prepared)}
```

The executable must be an absolute host-selected path; its implementation and
dependencies must be trusted. The default environment is empty, not inherited.
Credentials, when needed, require separately reviewed provisioning. Never let a
model choose executable paths, provider IDs or environment variables.

## Wire contract, version 1

One invocation receives one UTF-8 JSON object on stdin, then EOF:

```json
{"version":1,"stage":"prepared","request_id":"fresh-per-call-id",
 "check_id":"required-check","provider_id":"host-selected-provider",
 "body":{"request":{"job":{},"binding":{}},"snapshot":{}}}
```

The empty objects above indicate placement, not valid complete jobs. For shadow,
`body` instead contains `snapshot`, `proposal` and `binding`. Prepared requests
contain the actual tool/arguments and persisted candidate/source binding. Snapshots
can contain nonpublic data: they go only to the host's trusted verifier, not the
proposing worker. A verifier must assess the requested check against this exact
operation and authoritative current evidence, including retraction status.

The process returns exactly one JSON object on stdout and exits successfully:

```json
{"version":1,"request_id":"same-fresh-per-call-id",
 "request_sha256":"sha256-of-exact-stdin-bytes","check_id":"required-check",
 "provider_id":"host-selected-provider","status":"pass","evidence_ref":"provider:reference"}
```

Only `pass`, `fail`, `unknown`, `retracted` are accepted. Extra/missing fields,
duplicate keys, nonfinite values, partial JSON, mismatched identities or request
hashes are rejected. New IDs reject an old response even for identical request
bodies. Echoing IDs and hashes proves request correspondence only, not provider
identity, evidence truth, or complete current history. `GO` is not translated into
`pass`; follow the [provider integration contract](PROVIDER_INTEGRATION.md).

## Bounds and failure behavior

The underlying [command transport](WORKER_TRANSPORT.md) supplies streaming limits:
4 MiB encoded input, 64 KiB stdout, 64 KiB stderr, a default five-second deadline
and five-second cleanup allowance. Timeouts and limits use that transport's Linux
process-group cleanup. Nonzero exits are refused, even if they printed valid JSON.
No retry, model fallback, shell interpolation or automatic approval is performed.
LocalHost records a generic invalid/unavailable review on adapter errors without
copying raw rejected output into its approval audit.

These are per-invocation limits, not a whole-workflow deadline. Other callbacks,
especially approval UI, still need their own bounds. Blocked kernel calls and
descendants escaping the process group remain transport limitations. The command
can access whatever its OS account allows: use separately approved isolation for
untrusted code. No read-only OS boundary, resource quota, remote cancellation,
signature authentication or atomic ordering with remote retraction is added here.

Six protocol tests use real synthetic subprocesses for both stages and verdicts,
scope/schema rejection, repeated-body replay, timeout/output/exit errors and input
bounds. A LocalHost integration test also demonstrates timeout, then retraction,
then a fresh passing synthetic check: only the last requests approval and writes.
No actual provider service, private operational data or model is used.
