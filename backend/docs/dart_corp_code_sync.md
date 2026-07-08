# DART Corp Code Sync — corpCode.xml → stock_corp_codes

`docs/dart_corp_code_sync.md`

Backend 가 **DART 법인식별 정본**(`stock_code → corp_code`)을 DART OpenAPI `corpCode.xml` 로
동기화하는 경계의 정본. 물리 스키마는 [`schema.md`](schema.md), KIS 종목 마스터 동기화는
[`stock_master_sync.md`](stock_master_sync.md).

> **AI 패키지 import 없음.** 파싱 규칙은 DART 공식 응답 포맷을 근거로 backend 가 독자 구현한다.
> **이번 단계는 sync 기반 구현이며, 실제 전체 적용은 수동 `--apply` 로만** 한다.

## 1. 왜 별도 계층인가 (stocks 와의 경계)
- `stocks` = **KIS/KRX 종목 마스터**(`stock_code`·`stock_name`·`market`). 종목명 정본.
- `stock_corp_codes` = **DART 법인식별 정본**(`stock_code`→8자리 `corp_code`). 재무(Fundamental)
  에이전트가 DART 조회 전에 필요한 식별자.
- **출처가 다르다.** 서로의 정본을 덮지 않는다 — DART 공시명은 `corp_name_from_dart` 에만 두고
  `stocks.stock_name` 을 절대 덮어쓰지 않는다.
- **의도적 no-FK.** `stock_code → stocks` 물리 FK 를 걸지 않는다. DART 상장 전체를 `stocks` 적재
  상태(현재 bootstrap 10종)와 무관하게 **선반영**할 수 있게 결합을 끊는다. fundamental/industry/news
  공용 식별자 계층으로 확장 가능.

## 2. 데이터 출처 (공식 근거)
- DART OpenAPI endpoint: `https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=...`
- 응답: **ZIP** → 내부 `CORPCODE.xml`.
- 각 `<list>` 노드 필드:

| 필드 | 필수/옵션 | 처리 |
|---|---|---|
| `corp_code` | 필수(8자리) | 저장. 상장 행에서 결측이면 **fail-fast** |
| `corp_name` | 필수 | `corp_name_from_dart` 에 저장(**stocks.stock_name 안 덮음**) |
| `stock_code` | 옵션(상장 6자리 / 비상장 빈값) | `.strip()` 후 **빈 값이면 제외**(상장사만 대상) |
| `modify_date` | 옵션(YYYYMMDD) | 8자리 숫자면 원문 보존, 아니면 **NULL + count**(제외·실패 아님) |

## 3. 이상치 정책 (fail-fast)
- 같은 `stock_code` 중복 / 같은 `corp_code` 중복 → **fail-fast**(파서, 부분 반영 방지).
- 상장 행에 `corp_code`/`corp_name` 결측 → **fail-fast**.
- 빈 `stock_code`(비상장/기타 법인) → 이상치 아님, 제외(`non_listed` count).
- `modify_date` 형식 이상 → 이상치 아님, `NULL` 저장(`invalid_modify_date` count).
- DART 공시명 ≠ KIS `stock_name` → 정상. `corp_name_from_dart` 에만 보관(정본 안 덮음).

## 4. 동기화 정책
- **신규 stock_code → INSERT / (`corp_code`·`corp_name_from_dart`·`modify_date`) 실제 변경 → UPDATE /
  변경 없음 → 그대로.**
- **누락 매핑(DART 응답에 없음) → 삭제·비활성화 안 함.** 한 번의 누락으로 상장폐지 판단하지 않는다.
- `updated_at` 은 **실제 값 변경이 있을 때만** 갱신(전체 row 무조건 갱신 금지).
- **다운로드·파싱·검증 완료 후 단일 트랜잭션**. commit 여부는 호출자(script)가 결정.
- 앞자리 0·문자열 `stock_code`·8자리 `corp_code` 보존.

## 5. 안전장치(과소 데이터)
- 상장 record 0건 → 실패. 보수적 **하한 미만 → 실패**(기본 500 — 실제 규모 ~2,8xx 보다 훨씬 낮게 둬
  손상·빈 응답만 잡는다. 정확한 하한은 실데이터 검산 후 확정, 코드에 실수 고정 금지).

## 6. 설정 (`DART_API_KEY`)
- `src/api/config.py` 에 `DART_API_KEY`(+`DART_BASE_URL`) 가 있으나 **sync 전용**이다.
- **app startup 필수값이 아니다** — `_load_settings()` 의 필수 검증(`DATABASE_URL`·`AI_SERVICE_URL`)에
  포함하지 않는다. 값 존재는 **sync 실행 시점**(client)에서만 검증한다.
- 키는 **secret** — URL/로그/예외 메시지에 노출하지 않는다(존재 여부만).

## 7. 실행 (수동 전용 — 네트워크)
```bash
cd backend
uv run python -m scripts.sync_corp_codes             # dry-run: 다운로드·파싱·검증·diff, DB 미변경(기본)
uv run python -m scripts.sync_corp_codes --inspect    # 파싱 요약·샘플 행 검산, DB 미변경
uv run python -m scripts.sync_corp_codes --apply       # 실제 반영(commit)
```
- **기본은 dry-run**(DB 미변경). `--apply` 일 때만 commit.
- `--inspect` 는 상장/비상장/`invalid_modify_date` 카운트와 샘플 행을 출력해 실데이터를 검산한다.
- ⚠️ 실행 전 외부 네트워크 호출·DB 변경 여부(dry-run/`--apply`)를 확인하고 승인 후 실행한다.
- 앱 startup·pytest 에서 실행하지 않는다. 테스트는 fake ZIP/XML fixture 를 쓴다.

## 8. Fundamental 후속 연결 (이번 브랜치 범위 밖)
- 현재 재무 AI 는 내부 `CORP_CODE_MAP`(10종 하드코딩)에 의존한다.
- 이번 브랜치는 **backend 정본 저장·sync·repository·문서까지**만 한다. **AI 코드는 건드리지 않는다.**
- 조회 endpoint·AI wiring·Top Supervisor 연결은 **다음 브랜치**. 진입점은
  `src/api/repositories/corp_code_repository.py`(`get_corp_code(stock_code)`), 그 위에 내부 조회
  endpoint 를 얹을지는 다음 브랜치에서 timeout·인증·경계와 함께 설계한다.

## 9. 현재 한계 / 후속
- 이번 브랜치는 `stock_corp_codes` **테이블 1개 migration** 만 추가한다(다른 스키마 변경 없음).
- 상장폐지·sync 이력(예: `corp_code_sync_runs`)은 데이터·정책 확정 후 별도.
- 실데이터 `--apply` 는 아직 수행 전 — dry-run/`--inspect` 검산 후 승인받아 실행한다.
