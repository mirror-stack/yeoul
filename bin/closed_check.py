#!/usr/bin/env python3
"""closed_check.py <topic> [registry_path]
If the topic overlaps the closed-question registry, print a warning to stdout (nothing if no match).
Best-effort: silently exit 0 if the registry/fields are missing. Called by arc-open at Gate-1.
Registry defaults to ./registry/closed_questions.jsonl (override via arg or YEOUL_CLOSED_REGISTRY).
"""
import sys, os, json, re

topic = sys.argv[1] if len(sys.argv) > 1 else ""
reg = sys.argv[2] if len(sys.argv) > 2 else os.environ.get(
    "YEOUL_CLOSED_REGISTRY", "./registry/closed_questions.jsonl")


def toks(s):
    return set(w for w in re.findall(r"[0-9A-Za-z]{2,}", (s or "").lower()))


tt = toks(topic)
if not tt:
    sys.exit(0)

hits = []
try:
    with open(reg, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            q = o.get("question")
            if not q:
                continue
            qt = toks(q)
            if not qt:
                continue
            inter = tt & qt
            ratio = len(inter) / len(qt)
            if len(inter) >= 3 and ratio >= 0.30:
                hits.append((ratio, o.get("id", "?"), q,
                             (o.get("conclusion", "") or "")[:90],
                             bool(o.get("no_reopen"))))
except FileNotFoundError:
    sys.exit(0)

hits.sort(reverse=True)
for ratio, qid, q, concl, noreopen in hits[:3]:
    flag = " 🚫no_reopen" if noreopen else ""
    print(f"⚠️ possible closed question ({ratio:.0%} overlap) [{qid}]{flag}: {q}")
    print(f"    conclusion: {concl}")
sys.exit(0)
