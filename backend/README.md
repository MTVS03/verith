# veriθ Backend

FastAPI 백엔드 — 요청을 받아 AI 에이전트를 호출하고, 결과 JSON을 검증·저장하고, 프론트에 제공한다.

- DB 구조·관계·제약 정본: [`docs/schema.md`](docs/schema.md)
- Alembic 변경·검증 절차: [`docs/migrations.md`](docs/migrations.md)

## 개발 환경

```bash
# 저장소 루트에서 PostgreSQL(+pgvector) 기동 (host 포트 5433)
docker compose up -d postgres

cd backend
uv sync
# DATABASE_URL은 환경변수 또는 backend/.env로 주입
# 호스트에서 compose DB에 연결할 때: postgresql+asyncpg://...@localhost:5433/...
uv run alembic upgrade head     # 스키마 적용
```

`DATABASE_URL`은 필수이며 환경변수가 `backend/.env`보다 우선한다. 드라이버는 `asyncpg`이므로
DSN 스킴은 `postgresql+asyncpg://`를 사용한다. 컨테이너 내부에서 연결할 때는 서비스명과 컨테이너
포트 5432를 사용하고, 호스트에서 연결할 때는 compose host 포트 5433을 사용한다.

## Seed stocks

Technical Agent / Stock Resolver 에서 쓸 **기본 종목 마스터(지원 10종 + market)** 를 `stocks` 에 seed 한다.

```bash
cd backend
uv run python -m scripts.seed_stocks
# 또는
uv run python scripts/seed_stocks.py
```

주의:
- PostgreSQL 이 실행 중이어야 하고, `DATABASE_URL`(포트 5433) 이 설정돼 있어야 한다.
- 스크립트는 **idempotent** — 여러 번 실행해도 안전하다.
- `INSERT ... ON CONFLICT(stock_code) DO NOTHING` 이라 **기존 stock row(이름/시장)를 덮어쓰지 않는다.**
  종목명·시장 수정이 필요하면 seed 가 아니라 별도 관리 작업으로 처리한다.

확인:

```sql
SELECT stock_code, stock_name, market FROM stocks ORDER BY stock_code;
```

## 테스트

```bash
cd backend
# TEST_DATABASE_URL 우선, 없으면 DATABASE_URL(backend/.env) 사용. PostgreSQL 필요.
uv run pytest
uv run ruff check db src tests scripts
uv run alembic check
```

마이그레이션 생성, downgrade 주의사항, 검증 SQL과 DB 트러블슈팅은
[`docs/migrations.md`](docs/migrations.md)에 정리돼 있다.
