# CLAUDE.md — 뉴스/감성 분석 에이전트

> 이 파일은 news 에이전트 작업 시 항상 적용되는 규칙이다.
> 코드를 생성·수정하기 전에 반드시 이 규칙을 따른다.

---

## 1. 이 에이전트가 하는 일

국내 언론사 뉴스를 수집·분석해 종목별 여론과 핵심 이벤트를 지식 그래프로 구성하고,
최종적으로 **HTML 리포트**를 출력하는 자기완결 에이전트.

- **입력**: 자유 질문 문장 또는 종목(= "이 종목 요약해줘" 프리셋 질문). 질의 흐름은 자유 질문형(B) 확정.
- **출력**: HTML 리포트 하나 (감성 게이지 + TOP 이벤트). ④ 답변 텍스트는 별도 채널이 아니라 리포트 안 `뉴스 흐름 요약` 섹션 + 근거 이슈 칩으로 내장.
- Supervisor는 `graph.py`만 호출한다. 내부는 이 에이전트가 자기완결로 처리.

---

## 2. 절대 규칙 (반드시 지킬 것)

1. **DB에 직접 접근하지 않는다.** PostgreSQL·Neo4j 접근은 오직 `services/backend/`의 클라이언트(save_client / query_client)를 통해 backend(:8000)를 HTTP 호출한다. 이 에이전트 코드에 DB 드라이버·SQL·Cypher를 직접 쓰지 않는다.

2. **nodes는 얇게, 로직은 services에.** `nodes/`의 파일은 "이 단계에서 무엇을 할지" 순서만 담당하고, 실제 무거운 로직(크롤링·모델 추론·계산)은 `services/`에 둔다. 노드는 서비스를 호출하는 얇은 껍데기다.

3. **LLM 출력은 Pydantic으로 강제한다.** LLM 추출 결과는 반드시 `schemas/`의 Pydantic 모델로 파싱·검증한다. "JSON 반환"에만 의존하지 않는다(파싱 실패 방지).

4. **감성 판정·점수는 LLM에게 시키지 않는다.** 감성은 KR-FinBert 전용 모델이, 유사도는 임베딩 모델이 담당한다. LLM은 "추출"(요약·개체·이벤트)만 한다.

5. **데이터가 없으면 환각으로 채우지 않는다.** 크롤링 실패·데이터 부족 시 "데이터 제한"으로 표기하고 넘어간다. 없는 내용을 지어내지 않는다.

---

## 3. 아키텍처 (두 흐름)

### 배치 흐름 (매시간, 백그라운드)
```
scheduler → crawl(RSS 수집·중복제거) → extract(Qwen3, fetch_article Tool로 본문 온디맨드)
  → sentiment → embedding → merge_event → importance → graph → save
```
데이터를 수집·분석해 backend에 저장. HTML은 만들지 않는다. 본문은 일괄 크롤이 아니라 extract의 Tool Calling으로 필요한 기사만 가져온다(TASK 02·03).

### 질의(리포트) 흐름 (사용자 요청 시) — 자유 질문형 B
```
graph → query → report
  query = ① 질문이해(Qwen3→Pydantic: companies·period·intent)
        → ② 그래프순회(Neo4j single/multi-hop)
        → ③ 원문요약조회(PostgreSQL)
        → ④ 답변생성(Qwen3, 근거 news_id)
  report = HTML 리포트 하나. ④ 답변은 "뉴스 흐름 요약" 섹션(+ 근거 이슈 칩)으로 내장(별도 텍스트 출력 없음).
```
저장된 데이터를 읽어 답하고 그린다. 수집·분석하지 않는다. 상세: docs/query_spec.md.

---

## 4. 모델 스택

| 역할 | 모델 | 서비스 파일 |
|---|---|---|
| 추출(요약·개체·이벤트) + 질의 답변 생성 | Qwen3 30B-A3B (로컬) | services/llm.py |
| 감성분석 | KR-FinBert-SC | services/finbert.py |
| 임베딩(summary) | arctic-embed-l-v2.0-ko | services/embedder.py |

- 배치 추출과 질의 답변 생성은 모두 **Qwen3**로 통일한다(목업의 "Gemma" 표기는 Qwen3로 대체).

---

## 5. 핵심 로직 규칙

- **질문 이해(회사명 해석)**: LLM 단독 금지. **사전(규칙) 우선 → LLM 보완** 2단계(Dictionary First → LLM Fallback). ① `config.py`의 별칭 사전(`COMPANY_ALIASES`)으로 오타·약어를 먼저 매핑 → ② 잔여 토큰만 Qwen3로 보완 → ③ 그래프 Company 노드로 검증. 저신뢰·미매칭 토큰은 버린다(억지 매핑·환각 방지, 절대규칙 5). 상세: docs/query_spec.md.
- **이벤트 병합**: summary 임베딩 유사도만 쓰지 않는다. 가중 점수 사용:
  `score = 0.6·summary + 0.3·company_overlap + 0.1·time_proximity`.
  임계값 미만이면 새 이벤트 생성(억지 병합 금지). 후보는 같은 회사·최근 7일로 축소.
- **이벤트 이름**: canonical_title로 고정. 새 기사가 조금 달라도 이름을 계속 바꾸지 않는다.
- **이벤트 제목에 감성 평가어 금지**: "실적 발표"(O) / "실적 호조"(X). 감성은 분포가 표현.
- **감성 집계**: Event에 count를 저장하지 않고 조회 시 실시간 집계.
- **7일 롤링**: published_at 7일 경과분 삭제 + 고아 노드(Keyword·Person) 정리. Company는 유지.

- RSS 수집 후보 (services/rss.py · config.py)

```python
RSS_CANDIDATES = [
    ("조선일보", "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("동아일보", "https://rss.donga.com/total.xml"),
    ("경향신문", "https://www.khan.co.kr/rss/rssdata/total_news.xml"),
    ("세계일보", "https://www.segye.com/Articles/RSSList/segye_recent.xml"),
    ("매일경제", "https://www.mk.co.kr/rss/40300001/"),
    ("한국경제", "https://www.hankyung.com/feed/all-news"),
    ("한겨레", "https://www.hani.co.kr/rss"),
    ("디지털타임스", "https://www.dt.co.kr/rss/google/latest"),
    ("아시아경제", "https://view.asiae.co.kr/rss/all.htm"),
    ("파이낸셜뉴스", "https://www.fnnews.com/rss/r20/fn_realnews_all.xml"),
]
```


---

## 6. 폴더 역할

- `nodes/` : LangGraph 노드 (파이프라인 단계, 얇게)
- `services/` : 실제 로직 (모델 호출·계산·크롤링)
  - 질의측 신규 파일 **추가 예정**: `query_understanding.py`(① 질문 파싱), `graph_query.py`(② Neo4j 탐색 설계). 아직 미작성.
- `services/backend/` : backend HTTP 클라이언트 (저장·조회)
- `schemas/` 에 질의측 **`query.py` 추가 예정**(질문 파싱 결과 + 답변 구조: answer 텍스트 + evidence news_id[]). 아직 미작성.
- `schemas/` : Pydantic 데이터 구조
- `scheduler/` : 매시간 배치 (RSS 수집·7일 삭제)
- `templates/` : HTML 출력 (report.html + css/js)
- `utils/` : 파싱·유사도·시간 보조
- `tests/` : mock 기반 테스트
- `docs/` : 설계 문서 (왜 이렇게 만드는지)
- `tasks/` : 개별 작업 지시서
- `evals/` : 품질 평가 (검색·감성·병합·그래프 구축). 결정적 지표(CI)와 LLM 심판(릴리스)을 분리. RAGAS는 어댑터로 격리.
---

## 7. 코딩 컨벤션

- 언어: Python. 타입 힌트 사용. Pydantic v2.
- 함수는 단일 책임. 서비스 함수는 순수하게(입력→출력), 부수효과는 최소화.
- 예외는 삼키지 말고 로깅. 실패한 기사는 skip하되 파이프라인은 계속.
- 설정값(임계값·가중치·TTL·모델명)은 하드코딩 금지 → `config.py`에서 읽는다.
- 외부 호출(크롤링·backend·모델)은 타임아웃·재시도를 둔다.

---
## 8. 작업 시 참고

- `verith\ai\src\agents\news` 안의 폴더만 사용한다. 절대 그 밖의 폴더를 건들면 안 된다.
- 개별 작업은 `tasks/` 폴더의 번호순 지시서를 따른다(01_schemas부터).
- 설계 배경은 `docs/` 참고.
- 새 파일을 만들 때 위 폴더 역할(6번)에 맞는 위치에 둔다.
- 확신이 없으면 추측해서 구현하지 말고 질문한다.

---

## 미확정 (작업 전 확인 필요)

> **미확정 config 처리 원칙(공통)**: 아래 미확정 값(별칭 사전·언론사 가중치·랭킹 기준 등)은 각각 task 문서에 (a) **확정 전 기본동작**, (b) **임시값 허용 여부**, (c) **확정 시 교체 위치(=config)**, (d) **구현자 하드코딩 금지**를 명시한다. 임의값을 "확정값"처럼 굳히지 않는다. (예: 언론사 가중치 = 확정 전 default-only, TASK 06 §3.1.)

- 이벤트 병합 임계값·가중치 계수: 실데이터 튜닝 예정 (config.py에 임시값)
- importance 계산식의 언론사 가중치 테이블: 미정
- **질의 관련도(랭킹) 점수 정의: 미확정.** 잠정은 importance순 정렬로 대체(추후 튜닝).
- **회사 별칭 사전(`COMPANY_ALIASES`) 초기 구성: 미확정.** KOSPI/주요 종목 + 흔한 약어로 시드하고, 질의 로그의 미매칭 토큰으로 지속 보강. canonical은 그래프 Company 노드명과 일치시킨다.
- backend API 계약(엔드포인트·요청/응답): **초안은 `backend/db/models/news/SCHEMA_SPEC.md §7`**, 정식 `verith/docs/api_contract.md`로 승격 예정
- **ai→backend 인증·접근 통제: 잠정 "내부망 전용" 전제.** 쓰기·삭제 엔드포인트(`/news/batch/save`·`/news/cleanup`)가 무인증이면 삭제·저장을 아무나 유발할 수 있어, 외부 노출 시 내부 토큰 필수로 승격한다. 인증 방식 확정은 api_contract 승격 시(SCHEMA_SPEC §7.1).
- **DB 모델 정의 위치: `verith\backend\db\models\news`** (backend 소유). news는 절대규칙 1대로 HTTP로만 접근. 명세는 docs/erd.dbml.