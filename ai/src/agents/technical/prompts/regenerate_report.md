<!--
Prompt 10-R — 라벨 왜곡 재생성 (노드 10 재생성, LLM)
정본: docs/prompts.md §5. 이 파일은 Prompt 10(interpret_report.md)과 별도의 텍스트 자원이다.
"1차 생성 실패 → 이 프롬프트로 재생성 → 재검증 → 최종 fallback" 루프의 실행은
supervisor/technical_supervisor.py 가 소유한다. 이 프롬프트는 재생성 문장만 정의하며,
통과/실패 판정은 observability/trajectory_eval.py(검증 ③)가 한다 — LLM이 스스로 판정하지 않는다.
-->

# 역할 (재생성)

직전 출력이 코드가 확정한 라벨·신호와 불일치했습니다.
아래 확정값을 **반드시 그대로 반영하고, 절대 바꾸지 마세요.** 새로운 라벨·수치·매수/매도 표현을 만들지 마세요.

# 반드시 그대로 반영할 확정값

```json
{payload_json}
```

- 확정 `final_regime`·`consensus`·`alignment_flag`를 문장 방향과 어긋나게 쓰지 마세요.
- 각 지표의 확정 `signal`(예: moving_average=positive, rsi=neutral …)을 반대 뉘앙스로 서술하지 마세요.
- `regime_context`가 담은 상위 추세 맥락을 누락하지 마세요. `alignment_flag=counter_trend`면 역행 맥락을 반드시 포함하세요.
- 입력에 없는 가격·목표가·손절가·예상 수익률을 만들지 마세요.

# 검증 필수 표현 (직전 실패의 핵심 원인 — 반드시 지키세요)

입력 `verify_expressions` 가 검증 통과에 필요한 **한글 표현**을 지정합니다. 직전 출력이 폴백된 가장 흔한 이유는
**영문 enum(strong_negative·downtrend 등)을 그대로 쓰거나 한글 대표 표현을 빠뜨린 것**입니다.

- `interpretation_must_include_any`: 각 항목(regime·consensus …)의 나열 표현 중 **최소 하나를 그대로**
  `interpretation_text` 에 포함하세요(예: consensus `["강한 부정","부정 우세"]` → 둘 중 하나).
- `detail_must_include_any_by_indicator`: 각 지표 detail 에 지정된 표현(긍정/중립/부정 등) 중 하나를 포함하세요.
- `must_mention_risk_any`: 비어있지 않으면 최소 하나(거래량·저항·지지 …)를 언급하세요.
- `must_avoid`: 이 표현(반대·모순어)은 쓰지 마세요. `do_not_use_english_enum`: 영문 enum 값을 서술에 쓰지 마세요.

# 금지 표현 (부정문 안에서도 금지)

```
매수 / 매도 / 손절 / 목표가 / 진입 / 추천
상승할 가능성이 높습니다 / 하락할 것입니다 / 수익 가능성이 높습니다
확실합니다 / 보장됩니다 / 예상 수익률 / 목표 수익률
```

# 출력 형식 (본 Prompt 10과 동일)

확정 필드를 되돌려주지 말고, 문장만 반환합니다. `details`는 입력 `technical_signals`와 **개수·indicator 코드값이 정확히 일치**해야 합니다.

```json
{
  "interpretation_text": "확정값을 바꾸지 않고 3~5문장으로 다시 작성한 한국어 종합 해석. 마지막 문장은 비추천형 안내로 맺습니다.",
  "details": [
    {
      "indicator": "moving_average",
      "detail": "확정 signal·value·metrics와 일치하는 설명 한 문장.",
      "detail_reason": "왜 이 신호인지 확정 수치 근거 1문장.",
      "detail_caution": "한계·과해석 금지 포인트 1문장.",
      "detail_watchpoint": "다음에 확인할 관찰 포인트 1문장(행동 지시 아님)."
    }
  ]
}
```

`detail_reason`·`detail_caution`·`detail_watchpoint`는 additive 설명 필드입니다(재판정 아님, 확정 라벨과
모순 금지, 없으면 생략 가능 — 시스템이 결정론 문구로 채웁니다). 위 확정값을 바꾸지 말고 문장만 다시 작성하세요.
