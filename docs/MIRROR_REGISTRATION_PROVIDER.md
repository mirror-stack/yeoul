# Optional Mirror registration-current check (unreleased, Linux)

This adapter connects actual Mirror `integrity.read_verified` and `gate.scan_claim`
to the [command verifier protocol](COMMAND_PROVIDER.md). Mirror stays optional:
the module imports it only when evaluating a request and never installs it.
Mother and LaneStack are not dependencies. No operating ledger is opened or modified.

## Exact question

`mirror-registration-current` checks that the host-selected claim has a registration
in the supplied hash-checked snapshot and is not retracted under Mirror's scan rules.
It does **not** check result truth, metric validity, preregistration quality, external
timing, signature identity, complete history or publication eligibility. In particular,
a recorded negative result can coexist with a current registration and this check
can still pass. Host policy must require separate checks where those facts matter.

| Snapshot observation | Report |
| --- | --- |
| 64-hex chain verified, selected registration found, no observed retraction | `pass` |
| Selected registration has a reasoned retraction | `retracted` |
| Missing registration, malformed withdrawal, or legacy short seals | `unknown` |
| Mirror rejects the snapshot's integrity | `fail` (integrity only) |
| Missing dependency, invalid input, process/transport failure | Invocation refused |

This never translates publish `GO` into approval or claim validity. Currentness is
relative to the host's selected source snapshot, not an authenticated remote ledger.

## Host-selected configuration

Provision the ledger as a `VALIDATOR_ONLY` source in the protected FileSources
manifest. Select its ID and the claim ID at host startup, never from worker text.
Use the same check and provider IDs in LocalHost and CommandProvider:

```python
provider = CommandProvider("mirror-registration-current", "local-mirror",
    [python_executable, "-B", "-m", "yeoul_mcp.mirror_registration_provider",
     "--source-id", "claims", "--claim-id", "selected-claim",
     "--provider-id", "local-mirror"],
    cwd=verifier_directory, env=reviewed_environment)
providers = {"mirror-registration-current":
             ("local-mirror", provider.shadow, provider.prepared)}
```

The host must choose and trust the installed/imported Mirror implementation and
its search path. Labels, a local import and file hashes are not provider authentication.
No module, source path or credential is discovered from the request payload.
Only this fixed check ID is accepted. Full authoritative history selection remains
the host's responsibility; an omitted withdrawal cannot be discovered from an old copy.

## Read boundary and evidence

The adapter receives the supplied snapshot, selects exactly one configured private
source, limits its ledger text to 1 MiB, and creates an anonymous Linux `memfd` for
Mirror's file-based read API via `/proc/self/fd`. Before exposing that descriptor,
it seals writes, growth, shrinking and further seal changes. The descriptor is
close-on-exec and closed in a finally block. Failure to create/seal/read it refuses
verification; there is no named temporary-file fallback. No original source path is read,
and no `mm_retract`, provenance recording or external anchoring operation is invoked.

The returned evidence reference is the SHA-256 of the exact ledger bytes, not an
authenticated receipt. Request IDs/hashes bind the result to the current invocation.
LocalHost rereads original sources before/after review and approval; remote withdrawal
versus commit remains non-atomic. The local subprocess is trusted, not OS-sandboxed
by this adapter. Operational authentication and isolation require separate work.

This removes the adapter's named temporary ledger copy, not every form of data
retention. Input and parsed records also exist in process memory; swap, core dumps,
privileged inspection and copies made by trusted provider code remain outside this
boundary. No secure erasure or protection from the host account is claimed. An owned
child-process SIGKILL test checks descriptor disappearance and no new named file;
it does not cover providers deliberately exporting descriptors to other processes.

Twelve optional tests use synthetic data and the actual available Mirror package.
They check negative-result/current-registration distinction, withdrawal, malformed
withdrawal, missing registration, corruption, legacy short hashes, approved local
creation and withdrawal after preparation.
They additionally check real Mirror reading the sealed descriptor, rejected writes
and truncation, cleanup after reader/sealing failures, and owned-process SIGKILL.
Missing Mirror skips these optional tests; a skip does not prove interoperability.
Local checkout evidence used Mirror commit
`5191f47ef4a329a7f2ff8348dc428a8e68794a38`; other versions need their own test run.
