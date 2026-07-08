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
                    "failed_indicators": [], "summary": null },
  "trace_summary": {                                     // "어떻게 생성됐고 얼마나 안정적인지"(제품용 요약)
    "trace_id": "...",
    "generation_path": { "source": "KIS", "interpretation_source": "llm|llm_regenerated|template_fallback",
                         "template_fallback_used": false, "regen_count": 0,
                         "path_label": "normal|regenerated|template_fallback" },
    "data_quality":    { "data_status": "normal", "available_periods": ["3m","1y","5y"],
                         "intraday_available": false, "chart_count": 3, "limited": false },
    "verification_summary": { "outcome": "passed", "calc_passed": true, "regime_passed": true,
                             "label_matched": true, "failed_indicators_count": 0 },
    "stability": { "confidence": 0.42, "confidence_basis": "...", "verification_consistent": true },
    "flags": { "used_fallback": false, "had_regeneration": false, "limited_data": false,
               "verification_warning": false, "has_intraday_context": false,
               "has_daily_chart": true, "has_weekly_chart": true, "has_monthly_chart": false }
  }
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
- **verification**: 리포트 신뢰도 판단(상세) — `outcome`/`*_passed`/`regen_count`/`failed_indicators`.
- **trace_summary**: 결과 해석(summary/interpretation)과 **역할 분리** — "어떻게 생성/검증됐는지"의 제품용 요약.
  뱃지/서브패널용: `generation_path.path_label`(normal/regenerated/template_fallback)·`data_quality.limited`·
  `flags.*`(used_fallback·had_regeneration·limited_data·verification_warning·has_intraday_context·
  has_daily/weekly/monthly_chart). **raw trace/프롬프트/내부 로그는 노출하지 않는다.** `verification`(상세) ↔
  `trace_summary.verification_summary`(요약) 이중 구조. 모든 값은 저장값 projection(재해석 없음).

## Follow-up 대화 흐름 (parent report 기준)
`GET /api/technical/reports/{id}/followups` — 이 리포트에 이어진 후속 질문/답변 thread. report(분석 결과)와
followups(이어진 대화)를 **역할 분리**해 함께 준다. report detail 에는 신호용 `followup_count` 만 있고, 실제
thread 는 이 endpoint 로 받는다(스레드가 길어져도 detail payload 가 무겁지 않게).

```jsonc
{
  "report_id": "uuid",
  "stock": { "stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI" },  // canonical
  "report_summary": { "one_line_summary": "...", "directional_bias": "bullish",
                      "final_regime": "...", "as_of": "ISO8601" },   // parent 연결감
  "followup_count": 2,
  "followups": [   // created_at 오름차순(대화 순서), 0개면 []
    { "followup_id": "uuid", "request_id": "...", "question": "...", "answer": "...",
      "model_name": "...", "trace_id": "...", "created_at": "ISO8601", "answer_length": 42,
      "context": {   // raw context_snapshot 미노출 — 요약 projection(알려진 키만, 없으면 null)
        "has_context_snapshot": true, "base_report_regime": "...", "base_report_bias": "...",
        "base_report_data_status": "...", "base_report_signal_score": 0.3, "base_report_as_of": "ISO8601" } }
  ]
}
```
- **context**: `technical_report_followups.context_snapshot`(JSONB)의 raw 를 넘기지 않는다. 요약 키
  (`base_report_regime`/`bias`/`data_status`/`signal_score`/`as_of`)만 projection — snapshot 이 그 키를 담으면
  채워지고, 아니면 `has_context_snapshot` 만 true 로 두고 나머지는 `null`(tolerant). **미래 follow-up writer 는 위
  키로 snapshot 을 채우면 프론트가 base 맥락을 바로 읽는다.**
- **trace**: `trace_id`·`model_name`·`created_at` 만 제품용으로 노출(raw trace dump 아님).

### Follow-up 생성 (write)
`POST /api/technical/reports/{id}/followups` — parent report 기준 후속 질문/답변 저장. **answer 는 caller(상위/
프론트)가 생성**해 보낸다(backend 는 검증·저장·parent snapshot 만 — 본문 재생성/AI 재호출 아님).
```jsonc
// 요청
{ "question": "왜 과열인가요?", "answer": "단기 과열 신호가 관찰됩니다.",
  "client_session_id": "sess-9", "request_id": "...?", "trace_id": "...?", "model_name": "...?" }
// 응답 201 = FollowupItem (GET list item 과 동일 shape → 프론트가 thread 에 그대로 append)
```
- **404**: parent report 없음. **422**: 빈/과길이 question·answer(answer 필수).
- **메타 정책(caller 우선 + backend fallback)**: `request_id` 없으면 backend 생성(`fu-...`), `trace_id`/`model_name`
  은 caller 미제공 시 `null`(caller-provided answer 라 정직하게 null 허용).
- **context_snapshot(v1 canonical shape)**: 저장 시 parent report projection 으로 future-proof 하게 채운다 —
  `snapshot_version`·`base_report_id`·`stock_code/name/market`·`base_report_regime`·`base_report_bias`·
  `base_report_data_status`·`base_report_signal_score`·`one_line_summary`·`base_report_as_of`·`trace_path_label`·
  `verification_outcome`. **read 계약은 raw 미노출** — `_followup_context` 가 `base_report_*` 키만 요약으로 복원.
- **read-after-write**: POST 로 만든 row 는 즉시 `GET .../{id}/followups`(created_at 오름차순)에 나타난다.

## 목록 (별도 경량 인덱스)
`GET /api/reports?agent_type=technical` 은 full read model 이 아니라 **인덱스 요약**(`AgentReportListItem`:
report id·stock·question·data_status·summary 등)이다. 상세는 위 read model 로 조회한다(표준 REST: 목록=요약,
상세=full).

## 안정성 보장
- POST 201 응답 == GET 200 응답(동일 report) — shape·값 완전 동일(테스트 잠금).
- optional 필드가 비어도 키는 존재하고 `null`/`[]` 로 안정(프론트 조건분기 최소화).
- raw payload 접근이 필요하면(백오피스/디버깅) DB `technical_reports.output_payload` 를 본다 — API 표면 아님.
