"""Turn ONLY test fixtures into genuine MIRROR-SPEC chains; never use on live data."""
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
previous = 'genesis'
for row in rows:
    row.pop('seal', None)
    row['prev_seal'] = previous
    row['seal'] = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                          allow_nan=False).encode('utf-8')).hexdigest()
    previous = row['seal']
path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')
