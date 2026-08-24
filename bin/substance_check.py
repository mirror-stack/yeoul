#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""substance_check.py — 아크 종결 게이트의 **실질검사** 한 자리.

이 파일은 내부(apps/nacc/scripts/)와 OSS(bin/) 두 사본에 **바이트 동일**하게 놓인다.
그래서 출력은 산문이 아니라 **기계 코드**다 — 문구는 각 셸 사본이 자기 언어로 붙인다.
(드리프트를 규율이 아니라 구조로 막는다: 08-24 "수리는 양쪽, 시험은 OSS 에만" 재발 방지.)

왜 길이 검사를 버렸나
---------------------
옛 검사는 `[ ${#vans} -ge 6 ]`(6자 이상) 하나였다. 2026-08-24 실측: 회피성 답 **28종 28건
전부**가 그대로 박제됐다(`aaaaaa`·`yes yes`·`yes ok`·`ㅇㅇㅇㅇㅇㅇ`…). 길이는 실질의 대리변수라
대리변수를 만족시키는 비답이 무제한이다. ⚠️ 그렇다고 길이 바를 올리면 **진짜 짧은 답이 거절되는
반대 사고**가 난다(실측: 진짜 답 최단 42자였지만, `d=0.05 < 0.2 바 미달` 같은 18자 답은 정당하다).
⇒ 길이가 아니라 **내용**을 본다.

무엇을 거절하는가 (거절 코드)
-----------------------------
  DECODE_FAILED  UTF-8로 못 읽었다 — "판정 못 함"이지 "거부"가 아니다(둘을 뭉치면 위장된다)
  TRIVIAL_VOCAB  자명어휘만 남는다: `yes` `ok` `없음` `n/a` `.` `-` …
  DEFERRAL       정직한 비답: `모르겠다` `TODO` `나중에` `미확인` — 거짓은 아니나 봉인 근거가 못 된다
  REPEATED_UNIT  한 단위의 반복: `yesyesyes` `해당없음해당없음` `ㅁㄴㅇㄹㅁㄴㅇㄹ`
  LOW_DIVERSITY  글자 다양성 바닥: `aaaaaa` `......` `ㅇㅇㅇㅇㅇㅇ`
  THIN_CONTENT   내용토큰 2개 미만이고 글자종류도 10 미만: `qwerty` `123456`
  NEED_CATALOG   도감칸인데 catalog id 도 '해당없음'도 아니다
  NEED_ANCHOR    앵커칸인데 수치도 seal/재현 참조도 없다

🔴 이 검사는 **부류를 좁힐 뿐 닫지 못한다.** 내가 아는 회피 수법만 잡는다. 그래서 이 파일의
핵심은 위 규칙이 아니라 아래 `--selftest` 다 — 심어 둔 표본을 못 가르면 **게이트가 실제 판정을
해석하지 말고 죽는다**([[positive_control_on_instruments_too]]: 계기에도 양성대조를, 주석이 아니라
실행경로에).
"""
import re
import sys
import unicodedata

# ── 자명어휘: 그것만으로는 아무것도 주장하지 않는 토큰 ────────────────────────────
TRIVIAL = {
    "", "y", "n", "yes", "no", "ok", "okay", "na", "n/a", "nil", "none", "null",
    "pass", "fail", "true", "false", "done", "good", "yep", "yup", "sure", "fine",
    "x", "o", ".", "-", "--", "?", "!", "test", "tbd",
    "예", "네", "아니오", "응", "함", "됨", "무", "확인", "완료", "통과", "맞음", "없음",
    "해당없음", "그렇다", "아니다", "적용", "정상",
}

# ── 유예어휘: 정직한 비답. 거짓은 아니지만 봉인의 근거가 될 수 없다 ─────────────
DEFERRAL = [
    "모름", "모르겠", "모르겠다", "미확인", "미측정", "나중에", "추후", "차후", "보류",
    "todo", "tbd", "later", "unknown", "unclear", "not sure", "dunno", "pending",
    "안 쟀", "안쟀", "못 쟀", "못쟀", "안 함", "안함",
]

MIN_DEFERRAL_CONTENT = 3    # 유예어휘가 답을 지배하는지 가르는 선(절 vs 답 전체)
MIN_CONTENT_TOKENS = 2      # 실질적 답은 최소 두 가지를 말한다
MIN_DISTINCT_CHARS = 10     # 단일토큰이어도 글자종류가 넉넉하면 통과(한국어 무공백 대응)
# 🔴 글자종류를 **비율**로 재면 안 된다 — 알파벳이 유한하므로 답이 길수록 비율이 떨어진다.
#    ⇒ 긴 답일수록 거절되는 **거꾸로 된 자**였다. 실측으로 잡았다: 영어 한 문장
#    "not run — the face arm is absent ..."(85자·distinct 26 → 0.31)이 오거절됐다.
#    한국어 코퍼스는 음절 종류가 많아 이 결함을 못 드러냈다(내 표본이 한국어에 치우쳤다).
#    ⇒ 길이 무관한 **절대 하한**으로 바꾼다. 도배(`aaaaaab`)는 글자종류 자체가 바닥이다.
MIN_DISTINCT_FLOOR = 5      # 글자종류 절대 하한(길이 무관)

_PUNCT = re.compile(r"[\s,./·;:()\[\]{}<>\"'`~!?*_=+|\\@#$%^&—–…·]+")


def extract(raw_bytes):
    """게이트 한 줄(raw bytes) → (code, answer). 힌트(←) 이후는 버린다.

    ★ 추출도 이 파일 안에 둔다 — 2026-08-24 결함은 **추출부**에 있었다(CP949 에서 `←`가
      안 지워져 힌트가 답의 몸통이 됐다). 검사만 selftest 하고 추출을 밖에 두면 그 구멍이
      다시 시험 밖으로 나간다.
    """
    body = raw_bytes.split("←".encode("utf-8"))[0]
    s = body.decode("utf-8", "replace")
    if "�" in s:
        return "DECODE_FAILED", ""
    s = re.sub(r"^-\s*\*\*[^*]+\*\*:\s*", "", s)
    return "OK", s.strip()


def _normalize(ans):
    s = unicodedata.normalize("NFKC", ans)
    s = re.sub(r"\*\*|__|`", "", s)          # 마크다운 강조는 내용이 아니다
    return s.strip()


def _tokens(norm):
    return [t for t in _PUNCT.split(norm.lower()) if t]


def _repeated_unit(s):
    """문자열 전체가 한 단위의 반복인가 (`asdfasdf`, `해당없음해당없음`)."""
    t = re.sub(r"\s+", "", s)
    n = len(t)
    if n < 4:
        return False
    for unit in range(1, n // 2 + 1):
        if n % unit == 0 and t[:unit] * (n // unit) == t:
            return True
    return False


def judge(label, ans):
    """(code, detail). code == 'OK' 면 통과. 라벨별 전용칸도 여기서 함께 본다."""
    norm = _normalize(ans)
    low = norm.lower()

    # 라벨 전용칸 — 도감/앵커는 실질의 모양이 다르다(id / 수치·참조)
    if "도감" in label or re.search(r"catalog", label, re.I):
        if low in ("해당없음", "none"):
            return "OK", "exempt"
        # id 모양만 보면 `zzz` 가 통과한다 — 길이바와 **같은 부류**의 대리변수였다.
        # 내용토큰 수는 못 쓴다(진짜 id `vacuous_pass` 는 한 토큰이다) ⇒ 반복·다양성만 건다.
        if not re.search(r"[A-Za-z0-9_]{3,}", norm):
            return "NEED_CATALOG", norm
        _bare = re.sub(r"\s+", "", norm)
        if _repeated_unit(norm) or (_bare and len(set(_bare)) < MIN_DISTINCT_FLOOR):
            return "NEED_CATALOG", norm
        return "OK", "catalog-id"
    if "앵커" in label or re.search(r"anchor", label, re.I):
        if not re.search(r"[0-9]|seal|anchor|reproduc|converg|재현|수렴|앵커|hash", low):
            return "NEED_ANCHOR", norm
        # 앵커칸도 일반 실질검사를 **함께** 받는다 — 숫자 하나로 때우는 길을 막는다
        # (`123456` 이 앵커칸을 통과하던 자리)

    toks = _tokens(norm)
    content = [t for t in toks if t not in TRIVIAL and not t.isspace()]

    if not content:
        return "TRIVIAL_VOCAB", norm
    # 🔴 유예는 **답 전체가 비답일 때만** 건다. 이유·귀결을 갖춘 긴 답 안의 유예 *절* 은
    #    실질을 없애지 않는다 — 실측으로 잡았다: 박제이력 실물 32건 중 1건이 이 규칙에
    #    오거절됐다("미실행 — …측정 안 함. 얼굴 팔 부재로 앵커 자체 미구성").
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


# ── 양성대조 표본: 게이트 실행경로 맨 앞에서 매번 돌린다 ─────────────────────────
# 🔴 반드시 **양방향**이다. 위반만 심으면 "전부 거절"하는 고장난 검사가 만점을 받는다
#    (⊖ 음성만으론 못 가른다 — [[positive_control_on_instruments_too]]).
_PLANT_VIOLATIONS = [
    ("독립각도 수렴", "aaaaaa", "REPEATED_UNIT"),
    ("독립각도 수렴", "yes yes", "TRIVIAL_VOCAB"),
    ("독립각도 수렴", "yes ok", "TRIVIAL_VOCAB"),
    ("구현결함 배제", "ㅇㅇㅇㅇㅇㅇ", "REPEATED_UNIT"),
    ("구현결함 배제", "aaaaaab", "LOW_DIVERSITY"),
    ("구현결함 배제", "해당없음해당없음", "REPEATED_UNIT"),
    ("구현결함 배제", "qwerty", "THIN_CONTENT"),
    ("kill 문언 일치", "잘 모르겠다", "DEFERRAL"),
    ("kill 문언 일치", "......", "TRIVIAL_VOCAB"),
    ("도감 대조", "zzz", "NEED_CATALOG"),
    ("도감 대조", "aaaa", "NEED_CATALOG"),
    ("앵커(양성대조) 재현", "그냥 잘 됐다", "NEED_ANCHOR"),
]
_PLANT_GENUINE = [
    ("독립각도 수렴", "분석과 재현이 서로 다른 근거로 같은 결론(코드 인용 2건)"),
    ("구현결함 배제", "코드 verbatim 대조, 기제 로직 결함 아님"),
    ("kill 문언 일치", "d=0.05 < 0.2 바 미달로 봉인 문언 그대로 적중"),
    ("도감 대조", "vacuous_pass"),
    ("도감 대조", "해당없음"),
    ("앵커(양성대조) 재현", "앵커 3회 재현(seal 84007e65)"),
    # 유예 *절* 을 품은 진짜 답 — 이게 거절되면 규칙이 절과 답을 못 가른 것이다(실측 오거절 1/32)
    ("앵커(양성대조) 재현", "미실행 — 얼굴 팔 부재로 앵커 자체 미구성. 측정 안 함이 판정무효 규율에 해당"),
    # 🔴 영어 표본을 반드시 함께 심는다. 08-24: 글자종류를 비율로 재던 자가 **긴 영어 문장을**
    #    오거절했는데, 표본이 한국어뿐이라 시험이 그걸 못 봤다(OSS 회귀시험이 잡아냈다).
    ("Independent angles converged", "two independent angles agreed from different evidence"),
    ("Implementation defect ruled out",
     "not run — the face arm is absent so no anchor could be formed; recorded as verdict-void"),
    ("Kill wording match", "matches the sealed kill-condition verbatim, no post-hoc widening"),
]
# 추출부까지 덮는 표본 — 힌트(←) 가 붙은 줄, 그리고 CP949 로 손상된 줄
_PLANT_RAW = [
    ("- **독립각도 수렴**: yes ← 위 조건은 봉인 고정. 결과가 그 조건을 만족하는지만 판단".encode("utf-8"),
     "독립각도 수렴", "TRIVIAL_VOCAB"),
    ("- **독립각도 수렴**: yes ← 위 조건은 봉인 고정".encode("utf-8").decode("cp949", "replace").encode("utf-8"),
     "독립각도 수렴", "DECODE_FAILED"),
]


def selftest(verbose=False):
    """심어 둔 표본으로 검사기 자신을 잰다. (passed, total, failures)"""
    fails = []
    total = 0
    for label, ans, expect in _PLANT_VIOLATIONS:
        total += 1
        code, _ = judge(label, ans)
        if code != expect:
            fails.append(f"위반표본 미적발/오분류: [{label}] {ans!r} → {code} (기대 {expect})")
    for label, ans in _PLANT_GENUINE:
        total += 1
        code, _ = judge(label, ans)
        if code != "OK":
            fails.append(f"진짜표본 오거절: [{label}] {ans!r} → {code} (기대 OK)")
    for raw, label, expect in _PLANT_RAW:
        total += 1
        code, ans = extract(raw)
        if code == "OK":
            code, _ = judge(label, ans)
        if code != expect:
            fails.append(f"원문표본 오분류: {raw[:40]!r} → {code} (기대 {expect})")
    if verbose:
        for f in fails:
            print("  ✗ " + f)
    return total - len(fails), total, fails


def main(argv):
    if "--selftest" in argv:
        ok, total, fails = selftest(verbose=True)
        # 🔴 분모를 붙여 발화한다. `ALL OK` 단독은 아무것도 안 잰 초록과 구별되지 않는다.
        print(f"substance_check selftest: {ok}/{total}"
              f" (위반 {len(_PLANT_VIOLATIONS)} · 진짜 {len(_PLANT_GENUINE)} · 원문 {len(_PLANT_RAW)})")
        return 0 if not fails else 9
    label = ""
    if "--label" in argv:
        label = argv[argv.index("--label") + 1]
    code, ans = extract(sys.stdin.buffer.read())
    if code == "OK":
        code, _ = judge(label, ans)
    sys.stdout.write(code + "\t" + ans)
    return 0 if code == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
