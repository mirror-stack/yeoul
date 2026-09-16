"""Compare existing host metadata copies without restoring or authorizing them."""
import hashlib
import os
from pathlib import Path
import stat
import sys
import time

from .candidate_input import collect_candidate
from .workspace import checked_path


def compare_evidence(reference_root, candidate_root):
    """Host-operator-only bounded comparison of two existing .yeoul-mcp trees.

    Both copies must retain workspace.lock. Shared locks open existing files
    read-only; no runtime initialization, copy, extraction or record edits occur.
    Matching bytes are not authenticity, freshness, semantic validity or approval.
    """
    if sys.platform != 'linux':
        raise ValueError('Linux read-only evidence comparison required')
    import fcntl
    roots = [checked_path(root, existing=True) for root in (reference_root, candidate_root)]
    if roots[0] == roots[1] or any(a in b.parents for a, b in (roots, roots[::-1])):
        raise ValueError('choose distinct non-nested existing evidence roots')
    deadline = time.monotonic() + 30
    handles = []

    def tick():
        if time.monotonic() >= deadline:
            raise ValueError('evidence comparison deadline exceeded')

    def stamp(path):
        info = path.lstat()
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def inventory(root):
        control = checked_path(root / '.yeoul-mcp', existing=True)
        pending = [(control, 0)]
        identities, result, total, entries = {}, {}, 0, 0
        while pending:
            directory, depth = pending.pop()
            tick()
            checked_path(directory, existing=True)
            identities.setdefault(directory, stamp(directory))
            with os.scandir(directory) as listing:
                for entry in listing:
                    tick()
                    entries += 1
                    if entries > 4096:
                        raise ValueError('evidence entry limit exceeded')
                    path = checked_path(entry.path, existing=True)
                    identities[path] = stamp(path)
                    if stat.S_ISDIR(identities[path][2]):
                        if depth >= 16:
                            raise ValueError('evidence depth limit exceeded')
                        pending.append((path, depth + 1))
                        continue
                    relative = path.relative_to(control).as_posix()
                    if relative == 'workspace.lock':
                        continue  # Synchronization inode is not restorable evidence.
                    remaining = 32*1024*1024 - total
                    if remaining <= 0:
                        raise ValueError('evidence byte limit exceeded')
                    raw = collect_candidate(control, relative, byte_limit=min(4*1024*1024, remaining),
                                            timeout=max(.001, min(5, deadline-time.monotonic())))
                    total += len(raw)
                    result[relative] = (len(raw), hashlib.sha256(raw).hexdigest())
        for path, identity in identities.items():
            tick()
            if stamp(path) != identity:
                raise ValueError('evidence changed during comparison')
        return result, total, identities

    try:
        for root in sorted(roots):
            tick()
            lock = checked_path(root / '.yeoul-mcp' / 'workspace.lock', existing=True)
            before = stamp(lock)
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            handles.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino) != before[:2]:
                raise ValueError('unsafe evidence lock')
            while True:
                tick()
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.025)
        reference, reference_bytes, reference_identities = inventory(roots[0])
        candidate, candidate_bytes, candidate_identities = inventory(roots[1])
        for path, identity in {**reference_identities, **candidate_identities}.items():
            tick()
            if stamp(path) != identity:
                raise ValueError('evidence changed before comparison completed')
        missing = sorted(reference.keys() - candidate.keys())
        extra = sorted(candidate.keys() - reference.keys())
        changed = sorted(name for name in reference.keys() & candidate.keys() if reference[name] != candidate[name])
        return dict(byte_identical=not (missing or extra or changed), missing=missing, extra=extra,
                    changed=changed, reference_bytes=reference_bytes, candidate_bytes=candidate_bytes,
                    read_only=True, restore_authorized=False, execute_authorized=False,
                    scope='metadata copy comparison only; not authenticity or operational restoration')
    finally:
        for fd in reversed(handles):
            os.close(fd)
