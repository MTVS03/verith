# 16. 구현 계획 (Implementation Plan)

`docs/implementation_plan.md`

가격/기술적 분석 에이전트를 실제 코드로 구현하기 전에, **구현 순서와 모듈 책임을 한 장에 정리**하는 문서다. 새 규칙을 만드는 문서가 아니라, 기존 설계 문서 전체를 코드 구조에 연결하는 **구현 지도**다.

> 핵심: 어떤 파일/모듈이 · 어떤 설계 문서를 구현하고 · 어떤 순서로 개발할지.

---

## 1. 문서 목적

1. 설계 문서를 실제 코드 모듈에 매핑한다(§4).
2. 개발 착수 순서를 정의한다(§5).
3. MVP에서 제외할 범위를 명시해 스코프를 고정한다(§6).

이 문서는 규칙의 정본이 아니다. 규칙·값·계약의 정본은 각 설계 문서이며, 여기서는 "어느 모듈이 그 문서를 구현하는가"만 연결한다.

---

## 2. 구현 범위

Phase 1(국내장, KIS 기준) 단일 에이전트. AI Technical Supervisor 내부 10노드(LLM 3곳: 노드 1·2·10, 코드 7곳: 3~9)와 그 지원 모듈(데이터·캐시·계산·검증·API)을 구현한다. OpenDART는 재무/펀더멘털 에이전트 범위이므로 가격/기술적 분석 에이전트 MVP에서는 사용하지 않는다.

핵심 원칙(구현 내내 유지): **regime·signal_score·confidence·risk는 코드가 확정, LLM은 문장만.** 검증 ①②③으로 이 경계를 지킨다.

---

## 3. 추천 폴더 구조

이 에이전트는 팀 공통 **AI 서버(`:9000`)** 안의 한 패키지다. HTTP 경계와 에이전트 라우팅은 AI 서버 상위가 맡고, `agents/technical/`은 "기술 에이전트 로직 패키지"로 둔다.

```
src/ai/
├── main.py                        # FastAPI 앱 진입점 (:9000)
├── api/
│   └── internal.py                # Backend→AI HTTP 라우터 (/internal/technical/analyze 등, 전 에이전트 공통)
├── supervisor/
│   └── router.py                  # Top Supervisor: 쿼리 변형 + 에이전트 라우팅
└── agents/
    ├── fundamental/ · news/ · flow/ · industry/   # 다른 에이전트 (팀 영역)
    └── technical/                 # ← 이 문서의 대상
        ├── agent.py               # 외부 진입점(얇은 wrapper): 입력 검증 → supervisor 호출 → 출력 반환
        ├── config.py
        ├── schemas/
        │   ├── enums.py              # enums.md 코드값 정의
        │   └── contracts.py          # Agent input/output Pydantic 모델
        ├── services/
        │   ├── kis_client.py         # KIS API 호출
        │   └── cache_service.py      # Redis 가격 캐시
        ├── indicators/
        │   ├── moving_average.py
        │   ├── rsi.py
        │   ├── volume.py
        │   ├── support_resistance.py
        │   └── pattern.py
        ├── regime/
        │   ├── rules.py              # 일봉 국면 분류
        │   └── multiframe.py         # 주/월봉 추세, alignment_flag
        ├── synthesis/
        │   ├── signal_score.py       # 지표별 신호 가중 집계
        │   ├── confidence.py         # confidence 계산
        │   └── risk.py               # risk_flags, risk note
        ├── charts/
        │   └── chart_builder.py      # charts[] 생성
        ├── prompts/                  # LLM 프롬프트 텍스트 자원(.md). 숫자·라벨을 만들지 않음
        │   ├── normalize_question.md
        │   ├── focus_analysis.md
        │   ├── interpret_report.md      # Prompt 10 (종합 해석 + 지표별 detail, 단일 호출)
        │   └── regenerate_report.md     # Prompt 10-R (검증 ③ 실패 시 확정 라벨 강제 주입 재생성)
        ├── observability/
        │   ├── trace_logger.py       # trace event 기록
        │   ├── trajectory_eval.py    # 검증 ③ (LLM 라벨 왜곡) 판정 로직
        │   └── keyword_rules.py      # 검증 ③ 키워드 사전(대표어·충돌어·금지어)
        ├── nodes/                    # LangGraph 노드 = 얇은 어댑터(state→모듈 호출→state)
        │   ├── normalize_question.py    # 1. 질문 안전 정규화 (LLM)
        │   ├── focus_analysis.py        # 2. 분석 포커스 정리 (LLM)
        │   ├── data_collect.py          # 3. 데이터수집 (코드)
        │   ├── indicator_calculate.py   # 4. 지표계산 (코드)
        │   ├── regime_classify.py       # 5. 국면분류 (코드)
        │   ├── signal_aggregate.py      # 6. 신호종합 (코드)
        │   ├── confidence_calculate.py  # 7. 신뢰도계산 (코드)
        │   ├── risk_detect.py           # 8. 리스크관찰점 (코드)
        │   ├── chart_generate.py        # 9. 차트생성 (코드)
        │   └── interpret_report.py      # 10. 국면해석·리포트 (LLM). prompts/*.md + trajectory_eval 사용
        ├── supervisor/
        │   └── technical_supervisor.py # 10노드 실행 순서 조율, trace_id 생성, 예외 분기, 재생성 루프
        └── tests/                    # test_plan.md 기준 단위테스트
```

폴더 경로는 구현 시 이 문서의 구조를 기준으로 한다. `observability/`·`regime/`·`synthesis/`·`nodes/` 하위는 설계 문서(test_plan·trace_schema·regime_rules·architecture)에서 이미 명시한 경로와 일치한다.

**프롬프트·노드·검증의 3분할(노드 10 기준):** ① `prompts/interpret_report.md`·`regenerate_report.md`는 LLM에 넘길 **텍스트 자원**이고(숫자·라벨 생성 금지, `technical_coding_guidelines §6.1`·`prompts.md §4.1`), ② `nodes/interpret_report.py`는 payload 구성·LLM 응답 파싱·`observability/trajectory_eval.py` 검증 호출·`detail`/`interpretation.text` 병합·template fallback 문장 생성을 맡는 **얇은 노드**이며, ③ **1차 생성→검증 실패→재생성 1회→재검증→최종 fallback 전체 orchestration(재생성 루프)은 `supervisor/technical_supervisor.py`가 소유**한다. `architecture.md §3`이 서술한 "Node는 얇은 어댑터, 로직은 옆 모듈에 위임" 원칙과 일치한다.

**진입점 2단 분리:** `agent.py`는 router가 부르는 얇은 wrapper(입력 검증 → supervisor 호출 → 출력 반환)이고, 실제 조율 로직(10노드 실행·trace_id 생성·KIS 장애 분기·data_limited/stale_cache/regime_unavailable 처리·검증 실패 시 재생성/폴백)은 `supervisor/technical_supervisor.py`가 맡는다. agent.py에 노드 로직이 들어가기 시작하면 supervisor와 역할이 겹치므로, agent.py는 얇게 유지한다. 이 분리 덕분에 `technical_supervisor.run(request)`를 mock 입력으로 직접 호출해 HTTP·router 없이 end-to-end 파이프라인을 테스트할 수 있다.

**HTTP 라우터 위치:** Backend→AI HTTP 엔드포인트(`/internal/technical/analyze`)는 `technical/` 안이 아니라 AI 서버 상위 `src/ai/api/internal.py`에 둔다(전 에이전트 공통 라우팅·인증·에러 핸들링을 한 곳에서 관리). 엔드포인트 경로·계약은 `api_spec.md` 그대로이며, 위치만 상위로 승격된 것이다.

---

## 4. 모듈 ↔ 설계 문서 매핑

이 문서의 핵심 표다. "어디부터 파일을 만들지"의 답.

| 모듈 | 구현 책임 | 기준 문서 |
| --- | --- | --- |
| `schemas/enums.py` | enum 코드값 정의 | `enums.md` |
| `schemas/contracts.py` | Agent input/output Pydantic 모델 | `contracts.md`, `enums.md` |
| `config.py` | 임계값·가중치·기간·재시도 설정 로딩 | `config.md` |
| `services/kis_client.py` | allowlist 검증 후 KIS 종목별 기간별시세 호출, 100건 제한 구간 분할, 원본→내부 OHLCV 변환 | `kis_mapping.md`, `config.md` |
| `services/cache_service.py` | Redis 가격 캐시 조회·저장 | `schema.md`, `config.md` |
| `indicators/*.py` | 이동평균·RSI·거래량·지지저항·패턴 계산 | `regime_rules.md`, `config.md`, `test_plan.md`(검증 ①) |
| `regime/rules.py` | 일봉 국면 분류(6종 우선순위) | `regime_rules.md`, `enums.md` |
| `regime/multiframe.py` | 주/월봉 추세, alignment_flag, regime_context | `regime_rules.md`, `enums.md` |
| `synthesis/signal_score.py` | 지표별 신호 가중 집계, consensus | `config.md`, `enums.md` |
| `synthesis/confidence.py` | confidence 계산(confidence_level 파생) | `config.md`, `contracts.md` |
| `synthesis/risk.py` | risk_flags, risk note 생성 | `enums.md`, `contracts.md` |
| `charts/chart_builder.py` | charts[].period, chart_data(overlays·subcharts·annotations) 생성 | `contracts.md`, `frontend_mapping.md`, `chart_annotation_spec.md` |
| `prompts/*.md` | 질문 정규화·포커스 정리·리포트 문장·재생성 프롬프트 **텍스트 자원**(interpret_report.md·regenerate_report.md 분리) | `prompts.md` |
| `observability/trace_logger.py` | trace event 기록(JSONL) | `trace_schema.md` |
| `observability/trajectory_eval.py` | 검증 ③ LLM 라벨 왜곡 판정 | `test_plan.md`, `trace_schema.md` |
| `observability/keyword_rules.py` | 검증 ③ 키워드 사전(금지어·라벨 충돌) | `test_plan.md`, `prompts.md` |
| `nodes/*.py` | LangGraph 노드 어댑터(state 받아 모듈·프롬프트 호출 → state에 결과 얹음). 계산 로직은 옆 모듈, 순서 조율은 supervisor. `nodes/interpret_report.py`가 **10번 노드**(prompts/*.md·trajectory_eval 사용, 재생성 루프는 supervisor) | `architecture.md`, `prompts.md`, `contracts.md` |
| `supervisor/technical_supervisor.py` | 10노드 실행 순서 조율, trace_id 생성, 예외 상태 분기, 검증 ③ 재생성 루프(REGEN_MAX_COUNT=1)→template fallback | `architecture.md`, `trace_schema.md`, `contracts.md` |
| `agent.py` | 외부 진입점(얇은 wrapper): 입력 검증 → supervisor 호출 → 출력 반환 | `contracts.md` |
| *(상위)* `src/ai/api/internal.py` | `/internal/technical/analyze` HTTP 라우터 (AI 서버 공통, technical 밖) | `api_spec.md`, `contracts.md` |

백엔드(리포트 저장·조회 API, PostgreSQL)는 팀 백엔드 담당 영역이며, 이 에이전트는 `agent.py`가 JSON을 반환하는 데까지 책임진다. HTTP 경계(`src/ai/api/internal.py`)와 에이전트 라우팅(`supervisor/router.py`)은 AI 서버 상위 영역이다.

---

## 5. 개발 순서

바깥 의존(KIS·LLM)은 mock으로 먼저 세우고, 코드 확정 로직 → 검증 → API 순으로 쌓는다.

1. `enums`와 `schemas/contracts.py` Pydantic 모델 작성
2. `config.py` 로딩
3. `services/kis_client.py` **mock** 작성 (실제 KIS는 kis_mapping 후)
4. `services/cache_service.py` (Redis mock)
5. `indicators/*.py` 계산 모듈
6. `regime/rules.py` (일봉 6종)
7. `regime/multiframe.py` (alignment_flag 보정)
8. `synthesis/` signal_score → confidence → risk
9. `charts/chart_builder.py`
10. `observability/trace_logger.py`
11. `prompts/*.md`(interpret_report.md·regenerate_report.md 등 텍스트 자원) + `nodes/*.py`(LLM 노드 어댑터) 연결
12. `observability/trajectory_eval.py` + `keyword_rules.py` (검증 ③). 노드 10(`nodes/interpret_report.py`)의 문장 검증이 이걸 호출한다
13. `supervisor/technical_supervisor.py` — 노드 1~10 실행 순서 조율, trace_id 생성, 예외 분기, **검증 ③ 재생성 루프(1회)→template fallback**
14. `agent.py` (얇은 wrapper) + 상위 `src/ai/api/internal.py` 라우터 연결 — router→agent→supervisor 흐름 완성
15. `test_plan.md` 기준 단위테스트 작성 (검증 ①②③ 케이스). `technical_supervisor.run()`을 mock 입력으로 직접 호출해 HTTP 없이 end-to-end 검증

코드 확정 로직(5~9)을 LLM(11)보다 먼저 세운다 — LLM은 이미 확정된 값을 문장으로 풀 뿐이므로, 확정 로직이 있어야 LLM 노드를 붙일 수 있다. 개별 노드·모듈이 다 선 뒤(1~12) supervisor(13)가 그것들을 순서대로 엮고(재생성 루프 포함), api(14)는 supervisor를 호출만 한다. 노드 10 자체(`nodes/interpret_report.py`)는 순수 함수(생성·검증·병합·fallback 문장)까지만 책임지고, 재생성 루프 실행은 13에서 붙인다.

---

## 6. MVP에서 제외할 것

| 항목 | 제외 이유 |
| --- | --- |
| 비동기 Job API | MVP는 동기 API로 충분(`api_spec.md` §3) |
| PostgreSQL trace table | trace는 JSONL/summary로 관리(`trace_schema.md` §4) |
| AI Agent의 DB 직접 저장 | 저장은 backend 책임(`schema.md` §2) |
| 프론트 HTML 생성 | 에이전트는 JSON만 반환 |
| 실시간 WebSocket 시세 | MVP는 D/W/M 기반 분석이다. `1d` 장중 분봉 차트는 Beta/Future Work(`chart_annotation_spec.md` §3.1)이며, WebSocket 틱 스트리밍은 범위 밖 |
| report_id 별도 짧은 ID | `technical_reports.id` UUID를 그대로 사용(`api_spec.md` §4.3) |
| 행동 패턴 기반 종목 발견(개인화 ③) | 실사용 로그 필요 → Future Work |

`kis_mapping.md`는 KIS 응답 필드 구조가 공식 저장소로 검증되어 **1차 문서를 작성했다**(문서번호 17). 단, 실제 응답 JSON 값·건수·날짜 정렬 방향은 KIS 접근토큰 발급 후 실제 호출 결과로 채운다(kis_mapping §11 TODO).

---

## 7. 관련 문서

| 문서 | 이 계획에서의 역할 |
| --- | --- |
| `architecture.md` | 전체 구조·노드·층 조망 (구현 대상의 큰 그림) |
| `contracts.md` | 입출력 계약 (schemas 구현 기준) |
| `regime_rules.md` | 국면 규칙 (regime 모듈 기준) |
| `config.md` | 수치 설정 |
| `test_plan.md` | 검증 ①②③ (단위테스트 기준) |
| `trace_schema.md` | trace 로그 (observability 기준) |
| `api_spec.md` | API (api 모듈 기준) |
| `prompts.md` | LLM 프롬프트 (prompts 모듈 기준) |
| `chart_annotation_spec.md` | 차트 overlays·subcharts·annotations 구현 기준 (chart_builder) |
