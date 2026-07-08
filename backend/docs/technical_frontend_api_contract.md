# Technical Report — Frontend API 계약 (정본)

`backend/docs/technical_frontend_api_contract.md`

**이 문서 하나로 프론트가 technical 화면(목록→상세→trace→follow-up)을 구현할 수 있게 하는 정본.** backend
코드/DB 를 다시 읽지 않아도 되도록, **read model(제품 계약)** 기준으로 적는다. DB 의 `output_payload`·
`context_snapshot` 등 raw/internal 저장 구조는 **계약이 아니다**(§내부 저장 구조와의 차이). 모든 값은 저장/계산된
값의 projection 이며 backend 는 LLM 내용을 재생성/재해석하지 않는다.

기준 코드: `routes/technical_reports.py` · `schemas/technical_report.py` · `services/technical_report_service.py`.

---

## 1. Endpoint 맵
| Method | Path | Body | 성공 | 실패 |
|---|---|---|---|---|
| POST | `/api/technical/reports` | `TechnicalReportCreateRequest` | 201 `TechnicalReportReadModel` | 422(입력)/502(AI 계약·불가)/504(timeout) |
| GET | `/api/technical/reports` | — (query) | 200 `TechnicalReportListResponse` | — |
| GET | `/api/technical/reports/{id}` | — | 200 `TechnicalReportReadModel` | 404 |
| DELETE | `/api/technical/reports/{id}` | — | 204 | 404 |
| GET | `/api/technical/reports/{id}/followups` | — | 200 `TechnicalReportFollowupsReadModel` | 404 |
| POST | `/api/technical/reports/{id}/followups` | `FollowupCreateRequest` | 201 `FollowupItem` | 404/422 |

> cross-agent `GET /api/reports` 는 **다른 인덱스**(agent 공통)로 별도 유지 — technical 화면은 위 6개를 쓴다.

## 2. 공통 원칙 (프론트가 믿어도 되는 것)
- **raw payload 를 파싱하지 않는다.** 응답의 구조화 블록만 소비한다.
- **stock 은 canonical** (`stocks` 기준 stock_code/stock_name/market). 저장 당시 문자열보다 우선.
- **POST 저장 직후 응답 == GET 단건 응답**(동일 report). follow-up 은 **POST 응답 item == GET list item**(동일 `FollowupItem`).
- **optional 필드가 비어도 shape 는 안정적**: 문자열은 `null`, 배열은 `[]`. 구버전/부분 데이터에서도 키는 존재.
- 목록(list)=요약, 상세(detail)=full — **목록에 charts/full interpretation/verification 상세는 없다**(§4·§5).

## 3. 목록 API — `GET /api/technical/reports`
- **query**: `stock_code?`·`client_session_id?`·`limit`(1–100, 기본 20)·`offset`(≥0). **정렬: created_at DESC(최신순).**
- **응답 `TechnicalReportListResponse`**: `items[]`·`total`(필터 기준 전체 수)·`limit`·`offset`.
- **item `TechnicalReportListItem`** 블록:
  - `stock`: `{ stock_code, stock_name?, market? }` (canonical)
  - `summary`: `{ one_line_summary?, directional_bias?, final_regime? }` (카드 헤더 한 줄 + 방향)
  - `status`: `{ data_status?, path_label, verification_warning, limited_data }` (뱃지)
  - `engagement`: `{ followup_count }` (후속 대화 뱃지)
  - `meta`: `{ as_of?, created_at?, trace_id? }` (정렬/시각)

## 4. 상세 API — `GET /api/technical/reports/{id}` (= POST create 응답)
`TechnicalReportReadModel` 블록(**raw 파싱 불필요**):
| 블록 | 필드 | 용도 |
|---|---|---|
| `report_id` | UUID | 식별 |
| `stock` | stock_code·stock_name?·market? | 종목 헤더(canonical) |
| `meta` | request_id?·trace_id?·as_of?·source?·data_status?·model_name? | 추적/상태 |
| `summary` | one_line_summary?·directional_bias?·final_regime?·daily_regime?·weekly_trend?·monthly_trend?·alignment_flag?·timeframe_alignment? | 카드 헤더·국면 |
| `interpretation` | text?·source?·trend_interpretation?·signal_interpretation?·risk_interpretation?·what_to_watch_next?·invalidation_or_caution? | 설명 본문(섹션). `text`=호환/백업, 신규 화면은 섹션 사용 |
| `drivers` | key_drivers[]·warning_points[] | 근거·경고 bullet |
| `signals` | signal_score?·consensus?·confidence?·confidence_basis?·items[] | 종합 + 지표별 근거 |
| `signals.items[]` | indicator·signal?·value?·metrics[]·detail?·detail_source? | 지표 카드 |
| `risks` | items[] `{ flag, note?, ref_price? }` | 리스크(현재 확인된 위험) |
| `charts` | available_periods[]·items[] `{ period, candle_unit?, display_order, has_chart_data, annotation_count }` | 차트 탭·렌더 여부 |
| `verification` | outcome?·calc_passed?·regime_passed?·label_matched?·regen_count?·failed_indicators[]·summary? | 검증 상세 |
| `trace_summary` | §6 | 생성/검증/품질 요약 |
| `followup_count` | int | 후속 대화 수(스레드는 §7 별도 호출) |

> `risks`(현재 확인된 위험) ↔ `interpretation.invalidation_or_caution`(해석이 틀어지는 조건)은 **분리**된 개념이다.

## 5. trace_summary 의미표 (§4 상세 응답 내)
"결과가 무엇인지"(summary/interpretation)와 **역할 분리** — "어떻게 생성/검증됐고 얼마나 안정적인지". raw trace·
프롬프트는 노출 안 함.

| 경로 | 값 | 프론트 사용 |
|---|---|---|
| `generation_path.path_label` | `normal` | 정상 생성 — 표시 없음 |
| | `regenerated` | 재생성 후 안정 — "재생성됨" 소형 뱃지 |
| | `template_fallback` | LLM 대신 템플릿 — "요약 생성" 뱃지/주의 |
| `generation_path.interpretation_source` | `llm`/`llm_regenerated`/`template_fallback` | path_label 근거(상세 툴팁) |
| `generation_path.template_fallback_used` | bool | `flags.used_fallback` 와 **같은 값**(둘 중 하나만 봐도 됨) |
| `generation_path.regen_count` | int? | 재생성 횟수 |
| `data_quality.data_status` | `normal`/`stale_cache`/`data_limited`/`regime_unavailable` | 데이터 상태 라벨 |
| `data_quality.limited` | bool | 데이터 부족 경고(=`flags.limited_data`) |
| `data_quality.available_periods` | ["3m","1y","5y",...] | 차트 탭 |
| `data_quality.intraday_available` | bool | 장중(1d) 차트 유무 |
| `data_quality.chart_count` | int | 차트 개수 |
| `verification_summary` | outcome·calc/regime/label·failed_indicators_count | 검증 요약(상세는 `verification`) |
| `stability.confidence` / `confidence_basis` | float?/str? | 신뢰도 표시 |
| `stability.verification_consistent` | bool? | calc∧regime∧label 일치 여부 |
| `flags.verification_warning` | bool | **경고 아이콘**(검증 미통과/불일치) |
| `flags.used_fallback` | bool | 템플릿 fallback 뱃지 |
| `flags.had_regeneration` | bool | 재생성 표시 |
| `flags.limited_data` | bool | 데이터 부족 경고 |
| `flags.has_intraday_context` | bool | 장중 컨텍스트 유무 |
| `flags.has_daily/weekly/monthly_chart` | bool | 타임프레임별 차트 유무 |

## 6. Follow-up API
### 6.1 read — `GET /api/technical/reports/{id}/followups`
`TechnicalReportFollowupsReadModel`: `report_id`·`stock`(canonical)·`report_summary`(one_line_summary?·
directional_bias?·final_regime?·as_of? — 스레드 헤더 연결감)·`followup_count`·`followups[]`(**created_at 오름차순
= 대화 순서**, 0개면 `[]`).

### 6.2 write — `POST /api/technical/reports/{id}/followups`
- **answer 는 caller(상위/프론트)가 생성해 보낸다.** backend 는 검증·저장·parent snapshot 만(본문 재생성/AI 재호출 아님).
- **요청 `FollowupCreateRequest`**: `question`(1–1000자, 필수)·`answer`(1–50000자, 필수)·`client_session_id?`·`request_id?`·`trace_id?`·`model_name?`.
- **응답 201 = `FollowupItem`**(GET list item 과 **동일 shape** → 프론트가 thread 에 그대로 append).
- **메타 정책**: `request_id` 없으면 backend 생성, `trace_id`/`model_name` 없으면 `null`(정직).
- **404**: parent report 없음. **422**: 빈/과길이 question·answer.

### 6.3 `FollowupItem` (read list item == POST 응답)
`followup_id`·`request_id?`·`question?`·`answer?`·`model_name?`·`trace_id?`·`created_at?`·`answer_length`·
`context`. `context`(=`FollowupContextBlock`): `has_context_snapshot`·`base_report_regime?`·`base_report_bias?`·
`base_report_data_status?`·`base_report_signal_score?`·`base_report_as_of?` — **raw context_snapshot 미노출, 요약만**.

## 7. nullable / optional / empty-state 규칙
| 필드 | 비었을 때 | 의미 |
|---|---|---|
| `key_drivers` / `warning_points` / `signals.items` / `risks.items` / `charts.items` / `followups` | `[]` | 항목 없음(키는 존재) |
| `trace_id` / `model_name` | `null` | 생성 경로가 안 남겼거나 caller 미제공(정직) |
| `interpretation.*` 섹션 / `summary.one_line_summary` / `directional_bias` | `null` | 구버전 payload(구조화 이전) — text 는 있을 수 있음 |
| `flags.has_intraday_context` / `data_quality.intraday_available` | `false` | 장중(1d) 데이터 없음 |
| `context.has_context_snapshot` | `false` | follow-up 에 parent snapshot 없음(그러면 base_report_* 도 null) |
| `context.base_report_*` | `null` | snapshot 은 있으나 해당 키 미포함(구조 tolerant) |
| `verification.failed_indicators` / `verification_summary.failed_indicators_count` | `[]` / `0` | 현재 AI 가 failed_indicators 를 미생산 → 항상 0(정상) |
| `verification.summary` | `null` | 별도 요약 텍스트 미생산 |

## 8. 상태값 의미표 (enum)
| 필드 | 허용값 |
|---|---|
| `directional_bias` | `bullish` · `neutral` · `bearish` (consensus 파생, AI 재판정 아님) |
| `path_label` | `normal` · `regenerated` · `template_fallback` |
| `data_status` | `normal` · `stale_cache` · `data_limited` · `regime_unavailable` |
| `source` | `KIS` · `KIS (stale)` |
| `interpretation.source` | `llm` · `llm_regenerated` · `template_fallback` |
| `verification.outcome` | `passed` · `template_fallback` |
| `alignment_flag` | `aligned` · `counter_trend` · `neutral` |
| `weekly/monthly_trend` | `up` · `down` · `sideways` · `unavailable` |
| `charts.items[].period` | `3m` · `1y` · `5y` · `1d` |
| `charts.items[].candle_unit` | `D` · `W` · `M` · `1min` |
| `signals.items[].indicator` | `moving_average` · `rsi` · `volume` · `support_resistance` · `pattern` |
| `signals.items[].signal` | `positive` · `neutral` · `negative` |

## 9. 사용 시나리오 (하나로 연결)
목록(`GET /reports`)에서 카드로 훑기 → `followup_count`/`status` 뱃지로 클릭 가치 판단 → 상세(`GET /{id}`)로
진입해 summary/interpretation/signals/charts + `trace_summary` 확인 → 스레드(`GET /{id}/followups`) 읽기 →
후속 질문(`POST /{id}/followups`, answer 는 상위가 생성) → 응답 `FollowupItem` 을 thread 에 append(재조회 불필요).

## 10. 예시 JSON
**목록 item** (`GET /api/technical/reports` → items[0])
```json
{ "report_id": "e2b1...", "stock": { "stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI" },
  "summary": { "one_line_summary": "과열 국면 · 종합신호 약한 긍정(보통 신뢰도)", "directional_bias": "bullish", "final_regime": "overheated" },
  "status": { "data_status": "normal", "path_label": "normal", "verification_warning": false, "limited_data": false },
  "engagement": { "followup_count": 2 },
  "meta": { "as_of": "2026-07-09T00:00:00+09:00", "created_at": "2026-07-09T00:01:00+00:00", "trace_id": "tr-1" } }
```

**상세** (`GET /api/technical/reports/{id}`, 축약)
```json
{ "report_id": "e2b1...", "stock": { "stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI" },
  "meta": { "request_id": "req-...", "trace_id": "tr-1", "as_of": "...", "source": "KIS", "data_status": "normal", "model_name": null },
  "summary": { "one_line_summary": "...", "directional_bias": "bullish", "final_regime": "overheated", "daily_regime": "overheated",
               "weekly_trend": "up", "monthly_trend": "up", "alignment_flag": "aligned", "timeframe_alignment": "상위 추세와 정합합니다." },
  "interpretation": { "text": "...", "source": "llm", "trend_interpretation": "...", "signal_interpretation": "...",
                      "risk_interpretation": "...", "what_to_watch_next": "...", "invalidation_or_caution": "..." },
  "drivers": { "key_drivers": ["이동평균 긍정"], "warning_points": ["거래량 미확인"] },
  "signals": { "signal_score": 0.3, "consensus": "weak_positive", "confidence": 0.42, "confidence_basis": "...",
               "items": [ { "indicator": "moving_average", "signal": "positive", "value": 82900.0, "metrics": ["5MA 82900"], "detail": "...", "detail_source": "llm" } ] },
  "risks": { "items": [ { "flag": "volume_not_confirmed", "note": "...", "ref_price": null } ] },
  "charts": { "available_periods": ["3m","1y","5y"], "items": [ { "period": "3m", "candle_unit": "D", "display_order": 0, "has_chart_data": true, "annotation_count": 3 } ] },
  "verification": { "outcome": "passed", "calc_passed": true, "regime_passed": true, "label_matched": true, "regen_count": 0, "failed_indicators": [], "summary": null },
  "trace_summary": { "trace_id": "tr-1",
    "generation_path": { "source": "KIS", "interpretation_source": "llm", "template_fallback_used": false, "regen_count": 0, "path_label": "normal" },
    "data_quality": { "data_status": "normal", "available_periods": ["3m","1y","5y"], "intraday_available": false, "chart_count": 3, "limited": false },
    "verification_summary": { "outcome": "passed", "calc_passed": true, "regime_passed": true, "label_matched": true, "failed_indicators_count": 0 },
    "stability": { "confidence": 0.42, "confidence_basis": "...", "verification_consistent": true },
    "flags": { "used_fallback": false, "had_regeneration": false, "limited_data": false, "verification_warning": false,
               "has_intraday_context": false, "has_daily_chart": true, "has_weekly_chart": true, "has_monthly_chart": false } },
  "followup_count": 2 }
```

**follow-up POST** (`POST /api/technical/reports/{id}/followups`)
```json
// 요청
{ "question": "왜 과열인가요?", "answer": "단기 과열 신호가 관찰됩니다.", "client_session_id": "sess-9", "model_name": "gpt-x", "trace_id": "tr-fu-1" }
// 응답 201 (= GET list item 과 동일 FollowupItem)
{ "followup_id": "f1...", "request_id": "fu-...", "question": "왜 과열인가요?", "answer": "단기 과열 신호가 관찰됩니다.",
  "model_name": "gpt-x", "trace_id": "tr-fu-1", "created_at": "2026-07-09T01:00:00+00:00", "answer_length": 15,
  "context": { "has_context_snapshot": true, "base_report_regime": "overheated", "base_report_bias": "bullish",
               "base_report_data_status": "normal", "base_report_signal_score": 0.3, "base_report_as_of": "..." } }
```

**follow-up list** (`GET /api/technical/reports/{id}/followups`)
```json
{ "report_id": "e2b1...", "stock": { "stock_code": "373220", "stock_name": "LG에너지솔루션", "market": "KOSPI" },
  "report_summary": { "one_line_summary": "...", "directional_bias": "bullish", "final_regime": "overheated", "as_of": "..." },
  "followup_count": 1, "followups": [ /* FollowupItem, created_at 오름차순 */ ] }
```

## 11. 비대상 / 내부 저장 구조와의 차이
- **내부(계약 아님)**: `technical_reports.output_payload`(AI 원본 raw), `technical_report_followups.context_snapshot`
  (raw JSONB), 정규화 자식 테이블 — 디버깅/백오피스용. 프론트는 위 read model 만 본다.
- **AI 계약**(문장 생성 규칙·검증)은 `ai/src/agents/technical/docs/contracts.md` 소관. 이 문서는 **backend→frontend
  응답 계약**만 다룬다.
- follow-up **answer 생성 주체는 backend 아님**(caller-provided). backend 는 저장/조회 계층.
