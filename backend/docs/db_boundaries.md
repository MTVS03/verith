# DB 역할 경계 (canonical / dev·smoke / test)

`docs/db_boundaries.md`

**핵심: "어느 DB가 canonical truth인지"를 역할별로 분리한다.** 하나의 공유 DB(dev=test=smoke)를 계속
끌고 가면 운영 `--apply`/seed 커밋이 테스트 전제를 오염시키는 문제가 반복된다. 같은 PostgreSQL
인스턴스(`verith-postgres`, host `:5433`, user `verith`)에 **역할별 DB**를 둔다.

## 역할 표
| DB | 역할 | 내용 | 접속 경계 |
|---|---|---|---|
| **`verith_canonical`** | **canonical stocks 정본 + app runtime (ACTIVE)** | KIS master sync 전체 주권 **2,607**(KOSPI 893 + KOSDAQ 1,714) + battery/representative alias + corp_codes **3,976** | `DATABASE_URL` — app·scripts·alembic·`sync_stocks --apply` |
| `verith` | **legacy(전환 완료로 runtime 아님)** | bootstrap 13종 + corp_codes 혼재. 참고/과거용 | (더 이상 참조 안 함) |
| **`verith_test`** | **pytest 전용(clean)** | 스키마만(migrate). 테스트가 in-tx seed·rollback 격리 | `TEST_DATABASE_URL` — pytest |

> **전환 완료(2026-07):** app runtime `DATABASE_URL` 을 `verith` → **`verith_canonical`** 로 전환했다
> (`.env`, gitignore = 로컬 변경). `TEST_DATABASE_URL=verith_test` 는 불변. **테스트 DB 와 runtime DB 를
> 다시 혼용하지 않는다.**

## URL 경계
- **`DATABASE_URL`** = **`verith_canonical`**(ACTIVE): app runtime(FastAPI) · `scripts/*`(seed/sync) · `alembic`.
- **`TEST_DATABASE_URL`** = **`verith_test`**: pytest 만(`tests/conftest.py`). 미설정/앱 DB와 동일하면
  conftest 가 **경고**(오염 위험 노출).
- **canonical stock sync**(`sync_stocks --apply`)는 이제 `DATABASE_URL`(=canonical)에 적용된다.

## 원칙
- **canonical source = KIS master sync DB(verith_canonical)**. `seed_stocks`(battery 10)·
  `seed_representative_stocks`(대표 3)는 **bootstrap/보조**(제거 아님, fresh/오프라인 dev 편의).
- **shared `verith` 는 더 이상 canonical truth 가 아니다.** dev/smoke 편의 DB.
- **sync 는 별도 관리 명령**(`--inspect`/dry-run/`--apply`). **질문 처리 경로(resolver/supervisor/agents)는
  read-only** — 질문 처리 중 stocks 를 자동 insert/update 하지 않는다.
- **alias 는 수동/운영 큐레이션**. sync 는 `stocks` 만 갱신하고 `stock_aliases` 는 손대지 않는다.

## 테스트 오염 해소(검증)
- 전용 `verith_test`(clean)로 pytest → `corp_code_sync` 4건(공유 `verith` 의 3,976 corp_codes commit 전제
  충돌)이 **해소**됨. `test_fundamental_reports` 1건은 DB 오염이 아니라 **코드 이슈**(develop 머지)로 잔존 —
  별도 조사.
- boundary/semantics/resolver 테스트는 실존 종목 가정을 **synthetic 코드**로 분리해 universe 확장에도
  의미 유지(`test_stock_resolver.py`).

## 설정 방법
```bash
# 같은 인스턴스에 역할별 DB 생성(최초 1회) — verith user 는 superuser.
docker exec verith-postgres psql -U verith -d postgres -c "CREATE DATABASE verith_canonical;"
docker exec verith-postgres psql -U verith -d postgres -c "CREATE DATABASE verith_test;"
# 각 DB 스키마
DATABASE_URL=postgresql+asyncpg://verith:verith1234@localhost:5433/verith_canonical uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://verith:verith1234@localhost:5433/verith_test        uv run alembic upgrade head
# canonical 에 전체 주권 반영
DATABASE_URL=…/verith_canonical uv run python -m scripts.sync_stocks --apply
```
`backend/.env` 에 `TEST_DATABASE_URL=…/verith_test` 를 두면 pytest 가 전용 test DB 를 쓴다.
> **collation 주의:** 볼륨이 다른 libc 로 생성된 경우 `CREATE DATABASE` 가 template1 collation mismatch 로
> 실패할 수 있다 → `ALTER DATABASE template1 REFRESH COLLATION VERSION;`(postgres·verith 동일) 후 재시도.

## runtime 전환 완료 (verith_canonical = ACTIVE)
app runtime `DATABASE_URL` 을 `verith_canonical` 로 **전환 완료**하고 canonical 기준으로 smoke 검증했다.

| 항목 | 상태 | 근거(canonical runtime) |
|---|---|---|
| stocks / aliases / corp_codes | ✅ | 2,607 주권 / 32 alias / 3,976 corp_codes |
| reports/news | ✅ | 손실 데이터 없음(양쪽 0) |
| app startup | ✅ | `src.api.main` import OK(라우트 10개) on canonical |
| resolver(broader) | ✅ | 삼성전자·NAVER·SK하이닉스·셀트리온 exact / LG ambiguous[003550·051910·373220] / synthetic not_found |
| representative 회귀 | ✅ | LG에너지솔루션·카카오·삼성전자우 정상 resolved |
| report CRUD / save | ✅ | technical/news/stock-resolve API + resolver 검증(dry-run 59 passed) |
| read-only 원칙 | ✅ | resolve smoke 후 canonical stocks 수 불변(2,607) — 질문 경로 자동 write 없음 |

**broader universe 는 의도된 변화(release note 급):** 전환으로 예전 `not_found` 였던 종목(NAVER·SK하이닉스·
셀트리온 등)이 이제 `resolved` 되고, "LG" 는 (주)LG(003550) 포함으로 더 정확히 `ambiguous` 된다. **버그가
아니라 canonical 승격의 결과.**

## 후속(이번 브랜치 밖)
- **fundamental contract-violation 테스트 fixture 수정**(`meta.erd_payload.fundamental_report` 부재 —
  DB/runtime blocker 아님, `verith_test` 기준 pytest 유일 실패). runtime 전환과 무관해 분리한다.
- 실행 중인 backend(:8000)는 전환 전 `.env`(verith)로 떠 있을 수 있으니 **재기동해야** canonical 반영.
- delete/deactivate·상장폐지 lifecycle, sync 이력, alias 운영 경계, min_count 상향.
