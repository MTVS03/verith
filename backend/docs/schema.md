# veriθ Backend — 통합 PostgreSQL 스키마 (팀 공유 문서)

`docs/schema.md`

이 문서는 veriθ 백엔드의 **통합 ERD 기준 PostgreSQL 스키마**와, 로컬에서 Docker로 DB를
띄우고 **테이블을 내려받는(마이그레이션) 방법**을 정리한다. DB 컬럼·테이블 변경은 이 문서를
먼저 고치는 것을 원칙으로 한다(코딩 가이드 §1.1).

- 스키마 정의(정본): SQLAlchemy 모델 `backend/db/models/**` + Alembic 마이그레이션
- 최초 마이그레이션: `backend/db/migrations/versions/20260707_705a5833d4a3_add_integrated_postgresql_schema.py` (revision `705a5833d4a3`)
- 이 브랜치 범위: **테이블 생성만.** 저장/조회 API·repository·service는 각 담당자가 후속 브랜치에서 구현한다.

---

## 0. TL;DR — 테이블 내려받기 (복붙용)

```bash
# 1) 저장소 루트에서 Postgres(+pgvector) 컨테이너 기동
cd /path/to/verith
docker compose up -d postgres

# 2) DB 접속 정보 맞추기 (아래 §2 주의! host 포트는 5433)
#    backend/.env 의 DATABASE_URL 을 5433 으로 두거나, 아래처럼 환경변수로 준다.
export DATABASE_URL="postgresql+asyncpg://verith:verith1234@localhost:5433/verith"

# 3) 백엔드 의존성 설치 + 마이그레이션 적용
cd backend
uv sync
uv run alembic upgrade head

# 4) 확인
uv run alembic current            # 705a5833d4a3 (head) 이면 성공
```

되돌리기: `uv run alembic downgrade base` (모든 테이블·확장 제거).

---

## 1. 사전 준비물

| 항목 | 값 / 방법 |
|---|---|
| Docker | `docker compose up -d postgres` 로 `verith-postgres` 컨테이너 기동 |
| Postgres 이미지 | **`pgvector/pgvector:pg16`** (docker-compose.yml). plain `postgres:16` 아님 — `news.embedding` 의 `vector` 확장 때문 |
| Python 툴 | `uv` (backend 는 `uv sync` / `uv run …`) |
| DB 자격(개발용) | user=`verith`, password=`verith1234`, db=`verith` (docker-compose.yml 의 dev 값) |
| **host 포트** | **5433** (컨테이너 5432 → host 5433 매핑). §2 반드시 확인 |

---

## 2. ⚠️ DATABASE_URL 과 포트 (가장 자주 막히는 곳)

- docker-compose 는 `"5433:5432"` 로 매핑한다 → **호스트에서는 `localhost:5433`** 으로 접속한다.
- **`DATABASE_URL` 은 필수 환경변수다.** `config.py` 에 URL/비밀번호 하드코딩 fallback 은 **없다**(가이드 §2.1/§2.2). 없으면 설정 로딩 단계에서 즉시 에러가 난다.
- 값은 **환경변수 또는 `backend/.env`** 로 주입한다. `.env` 는 CWD 무관하게 backend 루트 기준으로 로드된다.
  → `.env` 의 `DATABASE_URL` 은 반드시 **포트 5433**(docker-compose host 포트)으로 맞춘다. `5432` 로 두면 alembic 이 `Connect call failed ... 5432` 로 막힌다.
- 드라이버는 **asyncpg**. DSN 스킴은 반드시 `postgresql+asyncpg://` 로 쓴다.

예시 DSN: `postgresql+asyncpg://verith:verith1234@localhost:5433/verith`
우선순위: **환경변수 `DATABASE_URL` > `backend/.env`** (하드코딩 fallback 없음).

---

## 3. PostgreSQL 확장 (extension)

최초 마이그레이션 `upgrade()` 가 테이블 생성 **전에** 아래를 만든다.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- uuid PK 기본값 gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;     -- news.embedding 의 vector 타입
```

> **확장 관리 규칙:** `pgcrypto`/`vector` 는 **이 initial 마이그레이션에서만** 생성/삭제한다.
> **후속 마이그레이션에서는 extension 을 drop 하지 않는다** (공유 자원).

---

## 4. 타입 규칙

| 종류 | 규칙 |
|---|---|
| UUID PK | postgres `uuid`, 기본값 `gen_random_uuid()` |
| 종목코드/ticker/corp_code | **varchar (문자열)**. 숫자 타입 금지(앞자리 0 보존) |
| created_at / as_of | `timestamptz` (created_at 은 서버 기본값 `now()`) |
| base_date | `date` |
| JSON | `jsonb` |
| news.embedding | `vector` (pgvector, **차원 미지정** — §7 참고) |

---

## 5. 테이블 카탈로그 (22개, 도메인별)

### Common
| 테이블 | 요약 | PK |
|---|---|---|
| `stocks` | 종목 마스터(코드·이름·시장) | `stock_code` (varchar) |
| `agent_reports` | 전 에이전트 리포트 통합 인덱스 | `id` (uuid) |

### Fundamental (재무)
| 테이블 | 요약 |
|---|---|
| `fundamental_reports` | 재무 분석 리포트 root |
| `report_ratios` | 재무 비율(roe·부채비율 등) |
| `report_evidence` | 비율/주장의 DART 원천 근거 |
| `fundamental_report_interpretations` | LLM/규칙 해석 (1:1) |
| `fundamental_report_verifications` | 검증 결과 (1:1) |
| `report_insights` | 배당/주주/감사 등 맥락 인사이트 |
| `report_filing_snippets` | 공시 원문 스니펫 |

### Technical (기술적)
| 테이블 | 요약 |
|---|---|
| `technical_reports` | 기술적 분석 리포트 root |
| `technical_report_signals` | 지표 신호 |
| `technical_report_charts` | 차트 페이로드 |
| `technical_report_risk_notes` | 리스크 노트 |
| `technical_report_interpretations` | 해석 (1:1) |
| `technical_report_verifications` | 검증 (1:1) |
| `technical_report_followups` | 후속 질의 |

### News (뉴스, PostgreSQL 부분만)
| 테이블 | 요약 |
|---|---|
| `news` | 기사 원본. `embedding vector`, `event_id`(Neo4j 논리 링크) |
| `news_reports` | 뉴스 질의 결과 리포트 (`report_id` PK) |

### Flow (수급)
| 테이블 | 요약 |
|---|---|
| `flow_reports` | 수급/자금흐름 리포트 root |
| `flow_report_interpretations` | 해석 (1:1) |
| `flow_report_verifications` | 검증 (1:1) |

### Industry (산업/섹터 — 5번째 에이전트 placeholder)
| 테이블 | 요약 |
|---|---|
| `industry_reports` | 산업/섹터 리포트 placeholder(세부 ERD 미정, request/answer 최소 컬럼) |

> **명칭 확정:** 5번째 에이전트는 **industry(산업/섹터)** 로 확정. 과거 스캐폴드/논의의
> `macro` 명칭은 폐기했고 테이블은 `industry_reports` 다.

---

## 6. 관계 (PostgreSQL 한정 Mermaid)

Neo4j 그래프(EVENT/COMPANY/SECTOR/…)는 **PostgreSQL 테이블이 아니다**(§8). 아래는 PG FK만.

```mermaid
erDiagram
    STOCKS ||--o{ AGENT_REPORTS : indexed_by
    STOCKS ||--o{ FUNDAMENTAL_REPORTS : analyzed_in

    FUNDAMENTAL_REPORTS ||--o{ REPORT_RATIOS : contains
    FUNDAMENTAL_REPORTS ||--o{ REPORT_EVIDENCE : has
    REPORT_RATIOS ||--o{ REPORT_EVIDENCE : proven_by
    FUNDAMENTAL_REPORTS ||--|| FUNDAMENTAL_REPORT_INTERPRETATIONS : explained_by
    FUNDAMENTAL_REPORTS ||--|| FUNDAMENTAL_REPORT_VERIFICATIONS : verified_by
    FUNDAMENTAL_REPORTS ||--o{ REPORT_INSIGHTS : contextualized_by
    FUNDAMENTAL_REPORTS ||--o{ REPORT_FILING_SNIPPETS : cites

    TECHNICAL_REPORTS ||--o{ TECHNICAL_REPORT_SIGNALS : contains
    TECHNICAL_REPORTS ||--o{ TECHNICAL_REPORT_CHARTS : has
    TECHNICAL_REPORTS ||--o{ TECHNICAL_REPORT_RISK_NOTES : observes
    TECHNICAL_REPORTS ||--|| TECHNICAL_REPORT_INTERPRETATIONS : explained_by
    TECHNICAL_REPORTS ||--|| TECHNICAL_REPORT_VERIFICATIONS : verified_by
    TECHNICAL_REPORTS ||--o{ TECHNICAL_REPORT_FOLLOWUPS : continues

    FLOW_REPORTS ||--|| FLOW_REPORT_INTERPRETATIONS : explained_by
    FLOW_REPORTS ||--|| FLOW_REPORT_VERIFICATIONS : verified_by
```

FK 전체 목록 (17개):

```
agent_reports.stock_code                        -> stocks.stock_code
fundamental_reports.stock_code                  -> stocks.stock_code
report_ratios.report_id                         -> fundamental_reports.id
report_evidence.report_id                       -> fundamental_reports.id
report_evidence.ratio_id (nullable)             -> report_ratios.id
report_insights.report_id                       -> fundamental_reports.id
report_filing_snippets.report_id                -> fundamental_reports.id
fundamental_report_interpretations.report_id(UQ)-> fundamental_reports.id
fundamental_report_verifications.report_id(UQ)  -> fundamental_reports.id
technical_report_signals.report_id              -> technical_reports.id
technical_report_charts.report_id               -> technical_reports.id
technical_report_risk_notes.report_id           -> technical_reports.id
technical_report_followups.report_id            -> technical_reports.id
technical_report_interpretations.report_id(UQ)  -> technical_reports.id
technical_report_verifications.report_id(UQ)    -> technical_reports.id
flow_report_interpretations.report_id(UQ)       -> flow_reports.id
flow_report_verifications.report_id(UQ)         -> flow_reports.id
```

**ON DELETE CASCADE** (자식 15개 FK): fundamental 7 + technical 6 + flow 2. report 삭제 시 자식이 함께 삭제된다. **`stocks` 참조 2개(agent_reports·fundamental_reports)는 마스터라 CASCADE 아님(NO ACTION).**

**FK 를 걸지 않는 것** (앱 레벨 논리 링크):
`agent_reports.agent_report_id`, `news.event_id`(Neo4j Event.canonical_id),
`news_reports.evidence`, 모든 `owner_user_id` / `owner_session_id`.

UNIQUE (9): `technical_reports.request_id`, `news.url`, **`technical_report_signals(report_id, indicator)`**, 그리고 1:1 report_id 6개(fundamental·technical·flow interpretations/verifications).

**NOT NULL 정책(핵심):** 항상 존재하는 실행 메타데이터와 degraded에도 sentinel로 채워지는 컬럼만 NOT NULL. 예) `technical_reports`: `request_id`·`ticker`·`data_status`·`source`·`trace_id`·`as_of`·`input_payload`·`output_payload`·`final_regime`·`daily_regime`·`alignment_flag` = NOT NULL / `consensus`·`signal_score`·`confidence`·`weekly_trend`·`monthly_trend` = nullable(정본 §9). `news`: `title`·`url` NOT NULL. 통합 ERD 신규 컬럼(`timeframe`, `chart_*`)은 저장 정책 확정 전까지 nullable.

명시 인덱스 (19, DESC 는 표현식 인덱스):
```
agent_reports        (agent_type, created_at DESC) / (client_session_id, created_at DESC)
                     / (stock_code, created_at DESC) / (trace_id)
fundamental_reports  (request_id) / (stock_code, as_of DESC) / (trace_id)
technical_reports    (client_session_id, created_at DESC) / (ticker, as_of DESC) / (trace_id)
technical_report_charts     (report_id, period)
technical_report_signals    UNIQUE(report_id, indicator)
technical_report_risk_notes (report_id, severity)
technical_report_followups  (report_id, created_at)
news                 (event_id) / (published_at)
news_reports         (created_at DESC)
flow_reports         (ticker, base_date DESC) / (trace_id)
```

---

## 7. news.embedding 차원(dimension) 미정

- 임베딩 모델은 `arctic-embed-l-v2.0-ko`(news `SCHEMA_SPEC.md`)지만 **차원 숫자가 코드/문서에
  확정돼 있지 않아**, 컬럼은 **차원 없는 `vector`** 로 생성했다.
- 유사도 검색용 **ANN 인덱스(ivfflat/hnsw)** 는 차원 확정 후 **별도 마이그레이션**에서 추가한다.
  (dimensionless vector 에는 ANN 인덱스를 만들 수 없다.)

---

## 8. Neo4j 경계 — PostgreSQL 에 만들지 않는 것

아래는 뉴스 에이전트의 **Neo4j logical graph** 이며 **PostgreSQL 테이블로 만들지 않는다.**

```
EVENT, COMPANY, SECTOR, NEWSREF, KEYWORD, PERSON, COUNTRY
```

PostgreSQL 에는 `news.event_id`(nullable uuid)만 둬서 Neo4j `Event.canonical_id` 를 **논리적으로**
가리킨다. DB FK 는 없다. Event↔News 연결은 backend app 레벨에서 처리한다.

---

## 9. 마이그레이션 규약 (Alembic, async)

- `backend/alembic.ini` + `backend/db/migrations/env.py`. env.py 는 **async(asyncpg)** 로 동작한다
  (`create_async_engine` + `connection.run_sync`). DSN 은 `src.api.config.settings.DATABASE_URL`.
- 모델을 추가하면 **반드시 `backend/db/models/registry.py` 에 import 를 등록**한다
  (env.py 가 `Base.metadata` 를 이걸로 채워 autogenerate 가 인식한다).

새 마이그레이션 만들기:

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://verith:verith1234@localhost:5433/verith"
uv run alembic revision --autogenerate -m "<메시지>"
uv run alembic upgrade head
```

> autogenerate 는 **`CREATE EXTENSION` 을 만들어주지 않는다.** 확장이 더 필요하면 수동으로
> `op.execute(...)` 를 넣되, 기존 `pgcrypto`/`vector` 는 이미 존재하므로 다시 만들지 않는다.

---

## 10. 검증 SQL

```bash
docker exec verith-postgres psql -U verith -d verith -c "
  SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','vector');
  SELECT count(*) FROM information_schema.tables
    WHERE table_schema='public' AND table_name<>'alembic_version';   -- 22
  SELECT format_type(atttypid,atttypmod) FROM pg_attribute
    WHERE attrelid='news'::regclass AND attname='embedding';         -- vector
"
```

기대: 확장 2개(pgcrypto, vector), public 테이블 22개, `news.embedding` = `vector`.

---

## 11. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `Connect call failed ('127.0.0.1', 5432)` | `.env`/DSN 이 5432 를 가리킴 → **5433** 으로 변경(§2) |
| `CREATE EXTENSION vector` 실패 / `type "vector" does not exist` | 이미지가 plain `postgres:16` → **`pgvector/pgvector:pg16`** 인지 확인(`docker inspect verith-postgres --format '{{.Config.Image}}'`) |
| `ValueError: the greenlet library is required` | async SQLAlchemy 용 greenlet 누락 → `uv sync`(deps 에 `sqlalchemy[asyncio]` 포함) |
| `NameError: pgvector` (마이그레이션 실행 중) | 마이그레이션 상단 `import pgvector.sqlalchemy.vector` 확인 |
| `insert or update on "agent_reports" violates foreign key ... stocks` | 저장 순서 문제 — **`stocks` 를 먼저 upsert** 한 뒤 `agent_reports`/report 를 저장(§12) |
| `database "verith" has a collation version mismatch` (경고) | 개발 볼륨/OS locale 차이. 무해. 필요 시 `ALTER DATABASE verith REFRESH COLLATION VERSION` |

---

## 12. 저장 담당자를 위한 주의 (후속 브랜치)

- **`agent_reports.stock_code` / `fundamental_reports.stock_code` → `stocks.stock_code` FK**:
  리포트를 저장하기 전에 해당 종목이 `stocks` 에 있어야 한다.
  권장: 리포트 저장 시 **`ticker`/`stock_name` 기준으로 `stocks` 를 upsert 한 뒤** 리포트를 저장.
  (배터리 종목 seed 를 미리 넣어도 되지만, upsert 가 결측에 강함.)
- `stock_code` 는 **nullable** 이다(뉴스/산업/거시성 질의는 종목이 없을 수 있음).
- 이 브랜치는 스키마만 만든다. 실제 파싱/저장/조회 로직은 각 에이전트 담당 브랜치 소관.
```
