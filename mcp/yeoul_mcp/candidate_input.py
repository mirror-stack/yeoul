"""Freeze one host-allowlisted candidate file. No parsing, execution or writes.

Linux descriptor-relative traversal refuses links. Stable metadata is a consistency
check, not provenance. The host still validates the returned bytes semantically.
"""
import os
from pathlib import Path
import stat
import sys
import time


def collect_candidate(root, relative_path, *, byte_limit=65536, timeout=5):
    """Return immutable bytes from a regular, single-link file under a host root.

    No directory enumeration or worker-selected discovery. Every path component
    is opened without following links, and the leaf is opened nonblocking so a
    FIFO replacement cannot block waiting for a writer. Never truncates a result.
    """
    if sys.platform != 'linux':
        raise ValueError('unsupported candidate collector')
    root = Path(root)
    if (not root.is_absolute() or root.parent == root or '..' in root.parts
            or len(str(root)) > 4096 or len(root.parts) > 64):
        raise ValueError('host must select an absolute candidate directory')
    if (not isinstance(relative_path, str) or len(relative_path) > 4096
            or len(relative_path.split('/')) > 64 or '\\' in relative_path or ':' in relative_path
            or any(ord(c) < 32 for c in relative_path)
            or any(p in ('', '.', '..') for p in relative_path.split('/'))):
        raise ValueError('invalid candidate relative path')
    if type(byte_limit) is not int or not 1 <= byte_limit <= 4*1024*1024:
        raise ValueError('invalid candidate byte limit')
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError('invalid candidate deadline')
    deadline = time.monotonic() + timeout
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    handles = []

    def tick():
        if time.monotonic() > deadline:
            raise ValueError('candidate read deadline exceeded')

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def directory_identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)

    def regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('candidate must be a regular non-aliased file')
        if info.st_size > byte_limit:
            raise ValueError('candidate byte limit exceeded')

    try:
        parent = os.open('/', directory)
        handles.append(parent)
        parts = relative_path.split('/')
        for part in root.parts[1:]:
            tick()
            parent = os.open(part, directory, dir_fd=parent)
            handles.append(parent)
        root_identity = directory_identity(os.fstat(parent))
        for part in parts[:-1]:
            tick()
            parent = os.open(part, directory, dir_fd=parent)
            handles.append(parent)
        tick()
        before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        regular(before)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        handles.append(fd)
        opened = os.fstat(fd)
        regular(opened)
        if identity(before) != identity(opened):
            raise ValueError('candidate changed before reading')
        data = bytearray()
        while True:
            tick()
            chunk = os.read(fd, min(65536, byte_limit-len(data)+1))
            if not chunk:
                break
            if len(data)+len(chunk) > byte_limit:
                raise ValueError('candidate byte limit exceeded')
            data.extend(chunk)
        tick()
        if (identity(opened) != identity(os.fstat(fd))
                or identity(opened) != identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False))):
            raise ValueError('candidate changed while reading')
        # The opened directory safely anchors this read, but the host also needs
        # to know that its allowlisted pathname still names that same boundary.
        try:
            current_root = os.open('/', directory)
            handles.append(current_root)
            for part in root.parts[1:]:
                tick()
                current_root = os.open(part, directory, dir_fd=current_root)
                handles.append(current_root)
            if directory_identity(os.fstat(current_root)) != root_identity:
                raise ValueError('candidate root changed while reading')
        except OSError:
            raise ValueError('candidate root changed while reading') from None
        return bytes(data)
    finally:
        for fd in reversed(handles):
            os.close(fd)
