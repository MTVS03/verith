# Supervisor ↔ Backend Integration Guide

`docs/supervisor_backend_integration.md`

이 문서는 **상위 Supervisor가 구현된 이후**, AI 쪽 orchestration 과 backend 쪽 정본/저장 경계가
어떻게 연결되어야 하는지를 한 번에 정리한 문서다.

기존 handoff 문서들은 각 agent별 backend 작업 범위를 설명한다.
이 문서는 그 위에서:

- Supervisor가 backend의 어떤 정본을 소비하는지
- 5개 agent에 어떤 방식으로 task를 나누는지
- 각 agent 결과가 다시 backend 어디로 연결되는지

를 **전체 흐름 관점**에서 설명한다.

관련 개별 문서:

- [`stock_resolver.md`](stock_resolver.md)
- [`stock_master_sync.md`](stock_master_sync.md)
- [`dart_corp_code_sync.md`](dart_corp_code_sync.md)
- [`news_backend_handoff.md`](news_backend_handoff.md)
- [`flow_backend_handoff.md`](flow_backend_handoff.md)
- [`fundamental_corp_code_handoff.md`](fundamental_corp_code_handoff.md)
- [`industry_backend_handoff.md`](industry_backend_handoff.md)
- [`schema.md`](schema.md)

---

## 1. 전체 구조

이제 시스템은 아래 3층으로 보는 것이 가장 정확하다.

### 1) Supervisor

위치:

- `ai/src/supervisor`

역할:

- 사용자 질문 해석
- 원본 query 보존
- 필요 시 종목/회사 식별
- 5개 agent 모두에 대한 task envelope 생성
- 각 agent의 실행 가능 여부(`can_run`)와 이유(`reason`) 정리

### 2) 5개 독립 agent

- `fundamental`
- `technical`
- `news`
- `flow`
- `industry`

역할:

- 각자 자기 분석만 수행
- 자기 output contract / html / json / payload 를 책임짐
- 다른 agent 결과를 직접 해석하거나 합치지 않음

### 3) Backend 정본/저장 계층

역할:

- 공통 종목 정본
- 공통 식별자 정본
- agent 결과 저장/조회
- News의 경우 PostgreSQL + Neo4j 저장/조회/cleanup

즉 전체 흐름은 아래처럼 본다.

```text
사용자 질문
  ↓
Supervisor
  - query 해석
  - 필요 시 stock resolve
  - 5개 agent task 생성
  ↓
5개 agent 병렬 실행
  ↓
각 agent 결과
  ↓
backend 저장/조회 경계
  ↓
frontend 5-card 표시
```

---

## 2. Supervisor가 새로 갖게 된 책임

예전 Supervisor는 사실상:

- 질문 해석
- 필요한 agent 선택
- rewritten query 생성

정도에 가까웠다.

하지만 backend 정본 계층이 생기면서, Supervisor는 이제 아래 책임까지 갖는다.

### 2.1 공통 종목 정본 소비

backend가 소유하는 공통 정본:

- `stocks`
- `stock_aliases`
- `stock_resolver`
- `stock_corp_codes`

Supervisor는 이 정본들을 **직접 DB로 읽는 것이 아니라**, backend 경계(도구/HTTP/client)를 통해
소비한다.

즉 Supervisor는:

- DB 직접 접근 금지
- ORM import 금지
- backend 정본을 “서비스 경계”로만 소비

가 원칙이다.

### 2.2 조건부 resolve

Supervisor는 모든 질문에 대해 stock resolver를 먼저 호출하면 안 된다.

예:

- `삼성전자 차트 어때?`
- `LG화학 수급 보여줘`
- `카카오 실적 괜찮아?`

처럼 종목 해석이 사실상 필요한 경우에만 resolve를 시도한다.

반대로:

- `2차전지 산업 전망 알려줘`
- `오늘 시장 분위기 어때?`
- `로제 관련 뉴스 알려줘`

같은 질문은 resolve 없이도 task 생성이 가능하다.

### 2.3 5-agent 고정 fan-out

현재 제품 방향은 “필요한 agent만 숨기는 구조”가 아니라,
**5개 agent를 모두 보여주는 구조**에 가깝다.

따라서 Supervisor는 이제:

- agent를 선택적으로 누락하는 계층이 아니라
- 5개 모두에 대해 task를 만들되
- 실행 가능 여부와 이유를 함께 채워주는 계층

이 된다.

---

## 3. Backend가 제공하는 공통 기반

Supervisor와 5개 agent가 공유하는 backend 기반은 크게 3가지다.

### 3.1 KIS/KRX 기준 공통 종목 마스터

- `stocks`
- 동기화 소스: [`stock_master_sync.md`](stock_master_sync.md)

역할:

- `stock_code`
- `stock_name`
- `market`

정본 제공.

### 3.2 자연어 종목 식별

- `stock_aliases`
- `stock_resolver`
- 문서: [`stock_resolver.md`](stock_resolver.md)

역할:

- 사용자 질문에서 종목/회사 식별
- canonical `stock_code`, `stock_name`, `market` 제공

### 3.3 DART 법인식별 정본

- `stock_corp_codes`
- 문서: [`dart_corp_code_sync.md`](dart_corp_code_sync.md)

역할:

- `stock_code -> corp_code`
- fundamental/industry/news 공용 식별자 기반

중요:

- `stocks` 와 `stock_corp_codes` 는 역할이 다르다
- `stocks` 는 KIS/KRX 종목 정본
- `stock_corp_codes` 는 DART 법인식별 정본
- 서로를 덮어쓰지 않는다

---

## 4. Supervisor 출력이 가져야 할 구조

Supervisor는 자유 텍스트가 아니라 구조화된 decision 을 내려야 한다.

최소한 아래 정보가 필요하다.

```json
{
  "original_query": "LG화학 차트상 어때?",
  "resolution": {
    "used_stock_resolver": true,
    "status": "resolved",
    "stock": {
      "stock_code": "051910",
      "stock_name": "LG화학",
      "market": "KOSPI"
    },
    "error": null
  },
  "tasks": [
    {
      "agent_type": "technical",
      "rewritten_query": "LG화학의 최근 차트와 추세를 기술적으로 분석해줘.",
      "context": {
        "stock_code": "051910",
        "stock_name": "LG화학",
        "market": "KOSPI"
      },
      "can_run": true,
      "reason": "stock_resolved"
    }
  ]
}
```

핵심은:

- `original_query` 는 항상 보존
- `resolution` 은 공통 context
- `tasks` 는 5개 agent 모두에 대해 생성
- 각 task는 `can_run` / `reason` 포함

---

## 5. 5-agent 고정 표시 구조에서의 정책

이제부터는 “누굴 실행할까”보다 “누가 어떤 상태로 카드에 나타날까”가 중요하다.

즉 각 agent는 아래 둘 중 하나 상태를 가져야 한다.

- 정상 실행 가능
- 명시적 unavailable/degraded

예시:

```json
{
  "agent_type": "technical",
  "rewritten_query": "사용자 질문을 기술적 관점에서 분석해줘.",
  "context": {
    "stock_code": null,
    "stock_name": null,
    "market": null
  },
  "can_run": false,
  "reason": "stock_not_resolved"
}
```

이 구조를 쓰면 frontend는 5개 카드를 항상 같은 레이아웃으로 보여줄 수 있다.

---

## 6. Agent별 Supervisor 연결 방식

### 6.1 Technical

현재 성격:

- ticker/stock_code 의존이 강함
- 종목 미식별 시 사실상 실행 불가

Supervisor 연결:

- 종목형 질문이면 resolve 시도
- resolved stock context를 technical task에 주입
- 미해결이면 `can_run=false`, `reason=stock_not_resolved`

Backend 연결:

- 기술적 결과 저장/조회
- `agent_reports` 인덱스
- 종목 정본은 `stocks`

### 6.2 Flow

현재 성격:

- stock_code 의존이 강함
- payload 정본은 이미 존재

Supervisor 연결:

- 종목 resolve 성공 시 strongly runnable
- 실패 시 unavailable 카드

Backend 연결:

- `flow_reports`
- `flow_report_interpretations`
- `flow_report_verifications`
- `agent_reports`

자세한 문서:

- [`flow_backend_handoff.md`](flow_backend_handoff.md)

### 6.3 Fundamental

현재 성격:

- 종목 식별이 거의 필수
- 장기적으로 `corp_code` backend 정본 소비 예정

Supervisor 연결:

- 우선 `stock_code`, `stock_name`, `market` context 주입
- corp_code는 supervisor가 임의 생성하지 않음
- 나중에 fundamental이 backend `stock_corp_codes`를 소비

Backend 연결:

- `stock_corp_codes`
- 향후 fundamental report 저장/조회 경계

자세한 문서:

- [`fundamental_corp_code_handoff.md`](fundamental_corp_code_handoff.md)

### 6.4 News

현재 성격:

- 종목 없이도 실행 가능한 질문이 많음
- 가장 free-form 질문 대응력이 큼

Supervisor 연결:

- 종목 질문이면 resolved stock context 주입 가능
- 비종목 질문이어도 `can_run=true` 가능
- 즉 resolve 실패와 무관하게 살아남을 가능성이 높은 agent

Backend 연결:

- 기사 원본 저장
- GraphBatch 저장
- query API
- report 저장/조회
- cleanup

자세한 문서:

- [`news_backend_handoff.md`](news_backend_handoff.md)

### 6.5 Industry

현재 성격:

- 종목 context가 있으면 좋음
- 산업/섹터/거시 질문은 종목 없이도 실행 가능

Supervisor 연결:

- 종목형 질문이면 resolve 결과 주입
- 산업형 질문이면 resolve 없이도 실행 가능

Backend 연결:

- `industry_reports`
- `agent_reports`

자세한 문서:

- [`industry_backend_handoff.md`](industry_backend_handoff.md)

---

## 7. Backend 문서 4개의 현재 위치

이제 handoff 문서들은 아래처럼 읽으면 된다.

### `news_backend_handoff.md`

의미:

- News AI가 backend를 어떻게 써야 하는지
- PostgreSQL + Neo4j 저장/조회/cleanup 경계 문서

Supervisor와의 관계:

- News는 종목 context가 없어도 실행 가능한 카드 후보

### `flow_backend_handoff.md`

의미:

- Flow payload를 backend 3테이블에 저장/조회하는 문서

Supervisor와의 관계:

- Flow는 stock-dependent
- resolved stock context가 있으면 실행, 없으면 unavailable

### `fundamental_corp_code_handoff.md`

의미:

- fundamental이 backend 정본으로 넘어오기 위한 준비 문서
- 핵심은 `stock_corp_codes`

Supervisor와의 관계:

- Supervisor는 우선 stock context만 보강
- corp_code 소비 전환은 fundamental 후속 브랜치

### `industry_backend_handoff.md`

의미:

- Industry payload 저장/조회 경계 문서

Supervisor와의 관계:

- 종목형이면 context 주입
- 산업형이면 context 없이도 실행 가능

---

## 8. Frontend 관점의 연결 결과

Frontend는 최종적으로 5개 카드를 항상 렌더할 수 있어야 한다.

즉 frontend는 Supervisor 출력 또는 각 agent 실행 결과에서 아래 정보를 기대한다.

- `agent_type`
- `status` 또는 `can_run`
- `reason`
- 성공 시 payload/html/json
- 실패 시 unavailable 설명

그래서 Supervisor는 “누굴 감출지”가 아니라
“5개 카드가 어떤 상태로 표시될지”를 정리하는 계층으로 보는 것이 맞다.

---

## 9. 구현 순서 권장

전체 관점에서 추천 순서는 아래다.

1. Supervisor 브랜치 완성
   - `ai/src/supervisor`
   - 5-agent 고정 fan-out
   - conditional stock resolve
   - task envelope 생성

2. Agent별 backend 저장/조회 경계 구현
   - news
   - flow
   - industry
   - technical
   - fundamental 후속

3. Fundamental의 backend 정본 소비 전환
   - `stock_corp_codes` 사용

4. Frontend 5-card 고정 표시 연결

---

## 10. 하지 말아야 할 것

이 문서 기준으로 다음은 피한다.

- Supervisor가 DB 직접 접근
- Supervisor가 ticker/corp_code를 임의 생성
- agent별 전용 stock resolver 중복 구현
- agent별 전용 KIS/DART 정본 중복 구축
- backend가 agent 결과를 다시 분석기로 재해석

---

## 11. 한 줄 결론

이제 구조는  
**“Supervisor가 backend의 공통 정본(`stocks`, `stock_resolver`, `stock_corp_codes`)을 필요 시 소비해 5개 agent 모두에 대한 task를 만들고, 각 agent는 자기 backend 저장/조회 경계로 연결되는 구조”**  
로 이해하면 된다.

즉 개별 handoff 문서 4개는 그대로 유지하되, 이 문서는 그 위에 놓이는 **전체 orchestration 연결 문서** 역할을 한다.
