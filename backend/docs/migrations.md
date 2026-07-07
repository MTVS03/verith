# veriθ Backend — PostgreSQL 마이그레이션 가이드

`docs/migrations.md`

이 문서는 PostgreSQL 스키마를 변경하고 Alembic 마이그레이션을 검증하는 절차를 다룬다.
테이블·관계·제약의 정본은 [`schema.md`](schema.md), 로컬 실행은 [`../README.md`](../README.md)를
따른다.

## 1. 기본 규약

- `backend/alembic.ini`와 `backend/db/migrations/env.py`를 사용한다.
- Alembic 환경은 `asyncpg` 기반이며 `create_async_engine`과 `connection.run_sync`로 실행한다.
- DSN은 `src.api.config.settings.DATABASE_URL`에서 읽는다.
- 모델을 추가하면 `backend/db/models/registry.py`의 import와 `__all__`에 반드시 등록한다.
- DB 컬럼·테이블을 바꾸기 전에 `docs/schema.md`를 먼저 갱신한다.

## 2. 스키마 변경 절차

### 2.1 모델 작성

- `backend/db/models/<domain>/<file>.py`에 모델을 둔다.
- `db.models._shared.uuid_pk`와 `created_at`을 재사용한다.
- UUID PK, 문자열 종목코드, `timestamptz`, `jsonb`, `Decimal` 등은 `schema.md`의 타입 규칙을 따른다.
- report 종속 자식 FK에는 `ondelete="CASCADE"`를 사용한다.
- `stocks` 같은 마스터 참조에는 CASCADE를 사용하지 않는다.
- Neo4j 객체(Event/Company/…)를 PostgreSQL 테이블로 만들지 않는다.

### 2.2 registry 등록

새 모델 클래스를 `backend/db/models/registry.py`에 import하고 `__all__`에 추가한다. 등록하지 않으면
Alembic autogenerate가 모델을 인식하지 못한다.

### 2.3 revision 생성

```bash
cd backend
uv run alembic revision --autogenerate -m "<메시지>"
```

### 2.4 생성 파일 수동 점검

- 새 extension은 autogenerate되지 않으므로 필요한 경우 명시적으로 생성한다.
- `pgcrypto`와 `vector`는 initial migration에서만 생성·삭제하며 후속 migration에서 drop하지 않는다.
- pgvector 타입을 추가했다면 migration의 `pgvector.sqlalchemy.vector` import를 확인한다.
- DESC/표현식 인덱스가 `sa.text("... DESC")`로 렌더됐는지 확인한다.
- 자식 FK의 `ondelete="CASCADE"`, UNIQUE, NOT NULL이 모델 정책과 일치하는지 확인한다.

### 2.5 적용과 정합성 검증

```bash
uv run alembic upgrade head
uv run alembic check
uv run ruff check db src
```

아직 공유되지 않은 초기 migration을 검증할 때만 필요에 따라 왕복 테스트를 수행한다.

```bash
uv run alembic downgrade base
uv run alembic upgrade head
```

`downgrade base`는 모든 애플리케이션 테이블과 initial extension을 제거하므로 공유 개발 DB나 운영 DB에서
실행하지 않는다.

## 3. 공유된 migration 정책

- 브랜치 내부에서 아직 아무도 적용하지 않은 migration은 수정·재생성할 수 있다.
- 이미 공유·머지되어 팀원 DB에 적용된 migration은 수정하지 않는다.
- 공유 후 변경이 필요하면 새 revision에서 ALTER로 보강한다.
- 삭제된 revision을 팀원 DB의 `alembic_version`이 가리키는 상태를 만들지 않는다.

## 4. 검증 SQL

```bash
docker exec verith-postgres psql -U verith -d verith -c "
  SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','vector');
  SELECT count(*) FROM information_schema.tables
    WHERE table_schema='public' AND table_name<>'alembic_version';
  SELECT format_type(atttypid,atttypmod) FROM pg_attribute
    WHERE attrelid='news'::regclass AND attname='embedding';
"
```

현재 initial schema 기준 기대값은 extension 2개(`pgcrypto`, `vector`), 애플리케이션 테이블 22개,
`news.embedding=vector`다.

## 5. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `Connect call failed ('127.0.0.1', 5432)` | 호스트 실행 시 `DATABASE_URL`을 compose host 포트 5433으로 맞춘다. |
| `CREATE EXTENSION vector` 실패 | PostgreSQL 이미지가 `pgvector/pgvector:pg16`인지 확인한다. |
| `ValueError: the greenlet library is required` | `uv sync`로 `sqlalchemy[asyncio]` 의존성을 설치한다. |
| `NameError: pgvector` | migration 상단의 `import pgvector.sqlalchemy.vector`를 확인한다. |
| `agent_reports ... stocks` FK 위반 | `stocks`를 먼저 확보한 뒤 report/index를 저장한다. |
| collation version mismatch 경고 | 개발 볼륨/OS locale 차이로 발생할 수 있다. 필요 시 DB collation version을 갱신한다. |
