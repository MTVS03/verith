# Stock Resolver — 응답 의미와 경계

`docs/stock_resolver.md`

자연어 입력에서 **종목을 식별**하는 공통 컴포넌트. 물리 구조(테이블·제약)는 [`schema.md`](schema.md),
실행/seed 는 [`../README.md`](../README.md) 참고. 이 문서는 **API 응답 의미와 책임 경계**만 다룬다.

> **현재 데이터 한계(중요):** Resolver **구조는 종목 수와 무관한 공통 구조**(DB `stocks` 전체를
> 대상으로 동작)이지만, 현재 `stocks` 에는 **개발 bootstrap 10종목**만 seed 돼 있다. 따라서 지금
> 실행 환경에서 **실제 식별 가능한 범위도 10종목**이다. 전체 KRX 종목 지원은 **후속 마스터 동기화
> 작업이 완료돼야** 가능하다(이 문서 §5). 이 컴포넌트는 "전체 종목 지원 완료"가 아니다.

---

## 1. 입력

`POST /api/stocks/resolve`

```json
{ "query": "LG화학 리포트 보여줘" }
```

- `query`: 1~300자, `extra` 필드 금지. 정규화(NFKC→casefold→공백제거→한글/영문/숫자만) 결과가 비면 **422**.
- **원문 query 는 응답에 되돌려주지 않고 로그에도 남기지 않는다**(길이/상태만).

## 2. 응답 계약

```
status : "resolved" | "ambiguous" | "not_found"
reason : "exact_match" | "multiple_stocks" | "conflicting_identifiers"
       | "ambiguous_alias" | "unknown_identifier" | "no_match"
stock      : { stock_code, stock_name, market } | null
candidates : [ { stock_code, stock_name, market, matched_text, match_type }, ... ]  # 최대 10
```

`resolved`/`ambiguous`/`not_found` 는 **모두 HTTP 200**. 입력 검증 실패만 422, DB 장애는 503.
응답에는 **`agent`·`intent`·`query` 같은 필드가 없다** — 아래 §3 책임 경계 때문.

## 3. status 의미 (⭐ 경계)

| status | 의미 | 뒤 단계 |
| --- | --- | --- |
| `resolved` | 종목 context 를 **제공할 수 있다**(1종 확정) | Top Supervisor 가 선택적 context 로 사용 |
| `ambiguous` | 종목 **선택/추가 확인이 필요**(후보 제공) | 사용자 재질문 또는 상위 계층 판단 |
| `not_found` | **종목 context 가 없다**는 뜻일 뿐 | 전체 요청은 계속 진행 가능 |

- **`not_found` 는 예외/HTTP 장애가 아니라 정상 200 도메인 결과다.** "이 질의에 확정 종목이 없다"만
  뜻하며, **전체 사용자 요청의 실패가 아니다** — 종목이 필요 없는 요청이면 상위 계층이 계속 진행한다.
- **정상 `not_found` 와 도구/HTTP 장애는 구분한다.** `resolved`/`ambiguous`/`not_found` 는 **Backend 가
  정상 응답했을 때의 도메인 결과**다. Backend 의 **정상 도메인 응답을 받지 못한 경우**(timeout·연결
  실패·5xx)는 **Resolver status 가 아니라** Step 4 의 AI HTTP 도구 계층 오류다 — `status` enum 에 `tool-error` 를
  추가하지 않는다. 도구 장애를 `not_found` 로 위장하지 않는다(장애 ≠ 종목 없음).
- **Resolver 는 Agent 를 선택하거나 intent 를 판별하지 않는다.** 어느 Agent(Technical/News/Flow/…)로
  보낼지는 **Resolver 밖(Top Supervisor)**의 책임이다.
- **Resolver 는 Technical 지원 여부를 검사하지 않는다.** `stocks` 에 있으면 resolved 할 수 있고,
  그 종목이 Technical 10종 지원 범위인지는 **Technical 경계에서 별도 확인**한다(§4).

### 비종목 질의 예시 (거부가 아님)
| 입력 | Resolver | 의미 |
| --- | --- | --- |
| "로제 관련 뉴스 보여줘" | `not_found` / `no_match` | 종목 context 없음. 전체 Chat 요청 거부 아님 — 향후 News Agent 가 인물/키워드로 처리 |
| "2차전지 산업 뉴스" | `not_found` / `no_match` | 산업/주제 질의. 향후 Top Supervisor/News Agent 책임 |
| "카카오 수급 분석" | `stocks` 에 카카오 있으면 `resolved` | 어느 Agent 로 보낼지는 Resolver 가 정하지 않음 |
| "LG화학 기술 분석" | `resolved` | Technical 지원 범위 검사는 Resolver 밖 |

## 4. stocks 와 Technical 지원 범위는 별개

- **`stocks`** = Backend 소유 **공통 종목 마스터**(장기적으로 전체 국내 상장 종목).
- **Technical supported universe** = Technical Agent 가 현재 분석 가능한 **10종목 정책**(`ai` 의
  `BATTERY_TICKERS`). Resolver·stocks 와 **동일 개념이 아니다.**
- `stocks` 에 종목이 있다고 Technical 이 분석 가능한 것은 아니다. 지원 여부는 Technical/상위 계층이 판단한다.

## 5. 데이터 상태와 후속 (전체 종목 마스터)

- 현재 `stocks` 10종 seed 는 **개발 bootstrap** 이며 **전체 종목 정본이 아니다**([README](../README.md) seed).
- 전체 KRX 종목 지원은 **별도 브랜치**에서 진행한다. 방향(합의): Backend 소유 KIS 종목 마스터 동기화
  (AI 패키지 import 금지 · Backend 전용 fetch/parser/sync 경계 · 실제 네트워크는 수동 script/운영 job ·
  테스트는 fake downloader · KOSPI/KOSDAQ market 보존 · 신규상장/이름변경/시장이전 정책 명시 ·
  1회 누락으로 상장폐지 처리 금지). `is_active`/`status`/`last_synced_at`/`listed_at`/`delisted_at`
  같은 스키마 변경은 **데이터가 실제 제공하는 값과 동기화 정책 확정 후** 별도 단계에서 결정한다.

## 6. 호출 방식 — 조건부 `resolve_stock` 도구 (개념 — Step 4, 이번 단계 미구현)

확정 아키텍처: **Backend 는 종목을 선제 분석하지 않는다.**

```text
Backend Chat API   → 원문 query 를 그대로 AI Top Supervisor 에 전달(종목 선제 resolve 없음)
AI Top Supervisor  → 종목 식별이 "필요할 때만" resolve_stock 도구를 호출
resolve_stock @tool → HTTP: Backend POST /api/stocks/resolve
                     ↳ 결과(status/reason/stock/candidates)를 Supervisor 실행 중 선택적으로 사용
```

- Backend/Chat 이 모든 query 를 Resolver 에 먼저 넣어 `stock_context` 를 만드는 **입력 계약이 아니다.**
- 종목이 필요 없는 요청(인물·산업·주제 뉴스 등)은 **Resolver 를 아예 호출하지 않을 수 있다.**
- 최종 ticker 정본은 **`resolved.stock.stock_code`**(LLM 이 만든 ticker 를 검증 없이 쓰지 않는다).
- **Resolver 는 Top Supervisor 를 호출하지 않는다**(역방향 의존 금지).

아래 JSON 은 **Chat→Supervisor 입력이 아니라, 도구 호출 후 Supervisor 가 내부적으로 보유하는 실행
context** 예시다(있을 수도, 없을 수도 있음):

```jsonc
// 비종목 요청 — 도구를 호출하지 않았거나 not_found → 종목 context 없음
{ "query": "로제 관련 뉴스 보여줘", "stock_context": null }
```
```jsonc
// 종목 필요 요청 — resolve_stock 호출 후 resolved → 내부 실행 context 로 보유
{ "query": "카카오 수급 분석해줘",
  "stock_context": { "stock_code": "035720", "stock_name": "카카오", "market": "KOSPI" } }
```

> **경계:** 실제 `resolve_stock` 도구·HTTP client·Chat API·Top Supervisor 는 **이번 단계에서
> 구현하지 않는다**(Step 4). `Backend Chat API → AI Supervisor → Backend Resolver API` 는 런타임
> **순환 호출**을 만든다 — 확정 구현이 아니라, **timeout·내부 인증·재시도 상한·연결 실패(도구 오류)
> 분기·trace 전파·worker/풀 구조**까지 함께 설계할 **Step 4 후속 과제**로 둔다.
