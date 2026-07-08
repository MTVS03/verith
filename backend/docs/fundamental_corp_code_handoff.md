# Fundamental Corp Code Sync — Handoff

`docs/fundamental_corp_code_handoff.md`

이 문서는 Fundamental(재무) 담당자가 다음 브랜치에서 구현할 작업을 넘겨주기 위한 handoff 문서다.
목표는 Fundamental AI가 DART 기준으로 전체 종목을 다룰 수 있도록, backend에 `stock_code -> corp_code`
정본 경계를 만드는 것이다.

이 문서는 구현 지시와 범위를 다루며, PostgreSQL 물리 스키마 정본은 [`schema.md`](schema.md),
마이그레이션 절차는 [`migrations.md`](migrations.md), 현재 종목 식별 경계는
[`stock_resolver.md`](stock_resolver.md), KIS 종목 마스터 동기화는
[`stock_master_sync.md`](stock_master_sync.md) 를 따른다.

---

## 1. 배경

현재 backend는 다음을 갖고 있다.

- `stocks`: KIS/KRX 기준 공통 종목 마스터 (`stock_code`, `stock_name`, `market`)
- `stock_resolver`: 종목명/코드 식별
- `stock master sync`: KIS 종목마스터 기반 `stocks` 확장 경계

하지만 Fundamental AI는 아직 backend 정본을 직접 쓰지 않고, AI 내부의 10종 하드코딩
`CORP_CODE_MAP` 에 의존한다. 그 결과:

- backend `stocks` 가 전체 종목으로 확장돼도
- Fundamental AI는 여전히 10종만 지원할 수 있다

즉, 재무 쪽의 실제 병목은 `DART_API_KEY` 자체가 아니라 `stock_code -> corp_code`
정본 부재다.

---

## 2. 이번 브랜치 목표

이번 브랜치의 목표는 backend에 DART 기준 `stock_code -> corp_code` 정본 저장 경계를
구축하는 것이다.

이번 브랜치에서 한다:

- DART `corpCode.xml` downloader 구현
- ZIP/XML parser 구현
- `stock_code -> corp_code` sync 서비스 구현
- 저장용 DB 모델 + migration 추가
- dry-run / `--apply` / `--inspect` 수동 스크립트 추가
- repository accessor 추가
- fake fixture 기반 테스트 추가
- 문서 정리

이번 브랜치에서 하지 않는다:

- Fundamental AI 코드 직접 수정
- 조회 endpoint 추가
- supervisor / chat API wiring
- KIS stock master sync 변경
- `stock_resolver` 변경
- `stocks.stock_name` 을 DART 이름으로 덮어쓰기

---

## 3. 확정 결정

### 3.1 저장 구조

`B안` 채택: 별도 테이블 `stock_corp_codes`

이유:

- `stocks` 는 KIS/KRX 종목 마스터 역할을 유지해야 한다
- DART 이름은 KIS 이름과 다를 수 있으므로 분리 보관이 안전하다
- corp_code 계층은 fundamental 외에 industry/news 등 다른 에이전트에도 재사용 가능하다
- backend 종목 마스터와 DART 식별자 소유권이 분리된다

### 3.2 FK 정책

`no-FK` 채택: `stock_corp_codes.stock_code -> stocks.stock_code` 는 논리 링크로만 둔다.

이유:

- bootstrap 10종 seed 상태에 묶이지 않고 DART 상장 전체를 선반영할 수 있다
- KIS 종목 sync와 DART corp sync를 서로 독립적으로 운용할 수 있다
- 현재 단계에서는 공통 정본 확보가 더 중요하고, 강한 결합은 다음 단계에서 재검토 가능하다

### 3.3 이상치 정책

`fail-fast` 채택:

- 같은 `stock_code` 에 다른 `corp_code` 가 나오면 실패
- 같은 `corp_code` 가 여러 `stock_code` 로 나오면 실패
- 과소데이터(상장 row 0 / 보수 하한 미만)면 실패

다만 아래는 실패 사유로 보지 않는다:

- `corp_name_from_dart` 와 `stocks.stock_name` 차이
- `modify_date` 빈 값 또는 비정상 형식

---

## 4. 저장 스키마

신규 테이블:

```text
stock_corp_codes
  stock_code           varchar   PK
  corp_code            varchar   NOT NULL UNIQUE
  corp_name_from_dart  text      NOT NULL
  modify_date          varchar   NULL
  created_at           timestamptz NOT NULL default now()
  updated_at           timestamptz NULL
```

규칙:

- `stock_code` 는 문자열 유지(앞자리 0 보존)
- `corp_code` 는 DART 8자리 문자열
- `corp_name_from_dart` 는 DART 원문 이름 보존
- `modify_date` 는 원문 보존용 문자열
- `updated_at` 은 실제 row 변경 시에만 설정

주의:

- `stocks.stock_name` 은 KIS/KRX 기준 정본으로 유지한다
- DART 이름으로 `stocks` 를 업데이트하지 않는다

---

## 5. DART 파싱 규칙

근거:

- DART OpenAPI `corpCode.xml`
- 기존 AI fundamental 구현은 이미 이 포맷을 사용 중이나, backend는 이를 참고만 하고
  독자 구현한다(AI import 금지)

읽을 필드:

- `corp_code`
- `corp_name`
- `stock_code`
- `modify_date`

처리:

- `stock_code.strip()` 후 빈 값이면 제외(비상장/미연결 법인)
- `corp_code` 빈 값이면 이상치로 fail-fast
- `corp_name` 빈 값이면 이상치로 fail-fast
- `modify_date` 는 원문 보존
  - 빈 값이면 `NULL`
  - 비정상 형식이어도 sync 실패로 보지 않음

구현 원칙:

- ZIP download / unzip 책임과 XML parse 책임을 분리
- parser 는 순수 함수 유지
- 테스트는 fake ZIP/XML fixture 만 사용

---

## 6. Sync 정책

insert:

- 새 `stock_code -> corp_code` row 추가

update:

- `corp_code`
- `corp_name_from_dart`
- `modify_date`

중 하나라도 실제로 바뀌면 row 갱신 + `updated_at` 설정

delete / deactivate:

- 이번 브랜치에서는 하지 않음
- 이번 실행에서 DART 결과에 누락된 row 도 DB에 유지

실행 방식:

- 기본: dry-run
- `--apply`: commit
- `--inspect`: 샘플 row / 카운트 / 이상치 관찰용

운영 원칙:

- 실 네트워크 호출은 수동 script 에서만
- startup / pytest / app request path 에서 호출 금지
- 전체 파싱/검증 후 단일 트랜잭션으로 반영

---

## 7. 예상 파일

신규:

- `backend/src/api/clients/dart_corp_code_client.py`
- `backend/src/api/services/dart_corp_code_parser.py`
- `backend/src/api/services/corp_code_sync_service.py`
- `backend/db/models/common/stock_corp_code.py`
- `backend/src/api/repositories/corp_code_repository.py`
- `backend/scripts/sync_corp_codes.py`
- `backend/tests/test_dart_corp_code_client.py`
- `backend/tests/test_dart_corp_code_parser.py`
- `backend/tests/test_corp_code_sync_service.py`
- `backend/docs/dart_corp_code_sync.md`
- alembic migration 1개

수정:

- `backend/db/models/registry.py`
- `backend/src/api/config.py`
- `backend/README.md`
- `backend/docs/schema.md`

이번 브랜치에서 수정하지 않을 것:

- `backend/src/api/main.py`
- `backend/src/api/routes/*`
- `ai/src/agents/fundamental/**`
- `backend/src/api/services/stock_resolver_service.py`
- `backend/src/api/services/stock_sync_service.py`

---

## 8. 설정 정책

`DART_API_KEY` 는 backend 설정에 추가할 수 있다. 단:

- sync 스크립트/서비스 전용
- backend app startup 필수값으로 승격 금지
- `DATABASE_URL`, `AI_SERVICE_URL` 처럼 `_load_settings()` 에서 즉시 검증하지 않음

즉, 앱 전체를 띄우는 데 `DART_API_KEY` 가 없어도 되고,
corp code sync 를 실행할 때만 필요하게 만든다.

---

## 9. 테스트 원칙

필수:

- fake ZIP / fake XML fixture 기반
- 실 네트워크 0
- DB rollback 격리
- insert/update/no-delete/fail-fast 검증
- 빈 `stock_code`
- 중복 `stock_code`
- 중복 `corp_code`
- 빈/이상 `modify_date`

회귀 확인:

- 기존 technical / stocks / resolver / KIS sync 에 영향 없음

권장 검증 항목:

- parser 단위 테스트
- client unzip/error 단위 테스트
- sync 서비스 단위/통합 테스트
- alembic `check`
- ruff

---

## 10. 완료 조건

아래를 모두 만족하면 이 브랜치는 완료로 본다.

1. `stock_corp_codes` 모델 + migration 생성 완료
2. DART client / parser / sync / script 구현 완료
3. dry-run / `--apply` / `--inspect` 인터페이스 정리
4. fake fixture 기반 테스트 추가 완료
5. ruff / pytest / alembic check 통과
6. 문서 반영 완료
7. 실 네트워크 실행은 하지 않고, 마지막에만 승인 요청을 남김

---

## 11. 다음 브랜치(이번 범위 밖)

이번 브랜치가 끝난 뒤 다음 단계는 아래다.

### 11.1 Fundamental AI wiring

목표:

- AI 내부 `CORP_CODE_MAP` 제거 또는 fallback 격하
- Fundamental AI가 backend 정본 `stock_corp_codes` 를 소비

가능한 방식:

- 내부 endpoint 추가 후 HTTP 조회
- 또는 공통 service / repository 경계 소비

이번 브랜치에서는 결정/구현하지 않는다.

### 11.2 Supervisor 연결

목표:

- 사용자 질의
- `stock_resolver` 로 종목 식별
- 재무 요청이면 `stock_code + corp_code + canonical stock_name` 전달

이 역시 이번 브랜치 범위 밖이다.

---

## 12. 팀원에게 바로 전달할 구현 지시 요약

- `B안 + no-FK + fail-fast` 로 간다
- 신규 테이블은 `stock_corp_codes`
- DART `corpCode.xml` 기준으로 상장사(`stock_code` 있음)만 동기화
- `stocks` 는 안 건드리고, DART 이름은 별도 저장
- endpoint/AI wiring은 하지 않는다
- `DART_API_KEY` 는 sync 전용 설정
- fake ZIP/XML 기준으로 client/parser/sync/model/migration/script/test/docs 까지만 완결한다

