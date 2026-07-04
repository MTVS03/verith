# 10. 프롬프트 계약 (Prompts)

`docs/prompts.md`

이 에이전트에서 LLM에 넘기는 입력·출력·금지 표현을 계약으로 고정한다. 다른 문서가 "코드가 무엇을 계산하는가"를 정의한다면, 이 문서는 **"LLM에게 무엇을 시키고, 무엇을 못 하게 막는가"**를 정의한다.

이 문서는 검증 ③(LLM 라벨 왜곡)의 **계약 원문**이다. 여기서 "금지"로 박은 것을 LLM이 어기면 `test_plan.md`의 검증 ③ 테스트가 잡는다. prompts와 test_plan은 짝이다 — 이쪽이 규칙, 저쪽이 그 규칙 위반의 탐지다.

> **LLM은 이 에이전트에서 3곳에만 쓰인다:** 노드 1(질문 정규화)·2(분석 포커스 정리)·10(국면 해석). 나머지 7개 노드는 결정론 코드다(`pipeline.md`). 이 문서는 그 3곳 + 재생성 변형을 다룬다.

> **프롬프트 텍스트 자원은 `prompts/*.md`에 둔다.** Prompt 1→`normalize_question.md`, Prompt 2→`focus_analysis.md`, Prompt 10→`interpret_report.md`, Prompt 10-R→`regenerate_report.md`(재생성은 별도 파일로 분리). 이 파일들을 실제로 불러 LLM에 넘기고 응답을 병합하는 **노드 어댑터는 `nodes/*.py`**(노드 10 = `nodes/interpret_report.py`)이며, 노드 10 출력 문장의 **검증 ③은 `observability/trajectory_eval.py`**(+`keyword_rules.py`)가 수행한다. **검증 실패 시 재생성 1회→template fallback으로 이어지는 루프 orchestration은 `supervisor/technical_supervisor.py`가 소유**한다(노드는 생성·검증·병합·fallback 문장 제공까지).

---

## 1. 공통 프롬프트 원칙

모든 프롬프트 맨 앞에 이 원칙을 시스템 지시로 넣는다.

1. **LLM은 투자 판단자가 아니라 해석자다.** 코드가 확정한 라벨·수치·신호를 **변경할 수 없다.**
2. **LLM은 숫자·라벨을 만들지 않는다.** 입력에 없는 가격·목표가·손절 기준·예상 수익률을 생성하지 않는다.
3. **매수/매도 프레임을 쓰지 않는다.** 사용자 노출 문구에서 "매수/매도"는 금지다(`enums.md` 사용 규약 3). 관찰·서술 톤만 쓴다.

### 금지 표현

```
- 매수하세요 / 매도하세요 / 손절하세요
- 목표가는 OOO원입니다
- 상승할 가능성이 높습니다 / 하락할 것입니다
- 이 종목을 추천합니다 / 이 전략을 추천합니다
- 지금이 진입 구간입니다 / 지금 사도 됩니다
```

### 허용 표현

```
- ~가 관찰됩니다 / ~로 해석됩니다
- ~는 참고 지점입니다
- 신호 강도는 제한적입니다
- 일부 신호가 엇갈립니다
- 상위 추세와 역행합니다 / 정합합니다
```

**원칙: 사실 서술과 관찰만. 행동 지시·미래 단정 없음.**

---

## 2. Prompt 1 — 질문 안전 정규화

**노드:** 1 · **역할:** 사용자 원문을 안전한 기술적 분석 질의로 정규화한다.

Prompt 1은 단순 요약이 아니라 **가드**다. 사용자의 위험한 표현("사도 돼?", "팔아야 해?")을 기술적 분석 프레임으로 세탁한다.

> **핵심 가드 규약:** **Prompt 1 이후의 LLM 노드는 원본 `query`를 직접 보지 않는다.** 노드 2·10에는 정규화된 문장만 흐른다. 이는 투자행동 표현이 파이프라인 내부로 반복 유입되는 것을 막기 위한 설계 가드다. 원본 `query`는 노드 1까지만 존재한다.

**입력:**
```json
{
  "ticker": "373220",
  "query": "LG에너지솔루션 지금 사도 돼?",
  "as_of": "2026-06-30T14:30:00+09:00"
}
```

**출력:**
```json
{
  "normalized_question": "LG에너지솔루션의 최근 시세·거래량·기술적 신호를 중심으로 현재 차트 국면과 리스크 관찰점을 분석합니다."
}
```

**규칙:**
- 원문의 투자행동 표현("사도 돼?" 등)을 **제거하고** 기술적 분석 관점으로 바꾼다.
- 출력은 `normalized_question` 하나만. 죽은 필드를 만들지 않는다(다음 노드가 쓰는 값만).
- 여기서 매수/매도 판단·의도를 만들지 않는다. 안전한 프레임으로의 변환만 한다.

---

## 3. Prompt 2 — 분석 포커스 정리

**노드:** 2 · **역할:** 리포트에서 어떤 관점을 더 강조할지 정리한다. **지표를 선택하지 않는다.**

> **정직성 규약:** MVP에서 5개 지표(moving_average·rsi·volume·support_resistance·pattern)는 **코드가 고정 계산**한다(`config.md` INDICATOR_WEIGHTS). LLM은 지표를 고르는 게 아니라 **설명 강조 관점**만 정리한다. "전략 선택"이 아니라 "포커스 정리"인 이유다. 실제 지표 계산 여부·가중치는 전부 코드/config가 결정한다.

**입력:** (Prompt 1의 출력만 받는다. 원본 query 없음.)
```json
{
  "ticker": "373220",
  "normalized_question": "LG에너지솔루션의 최근 시세·거래량·기술적 신호를 중심으로 현재 차트 국면과 리스크 관찰점을 분석합니다."
}
```

**출력:**
```json
{
  "analysis_focus": ["trend", "momentum", "volume", "support_resistance", "risk"],
  "focus_summary": "최근 차트 국면을 보기 위해 추세·모멘텀·거래량·지지저항·리스크 관찰점을 함께 확인합니다."
}
```

**규칙:**
- `analysis_focus`는 **설명 강조 관점**이지 계산 대상 선택이 아니다. 5개 지표는 기본적으로 모두 계산한다. 단, 데이터 부족으로 특정 지표 계산이 불가능한 경우에는 코드가 해당 지표를 제외하고 남은 지표로 가중치를 재정규화한다. 이 제외 여부도 LLM이 아니라 코드가 결정한다.
- 신호 판정·수치를 만들지 않는다.
- Future Work: 지표 동적 선택(실제 사용 로그 확보 후).

---

## 4. Prompt 10 — 국면 해석·리포트

**노드:** 10 · **역할:** 코드가 확정한 라벨·수치를 자연어 문장으로 푼다. **이 문서의 핵심.**

Prompt 10은 이미 확정된 값을 **입력으로 받아 문장만 반환**한다. LLM은 확정값을 손대지 않는다.

**입력:** (전부 코드가 이미 확정한 값 — 아래는 축약 예시로, 정상 리포트에서는 기본 5개 지표가 들어가며 데이터 부족 시 계산 가능한 지표만 들어갈 수 있다)
```json
{
  "daily_regime": "overheated",
  "final_regime": "overheated",
  "weekly_trend": "up",
  "monthly_trend": "up",
  "alignment_flag": "neutral",
  "regime_context": "상위 추세는 상승이나 일봉 기준 단기 과열이 관찰됩니다.",
  "consensus": "weak_positive",
  "signal_score": 0.30,
  "confidence": 0.42,
  "confidence_basis": "5개 지표 중 긍정 2·중립 2·부정 1로 일부 신호가 엇갈립니다.",
  "technical_signals": [
    { "indicator": "moving_average", "signal": "positive", "value": 82900, "metrics": ["5MA 82,900", "20MA 81,400", "60MA 80,600"] },
    { "indicator": "rsi", "signal": "neutral", "value": 58.2, "metrics": ["RSI(14) 58.2", "기준 35 / 70"] }
  ],
  "risk_items": [
    { "flag": "volume_not_confirmed", "note": "거래량 확인이 약해 현재 신호의 강도는 제한적입니다." }
  ]
}
```

> `daily_regime`·`weekly_trend`·`monthly_trend`·`alignment_flag`를 입력에 명시하는 이유: LLM은 라벨을 만들지 않지만, 코드가 확정한 멀티프레임 맥락을 문장으로 풀려면 이 값들이 입력에 있어야 한다. 특히 검증 ③은 `alignment_flag=counter_trend`인데 해석이 역행 맥락을 누락하면 실패시키므로, LLM이 `regime_context`만 보고 추론하게 두지 않고 `alignment_flag`를 직접 준다.

**출력:** (문장만. 확정 필드를 되돌려주지 않는다.)
```json
{
  "interpretation_text": "현재 차트는 상위 추세가 상승인 가운데 일봉 기준 단기 과열 신호가 관찰됩니다. 다만 거래량 확인이 약하고 일부 신호가 엇갈려 신호 강도는 제한적으로 해석됩니다.",
  "details": [
    { "indicator": "moving_average", "detail": "20일선이 60일선을 상향 돌파해 이동평균선 기준으로는 긍정 신호가 관찰됩니다." },
    { "indicator": "rsi", "detail": "RSI는 58.2로 과매수·과매도 어느 쪽도 아닌 중립 구간입니다." }
  ]
}
```

### 4.1 LLM이 절대 반환하면 안 되는 필드

LLM 출력에 아래가 들어오면 **검증 ③ 실패**로 처리한다. LLM은 문장(`interpretation_text`·`details[].detail`)만 반환한다.

```
final_regime · consensus · signal_score · confidence · confidence_basis
signal · value · metrics · weight · risk flag
```

이 필드들은 코드 확정값이며, 시스템이 이미 갖고 있다. LLM이 이걸 다시 반환하면 "확정값을 재생성하려 한다"는 신호이므로 차단한다.

### 4.2 details 병합 안전장치

시스템이 LLM 출력을 코드 확정 JSON에 병합한다.

- `interpretation_text` → `interpretation.text`에 삽입
- `details[].detail` → 같은 `indicator`를 가진 `technical_signals[].detail`에 삽입
- `detail_source`·`interpretation.source` → 검증 결과에 따라 **시스템이** `llm`/`llm_regenerated`/`template_fallback` 부여 (LLM이 정하지 않음)

**병합이 깨지지 않도록, LLM 출력 `details`는 반드시:**
1. **입력으로 준 `technical_signals`와 같은 개수**여야 한다(5개 주면 5개).
2. **각 `indicator`는 입력에 있던 코드값과 정확히 일치**해야 한다. `ma`·`movingAvg`·`macd`·`trend`처럼 없는 값을 만들면 실패.
3. 순서는 무관하나, indicator로 짝짓는다.

**하나라도 어기면 검증 ③ 실패 → 재생성.** (index 짝짓기 버그를 막는 규약이며, contracts에서 risk를 `items[]`로 묶은 것과 같은 방어다.)

### 4.3 왜곡 금지 규칙

- `final_regime`을 다른 국면으로 바꿔 서술하지 않는다. (`overheated`인데 "상승 추세"로 쓰면 왜곡)
- `consensus`를 뒤집지 않는다. (`weak_positive`인데 "부정적"으로 쓰면 왜곡)
- `signal=positive`인 지표를 부정 뉘앙스로 설명하지 않는다.
- `regime_context`가 담은 상위 추세 맥락을 누락하지 않는다.
- 새로운 수치·가격·목표가를 만들지 않는다.

---

## 5. Prompt 10-R — 라벨 왜곡 재생성

**노드:** 10(재생성 루프) · **파일:** `prompts/regenerate_report.md`(Prompt 10과 별도 자원) · **역할:** 검증 ③ 실패 시 확정 라벨을 강제 주입해 문장만 다시 생성한다.

> **책임 경계:** **10-R은 재생성 프롬프트(문장 생성)만 정의한다. 통과/실패 판정은 LLM이 하지 않는다 — 검증 ③ 코드(`observability/trajectory_eval.py`)가 한다.** 그리고 "1차 실패 → 10-R로 재생성 → 재검증 → 최종 fallback"으로 이어지는 **루프 실행 자체는 `supervisor/technical_supervisor.py`가 소유**한다(`nodes/interpret_report.py`는 1회 생성·검증·병합·fallback 문장 제공까지). LLM에게 "이번엔 맞게 썼는지 스스로 판단해봐"라고 시키지 않는다. 프롬프트(문장 생성)와 검증(코드 판정)의 책임을 섞지 않는다.

**흐름:**
```
Prompt 10 출력 → 검증 ③ 코드 검사 → 실패
  → Prompt 10-R로 1회 재생성 → 검증 ③ 코드 재검사
    → 통과 → detail_source/interpretation.source = "llm_regenerated"
    → 또 실패 → template_fallback (LLM 문장 버리고 코드 템플릿 문장)
```

재생성은 **1회만**(`config.md` REGEN_MAX_COUNT = 1). 무한 루프가 구조적으로 불가능하다.

**추가 시스템 지시 (본 Prompt 10에 덧붙임):**
```
직전 출력이 코드 확정 라벨과 불일치했습니다.
아래 확정값을 반드시 그대로 반영하고, 절대 바꾸지 마세요.
- 확정 final_regime: "{final_regime}"
- 확정 consensus: "{consensus}"
- 확정 alignment_flag: "{alignment_flag}"
- (지표별) 확정 signal: moving_average=positive, rsi=neutral, ...

위 값을 바꾸지 말고 문장만 다시 작성하세요.
새로운 라벨·수치·매수/매도 표현을 만들지 마세요.
```

**재생성 출력 형식은 본 Prompt 10과 동일:**
```json
{ "interpretation_text": "...", "details": [ { "indicator": "...", "detail": "..." } ] }
```

---

## 6. 프롬프트 규약

1. **공통 원칙을 모든 프롬프트 앞에 넣는다.** 금지 표현은 예외 없이 적용.
2. **원본 query는 노드 1까지만.** 이후 노드는 `normalized_question`만 본다(안전 가드).
3. **LLM은 문장만 반환한다.** 확정 라벨·수치를 되돌려주지 않는다(4.1 금지 필드).
4. **details는 입력 지표와 개수·코드값 일치.** 병합 안전장치(4.2).
5. **재생성은 프롬프트, 판정은 코드.** 10-R은 문장만 다시 만들고 통과 여부는 검증 ③이 정한다.
6. **변경 시** 이 문서 → `contracts.md`(출력 구조) → `test_plan.md`(검증 케이스) 순으로 반영.

---

## 관련 문서

| 문서 | 담당 |
| --- | --- |
| `contracts.md` | 출력 JSON 구조 (`technical_signals[].detail`·`interpretation`) |
| `enums.md` | 금지어 규약, `detail_source`·`interpretation_source` 값 |
| `test_plan.md` | 이 문서의 금지 규칙을 어겼을 때의 검증 케이스 (검증 ③) |
| `usecase.md` | T6 (LLM 라벨 왜곡 → 재생성 → 폴백 시나리오) |
| `pipeline.md` | LLM 3곳의 파이프라인 위치 |
