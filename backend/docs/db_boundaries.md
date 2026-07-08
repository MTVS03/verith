# DB 역할 경계 (canonical / dev·smoke / test)

`docs/db_boundaries.md`

**핵심: "어느 DB가 canonical truth인지"를 역할별로 분리한다.** 하나의 공유 DB(dev=test=smoke)를 계속
끌고 가면 운영 `--apply`/seed 커밋이 테스트 전제를 오염시키는 문제가 반복된다. 같은 PostgreSQL
인스턴스(`verith-postgres`, host `:5433`, user `verith`)에 **역할별 DB**를 둔다.

## 역할 표
| DB | 역할 | 내용 | 접속 경계 |
|---|---|---|---|
| **`verith_canonical`** | **canonical stocks 정본** | KIS master sync 전체 주권 **2,607**(KOSPI 893 + KOSDAQ 1,714) + battery/representative alias | `sync_stocks --apply` 대상. (app runtime 승격은 후속 결정) |
| `verith` | dev / smoke (현행 app runtime) | bootstrap 13종 + DART corp_codes 등 혼재 | `DATABASE_URL` — app·scripts·alembic |
| **`verith_test`** | **pytest 전용(clean)** | 스키마만(migrate). 테스트가 in-tx seed·rollback 격리 | `TEST_DATABASE_URL` — pytest |

## URL 경계
- **`DATABASE_URL`**: app runtime(FastAPI) · `scripts/*`(seed/sync) · `alembic`. 현재 `verith`.
- **`TEST_DATABASE_URL`**: pytest 만(`tests/conftest.py`). **전용 `verith_test`** 를 가리켜야 한다.
  미설정/앱 DB와 동일하면 conftest 가 **경고**(오염 위험 노출).
- **canonical stock sync**(`sync_stocks --apply`)는 **canonical DB(verith_canonical)** 에 적용한다.
  공유 `verith` 에는 --apply 하지 않는다(테스트 오염 방지).

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

## runtime 전환 readiness (verith_canonical 검증 완료)
app runtime `DATABASE_URL` 을 `verith_canonical` 로 바꿔도 되는지 dry-run 으로 확인했다.

| 항목 | 상태 | 근거 |
|---|---|---|
| stocks | ✅ | 2,607 주권(verith 13 대비 상위 정본) |
| stock_aliases | ✅ | 32(battery+representative seed 동일) |
| **stock_corp_codes** | ✅ | **3,976 정렬 완료**(verith→canonical 복사; DART 재다운로드 제한으로 검증된 데이터 복사) |
| reports/news | ✅ | 양쪽 0 — 전환 시 손실 데이터 없음 |
| app startup | ✅ | `src.api.main` import OK(라우트 10개 로드) on canonical |
| resolver(broader) | ✅ | NAVER/SK하이닉스/셀트리온 exact resolved, LG ambiguous, synthetic not_found |
| report CRUD / save | ✅ | technical/news/stock-resolve API + resolver **59 passed** on canonical |
| fundamental save | ✅ | 저장 경로 정상. `test_fundamental_contract_violation_rejected` 만 실패 = **fake AI output fixture 의 `meta.erd_payload.fundamental_report` 부재**(develop 머지 스키마 변경) — DB/runtime blocker 아님 |

**결론: DATABASE_URL → verith_canonical 전환 가능(하드 blocker 0).** 단 이번 브랜치는 **전환 확정이
아니라 준비 확인** 단계이므로 `.env` 의 `DATABASE_URL` 은 바꾸지 않는다(실전 전환은 별도 브랜치).

## 후속(이번 브랜치 밖)
- **실전 전환 브랜치**: `.env` `DATABASE_URL` → `verith_canonical` 로 변경 + 앱/스모크 재기동 검증.
  (선행 corp_code 정렬은 이번에 완료. fundamental fixture 이슈는 병행 정리.)
- fundamental contract-violation 테스트 fixture(`meta.erd_payload.fundamental_report`) 수정.
- delete/deactivate·상장폐지 lifecycle, sync 이력, alias 운영 경계, min_count 상향.
