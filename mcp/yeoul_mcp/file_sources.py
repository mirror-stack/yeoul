"""Opt-in host-selected current files and bounded on-demand context retrieval."""
import json
import os
import threading
import time

from .candidate_input import collect_candidate
from .context_shadow import checked, digest, encoded, retrieve
from .workspace import checked_path

HOST_SELECTION_ID = '__yeoul_host_selection__'


class FileSources:
    """Host provisions .yeoul-mcp/source-manifest.json; no default discovery.

    File roles/categories are authority supplied by the host, never inferred from
    prose. This cannot prove that the host selected every applicable policy.
    """
    def __init__(self, root):
        self.root = checked_path(root, existing=True)

    def _manifest(self):
        path = checked_path(self.root / '.yeoul-mcp' / 'source-manifest.json', existing=True)
        parent, info = path.parent.stat(), path.stat()
        if (parent.st_uid != os.geteuid() or parent.st_mode & 0o077
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError('source manifest must be protected by its host account')
        raw = collect_candidate(self.root, '.yeoul-mcp/source-manifest.json', byte_limit=65536)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate source manifest field')
                result[key] = value
            return result
        manifest = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(manifest, dict) or set(manifest) != {'version', 'target', 'sources'}
                or type(manifest['version']) is not int or manifest['version'] != 1
                or not isinstance(manifest['sources'], list) or not 1 <= len(manifest['sources']) <= 64):
            raise ValueError('invalid bounded host source manifest')
        for source in manifest['sources']:
            if (not isinstance(source, dict) or set(source) != {'id', 'role', 'category', 'path'}
                    or not isinstance(source['path'], str) or source['id'] == HOST_SELECTION_ID):
                raise ValueError('invalid host source entry')
        checked(dict(target=manifest['target'], revision='shape', sources=[
            dict(id=s['id'], role=s['role'], category=s['category'], body='shape') for s in manifest['sources']]))
        return manifest

    def load_snapshot(self):
        manifest = self._manifest()
        deadline = time.monotonic() + 30
        def collect():
            result, total = [], 0
            for source in manifest['sources']:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or total >= 4*1024*1024:
                    raise ValueError('host source snapshot budget exceeded')
                raw = collect_candidate(self.root, source['path'], byte_limit=min(1024*1024, 4*1024*1024-total),
                                        timeout=min(5, remaining))
                total += len(raw)
                result.append(dict(id=source['id'], role=source['role'], category=source['category'],
                                   body=raw.decode('utf-8')))
            return result
        sources = collect()
        # Catch observed edits across collection, not just inside a single read.
        if self._manifest() != manifest or collect() != sources or self._manifest() != manifest:
            raise ValueError('host source set changed while reading')
        if time.monotonic() >= deadline:
            raise ValueError('host source snapshot deadline exceeded')
        # Public revision commits only to already-disclosed active content/pointers.
        # Keep manifest paths and nonpublic bodies in the host-only binding instead.
        ordered = sorted(sources, key=lambda source: source['id'])
        public = dict(target=manifest['target'],
            active=[s for s in ordered if s['category'] == 'REQUIRED_ACTIVE'],
            retrieval_pointers=[dict(id=s['id'], role=s['role']) for s in ordered
                                if s['category'] == 'RETRIEVABLE_ON_DEMAND'])
        sources.append(dict(id=HOST_SELECTION_ID, role='host_selection', category='VALIDATOR_ONLY',
                            body=encoded(manifest).decode('utf-8')))
        return checked(dict(target=manifest['target'], revision=digest(public), sources=sources))

    def retrieval_session(self, packet, *, max_requests=8, max_bytes=256*1024):
        return FileRetrieval(self, packet, max_requests=max_requests, max_bytes=max_bytes)


class FileRetrieval:
    """One host-bound request budget; returned bytes are the counted wire payload."""
    def __init__(self, source, packet, *, max_requests, max_bytes):
        if (type(max_requests) is not int or not 1 <= max_requests <= 64
                or type(max_bytes) is not int or not 1 <= max_bytes <= 4*1024*1024):
            raise ValueError('invalid retrieval budget')
        self.source = source
        self._packet = json.loads(encoded(packet))
        self.max_requests, self.max_bytes = max_requests, max_bytes
        self.requests, self.delivered_bytes = 0, 0
        self._lock = threading.Lock()

    def request(self, source_id):
        with self._lock:
            if self.requests >= self.max_requests:
                raise ValueError('retrieval request limit exceeded')
            self.requests += 1  # Denied/stale requests consume an attempt too.
            if not isinstance(source_id, str) or source_id not in {
                    p['id'] for p in self._packet['model']['retrieval_pointers']}:
                raise ValueError('source is not allowlisted for retrieval')
            current = self.source.load_snapshot()
            body = retrieve(self._packet, current, source_id)
            wire = encoded(dict(id=source_id, body=body,
                                model_sha256=self._packet['binding']['model_sha256']))
            if self.delivered_bytes + len(wire) > self.max_bytes:
                raise ValueError('retrieval byte limit exceeded')
            self.delivered_bytes += len(wire)
            return wire
