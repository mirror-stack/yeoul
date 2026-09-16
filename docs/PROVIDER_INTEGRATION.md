# Verification provider integration (unreleased)

Yeoul accepts host-normalized reports; it does not authenticate a verifier or
establish evidence truth. Mirror is one optional independent provider, not a
package dependency. No provider connection or production loader is enabled here.

The optional [local command adapter](COMMAND_PROVIDER.md) supplies a strict,
request-bound wire protocol and per-process limits for a host-selected executable.
It does not authenticate a remote provider or implement claim-status verification.

The optional [Mirror registration-current adapter](MIRROR_REGISTRATION_PROVIDER.md)
implements one narrower check over host-supplied snapshots using real Mirror code.
It observes registration and withdrawal, not result truth or publication eligibility.

## Define the question before translating a result

`pass` means that **this specific required check**, for the exact current prepared
operation, passed according to its trusted provider. It must not mean merely that
an API returned successfully, an evidence file has a valid hash, or publication is
permitted. Select complete check IDs and providers on the host, not in model text.

For example, keep `publication-policy`, `claim-validity`, and `source-integrity`
separate. Passing publication policy cannot satisfy claim validity. A negative
result may be perfectly legitimate to publish; workflows publishing negatives
should check accurate disclosure, not require a fabricated positive claim.

### Mirror compatibility note

Local source inspection of mirror-stack-mcp commit
`5191f47ef4a329a7f2ff8348dc428a8e68794a38` found these semantics. This is a pinned
source observation, not a statement about every installed or future version.

| Observed result | What it supports | What it does not support |
| --- | --- | --- |
| `mm_preflight(gate="publish")` returns `GO` | Publication conditions passed, including a sealed negative or retraction | The claim is true or the proposal is approved |
| `mm_preflight(gate="compute")` returns `GO` | Preregistration conditions passed | The experiment has run or succeeded |
| `HASH_RECOMPUTED` / valid chain | The supplied snapshot's hashes and links match | Provider identity, complete current history, or content truth |
| `BLOCK`, missing data, parse/transport error | Hold the relevant operation | A proven false claim, unless an authenticated claim verdict separately says so |

`mm_verify` returns probe findings for the supplied inputs, not Yeoul's bound report
schema. `mm_retract` appends a retraction: it is a write operation, not a status
query. `pm_verify` also records provenance evidence and must not be invoked as a
read-only connection probe. Never discover withdrawal by issuing a retraction.

The inspected `mm_preflight` response does not provide Yeoul's prepared task,
tool/argument, source revision and proposal binding. Renaming `GO` to `pass`, or
adding a new binding to an old report, cannot supply the missing verification.

## Host adapter acceptance checklist

Before enabling a real provider, establish all of the following:

1. **Identity and scope:** host-selected provider implementation/endpoint and
   credentials; allowlisted read-only operations and source locations. A provider
   label, ledger hash or model-supplied endpoint is not authentication. Keep
   credentials and private source bindings outside worker input.
2. **Exact operation:** verify the requested check against the prepared tool,
   arguments, proposal and current authoritative source set. Preserve the provider's
   evidence reference and assessed scope. A shadow report is not a prepared report.
3. **Current complete evidence:** read the authoritative current status, including
   withdrawals, rather than selecting an older passing event. Missing, unsupported,
   ambiguous, failed or unauthenticated responses hold the task. Do not infer a
   claim verdict from a diagnostic message or publication decision.
4. **Bounded communication:** enforce response limits, deadlines, partial-response
   refusal and cancellation in the actual transport. A synchronous trusted Python
   callback does not provide these limits by itself. Do not silently retry an
   uncertain external operation or retain credentials in diagnostics.
5. **Execution boundary:** obtain fresh prepared reports and explicit host approval
   through [reviewed execution](REVIEWED_EXECUTION.md), preserving denial evidence.
   State precisely how withdrawal is ordered with commit. A final network read
   alone cannot prevent a remote withdrawal racing immediately afterward.

No general claim-status adapter, signature scheme, remote withdrawal subscription,
or cross-system transaction is supplied by this guide. Those remain integration
work, not capabilities implied by a green local test. Do not duplicate Mirror's
ledger/verifier logic inside Yeoul to conceal a missing provider contract.

## Test the boundary, not just a successful response

Use synthetic data and an explicitly selected local provider implementation first.
Check a negative result, inconclusive result, retraction and corrupted evidence;
then test wrong identity/target, stale source, missing checks, timeouts, and a
withdrawal between shadow review and prepared execution. Record which parts used
real provider code and which were fixture callbacks. Actual authenticated transport
and deployment require separate evidence and authorization.

The [shadow-to-write tests](REVIEWED_EXECUTION.md#shadow-to-write-boundary) cover
binding separation and a fresh synthetic withdrawal at the local write gate. They
do not prove remote authenticity or live withdrawal discovery.
