# TASK 09 — 질의·리포트 흐름 (schemas/query.py · services/query_understanding.py · services/graph_query.py · services/answer_generator.py · services/report_renderer.py · nodes/query.py · nodes/report.py)

> **⚠️ 결정 변경(팀 합의): 최종 출력 = HTML → JSON.** ai·backend·frontend 모두 **JSON 형식으로 통일**한다.
> ai는 리포트를 **`ReportModel` JSON**(`state["report_json"]`)으로 산출하고, backend가 저장하며, frontend가 그 JSON을 받아 렌더한다.
> ai는 더 이상 HTML을 만들지 않는다 — `render_html`·Jinja2·`REPORT_TEMPLATE_PATH`는 제거됐고, `templates/report.html`(+css/js)은
> **frontend 렌더용 목업 디자인 자산**으로만 남는다. ④ 답변은 `ReportModel.answer_text`(+`cited_event_ids`·`evidence_news_ids`)로 내장된다.
> 게이지 비율·순점수·라벨은 `SentimentGauge`의 computed 필드로 JSON에 함께 실려 프론트가 재계산할 필요가 없다(감성 판정 아님).
> 아래 본문의 "HTML 렌더" 관련 서술은 이 결정으로 "JSON 조립"으로 대체해 읽는다(핵심 계약 문장은 갱신됨).

## 0. 개요
- **목적**: 배치 흐름이 저장해 둔 데이터를 읽어 **사용자 질문(또는 종목 프리셋)에 답하고 JSON 리포트 하나(`ReportModel`)를 만드는** 질의 흐름 전체를 구현한다. 자유 질문형 B(query_spec §0). 흐름은 **① 질문이해(Qwen3→Pydantic) → ② 그래프순회(single/multi-hop) → ③ 원문요약조회(PostgreSQL) → ④ 답변생성(Qwen3, 근거 news_id) → JSON 리포트 조립**이며(query_spec §1, sequence §2), ②③의 실제 DB 접근은 **TASK 08의 `query_client`가 backend HTTP로 대행**한다(절대규칙 1: 이 에이전트는 DB에 직접 붙지 않는다). 최종 출력은 **JSON 리포트 하나**(backend 저장·frontend 렌더)이고, ④ 답변 텍스트는 별도 채널이 아니라 리포트 안 **`뉴스 흐름 요약` 섹션(answer_text) + 근거 이슈 칩(cited_event_ids)**으로 내장된다(CLAUDE.md §1). Supervisor는 `graph.py`만 호출하고, 이 흐름이 자기완결로 처리한다.
- **선행 작업**:
  - TASK 01(schemas: `Event`, `ReportModel`·`ReportEvent`·`SentimentGauge`·`ArticleRef`(report.py), `SubjectQueryResponse`·`EventWithArticles`(response.py)). 리포트 입력·조회 응답 모델. `schemas/query.py`(질문 파싱·답변)는 **질의측 전용 스키마이므로 이 문서(TASK 09)가 신규로 소유**한다. TASK 01은 배치측 스키마만 담당하며 질의 스키마를 알 필요가 없다(관심사 분리 — 배치/질의 흐름이 독립적).
  - TASK 03(`services/llm.py`의 Qwen3 클라이언트. **① 질문이해·④ 답변생성이 이 클라이언트를 재사용**한다 — TASK 03 §0.1). 감성 판정·점수는 여기서 하지 않는다(절대규칙 4).
  - TASK 07(`schemas/graph.py`의 `NodeLabel`/`RelType`·정체성 규칙 §0.2. ② 그래프 순회가 이 라벨·관계 타입으로 설계된다 — TASK 07 §0.1).
  - TASK 08(`services/backend/query_client.py`: `get_events_by_subject`(single-hop·importance순·이벤트별 대표 기사 소수 포함)·`get_shared_events`(multi-hop)·`get_articles_by_event(event_id, limit)`(대표 소수 밖 근거 on-demand). **②③의 backend HTTP 조회를 여기서 소비**한다. 감성 게이지는 backend가 실시간 집계해 `SentimentGauge`로 준다).
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 질의·리포트 옵션(기본 조회 기간·TOP N·이벤트별 대표 기사 수·정렬(랭킹) 기준·프리셋 질문 문구·④ 답변 생성 프롬프트/토큰). 하드코딩 금지의 귀착점. **랭킹 점수는 미확정 → 잠정 importance순**(query_spec §6, CLAUDE.md §8).
  - `schemas/query.py`(**신규** — TASK 09 소유) — ① 질문 파싱 결과(`QueryIntent` Enum·`QueryUnderstanding`) + ④ 답변 구조(`Answer`: answer 텍스트 + evidence news_id[]) + (선택) 흐름 번들(`QueryResult`). 질의측 전용 스키마로 이 문서가 소유한다(TASK 01과 독립).
  - `services/query_understanding.py`(**신규**) — ① 자유 문장/종목을 Qwen3로 파싱해 `QueryUnderstanding`(companies·period·intent)로 강제(Pydantic). 종목 선택은 `intent=요약` 프리셋으로 변환.
  - `services/graph_query.py`(**신규**) — ② 그래프 탐색 **설계**: 회사 수·intent로 single-hop / multi-hop을 정하고 `query_client`를 호출해 `SubjectQueryResponse`를 얻는다. 실제 Neo4j 순회는 backend(HTTP).
  - `services/answer_generator.py`(**신규**) — ④ 답변 생성: ③의 요약·감성을 근거로 Qwen3가 `뉴스 흐름 요약` 본문을 작성하고 **주장마다 근거 news_id를 부착**한 `Answer`를 만든다. 근거 부족 시 "데이터 제한"(절대규칙 5).
  - `services/report_renderer.py`(**신규**) — 조회 결과(`SubjectQueryResponse`)를 `ReportModel`로 조립(importance순 TOP N·대표 기사 소수)하고, ④ `Answer`를 `ReportModel.answer_text`(+`cited_event_ids`·`evidence_news_ids`)로 내장한다. **직렬화(`model_dump(mode="json")`)는 노드가 수행**해 JSON 리포트를 만든다(HTML 렌더 없음).
  - `nodes/query.py`(**신규** — 얇게) — ①→②→③→④ 순서만 담당하고 결과를 `state`에 싣는다(로직은 services).
  - `nodes/report.py`(**신규** — 얇게) — `report_renderer.build_report_model`을 호출해 `ReportModel`을 만들고 `state["report_model"]`·`state["report_json"]`(=`model_dump(mode="json")`)에 싣는다.
  - `templates/report.html`(**frontend 렌더용 목업 디자인 자산**) — `veriθ News Report` 목업. ai는 이 파일을 렌더하지 않는다(출력은 JSON). frontend가 이 목업 UI로 리포트 JSON을 렌더한다. 목업 각 요소↔JSON 필드 매핑은 query_spec §3. 프론트 레포로 이관 대상.
- **범위 밖(주의)**:
  - **DB 직접 접근·실제 Neo4j 순회·PostgreSQL 조회는 backend(TASK 08 `query_client`)**. 이 흐름은 조회를 **설계·요청**만 하고, SQL·Cypher·드라이버·backend HTTP를 직접 쓰지 않는다(절대규칙 1). `graph_query`는 "무엇을 어떻게 순회할지"를 정하고 `query_client`를 부른다.
  - **감성 판정·게이지 집계는 하지 않는다.** 감성 라벨은 배치(TASK 04)가 이미 붙였고, **긍/중/부 분포(게이지)는 backend가 조회 시 실시간 집계**해 `SentimentGauge`로 준다(TASK 08·CLAUDE.md §5). 이 흐름은 게이지를 **받아 표시만** 하고, LLM에게 감성을 다시 판정시키지 않는다(절대규칙 4). ④ 답변 LLM은 **텍스트만** 생성한다.
  - **수집·분석(크롤링·추출·임베딩·병합·importance·저장)은 배치 흐름(TASK 02~08)**. 질의 흐름은 **저장된 데이터를 읽어 답하고 그릴 뿐** 새 데이터를 만들지 않는다(query_spec §0, pipeline_spec §11).
  - **importance(중요도) 계산은 TASK 06**. 정렬(랭킹)에 **이미 계산된 importance를 소비만** 한다(재계산 없음). 관련도(질문-이벤트 적합도) 별도 산출은 **미확정 → 잠정 importance순**(query_spec §6).
  - **backend 저장 API·엔드포인트·요청/응답 스키마는 backend 소유**(api_contract.md 미확정, TASK 08 config). 이 흐름은 `query_client`의 함수 계약만 본다.
  - **`graph.py`(LangGraph 조립)·Supervisor 연동은 TASK 11 소유**: `graph.py`가 query→report 노드를 잇는 배선(`build_query_graph`)·`state.py`(`QueryState` 키 계약)은 TASK 11이 만든다. 이 문서는 그 배선이 호출할 **query·report 노드**를 제공한다. 노드 시그니처(`state` in/out)는 §4 규약·TASK 11 `QueryState`를 따른다.
  - **리포트 이력 저장(`reports` 테이블: report_id·question·answer_text·evidence·report_json)은 backend**(erd.dbml). 이 흐름은 리포트 **JSON을 생성**하고, 저장이 필요하면 backend 계약을 통한다(이 문서 범위 밖, api_contract.md 확정 시). 여기서는 `report_json` 산출까지.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 파이프라인의 **최종 출력(JSON 리포트)** 을 만든다. 아래 계약을 바꾸면 Supervisor·evals·목업 정합이 함께 영향받는다.

| 산출물 | 소비/연계 |
|---|---|
| `schemas/query.py`(`QueryUnderstanding`·`Answer`) | ①④ 사이 계약, evals answer 축(faithfulness·evidence 추적), backend `reports` 저장(answer_text·evidence) |
| `state["report_json"]`(최종 JSON 리포트) | `graph.py`→Supervisor 최종 출력, backend 저장(`reports.report_json`), frontend 렌더(목업 정합) |
| `services/report_renderer.py`(`SubjectQueryResponse`→`ReportModel`) | JSON 리포트 계약, 목업 레이아웃·톤(query_spec §3), TASK 01 report 스키마 |
| `services/graph_query.py`(single/multi-hop 설계) | TASK 08 `query_client` 계약, TASK 07 라벨·관계 타입 |
| `services/answer_generator.py`(④ 근거 news_id) | evals source_traceability(근거 추적), 절대규칙 5(환각 금지) |
| 정렬(랭킹) 기준(잠정 importance순) | query_spec §6·pipeline_spec §11(관련도 점수 확정 시 config로 교체) |

### 0.2 근거 추적 규칙 (evidence chain) — ★핵심 계약
> 자유 질문은 **환각·근거 통제가 생명**이다(query_spec §5). 그래서 답변의 모든 주장은 **칩 → 이벤트 → 기사(news_id)** 로 역추적 가능해야 한다. 이 사슬이 어긋나면 evals answer 축(faithfulness·source_traceability)이 깨지므로, 아래를 ④ 답변생성·렌더·evals가 **동일하게** 사용한다.

| 계층 | 식별 | 출처 | 규칙 |
|---|---|---|---|
| 근거 이슈 칩 | 이벤트(canonical_title) | ② 그래프순회 결과 | `뉴스 흐름 요약`이 언급한 이벤트를 칩으로. 칩→이벤트 링크 |
| 이벤트 | `canonical_id` | ② `EventWithArticles.event` | TOP N에 노출. importance순(§6 잠정) |
| 근거 기사 | `news_id`(→`ArticleRef` news_id+summary+url) | ② `EventWithArticles.articles`(대표 소수, news_id 포함) / (추가) `query_client.get_articles_by_event(event_id, limit)` on-demand | ④ 답변의 각 주장에 news_id 부착. `ArticleRef.news_id`가 사슬의 원천(TASK 01·08). 일반 리포트는 대표 소수만으로 근거를 닫고, 더 깊은 근거만 on-demand 조회 |

> **③ 근거 조회 = 대표 기사 우선, 추가는 on-demand(계약 확정)**: ②의 `EventWithArticles.articles`(대표 소수)는 `ArticleRef`로 **news_id·summary를 이미 담으므로 일반 리포트는 재조회 없이** 근거를 단다(원래 "③에서 무엇으로 조회하나" 공백은 대표 소수 안에서 닫힌다). 대표 소수를 넘는 깊은 근거가 필요할 때만 `query_client.get_articles_by_event(event_id, limit)`(TASK 08·SCHEMA_SPEC §7.2)로 이벤트별 기사를 on-demand 조회한다. **event_id→news_id 목록을 조회 DTO에 상시 싣지 않는다**(대표 기사 조회와 근거 조회를 분리 → 이벤트 DTO 경량·Top-N 조정은 `limit` 인자로). bare news_id가 아니라 `ArticleRef`를 돌려주므로(news_id+summary 동시 확보) id→기사 왕복이 생기지 않는다.

- **모든 주장에 근거 news_id 부착**(query_spec §4·pipeline_spec §11). `Answer.evidence_news_ids`로 담고, 근거 없는 문장은 만들지 않는다(환각 금지, 절대규칙 5).
- **근거가 없으면 "데이터 제한"** 을 해당 섹션에 표기한다(`ReportModel.data_limited`/`note`, `SubjectQueryResponse.subject_found`). "없는 종목"과 "뉴스 0건"을 `subject_found`로 구분해 문구를 다르게 쓴다(TASK 01 §3.4).
- **감성은 근거 사슬에 포함되지 않는다**: 게이지는 backend 집계값(`SentimentGauge`)을 표시만. ④ LLM이 감성을 판정하거나 분포를 지어내지 않는다(절대규칙 4).

## 1. 참고 문서
- `docs/query_spec.md` — 전체 흐름(§1), 단계 상세(§2: ① companies·period·intent, ② single/multi-hop, ③ news_id→요약·감성 실시간 집계, ④ 근거 news_id·데이터 제한), 목표 UI↔데이터 매핑(§3), 구현 위치(§4), evals answer 축(§5), **관련도 점수 미확정→잠정 importance순(§6)**.
- `docs/pipeline_spec.md` §1(출력=JSON 리포트 하나·④ 답변 내장), §11(질의: Graph→PostgreSQL→Qwen3·모든 주장 근거·관련도 잠정 importance순), §8(Event 중심·importance 보관→중요도순 정렬).
- `docs/sequence.md` §2(질의 시퀀스: query_understanding→graph_query→query_client→llm ④→report_renderer JSON 조립. 수집·분석 안 함·답변은 JSON 내장).
- `docs/erd.dbml` — `reports` 테이블(report_id·question·intent·answer_text·evidence·report_json·created_at = 리포트 이력, backend 소유), Neo4j 관계(② 순회 대상), 감성 count 미저장(조회 시 집계).
- `backend/db/models/news/SCHEMA_SPEC.md` §6(조회: importance순·multi-hop·news_id→요약/감성·**감성 실시간 집계**) — `query_client`의 backend측 상대.
- `CLAUDE.md` §1(출력=JSON 리포트 하나·④ 답변은 `뉴스 흐름 요약` 섹션 내장·Supervisor는 graph.py만), §2-1(DB 직접 접근 금지→query_client만), §2-2(nodes 얇게·로직 services), §2-3(LLM 출력 Pydantic 강제→query.py), §2-4(감성은 전용 모델·LLM은 텍스트만), §2-5(환각 금지·데이터 제한), §3(질의 흐름 B), §4(모델 스택: 답변 생성=Qwen3), §5(감성 count 미저장·조회 시 집계), §7(외부 호출 타임아웃·재시도·예외 로깅·하드코딩 금지), §8(관련도 점수 미확정).
- TASK 01 `schemas/report.py`(`ReportModel`/`ReportEvent`/`SentimentGauge`/`ArticleRef`), `schemas/response.py`(`SubjectQueryResponse`/`EventWithArticles`), `schemas/event.py`(`Event`).
- TASK 03 §0.1·§3.1(`services/llm.py` Qwen3 클라이언트 재사용), TASK 07 §0.2(라벨·관계 정체성), TASK 08 §3.5(`query_client` 3개 함수·`SentimentGauge` 수신).
- `templates/report.html` — 목표 UI 목업(`veriθ News Report`). **frontend 렌더 기준**(리포트 JSON이 정합해야 할 레이아웃·톤). ai는 렌더하지 않음.

## 2. 배경 (왜)
- **왜 질의 흐름이 배치와 분리되나**: 배치(TASK 02~08)는 매시간 백그라운드로 **수집·분석·저장**만 하고 HTML을 만들지 않는다(CLAUDE.md §3). 질의 흐름은 사용자 요청 시 **저장된 데이터를 읽어 답하고 그린다**. 둘을 나누면 (1) 리포트 생성이 크롤링·모델 추론에 묶이지 않고 빠르며, (2) 같은 저장 데이터로 여러 질문에 답할 수 있고, (3) 절대규칙 1(DB는 backend HTTP)을 질의측에서도 그대로 지킨다.
- **왜 ①질문이해를 LLM으로 하되 Pydantic으로 강제하나**: 자유 문장에서 회사·기간·의도를 뽑는 건 LLM(Qwen3)이 맞지만, "JSON 반환"에만 의존하면 필드 누락·타입 붕괴가 생긴다(CLAUDE.md §2-3). 그래서 ①의 출력은 `schemas/query.py`의 `QueryUnderstanding`으로 **파싱·검증**한다. 종목 선택은 LLM 없이 `intent=요약, companies=[종목]` 프리셋으로 변환해 A(종목형)를 B에 흡수한다(query_spec §2-①).
- **왜 intent가 "채널 on/off"가 아니라 "섹션 초점·분량"만 정하나**: 출력은 항상 JSON 리포트 하나이고, ④ 답변은 언제나 그 안 `뉴스 흐름 요약` 섹션(answer_text)에 들어간다(CLAUDE.md §1). intent(관계/이유/요약/현황)는 **그 섹션을 서사(왜/관계) 중심으로 길게** 쓸지, **분포·핵심 이슈 중심으로 짧게** 쓸지만 조절한다(query_spec §2-①). 별도 텍스트 출력을 켜고 끄지 않는다.
- **왜 ②그래프 "설계"와 backend "순회"를 나누나**: single-hop(한 회사 참여 이벤트)이냐 multi-hop(두 회사 공유 이벤트)이냐를 정하는 건 질문의 형태(회사 수·intent)에 달렸고 이는 도메인 판단이다. 실제 Neo4j 순회는 절대규칙 1대로 backend가 한다. 그래서 `graph_query`는 **어떤 조회를 부를지 설계**하고 `query_client`(TASK 08)를 호출한다. 관계 질문(두 회사)의 핵심은 **multi-hop 공유 이벤트**이므로 회사가 둘이면 `get_shared_events`, 하나면 `get_events_by_subject`로 분기한다(query_spec §2-②).
- **왜 ③원문요약까지 보나(그래프만으론 부족)**: 그래프는 "무엇이 일어났나(이벤트·관계)"는 주지만 "왜"를 설명 못 한다(pipeline_spec §11). 그래서 ②의 이벤트에 붙은 news_id로 PostgreSQL 요약·감성을 조회해(③) ④ 답변의 근거로 쓴다. 감성 **분포**는 이때 backend가 실시간 집계해 준다(저장 안 함, CLAUDE.md §5).
- **왜 ④답변에 근거 news_id를 반드시 붙이나**: 자유 질문은 환각이 최대 위험이다(query_spec §5). 모든 주장을 news_id로 추적 가능하게 하면(칩→이벤트→기사, §0.2) evals가 faithfulness·source_traceability를 채점할 수 있고, 사용자가 근거를 확인할 수 있다. 근거가 없으면 문장을 만들지 말고 "데이터 제한"으로 표기한다(절대규칙 5). ④는 감성을 판정하지 않고(절대규칙 4) **텍스트만** 만든다.
- **왜 게이지·분포를 이 흐름이 집계하지 않고 받나**: Event에 감성 count를 저장하지 않고 조회 시 backend가 실시간 집계한다(CLAUDE.md §5, 하루 수백 건이라 충분). 그래서 `query_client`가 이미 집계된 `SentimentGauge`를 돌려주고, 렌더러는 **비율만 계산해 표시**한다(감성 판정 아님). 이 흐름 어디에서도 기사 감성을 다시 세지 않는다(이중 소스 방지).
- **왜 정렬이 잠정 importance순인가**: "질문에 얼마나 관련 있나"의 관련도 점수는 아직 정의가 미확정이다(query_spec §6, CLAUDE.md §8). 그래서 지금은 TASK 06이 계산해 둔 **importance(기사수+언론사가중치+감성절대값)로 내림차순** 정렬한다(pipeline_spec §11). 정렬 기준을 코드에 박지 말고 `config`로 빼, 관련도 점수 확정 시 교체한다.
- **왜 nodes는 얇고 로직은 services인가**: `nodes/query.py`·`nodes/report.py`는 "①→②→③→④→JSON 조립" 순서만 담당하고, 질문 파싱·탐색 설계·답변 생성·`ReportModel` 조립은 각 서비스에 둔다(CLAUDE.md §2-2). 그래야 각 단계를 backend·LLM mock으로 단위 테스트할 수 있다.
- **왜 목업을 렌더하지 않고 JSON만 내나(팀 계약)**: `templates/report.html`의 목업은 확정된 목표 UI(레이아웃·톤·색)지만, **렌더는 frontend가 하고 ai는 그 UI에 매핑되는 JSON 필드만 채운다**(ai·backend·frontend JSON 통일). ai가 HTML을 그리면 프론트와 렌더가 이중화되고 화면 변경마다 ai를 고쳐야 한다. 그래서 목업의 각 자리(종목·기간·게이지·요약·TOP 이슈·칩)를 **`ReportModel`의 필드로** 대응시키고(query_spec §3 매핑), "추정으로 채우지 않습니다" 배지는 `data_limited`와 연동한다(표현은 frontend).
- **DB 접근 금지의 귀착점**: 질의측 어디에도 DB·HTTP-to-DB 호출이 없다. ②③은 오직 `query_client`(TASK 08)를 통한다.

## 3. 요구사항

### 3.1 `config.py` — 질의·리포트 옵션 (하드코딩 금지)
1. **조회 기간·규모**: `QUERY_DEFAULT_PERIOD_DAYS: int = 7`(질문에 기간 없을 때 기본, query_spec §2-①), `REPORT_TOP_N: int`(주요 이슈 TOP 개수), `REPORT_MAX_ARTICLES_PER_EVENT: int`(이벤트별 화면 노출 대표 기사 수 — `article_count`(총 건수)와 별개, TASK 01 §3.3).
2. **정렬(랭킹) 기준(잠정)**: `REPORT_RANKING: str = "importance"` — 관련도 점수 **미확정 → 잠정 importance순**(query_spec §6, CLAUDE.md §8). **주석으로 "관련도 점수 확정 시 교체" 명시.** 기준 문자열을 코드에 박지 않고 config에.
3. **④ 답변 생성 옵션**: `QUERY_ANSWER_MAX_TOKENS`·`QUERY_ANSWER_TEMPERATURE`(재사용하는 `services/llm.py`에 넘길 값. LLM 공통 설정 `LLM_BASE_URL/MODEL/TIMEOUT/RETRIES`는 TASK 03 config 재사용). intent별 분량/초점은 프롬프트로 조절.
4. **프리셋 질문 문구**: `QUERY_PRESET_QUESTION_TEMPLATE: str`(예: `"{company} 최근 뉴스 요약해줘"`) — 종목 선택을 자유 질문으로 변환(query_spec §2-①). 문구를 코드에 흩지 않고 config에.
4b. **회사 별칭 사전(Dictionary First)**: `COMPANY_ALIASES: dict[str, list[str]]` — 별칭→canonical 회사명(`삼전→[삼성전자]`, `삼전닉스→[삼성전자, SK하이닉스]` 다중 매핑 가능). ⚠️ **미확정(CLAUDE.md §8)** → 초기 시드는 KOSPI/주요 종목+흔한 약어, 질의 로그의 미매칭 토큰으로 지속 보강. canonical은 그래프 Company 노드명과 일치. **사전이 비어도 ②LLM 보완으로 동작**(default). 코드에 흩지 않고 config에.
5. ~~**템플릿 경로**: `REPORT_TEMPLATE_PATH`~~ — **제거됨**(JSON 출력 전환). ai가 HTML을 렌더하지 않으므로 템플릿 경로 config는 없다. `templates/report.html`은 frontend 렌더용 목업 자산.
6. 라벨·관계 타입 문자열(②)은 **`schemas/graph.py` Enum(TASK 07)** 을 재사용하고 config에 흩지 않는다(계약은 스키마, 정책값만 config).

### 3.2 `schemas/query.py` — 질문 파싱·답변 구조 (신규, TASK 09 소유)
> ① 출력·④ 출력을 강제하는 Pydantic 모델. LLM 출력은 반드시 이 모델로 파싱·검증(CLAUDE.md §2-3). 질의측 전용 스키마로 이 문서(TASK 09)가 소유한다(TASK 01은 배치측만 — 질의 스키마와 독립).

1. **`QueryIntent`(str Enum)**: `RELATION="관계"`, `REASON="이유"`, `SUMMARY="요약"`, `STATUS="현황"`(query_spec §2-①). `뉴스 흐름 요약` 섹션의 초점·분량을 결정.
2. **`QueryUnderstanding`(BaseModel)**: `companies: list[str]`, `period_days: int`(기본 `QUERY_DEFAULT_PERIOD_DAYS`), `intent: QueryIntent`, `is_preset: bool = False`(종목 프리셋 여부), **`dropped_tokens: list[str] = []`**(사전·LLM에서 회사로 확정 못 해 버린 토큰 — 관측/사전 보강용, query_spec §①-1·§4), (선택) `original_question: str`(사용자 원문 질문. `raw_` 대신 `original_`). ①의 파싱 결과.
3. **`Answer`(BaseModel)**: `text: str`(`뉴스 흐름 요약` 본문 = ④ 답변 그 자체), `evidence_news_ids: list[int]`(모든 주장의 근거 news_id, §0.2), `cited_event_ids: list[str] = []`(근거 이슈 칩이 링크할 `canonical_id`), `data_limited: bool = False`(근거 부족 표기). LLM이 이 구조로 반환하도록 강제.
4. **(선택) `QueryResult`(BaseModel)**: 흐름 번들 — `understanding: QueryUnderstanding`, `response: SubjectQueryResponse`, `answer: Answer`. `state` 대신 타입 안전하게 넘기고 싶을 때. 없어도 무방(노드가 `state` 키로 전달 가능).
5. Pydantic v2. `evidence_news_ids`는 backend가 부여한 정수 news_id(`Article.id`, TASK 01). 근거 없는 값을 지어내지 않는다(환각 금지).

### 3.3 `services/query_understanding.py` — ① 질문 이해 (Dictionary First → LLM Fallback)
> **회사명 해석은 LLM 단독이 아니다.** `사전(규칙) 우선 → LLM 보완 → 그래프 검증 → 저신뢰 제거` 순(query_spec §①-1, CLAUDE.md §5). 오타·약어(`삼전`·`SK닉스`·`카겜`)를 사전으로 먼저 잡아 LLM 오인식·호출을 줄인다. 기간(period)·의도(intent)만 LLM 파싱.
1. **`understand_query(question: str) -> QueryUnderstanding`**:
   - **① 사전 매칭(Dictionary First)**: 입력을 가볍게 정규화(공백·조사 제거) 후 `config.COMPANY_ALIASES`(별칭→canonical)를 **최장일치 스캔**으로 적용. 대부분의 약어·별칭을 LLM 없이 해결.
   - **② LLM 보완(잔여 토큰만)**: 사전에 안 잡힌 토큰만 `services/llm.py`(Qwen3)에 넘겨 `회사 후보+confidence`를 받는다(전체 문장 재해석 아님). period·intent 파싱도 이 호출에서.
   - **③ 그래프 검증**: 사전+LLM으로 얻은 회사명을 backend(`query_client`, TASK 08) Company 노드/이벤트 존재로 확인. 없으면 그 회사를 제외(리포트가 해당 부분 "데이터 제한"). *전용 검증 엔드포인트 유무는 api_contract 확정 대상; 없으면 ②그래프순회 결과(`subject_found`)로 판정.*
   - **④ 저신뢰 제거**: LLM confidence가 낮거나 "회사 아님"이면 그 토큰을 버리고 사전 결과만 사용(억지 매핑·환각 금지, 절대규칙 5). 버린 토큰은 **`dropped_tokens[]`** 로 남겨 관측·사전 보강에 쓴다.
   - 결과를 **`QueryUnderstanding`으로 검증**(CLAUDE.md §2-3). 기간 표현 없으면 `QUERY_DEFAULT_PERIOD_DAYS`. **canonical 회사명은 그래프 Company 노드명과 일치**(사전 canonical == 노드명).
2. **`from_subject(company: str) -> QueryUnderstanding`**(또는 `understand_query`가 프리셋 감지): 종목 선택은 LLM 없이 `intent=요약, companies=[company], is_preset=True`로 변환(query_spec §2-①). `QUERY_PRESET_QUESTION_TEMPLATE`로 `original_question` 채움.
3. **파싱 실패 degrade**: LLM 응답이 스키마로 파싱 안 되면 예외로 흐름을 죽이지 말고 로깅 후 **보수적 기본값**(회사 추출 실패 시 빈 리스트 → 리포트가 "데이터 제한")으로 통과(절대규칙 5·§7). 감성·영향도를 여기서 판정하지 않는다(절대규칙 4).
4. LLM 호출은 `services/llm.py`만(타임아웃·재시도는 그쪽). 사전(`COMPANY_ALIASES`)·정규화는 config/utils. 이 파일은 사전 적용·프롬프트 구성·파싱·검증만.

### 3.4 `services/graph_query.py` — ② 그래프 탐색 설계 (single/multi-hop)
> 실제 Neo4j 순회는 backend(`query_client`, TASK 08). 여기서는 **어떤 조회를 부를지 설계**만 한다(절대규칙 1).

1. **`fetch_events(understanding: QueryUnderstanding) -> SubjectQueryResponse`**: 회사 수·intent로 분기:
   - **회사 1개** → `query_client.get_events_by_subject(companies, within_days)`(single-hop, importance순).
   - **회사 2개**(또는 intent=관계) → `query_client.get_shared_events(company_a, company_b, within_days)`(multi-hop 공유 이벤트, 관계 질문 핵심 — query_spec §2-②).
   - **회사 0개** → backend 호출 없이 빈 응답 + `subject_found` 처리(리포트가 "데이터 제한").
2. **기간 필터**: `understanding.period_days`를 `within_days`로 전달(최근 7일 등).
3. **degrade**: `query_client`가 `BackendError`를 올리면(TASK 08 §4.2) 로깅 후 빈/`subject_found=False` 응답으로 흐름을 이어 리포트가 "데이터 제한"으로 처리(절대규칙 5). 예외로 흐름을 죽이지 않는다.
4. 관련도(랭킹)는 backend가 준 importance순을 그대로 쓰거나 `REPORT_RANKING`에 따른다(잠정 importance순, §6). 정렬 기준을 여기 박지 않는다.
5. news는 **탐색 요청 설계**만, DB 접근은 backend HTTP. Cypher를 쓰지 않는다.

### 3.5 `services/answer_generator.py` — ④ 답변 생성 (Qwen3, 근거 news_id)
1. **`generate_answer(understanding, response) -> Answer`**: ③의 요약·감성(`ArticleRef`·`SentimentGauge`)을 근거로 Qwen3가 `뉴스 흐름 요약` 본문을 작성한다. **intent로 초점·분량 조절**(관계·이유=서사 상세, 요약·현황=짧게 — query_spec §2-①).
2. **근거 부착**: 모든 주장에 근거 news_id를 달아 `Answer.evidence_news_ids`·`cited_event_ids`를 채운다(§0.2). 근거 기사는 **우선 `EventWithArticles.articles`(대표 소수, news_id·summary 포함)에서** 얻고, 대표 소수로 부족할 때만 **`query_client.get_articles_by_event(event_id, limit)`로 on-demand 추가 조회**(§0.2·SCHEMA_SPEC §7.2). 근거로 실제 조회된 news_id만 넣는다(환각 금지).
3. **데이터 제한**: 관련 데이터가 없으면 지어내지 말고 `Answer.data_limited=True` + 섹션 문구를 "데이터 제한"으로(절대규칙 5). `subject_found`로 "없는 종목"/"뉴스 0건" 구분해 문구를 다르게.
4. **감성 금지**: LLM은 텍스트만. 감성 라벨·분포를 판정·생성하지 않는다(게이지는 backend 집계값 표시, 절대규칙 4).
5. LLM 호출은 `services/llm.py`만(TASK 03 재사용, 타임아웃·재시도). 출력은 `Answer`로 파싱·검증(CLAUDE.md §2-3).

### 3.6 `services/report_renderer.py` — ReportModel(JSON) 조립
> ④ 답변을 `ReportModel.answer_text`에 넣어 JSON 리포트 하나를 조립한다(별도 텍스트 출력 없음, query_spec §4). HTML 렌더 없음 — 직렬화는 노드가 `model_dump(mode="json")`으로, 렌더는 frontend가.

1. **`build_report_model(understanding, response, answer) -> ReportModel`**: `SubjectQueryResponse`를 `ReportModel`로 조립.
   - `top_events`: `EventWithArticles`를 **`REPORT_RANKING`(잠정 importance)순**으로 정렬해 **TOP `REPORT_TOP_N`** 만. 각 `ReportEvent`에 `canonical_title`·`importance`·`gauge`(backend 집계)·`article_count`(총 건수)·`articles`(대표 `REPORT_MAX_ARTICLES_PER_EVENT`건). `article_count`(전체)와 `articles`(대표 소수)를 구분(TASK 01 §3.3).
   - `overall_gauge`: **`response.overall_gauge`(backend가 채운 전체 감성 집계, `sentiment=None` 제외)를 그대로** 쓴다(SCHEMA_SPEC §7.3에서 backend 제공으로 확정). **에이전트가 기사 감성을 다시 세지 않는다**(절대규칙 4). 비율(%)·순점수·라벨은 `SentimentGauge`의 computed 필드가 계산해 JSON에 함께 실린다(감성 판정 아님, 프론트 재계산 불필요).
   - **④ 답변 내장**: `answer_text`=`answer.text`, `cited_event_ids`=`answer.cited_event_ids`(근거 이슈 칩→이벤트), `evidence_news_ids`=`answer.evidence_news_ids`(근거 news_id).
   - `data_limited`/`note`: `subject_found`·이벤트 0건·`answer.data_limited`를 반영("데이터 제한", 절대규칙 5).
2. **`fallback_report_json(understanding) -> dict`**: 조립 실패 시 스키마(`ReportModel`)에 맞는 최소 JSON(`data_limited=True`+"데이터 제한" note). 성공 위장 금지(절대규칙 5·§7).
3. **JSON 필드 ↔ 목업 UI 매핑**(frontend가 렌더, query_spec §3):
   - 헤더(종목·집계기간·건수) ← `subject`·`period_days`·건수(있으면). **없는 값은 지어내지 말고 생략/데이터 제한**(원문/중복제거 318→142·반응도 "평소比 1.8배"는 baseline·수집메타가 있어야 함 → backend가 안 주면 필드에 안 담음, 환각 금지).
   - 감성 게이지(±점수·긍/중/부 %) ← `overall_gauge`(count + computed 비율·score·label). 분석 기사 수 ← `overall_gauge.total`.
   - **`뉴스 흐름 요약` 섹션 ← `answer_text` 그 자체** + 근거 이슈 칩(`cited_event_ids`→이벤트).
   - 주요 이슈 TOP N ← `top_events`(importance순). 이슈 상세 패널(감성 분포+관련 기사) ← 이벤트별 `gauge`·`articles`.
   - "추정으로 채우지 않습니다" 배지 ← `data_limited` 연동(근거 검증 표시).
4. **관계 질문 레이아웃**: intent=관계/multi-hop이면 같은 레이아웃에 **초점을 "관계"로** — 상단 요약=두 회사를 잇는 사건, TOP=공유 이벤트 위주(query_spec §3). (레이아웃 표현은 frontend, ai는 데이터만)
5. 렌더러는 **감성·importance를 재계산하지 않는다**(소비만). JSON 조립만. DB·LLM을 직접 부르지 않는다(입력은 이미 조회·생성된 데이터).
6. **이스케이프·XSS 방지는 렌더하는 frontend 책임**이다. ai는 값을 JSON에 그대로(변형 없이) 실어 보낸다 — 데이터 유실·이중 이스케이프를 만들지 않는다.

### 3.7 `nodes/query.py` · `nodes/report.py` — 얇은 노드
1. **`query_node(state) -> state`**: `state["question"]`(또는 종목)을 받아 `understand_query`(①) → `graph_query.fetch_events`(②) → (③은 `answer_generator`가 `query_client`로) → `answer_generator.generate_answer`(④) 순서로 부르고, `state["understanding"]`·`state["query_response"]`·`state["answer"]`에 싣는다. 순서만 담당하는 얇은 껍데기(CLAUDE.md §2-2).
2. **`report_node(state) -> state`**: `report_renderer.build_report_model`을 불러 `state["report_model"]`에, 그 `model_dump(mode="json")`을 `state["report_json"]`에 싣는다. 조립 로직은 서비스에(노드는 얇게). 조립 실패 시 `report_renderer.fallback_report_json`으로 degrade.
3. **실패 격리**: 한 단계 실패(LLM 파싱·backend 조회)해도 예외로 흐름을 죽이지 말고 로깅 후 **"데이터 제한" 리포트**로 통과(절대규칙 5·§7). 부분 데이터라도 정직하게 표시(성공 위장 금지).
4. 노드는 backend·LLM을 직접 부르지 않는다 — 각 서비스만 호출한다(절대규칙 1·§2-2). 조립·파싱·렌더 로직을 노드에 두지 않는다.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. **backend 조회 계약은 TASK 08 `query_client`, LLM 호출은 TASK 03 `services/llm.py`를 재사용**한다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — 질의·리포트 옵션. 정책값(주석 표기). 랭킹은 잠정 importance순.
QUERY_DEFAULT_PERIOD_DAYS: int = 7                 # 질문에 기간 없을 때 기본(query_spec §2-①)
REPORT_TOP_N: int = 5                              # 주요 이슈 TOP 개수
REPORT_MAX_ARTICLES_PER_EVENT: int = 3            # 이벤트별 화면 노출 대표 기사 수(article_count와 별개)
REPORT_RANKING: str = "importance"                # ⚠️ 관련도 점수 미확정 → 잠정 importance순(query_spec §6). 확정 시 교체
QUERY_ANSWER_MAX_TOKENS: int = 1024               # ④ 답변 생성 토큰(services/llm.py에 전달)
QUERY_ANSWER_TEMPERATURE: float = 0.3
QUERY_PRESET_QUESTION_TEMPLATE: str = "{company} 최근 뉴스 요약해줘"  # 종목→자유질문 변환
# ⚠️ 미확정(CLAUDE.md §8) — 별칭→canonical(그래프 Company 노드명과 일치). 비어도 LLM 보완으로 동작.
COMPANY_ALIASES: dict[str, list[str]] = {
    "삼전": ["삼성전자"], "하이닉스": ["SK하이닉스"], "SK닉스": ["SK하이닉스"],
    "현차": ["현대자동차"], "카겜": ["카카오게임즈"], "삼전닉스": ["삼성전자", "SK하이닉스"],
    # ... 실데이터·질의 로그로 지속 보강
}
# (REPORT_TEMPLATE_PATH 제거 — JSON 출력 전환. ai는 HTML 템플릿을 렌더하지 않는다)
```

```python
# schemas/query.py — 질문 파싱 결과 + 답변 구조(신규, TASK 09 소유). LLM 출력은 이 모델로 강제.
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field
from schemas.response import SubjectQueryResponse

class QueryIntent(str, Enum):
    RELATION = "관계"; REASON = "이유"; SUMMARY = "요약"; STATUS = "현황"

class QueryUnderstanding(BaseModel):
    """① 질문이해 결과. companies·period·intent(query_spec §2-①)."""
    companies: list[str] = Field(default_factory=list)
    period_days: int = 7                    # 기본 QUERY_DEFAULT_PERIOD_DAYS
    intent: QueryIntent = QueryIntent.SUMMARY
    is_preset: bool = False                 # 종목 선택 프리셋 여부
    dropped_tokens: list[str] = Field(default_factory=list)  # 회사로 확정 못 해 버린 토큰(관측·사전 보강, §①-1)
    original_question: str | None = None   # 사용자 원문 질문(raw llm output·raw json과 혼동 방지)

class Answer(BaseModel):
    """④ 답변. text=뉴스 흐름 요약 본문. 모든 주장에 근거 news_id 부착(§0.2)."""
    text: str
    evidence_news_ids: list[int] = Field(default_factory=list)   # 근거 news_id(Article.id)
    cited_event_ids: list[str] = Field(default_factory=list)     # 근거 이슈 칩→canonical_id
    data_limited: bool = False              # 근거 부족 시 "데이터 제한"

class QueryResult(BaseModel):              # (선택) 흐름 번들
    understanding: QueryUnderstanding
    response: SubjectQueryResponse
    answer: Answer
```

```python
# services/query_understanding.py — ① 질문이해(Qwen3 → Pydantic). LLM은 services/llm.py 재사용.
from __future__ import annotations
from schemas.query import QueryUnderstanding

def understand_query(question: str) -> QueryUnderstanding:
    """회사명 = Dictionary First → LLM Fallback → 그래프 검증 → 저신뢰 제거(§3.3, query_spec §①-1):
    ① COMPANY_ALIASES 최장일치 매칭 → ② 잔여 토큰만 Qwen3 보완(+period·intent) →
    ③ query_client로 Company 존재 검증 → ④ 저신뢰·미매칭은 dropped_tokens로 버림.
    결과를 QueryUnderstanding으로 검증. 실패 시 보수적 기본값(빈 회사→'데이터 제한'). 감성 판정 안 함."""
    ...

def from_subject(company: str) -> QueryUnderstanding:
    """종목 선택 → intent=요약 프리셋(LLM 없이). is_preset=True."""
    ...
```

```python
# services/graph_query.py — ② 그래프 탐색 설계(single/multi-hop). 순회는 backend(query_client).
from __future__ import annotations
from schemas.query import QueryUnderstanding
from schemas.response import SubjectQueryResponse
import services.backend.query_client as query_client

def fetch_events(understanding: QueryUnderstanding) -> SubjectQueryResponse:
    """회사 수·intent로 분기: 1개→get_events_by_subject(single-hop),
    2개/관계→get_shared_events(multi-hop 공유 이벤트), 0개→빈 응답(subject_found).
    BackendError 시 로깅 후 빈 응답으로 degrade(리포트가 '데이터 제한'). Cypher 없음."""
    ...
```

```python
# services/answer_generator.py — ④ 답변생성(Qwen3, 근거 news_id). LLM은 텍스트만.
from __future__ import annotations
from schemas.query import QueryUnderstanding, Answer
from schemas.response import SubjectQueryResponse

def generate_answer(understanding: QueryUnderstanding,
                    response: SubjectQueryResponse) -> Answer:
    """③ 근거(response.articles 대표 소수 + 필요 시 query_client.get_articles_by_event)를 근거로 뉴스 흐름 요약 본문 작성.
    intent로 초점·분량 조절. 모든 주장에 근거 news_id(§0.2). 데이터 없으면 data_limited=True.
    감성 판정 안 함(게이지는 backend 집계값). 출력은 Answer로 파싱·검증."""
    ...
```

```python
# services/report_renderer.py — ReportModel(JSON) 조립. HTML 렌더 없음. 감성·importance 재계산 없음.
from __future__ import annotations
from schemas.query import QueryUnderstanding, Answer
from schemas.report import ReportModel
from schemas.response import SubjectQueryResponse

def build_report_model(understanding: QueryUnderstanding,
                       response: SubjectQueryResponse, answer: Answer) -> ReportModel:
    """SubjectQueryResponse → ReportModel. top_events는 REPORT_RANKING(잠정 importance)순 TOP N,
    이벤트별 대표 기사 소수(article_count와 구분). overall_gauge는 backend 집계값(재계산 없음).
    ④ 답변 내장: answer_text·cited_event_ids·evidence_news_ids.
    subject_found·0건·answer.data_limited → data_limited/note('데이터 제한')."""
    ...

def fallback_report_json(understanding: QueryUnderstanding) -> dict:
    """조립 실패 시 스키마에 맞는 최소 JSON(data_limited=True + '데이터 제한' note). 성공 위장 금지."""
    ...
```

```python
# nodes/query.py · nodes/report.py — 얇은 노드. 각 서비스만 호출(절대규칙 1·§2-2).
from __future__ import annotations
import services.query_understanding as query_understanding
import services.graph_query as graph_query
import services.answer_generator as answer_generator
import services.report_renderer as report_renderer

def query_node(state: dict) -> dict:
    """①understand → ②fetch_events → ④generate_answer 순서. 결과를 state에 싣는다.
    한 단계 실패해도 로깅 후 '데이터 제한'으로 통과(흐름 안 죽임). backend·LLM 직접 호출 없음."""
    ...

def report_node(state: dict) -> dict:
    """report_renderer.build_report_model → state["report_model"], 그 model_dump(mode="json")
    → state["report_json"]. 조립 로직은 서비스에(노드는 얇게). 실패 시 fallback_report_json."""
    ...
```

### 4.1 질의 단계 요약 (① → ④ → JSON 조립)
| 단계 | 함수 | 모델/서비스 | 산출물 | 규칙 |
|---|---|---|---|---|
| ① 질문이해 | `understand_query`/`from_subject` | 사전(COMPANY_ALIASES) + Qwen3(`llm.py`) | `QueryUnderstanding` | Dictionary First→LLM 보완→그래프 검증→저신뢰 제거(§3.3). Pydantic 강제. 종목은 프리셋(요약) |
| ② 그래프순회 | `graph_query.fetch_events` | backend(`query_client`) | `SubjectQueryResponse` | 1개=single-hop, 2개=multi-hop. Cypher 없음(절대규칙 1) |
| ③ 근거 기사 | `EventWithArticles.articles`(대표) + `query_client.get_articles_by_event`(추가) | backend(TASK 08) | `ArticleRef`·`SentimentGauge` | 대표 소수로 닫고 부족 시 on-demand. 감성 게이지는 backend 실시간 집계(§5) |
| ④ 답변생성 | `answer_generator.generate_answer` | Qwen3(`llm.py`) | `Answer` | 근거 news_id 부착(§0.2). 텍스트만(절대규칙 4) |
| JSON 조립 | `report_renderer.build_report_model` + node `model_dump` | ReportModel | `ReportModel`·`report_json` | importance순 TOP N. 감성 재계산 없음. HTML 렌더는 frontend |

### 4.2 목업 UI ↔ report_json 필드 매핑 (query_spec §3, frontend가 렌더)
| UI 요소 | report_json 필드 | 규칙 |
|---|---|---|
| 헤더(종목·기간·건수) | `subject`·`period_days`·집계 건수 | 없는 수집메타(318→142)는 지어내지 않음(환각 금지) |
| 감성 게이지(±·긍/중/부 %) | `overall_gauge`(backend 집계 count + computed 비율·score·label) | 비율은 computed 필드가 계산해 JSON에 실림. 감성 판정 아님(절대규칙 4) |
| 분석 기사 수·반응도 | `overall_gauge.total` / (반응도=baseline 필요) | 반응도는 baseline 없으면 필드에 안 담음 |
| **뉴스 흐름 요약(+근거 칩)** | **`answer_text` 그 자체** + `cited_event_ids` | ④ 답변 내장(별도 텍스트 없음). 칩→이벤트(frontend가 링크) |
| 주요 이슈 TOP N | `top_events`(importance순 §6) | 잠정 importance, 관련도 확정 시 교체 |
| 이슈 상세(감성 분포·기사) | 이벤트별 `gauge`·`articles` | 대표 소수(`article_count`와 구분) |
| "추정으로 채우지 않습니다" 배지 | `data_limited` | 근거 부족·subject_found 연동(절대규칙 5) |

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** ②③은 오직 `query_client`(TASK 08, backend HTTP). 이 흐름에 SQL·Cypher·드라이버·직접 HTTP-to-DB가 없다.
- **§2-2 nodes는 얇게, 로직은 services.** `query_node`·`report_node`는 순서만. 파싱·탐색설계·답변생성·렌더는 각 서비스에.
- **§2-3 LLM 출력은 Pydantic 강제.** ①은 `QueryUnderstanding`, ④는 `Answer`(`schemas/query.py`)로 파싱·검증. "JSON 반환"에만 의존하지 않는다.
- **§2-4 감성은 전용 모델·LLM 아님.** 게이지는 backend 실시간 집계값(`SentimentGauge`) 표시만. ④ LLM은 텍스트만 만들고 감성을 판정·집계하지 않는다.
- **§2-5 환각 금지 / 데이터 제한.** 모든 주장에 근거 news_id(§0.2). 근거 없으면 "데이터 제한"(`data_limited`·`subject_found`). 없는 수집메타·반응도를 지어내지 않는다.
- **§5 감성 count 미저장·조회 시 집계.** 분포는 backend가 조회 시 집계해 주고 이 흐름은 표시만. 정렬은 importance순(중요도순).
- **§7 외부 호출(LLM) 타임아웃·재시도, 예외 로깅·degrade. 설정값 하드코딩 금지**(기간·TOP N·랭킹·프롬프트 토큰은 config, 라벨·관계 타입은 schemas Enum).
- **§8 미확정 존중.** 관련도(랭킹) 점수 미확정 → 잠정 importance순(`REPORT_RANKING` config + 주석). backend 조회 계약(api_contract.md)·`reports` 저장은 backend 소유.

## 6. 완료 조건 (DoD)
- [ ] `schemas/query.py`가 **신규 생성**되어 `QueryIntent`(관계/이유/요약/현황)·`QueryUnderstanding`(companies·period_days·intent·is_preset·**dropped_tokens**)·`Answer`(text·evidence_news_ids·cited_event_ids·data_limited)를 Pydantic v2로 정의.
- [ ] `config.py`에 `QUERY_DEFAULT_PERIOD_DAYS`·`REPORT_TOP_N`·`REPORT_MAX_ARTICLES_PER_EVENT`·`REPORT_RANKING`("importance", 주석)·프리셋 문구·`COMPANY_ALIASES`(별칭 사전, ⚠️미확정 주석)·템플릿 경로가 정의됨. 기간·TOP N·랭킹·프롬프트 토큰·별칭 하드코딩 없음.
- [ ] `query_understanding.understand_query`가 **Dictionary First → LLM Fallback → 그래프 검증 → 저신뢰 제거** 순으로 회사명을 해석함(§3.3): ① `COMPANY_ALIASES` 사전 매칭 → ② 잔여 토큰만 Qwen3 보완(+period·intent) → ③ `query_client`로 Company 존재 검증 → ④ 저신뢰·미매칭은 `dropped_tokens`로 버림. 결과를 **`QueryUnderstanding`으로 검증**. 종목 선택은 `from_subject` 프리셋. 파싱 실패 시 예외 없이 "데이터 제한" degrade. 감성 판정 없음. canonical == 그래프 Company 노드명.
- [ ] `graph_query.fetch_events`가 회사 1개=`get_events_by_subject`(single-hop)·2개=`get_shared_events`(multi-hop)로 분기하고 `within_days`를 넘김. `BackendError` 시 빈/`subject_found=False`로 degrade. **Cypher·직접 DB 접근 없음**(절대규칙 1).
- [ ] `answer_generator.generate_answer`가 ③ 요약을 근거로 `뉴스 흐름 요약` 본문을 만들고 **모든 주장에 근거 news_id(`evidence_news_ids`)·`cited_event_ids`를 부착**(§0.2). 데이터 없으면 `data_limited=True`. **LLM은 텍스트만**(감성 판정·집계 없음, 절대규칙 4). 출력은 `Answer`로 검증.
- [ ] **근거 조회 경로가 계약으로 닫힘**: 일반 리포트는 대표 소수(`articles`, news_id 포함)만으로 근거를 닫고, 부족할 때만 `query_client.get_articles_by_event(event_id, limit)`로 on-demand 조회(§0.2·§3.5·SCHEMA_SPEC §7.2). 조회 DTO에 전체 news_id 목록을 상시 싣지 않음(대표/근거 조회 분리).
- [ ] `report_renderer.build_report_model`이 `SubjectQueryResponse`→`ReportModel`을 조립: `top_events`는 **importance순 TOP `REPORT_TOP_N`**, 이벤트별 대표 기사 `REPORT_MAX_ARTICLES_PER_EVENT`건(`article_count`(총 건수)와 구분), `overall_gauge`는 **backend 집계값**(감성 재계산 없음), ④ 답변 내장(`answer_text`·`cited_event_ids`·`evidence_news_ids`), `subject_found`·0건·`answer.data_limited`→`data_limited`/`note`.
- [ ] `ReportModel.model_dump(mode="json")`가 **완결된 리포트 JSON**을 만든다: `answer_text`=`뉴스 흐름 요약` 본문, 근거 이슈 칩=`cited_event_ids`, TOP 이슈=importance순, 감성 게이지=`overall_gauge`(count + computed 비율·score·label). **없는 수집메타·반응도는 필드에 안 담음(생략/데이터 제한)**, `data_limited`↔"추정으로 채우지 않습니다" 배지(frontend). `SentimentGauge` computed 필드가 비율·라벨을 계산해 프론트 재계산 불필요.
- [ ] `templates/report.html`(+css/js)은 **frontend 렌더용 목업 디자인 자산**으로만 남는다(ai는 렌더하지 않음). 이스케이프·XSS 방지는 렌더하는 frontend 책임.
- [ ] `nodes/query.py`가 ①→②→④ 순서로 서비스만 호출해 `state`에 싣고, `nodes/report.py`가 `report_renderer`로 `state["report_model"]`·`state["report_json"]`을 만든다. 한 단계 실패해도 예외 없이 "데이터 제한" JSON으로 통과(흐름 안 죽임). backend·LLM **직접 호출 없음**.
- [ ] 출력은 **JSON 리포트 하나**(`report_json`)이고 ④ 답변이 그 안 `뉴스 흐름 요약` 섹션(`answer_text`)에 내장됨(별도 텍스트 출력 없음). backend 저장·frontend 렌더. 관계 질문은 초점이 "관계"(multi-hop 공유 이벤트)로 이동.
- [ ] 이 흐름 어디에도 DB/HTTP-to-DB 호출·감성 판정·importance 재계산이 없음(②③은 `query_client`만, 게이지는 backend 집계 표시).

## 7. 테스트
- **대상 파일**: `tests/test_query_understanding.py`·`tests/test_graph_query.py`·`tests/test_answer_generator.py`·`tests/test_report_renderer.py`·`tests/test_query_report_nodes.py`(**신규**).
- **mock 전략**: 실제 LLM·backend·네트워크를 호출하지 않는다(CLAUDE.md: tests는 mock 기반). `services/llm.py`(Qwen3)와 `services/backend/query_client.py`를 mock해 고정 응답/예외를 돌려준다.
  - **`understand_query`**: (1) LLM mock이 준 JSON → `QueryUnderstanding`(companies·period·intent) 파싱, (2) 기간 표현 없으면 `QUERY_DEFAULT_PERIOD_DAYS`, (3) 파싱 실패(깨진 JSON) → 예외 없이 보수적 기본값(빈 회사)으로 degrade, (4) `from_subject`가 `intent=요약·is_preset=True` 프리셋 생성. **감성 필드 없음**.
  - **`fetch_events`**: 회사 1개 → `get_events_by_subject` 호출(single-hop), 2개/intent=관계 → `get_shared_events`(multi-hop), 0개 → backend 미호출·`subject_found` 처리. `within_days`가 `period_days`대로 전달되는지. `BackendError` mock → 빈/`subject_found=False`로 degrade(예외 전파 안 함). **Cypher·DB 드라이버 import 없음**.
  - **`generate_answer`**: (1) 근거 있는 응답 → `Answer.text` + **`evidence_news_ids`·`cited_event_ids`가 실제 조회된 news_id/event_id로 채워짐**(지어낸 값 없음), (2) 데이터 0건 → `data_limited=True`·"데이터 제한" 문구, (3) intent별 분량/초점 프롬프트 분기, (4) **LLM 출력에 감성 판정이 없고**(텍스트만) `Answer`로 파싱됨. LLM mock으로 근거 밖 news_id를 넣으면 걸러지는지(환각 방지).
  - **`build_report_model`**: (1) `top_events`가 **importance 내림차순 TOP N**, (2) 이벤트별 `articles`가 `REPORT_MAX_ARTICLES_PER_EVENT`건이고 `article_count`(총 건수)와 다름, (3) `overall_gauge`가 **backend 집계값**(렌더러가 기사 감성을 다시 세지 않음), (4) `subject_found=False`/0건 → `data_limited=True`, (5) ④ 답변이 `answer_text`·`cited_event_ids`·`evidence_news_ids`로 내장됨.
  - **`report_json`(model_dump)**: (1) `answer_text`가 채워지고 `cited_event_ids`·`evidence_news_ids`가 실제 값으로 실림, (2) TOP 이슈가 importance순, (3) `overall_gauge`에 computed 비율·score·label이 담김(합 100·라벨 규칙), (4) **없는 수집메타·반응도 필드가 없음**(생략/제한), (5) 특수문자가 **변형 없이 그대로** 실림(이스케이프는 frontend 책임). 핵심 섹션 필드(subject·overall_gauge·answer_text·top_events)가 모두 존재. `fallback_report_json`이 스키마에 맞는 최소 JSON을 냄.
  - **`query_node`/`report_node`**: (1) 서비스만 호출(backend·LLM **직접 호출 없음**), (2) 한 단계 실패(LLM 파싱·`BackendError`)해도 예외 없이 "데이터 제한" 리포트로 통과, (3) `state["report_json"]`이 dict로 채워짐, (4) 결과가 **JSON 리포트 하나**(별도 텍스트 출력 없음).
  - **DB 미접근·감성 미판정**: 질의 경로 어디에도 SQL·Cypher·DB 드라이버 import가 없고(절대규칙 1), FinBert/감성 집계를 호출하지 않음(게이지는 backend 값 표시)을 확인.
- **경계 케이스**: 회사 0개(없는 종목)·이벤트 0건(뉴스 0건, `subject_found`로 구분)·근거 news_id 빈 값·multi-hop 공유 이벤트 없음·LLM 타임아웃·backend 조회 실패·특수문자/긴 요약·TOP N보다 이벤트가 적음.
- **evals 연계**: 자유 질문은 **answer 축이 핵심**(query_spec §5). faithfulness(환각)·answer correctness/relevancy는 `evals/metrics/judge`(RAGAS 어댑터), source_traceability(근거 news_id 추적)는 `evals/metrics/deterministic`. 정답셋은 `evals/datasets/qa_goldset.jsonl`(질의→정답+evidence_path). 여기 tests는 계약·매핑·degrade·근거 부착을 검증하고, 답변 품질은 evals가 채점한다.
- 이 문서는 여러 TASK의 산출물(01 report/response·query 스키마, 03 llm, 07 라벨·관계, 08 query_client)을 **소비·조립**하므로, 그 계약이 바뀌면 함께 수정한다(스키마·조회 계약 소유는 각 TASK, 질의·렌더 조립은 여기).

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| `state["question"]`(또는 종목) | `state["report_json"]`(JSON 리포트 하나, ④ 답변 내장) | `services/query_understanding`·`graph_query`·`answer_generator`·`report_renderer`(→ `llm`·`query_client`) | DB 직접, 감성 판정, importance 재계산, gauge 재집계, HTML 렌더 | 단계 실패→예외 없이 "데이터 제한" JSON 리포트 |
