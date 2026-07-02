# CLAUDE.md — 뉴스/감성 분석 에이전트

> 이 파일은 news 에이전트 작업 시 항상 적용되는 규칙이다.
> 코드를 생성·수정하기 전에 반드시 이 규칙을 따른다.

---

## 1. 이 에이전트가 하는 일

국내 언론사 뉴스를 수집·분석해 종목별 여론과 핵심 이벤트를 지식 그래프로 구성하고,
최종적으로 **HTML 리포트**를 출력하는 자기완결 에이전트.

- **입력**: 종목(또는 섹터)
- **출력**: HTML 리포트 (감성 게이지 + TOP 이벤트)
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
scheduler → crawl → extract → sentiment → embedding → merge_event → importance → save
```
데이터를 수집·분석해 backend에 저장. HTML은 만들지 않는다.

### 리포트 흐름 (사용자 요청 시)
```
graph → query(backend 조회) → report(HTML 생성)
```
저장된 데이터를 읽어 HTML만 그린다. 수집·분석하지 않는다.

---

## 4. 모델 스택

| 역할 | 모델 | 서비스 파일 |
|---|---|---|
| 추출(요약·개체·이벤트) | Qwen3 30B-A3B (로컬) | services/llm.py |
| 감성분석 | KR-FinBert-SC | services/finbert.py |
| 임베딩(summary) | arctic-embed-l-v2.0-ko | services/embedder.py |

---

## 5. 핵심 로직 규칙

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
- `services/backend/` : backend HTTP 클라이언트 (저장·조회)
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

- `verith\ai\agents\news` 안의 폴더만 사용한다. 절대 그 밖의 폴더를 건들면 안 된다.
- 개별 작업은 `tasks/` 폴더의 번호순 지시서를 따른다(01_schemas부터).
- 설계 배경은 `docs/` 참고.
- 새 파일을 만들 때 위 폴더 역할(6번)에 맞는 위치에 둔다.
- 확신이 없으면 추측해서 구현하지 말고 질문한다.

---

## 미확정 (작업 전 확인 필요)
- 이벤트 병합 임계값·가중치 계수: 실데이터 튜닝 예정 (config.py에 임시값)
- importance 계산식의 언론사 가중치 테이블: 미정
- backend API 계약(엔드포인트·요청/응답): verith/docs/api_contract.md에서 확정 예정