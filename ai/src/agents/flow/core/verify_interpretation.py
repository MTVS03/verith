"""게이트3 — 해석↔팩트 정합성 대조 (자연어 검증).

원리: "LLM은 확률적이라 거짓말할 수 있다 → 코드로 가둔다."
  explain 노드가 낸 해석 '문장'이 검증된 팩트(signals dict)와 어긋나지 않는지
  코드로 대조한다. 자연어 검증은 불완전하므로 '애매하면 통과(스킵)'로 설계해
  거짓 양성(멀쩡한 해석을 틀렸다고 하는 것)을 최소화한다 — 명백한 모순만 잡는다.

입력:
  interpretation : explain()이 낸 한국어 해석 문자열
  signals        : compute_signals(df) 결과 dict (팩트의 원천)
출력:
  GateResult(gate=3, passed, checks, failures)
"""

from __future__ import annotations

import re

from . import signals as sig
from ..schemas import GateResult

# 방향 어휘 사전 (부분문자열 매칭). 매수/매도 계열.
_POS_WORDS = ("순매수", "매수", "사들", "매집", "유입", "매수세")
_NEG_WORDS = ("순매도", "매도", "팔", "매도세", "유출", "이탈", "처분")
# 부정 표지 — 있으면 방향 판정을 보류(뒤집기 대신 스킵: 오탐 최소화).
_NEGATIONS = ("않", "못")
# 수급구도 관계어
_ALIGN_WORDS = ("엇갈", "동반")
# 절 분리자
_CLAUSE_SPLIT = re.compile(r"[,.·;\n]")


def _subject_windows(text: str) -> dict[str, str]:
    """문장을 주체 등장 위치로 조각내, 각 주체의 '구간' 텍스트를 모은다.

    구간 = 그 주체 언급부터 다음(다른) 주체 언급 직전까지. 한 주체가 여러 번
    나오면 구간들을 이어붙인다. 어순이 꼬이면 경계가 어긋날 수 있으나,
    방향 판정이 '애매하면 스킵'이라 그 위험을 완충한다.
    """
    occ: list[tuple[int, str]] = []
    for subject in sig.SUBJECTS:
        start = 0
        while (i := text.find(subject, start)) >= 0:
            occ.append((i, subject))
            start = i + len(subject)
    occ.sort()
    windows: dict[str, str] = {s: "" for s in sig.SUBJECTS}
    for idx, (pos, subject) in enumerate(occ):
        end = occ[idx + 1][0] if idx + 1 < len(occ) else len(text)
        windows[subject] += text[pos:end]
    return windows


def _asserted_direction(window: str) -> str | None:
    """구간 텍스트가 주장하는 방향: '매수' | '매도' | None(보류).

    부정어(않/못)가 있으면 무엇이 부정됐는지 crude 파서로는 확신 못 하므로 보류.
    매수어·매도어가 둘 다이거나 아무것도 없어도 보류. → 명백할 때만 방향 확정.
    """
    if any(neg in window for neg in _NEGATIONS):
        return None
    pos = any(w in window for w in _POS_WORDS)
    neg = any(w in window for w in _NEG_WORDS)
    if pos and not neg:
        return "매수"
    if neg and not pos:
        return "매도"
    return None


def _fact_direction(signals: dict, subject: str) -> str | None:
    """팩트의 주체 방향: ratio 부호. 양수→매수, 음수→매도, 0/None→방향 없음."""
    ratio = signals.get("strength", {}).get(subject, {}).get("ratio")
    if ratio is None or ratio == 0:
        return None
    return "매수" if ratio > 0 else "매도"


def verify_interpretation(interpretation: str, signals: dict) -> GateResult:
    """해석 문장이 팩트와 모순되지 않는지 대조한다(명백한 모순만 실패)."""
    checks: list[str] = []
    failures: list[str] = []
    text = interpretation

    # ── 규칙 1: 주체별 방향 모순 ──────────────────────────
    windows = _subject_windows(text)
    for subject in sig.SUBJECTS:
        fact_dir = _fact_direction(signals, subject)
        if fact_dir is None:
            continue                              # 팩트 방향 없음(0/None) → 대조 안 함
        asserted = _asserted_direction(windows.get(subject, ""))
        if asserted is None:
            checks.append(f"방향 정합: {subject} 문장 방향이 명백치 않아 보류(통과)")
        elif asserted == fact_dir:
            checks.append(f"방향 정합: {subject} 문장이 '{asserted}' — 팩트('{fact_dir}')와 일치")
        else:
            failures.append(
                f"방향 모순: {subject} 팩트는 '{fact_dir}'인데 문장은 '{asserted}'로 서술"
            )

    # ── 규칙 2: 수급구도 값 모순 (반대어만 있고 정답어 없을 때만 실패) ──
    alignment = signals.get("alignment")
    if alignment == "엇갈림":
        if "동반" in text and "엇갈" not in text:
            failures.append("구도 값 모순: 팩트는 '엇갈림'인데 문장은 '동반'이라 서술")
        else:
            checks.append("구도 값 정합: 팩트 '엇갈림'과 문장 서술이 모순되지 않음")
    elif alignment in ("동반매수", "동반매도"):
        if "엇갈" in text and "동반" not in text:
            failures.append(f"구도 값 모순: 팩트는 '{alignment}'인데 문장은 '엇갈림'이라 서술")
        else:
            checks.append(f"구도 값 정합: 팩트 '{alignment}'와 문장 서술이 모순되지 않음")

    # ── 규칙 3: 수급구도에 개인 오귀속 ────────────────────
    # 구도(엇갈림/동반)는 외국인·기관만의 관계. 같은 '절' 안에서 개인이
    # 관계조사(과/와/간/사이)로 묶여 구도의 당사자처럼 서술되면 실패.
    misattributed = False
    for clause in _CLAUSE_SPLIT.split(text):
        if any(kw in clause for kw in _ALIGN_WORDS) and re.search(
            r"개인[^가-힣]{0,2}(과|와|간|사이)", clause
        ):
            misattributed = True
            break
    if misattributed:
        failures.append("구도 주체 오귀속: 수급구도(외국인·기관 관계)에 개인을 당사자로 서술")
    else:
        checks.append("구도 주체 정합: 개인을 수급구도 관계의 당사자로 끌어들이지 않음")

    return GateResult(
        gate=3,
        passed=(len(failures) == 0),
        checks=checks,
        failures=failures,
    )
