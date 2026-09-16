# Worker isolation capability test

2026-09-15 follow-up: a separately approved [transient-service resource test](WORKER_RESOURCE_LIMITS.md)
now demonstrates CPU/memory/process/output limits and one combined Bubblewrap
case. The original fixture described below still has no quotas of its own;
neither test activates a production launcher.

Status: Linux-only, opt-in synthetic test using an already installed Bubblewrap
(`bwrap`). No Yeoul runtime launcher or operational profile is activated by this
test. No account creation, package installation, host permission changes or
dependency on Mirror, Mother or LaneStack is introduced.

## Boundary under test

A fresh temporary workspace contains three separate directories: authoritative
input, worker output, and a host-only marker. A child runs with a new user, mount,
PID, network, IPC and UTS namespace; dropped capabilities; a cleared environment;
a new session; and closed inherited file descriptors. System software under
`/usr` and library paths is read-only. The host root, home, and workspace are not mounted.
The only host directory writable by the worker is its temporary output directory.
The child also has ephemeral `/tmp`, a private `/proc`, and a minimal `/dev`.

The input directory is mounted read-only without changing its host permissions.
The same host account can still manage its own data outside the sandbox. This
avoids claiming that removing Unix write bits from a same-owner file is isolation.

The test checks these boundaries with actual child operations:

| Attempt | Required result |
|---|---|
| Read synthetic input and write a candidate in the output directory | Allowed |
| Overwrite, delete or chmod input | Denied |
| Rename or hardlink input into output | Denied |
| Write through an output symlink pointing at input | Denied |
| Read/write the unmounted host-only marker | Denied |
| Access the host marker through the host process's `/proc` root | Denied |
| Obtain a synthetic host environment sentinel | Not present |
| Connect to a live host-loopback test listener | Denied |

The parent separately checks that the candidate contains the correct synthetic
sum and the original input/marker contents and permission modes are unchanged.
No candidate is copied into authoritative storage or committed automatically.

## Reproduction and interpretation

Requires existing Linux namespace support, `bwrap`, and `/usr/bin/python3`:

```sh
YEOUL_RUN_ISOLATION_TESTS=1 python -B mcp/tests/test_worker_isolation.py
```

Do not install dependencies or change kernel/sysctl/security policy merely to make
this test pass without separate approval. With no opt-in, the test is skipped.
Missing tools are also a skip, not a successful isolation result. With the required
tools present, namespace/launch failures fail the test; there is no raw-execution
fallback. Existing sandbox restrictions may prohibit nested namespaces; a test
outside that sandbox needs explicit approval and must retain the synthetic scope.

Observed local result: three tests passed, including the original twelve child
boundary assertions and two connected shadow-flow cases. Input writes
and chmod failed with EROFS, cross-mount rename/hardlink with EXDEV, unmounted host
paths with ENOENT, and host-loopback connection with ECONNREFUSED. The listener
was live on the host, so a nonexistent service is not the explanation. A launch
probe inside the existing app sandbox failed; the approved host-side probe and
full synthetic tests passed. No security policy was relaxed to obtain that result.

## Connected test flow

Two cases connect the actual isolated process to `shadow_workflow.run_shadow`.
The host freshly loads synthetic source data, extracts Active Context, and sends
only the frozen model payload to the child's stdin. The child checks that private
validator/history markers are absent and the observed rows match its read-only
input. It returns an input-bound JSON proposal through stdout; the host independently
checks the arithmetic and routes the result. A correct total reaches ready_for_review;
an intentionally wrong total reaches needs_review. Both have NONE authority and
NOT_PERFORMED execution. No source or host marker contents/permissions change.

The output file is only a fixture artifact. It is not imported or executed by the
workflow. The parent now reads it with the [bounded collector](CANDIDATE_INPUT.md)
and compares its synthetic content; collection alone is not semantic verification.
The child launcher is local to the test, not a general-purpose product launcher.
Its pipe/deadline handling now uses the [bounded command transport](WORKER_TRANSPORT.md)
instead of collecting unrestricted subprocess output. This does not add CPU,
memory, process-count or disk quotas to the fixture.

## What this does not prove

- This deterministic child is not Luna or an untrusted arbitrary agent. Real model
  credentials, model transport and tool bridges must be designed separately. Do
  not mount a home directory or credential/socket store to make a model run.
- No CPU, memory, process-count, disk quota or comprehensive syscall filter is
  implemented. The test has a parent-side timeout, not production resource control.
- A host-side process under the same account can still modify source and output.
  Namespace isolation does not freeze source updates or authenticate the host.
- Candidates are untrusted data: a future importer must validate paths, symlinks,
  file types, sizes and diffs, then recheck current policy and target freshness.
  Never execute files or follow links merely because they came from the output.
- Windows/macOS, network filesystems, malicious kernel exploitation, external
  effects, all possible `/proc` attacks and automatic recovery are not covered.
- The synthetic test connects to `shadow_workflow`, but not to the commit path
  or a live model. This is evidence for a test-host adapter, not proof of end-to-end
  operational isolation or permission to activate a production launcher.

Yeoul owns worker lifecycle and safe result handling; evidence providers retain
their independent verification role. Installing or enabling a production launcher
requires separate approval and environment-specific validation.
