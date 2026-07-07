# 13. Trace 스키마 (Trace Schema)

`docs/trace_schema.md`

가격/기술적 분석 에이전트의 실행 과정에서 남기는 trace 로그 구조를 정의한다. 이 문서는 최종 리포트 DB 스키마가 아니라, **노드별 입력·출력·계산·검증·예외·폴백을 추적하기 위한 관측 스키마**다.

> **구현 상태(MVP — `feat/technical-trace-logger`):** 이 스키마는 `observability/trace_logger.py`(`TraceLogger`+`TraceSink`: Noop/InMemory/JSONL)로 구현됐고, `supervisor/technical_supervisor.py`·`agent.py`에 `trace_sink` **주입식**으로 배선됐다. **MVP 범위** — run/node/cache/KIS/LLM validation/retry/fallback 핵심 이벤트를 우선 지원하며, 이 문서의 **전체 상세 필드(§9의 지표별 값·date range·confidence components 등)는 후속 AI endpoint/production 통합 단계에서 확장**한다.
>
> - **허용 event_type enum: 8종**(§7). **현재 실제 emit: 7종**(`trace_start·trace_end·node_start·node_end·validation·retry·fallback`). `error`는 독립 이벤트로도 허용되지만 MVP에서는 `node_end`/`trace_end`의 `status=failed`+`error` 필드 중심으로 기록한다. 세부(cache_hit·stale·재생성 등)는 `node`+event_type+summary 조합으로 표현한다.
> - **secret-safe(§10·§13) 2겹:** ① key 이름 redaction ② **값-패턴 스크럽**(sk-·Bearer·URL credential·JWT·`k=v` secret·긴 고엔트로피 토큰) — key가 무해해도 값 자체가 secret 형태면 가린다. 단 `trace_id`·`event_id`·`*_hash`는 긴 토큰 redaction에서 면제(식별자 정합성). 원문 query는 `original_query_hash`(salt 없는 sha256)만, LLM prompt/response·시세/annotation 배열·API key/token은 미기록. error(예외/dict/str)는 모두 정화 경로를 거친다.
> - **동작 보장:** trace emit 실패는 흡수해 계산·판단 로직에 영향이 없다. sink 미주입(Noop)이면 **출력 결과는 불변**이고 timestamp/hash/wrapper 생성 등 경미한 관측 오버헤드만 있다. **운영 sink 인스턴스 생성·JSONL 파일 경로·config 결선은 AI endpoint 통합 단계로 이연**한다.

---

## 1. 문서 목적

1. 한 번의 분석 실행이 어떤 노드 흐름을 거쳤는지 기록한다.
2. 코드가 확정한 라벨·수치·신호의 근거를 추적한다.
3. LLM 출력이 코드 확정값을 왜곡하지 않았는지 검증 기록을 남긴다.
4. KIS 장애·캐시 폴백·데이터 부족·재생성·템플릿 폴백 같은 예외 흐름을 기록한다.
5. 테스트 실패나 리포트 이상 발생 시 원인을 역추적할 수 있게 한다.

> trace는 사용자에게 보여주는 리포트가 아니다. 개발·검증·디버깅을 위한 실행 기록이다.

---

## 2. schema.md와의 차이

| 문서 | 저장 대상 | 목적 |
| --- | --- | --- |
| `schema.md` | 최종 리포트 결과 | backend 저장·조회 API 기준 |
| `trace_schema.md` | 실행 과정 로그 | 디버깅·검증·재현성 확인 |

`schema.md`는 **"무엇이 최종 결과로 저장되는가"**를 정의하고, `trace_schema.md`는 **"그 결과가 어떻게 만들어졌는가"**를 정의한다. 최종 리포트 JSON은 `contracts.md`에 정의되어 있으며, 판단 불가 시에도 `interpretation`은 null이 아니라 `template_fallback` 문장으로 안전 착지한다.

---

## 3. Trace 식별자 규칙

| 필드 | 설명 | 저장 위치 |
| --- | --- | --- |
| `request_id` | Top Supervisor가 넘긴 외부 요청 ID | trace 로그에는 기록 가능, 리포트 DB에는 저장하지 않음 |
| `trace_id` | 가격/기술 에이전트 내부 실행 추적 ID | trace 로그와 최종 리포트 DB에 모두 기록 |
| `node_run_id` | 노드 1회 실행 단위 ID | trace 로그에만 기록 |

`trace_id`는 **Technical Supervisor 진입 시 생성**된다. 생성된 `trace_id`는 모든 trace event에 동일하게 부여되며, 최종 리포트의 `technical_reports.trace_id`에도 같은 값으로 저장된다. 이로써 "실행 로그 ↔ 저장된 리포트"가 하나의 ID로 이어진다.

`request_id`는 Top Supervisor가 넘긴 런타임 요청 ID이고, `trace_id`는 에이전트 내부 실행 추적 ID다. 영구 리포트 추적은 `trace_id`를 기준으로 한다(`schema.md` §12와 일치 — request_id는 DB 미저장).

---

## 4. Trace 저장 방식

MVP에서는 trace를 PostgreSQL 정규 테이블로 만들지 않는다. 실행 로그 또는 JSONL 형태로 저장하고, 최종 요약만 `report_verification`과 `technical_reports.trace_id`에 남긴다.

Trace Summary는 실행 시작 시 `status=running`으로 생성되고, 실행 종료 시 `completed`·`failed`·`fallback` 중 하나로 갱신된다. 이벤트 로그는 append-only로 기록한다.

| 방식 | MVP 사용 여부 | 설명 |
| --- | --- | --- |
| JSONL event log | 사용 | 노드별 이벤트를 append-only로 기록 |
| Trace Summary | 사용 | 실행 시작 시 running, 종료 시 최종 상태로 갱신 |
| PostgreSQL trace table | Future Work | 운영 조회가 필요할 때 확장 |
| LangSmith/OpenTelemetry | Future Work | 외부 관측 도구 연동 시 |

> trace는 상세 실행 기록이고, PostgreSQL의 `technical_reports`는 최종 리포트 저장소다. 둘을 섞지 않는다.

---

## 5. Trace Summary 스키마

하나의 분석 실행은 하나의 `trace_id`를 가진다. Summary는 실행 전체의 최종 상태를 요약한다.

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `trace_id` | string | YES | 에이전트 실행 추적 ID |
| `request_id` | string | YES | Top Supervisor 요청 ID |
| `ticker` | string | YES | 종목 코드 |
| `as_of` | ISO8601 | YES | 분석 기준 시각 |
| `status` | string | YES | running/completed/failed/fallback |
| `data_status` | string | YES | normal/stale_cache/data_limited/regime_unavailable |
| `final_regime` | string | NO | 최종 국면 |
| `outcome` | string | NO | passed/regenerated/template_fallback/failed |
| `regen_count` | int | YES | LLM 재생성 횟수 (trace 시작 시 0으로 초기화) |
| `started_at` | ISO8601 | YES | trace 시작 시각 |
| `ended_at` | ISO8601 | NO | trace 종료 시각 |

**status 값 의미:**

| status | 의미 |
| --- | --- |
| `running` | 실행 중 |
| `completed` | 정상 완료 |
| `failed` | 복구 불가능한 실패 |
| `fallback` | 예외가 있었지만 안전한 폴백 결과 반환 |

`running`은 실행 중 상태와 stuck trace를 추적하기 위해 둔다. 일정 시간 이상 `running`에서 갱신되지 않으면 KIS 호출·LLM 호출·서버 재시작 등으로 중단된 실행으로 볼 수 있다.

`regen_count`는 trace 시작 시 `0`으로 초기화하고, LLM 재생성 발생 시 증가시킨다(최대 `REGEN_MAX_COUNT=1`). schema의 `report_verification.regen_count`(NOT NULL DEFAULT 0)와 일관된다 — 실행 로그와 최종 저장 모두 null이 아니라 0에서 시작한다.

---

## 6. 값 재사용 규칙

trace에서 쓰는 값 중 일부는 기존 문서의 enum을 그대로 재사용한다. 같은 의미의 값을 trace 전용으로 새로 만들지 않는다.

**재사용 (기존 문서 기준):**

| 값 | 기준 문서 | 허용값 |
| --- | --- | --- |
| `data_status` | contracts / schema / enums | normal, stale_cache, data_limited, regime_unavailable |
| `outcome` | schema / test_plan | passed, regenerated, template_fallback, failed |
| `interpretation_source` | contracts / schema | llm, llm_regenerated, template_fallback |
| `detail_source` | contracts / schema | llm, llm_regenerated, template_fallback |
| `final_regime` | enums | overheated, oversold_rebound_watch, bullish_reversal_watch, uptrend_intact, downtrend, sideways, unavailable |

**trace 전용 (새로 정의):**

| 필드 | 허용값 |
| --- | --- |
| `summary.status` | running, completed, failed, fallback |
| `event_type` | trace_start, trace_end, node_start, node_end, validation, retry, fallback, error |
| `event.status` | success, failed, skipped |

---

## 7. Event 공통 스키마

모든 노드·검증·예외 이벤트는 공통 필드를 가진다.

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `event_id` | string | YES | 이벤트 ID |
| `trace_id` | string | YES | trace ID |
| `node_run_id` | string | NO | 노드 실행 단위 ID |
| `node` | string | NO | 발생 노드 코드값 (§8) |
| `event_type` | string | YES | trace_start/trace_end/node_start/node_end/validation/retry/fallback/error |
| `status` | string | YES | success/failed/skipped |
| `started_at` | ISO8601 | YES | 시작 시각 |
| `ended_at` | ISO8601 | NO | 종료 시각 |
| `duration_ms` | int | NO | 수행 시간 |
| `input_summary` | object | YES | 입력 요약 |
| `output_summary` | object | YES | 출력 요약 |
| `error` | object/null | YES | 에러 정보 |

> **로그 축약 원칙:** trace에는 전체 원천 OHLCV 배열이나 LLM 원문 전체를 무제한 저장하지 않는다. 필요한 경우 요약·hash·count·일부 샘플만 저장한다(§13).

`trace_start`·`trace_end`는 trace 자체의 시작/끝을 표시하는 이벤트로, 특정 노드에 속하지 않으므로 `node`가 없을 수 있다(그래서 `node`는 NO).

---

## 8. 노드 코드값

`node` 필드에는 한글 이름이 아니라 **영문 snake_case 코드값**을 저장한다. 한글 이름은 문서 설명용 라벨이다.

| 번호 | 한글 이름 | trace node 코드값 |
| --- | --- | --- |
| 1 | 질문 안전 정규화 | `normalize_question` |
| 2 | 분석 포커스 정리 | `focus_analysis` |
| 3 | 데이터수집 | `data_collect` |
| 4 | 신호용 지표계산(signal_score용 bundle) | `indicator_calculate` |
| 5 | 국면분류(OHLCV 선판정·gate) | `regime_classify` |
| 6 | 신호종합 | `signal_aggregate` |

> **실행 순서 주의:** 노드 번호는 안정 ID이지만, **실제 실행은 국면분류(5·gate)가 지표계산(4)보다 먼저**다(`architecture.md` §10노드). regime은 지표 bundle을 쓰지 않는 OHLCV 선판정이고, indicator는 그 뒤 signal_score용 bundle이다.
| 7 | 신뢰도계산 | `confidence_calculate` |
| 8 | 리스크관찰점 | `risk_detect` |
| 9 | 차트생성 | `chart_generate` |
| 10 | 국면해석·리포트 | `interpret_report` |

---

## 9. 노드별 Trace 기록 항목

| node | 기록할 핵심 |
| --- | --- |
| `normalize_question` | original_query_hash, normalized_question |
| `focus_analysis` | analysis_focus, focus_summary |
| `data_collect` | cache_hit_by_period, kis_call_by_period, retry_count_by_period, data_status |
| `indicator_calculate` | bar_count_by_period, date_range_by_period, calculated_indicators, indicator_status |
| `regime_classify` | daily_regime, weekly_trend, monthly_trend, alignment_flag, final_regime, regime_context |
| `signal_aggregate` | indicator signals, weights, signal_score, consensus |
| `confidence_calculate` | confidence, confidence_basis, confidence components |
| `risk_detect` | risk_flags, ref_price 여부 |
| `chart_generate` | chart periods, chart_data size, generated_annotations, skipped_annotations (chart_annotation_spec §18) |
| `interpret_report` | interpretation_source, detail_source_counts, validation result |

### 9.1 skipped 기록 규칙

`regime_unavailable`이 발생하면 국면분류(노드 5·gate) 뒤로는 **노드 4(`indicator_calculate`)·6(`signal_aggregate`)·7(`confidence_calculate`)·8(`risk_detect`)을 실행하지 않고** 각각 **`status=skipped` 이벤트를 남긴다.** 국면분류(5·gate)를 신호용 지표계산(4)보다 먼저 실행하므로 지표계산도 스킵된다(`architecture.md` §10노드 — regime은 gate, indicator는 signal_score용 bundle). 신뢰도·리스크는 regime 결과에 의존하므로 어차피 실행 불가다. 이벤트를 생략하지 않는다 — 생략하면 "왜 지표·신호·신뢰도·리스크가 없었는지"를 trace에서 확인할 수 없기 때문이다.

```json
{
  "event_id": "evt_006",
  "trace_id": "trace_xyz789",
  "node": "signal_aggregate",
  "event_type": "node_end",
  "status": "skipped",
  "started_at": "2026-06-30T14:30:04+09:00",
  "ended_at": "2026-06-30T14:30:04+09:00",
  "duration_ms": 0,
  "input_summary": { "final_regime": "unavailable", "data_status": "regime_unavailable" },
  "output_summary": { "reason": "regime_unavailable", "message": "final_regime=unavailable이므로 신호 종합을 수행하지 않습니다." },
  "error": null
}
```

---

## 10. Query 로그 규칙

원본 query는 trace에 **평문으로 저장하지 않는다.** `original_query_hash`만 기록한다. Node 1이 생성한 `normalized_question`은 안전 정규화가 끝난 문장이므로 평문 저장할 수 있다.

> 이는 원본 질의의 위험 표현이 Node 1 이후 파이프라인에 흐르지 않는다는 `prompts.md`의 안전 경계를 **로그 레벨에서도 유지**하기 위함이다. "사도 돼?" 같은 표현이 로그에 박제되지 않는다.

```json
{
  "node": "normalize_question",
  "event_type": "node_end",
  "status": "success",
  "input_summary": { "original_query_hash": "sha256:8f3a..." },
  "output_summary": { "normalized_question": "LG에너지솔루션의 최근 시세·거래량·기술적 신호를 중심으로 현재 차트 국면과 리스크 관찰점을 분석합니다." },
  "error": null
}
```

---

## 11. 검증 Trace 스키마

검증 이벤트는 `event_type=validation`으로 기록한다.

| 검증 | 기록 항목 |
| --- | --- |
| 검증 ① 계산 정확성 | calc_passed, failed_indicator, expected/actual 요약 |
| 검증 ② regime 규칙 | regime_passed, rule_id, matched_condition, final_regime |
| 검증 ③ LLM 라벨 왜곡 | label_matched, failed_reason, regen_count, final_source |

**검증 ③ 예시** (test_plan의 LLM-*·DETAIL-* 케이스와 이어진다):

```json
{
  "event_id": "evt_val_003",
  "trace_id": "trace_xyz789",
  "node": "interpret_report",
  "event_type": "validation",
  "status": "failed",
  "started_at": "2026-06-30T14:30:07+09:00",
  "ended_at": "2026-06-30T14:30:07+09:00",
  "duration_ms": 12,
  "input_summary": { "final_regime": "sideways", "consensus": "neutral", "alignment_flag": "neutral" },
  "output_summary": {
    "validation_type": "label_distortion",
    "label_matched": false,
    "failed_targets": [
      { "target": "interpretation.text", "reason": "regime_conflict", "expected_regime": "sideways", "conflict_term": "상승 전환" },
      { "target": "technical_signals[1].detail", "indicator": "rsi", "reason": "signal_mismatch", "expected_signal": "neutral" }
    ],
    "regen_count": 1,
    "final_action": "template_fallback"
  },
  "error": null
}
```

`failed_targets[]`는 종합 해석(`interpretation.text`)과 지표별 detail(`technical_signals[n].detail`)을 각각 어느 이유로 실패했는지 담는다 — test_plan §5.3의 판정 규칙(regime_conflict·signal_mismatch·forbidden_term 등)과 대응한다.

---

## 12. 재시도·폴백 Trace 스키마

| 상황 | event_type | 기록 |
| --- | --- | --- |
| KIS 실패 | retry | period(D/W/M), attempt, max_attempts, backoff_sec, error_code |
| stale cache 사용 | fallback | period, cache_key, fallback_type=stale_cache, cache_age_days, stale_limit_days |
| W/M 미확보 | fallback | period(W/M), fallback_type=data_limited, trend=unavailable, reason |
| 데이터 부족 | fallback | fallback_type=regime_unavailable, bar_count_by_period, required_bars, reason |
| LLM 재생성 | retry | target=interpretation/detail, regen_count |
| 템플릿 폴백 | fallback | fallback_type=template_fallback, failed_reason |

```json
{
  "event_id": "evt_retry_001",
  "trace_id": "trace_xyz789",
  "node": "data_collect",
  "event_type": "retry",
  "status": "failed",
  "started_at": "2026-06-30T14:30:02+09:00",
  "ended_at": "2026-06-30T14:30:03+09:00",
  "duration_ms": 1000,
  "input_summary": { "period": "W", "attempt": 1, "max_attempts": 3, "backoff_sec": 1 },
  "output_summary": { "error_code": "KIS_TIMEOUT" },
  "error": { "type": "timeout", "message": "KIS request timed out" }
}
```

W/M stale 캐시 사용 fallback 예시:
```json
{
  "event_type": "fallback",
  "node": "data_collect",
  "input_summary": { "period": "W", "cache_key": "ohlcv:weekly:373220" },
  "output_summary": { "fallback_type": "stale_cache", "cache_age_days": 5, "stale_limit_days": 7 }
}
```

W/M 미확보 fallback 예시:
```json
{
  "event_type": "fallback",
  "node": "data_collect",
  "input_summary": { "period": "M", "fallback_type": "data_limited" },
  "output_summary": { "trend": "unavailable", "reason": "monthly cache missing after KIS retry" }
}
```

이 흐름은 `contracts.md`의 예외 상태 출력(stale_cache·data_limited·regime_unavailable·template_fallback), `config.md`의 재시도 설정(3회·1·2·4초 백오프)과 연결된다.

---

## 13. 민감정보·로그 축약 규칙

1. 원본 query는 평문 저장하지 않고 `original_query_hash`만 저장한다.
2. 안전 정규화가 끝난 `normalized_question`만 평문 저장한다.
3. OHLCV 전체 배열은 저장하지 않고 `bar_count_by_period`·`date_range_by_period`·`data_hash_by_period`를 저장한다.
4. LLM prompt 전문은 저장하지 않고 `prompt_version`·`input_summary`·`output_summary`를 저장한다.
5. 사용자 노출 금지어가 포함된 LLM 출력은 검증 이벤트에 `reason`만 저장하고, 원문 전체 저장 여부는 환경 설정으로 제어한다.

---

## 14. 예시 Trace

```json
{
  "trace_id": "trace_xyz789",
  "request_id": "req_abc123",
  "ticker": "373220",
  "as_of": "2026-06-30T14:30:00+09:00",
  "status": "completed",
  "data_status": "normal",
  "final_regime": "overheated",
  "outcome": "passed",
  "regen_count": 0,
  "started_at": "2026-06-30T14:30:01+09:00",
  "ended_at": "2026-06-30T14:30:08+09:00",
  "events": [
    {
      "event_id": "evt_001",
      "node": "data_collect",
      "event_type": "node_end",
      "status": "success",
      "output_summary": { "cache_hit": true, "bar_count_by_period": { "D": 240, "W": 104, "M": 60 }, "data_status": "normal" }
    },
    {
      "event_id": "evt_005",
      "node": "regime_classify",
      "event_type": "node_end",
      "status": "success",
      "output_summary": { "daily_regime": "overheated", "monthly_trend": "up", "alignment_flag": "neutral", "final_regime": "overheated" }
    },
    {
      "event_id": "evt_010",
      "node": "interpret_report",
      "event_type": "validation",
      "status": "success",
      "output_summary": {
        "label_matched": true,
        "interpretation_source": "llm",
        "detail_source_counts": { "llm": 5, "llm_regenerated": 0, "template_fallback": 0 }
      }
    }
  ]
}
```

---

## 15. 관련 문서

| 문서 | 담당 |
| --- | --- |
| `architecture.md` | trace가 위치한 D 관측/평가 층 설명 |
| `contracts.md` | 최종 출력 JSON 구조와 예외 출력 |
| `schema.md` | 최종 리포트 DB 저장 구조 (trace_id 연결) |
| `test_plan.md` | 검증 ①②③ 테스트 기준 (TRACE-* 케이스) |
| `prompts.md` | 원본 query 차단, LLM 출력 금지 규칙 |
| `enums.md` | 재사용 enum 값 기준 |
