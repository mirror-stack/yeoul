#!/usr/bin/env python3
"""Check publishable Markdown links without network access.

Repository-local target existence, boundary containment and Markdown heading
anchors are checked. Remote URLs are intentionally out of scope.
"""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import re
import sys
import unicodedata


INLINE = re.compile(r'!?\[[^\]\n]*\]\(([^)\n]+)\)')
WRAPPED_IMAGE = re.compile(r'\[!\[[^\]\n]*\]\([^)\n]+\)\]\(([^)\n]+)\)')
REFERENCE = re.compile(r'^\s*\[[^\]\n]+\]:\s*(.+?)\s*$')
FENCE = re.compile(r'^\s*(```+|~~~+)')
INLINE_CODE = re.compile(r'`[^`\n]*`')
HEADING = re.compile(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$')
REMOTE_SCHEMES = {'http', 'https', 'mailto', 'tel', 'data'}


def link_target(raw):
    raw = raw.strip()
    if raw.startswith('<'):
        end = raw.find('>')
        return raw[1:end] if end >= 0 else None
    # A title may follow a whitespace-free destination. Paths containing spaces
    # must use Markdown's angle-bracket destination form.
    return raw.split(None, 1)[0] if raw else None


def markdown_targets(text):
    fenced = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        visible = INLINE_CODE.sub('', line)
        for match in WRAPPED_IMAGE.finditer(visible):
            yield line_number, link_target(match.group(1))
        for match in INLINE.finditer(visible):
            yield line_number, link_target(match.group(1))
        match = REFERENCE.match(visible)
        if match:
            yield line_number, link_target(match.group(1))


def heading_anchors(text):
    anchors, counts = set(), {}
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        label = re.sub(r'<[^>]*>', '', match.group(1))
        label = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', label)
        label = label.replace('`', '').lower()
        label = ''.join(character for character in label
                        if character in '-_' or not unicodedata.category(character).startswith(('P', 'S')))
        base = re.sub(r'\s+', '-', label.strip())
        if not base:
            continue
        duplicate = counts.get(base, 0)
        counts[base] = duplicate + 1
        anchors.add(base if duplicate == 0 else f'{base}-{duplicate}')
    return anchors


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: check_markdown_links.py REPO FILELIST')
    root = Path(sys.argv[1]).resolve()
    file_list = Path(sys.argv[2])
    failures = []
    anchor_cache = {}
    for relative in file_list.read_text(encoding='utf-8').splitlines():
        if not relative.endswith('.md'):
            continue
        source = (root / relative).resolve()
        try:
            text = source.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            failures.append((relative, 0, 'unreadable Markdown: ' + type(exc).__name__))
            continue
        for line, target in markdown_targets(text):
            if not target:
                continue
            parsed = urlsplit(target)
            if parsed.scheme.lower() in REMOTE_SCHEMES or parsed.netloc:
                continue
            if parsed.scheme:
                failures.append((relative, line, 'unsupported link scheme: ' + parsed.scheme))
                continue
            path_text = unquote(parsed.path)
            destination = (source if not path_text else
                ((root / path_text.lstrip('/')) if path_text.startswith('/')
                 else (source.parent / path_text)).resolve())
            try:
                destination.relative_to(root)
            except ValueError:
                failures.append((relative, line, 'link escapes repository: ' + target))
                continue
            if not destination.exists():
                failures.append((relative, line, 'missing local target: ' + target))
                continue
            fragment = unquote(parsed.fragment)
            if fragment and destination.suffix.lower() == '.md':
                if destination not in anchor_cache:
                    try:
                        anchor_cache[destination] = heading_anchors(
                            destination.read_text(encoding='utf-8'))
                    except (OSError, UnicodeError):
                        anchor_cache[destination] = set()
                if fragment not in anchor_cache[destination]:
                    failures.append((relative, line, 'missing local heading anchor: ' + target))
    for relative, line, reason in failures:
        print(f'{relative}:{line}: {reason}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
