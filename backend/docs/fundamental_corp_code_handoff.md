# Fundamental Backend Handoff

`docs/fundamental_corp_code_handoff.md`

이 문서는 Fundamental(재무) 담당자가 backend 쪽 구현을 이어받을 때 참고할 handoff 문서다.
목표는 **이미 구축된 backend 정본 계층**을 바탕으로, Fundamental AI가 DART 기준으로 전체 종목을
다룰 수 있게 다음 단계를 정리하는 것이다.

중요: 이 문서는 더 이상 “`stock_code -> corp_code` 정본을 새로 만드는 문서”가 아니다.
그 작업은 **이미 완료되었고 실데이터까지 반영**되었다.
이제 다음 작업은 그 정본을 **fundamental이 어떻게 소비할지 연결하는 것**이다.

이 문서는 구현 지시와 범위를 다루며, PostgreSQL 물리 스키마 정본은 [`schema.md`](schema.md),
마이그레이션 절차는 [`migrations.md`](migrations.md), 현재 종목 식별 경계는
[`stock_resolver.md`](stock_resolver.md), KIS 종목 마스터 동기화는
[`stock_master_sync.md`](stock_master_sync.md), 전체 Supervisor/Backend 연결은
[`supervisor_backend_integration.md`](supervisor_backend_integration.md) 를 따른다.

---

## 1. 현재 상태 요약

현재 backend는 이미 아래 공통 기반을 갖고 있다.

- `stocks`
  - KIS/KRX 기준 공통 종목 마스터
  - `stock_code`, `stock_name`, `market`
- `stock_resolver`
  - 자연어에서 종목/회사 식별
- `stock master sync`
  - KIS 종목마스터 기반 `stocks` 확장 경계
- `stock_corp_codes`
  - DART 기준 `stock_code -> corp_code` 정본 계층

즉, 재무 쪽의 “정본 부재” 문제는 이미 해결되었다.
이제 남은 건 Fundamental AI가 backend 정본을 **실제로 소비하도록 연결하는 것**이다.

---

## 2. 이번 문서가 넘겨주는 핵심

이번 handoff의 핵심은 아래 2개다.

1. `stock_corp_codes` 정본 계층은 이미 완료되었고, 재구현 대상이 아니다
2. 다음 Fundamental backend/AI 브랜치의 본질은
   - backend 정본 소비 경계 만들기
   - AI의 `CORP_CODE_MAP` 의존 제거 방향 설계

즉, 다음 fundamental 관련 브랜치는 더 이상 “sync 구현”이 아니라
**“정본 소비 전환” 브랜치**로 이해하면 된다.

---

## 3. 이미 완료된 것

### 3.1 저장 구조

신규 테이블 `stock_corp_codes` 가 이미 존재한다.

```text
stock_corp_codes
  stock_code           varchar   PK
  corp_code            varchar   NOT NULL UNIQUE
  corp_name_from_dart  text      NOT NULL
  modify_date          varchar   NULL
  created_at           timestamptz NOT NULL default now()
  updated_at           timestamptz NULL
```

원칙:

- `stocks` 와 **역할이 다른 별도 계층**
- `stock_code -> stocks.stock_code` 는 **no-FK 논리 링크**
- `corp_name_from_dart` 는 DART 공시명 원문
- `stocks.stock_name` 정본은 절대 덮어쓰지 않음

### 3.2 DART sync 경계

아래 구성은 이미 구현돼 있다.

- client
  - `backend/src/api/clients/dart_corp_code_client.py`
- parser
  - `backend/src/api/services/dart_corp_code_parser.py`
- sync service
  - `backend/src/api/services/corp_code_sync_service.py`
- repository
  - `backend/src/api/repositories/corp_code_repository.py`
- script
  - `backend/scripts/sync_corp_codes.py`
- migration
  - `20260708_6ca978063906_add_stock_corp_codes.py`

### 3.3 정책

이미 확정된 정책:

- `B안`: `stocks` 와 분리된 별도 테이블
- `no-FK`: `stock_code -> stocks.stock_code` 는 논리 링크
- `fail-fast`
  - 같은 `stock_code` 에 다른 `corp_code`
  - 같은 `corp_code` 에 다른 `stock_code`
  - 과소데이터
- `delete/deactivate` 없음
- `updated_at` 은 실제 변경 시에만 갱신
- `DART_API_KEY` 는 sync 전용, app startup 필수값 아님

### 3.4 실데이터 반영 상태

실데이터 기준 상태:

- `stock_corp_codes` 3,976행 반영 완료
- 대표 종목 매핑 검증 완료
  - 삼성전자 `00126380`
  - 카카오 `00258801`
  - LG화학 `00356361`
- 재-dry-run 결과 멱등 확인
  - `inserted=0`
  - `updated=0`
  - `unchanged=3976`

즉 이 계층은 이제 “설계 단계”가 아니라 **실반영 완료된 정본 계층**이다.

---

## 4. 왜 이 구조가 맞는가

### 4.1 `stocks` 와 분리한 이유

`stocks` 는 KIS/KRX 종목 마스터 역할을 유지해야 한다.

반면 `stock_corp_codes` 는:

- DART 식별자 계층
- `stock_code -> corp_code`
- DART 이름(`corp_name_from_dart`) 보관

을 맡는다.

즉 출처도 다르고, 정본도 다르다.
둘을 섞지 않는 것이 맞다.

### 4.2 no-FK 이유

`stock_corp_codes` 에 물리 FK를 걸지 않은 이유는:

- bootstrap 10종 seed 상태에 묶이지 않기 위해
- DART 상장 전체를 선반영하기 위해
- KIS `stocks` sync 와 DART corp sync 를 독립적으로 운영하기 위해

이 구조는 fundamental 뿐 아니라 industry/news 쪽 식별자 계층으로도 재사용 가능하다.

---

## 5. Fundamental AI의 현재 병목

현재 Fundamental AI는 아직 backend 정본을 직접 쓰지 않고,
AI 내부의 하드코딩 `CORP_CODE_MAP` 에 의존한다.

그 결과:

- backend `stocks` 가 전체 종목으로 확장돼도
- backend `stock_corp_codes` 가 실데이터로 채워져 있어도
- Fundamental AI는 여전히 10종 중심 구조에 묶일 수 있다

즉 지금의 실제 병목은 DART 키가 아니라,
**backend 정본 소비 경계가 아직 붙지 않은 것**이다.

---

## 6. 다음 브랜치의 목표

다음 fundamental 관련 브랜치의 목표는 아래다.

### 6.1 해야 하는 것

- backend 정본(`stock_corp_codes`) 소비 경계 만들기
- `stock_code` 기준으로 `corp_code` 를 안정적으로 조회할 수 있게 하기
- Fundamental AI가 장기적으로 `CORP_CODE_MAP` 대신 backend 정본을 보도록 전환하기

### 6.2 이번 handoff 기준 추천 범위

추천:

- `corp_code_repository.get_corp_code(stock_code)` 를 기준 진입점으로 사용
- 필요 시 내부 조회 endpoint 추가
- Supervisor가 넘긴 `stock_code` 를 fundamental 쪽 입력으로 소비
- fundamental agent가 backend 정본을 통해 `corp_code` 를 확보하게 연결

이번 단계에서 하지 말 것:

- `stock_corp_codes` 재구현
- DART sync 재설계
- `stocks.stock_name` 을 DART 이름으로 덮어쓰기
- `stock_resolver` 로직 변경

---

## 7. 추천 연결 구조

전체 흐름은 아래처럼 보는 것이 좋다.

```text
사용자 질문
  ↓
Supervisor
  - 필요 시 stock_resolver 호출
  - stock_code / stock_name / market context 생성
  ↓
Fundamental task
  ↓
backend corp_code 조회 경계
  - stock_code -> corp_code
  ↓
Fundamental AI가 DART 조회 수행
```

핵심:

- Supervisor는 우선 `stock_code` context만 안정적으로 주면 된다
- `corp_code` 는 Supervisor가 추정하지 않는다
- Fundamental이 backend 정본을 소비해서 가져가는 구조가 맞다

---

## 8. 권장 backend 후속 구현 범위

다음 fundamental backend/연결 브랜치에서 추천하는 범위는 아래다.

### 8.1 repository accessor 재사용

이미 존재:

- `get_corp_code(stock_code)`

이 accessor를 먼저 기준점으로 둔다.

### 8.2 내부 조회 경계

선택적으로 추가 가능:

- 내부 service
- 내부 endpoint
- AI용 thin client

중요:

- DB 직접 접근보다 경계를 두는 쪽이 장기적으로 안전
- timeout / auth / observability 도 여기서 제어 가능

### 8.3 AI 전환

장기 방향:

- `CORP_CODE_MAP` 제거
- backend 정본 우선
- 정본 없으면 명시적 미지원/미식별 처리

즉 LLM이나 AI 코드가 corp_code를 임의 생성하면 안 된다.

---

## 9. 실무 주의사항

### 9.1 `get_all_corp_codes()` 전체 로드

현재 repository에는 전체 로드 accessor도 있다.
이건 지금은 문제 없지만, 운영 API를 붙일 때는:

- pagination
- streaming
- search 조건

을 고려하는 편이 좋다.

즉 다음 브랜치에서 조회 API를 만들 때는 전체 로드를 그대로 노출하지 않는 것이 좋다.

### 9.2 `corp_name_from_dart` 의미

이 필드는 DART 공시명 원문 보관용이다.

즉:

- 표시 보조 정보로는 쓸 수 있음
- 하지만 `stocks.stock_name` 정본을 대체하지는 않음

### 9.3 상장폐지 필터

실데이터 기준 `stock_corp_codes` 는 현재 상장폐지 이력까지 포함할 수 있다.
이건 현재 구조상 문제는 아니다.

이유:

- `stock_corp_codes` 는 corp_code 매핑 정본 계층
- 현재 상장분 여부는 필요 시 `stocks` 와 join 해서 좁히면 됨

따라서 상장폐지 필터는 별도 정책/브랜치로 다루는 것이 맞다.

---

## 10. 관련 문서 관계

이 문서는 아래 문서들과 함께 읽으면 된다.

- [`dart_corp_code_sync.md`](dart_corp_code_sync.md)
  - sync 구현/운영 정본
- [`stock_resolver.md`](stock_resolver.md)
  - 종목 식별 경계
- [`stock_master_sync.md`](stock_master_sync.md)
  - KIS 기반 `stocks` 정본
- [`supervisor_backend_integration.md`](supervisor_backend_integration.md)
  - Supervisor와 backend 전체 연결 구조

즉 관계를 한 줄로 정리하면:

- `stocks` = KIS/KRX 종목 정본
- `stock_resolver` = 자연어 -> 종목 식별
- `stock_corp_codes` = DART 식별자 정본
- Fundamental 후속 브랜치 = 이 정본을 실제로 소비하게 만드는 연결 작업

---

## 11. 이번 문서 기준으로 하지 않을 것

이 handoff 범위에서는 다음을 하지 않는다.

- `stock_corp_codes` sync 로직 재구현
- DART downloader/parser 재수정
- `stock_resolver` 변경
- KIS stock master sync 변경
- `stocks` 이름 정본 교체
- Fundamental AI 내부 분석 로직 수정

즉, 이 문서는 **기반을 새로 만드는 문서가 아니라, 이미 완성된 기반을 fundamental이 어떻게 받아서 써야 하는지 넘겨주는 문서**다.

---

## 12. 한 줄 결론

이제 Fundamental 쪽의 다음 작업은  
**“backend에 이미 존재하는 `stock_corp_codes` 정본 계층을 기준으로, Fundamental AI가 `CORP_CODE_MAP` 대신 backend 정본을 소비하도록 연결하는 것”**  
으로 이해하면 된다.
