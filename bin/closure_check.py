#!/usr/bin/env python3
"""Required closure fields, shared by the public and internal harness.

Shape/substance checks are not evidence verification or independent reproduction.
"""
import re
import sys
from pathlib import Path


def check_fields(text, kill, linked):
    # Unicode escapes keep this shared source locale-neutral for publication.
    groups = [('Result triggers', '\uacb0\uacfc\uac00') if linked
              else ('Kill wording', 'kill \ubb38\uc5b8')]
    if kill:
        groups += [('Anchor', '\uc575\ucee4'), ('Independent', '\ub3c5\ub9bd'),
                   ('Implementation', '\uad6c\ud604'), ('Catalog', '\ub3c4\uac10')]
    labels = re.findall(r'^- \*\*([^*]+)\*\*:', text, re.M)
    for alternatives in groups:
        if sum(any(label.startswith(prefix) for prefix in alternatives) for label in labels) != 1:
            raise ValueError('missing or duplicated required closure field: '+alternatives[0])


def main():
    try:
        text = Path(sys.argv[1]).read_text(encoding='utf-8')
        if sys.argv[2] == '--record':
            verdicts = re.findall(r'^- \*\*(?:Verdict|\ud310\uc815)\*\*:\s*(.*)$', text, re.M)
            stops = re.findall(r'^- \*\*stop_reason\*\*:\s*(\S+)', text, re.M)
            if verdicts != [sys.argv[3]] or stops != [sys.argv[4]]:
                raise ValueError('verdict/stop must occur once and match the requested close')
            for title in (r'What was closed|\ub2eb\uc740 \uac83',
                          r'What was NOT closed|\uc548 \ub2eb\uc740 \uac83'):
                sections = re.findall(r'^## (?:'+title+r')[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
                if len(sections) != 1 or not any(c.isalnum() for c in sections[0]):
                    raise ValueError('missing/empty/duplicated conclusion or out-of-scope section')
        else:
            check_fields(text, sys.argv[2] == 'yes', sys.argv[3] == 'yes')
    except (OSError, ValueError, IndexError) as exc:
        print(f'closure refused: {exc}', file=sys.stderr)
        return 5
    return 0


if __name__ == '__main__':
    sys.exit(main())
