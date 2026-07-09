# Shared verith SQL dump

이 디렉터리는 **공용 `verith` DB의 canonical 상태를 팀원이 pull 만으로 재현할 수 있게 하는 SQL dump snapshot**
을 담는다.

스키마는 Alembic 이 관리하고, 이 dump 는 **데이터만** 담는다.

## 파일

- `shared_verith_snapshot.sql`
  - `stocks` **2,607**
  - `stock_aliases` **32**
  - `stock_corp_codes` **3,976**

## 팀원 사용 순서

```bash
docker compose up -d postgres

cd backend
uv sync
uv run alembic upgrade head
docker exec -i verith-postgres psql -U verith -d verith < dumps/shared_verith_snapshot.sql
```

## restore 후 확인

아래 3개 count 가 맞으면 정상이다.

```bash
docker exec verith-postgres psql -U verith -d verith -c "SELECT COUNT(*) FROM stocks;"
docker exec verith-postgres psql -U verith -d verith -c "SELECT COUNT(*) FROM stock_aliases;"
docker exec verith-postgres psql -U verith -d verith -c "SELECT COUNT(*) FROM stock_corp_codes;"
```

기대값:

- `stocks = 2607`
- `stock_aliases = 32`
- `stock_corp_codes = 3976`

## 중요한 주의사항

- 이 dump 는 **데이터 snapshot** 이다. 스키마는 포함하지 않으므로 항상 `uv run alembic upgrade head` 를 먼저 한다.
- restore 대상은 **공용 `verith` DB** 다.
- restore 는 `stocks` / `stock_aliases` / `stock_corp_codes` 를 snapshot 기준 상태로 다시 맞춘다.
- backend 서버가 이미 떠 있으면 restore 후 재기동하는 편이 안전하다.

## 갱신 원칙

- 질문 처리 경로는 계속 **read-only** 이다.
- 이 dump 갱신은 **명시적 관리 작업**이다.
- KIS/DART live sync 결과를 팀과 공유할 필요가 있을 때만 snapshot 을 새로 export 해 커밋한다.

---

# 뉴스 스냅샷 (news + Neo4j 그래프)

주식 마스터와 달리 **뉴스는 저장소가 2곳**(PostgreSQL 기사 + Neo4j 지식그래프)이고, 매시간 수집 +
7일 롤링이라 **변동이 크다**. 그래서 뉴스 스냅샷은 "그 시점의 재현용 샘플"로 본다(live 최신본이 아님).

## 파일

- `shared_news_pg.sql` — PostgreSQL `news` + `news_reports`. 맨 앞 `TRUNCATE ... RESTART IDENTITY` 로
  복원 시 스냅샷 상태로 리셋된다(COPY + `setval` 이 데이터·시퀀스 복구). **기본은 `news.embedding`(pgvector)
  제외** — 파일을 수십 MB 로 부풀리는데 배치의 이벤트 병합에만 쓰이고 조회/리포트는 안 읽기 때문(51MB→~17MB).
- `shared_news_neo4j.cypher` — Neo4j 뉴스 그래프 전체(Event/Company/Keyword/Person/Country/NewsRef +
  관계)를 **정체성 키(`key`/`news_id`) 기준 MERGE 문**으로. APOC 불필요·멱등.

## 스냅샷 뜨기 (데이터 소유자)

repo 루트에서:

```powershell
./snapshot_news.ps1     # backend/dumps/ 에 두 파일 생성 → git add/commit/push
```

내부적으로 PG 는 `pg_dump`, Neo4j 는 `python -m scripts.export_news_graph` 를 실행한다.

## 복원 (팀원)

```powershell
docker compose up -d
cd backend
.venv\Scripts\python.exe -m alembic upgrade head   # PG 스키마
# backend 를 한 번 기동 → Neo4j 유니크 제약 생성(복원 속도·정합). 이후 종료해도 됨.
cd ..
./restore_news.ps1      # PG + Neo4j 복원
```

bash 를 쓴다면 리디렉션으로 직접:

```bash
docker exec -i verith-postgres psql -U verith -d verith < backend/dumps/shared_news_pg.sql
docker exec -i verith-neo4j cypher-shell -u neo4j -p verith1234 < backend/dumps/shared_news_neo4j.cypher
```

## 주의

- 이 dump 는 **데이터**만 담는다. PG 스키마는 항상 `alembic upgrade head` 로 먼저 맞춘다. Neo4j 유니크
  제약은 backend 앱 startup(`db/graph/bootstrap.py`)이 만든다 — 복원 전 backend 를 한 번 띄우면 있다.
- `shared_news_pg.sql` 은 기본으로 `news.embedding`(pgvector)을 **제외**한다(조회·리포트 무관, 배치 병합
  전용). 완전 보존이 필요하면 `snapshot_news.ps1` 상단 `$IncludeEmbedding = $true`
  (또는 `python -m scripts.export_news_pg --include-embedding`).
- 복원은 뉴스 관련 테이블/그래프만 다룬다(주식 마스터 dump 와 독립).

---

# 산업 스냅샷 (industry_reports + Neo4j 그래프 + DART 청크 벡터)

산업 에이전트의 DB 자산도 뉴스와 같은 방식으로 공유한다.

> `ai/src/agents/industry/data/` (raw·structured·extracted) 는 **이미 git 이 추적**한다. 스냅샷 대상이
> 아니다 — 그냥 `git add`. 스냅샷이 나르는 건 **DB 안의 것**뿐이다.

## 파일

- `shared_industry_pg.sql` — PostgreSQL `industry_reports` + `agent_reports`(`agent_type='industry'` 한정).
  `industry_reports` 는 `TRUNCATE` 후 주입한다(uuid PK 라 시퀀스/`setval` 없음). **`agent_reports` 는
  전 에이전트 공용 인덱스 테이블이라 `TRUNCATE` 하지 않고** `DELETE ... WHERE agent_type='industry'`
  로만 스코프 리셋한다 — 뉴스/기술/재무/수급 인덱스 행을 보존하기 위함.
- `shared_industry_neo4j.cypher` — 산업 그래프(`Company`/`Industry`/`Product`/`Policy`/`Person` +
  5종 관계) + `:Chunk`(DART 원문 청크, **임베딩 포함**) + `FROM_FILING`. 전부 MERGE 문이라 멱등.
  제약·인덱스·벡터인덱스를 파일이 스스로 만들므로 **복원 전 backend 선기동이 필요 없다**(뉴스와 다름).

## 스냅샷 뜨기 (데이터 소유자)

repo 루트에서:

```powershell
./snapshot_industry.ps1     # bash: ./snapshot_industry.sh
```

내부적으로 `python -m scripts.export_industry_pg` 와 `python -m scripts.export_industry_graph` 를 돌린다.

## 복원 (팀원)

```powershell
docker compose up -d
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
cmd /c "docker exec -i verith-postgres psql -U verith -d verith < dumps\shared_verith_snapshot.sql"
cd ..
./restore_news.ps1          # 뉴스 스냅샷도 쓴다면 — 반드시 산업보다 먼저 (아래 주의)
./restore_industry.ps1
```

## 주의

- **⚠ 복원 순서: 뉴스 → 산업.** 두 그래프는 단일 `verith-neo4j` 에 `Company`/`Person` 레이블을
  공유하는데 정체성 키가 다르다(뉴스 `key`, 산업 `name`). 뉴스 노드는 **전부 `name` 도 함께 갖고**
  회사명 **28개가 겹친다**(LG화학·삼성SDI·SK이노베이션 …). 산업을 먼저 복원하면 뉴스의
  `MERGE (n:Company {key:...}) SET n += {name:...}` 이 같은 이름의 노드를 새로 만들어
  `Company.name` 유니크 제약(`ai/.../industry/ingest.py` 가 생성)을 위반한다 —
  `Neo.ClientError.Schema.ConstraintValidationFailed` 로 뉴스 복원이 죽는다.
- 같은 이유로 **산업 노드는 속성으로 판별할 수 없다**(`n.name IS NOT NULL` 은 뉴스 노드에도 참).
  exporter 는 `ai/src/agents/industry/data/extracted/graph_documents.json` 을 **allowlist** 로 쓴다.
  이 파일이 산업 그래프의 정본이므로, ai 쪽에서 그래프를 갱신하면 이 파일도 함께 커밋해야 한다.
- 복원 시 `:Chunk` 는 전량 삭제 후 재생성한다(산업 전용 레이블이라 안전). 본체 관계 5종은
  **양끝이 모두 allowlist 안에 있을 때만** 삭제 대상이다 — 뉴스도 `BELONGS_TO` 사용을 계획 중이라
  (`ai/src/agents/news/tasks/07_graph_builder.md`) 타입만으로는 스코프가 안 되기 때문.
- **`shared_industry_neo4j.cypher` 는 `:Chunk.embedding`(1024d)을 기본 포함**한다(파일 ~10MB).
  뉴스 embedding 은 배치 병합 전용이라 뺐지만, 산업의 청크 임베딩은 `vector_retrieve.py` 하이브리드
  검색의 **조회 경로**다. 빼면 팀원이 GPU 로 `vectorize.py` 를 다시 돌려야 한다.
  굳이 빼려면 `python -m scripts.export_industry_graph --no-embedding`.
- `shared_verith_snapshot.sql`(주식 마스터)을 **먼저** 복원해야 한다 — `agent_reports.stock_code` 가
  `stocks.stock_code` 로 FK 를 건다. 종목 context 있는 산업 리포트가 있으면 FK 위반이 난다.
- 스키마는 이 dump 에 없다. 항상 `alembic upgrade head` 를 먼저.
