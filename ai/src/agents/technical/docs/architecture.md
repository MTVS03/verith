# 6. 아키텍처 (Architecture)

`docs/architecture.md`

가격/기술적 분석 에이전트(②번)의 전체 구조를 한 곳에 모은다. 개별 규칙·값은 다른 문서(`regime_rules.md`·`enums.md`·`contracts.md`·`config.md`)가 담당하고, 이 문서는 **그것들이 어떻게 하나의 시스템으로 맞물리는가**를 설명한다.

세 축으로 나눈다: (1) 두 슈퍼바이저의 관계와 의존 방향, (2) A~E 층 파이프라인 구조, (3) 저장 구조(PostgreSQL / Redis). 마지막에 문서 간 값이 어긋나기 쉬운 지점(alignment_flag 매핑 등)을 단일 기준으로 못 박는다.

---

## 1. 두 슈퍼바이저 — Top vs Technical

veriθ에는 **Top Supervisor**와 **Technical Supervisor** 두 층의 조율자가 있다. 이름이 비슷해 섞이기 쉬우나, **책임 범위가 완전히 다르다.** 이 구분이 흐트러지면 "에이전트가 투자 판단을 한다"는 과장으로 이어지므로 honest scoping의 핵심 경계다.

| 구분 | Top Supervisor | Technical Supervisor |
| --- | --- | --- |
| 소속 | 팀 공용 (5개 에이전트 상위) | 이 에이전트 **내부** |
| 색 규약 | 회색 | 보라 (LLM 성격) |
| 역할 | 쿼리 변형 + 병렬 디스패치 | 흐름 조율 + 모듈 종합 + 기술적 분석 내부 판단 |
| 판단 범위 | **종합·판단 안 함** | **기술적 분석 내부의** 국면·신호·리스크만 |
| 전체 투자 판단 | 안 함 (5개 에이전트 결과를 나중에 합치는 건 별도 계층) | **안 함** (기술적 분석 안의 종합일 뿐) |

**핵심:** Technical Supervisor가 내는 것은 "이 종목의 기술적 국면·신호·리스크"이지 "사라/팔라"가 아니다. 전체 투자 판단은 이 에이전트의 책임이 아니며, 애초에 산출물에 그런 결론이 없다.

Top Supervisor는 이 에이전트에게 변형된 도메인 질의 하나만 넘긴다. **에이전트는 다른 4개 에이전트의 존재를 모른다.** `{ticker, query, request_id, as_of}` 4개만 받으면 독립 동작한다(상세: `contracts.md` 입력 계약).

---

## 2. 의존 방향 (Dependency)

```
frontend → backend → ai(내 에이전트)     [HTTP only, 단방향]
```

화살표는 한 방향이다. 역방향 호출이 없다.

- **ai는 DB를 직접 만지지 않는다.** 구조화된 **JSON만 반환**한다.
- **backend**가 그 JSON을 받아 ERD(PostgreSQL)에 저장하고 frontend에 제공한다.
- **frontend**가 데이터로 화면을 렌더한다(목록=요약, 클릭=상세).
- **에이전트는 HTML을 출력하지 않는다.** JSON 데이터만 주고, 렌더링은 프론트 책임.
- 유일한 예외: **시세 캐시(Redis)만 ai가 소유**한다(분석의 일부라서).

> **화면 렌더링 규약은 5개 에이전트 공통이어야 한다.** "데이터만 반환, HTML 안 만듦"을 팀 차원에서 통일한다. 그래야 프론트가 5개 결과를 하나의 통일된 디자인으로 렌더할 수 있다.

이 단방향 구조 덕분에 에이전트는 저장·렌더링을 몰라도 되고, **JSON 구조 하나만 책임지면 된다.** 테스트·재현·검증이 모두 이 JSON 경계에서 이뤄진다.

---

## 3. 내부 구조 — Module과 Node

에이전트 내부는 **Sub-Agent가 아니라 Module**로 짠다. LLM 호출을 최소화해 과설계를 피하기 위함이다.

| 용어 | 정의 |
| --- | --- |
| **Module** | 에이전트 내부 기능 단위. 계산 로직이 여기 산다. LLM 호출 최소. |
| **Node** | LangGraph 흐름의 각 단계. **얇은 어댑터**일 뿐, 로직은 옆 모듈에 위임. |

Node는 상태를 받아 모듈을 호출하고 결과를 상태에 얹는 얇은 층이다. "국면을 어떻게 판정하는가"는 `regime/` 모듈에 있고, `nodes/regime.py`는 그걸 부르기만 한다. 이 분리로 **검증(D)이 모듈 단위 mock 테스트로 가능**해진다.

---

## 4. A~E 층 파이프라인

에이전트 전체를 5개 관심사(A~E)로 나눠 본다. 안쪽에 10노드 흐름이 있고, 그것을 D(관측)와 E(하네스)가 바깥에서 감싼다.

```
E · 하네스 (resilience) ─ 전체를 감쌈
└ D · 관측/평가 (observability) ─ 전 구간 trace + 검증 3층
  └ [1.질문 정규화·2.포커스 정리] → [3.수집·4.지표·5.국면·6~8.종합/신뢰도/리스크·9.차트] → [10.해석]
    LLM(보라)                    코드(청록)                                         LLM(보라)
```

### 층별 판정

| 층 | 판정 | 이유 |
| --- | --- | --- |
| **A 오케스트레이션** | 중간 | 국면분류·데이터부족 조건부 분기 증가. LangGraph 조건부 엣지 + verify-to-dispatch 재생성 루프. |
| **B 도구/연결** | 필수·제일 무거움 | KIS가 모든 지표의 입력. 캐싱·rate limit·과거/오늘 분리. 기획이 바뀌어도 불변. |
| **C 메모리/검색** | **거의 불필요** | regime·confidence 전부 숫자에서 나오는 라벨. 검색할 텍스트 0, GraphRAG 0. **"도메인에 맞게 뺐다"가 포폴 강점** — 부재가 설명 포인트. |
| **D 평가/관측** | **핵심으로 격상** | 검증 대상 1개 → 3층. 아래 상세. |
| **E 하네스** | 필수 + 가드 1개 | KIS 복원력(재시도·백오프·폴백) + 데이터부족 시 "판단 불가" 가드. |

### KIS 조회·변환 (B층 핵심)

일봉·주봉·월봉을 KIS `inquire-daily-itemchartprice`로 각각 조회한다(`FID_PERIOD_DIV_CODE`를 `D`/`W`/`M`으로). `output2`의 축약 필드를 `kis_client.py`가 표준 OHLCV(`date`/`open`/`high`/`low`/`close`/`volume`/`trading_value`)로 변환한다. 거래대금(`acml_tr_pbmn`)은 `low_liquidity` 판정용으로 함께 가져온다(`config.md` §6). 상세 필드 매핑은 `kis_mapping.md` §7을 따른다.

**C가 없는 것이 정답이다.** 빠뜨린 게 아니라, 숫자 계산 기반 에이전트라 의미검색·GraphRAG가 필요 없어 의도적으로 제외했다. 이걸 문서에 명시하는 것 자체가 설계 이해도를 보여주는 지점이다.

### 10노드 흐름 (성공 경로)

노드 번호는 안정적인 **노드 ID**(4=지표계산, 5=국면분류)이고, **아래는 실제 실행 순서**다 — 국면분류(5·gate)를 지표계산(4)보다 먼저 실행한다:

```
진입 → 1.질문 안전 정규화[LLM] → 2.분석 포커스 정리[LLM] → 3.데이터수집[코드]
→ 5.국면분류[코드·신규·gate] → 4.신호용 지표계산[코드] → 6.신호종합1차[코드]
→ 7.신뢰도계산[코드·신규] → 8.리스크관찰점[코드·신규] → 9.차트생성[코드]
→ 10.국면해석·리포트[LLM] → 결과패키징 → 상위반환
```

> **국면분류(5)를 지표계산(4)보다 먼저 실행한다(실제 구현·정본).** 일반 설계라면 "지표계산 → 국면분류"가 자연스럽지만, 이 구조에서 **`regime_classify`(5)는 지표 bundle을 쓰지 않는다** — OHLCV(일/주/월봉)로 직접 판정하는 **선판정(gate)** 노드다. **`indicator_calculate`(4)는 그 뒤 `signal_score` 계산에 쓰는 "신호용 지표 bundle"**(RSI·MACD 등)이다. 둘은 같은 OHLCV에서 나오는 독립 산출물이라 순서를 바꿔도 계산 결과는 같지만, 국면을 gate로 먼저 보는 이유는 ① `final_regime=unavailable`이면 이후 지표·신호·신뢰도·리스크가 의미 없어 조기 중단(early return)으로 불필요 계산을 건너뛰고, ② `confidence`·`risk`는 regime 결과를 입력으로 받기 때문이다. 따라서 **regime_unavailable 경로에서는 노드 4·6·7·8(지표계산·신호종합·신뢰도·리스크)이 모두 skipped**이고 trace에 skipped로 기록한다(`trace_schema.md §9.1`). 실행 순서 조율은 LangGraph StateGraph(`supervisor/technical_graph.py`)가 담당한다.

**가장 중요한 원칙 — LLM은 라벨·수치를 만들지 않는다.**
regime·signal_score·confidence·risk는 전부 **코드가 확정**한다. 10번 LLM은 그 확정된 값을 **문장으로 풀기만** 한다. LLM이 숫자·라벨을 스스로 만들지 않으므로 **환각이 들어올 틈이 구조적으로 막혀 있다.** 이것이 veriθ 신뢰성 설계의 축이다.

**의존성 순서 근거:** 국면분류(5)는 원지표에서 바로 나오므로 종합(6) 앞에, 신뢰도(7)는 `signal_score`를 입력받으므로 종합 뒤에 둔다. 차트(9)는 리포트 직전에 두어 그 시점 데이터를 최종 스냅샷으로 굳힌다.

### 멀티프레임 — 노드 4·5가 핵심

**(나) 핵심만 멀티** 방식이다. 타임프레임마다 역할이 다르다.

| 타임프레임 | 역할 | 계산 |
| --- | --- | --- |
| **일봉 (주력)** | 신호 주력 | 기본 5개 지표 → 신호·`signal_score` (데이터 부족 시 계산 가능한 지표만) |
| **주봉 (중기)** | 맥락 확인 | 추세 방향 + 주요 지지저항 |
| **월봉 (대세)** | 방향 확인 | 추세 방향만 |

**일봉·주봉·월봉을 KIS에서 각각 직접 조회한다.** 세 타임프레임 모두 KIS 원본 시세를 정본으로 쓴다(같은 API에 `FID_PERIOD_DIV_CODE`만 D/W/M으로). 리샘플로 파생하지 않으므로, 상위 추세 판정과 차트가 전부 검증 가능한 실제 시세에 근거한다 — 이 에이전트의 멀티프레임 셀링포인트다.

**노드 5는 "보정"이다:** ① 일봉으로 1차 국면 판정 → ② 주/월 추세로 보정 → ③ 정합/역행 플래그와 함께 최종 regime 확정. 정합/역행은 방향성 있는 국면에만 적용하고, 과열·과매도·횡보 같은 중립 국면은 `alignment_flag=neutral`로 둔다. 예(방향성): "일봉 상승 전환 관찰 + 월봉 하락"이면 라벨은 여전히 `bullish_reversal_watch`이되 `alignment_flag=counter_trend`·`regime_context`("대세 하락 안의 단기 반등일 수 있음")로 맥락을 담는다.

**final_regime 라벨은 6종 고정이다.** 멀티프레임이 조합 라벨("상승 중 단기 과열")을 만들지 않고 `alignment_flag` + `regime_context`로 분리하는 이유는 **라벨 폭발을 막아 검증 ②를 가능하게** 하기 위함이다(상세: `glossary.md`·`regime_rules.md`).

### D 검증 3층

전 구간에 trace를 깔고, 아래 3개가 각 노드를 검사한다.

| 검증 | 신구 | 무엇을 | 대상 노드 |
| --- | --- | --- | --- |
| **① 계산 정확성** | 기존 | RSI·이동평균이 라이브러리와 일치? mock 단위테스트 | 4·5 |
| **② regime 규칙** | 신규 | "정배열+RSI72 → 과열?" 입력→라벨 테스트. **멀티프레임 보정 규칙도 여기서 검증** | 5 |
| **③ LLM 라벨 왜곡** | 신규·**최중요** | 코드 확정 라벨 == LLM 출력 라벨? trajectory eval. 종합 해석(`interpretation`) + 지표별 설명(`detail`) 모두 대상 | 10 |

**③이 이번 설계의 핵심 검증이다.** regime이 `sideways`(횡보)인데 LLM이 문장에 "상승 전환"을 쓰면 그것이 환각이다. 노드 10이 생성하는 두 종류의 LLM 문장 — 종합 해석(`interpretation.text`)과 지표별 설명(`technical_signals[].detail`) — 을 모두 trajectory eval로 검사해, 코드가 확정한 라벨·signal과 어긋나지 않는지 본다. **"LLM을 썼지만 검증으로 가뒀다"를 데이터로 증명**하는 지점이다(`interpretation_source`·`detail_source` 필드가 그 증거).

### E 하네스 — 실패를 받는 층

E는 전체 흐름을 감싸 어디서 터져도 받아낸다. **모든 예외 경로가 안전하게 착지하며, 억지 판단이나 환각으로 끝나는 경로가 없다.**

| 실패 지점 | 처리 | 결과 표기 |
| --- | --- | --- |
| 일봉(D) 호출 실패 + stale daily 있음 | 재시도(최대 3회, 1·2·4초) → stale daily 폴백 | `stale_cache` (최신 시세 미반영) |
| 일봉(D) 호출 실패 + 캐시 없음 | 데이터 제한 명시, **환각으로 안 채움** | `data_limited` |
| 주봉(W)·월봉(M) 실패 + stale W/M 있음 | stale 상위 타임프레임 사용, 최신봉 미반영 표시 | `stale_cache` (보조 안내) |
| 주봉(W)·월봉(M) 실패 + 캐시 없음, D 정상 | 일봉 기준 분석 계속, 해당 추세는 unavailable | `data_limited` |
| 봉 수 부족 | regime "판단 불가", 지표계산·종합·신뢰도·리스크(4·6~8) 스킵하고 바로 차트(9)로 | `regime_unavailable` |
| 검증 ③ 재생성 후에도 실패 | LLM 문장 버리고 템플릿 폴백 | `interpretation_source = template_fallback` |

**루프는 딱 2곳, 둘 다 상한이 있다:** KIS 재시도(최대 3회) + 검증 재생성(1회). 무한 루프가 구조적으로 불가능하다.

---

## 5. 저장 구조 (Storage)

저장은 두 계층이다. **영구 저장은 backend가 PostgreSQL로, 시세 캐시는 ai가 Redis로** 소유한다. 에이전트는 영구 저장을 모른다(JSON만 반환하고 backend가 매핑).

### 5.1 영구 = PostgreSQL (ERD) — backend 소유

6테이블. 본체 하나에 5개 상세 테이블이 매달린다.

```
TECHNICAL_REPORTS (본체, 1행)
├─ 1:1 REPORT_INTERPRETATION   (해석 문장 — 길어서 분리)
├─ 1:1 REPORT_VERIFICATION     (검증 결과)
├─ 1:N REPORT_SIGNALS          (지표별 신호)
├─ 1:N REPORT_CHARTS           (기간별 차트)
└─ 1:N REPORT_RISK_NOTES       (리스크 관찰점)
```

**설계 원칙 — 본체는 목록용 요약만.** 상세에서만 보는 것(interpretation·charts·signals·risk)은 분리 테이블로 빼서, 목록 조회 시 딸려오지 않게 한다. 리스트를 가볍게 유지하고 클릭 시 JOIN한다.

**본체 `TECHNICAL_REPORTS` 컬럼:**
```
id PK, ticker, final_regime, daily_regime, weekly_trend, monthly_trend,
alignment_flag, regime_context, consensus, signal_score, confidence,
confidence_basis, data_status, trace_id, source, as_of, created_at
```

저장 규칙 두 가지가 중요하다(상세: `contracts.md` §3):

- **`confidence_level`은 저장 안 함.** confidence float에서 재계산 가능한 파생값이며, 경계값이 바뀌면 저장값이 꼬인다. 프론트가 confidence로 매핑한다.
- **`alignment_flag`·`regime_context`는 저장함.** 재계산이 아니라 그 시점의 판단 결과이며, 필터("정합 리포트만")·재현성 추적에 쓰인다.

`html`은 저장하지 않는다 — 에이전트가 데이터만 주고 프론트가 렌더하므로 저장할 html이 없다. persistence는 backend 담당이라 에이전트 폴더에 `persistence/`가 없다.

### 5.2 캐시 = Redis — ai 소유

시세 캐시만 에이전트가 소유한다. 분석의 일부이기 때문이다. **Redis는 ERD가 아니며**, 문서에는 표로만 기록한다.

| 키 패턴 | 내용 | TTL |
| --- | --- | --- |
| `ohlcv:daily:{ticker}` | 과거 일봉 (KIS D) | 없음 (안 바뀜) |
| `ohlcv:weekly:{ticker}` | 주봉 (KIS W) | 없음 |
| `ohlcv:monthly:{ticker}` | 월봉 (KIS M) | 없음 |
| `ohlcv:today:{ticker}` | 오늘 일봉 | 15분 |
| `ohlcv:minute:{ticker}` | 분봉 | 1분 (lazy, 1d Beta용·MVP 필수 아님) |

**일봉·주봉·월봉 캐시를 분리한다.** 각각 KIS D/W/M 호출 결과를 `ohlcv:daily`·`ohlcv:weekly`·`ohlcv:monthly`로 저장한다. 세 타임프레임 모두 KIS 원본이므로 리샘플 파생은 쓰지 않는다.

### 5.3 저장 경계 요약

```
ai(에이전트)          backend                  frontend
─────────────        ─────────────            ─────────────
Redis 캐시 소유   →   JSON 받아 PostgreSQL     →  데이터로 렌더
JSON만 반환           6테이블에 매핑 저장          (HTML은 여기서)
DB 모름               영구 저장 소유
```

---

## 6. 문서 간 단일 기준 — 값 매핑

이 문서군은 **코드·DB·프론트 세 계층의 단일 기준**을 표방한다. 문서끼리 표기가 어긋나면 그 자체가 버그의 씨앗이므로, 헷갈리기 쉬운 대응을 여기서 못 박는다.

### 6.1 alignment_flag — 한글 ↔ 코드값 매핑

`regime_rules.md` 2단계 보정 테이블은 판정을 **한글**("정합/역행/중립")로 서술하고, `enums.md`는 **코드값**으로 정의한다. 둘은 같은 것을 가리키며, 대응은 다음과 같다.

| `regime_rules.md` (판정 서술) | `enums.md` 코드값 | 표시 라벨 | 의미 |
| --- | --- | --- | --- |
| 정합 | `aligned` | 정합 | 일봉 국면과 상위 추세 방향 일치 |
| 역행 | `counter_trend` | 역행 | 일봉 국면과 상위 추세 방향 반대 |
| 중립 | `neutral` | 중립 | 판정 대상 아님 (횡보·과열·과매도 등 성격 중립 국면) |

**규약:** `regime_rules.md`가 규칙을 한글로 서술하더라도, **코드·DB·JSON에 들어가는 값은 항상 `enums.md`의 코드값(`aligned`/`counter_trend`/`neutral`)이다.** 한글은 프론트 표시 라벨일 뿐 DB에 저장하지 않는다(`enums.md` 사용 규약 2번).

### 6.2 그 외 헷갈리기 쉬운 축 (재확인)

세부 정의는 각 문서에 있으나, 자주 섞이는 것만 여기 모아 재확인한다.

- **regime 성격(중립/긍정/부정) ≠ risk_flags.** 성격은 `alignment_flag` 판정에만 쓰고, risk는 별개 축의 리스크 경고다. 예: `overheated`는 성격상 중립(방향성 없음)이지만 `overheated_momentum` risk flag가 붙을 수 있다.
- **signal_score(방향·세기) ≠ confidence(신뢰도).** "약한 긍정인데 신뢰도는 낮음"이 가능하다.
- **final_regime(상태) ≠ consensus(신호).** "regime=과열 + consensus=약한 긍정"이 동시에 성립한다.
- **`indicator`(지표) — "전략" 아님.** JSON·DB 모두 `indicator`로 통일. "전략"은 투자 권유를 암시해 회피한다.

---

## 7. 관련 문서

| 문서 | 담당 |
| --- | --- |
| `glossary.md` | 용어 정의, 헷갈리는 축 구분 |
| `regime_rules.md` | 국면 판정 규칙 (1·2·3단계), 검증 ② 기준 |
| `enums.md` | 열거값 (코드값 ↔ 한글 라벨), 세 계층 단일 기준 |
| `contracts.md` | 입출력 JSON 계약, JSON↔ERD 매핑 |
| `config.md` | 설정값 (구조는 코드, 수치는 config) |
| **`architecture.md`** | **(이 문서) 슈퍼바이저·A~E층·저장구조 통합** |
