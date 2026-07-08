## Supervisor 이후 각 Agent 후속 정리

이 문서는 `ai/src/supervisor`의 planning + execution 계층이 완료된 현재 시점에서, 각 서브에이전트가 Supervisor와 더 자연스럽게 붙기 위해 무엇을 맞춰야 하는지 정리한 문서입니다.

핵심 전제는 아래와 같습니다.

- Supervisor는 이미 다음 책임을 가집니다.
  - 사용자 질문 해석
  - 필요 시 stock resolver 호출
  - 5개 agent 모두에 대한 task envelope 생성
  - 실행 가능 여부(`can_run`) 판정
  - 각 agent 공개 진입점으로의 얇은 adapter 실행
- 따라서 이제 남은 일은 “Supervisor를 다시 만드는 것”이 아니라, 각 agent가 장기적으로 더 단순하고 일관된 공개 계약을 갖도록 정리하는 것입니다.

---

## 1. 결론 요약

현재 Supervisor execution adapter가 차이를 흡수하고 있으므로, 모든 agent를 지금 당장 크게 뜯어고칠 필요는 없습니다.

다만 장기적으로는 아래 방향으로 수렴하는 것이 좋습니다.

| agent | 현재 Supervisor가 넘기는 핵심 입력 | 장기 목표 공개 계약 | 우선순위 |
|---|---|---|---|
| fundamental | `ticker + rewritten_query` | `ticker + natural query` | 높음 |
| technical | `ticker + rewritten_query` | `ticker + natural query` | 높음 |
| flow | `stock context + rewritten_query` | `query + ticker(or stock_name)` | 높음 |
| news | `rewritten_query` | `question` 유지 | 낮음 |
| industry | `rewritten_query` | `question` 유지 | 낮음 |

즉, 실제로 손을 많이 봐야 하는 쪽은 `fundamental / technical / flow`이고, `news / industry`는 현재 구조도 Supervisor와 비교적 잘 맞습니다.

---

## 2. 현재 Supervisor가 실제로 기대하는 것

Supervisor execution 계층은 agent 내부 로직을 재구현하지 않고, 아래 정도만 adapter로 맞춰서 호출합니다.

- fundamental: 종목이 확정된 경우만 실행
- technical: 종목이 확정된 경우만 실행
- flow: 종목이 확정된 경우만 실행
- news: 종목 없이도 실행 가능
- industry: 종목 없이도 실행 가능

즉 Supervisor 관점에서는 agent가 아래 두 부류로 나뉩니다.

### 2.1 종목 의존 agent

- fundamental
- technical
- flow

이 셋은 `resolution.status == "resolved"`일 때만 `can_run=true`가 됩니다.

### 2.2 종목 선택 agent

- news
- industry

이 둘은 종목이 없어도 `can_run=true`로 실행 가능합니다.

---

## 3. Agent별 후속 작업

### 3.1 Fundamental

현재 확인된 공개 진입점은 다음과 같습니다.

- [`analyze_fundamental()`](/Users/parkjinhee/AI/verith/ai/src/agents/fundamental/graph.py)
- 입력 모델: [`FundamentalRequest`](/Users/parkjinhee/AI/verith/ai/src/agents/fundamental/core/contract.py)

현재 `FundamentalRequest`는 사실상 아래를 호출자가 많이 알아야 합니다.

- `ticker`
- `corp_name`
- `intent`
- `fs_div`
- `report_mode`
- `years`
- `request_id`
- `trace_id`

이 구조는 단독 agent로는 괜찮지만, Supervisor 아래에 들어오면 호출 경계가 무겁습니다.

#### 지금 꼭 필요한 방향

Fundamental 쪽은 장기적으로 외부 공개 계약을 아래처럼 단순화하는 것이 좋습니다.

- 입력: `ticker + natural query`

즉 Supervisor는 “사용자 질문 + 종목코드”까지만 넘기고,

- intent 해석
- years/report_mode/fs_div 기본값 결정
- corp_code 조회
- 내부 retrieval 전략 선택

이런 것은 fundamental 내부 책임으로 가져가는 방향이 가장 자연스럽습니다.

#### 왜 필요한가

지금처럼 상위 계층이 `intent`, `years`, `fs_div`까지 알아야 하면:

- Supervisor가 재무 도메인 내부 정책까지 알아야 하고
- 향후 정책 변경 때 Supervisor도 같이 바뀌며
- 공개 계약이 agent-friendly가 아니라 internal-workflow-friendly가 됩니다

#### 권장 후속

1. `ticker + query` 중심의 얇은 public wrapper 추가
2. 기존 `FundamentalRequest`는 내부/고급 진입점으로 유지 가능
3. `stock_corp_codes` 정본을 fundamental 내부에서 소비하도록 연결
4. `CORP_CODE_MAP` 의존 제거

#### 우선순위

가장 먼저 손봐야 하는 팀입니다.

---

### 3.2 Technical

현재 공개 진입점은 다음과 같습니다.

- [`run_technical_agent()`](/Users/parkjinhee/AI/verith/ai/src/agents/technical/agent.py)

현재 구조는 이미 상당히 Supervisor-friendly 합니다.

- 입력 payload 검증
- `ticker + query`
- 내부 supervisor로 위임

#### 지금 꼭 필요한 방향

Technical은 큰 구조 변경보다, “Supervisor 아래에 들어오는 자연어 query를 기준으로 더 자연스럽게 받는 것”만 정리하면 됩니다.

장기 목표 공개 계약:

- 입력: `ticker + natural query`

이미 거의 이 방향이므로, 실제 수정량은 많지 않을 가능성이 큽니다.

#### 권장 후속

1. public contract를 Supervisor 기준으로 다시 한 번 문서화
2. execution adapter에서 임시로 흡수하는 부분이 있다면 agent 쪽으로 당겨오기
3. technical 내부에서 필요한 추가 문맥(as_of, request_id 등)은 유지하되, 상위에는 최대한 단순하게 노출

#### 우선순위

높음. 다만 구조 변경 폭은 fundamental보다 작습니다.

---

### 3.3 Flow

현재 공개 진입점은 다음과 같습니다.

- [`run()`](/Users/parkjinhee/AI/verith/ai/src/agents/flow/agent.py)

현재도 자연어 `query`를 받지만, 실제 종목 축은 아래 둘 중 하나에 기대고 있습니다.

- `stock_name`
- `ticker`

또 내부에는 다음과 같은 flow 고유 정책이 있습니다.

- 게이트1 검증
- 종목명 기반 해석
- 거래일/base_date 확정

#### 지금 꼭 필요한 방향

Flow의 장기 목표 공개 계약은 아래처럼 정리하는 것이 좋습니다.

- 입력: `query + ticker(or stock_name)`

즉 상위 Supervisor는 종목 문맥과 자연어 질문까지만 넘기고,

- 최종 티커/이름 보정
- 게이트1
- 기준일 처리
- 내부 리포트 생성

은 flow 내부가 책임지는 구조가 맞습니다.

#### 왜 필요한가

Flow는 technical처럼 완전히 ticker-only도 아니고, news처럼 question-only도 아닙니다.
그래서 지금처럼 adapter가 흡수하는 것은 괜찮지만, 공개 계약이 명확하지 않으면 상위 계층이 가장 헷갈리기 쉬운 agent가 됩니다.

#### 권장 후속

1. 외부 공개 계약을 `query + stock context`로 명시
2. `base_date` 같은 내부 실행 변수는 public contract에서 숨기기
3. `ticker`와 `stock_name` 중 무엇을 정본 입력으로 삼을지 문서화
4. Supervisor가 넘긴 문맥만으로 안정적으로 실행되는지 smoke 정리

#### 우선순위

높음. fundamental과 함께 맞춰두면 Supervisor 구조가 훨씬 깔끔해집니다.

---

### 3.4 News

현재 공개 진입점은 다음과 같습니다.

- [`run_query(question)`](/Users/parkjinhee/AI/verith/ai/src/agents/news/graph.py)

이 구조는 Supervisor와 잘 맞습니다.

장기 목표 공개 계약도 사실상 현재와 동일합니다.

- 입력: `question`

#### 지금 꼭 필요한 변경

크게 없습니다.

#### 있으면 좋은 정도

1. public entrypoint를 한 번 더 “Supervisor가 호출하는 공식 진입점”으로 문서화
2. question-only 계약을 유지한다고 명시
3. 종목 context가 붙더라도 필수 입력은 아니라는 점을 문서화

#### 우선순위

낮음.

---

### 3.5 Industry

현재 외부 실행 형태는 사실상 아래 형태입니다.

- [`build_agent(graph).invoke({"question": ...})`](/Users/parkjinhee/AI/verith/ai/src/agents/industry/agent.py)

즉 현재는 “질문형 agent”라서 Supervisor와 개념적으로 잘 맞습니다.

장기 목표 공개 계약:

- 입력: `question`

#### 지금 꼭 필요한 변경

필수는 아닙니다.

다만 지금은 `build_agent(...).invoke(...)` 형태라서, 상위 계층에서 부르기 좋은 “얇은 공식 wrapper”가 하나 있으면 더 좋습니다.

예를 들면:

- `run_industry_agent(question: str, ...)`

같은 식의 명시적 public entrypoint입니다.

#### 권장 후속

1. 공식 외부 진입점 wrapper 추가
2. `question-only` 계약 문서화
3. graph/llm/neo4j 의존성 주입 방식 정리

#### 우선순위

낮음. 하지만 public wrapper는 있으면 좋습니다.

---

## 4. 지금 당장 팀별로 요청해야 하는 순서

Supervisor 기준으로 보면 우선순위는 아래가 적절합니다.

1. fundamental
2. flow
3. technical
4. industry
5. news

설명:

- fundamental: 가장 무거운 입력 계약을 갖고 있어서 상위 계층과의 경계를 먼저 정리해야 함
- flow: Supervisor 아래에 붙을 때 헷갈릴 여지가 큰 구조
- technical: 이미 많이 맞아 있으나 public contract를 supervisor 기준으로 다시 다듬으면 좋음
- industry/news: 지금도 question형이라 상대적으로 덜 급함

---

## 5. 최종 목표 형태

장기적으로는 Supervisor 아래의 5개 agent 공개 계약이 아래 정도로 수렴하는 것이 가장 이상적입니다.

| agent | 장기 공개 입력 |
|---|---|
| fundamental | `ticker + query` |
| technical | `ticker + query` |
| flow | `query + ticker(or stock_name)` |
| news | `question` |
| industry | `question` |

이렇게 되면 Supervisor는 각 agent의 내부 도메인 규칙을 거의 몰라도 되고,

- 질문 해석
- stock resolve
- 5-task 생성
- 실행 orchestration

에 집중할 수 있습니다.

---

## 6. 문서 사용 방법

이 문서는 팀원들에게 “지금 네 agent를 어떻게 바꾸면 Supervisor와 잘 붙는지” 설명할 때 기준 문서로 사용합니다.

권장 방식은 다음과 같습니다.

- fundamental 팀원: 이 문서의 3.1만 발췌해서 전달
- flow 팀원: 3.3만 발췌해서 전달
- technical(본인 작업): 3.2 기준으로 정리
- news / industry 팀원: 당장 필수 변경은 없고, wrapper/문서화 위주로 안내

---

## 7. 현재 상태 한 줄 요약

Supervisor는 이미 planning + execution까지 완료되었고, 지금부터의 핵심은 “각 agent의 공개 계약을 Supervisor-friendly하게 정리하는 것”입니다.

즉, 다음 단계의 본질은 새 로직 추가가 아니라 **경계 정리와 public interface 정리**입니다.
