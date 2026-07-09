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
