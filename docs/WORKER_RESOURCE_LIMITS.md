# Temporary Linux resource enforcement evidence

Status: opt-in synthetic host test, not a production launcher or installation.
The operator must approve transient system service creation. No existing unit,
user-controller delegation, account, package or host file mode is changed by the
test. Existing noninteractive administrative access is required; no password is
requested or stored. An unavailable capability fails/skips explicitly, never falls
back to an unrestricted worker.

## What runs

`mcp/tests/test_worker_resource_limits.py` creates uniquely named
`yeoul-resource-test-<uuid>.service` transient services through systemd. Service
creation is privileged, but every fixed synthetic payload runs as the invoking
non-root user with no new privileges. Do not expose this sudo/service-creation
capability or permit arbitrary service properties through worker MCP tools.

Each service has these limits, verified by reading its actual cgroup files:

| Resource | Limit | Observed enforcement |
|---|---|---|
| CPU bandwidth | 50,000 μs per 100,000 μs period (0.5 core) | Busy work increases kernel throttling counters |
| Memory | 128 MiB, swap 0 | Allocating/touching child killed; cgroup OOM counter increases |
| Processes/threads | 16 total | Parent plus 15 children; next fork denied with EAGAIN |
| Temporary output storage | 16 MiB tmpfs | Extra file writes denied with ENOSPC |

Services also declare a 15-second runtime ceiling, three-second stop timeout and
control-group cleanup. These are configured safeguards; this test does not exhaust
the lifetime ceiling or prove all escaped-child cleanup scenarios.

A fifth case launches existing Bubblewrap inside the limited service. It mounts
synthetic input read-only, private output writable on the same bounded tmpfs,
software read-only and only its own cgroup files read-only. Host home/source paths
are not mounted. A new network namespace cannot reach a live listener in the
outer test service. The child reads [4,7,6], returns a proposal of 17 and preserves
the input and hidden marker. This is deterministic test code, not a model call or
an actual verification-provider integration.

Services use automatic collection. The test checks each exact generated unit is
unloaded, stopping only that unit if needed. Its tmpfs is ephemeral: test output
files disappear when the service ends. There is no source import, publication or
commit. Runtime process accounting may remain in the host journal; test code does
not erase system logs.

## Reproduction

After explicit approval, on a compatible host with existing systemd, sudo,
Bubblewrap and `/usr/bin/python3`:

```sh
YEOUL_RUN_RESOURCE_TESTS=1 python -B mcp/tests/test_worker_resource_limits.py
```

Without opt-in the test skips and performs no privileged action. Regular CI must
not set the opt-in automatically. A passing skip is not enforcement evidence.

Observed 2026-09-15: all five cases passed on Linux/systemd 249. Final enumeration
found no remaining test units; existing user delegation remained `memory pids`.
The earlier missing user-level CPU delegation was addressed by approved separate
temporary system services, not by widening the existing user's delegation.

## Limits and product work still required

Follow-up: an opt-in [host-only product adapter](ISOLATED_WORKER.md) now implements
fixed manifests, kernel-limit preflight, isolated stdin/stdout delivery and host
lifecycle events, with actual shadow-flow tests. It still requires a trusted host
broker and is not automatically installed or enabled.

The resource fixture alone proves a viable host-side primitive, not finished operational integration.
Production still needs a narrowly authorized host broker and durable operational
storage for the adapter's manifest and lifecycle records, plus integration with
the actual model/provider and reviewed business task.
Never package this test's general sudo invocation as an agent-accessible API.

The storage bound is for the dedicated memory-backed output filesystem; it is not
a general host disk quota. The fifth case proves namespace and resource setup work
together, while overflow cases exercise those same limits separately. It does not
prove every attack inside the combined setup, whole-machine power-loss durability,
cross-platform support, or live model/provider/commit integration. See also
[namespace isolation](WORKER_ISOLATION.md), [bounded transport](WORKER_TRANSPORT.md)
and [reviewed execution](REVIEWED_EXECUTION.md).
