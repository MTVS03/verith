# Technical Report API — 프론트 응답 계약 (정본)

`docs/technical_backend_handoff.md`

프론트가 믿고 쓰는 **technical report 응답 정본**. `POST /api/technical/reports`(저장 직후)와
`GET /api/technical/reports/{id}`(단건 조회)는 **완전히 동일한 read model** 을 반환한다(테스트로 잠금:
`test_post_and_get_return_identical_read_model`). 목록은 별도 경량 인덱스다(아래 §목록).

## 원칙
- **조회 계약 = read model ≠ 저장 형식.** DB 에는 AI output 원본(raw)이 `technical_reports.output_payload` 로
  보존되지만, **API 응답에는 raw 를 싣지 않는다.** 프론트는 raw blob 을 파싱하지 않는다.
- **backend 는 값을 재해석하지 않는다.** 모든 값은 AI 계산/저장값의 projection 이다.
- **`stock` 은 canonical `stocks` 기준**(payload 의 중복 문자열보다 우선).
- **backward-compatible.** 구버전 리포트(구조화 섹션 없음)에서도 shape 는 안정적이며 해당 필드만 `null`/`[]`.

## 응답 shape (POST 201 · GET 200 동일)

```jsonc
{
  "report_id": "uuid",
  "stock":   { "stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI" },  // canonical
  "meta":    { "request_id": "...", "trace_id": "...", "as_of": "ISO8601",
               "source": "KIS", "data_status": "normal", "model_name": null },
  "summary": { "one_line_summary": "...", "directional_bias": "bullish|neutral|bearish",
               "final_regime": "...", "daily_regime": "...", "weekly_trend": "...",
               "monthly_trend": "...", "alignment_flag": "...", "timeframe_alignment": "..." },
  "interpretation": { "text": "종합(호환/백업)", "source": "llm|llm_regenerated|template_fallback",
                      "trend_interpretation": "...", "signal_interpretation": "...",
                      "risk_interpretation": "...", "what_to_watch_next": "...",
                      "invalidation_or_caution": "..." },
  "drivers": { "key_drivers": ["..."], "warning_points": ["..."] },
  "signals": { "signal_score": 0.3, "consensus": "weak_positive", "confidence": 0.42,
               "confidence_basis": "...",
               "items": [ { "indicator": "moving_average", "signal": "positive", "value": 82900.0,
                            "metrics": ["5MA 82900"], "detail": "...", "detail_source": "llm" } ] },
  "risks":   { "items": [ { "flag": "volume_not_confirmed", "note": "...", "ref_price": null } ] },
  "charts":  { "available_periods": ["3m","1y","5y"],
               "items": [ { "period": "3m", "candle_unit": "D", "display_order": 0,
                            "has_chart_data": true, "annotation_count": 3 } ] },
  "verification": { "outcome": "passed|template_fallback", "calc_passed": true,
                    "regime_passed": true, "label_matched": true, "regen_count": 0,
                    "failed_indicators": [], "summary": null }
}
```

## 블록별 소비 가이드
- **stock**: 종목 헤더(항상 canonical). **meta**: 추적/상태 배지(trace_id·source·data_status). `model_name`
  현재 `null`(후속에 채움 가능) — 두 진입점 동일 소스.
- **summary**: 카드 헤더 한 줄 — `one_line_summary` + `directional_bias`(bullish/neutral/bearish, **AI 파생**) +
  국면/timeframe. **interpretation**: 설명 본문(섹션별). `text` 는 호환용 — 신규 화면은 structured 섹션 사용 권장.
- **drivers**: 근거 bullet(key_drivers)·경고 bullet(warning_points). **signals**: 종합 + 지표별 근거 수치.
- **risks**: 리스크 포인트(현재 확인된 위험) — `invalidation_or_caution`(해석 무효화 조건)과는 **분리**.
- **charts**: `available_periods` 로 탭 구성, item 의 `has_chart_data`/`annotation_count` 로 렌더 여부 판단.
  intraday(`1d`) 없으면 `available_periods` 에 없음(명시적으로 없음 = 없음).
- **verification**: 리포트 신뢰도 판단 — `outcome`/`*_passed`/`regen_count`/`failed_indicators`.

## 목록 (별도 경량 인덱스)
`GET /api/reports?agent_type=technical` 은 full read model 이 아니라 **인덱스 요약**(`AgentReportListItem`:
report id·stock·question·data_status·summary 등)이다. 상세는 위 read model 로 조회한다(표준 REST: 목록=요약,
상세=full).

## 안정성 보장
- POST 201 응답 == GET 200 응답(동일 report) — shape·값 완전 동일(테스트 잠금).
- optional 필드가 비어도 키는 존재하고 `null`/`[]` 로 안정(프론트 조건분기 최소화).
- raw payload 접근이 필요하면(백오피스/디버깅) DB `technical_reports.output_payload` 를 본다 — API 표면 아님.
