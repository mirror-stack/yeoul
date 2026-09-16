"""Opt-in test-host records using Yeoul's existing lock and safe-path helpers.

No model dispatch, credentials, repair, automatic retry or production loader.
The host must use a dedicated synthetic experiment root, outside worker access.
"""
import os

from comparison_design import cases, design
from comparison_results import summarize
from yeoul_mcp import runtime
from yeoul_mcp.context_shadow import encoded
from yeoul_mcp.workspace import checked_path, read_json


def _once(path, value):
    """Retain even a partial record on failure; never overwrite or clean it up."""
    raw = encoded(value)
    if len(raw) > 1024 * 1024:
        raise ValueError('experiment record exceeds 1 MiB')
    runtime.safe_components(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    runtime.sync_dir(path.parent)


class ComparisonJournal:
    def __init__(self, root, frozen_manifest):
        self.root = checked_path(root, existing=True)
        if not self.root.is_dir() or encoded(frozen_manifest) != encoded(design()):
            raise ValueError('dedicated root and unchanged frozen design required')
        self.manifest = encoded(frozen_manifest)

    def _directory(self, control):
        directory = control/'comparison'
        runtime.safe_components(directory)
        if not directory.exists():
            directory.mkdir(mode=0o700)
            runtime.sync_dir(control)
            _once(directory/'manifest.json', design())
        if encoded(read_json(directory/'manifest.json')) != self.manifest:
            raise ValueError('retained experiment design changed')
        return directory

    def reserve(self, run_id):
        """Return only after durable intent; any existing run directory blocks reuse.

        A reservation covers the complete conversation, including its permitted
        retrieval continuation. It does not itself permit any model call.
        """
        run = next((r for r in design()['runs'] if r['run_id'] == run_id), None)
        if run is None:
            raise ValueError('unknown experiment run')
        row = next(c for c in cases() if c['case_id'] == run['case_id'])
        with runtime.workspace_lock(self.root) as control:
            parent = self._directory(control)
            directory = parent/run_id
            runtime.safe_components(directory)
            directory.mkdir(mode=0o700)  # Exclusive tombstone before writing intent.
            runtime.sync_dir(parent)
            intent = dict(version=1, design_sha256=design()['design_sha256'], run=run,
                          delivered_prompt=row['prompts'][run['arm']],
                          state='RESERVED_NOT_PROOF_OF_DISPATCH')
            _once(directory/'intent.json', intent)
            return intent

    def finish(self, record):
        """Preserve one host result, including errors; no new request or overwrite."""
        summarize([record])  # Validate shape/accounting; wrong answers remain records.
        with runtime.workspace_lock(self.root) as control:
            parent = self._directory(control)
            directory = parent/record['run_id']
            intent = read_json(directory/'intent.json')
            run = next(r for r in design()['runs'] if r['run_id'] == record['run_id'])
            row = next(c for c in cases() if c['case_id'] == run['case_id'])
            expected = dict(version=1, design_sha256=design()['design_sha256'], run=run,
                            delivered_prompt=row['prompts'][run['arm']],
                            state='RESERVED_NOT_PROOF_OF_DISPATCH')
            if encoded(intent) != encoded(expected) or record['delivered_prompt'] != intent['delivered_prompt']:
                raise ValueError('result does not match retained intent')
            _once(directory/'result.json', record)
