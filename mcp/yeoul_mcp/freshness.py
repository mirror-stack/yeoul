"""Bounded target snapshots for cooperative prepared-task execution.

Not an OS sandbox or proof of provenance. Call capture under workspace_lock.
"""
import hashlib
import json
from pathlib import Path
import stat
import time

MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 20000
MAX_SECONDS = 5
MAX_PREREG_BYTES = 64 * 1024


def targets(policy, tool, values):
    paths = []
    if tool in {'yeoul_new', 'build_handoff'}:
        paths.append(Path(policy.env['YEOUL_PROJECTS']) / values['name'])
    elif tool == 'arc_open':
        paths.append(Path(values['arcs_dir']))
    elif tool in {'arc_ticket', 'arc_close', 'arc_prereg', 'loop_guard_init', 'loop_guard_tick'}:
        arc = Path(values['arc_dir'])
        paths.append(arc)
        if tool == 'arc_close':
            paths.extend([arc.parent / '_archive' / arc.name, Path(policy.env['YEOUL_INDEX'])])
        prereg = arc / '.prereg'
        from .runtime import safe_components
        safe_components(prereg)
        if prereg.is_file():
            # Target discovery runs before the bounded tree walk. Do not read an
            # arbitrarily large metadata file just to discover a linked ledger.
            if prereg.stat().st_size > MAX_PREREG_BYTES:
                raise ValueError('preregistration metadata limit exceeded')
            with prereg.open('rb') as stream:
                data = stream.read(MAX_PREREG_BYTES + 1)
            if len(data) > MAX_PREREG_BYTES:
                raise ValueError('preregistration metadata limit exceeded')
            lines = data.decode('utf-8').splitlines()
            if len(lines) >= 2:
                paths.append(policy.path(lines[1], base=policy.cwd, external_read=True))
    elif tool == 'verify_gate':
        # Arbitrary approved verification can read/write anywhere in this workspace.
        paths.append(policy.root)
    else:
        raise ValueError('no freshness target contract for tool')
    if tool in {'arc_open', 'yeoul_new'}:
        paths.append(Path(policy.env['YEOUL_CLOSED_REGISTRY']))
    if tool == 'arc_prereg':
        ledger = values.get('ledger') or policy.env.get('YEOUL_LEDGER')
        if not ledger:
            raise ValueError('prepared preregistration requires an explicit ledger')
        paths.append(policy.path(ledger, base=policy.cwd, external_read=True))
    # Configuration is authority input, not a writable business target.
    paths.append(policy.root / '.yeoul-workspace.json')
    return sorted(set(paths), key=str)


def capture(policy, tool, values):
    from .runtime import safe_components
    deadline = time.monotonic() + MAX_SECONDS
    count = size = 0
    summaries = []
    for target in targets(policy, tool, values):
        h = hashlib.sha256()
        stack = [target]
        while stack:
            path = stack.pop()
            if path == policy.root / '.yeoul-mcp':
                continue
            count += 1
            if count > MAX_ENTRIES or time.monotonic() > deadline:
                raise ValueError('freshness scan limit exceeded')
            safe_components(path)
            relative = '.' if path == target else path.relative_to(target).as_posix()
            if not path.exists():
                h.update(json.dumps([relative, 'missing']).encode())
                continue
            before = path.stat()
            if stat.S_ISDIR(before.st_mode):
                # Directory mtimes change on unrelated sibling creation; bind membership instead.
                h.update(json.dumps([relative, 'directory']).encode())
                children = []
                for child in path.iterdir():
                    if count + len(stack) + len(children) + 1 > MAX_ENTRIES or time.monotonic() > deadline:
                        raise ValueError('freshness scan limit exceeded')
                    children.append(child)
                stack.extend(sorted(children, key=lambda p: p.name, reverse=True))
            else:
                if size + before.st_size > MAX_BYTES:
                    raise ValueError('freshness byte limit exceeded')
                body = hashlib.sha256()
                with path.open('rb') as stream:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError('freshness byte limit exceeded')
                        body.update(chunk)
                        if time.monotonic() > deadline:
                            raise ValueError('freshness scan timeout')
                after = path.stat()
                identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                if identity(before) != identity(after):
                    raise ValueError('source changed during freshness capture')
                h.update(json.dumps([relative, 'file', identity(after), body.hexdigest()]).encode())
        summaries.append({'path': str(target), 'sha256': h.hexdigest()})
    return {'schema': 1, 'targets': summaries}


def check_shape(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'targets'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['targets'], list) or not 1 <= len(value['targets']) <= 16):
        raise ValueError('invalid prepared freshness contract')
    previous = None
    for item in value['targets']:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256'}
                or not isinstance(item['path'], str) or not Path(item['path']).is_absolute()
                or not isinstance(item['sha256'], str) or len(item['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in item['sha256'])
                or (previous is not None and previous >= item['path'])):
            raise ValueError('invalid prepared target digest')
        previous = item['path']
    return value
