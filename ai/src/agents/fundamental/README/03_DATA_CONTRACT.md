# 03. 데이터와 계약

## ERD 동결 전제

DB ERD는 동결 상태입니다. 이 폴더의 작업은 백엔드 스키마 변경을 제안하거나 요구하지 않습니다. `meta.erd_payload`는 저장 미리보기 계약이며, 실제 DB write는 이 워커가 수행하지 않습니다.

## 공개 입력 계약: FundamentalAgentInput

Supervisor가 호출하는 공개 입력은 `core/contract.py`의 `FundamentalAgentInput`입니다. 내부 분석 파라미터(`intent`, `fs_div`, `report_mode`, `years`)는 외부에서 받지 않고, `query`를 결정론 규칙으로 해석해 `FundamentalRequest`로 변환합니다.

```json
{
  "request_id": "req-001",
  "trace_id": "trace-001",
  "ticker": "005930",
  "query": "삼성전자 최근 3년 수익성 분석해줘"
}
```

| 필드 | 검증 | 의미 |
| --- | --- | --- |
| `request_id` | 빈 문자열 금지 | 요청 추적 ID |
| `trace_id` | 빈 문자열 금지 | 실행 trace ID |
| `ticker` | 6자리 숫자 문자열 | backend stock_resolver가 확정한 종목코드 |
| `query` | 빈 문자열 금지 | 사용자 자연어 질문 또는 Supervisor가 보존한 질의 |

Technical 입력과의 대칭은 아래와 같습니다.

| 축 | TechnicalAgentInput | FundamentalAgentInput |
| --- | --- | --- |
| 종목 | `ticker` 6자리 문자열 | `ticker` 6자리 문자열 |
| 질의 | `query` | `query` |
| 요청 추적 | `request_id` | `request_id` |
| 실행 추적 | 출력에서 `trace_id` 생성 | 입력 `trace_id` 보존 |
| 기준 시각 | `as_of` 입력 | DART 보고서 탐색/연간 기본값으로 내부 결정 |
| 내부 파라미터 | 기술 분석 내부에서 결정 | `intent`, `fs_div`, `report_mode`, `years`를 query 해석기로 결정 |

해석 결과는 응답 `meta.input_interpretation`에 기록합니다. `corp_code`는 `stock_corp_codes` backend 정본 조회를 우선하고, DB 미설정/실패 시 기존 정적 맵으로 폴백하며 이때 `CORP_CODE_FALLBACK_STATIC`을 `risk_flags`와 `meta.corp_code_resolution`에 남깁니다. DB DSN은 `VERITH_DB_URL`을 우선 사용하고, 미설정이면 backend와 같은 접속 문자열을 공유하기 위해 `DATABASE_URL`을 호환 alias로 읽습니다.

## 주 계약: FundamentalResponse JSON

`core/contract.py` 기준 최상위 응답은 `FundamentalResponse`입니다. 프론트/백엔드는 이 JSON을 계약으로 사용하고, `report_html`에서 값을 역파싱하지 않습니다.

| 필드 | 의미 | 프론트 사용 |
| --- | --- | --- |
| `agent` | `"fundamental"` 고정 | 워커 식별 |
| `request_id` | 요청 식별자 | 요청 추적 |
| `ticker`, `corp_name` | 종목코드와 기업명 | 화면 제목, 종목 표시 |
| `verdict` | 최종 한국어 판정 문장 | 본문 표시 가능. 숫자 소스로 사용 금지 |
| `verdict_label` | `strong`, `moderate`, `weak`, `insufficient_data` | 라벨 배지. `score`에서 재유도 금지 |
| `confidence` | 0~1 신뢰도 | 보조 표시 |
| `score` | 0~100 절대 재무점수 | 메인 점수 |
| `score_breakdown` | 점수 구성, 설명, peer-relative 정보 | 점수 설명과 배치 비교 표시 |
| `analyst_plan` | 섹션 순서와 분석 brief, agent plan | 디버그/고급 UI |
| `evidence_graph` | filing/account/metric/claim graph | 근거 경로 표시 또는 디버그 |
| `retrieval_context` | LLM에 전달한 근거 요약과 선택 경로 | 디버그 |
| `ratios` | 재무 지표 dict. `value`, `unit`, `display_value`, `label`, `category`, `status`, `reason` 포함 가능 | 지표 카드. 표시는 `display_value` 우선 |
| `trend` | `years`, `revenue`, `op_income`, `roe`, `display`, `period_labels` | 차트와 추세 표 |
| `insights` | 배당, 최대주주, 소액주주, 감사의견 등 정기공시 보강 | 보조 인사이트 |
| `interpretation` | LLM/template 설명 문장 | 본문 표시 가능. 숫자 소스로 사용 금지 |
| `evidence` | `Evidence` 배열. `claim`, `metric`, `value`, `unit`, `display_value`, `fiscal_year`, `rcept_no`, `account_ids`, `accounts`, `source_url` | DART 근거 링크와 계정 표시 |
| `risk_flags` | 데이터 누락, fallback, 검증 경고 | 한계/주의 표시 |
| `report_html` | self-contained HTML fragment | 로컬 검수/디버그. 서비스 UI의 필수 파싱 대상 아님 |
| `meta` | provider/model, corp_code, DART source, verification, cost, workflow, run context, `erd_payload` | 운영 관측과 저장 미리보기 |

## erd_payload 저장 미리보기

`report/schema_builder.py`의 `build_erd_payload()`는 아래 구조를 `meta.erd_payload`에 넣습니다.

| 키 | 내용 |
| --- | --- |
| `stock` | `stock_code`, `stock_name` |
| `fundamental_report` | report id, request id, 종목, corp code, 사업연도, `fs_div`, `reprt_code`, verdict, label, confidence, score, data status, risk flags, trace id, 시각 |
| `report_ratios` | 지표명, 연도, 값, 단위, 라벨, 카테고리, display, formula, status, reason, basis |
| `report_evidence` | ratio id에 연결된 DART 접수번호, 사업연도, 재무제표 구분, 계정 ID/명, 금액, 통화, role, source URL |
| `report_interpretation` | report id, 해석 문장, interpretation source |
| `report_verification` | binding, consistency, verdict stability, outcome, regen count |
| `report_insights` | 배당/주주/감사의견 등 정기공시 보강 payload |
| `report_filing_snippets` | 현재 AI가 공시 원문 스니펫을 별도 생산하지 않아 빈 배열로 명시 |
| `retrieval_summary` | DART source policy 요약 |

`report_id`는 `trace_id`, `ticker`, `bsns_year`, `reprt_code`를 포함한 UUID5 기반입니다.

## DART 소스 정책

`collect_node.py`와 `retrieval/source_policy.py`를 통해 재무제표 수집 이력이 `retrieval_summary`로 전달됩니다. annual 모드는 캐시를 사용할 수 있고, latest 모드는 최신 보고서 탐색 후 최신 연도에 대해 cache bypass를 적용합니다. refresh 실패로 stale cache를 쓰면 `STALE_DART_CACHE_FALLBACK`이 `risk_flags`에 추가됩니다.

## annual vs latest 기준

`FundamentalRequest.report_mode`는 `annual` 또는 `latest`입니다. 기본값은 `annual`입니다.

| 모드 | 의미 | 대표 보고서 | 프론트 표시 기준 |
| --- | --- | --- | --- |
| `annual` | 연간 사업보고서 기준 분석 | `reprt_code=11011`, 사업보고서 | 기본 재무 리포트. 기간 배지는 연간 기준 |
| `latest` | DART에서 가장 최신 제출 보고서를 탐색한 뒤 그 보고서 기준으로 분석 | 1분기보고서, 반기보고서, 3분기보고서, 사업보고서 중 최신 | 최신 공시 기준 리포트. 기간 배지는 분기/반기/연간 여부에 따라 표시 |

응답 JSON에서는 아래 필드로 실제 기준을 확인합니다.

| 필드 | 의미 |
| --- | --- |
| `meta.report_mode` | 요청/실행 모드 |
| `meta.reprt_code` | DART 보고서 코드 |
| `meta.reprt_name` | DART 보고서 이름 |
| `meta.period_basis` | 화면 표시용 기간 설명과 분기 여부 |
| `meta.fresh_dart` | latest 요청 여부 기반의 최신 조회 표시 |

프론트는 `report_mode`만 보고 기간을 추측하지 말고, `reprt_code`, `reprt_name`, `period_basis`를 함께 표시해야 합니다.

## 프론트 주의점

- `score`, `verdict_label`, `ratios[*].value`는 JSON 필드에서 읽습니다.
- 표시 문자열은 가능하면 `ratios[*].display_value`, `trend.display`, `evidence[*].display_value`를 우선 사용합니다.
- `verdict`와 `interpretation`은 설명 문장입니다. 여기서 숫자·라벨을 재계산하거나 추출하지 않습니다.
- `report_html`은 격리 삽입 가능한 검수용 fragment이지만, 장기 서비스 UI는 JSON을 직접 렌더링하는 방향이 맞습니다.
