"""Optional local Mirror registration check; no Mirror import at package startup.

Reads only a bounded snapshot copy supplied by the host. This is not claim truth,
preregistration quality, provider authentication or publication authorization.
"""
import argparse
from contextlib import contextmanager
import hashlib
import os
import sys

from .command_provider import _parse
from .context_shadow import checked, encoded

CHECK = 'mirror-registration-current'


@contextmanager
def _snapshot_path(raw):
    """Sealed anonymous Linux file for Mirror's path-based reader; no disk fallback."""
    if sys.platform != 'linux' or not hasattr(os, 'memfd_create'):
        raise ValueError('sealed memory snapshots require Linux memfd')
    import fcntl
    fd = os.memfd_create('yeoul-mirror-snapshot', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError('incomplete memory snapshot')
            remaining = remaining[written:]
        os.lseek(fd, 0, os.SEEK_SET)
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & seals != seals:
            raise ValueError('memory snapshot seals incomplete')
        yield '/proc/self/fd/' + str(fd)
    finally:
        os.close(fd)


def evaluate(snapshot, source_id, claim_id):
    # Mirror is optional; absence fails the invocation, without installing it.
    from mirror_stack_mcp.integrity import read_verified
    from mirror_stack_mcp.gate import scan_claim
    checked(snapshot)
    sources = [source for source in snapshot['sources'] if source['id'] == source_id]
    if len(sources) != 1 or sources[0]['category'] != 'VALIDATOR_ONLY':
        raise ValueError('host-selected private ledger source required')
    raw = sources[0]['body'].encode('utf-8')
    if len(raw) > 1024*1024:
        raise ValueError('ledger snapshot exceeds limit')
    reference = 'mirror-snapshot-sha256:' + hashlib.sha256(raw).hexdigest()
    with _snapshot_path(raw) as path:
        entries, error = read_verified(path)
        if error:
            return dict(status='fail', evidence_ref=reference)
        if any(len(entry['seal']) != 64 for entry in entries):
            return dict(status='unknown', evidence_ref=reference)
        # An uninterpretable withdrawal cannot be treated as no withdrawal.
        malformed = any(entry.get('claim_id') == claim_id and entry.get('_type') == 'retraction'
            and (not isinstance(entry.get('reason'), str) or not entry['reason'].strip())
            for entry in entries)
        if malformed:
            return dict(status='unknown', evidence_ref=reference)
        registration, retracted, _ = scan_claim(path, claim_id, entries)
    status = 'retracted' if retracted else ('pass' if registration is not None else 'unknown')
    return dict(status=status, evidence_ref=reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--claim-id', required=True)
    parser.add_argument('--provider-id', required=True)
    args = parser.parse_args()
    try:
        if any(not value.strip() or len(value) > 1024
               for value in (args.source_id, args.claim_id, args.provider_id)):
            raise ValueError('invalid host selection')
        raw = sys.stdin.buffer.read(4*1024*1024+1)
        request = _parse(raw, 4*1024*1024)
        if (not isinstance(request, dict) or set(request) != {'version', 'stage', 'request_id',
                'check_id', 'provider_id', 'body'} or type(request['version']) is not int
                or request['version'] != 1 or request['check_id'] != CHECK
                or request['provider_id'] != args.provider_id
                or request['stage'] not in ('shadow', 'prepared')
                or not isinstance(request['request_id'], str)
                or len(request['request_id']) != 32
                or any(c not in '0123456789abcdef' for c in request['request_id'])):
            raise ValueError('unsupported verifier request')
        body = request['body']
        fields = {'snapshot', 'proposal', 'binding'} if request['stage'] == 'shadow' else {'snapshot', 'request'}
        if not isinstance(body, dict) or set(body) != fields:
            raise ValueError('invalid verifier request body')
        result = evaluate(body['snapshot'], args.source_id, args.claim_id)
        sys.stdout.buffer.write(encoded(dict(version=1, request_id=request['request_id'],
            request_sha256=hashlib.sha256(raw).hexdigest(), check_id=CHECK,
            provider_id=args.provider_id, **result)))
        return 0
    except Exception:
        # Never print ledger content, provider exceptions or host paths.
        sys.stderr.write('mirror registration verification unavailable or invalid\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
