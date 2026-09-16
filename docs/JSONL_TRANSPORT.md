# Bounded duplex JSONL transport

Unreleased, opt-in Linux building block. No dependency on Codex, Mirror, Mother,
Lane Stack or an account. `JsonlProcess` is not a model runner or sandbox.

`yeoul_mcp.jsonl_transport.JsonlProcess` accepts a host-selected absolute command,
working directory and explicit environment (empty by default). Use it only in a
`with` block. `send(dict)` and `receive()` exchange strict UTF-8 JSON objects.
Requests, notifications and responses all count against cumulative limits.

`poll()` drains at most one I/O readiness batch and returns a complete frame or
`None`. It preserves partial bytes internally and never renews the session deadline.
The host can use it to send cancellation before the overall transport deadline;
it is not itself a cancellation protocol. Process/OS delays remain subject to the
same limitations as `receive()`.

Defaults are 30 seconds for the whole session, 3 seconds for leader cleanup,
1 MiB each for input/stdout, and 64 KiB stderr. Waiting for writable stdin drains
both output pipes too. Repeated messages do not renew the deadline or byte budget.
Invalid JSON, duplicate keys, nonfinite values, nonobjects, partial EOF, timeout
and excess output fail closed. I/O/protocol failure poisons the session. Child
stderr is counted but never printed or retained as a raw error message.

Nested request keys must be strings; numeric keys are not silently converted into
duplicate JSON keys. Decoded strings and keys must also encode as UTF-8, rejecting
unpaired escaped surrogates. Selector failures poison the session with a sanitized
reason. A final deadline check rejects responses whose parsing crossed the deadline;
it does not forcibly interrupt the parser itself.

Stdin selector registration/unregistration and output EOF unregistration errors
also poison the session with `jsonl_io_failed`. An unregister error does not replace an earlier timeout or
protocol failure. No automatic resend follows a partially delivered request.

Exit kills only the owned process group and reaps its leader. It does not stop an
existing daemon. It is not proof that a remote model request was cancelled, nor
that descendants which escape the group are stopped. Process creation, kernel
operations and synchronous JSON serialization are not forcibly interruptible.
Use an outer isolation/resource supervisor for untrusted workers.

Receiving a JSON object is not task completion. The host must separately enforce
RPC/turn identity, final response schema, no-tools policy, subscription-only
routing, durable intent, response recording and no automatic retries. A remote
cancel acknowledgement and a terminal interrupted event are separate evidence;
neither is manufactured by local process cleanup. On uncertainty, preserve the
attempt and do not redispatch. No model call is implemented by this component.

Verification: `python3 -B mcp/tests/test_jsonl_transport.py` runs real synthetic
processes with no models, network, accounts or installation. It covers duplex
Unicode framing/notifications, input backpressure, timeout, cumulative byte
caps, malformed and partial output, and cleanup after caller failure. Included
in CI and the temporary distribution-install test; CI edits are not remote CI
results. See [one-shot transport](WORKER_TRANSPORT.md) for shared boundaries.
