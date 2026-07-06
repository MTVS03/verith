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

**3~9번 코드 노드 어댑터 규약:** `nodes/data_collect.py`·`indicator_calculate.py`·`regime_classify.py`·`signal_aggregate.py`·`confidence_calculate.py`·`risk_detect.py`·`chart_generate.py`는 기존 계산 모듈(`services/kis_client`·`indicators/*`·`regime/*`·`synthesis/*`·`charts/chart_builder`)을 호출하는 **얇은 wrapper**다. 규약:
- 계산 로직을 노드 안에 다시 만들지 않는다. 모듈 함수만 호출한다.
- 노드는 모듈의 **로컬 dataclass/리스트를 그대로 반환**하고, **최종 `contracts.*`(RegimeResult·SignalSummary·TechnicalSignal·TechnicalAgentOutput)를 조립하지 않는다.** 계약 조립과 전역 state 확정은 **supervisor 단계** 몫이다(`regime/multiframe.py` 주석과 일치).
- `regime`·`signal_score`·`chart_builder`는 현재 OHLCV 기반 **self-contained** 모듈이라 각자 내부에서 지표를 재계산한다. `indicator_calculate`(노드 4)는 그 공유 캐시가 아니라 **일봉 기반으로 confidence·risk 노드가 소비하는 최신 지표 스칼라 묶음(IndicatorBundle)**만 만든다. 지표 중복 계산은 이 self-contained 설계에 따른 것이며 결함이 아니다.
- **주봉·월봉 추세 계산은 노드 5(`regime_classify`) 책임이다.** 노드 5가 `daily_regime`과 `weekly_trend`·`monthly_trend`를 함께 만들고 `final_regime`·`alignment_flag`·`regime_context`로 보정한다(`regime/multiframe.py`, `trace_schema.md §9`). 노드 4는 주/월 추세를 만들지 않는다(과거 `pipeline.md`·`sequence.md`의 "노드 4가 주/월 추세 계산" 서술은 이 기준으로 정정됨).
- **순수성 경계:** 노드 4~9는 주어진 입력에 대해 **순수 함수형 어댑터**다. 반면 노드 3 `data_collect`는 **fetcher를 주입받는 I/O 어댑터**로, 기본 fetcher가 실제 KIS 호출이므로 순수 함수가 아니다(테스트는 fake fetcher로 외부 호출을 차단한다).
- 전역 state 스키마(`TechnicalState` 등)는 이 단계에서 만들지 않는다 — state dict 매핑은 supervisor에서 확정한다.
- **MA window 의미 상수화(완료 — `refactor/technical-ma-window-config`).** `MA_WINDOWS`(5/20/60)는 단기·중기·장기 역할을 가진 구조적 가정이므로, `config.md §1`에 `MA_SHORT_WINDOW`·`MA_MID_WINDOW`·`MA_LONG_WINDOW`를 도입하고 `MA_WINDOWS`를 이들에서 파생시켰다. 소비 코드(`indicators`·`regime/rules.py`·`synthesis/signal_score.py`·`charts/chart_builder.py`·`nodes/indicator_calculate.py`)는 `mas[5]` 하드코딩 키를 제거하고 역할 상수로 접근한다. `IndicatorBundle` 필드도 `ma_short`·`ma_mid`·`ma_long`으로 명명한다. 기본값 5/20/60의 분석 결과는 불변이며, window 변경 시에도 `KeyError`가 없다(회귀 가드: `test_plan.md` CALC-06).

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
| `agent.py` | 외부 진입점(얇은 wrapper) `run_technical_agent(payload, *, llm_client, fetcher=None, trace_id=None)`: 입력 검증(`TechnicalAgentInput` \| dict) → `technical_supervisor.run` 위임 → `TechnicalAgentOutput` 반환. node/KIS/LLM/계산 로직을 직접 호출하지 않는다 | `contracts.md` |
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
13. `supervisor/technical_supervisor.py` — 노드 1~10 실행 순서 조율, trace_id 생성(주입 없으면 uuid4), 예외 분기, **검증 ③ 재생성 루프(1회)→template fallback**, 그리고 **로컬 dataclass → `contracts.*` 최종 조립**(여기서 처음으로 `TechnicalAgentOutput`을 만든다). 조립 규약:
    - `MultiframeRegimeResult`→`RegimeResult`(1:1), `SignalScoreResult`+`ConfidenceResult`→`SignalSummary`, `IndicatorSignalResult`+`DetailResult`→`TechnicalSignal`(`value=None` 보존), `risk_detect`·`chart_generate` 반환은 그대로(`RiskSummary(items=…)`·`charts`).
    - **LLM 호출 자체 예외(normalize·focus·interpret·regenerate의 `client.complete`)는 supervisor가 잡아 template fallback으로 진행**(사용자 응답 생성). **fetcher/KIS 실패·OHLCV envelope 불량·계약 조립 불가·예상 못한 계산 오류는 전파**(조용히 삼키지 않음).
    - `data_status`: 정상=`normal`, 일봉 빈 데이터=`data_limited`(안전 착지), 봉 부족으로 `final_regime=unavailable`=`regime_unavailable`(6~8 스킵), W/M 부족=`data_limited`(일봉 분석 계속). **`stale_cache`·`source="KIS (stale)"`는 `services/cache_service.py`(Redis) + supervisor 폴백으로 구현됐다**(`feat/technical-cache-service`, config.md §7·§8): fresh 캐시 hit이면 KIS 없이 사용, miss/만료면 KIS 후 write. **stale 폴백은 KIS 통신 실패(`KisApiError`)에만** 적용하고 envelope/타입/as_of 오류는 전파(fail-fast). KIS 실패 시 **per-timeframe 재구성**(D 필수·W/M optional-empty)으로 복원 가능한 만큼 분석을 계속한다(하나라도 stale이면 `data_status=stale_cache`·`source="KIS (stale)"`). cache는 supervisor **주입식**(기본 None=미사용, 기존 동작), Redis 장애·entry 무결성(ticker/timeframe/as_of/fetched_at)은 cache_service가 miss/no-op으로 흡수한다. **official runtime wiring(agent.py/AI router에서 `default_cache()` 주입)은 후속 브랜치**, 1D 분봉 캐시는 범위 밖.
    - `normalize_question` 결과는 노드 2 입력으로만 쓰고 출력에 싣지 않는다. **`focus_analysis`의 `analysis_focus`·`focus_summary`는 노드 10 payload에 "설명 강조 힌트"로 전달**한다(interpret가 이 관점을 문장에 반영, 확정값은 불변 — prompts.md §4). `schemas/state.py`는 만들지 않고 supervisor 내부 로컬 흐름으로 둔다.
    - **재생성/부분 폴백:** 1차 interpret 후 `REGEN_MAX_COUNT`(config.py)만큼 재생성한다. 소진 후에도 실패하면 **granular fallback** — `interpretation.text`가 통과하면 유지하고 실패한 지표의 `detail`만 template로 대체한다(REGEN-04). 구조 자체를 못 믿으면(파싱 실패·details 개수/코드값 불일치·확정값 재생성 필드) 전체 폴백. 재생성 횟수는 코드 하드코딩이 아니라 `config.py REGEN_MAX_COUNT`(정본 `config.md §9`)에서 가져온다.
    - **LLM 호출 실패 경계(typed):** `nodes/_llm_utils.LlmCallError`로 `client.complete` 실패만 감싼다. supervisor는 이 타입만 잡아 fallback하고, 프롬프트 파일 로딩·타입·프로그래밍 오류는 전파한다.
    - **as_of → KIS 조회 종료일(완료 — `refactor/technical-as-of-data-fetch`):** supervisor가 `as_of`를 `run_data_collect(as_of=…)`로 넘기고, `data_collect`가 `kis_client.normalize_end_date`로 `end_date`(date)로 정규화해 `fetch_multi_timeframe_ohlcv(end_date=…)`→`fetch_ohlcv(end_date=…)`→`FID_INPUT_DATE_2`까지 스레딩한다(D/W/M 동일 기준일). 생략 시 오늘 기준(하위 호환). **미래 `as_of`는 ValueError**(tz-안전 비교). `fetch_ohlcv_range`·pagination은 무변경 재사용. 상세: `kis_mapping.md §8.2`.
14. `agent.py` (얇은 wrapper) + 상위 `src/ai/api/internal.py` 라우터 연결 — router→agent→supervisor 흐름 완성
15. `test_plan.md` 기준 단위테스트 작성 (검증 ①②③ 케이스). `technical_supervisor.run()`을 mock 입력으로 직접 호출해 HTTP 없이 end-to-end 검증

코드 확정 로직(5~9)을 LLM(11)보다 먼저 세운다 — LLM은 이미 확정된 값을 문장으로 풀 뿐이므로, 확정 로직이 있어야 LLM 노드를 붙일 수 있다. 개별 노드·모듈이 다 선 뒤(1~12) supervisor(13)가 그것들을 순서대로 엮고(재생성 루프 포함), api(14)는 supervisor를 호출만 한다. 노드 10 자체(`nodes/interpret_report.py`)는 순수 함수(생성·검증·병합·fallback 문장)까지만 책임지고, 재생성 루프 실행은 13에서 붙인다.

**수동 smoke script(`src/agents/technical/scripts/smoke_technical_agent.py`).** 공식 진입점 `run_technical_agent()`를 **real KIS + fake LLM**으로 호출해 전체 파이프라인이 끝까지 도는지·`TechnicalAgentOutput`이 나오는지 눈으로 확인하는 개발자용 도구다. KIS는 실제 호출(기존 `kis_client`/`supervisor` 경로만), LLM은 payload-aware fake(검증 ③ 1차 통과하도록 확정 라벨 echo). **pytest/CI 기본 흐름에는 포함하지 않는다**(real KIS env 필요). 결과 JSON은 `src/agents/technical/scripts/technical_smoke_output/`에 저장하고 커밋하지 않는다(`.gitignore`). smoke는 계산·조율 로직을 만들지 않고 entrypoint 위임만 확인한다. (1D intraday 전용 수동 smoke는 `src/agents/technical/scripts/smoke_intraday_minute.py` — `kis_mapping.md §12.9`.)

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

**`feat/technical-chart-patterns` 브랜치 우선순위** (chart annotation·패턴 개선, 정본: `chart_annotation_spec.md §19.1`):
diagnostics → role clarification(§1.1·§7.1) → display/importance policy(§4.1) → rolling S/R → rolling box_range → box_breakout → cup_handle → fetch lookback 재검토.
**fetch lookback 확대는 즉시 진행하지 않는다** — rolling box/cup 탐지 후 diagnostics에서 historical pre-buffer 부족이 실제 원인으로 확인될 때만 재검토한다(최신 패턴 탐지는 현재 capacity로 충분). `cup_handle_candidate`·`box_breakout_candidate`는 **annotation-only**이며 `signal_score`/`final_regime`/top-level `confidence`/`risk`에 반영하지 않는다.

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

---

## 8. 개발용 수동 시각 QA 도구 (Streamlit lab)

`devtools/streamlit_technical_lab.py` 는 **프론트 구현 전** chart payload·KIS 데이터가 화면에서 쓸 만한지 사람이 눈으로 확인하는 **수동 시각 QA 도구**다(자동 테스트 아님).

- 데이터: **real KIS**(`services/kis_client.fetch_multi_timeframe_ohlcv`) + **fake LLM**(payload-aware, 검증 ③ 우회 없음).
- 진입점: 공식 `agent.run_technical_agent()` 만 호출(노드 직접 호출·production 로직 수정 없음).
- KIS 이중 호출 회피: raw D/W/M 를 먼저 조회해 `st.session_state` 에 담고, agent 실행 시 injected fetcher 로 같은 데이터를 재사용한다. **이 session_state 는 production cache(Redis/`cache_service`)가 아니라 수동 QA용 임시 상태다.**
- 렌더링: `chart_data.candles` 를 **candlestick(altair)** 로 QA 렌더링할 수 있고, MA line 을 그 위에 overlay 한다. altair 불가·candles 결손 시 **close line fallback** 을 유지한다. **plotly 는 사용하지 않는다**(altair 는 streamlit 번들 의존성). 상승봉=빨강·하락봉=파랑(국내 관례 최소 색상).
- 5지표 확인: `moving_average / rsi / volume / support_resistance / pattern` 계산 결과를 화면에서 확인한다 — MA/RSI/volume/SR 는 chart 구간에서, pattern 포함 여부는 §5 의 `technical_signals` 요약 표에서 본다. **candlestick 은 QA용 렌더링일 뿐, production 계산은 `chart_builder` 결과를 그대로 사용한다**(lab 은 재계산하지 않음).
- support/resistance 는 표를 항상 유지하고, candlestick 에서는 점선 수평선으로 근사 overlay 한다. **annotation marker(캔들 위 마커) overlay 는 future work** 다.
- 저장: 디스크 미기록. `st.download_button` 으로 output JSON 만 내려받는다. secret 값은 화면에 절대 표시하지 않고 존재 여부만 OK/MISSING.
- **pytest/CI 에 포함하지 않는다**(real KIS env 필요). **streamlit 은 dev dependency** 이고, **altair 는 streamlit 설치로 사용 가능한 전이(bundled) 의존성**이다 — altair import 가 가능하면 candlestick QA 렌더링을, 불가하면 close line fallback 을 쓴다. **이번 브랜치에서는 altair 를 `pyproject.toml` 에 직접 추가하지 않는다.**

실행:

```bash
cd ai
uv run streamlit run src/agents/technical/devtools/streamlit_technical_lab.py
```

Streamlit lab의 **1D Intraday QA** 섹션은 **fixture/수동 입력** 기반이다 — KIS 호출·자동 refresh·WebSocket·polling 없이 이미 만든 intraday 빌더/헬퍼를 호출해 표시만 한다(기존 D/W/M chart QA와 분리).

---

## 9. 1D intraday (Beta) 구현 현황

장중 분봉(1d)은 **보조 화면**이다(정본 정책: `chart_annotation_spec.md §3.1`, 계약: `contracts.md` "1D intraday"). 기존 **D/W/M 계약은 그대로 유지**되며, intraday는 그 위에 얹히는 **선택적** 확장이다.

**구현된 범위:**

| 항목 | 위치 |
| --- | --- |
| `IntradayCandle`(timestamp)·`IntradayPoint`·`IntradayChartData`(candle_unit `1min`)·`IntradayContext` 스키마 | `schemas/intraday.py` |
| `ChartPeriod`에 `1d` 추가 | `schemas/enums.py` |
| `ChartPayload.chart_data` = `ChartData \| IntradayChartData` 판별 유니온(candle_unit 기준) + `1d→1min` validator | `schemas/contracts.py` |
| 1d chart payload 생성 | `charts/intraday_chart_builder.py` |
| intraday 관측 컨텍스트 계산 | `charts/intraday_context_builder.py` |
| intraday_regime_hint·regime_alignment | `synthesis/intraday_alignment.py` |
| confidence_adjustment(cap ±0.05)·risk_notes(context 내부) | `synthesis/intraday_adjustment.py` |
| **KIS 분봉 fetcher** `fetch_minute_ohlcv`(inquire-time-itemchartprice, TR FHKST03010200) | `services/kis_client.py` |
| supervisor의 optional 조립 — 직접 `intraday_candles` 주입 + optional `intraday_fetcher` 주입(둘 다 실패는 흡수) | `supervisor/technical_supervisor.py` |
| 1D Intraday QA(fixture/manual) | `devtools/streamlit_technical_lab.py` |

**production default-on은 flag로 gate(기본 OFF):** `config.INTRADAY_FETCH_ENABLED`(기본 `False`, **`.env`/환경변수 `INTRADAY_FETCH_ENABLED`로 override** — 환경별 dev/staging=on·prod=off)가 `True`이고 `intraday_fetcher`가 미주입일 때만 supervisor가 기본 `fetch_minute_ohlcv`를 쓴다(C안). 기본(False)에서는 **기본 agent path가 기존 D/W/M과 동일**하다. 우선순위: `intraday_candles` 직접 주입 > 명시 `intraday_fetcher` > (flag ON) `fetch_minute_ohlcv` > off. `agent.py`는 thin wrapper 유지(변경 없음). 운영에서 flag를 켤지는 smoke 결과·운영 정책을 보고 **별도 결정**한다. `kis_mapping.md §12.9`는 실 KIS **manual smoke**로 확인했다(핵심 항목 green).

**불변식:** `charts`는 `{3m, 1y, 5y}`가 항상 존재하고 `1d`는 조건부(소비 측은 `len == 3`이 아닌 period 집합으로 처리). `OHLCV.date`는 날짜 전용 유지. intraday는 `final_regime`을 덮어쓰지 않고, top-level `confidence`/`signal_score`/`risk`도 이 단계에서 변경하지 않는다(`signal_score_adjustment`=0.0). intraday **마커 annotation은 Phase 3(Future Work)**.
