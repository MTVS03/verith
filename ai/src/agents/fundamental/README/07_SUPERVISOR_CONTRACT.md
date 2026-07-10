# 07. Supervisor 통합 — 공개 입력 계약 · insufficient_data 정책 · 후속 debt

PR #56 리뷰(팀장) 후속 정렬 기록. Fundamental이 갖춘 새 공개 계약을 Supervisor가 실제로 소비하도록
맞춘 작업과, ERD 크로스체크·후속 설계 debt를 정리한다. (2026-07-09)

## 1. 공개 입력 계약

Supervisor fan-out이 부르는 외부 진입점은 아래 하나다.

```text
FundamentalAgentInput(request_id, trace_id, ticker, query)
  → analyze_fundamental_public(...)
```

- `intent · years · fs_div · report_mode`는 **외부에서 조립하지 않는다.** `query`를 fundamental 내부
  결정론 해석기(`core/query_interpreter.py`)가 파싱해 정한다. LLM 미사용.
- 적용된 규칙은 응답 `meta.input_interpretation`에 기록되어 Supervisor/디버깅에서 추적 가능하다.
- 옛 내부 계약 `FundamentalRequest(ticker, intent…)`는 내부 계약으로만 남고, 외부 진입점은 위 하나다.
- 해석 규칙 v2(2026-07-10): 2개 이상 분석 축이 함께 매칭되면 `fundamental_health` 종합 intent로 해석한다.
- `latest`는 분기 계열 명시어로만 선택하며, bare `최근`·`최신`은 `annual` 기본값을 유지한다.
- 명확한 동의어 `이익률`·`건전성`·`레버리지`·`차입`·`고평가`를 각 축에 보수적으로 추가한다.

## 2. Supervisor adapter 연결 (이번 변경)

`ai/src/supervisor/execution/adapters.py`의 `FundamentalAdapter`가 옛 경로(`FundamentalRequest` +
`analyze_fundamental`)를 직접 호출해 **query 해석기가 우회되던** 문제를 정렬했다.

| 구분 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 진입점 | `FundamentalRequest` + `analyze_fundamental` | `FundamentalAgentInput` + `analyze_fundamental_public` |
| query | 미전달 | `query = task.rewritten_query` (technical/flow와 동일) |
| corp_name | `corp_name = context.stock_name` 전달 | 미전달 (agent 내부가 corp_code 정본으로 확보) |

**동작 검증(엔드투엔드):** `"최근 3년 부채비율 별도 기준"`을 adapter→public entrypoint로 흘리면 내부
해석기가 `years=3 · report_mode=annual · fs_div=OFS · intent=stability`로 파싱함을 확인.
테스트: supervisor / fundamental green.

코드 변경 위치는 supervisor 계층(`execution/adapters.py`, `tests/test_agent_adapters.py`)이다.
supervisor README(도메인 소유 문서)는 fundamental 팀이 직접 편집하지 않는다 — 아래 §6에 갱신 스펙을
규정해 supervisor 소유자에게 전달한다.

## 3. unsupported ticker / insufficient_data 정책

Fundamental은 지원 밖 종목이나 corp_code 미해결을 **HTTP/실행 실패로 표현하지 않는다.** backend 정본과
static fallback에서 모두 못 찾은 종목도 `200 FundamentalResponse(verdict_label="insufficient_data")`로
반환될 수 있다 (근거: `docs/api_spec.md`).

| Agent | 지원 밖 종목 | Supervisor/UI 처리 |
| --- | --- | --- |
| Technical | 실행 불가 / 실패 / skipped | 실패 카드 |
| Fundamental | 200 + `insufficient_data` | "리포트는 생성됐으나 데이터 부족" 카드. **실패로 뭉개지 않는다.** |

즉 execution 계층에서 adapter 예외는 failed이지만, Fundamental 성공 응답의 `insufficient_data` 라벨은
데이터 부족 상태로 **보존**해야 한다. Supervisor·Backend executor·Frontend가 이 차이를 알아야 한다.

## 4. ERD 크로스체크 (2026-07-09)

`report/schema_builder.py`의 erd_payload 블록을 `backend/db/models/fundamental/*` 컬럼과 전수 대조.
ai는 backend를 임포트하지 않으므로 계약 고정 테스트(`tests/test_schema_builder.py`)가 컬럼 세트를 상수로
복제해 검증하고, 그 상수가 실제 backend 모델과 일치하는지는 수동 대조로 확인했다.

| payload 블록 | backend 모델 | 컬럼 수 | 판정 |
| --- | --- | --- | --- |
| `fundamental_report` | `fundamental_reports` | 27 | 일치 |
| `report_ratios` | `report_ratios` | 14 | 일치 |
| `report_evidence` | `report_evidence` | 17 | 일치 (`currency`→`unit` 교정 반영) |
| `report_interpretation` | `fundamental_report_interpretations` | 7 | 일치 |
| `report_verification` | `fundamental_report_verifications` | 10 | 일치 |
| `report_insights` | `report_insights` | 6 | 일치 |
| `report_filing_snippets` | `report_filing_snippets` | — | AI 미생산 → 빈 배열(의도, 후속 GraphRAG) |

## 5. 후속 설계 debt — corp_code DB 직접 접근

현재 재무 AI는 backend 정본을 **DB에 직접 붙어** 조회한다.

```text
core/config.py : VERITH_DB_URL / DATABASE_URL 읽음
data/corp_code.py : psycopg.connect(...) → SELECT ... FROM stock_corp_codes
                    (실패/미설정 시 static CORP_CODE_MAP fallback + CORP_CODE_FALLBACK_STATIC 플래그)
```

이는 이번 PR의 차단 이슈는 아니지만(설명대로 "direct DB + fallback"으로 의도 구현), 장기적으로 AI가
backend DB schema를 직접 아는 구조는 결합도가 높다. 팀장 리뷰 §3 권고 방향:

```text
AI → Backend internal endpoint → stock_corp_codes 조회
```

또는 최소한 DB 접근 경계를 더 얇게 분리하는 방향이 안전하다. **후속 브랜치 debt로 기록**하며, 이번
단계에서 `corp_code.py` 로직은 변경하지 않는다.

## 6. supervisor 소유자 전달용 변경 스펙 (fundamental 팀 → 팀장)

supervisor 폴더는 팀장 소유이므로 fundamental 팀이 `supervisor/README.md`를 직접 편집하지 않는다.
대신 아래 갱신을 **정확한 스펙으로 규정**하여 supervisor 소유자에게 전달한다. (팀장 리뷰 §2 반영)

**대상:** `ai/src/supervisor/README.md` — "adapter 별 입력 매핑 / 흡수 차이" 표의 fundamental 행.

변경 전 (현재 stale):
```text
| fundamental | FundamentalRequest(ticker, intent…) | ticker(+corp_name=stock_name) | free query 슬롯 없음 → query 미전달, intent 등 agent 기본값. **corp_code 미조립**(후속) |
```

변경 후 (제안):
```text
| fundamental | FundamentalAgentInput(request_id, trace_id, ticker, query) | stock_code + rewritten_query | query 전달 → agent 내부 결정론 해석기가 intent/years/fs_div/report_mode 결정. corp_name/corp_code 미조립(agent가 정본 소비) |
```

근거: 코드는 이미 이 계약대로 동작한다(위 §2, `adapters.py` 변경 반영, supervisor 테스트 green).
supervisor README의 표만 실제 코드와 어긋난 stale 상태이므로, 위 한 행 교체로 정합된다.

> 이 스펙은 supervisor 소유자가 반영한다. fundamental 브랜치는 supervisor 폴더 내부를 편집하지 않고,
> 이 문서로 변경 내용을 전달·설명하는 것까지만 책임진다.
