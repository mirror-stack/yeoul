# Local worker access (unreleased, Linux only)

`WorkerAccess` binds `WorkerTasks.authorize` to kernel-reported UNIX stream
connection credentials, not a user name or UID supplied in request data.
Only a trusted host configures task IDs, owning UIDs and explicit `execute`,
`inspect`, `retire`, `cancel` actions. No action implies another action. Existing
three-action policies do not acquire cancellation authority automatically.

```python
access = WorkerAccess(workspace_root)
# Trusted operator setup only; never expose configure through client dispatch.
revision = access.configure({"ticket-123": {"uid": allowed_uid,
                                         "actions": ["execute", "inspect"]}})
tasks = WorkerTasks(workspace_root, host_invoke, argv=host_command,
                    uid=worker_uid, gid=worker_gid, authorize=access.authorize)
# accepted_socket is a real connected UNIX stream socket owned by the host.
with access.connection(accepted_socket):
    output = tasks.execute("ticket-123", frozen_input)
# Updates require the current revision; old policy revisions are retained.
access.configure({}, expected_revision=revision)
```

The host owns and closes the socket. Identity is scoped to the connection context;
leaving the scope also invalidates copied contexts. Every authorization reloads
the current host-owned policy. Missing/corrupt/unprotected policies, closed sockets,
unknown tasks and absent grants deny access. WorkerTasks rechecks before dispatch
reservation and result delivery, including retained-result delivery after restart.
Policy writes use the same workspace lock and preserve prior revisions in history.
Authorization callbacks must not acquire that lock again.

This authenticates the account at connection establishment, not a particular app
or each message after descriptor transfer. Same-UID processes share authority;
same-account metadata rewriting is outside the protection provided. The host itself is trusted.
No listener, framing, rate limiting, remote authentication, root daemon, production
socket permissions or operational grants are installed. This does not cancel an
already dispatched job, fence late starts or approve a business-state change.

Fourteen Linux tests cover real socket credentials, foreign-owner denial, individual
actions, expired/copied contexts, closed sockets, revocation, corrupt policies and
stale revision refusal. Opt-in isolated-service integration connects this boundary
to a synthetic task, shadow review and restart replay without a new execution.

## Policy changes and existing execution

Through the trusted `configure` API, removing an existing execute grant or changing
its owning UID now persists logical cancellation intent and the corresponding
unit's launch revocation marker before replacing the policy. Only affected task
IDs with existing mappings are touched. Removing unrelated actions does not
cancel execution. Configuration uses the same workspace lock as dispatch/delivery
checks and the same revocation writer as explicit cancellation. No service broker
is called during policy configuration.

This makes queued version-3 launches consult revocation and prevents future result
delivery. It does **not** stop an already running service; a host operator with
separately granted `cancel` authority must observe/stop it. Direct external edits
to the JSON policy are not a supported revocation transaction or watched event.
Other host authorization implementations do not acquire this behavior automatically.

Policy updates are fail-closed, not an all-or-nothing multi-file transaction.
If marker/policy persistence fails, the old policy may remain while some affected
tasks are already held. The error is returned; existing evidence is preserved.
An operator may retry the intended update with the unchanged expected revision.
Neither retry nor granting execute again clears an existing cancellation intent.
Restored permissions or a new owner cannot silently revive old work; creation of
new work requires separate host workflow decisions and reconciliation as needed.

Tests cover revocation during dispatch, owner transfer, unrelated action changes,
restore-without-rearming, marker-write failure and policy-write failure without
service calls or overwriting existing cancellation evidence.
