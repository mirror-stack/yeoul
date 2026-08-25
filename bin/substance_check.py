#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""substance_check.py — the one place an arc close decides whether an answer has substance.

This file is kept BYTE-IDENTICAL between the internal copy (apps/nacc/scripts/) and the OSS
copy (bin/). It emits machine CODES only; each shell renders its own prose. Drift between the
two copies is prevented by construction rather than by discipline — a previous fix went into
both copies while its regression test went into only one.

Why the length test was dropped
-------------------------------
The check used to be a single `[ ${#vans} -ge 6 ]` — six characters or more and the answer
sealed. Measured 2026-08-24 against the real binary: **28 of 28 evasive answers sealed, 0
caught** (`aaaaaa`, `yes yes`, `yes ok`, ...). Length is a proxy, and the set of non-answers
that satisfy a proxy is unbounded.

Raising the bar fails in the other direction: a genuine answer can be short
(`d=0.05 < 0.2, under the sealed bar`). So this judges CONTENT, and the repair was measured
both ways — evasions caught AND genuine answers not refused.

Korean here is functional data, not decoration
----------------------------------------------
Yeoul is used in Korean as well as English, so the trivial/deferral vocabularies and the field
labels include Korean. This repo's publish guard treats raw Hangul as a personalization leak
(`setup/pre-publish-check.sh`), so every Korean literal below is written as an escape carrying
a romanization and an English gloss. The guard uses that same technique on itself. The escapes
were generated, not typed, and round-tripped back to the source words before being committed.

Rejection codes (the shell attaches the wording)
------------------------------------------------
  DECODE_FAILED  not readable as UTF-8 — "could not judge", which is NOT "refused on the
                 merits"; merging the two disguises one as the other
  TRIVIAL_VOCAB  nothing but trivial vocabulary: `yes` `ok` `n/a` `.` `-`
  DEFERRAL       an honest non-answer: "don't know", "TODO", "not measured" — not a lie, but
                 it cannot ground a seal
  REPEATED_UNIT  one unit repeated: `yesyesyes`, `abcabcabc`
  LOW_DIVERSITY  almost no character variety: `aaaaaab`
  THIN_CONTENT   too few content tokens to carry a claim: `qwerty`, `123456`
  NEED_CATALOG   catalog field without a real catalog id (or the literal "none")
  NEED_ANCHOR    anchor field without a number or a seal/reproduction reference

🔴 These rules NARROW the class; they do not close it. They catch evasions we thought of.
That is exactly why the load-bearing part of this file is `--selftest`: the gate runs planted
specimens through this judge at the HEAD OF ITS EXECUTION PATH, and if the judge cannot
separate them it refuses to interpret the real answers at all.
"""
import re
import sys
import unicodedata

# ── Korean vocabulary, escaped so this file carries no raw Hangul ────────────────
_KO = {
    "YES1": "\uc608",                         # ye — "yes"
    "YES2": "\ub124",                         # ne — "yes"
    "NO_": "\uc544\ub2c8\uc624",              # anio — "no"
    "UHUH": "\uc751",                         # eung — "uh-huh"
    "DID": "\ud568",                          # ham — "did it"
    "DONE_": "\ub428",                        # doem — "done"
    "NONE_CH": "\ubb34",                      # mu — "none"
    "CONFIRM": "\ud655\uc778",                # hwagin — "confirmed"
    "COMPLETE": "\uc644\ub8cc",               # wallyo — "complete"
    "PASSED": "\ud1b5\uacfc",                 # tonggwa — "passed"
    "CORRECT": "\ub9de\uc74c",                # majeum — "correct"
    "ABSENT": "\uc5c6\uc74c",                 # eopseum — "none / absent"
    "NA_KO": "\ud574\ub2f9\uc5c6\uc74c",      # haedang-eopseum — "not applicable"
    "SO": "\uadf8\ub807\ub2e4",               # geureota — "that is so"
    "NOT_SO": "\uc544\ub2c8\ub2e4",           # anida — "that is not so"
    "APPLIED": "\uc801\uc6a9",                # jeogyong — "applied"
    "NORMAL": "\uc815\uc0c1",                 # jeongsang — "normal"
    "DUNNO1": "\ubaa8\ub984",                 # moreum — "don't know"
    "DUNNO2": "\ubaa8\ub974\uaca0",           # moreugess — "don't know (stem)"
    "UNCONF": "\ubbf8\ud655\uc778",           # mihwagin — "unconfirmed"
    "UNMEAS": "\ubbf8\uce21\uc815",           # micheukjeong — "unmeasured"
    "LATER1": "\ub098\uc911\uc5d0",           # najunge — "later"
    "LATER2": "\ucd94\ud6c4",                 # chuhu — "later"
    "LATER3": "\ucc28\ud6c4",                 # chahu — "later"
    "HOLD": "\ubcf4\ub958",                   # boryu — "on hold"
    "NOTMEAS1": "\uc548\u0020\uc7c0",         # an jaess — "did not measure"
    "NOTMEAS2": "\uc548\uc7c0",               # anjaess — "did not measure"
    "NOTMEAS3": "\ubabb\u0020\uc7c0",         # mot jaess — "could not measure"
    "NOTMEAS4": "\ubabb\uc7c0",               # motjaess — "could not measure"
    "NOTDONE1": "\uc548\u0020\ud568",         # an ham — "did not do"
    "NOTDONE2": "\uc548\ud568",               # anham — "did not do"
    "CATALOG": "\ub3c4\uac10",                # dogam — "catalog"
    "ANCHOR": "\uc575\ucee4",                 # aengkeo — "anchor"
    "REPRO": "\uc7ac\ud604",                  # jaehyeon — "reproduce"
    "CONVERGE": "\uc218\ub834",               # suryeom — "converge"
}

# ── Trivial vocabulary: tokens that assert nothing on their own ──────────────────
TRIVIAL = {
    "", "y", "n", "yes", "no", "ok", "okay", "na", "n/a", "nil", "none", "null",
    "pass", "fail", "true", "false", "done", "good", "yep", "yup", "sure", "fine",
    "x", "o", ".", "-", "--", "?", "!", "test", "tbd",
} | {_KO[k] for k in (
    "YES1", "YES2", "NO_", "UHUH", "DID", "DONE_", "NONE_CH", "CONFIRM", "COMPLETE",
    "PASSED", "CORRECT", "ABSENT", "NA_KO", "SO", "NOT_SO", "APPLIED", "NORMAL",
)}

# ── Deferral vocabulary: honest non-answers. True, but they cannot ground a seal ──
DEFERRAL = [
    "todo", "tbd", "later", "unknown", "unclear", "not sure", "dunno", "pending",
    "not run", "not measured",
] + [_KO[k] for k in (
    "DUNNO1", "DUNNO2", "UNCONF", "UNMEAS", "LATER1", "LATER2", "LATER3", "HOLD",
    "NOTMEAS1", "NOTMEAS2", "NOTMEAS3", "NOTMEAS4", "NOTDONE1", "NOTDONE2",
)]

MIN_DEFERRAL_CONTENT = 3    # below this, a deferral IS the answer rather than a clause in it
MIN_CONTENT_TOKENS = 2      # a real answer says at least two things
MIN_DISTINCT_CHARS = 10     # a single long token can still carry substance (unspaced Korean)
# 🔴 Do NOT measure character variety as a RATIO. Alphabets are finite, so a longer answer
#    scores lower — that ruler rejects answers for being long, which is backwards. Measured:
#    an 85-char English sentence has 26 distinct chars = 0.31 and was refused. A Korean-heavy
#    corpus cannot expose this (thousands of syllables keep the ratio high), so the sealed
#    measurement went green and an OSS regression test caught it instead.
MIN_DISTINCT_FLOOR = 5      # length-independent absolute floor

_PUNCT = re.compile(r"[\s,./·;:()\[\]{}<>\"'`~!?*_=+|\\@#$%^&—–…]+")


def extract(raw_bytes):
    """One gate line (raw bytes) -> (code, answer). Everything after the `←` hint is dropped.

    ★ Extraction lives in this file on purpose. The 2026-08-24 defect was IN THE EXTRACTOR:
      under a CP949 mis-decode the `←` was not stripped, so the hint became the body of the
      answer and a trivial "yes" arrived long enough to clear the checks. Testing the judge
      but leaving the extractor outside would put that hole back outside the tests.
    """
    body = raw_bytes.split("←".encode("utf-8"))[0]
    s = body.decode("utf-8", "replace")
    if "�" in s:
        return "DECODE_FAILED", ""
    s = re.sub(r"^-\s*\*\*[^*]+\*\*:\s*", "", s)
    return "OK", s.strip()


def _normalize(ans):
    s = unicodedata.normalize("NFKC", ans)
    s = re.sub(r"\*\*|__|`", "", s)          # markdown emphasis is not content
    return s.strip()


def _tokens(norm):
    return [t for t in _PUNCT.split(norm.lower()) if t]


def _repeated_unit(s):
    """Is the whole string one unit repeated (`abcabc`, `yesyesyes`)?"""
    t = re.sub(r"\s+", "", s)
    n = len(t)
    if n < 4:
        return False
    for unit in range(1, n // 2 + 1):
        if n % unit == 0 and t[:unit] * (n // unit) == t:
            return True
    return False


def judge(label, ans):
    """(code, detail). 'OK' passes. Field-specific branches are handled here too."""
    norm = _normalize(ans)
    low = norm.lower()

    # Catalog field: an id, or an explicit "not applicable"
    if _KO["CATALOG"] in label or re.search(r"catalog", label, re.I):
        if low in (_KO["NA_KO"], "none"):
            return "OK", "exempt"
        # An id-SHAPE test alone lets `zzz` through — the same kind of proxy as the length bar.
        # Content-token count cannot be used (a real id like `vacuous_pass` is one token), so
        # repetition and character variety are what apply.
        if not re.search(r"[A-Za-z0-9_]{3,}", norm):
            return "NEED_CATALOG", norm
        _bare = re.sub(r"\s+", "", norm)
        if _repeated_unit(norm) or (_bare and len(set(_bare)) < MIN_DISTINCT_FLOOR):
            return "NEED_CATALOG", norm
        return "OK", "catalog-id"

    # Anchor field: a number, or a seal/reproduction reference. Falls through to the general
    # test afterwards, so a bare `123456` cannot satisfy it.
    if _KO["ANCHOR"] in label or re.search(r"anchor", label, re.I):
        pat = "[0-9]|seal|anchor|reproduc|converg|hash|%s|%s|%s" % (
            _KO["REPRO"], _KO["CONVERGE"], _KO["ANCHOR"])
        if not re.search(pat, low):
            return "NEED_ANCHOR", norm

    toks = _tokens(norm)
    content = [t for t in toks if t not in TRIVIAL and not t.isspace()]

    if not content:
        return "TRIVIAL_VOCAB", norm
    # 🔴 A deferral only counts when it IS the whole answer. A deferral CLAUSE inside a
    #    reasoned answer does not remove its substance — measured: 1 of 32 real answers
    #    already sealed by this gate was wrongly refused by the naive form of this rule
    #    ("not run — the face arm is absent, so no anchor could be formed").
    if len(set(content)) < MIN_DEFERRAL_CONTENT and any(d in low for d in DEFERRAL):
        return "DEFERRAL", norm
    if _repeated_unit(norm):
        return "REPEATED_UNIT", norm

    bare = re.sub(r"\s+", "", norm)
    if bare and len(set(bare)) < MIN_DISTINCT_FLOOR:
        return "LOW_DIVERSITY", norm

    if len(set(content)) < MIN_CONTENT_TOKENS and len(set(bare)) < MIN_DISTINCT_CHARS:
        return "THIN_CONTENT", norm

    return "OK", norm


# ── Planted specimens. The gate runs these at the head of its execution path ─────
# 🔴 BIDIRECTIONAL ON PURPOSE. Plant only violations and a checker that rejects everything
#    scores full marks. Measured: sabotaging the judge to always return OK scores a PARTIAL,
#    not a zero, precisely because the genuine specimens still have to pass.
# Korean specimens are built FROM the vocabulary table above, so this file needs no raw Hangul
# and the Korean paths still get exercised on both copies.
_L_IND = "Independent angles converged"
_L_IMP = "Implementation defect ruled out"
_L_KILL = "Kill wording match"
_L_CAT_EN = "Catalog cross-check"
_L_ANC_EN = "Anchor (positive control) reproduced"

_PLANT_VIOLATIONS = [
    (_L_IND, "aaaaaa", "REPEATED_UNIT"),
    (_L_IND, "yes yes", "TRIVIAL_VOCAB"),
    (_L_IND, "yes ok", "TRIVIAL_VOCAB"),
    (_L_IMP, "aaaaaab", "LOW_DIVERSITY"),
    (_L_IMP, "qwerty", "THIN_CONTENT"),
    (_L_KILL, "TODO later", "DEFERRAL"),
    (_L_KILL, "......", "TRIVIAL_VOCAB"),
    (_L_CAT_EN, "zzz", "NEED_CATALOG"),
    (_L_CAT_EN, "aaaa", "NEED_CATALOG"),
    (_L_ANC_EN, "it just went fine", "NEED_ANCHOR"),
    # Korean paths: trivial vocabulary, one unit repeated, a bare deferral — and the two
    # Korean FIELD LABELS, which must route to the catalog/anchor branches just as the
    # English ones do (that routing is a plain substring test and would fail silently).
    (_L_IMP, _KO["CONFIRM"] + " " + _KO["COMPLETE"], "TRIVIAL_VOCAB"),
    (_L_IMP, _KO["NA_KO"] * 2, "REPEATED_UNIT"),
    (_L_KILL, _KO["DUNNO2"], "DEFERRAL"),
    (_KO["CATALOG"], "zzz", "NEED_CATALOG"),
    (_KO["ANCHOR"], "it just went fine", "NEED_ANCHOR"),
]
_PLANT_GENUINE = [
    (_L_IND, "two independent angles agreed from different evidence"),
    (_L_IMP, "code compared verbatim, the mechanism is not at fault"),
    (_L_KILL, "d=0.05 < 0.2, hits the sealed wording with no post-hoc widening"),
    (_L_CAT_EN, "vacuous_pass"),
    (_L_CAT_EN, "none"),
    (_L_ANC_EN, "anchor reproduced 3x (seal 84007e65)"),
    # 🔴 A genuine answer carrying a deferral CLAUSE must survive. The naive rule refused this
    #    shape, and it was a REAL answer this gate had already sealed.
    (_L_ANC_EN, "not run - the face arm is absent so no anchor could be formed; verdict-void"),
    # Korean genuine answers must still seal
    (_L_CAT_EN, _KO["NA_KO"]),
    (_L_ANC_EN, _KO["REPRO"] + " 3x (seal 84007e65)"),
    (_L_IND, _KO["CONVERGE"] + " over 2 seeds, code cited"),
]
# Raw-line specimens cover EXTRACTION too — a `←` hint, and a CP949-damaged line.
_HINT = _KO["REPRO"] + " " + _KO["CONVERGE"]
_RAW_OK = ("- **%s**: yes ← %s" % (_L_IND, _HINT)).encode("utf-8")
_PLANT_RAW = [
    (_RAW_OK, _L_IND, "TRIVIAL_VOCAB"),
    (_RAW_OK.decode("cp949", "replace").encode("utf-8"), _L_IND, "DECODE_FAILED"),
]


def selftest(verbose=False):
    """Run the planted specimens through this judge. Returns (passed, total, failures)."""
    fails = []
    total = 0
    for label, ans, expect in _PLANT_VIOLATIONS:
        total += 1
        code, _ = judge(label, ans)
        if code != expect:
            fails.append("violation not caught/misclassified: [%s] %r -> %s (expected %s)"
                         % (label, ans, code, expect))
    for label, ans in _PLANT_GENUINE:
        total += 1
        code, _ = judge(label, ans)
        if code != "OK":
            fails.append("genuine answer wrongly refused: [%s] %r -> %s (expected OK)"
                         % (label, ans, code))
    for raw, label, expect in _PLANT_RAW:
        total += 1
        code, ans = extract(raw)
        if code == "OK":
            code, _ = judge(label, ans)
        if code != expect:
            fails.append("raw line misclassified: %r -> %s (expected %s)" % (raw[:40], code, expect))
    if verbose:
        for f in fails:
            print("  x " + f)
    return total - len(fails), total, fails


def emit(code, ans):
    """The verdict channel. ASCII code, TAB, answer — written as UTF-8 BYTES.

    🔴 This used to be `sys.stdout.write(...)`, whose encoding is the caller's console encoding. On a
      console that is not UTF-8, echoing back an answer containing any non-ASCII character (an
      em-dash was enough) raised UnicodeEncodeError, killed the process, and left stdout EMPTY. The
      gate reads its verdict from this output and correctly refuses on empty ("an unmeasured field is
      not a passing field") — so a genuine answer was refused, on one machine and not another, and
      nothing in the refusal pointed at encoding. Measured on Windows 2026-08-25; reproduced with
      PYTHONIOENCODING=ascii. The contract is bytes, so it cannot depend on where it is being read.
    """
    sys.stdout.buffer.write((code + "\t" + ans).encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def main(argv):
    if "--selftest" in argv:
        ok, total, fails = selftest(verbose=True)
        # 🔴 Print the DENOMINATOR. A checker that measured nothing also prints green.
        # 🔴 Echo a non-ASCII answer through the real output path before declaring the checker sound.
        #    The selftest prints an ASCII-only summary, so it scored 27/27 on a machine where every
        #    real call carrying an em-dash died writing its result. A positive control that never
        #    exercises the path under test vouches for nothing.
        # 🔴 through emit(), the SAME function the real call uses. An earlier version of this
        #    control wrote the probe with sys.stdout.buffer directly — it therefore vouched for a
        #    path the product does not take, and stayed green with the defect reinstated.
        probe = "em-dash \u2014 and hangul \uac00 must survive the verdict channel"
        try:
            emit("SELFTEST_ECHO", probe)
            sys.stdout.buffer.write(b"\n")
            sys.stdout.buffer.flush()
        except Exception as e:            # pragma: no cover - the failure this exists to catch
            # 🔴 report on stderr, in pure ASCII. The first version used print(... %r) — repr of a
            #    UnicodeEncodeError contains the offending character, sent through the very channel
            #    that just failed, so the diagnostic died while reporting the fault it exists to
            #    report. A failure message must not depend on what it is reporting about.
            msg = ("substance_check selftest: FAILED to write a non-ASCII verdict: %s\n"
                   % type(e).__name__)
            sys.stderr.buffer.write(msg.encode("ascii", "replace"))
            sys.stderr.buffer.flush()
            return 9
        print("substance_check selftest: %d/%d (violations %d - genuine %d - raw %d)"
              % (ok, total, len(_PLANT_VIOLATIONS), len(_PLANT_GENUINE), len(_PLANT_RAW)))
        return 0 if not fails else 9
    label = ""
    if "--label" in argv:
        label = argv[argv.index("--label") + 1]
    code, ans = extract(sys.stdin.buffer.read())
    if code == "OK":
        code, _ = judge(label, ans)
    emit(code, ans)
    return 0 if code == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
