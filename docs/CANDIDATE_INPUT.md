# Bounded candidate file collection

Status: opt-in Linux input collector, not an importer, verifier or commit API.
`yeoul_mcp.candidate_input.collect_candidate(root, relative_path)` returns immutable
bytes from one host-allowlisted output file. It never enumerates worker-chosen
directories, parses/executes content, copies it into authoritative state, or writes
files. The host selects the root/path and validates the resulting content separately.

The default byte limit is 64 KiB; the cooperative read deadline is 5 seconds.
Explicit limits are validated. Root and relative paths are bounded to 4,096
characters and 64 components each. Empty, absolute, traversal, control-character,
backslash and colon-containing relative paths are refused.

Traversal starts from a directory descriptor and opens every component with
O_NOFOLLOW and O_DIRECTORY. The leaf must be a regular file with one link; it is
opened with O_NOFOLLOW/O_NONBLOCK. Size is checked before reading and charged
against actual bytes as they are read. Oversize output is refused, never truncated.
Opened-file identity is compared before/after reading and against the final leaf
entry. Descriptors are closed on success and exceptions.

## What is and is not established

- A returned bytes object cannot later be changed by rewriting the file. Use those
  exact bytes for proposal validation/binding, not a subsequent path reread.
- Normal link aliases and leaf replacement during collection are refused. An open
  directory anchors traversal even if its pathname changes. This is not proof of
  the directory's continuing pathname identity or trusted origin; the host must
  keep ownership of the output-root handle/lifecycle and confirm the expected root.
- Metadata consistency and link count are not provenance. Same-user hostile host
  mutation, privileged mount changes and file-origin laundering are not solved.
- The deadline is checked between filesystem calls, not a hard timeout on blocked
  kernel/storage I/O. There is no aggregate directory quota or CPU/memory control.
- Nonblocking open helps avoid a FIFO replacement hanging the reader. This is not
  kernel-level protection against every device/filesystem race or malicious host.
- Non-Linux platforms refuse this collector; their existing Yeoul interfaces are
  unchanged. A skipped collector test does not establish platform support.
- A successfully collected wrong answer is still wrong. The isolation integration
  deliberately collects both 17 and 18 while independent review refuses 18.

Tests: `python -B mcp/tests/test_candidate_input.py`. Includes path ambiguity,
symlink components/leaf, hardlinks, FIFO, oversized/growing reads, leaf replacement,
deadline rejection and immutable results. The optional isolation suite additionally
collects a real namespace worker's candidate file; it does not publish it.
