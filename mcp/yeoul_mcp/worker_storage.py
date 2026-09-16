"""Bounded metadata accounting and new-work admission, not a hard disk quota."""
import os
import shutil
import stat

from .workspace import checked_path
from .worker_transport import WorkerTransportError


def metadata_usage(root, *, max_entries=50000, max_depth=16):
    """Host-only byte/count snapshot; never returns contents or paths.

    Caller serializes cooperative writes with the workspace lock. External disk
    users and noncooperating writers are not constrained by this observation.
    """
    if (type(max_entries) is not int or not 1 <= max_entries <= 1000000
            or type(max_depth) is not int or not 1 <= max_depth <= 64):
        raise ValueError('invalid bounded storage scan')
    root = checked_path(root, existing=True)
    control = checked_path(root / '.yeoul-mcp')
    pending = [(control, 0)] if control.exists() else []
    size, entries = 0, 0
    while pending:
        directory, depth = pending.pop()
        checked_path(directory, existing=True)
        with os.scandir(directory) as listing:
            for entry in listing:
                entries += 1
                if entries > max_entries:
                    raise ValueError('metadata entry limit exceeded')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    size += info.st_size
                elif stat.S_ISDIR(info.st_mode):
                    if depth + 1 > max_depth:
                        raise ValueError('metadata depth limit exceeded')
                    pending.append((checked_path(entry.path, existing=True), depth + 1))
                else:
                    raise ValueError('unsafe metadata entry')
    return dict(logical_bytes=size, entries=entries, free_bytes=shutil.disk_usage(root).free,
                read_only=True, hard_quota=False, recovery_space_reserved=False)


def admit_storage(root, *, high_water_bytes, min_free_bytes):
    try:
        snapshot = metadata_usage(root)
    except (OSError, ValueError):
        raise WorkerTransportError('worker_storage_needs_attention') from None
    if snapshot['logical_bytes'] >= high_water_bytes:
        raise WorkerTransportError('worker_storage_high_water')
    if snapshot['free_bytes'] < min_free_bytes:
        raise WorkerTransportError('worker_storage_low_free_space')
    return snapshot
