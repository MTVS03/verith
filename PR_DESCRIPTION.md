## ⭐ Key Changes
> 핵심 변경 사항을 적어주세요.

**뉴스 에이전트의 backend 데이터 계층 구현** (PostgreSQL + Neo4j). ai 뉴스 에이전트(:9000)는 DB에 직접 붙지 않고 backend(:8000) `/news/*` HTTP로만 접근하는데, 그 backend 쪽 저장·조회·삭제 계층을 이 PR에서 구현했습니다.

1. **Neo4j 데이터스토어 연결** — `db/graph/`(driver·bootstrap), 앱 lifespan에서 노드 정체성 유니크 제약을 멱등 보장(`ensure_constraints`).
2. **`/news/*` 7개 엔드포인트**
   - `POST /news/batch/save` — 기사(PostgreSQL upsert) + GraphBatch(Neo4j MERGE)를 한 배치로 저장. NewsRef의 url을 저장 시 news_id로 해소.
   - `POST /news/cleanup` — 7일(168h) 롤링 삭제 + 고아 노드 정리 + 살아남은 이벤트 importance 재계산.
   - `GET /news/events/stats` · `GET /news/events/{event_id}/articles` — 이벤트 누적 통계·근거 기사(순수 PostgreSQL).
   - `GET /news/query/subject` · `GET /news/query/shared` — 종목 single-hop·두 회사 multi-hop(Neo4j 순회 + 감성 게이지 실시간 집계, importance순).
   - `GET /news/events/recent` — 병합 후보 이벤트 + centroid(임베딩 평균).
3. **계층 구조** — `schemas`(ai 계약 미러) → `repositories`(news_repository=PG, news_graph_repository=Neo4j Cypher) → `services` → `routes`. technical 에이전트 패턴을 따랐습니다.
4. **importance 재계산(backend)** — cleanup 이후 정렬이 흔들리지 않도록 ai와 동일한 공식(volume·publisher·sentiment 가중)을 backend에도 두었습니다. *(공식이 ai·backend 두 곳에 복제돼 있어 변경 시 동기화 필요)*
5. **config 수정** — `EMBED_MODEL`이 로드 불가한 이름이라 실제 임베딩이 깨지던 것을 유효한 HF 레포 ID(`dragonkue/snowflake-arctic-embed-l-v2.0-ko`)로 교정.
6. **end-to-end 스트림릿 데모** — `ai/src/agents/news/demo_pipeline_app.py`: 수집→추출→감성→임베딩→그래프→저장→검색→리포트를 실제로 돌려 눈으로 확인.
7. **데이터 모델 문서** — `backend/db/DATA_MODEL.md` 신규, `SCHEMA_SPEC.md`에 §0 ERD(mermaid) 추가.

> 최신 `develop`를 머지해 반영했습니다(stocks 라우터/서비스와 충돌 없이 news와 공존하도록 해결).

<br>

## ✅ 확인 방법
> 리뷰어가 직접 돌려볼 수 있도록 실행 방법을 적어주세요.

**1) 인프라 기동** (PostgreSQL + Neo4j)
```bash
docker compose up -d postgres neo4j
```

**2) backend 테스트** — news 저장·조회·삭제·병합후보·importance 단위 테스트(mock 세션 기반)
```bash
cd backend
uv run pytest -q
```

**3) backend 서버 + API 확인**
```bash
cd backend
uv run alembic upgrade head          # 스키마 마이그레이션
uv run uvicorn src.api.main:app --port 8000
# http://localhost:8000/docs 에서 /news/* 엔드포인트 확인
```

**4) end-to-end 데모(선택)** — 실제 뉴스 수집→검색→리포트
```bash
BACKEND_BASE_URL=http://localhost:8000 \
uv run --project ai --with streamlit streamlit run ai/src/agents/news/demo_pipeline_app.py
# 사이드바 "뉴스 수집·분석 실행" → 회사 칩/자유질문으로 리포트 생성
```

<br>

## 👪 To Reviewers
> 주요 리뷰 포인트입니다.
> - **DB 경계**: news 관련 DB 모델·마이그레이션은 backend 소유이고, ai 에이전트는 절대 DB에 직접 붙지 않고 HTTP로만 접근합니다. `repositories/`에만 SQL·Cypher가 모여 있는지 봐주세요.
> - **importance 공식 이중화**: `backend/src/api/services/importance.py` 가 ai 쪽 공식과 동일해야 cleanup 재계산 후 정렬(TOP-N)이 안 흔들립니다. 궁극적으로 단일 소유로 고정 필요(언론사 가중치 테이블은 아직 임시값).
> - **인증**: `/news/batch/save`·`/news/cleanup`(쓰기·삭제)은 잠정 "내부망 전용" 전제 — 무인증이라 외부 노출 시 내부 토큰 필수로 승격해야 합니다.
> - **스키마 명세**(`backend/db/models/news/SCHEMA_SPEC.md`): 팀 확정 전 잠정 항목이 있어 최종 확인이 필요합니다.
