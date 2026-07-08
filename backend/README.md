# veriθ Backend

FastAPI 백엔드 — 요청을 받아 AI 에이전트를 호출하고, 결과 JSON을 검증·저장하고, 프론트에 제공한다.

- DB 구조·관계·제약 정본: [`docs/schema.md`](docs/schema.md)
- Alembic 변경·검증 절차: [`docs/migrations.md`](docs/migrations.md)
- Stock Resolver 응답 의미·경계: [`docs/stock_resolver.md`](docs/stock_resolver.md)
- 전체 종목 마스터 동기화(KIS): [`docs/stock_master_sync.md`](docs/stock_master_sync.md)
- DART 법인코드 동기화(corp_code): [`docs/dart_corp_code_sync.md`](docs/dart_corp_code_sync.md)

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

`stocks` 에 **개발 bootstrap 종목(10종 + market)** 을 seed 한다.

> ⚠️ **이 10종은 개발 bootstrap 데이터이지 전체 종목 정본이 아니다.** Stock Resolver 는 종목 수와
> 무관한 공통 구조지만, 현재 실제 식별 가능한 범위는 seed 된 10종뿐이다. 전체 KRX 종목 지원은 후속
> 마스터 동기화 작업(별도 브랜치)이 완료돼야 한다 — [`docs/stock_resolver.md`](docs/stock_resolver.md) §5.
> `stocks`(공통 마스터)와 Technical 10종 지원 정책(`BATTERY_TICKERS`)은 **별개**다.

```bash
cd backend
# 순서 중요: 종목 마스터 먼저, 그다음 Stock Resolver 별칭.
uv run python -m scripts.seed_stocks
uv run python -m scripts.seed_stock_aliases
```

주의:
- PostgreSQL 이 실행 중이어야 하고, `DATABASE_URL`(포트 5433) 이 설정돼 있어야 한다.
- 두 스크립트 모두 **idempotent** (`ON CONFLICT ... DO NOTHING`) — 여러 번 실행해도 기존 row 를 덮지 않는다.
- `seed_stock_aliases` 는 참조 종목이 `stocks` 에 없으면 **부분 seed 없이 fail-fast** 하므로 반드시 `seed_stocks` 를 먼저 실행한다.
- 별칭 정본은 `src/api/constants/stock_aliases.py`(변형만 — 공식 이름은 `stocks.stock_name`).

**전체 종목 마스터 동기화(bootstrap 과 별개, 수동·네트워크):** 개발 10종 seed 는 bootstrap 이고, 전체
국내 종목은 KIS 마스터를 `sync_stocks` 로 동기화한다. 기본 dry-run(DB 미변경), `--apply` 에서만 반영.
```bash
uv run python -m scripts.sync_stocks            # dry-run
uv run python -m scripts.sync_stocks --inspect   # 앵커 검산(DB 미변경)
uv run python -m scripts.sync_stocks --apply      # 실제 반영(commit)
```
자세한 출처·파싱·포함/제외·정책은 [`docs/stock_master_sync.md`](docs/stock_master_sync.md).

**DART 법인코드 동기화(별도 계층, 수동·네트워크):** 재무(Fundamental) 에이전트가 DART 조회 전에 쓰는
`stock_code → corp_code` 정본을 DART `corpCode.xml` 로 동기화한다(`stock_corp_codes`, stocks 와 no-FK 별도
계층). 기본 dry-run, `--apply` 에서만 반영. `DART_API_KEY`(sync 전용, startup 필수 아님)가 필요하다.
```bash
uv run python -m scripts.sync_corp_codes            # dry-run
uv run python -m scripts.sync_corp_codes --inspect   # 파싱 요약·샘플 검산(DB 미변경)
uv run python -m scripts.sync_corp_codes --apply      # 실제 반영(commit)
```
자세한 출처·파싱·이상치·정책은 [`docs/dart_corp_code_sync.md`](docs/dart_corp_code_sync.md).

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
