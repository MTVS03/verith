# veriθ 가격/기술적 분석 에이전트 — 코드 작성 규칙

`docs/technical_coding_guidelines.md`

이 문서는 veriθ 가격/기술적 분석 에이전트를 구현할 때 지켜야 할 코드 작성 기준을 정리한다. 목적은 단순히 코드 스타일을 맞추는 것이 아니라, **하드코딩·스파게티 코드·책임 범위 혼동·LLM 환각·비밀키 노출**을 방지하는 것이다.

이 문서는 모든 구현 단계에서 공통으로 적용한다. 특히 Claude, Codex 같은 코드 생성 도구에 작업을 맡길 때도 이 문서를 기준으로 지시한다.

---

## 1. 기본 원칙

### 1.1 문서가 먼저, 코드는 그다음

설정값·계약·enum·DB 구조·API 구조는 문서가 정본이다.

- 값 변경은 `docs/config.md`를 먼저 수정한다.
- JSON 구조 변경은 `docs/contracts.md`를 먼저 수정한다.
- enum 변경은 `docs/enums.md`를 먼저 수정한다.
- KIS 응답 구조 변경은 `docs/kis_mapping.md`를 먼저 수정한다.
- 코드가 문서와 다르면 코드가 틀린 것으로 본다.

코드는 새로 설계하는 곳이 아니라, 문서에 확정된 내용을 구현하는 곳이다.

---

## 2. 하드코딩 금지

### 2.1 금지하는 하드코딩

아래 값은 코드 중간에 직접 박아 넣지 않는다.

- KIS 인증키
- API base URL
- 종목 지원 정책·표시명 map (`is_supported_ticker`·`BATTERY_TICKERS` — allowlist gate 아님, config 소유)
- KIS period 값 `D`, `W`, `M`
- timeout, retry, backoff 값
- RSI, 이동평균, 볼린저밴드 등 분석 상수 (예: `RSI_OVERSOLD = 35` — 문서에서 확정된 값이므로 코드에 `35`를 직접 박지 않는다)
- regime 임계값
- signal/confidence 가중치 (예: `STRATEGY_WEIGHTS`)
- cache TTL
- chart period
- 에러 코드 문자열
- 사용자 노출 라벨

이 값들은 반드시 정해진 config, enum, constants, schema에서 가져온다.

나쁜 예:

```python
if period == "D":
    timeout = 5
```

좋은 예:

```python
from src.agents.technical.config import KIS_PERIOD_DAILY, KIS_TIMEOUT_SECONDS

if period == KIS_PERIOD_DAILY:
    timeout = KIS_TIMEOUT_SECONDS
```

### 2.2 인증정보는 절대 코드에 쓰지 않는다

KIS 인증정보는 반드시 `.env` 또는 환경변수에서만 읽는다.

사용 키:

```bash
KIS_API_KEY=
KIS_API_SECRET=
KIS_BASE_URL=
```

금지:

```python
KIS_API_KEY = "실제키"
KIS_API_SECRET = "실제시크릿"
```

`KISSettings` 같은 설정 객체를 출력할 때도 secret이 노출되지 않도록 `repr=False` 또는 별도 마스킹 처리를 적용한다.

---

## 3. 스파게티 코드 금지

### 3.1 한 함수는 한 가지 책임만 가진다

함수 하나에서 아래 일을 한꺼번에 처리하지 않는다.

- 환경변수 로딩
- KIS 호출
- 응답 검증
- OHLCV 변환
- 지표 계산
- regime 판정
- 리포트 문장 생성

나쁜 예:

```python
def analyze_ticker(ticker):
    # env 로딩
    # KIS 호출
    # dataframe 변환
    # RSI 계산
    # regime 판정
    # LLM 호출
    # JSON 생성
    return result
```

좋은 예:

```python
def load_kis_settings():
    ...

def fetch_ohlcv(ticker: str, period: str):
    ...

def map_kis_output_to_ohlcv(rows: list[dict]):
    ...

def calculate_indicators(ohlcv):
    ...

def classify_regime(indicators):
    ...
```

### 3.2 함수 길이는 짧게 유지한다

권장 기준:

- 일반 함수: 30~50줄 이내
- 복잡한 분기 함수: 80줄 이내
- 그 이상 길어지면 책임을 나누는 것을 우선 검토한다.

단, 단순 상수 정의나 mapping dict는 예외로 본다.

---

## 4. 모듈 경계

### 4.1 모듈별 책임을 섞지 않는다

각 모듈은 자기 책임만 가진다.

| 모듈 | 책임 | 하지 말아야 할 것 |
| --- | --- | --- |
| `config.py` | 설정값, 종목 지원 정책(`is_supported_ticker`)·표시명 fallback, env 로딩 | KIS 호출, 지표 계산 |
| `services/kis_client.py` | KIS 호출, 재시도, 원본 응답 수신 | regime 판정, LLM 호출 |
| `schemas/` | 데이터 구조 정의 | 외부 API 호출 |
| `indicators/` | RSI, MA, Bollinger 등 지표 계산 | KIS 호출, LLM 호출 |
| `regime/` | 국면 판정, 멀티프레임 보정 | 리포트 문장 생성 |
| `synthesis/` | signal_score, confidence, risk 계산 | KIS 호출, DB 저장 |
| `charts/` | 차트 데이터와 annotation 생성 | HTML 렌더링 |
| `observability/` | trace, 검증, trajectory eval | 비즈니스 계산 자체 |
| `prompts/` | LLM 프롬프트 템플릿 | 숫자·라벨 생성 |
| `supervisor/` | 10노드 흐름 조율 | 세부 계산 로직 직접 구현 |
| `agent.py` | 외부 진입점 wrapper | DB 저장, HTML 생성 |

### 4.2 Node는 얇게 유지한다

LangGraph node는 로직을 직접 많이 갖지 않는다.

Node의 역할:

1. state를 받는다.
2. 필요한 모듈 함수를 호출한다.
3. 결과를 state에 얹는다.
4. 다음 노드로 넘긴다.

계산 로직은 `indicators/`, `regime/`, `synthesis/`, `charts/` 같은 모듈에 둔다.

---

## 5. AI 에이전트 책임 경계

### 5.1 DB를 직접 만지지 않는다

AI 에이전트는 PostgreSQL에 직접 저장하지 않는다.

- AI는 구조화된 JSON만 반환한다.
- Backend가 JSON을 받아 DB에 저장한다.
- AI 폴더에는 `persistence/`를 만들지 않는다.

금지:

```python
session.add(report)
db.commit()
```

### 5.2 HTML을 만들지 않는다

AI 에이전트는 HTML을 생성하지 않는다.

- AI는 JSON만 반환한다.
- Frontend가 JSON을 렌더링한다.
- HTML 문자열, CSS 문자열, 화면용 마크업을 에이전트에서 만들지 않는다.

금지:

```python
return "<div>상승 추세 유지</div>"
```

좋은 예:

```python
return {
    "final_regime": "uptrend_intact",
    "signal_score": 0.42,
    "confidence": 0.68,
}
```

---

## 6. LLM 사용 규칙

### 6.1 LLM은 숫자와 라벨을 만들지 않는다

아래 값은 반드시 코드가 확정한다.

- `final_regime`
- `daily_regime`
- `weekly_trend`
- `monthly_trend`
- `alignment_flag`
- `signal_score`
- `consensus`
- `confidence`
- `risk_flags`
- `chart annotations`

LLM은 코드가 확정한 값을 문장으로 풀기만 한다.

금지:

```python
llm에게 "이 종목의 regime을 판단해줘"라고 요청
```

허용:

```python
llm에게 "이미 확정된 regime과 signal을 사용자에게 설명해줘"라고 요청
```

### 6.2 LLM 출력은 검증 대상이다

LLM이 만든 문장은 항상 검증한다.

- 코드 라벨과 문장 라벨이 맞는지 확인한다.
- 금지어가 들어갔는지 확인한다.
- 매수/매도 권유처럼 보이는 표현을 막는다.
- 검증 실패 시 재생성 1회 후 템플릿 폴백한다.

---

## 7. 금융 표현 규칙

### 7.1 매수/매도 권유 금지

사용자 노출 문구에서 아래 표현을 쓰지 않는다.

- 매수
- 매도
- 사라
- 팔아라
- 지금 들어가라
- 목표 수익률
- 예상 수익률
- 수익 보장
- 적중률
- 실시간 (KIS는 준실시간이며 WebSocket 틱 스트리밍은 범위 밖이다. "실시간" 대신 "장중/분봉/준실시간"을 쓴다.)

대신 관찰형 표현을 쓴다.

| 피해야 할 표현 | 대체 표현 |
| --- | --- |
| 매수 신호 | 긍정 신호 |
| 매도 신호 | 부정 신호 |
| 사도 된다 | 긍정 요인이 관찰된다 |
| 팔아야 한다 | 부정 요인이 관찰된다 |
| 급등 가능 | 변동성 확대 가능성이 있다 |
| 수익 기대 | 과거 지표 기준 긍정 흐름이 보인다 |
| 실시간 시세 | 장중 시세 / 준실시간 시세 |

### 7.2 코드값은 영어 snake_case, 화면 라벨은 한글

DB, JSON, enum에는 영어 코드값을 쓴다.

좋은 예:

```json
{
  "final_regime": "uptrend_intact",
  "alignment_flag": "aligned"
}
```

화면에는 프론트가 한글 라벨로 변환한다.

---

## 8. KIS 연동 코드 규칙

### 8.1 KIS는 D/W/M 직접 호출

일봉에서 주봉·월봉을 리샘플링하지 않는다.

- 일봉: `FID_PERIOD_DIV_CODE = KIS_PERIOD_DAILY`  (`"D"`)
- 주봉: `FID_PERIOD_DIV_CODE = KIS_PERIOD_WEEKLY` (`"W"`)
- 월봉: `FID_PERIOD_DIV_CODE = KIS_PERIOD_MONTHLY` (`"M"`)

period 값 `"D"/"W"/"M"`도 코드에 직접 박지 않고 config 상수(`KIS_PERIOD_*`)로 가져온다(§2.1). 리샘플 관련 함수나 상수(`WEEKLY_RESAMPLE` 등)는 만들지 않는다.

금지:

```python
daily_df.resample("W")
```

### 8.2 KIS 원본 응답과 내부 모델을 분리한다

KIS 원본 필드를 코드 전역에서 직접 쓰지 않는다.

KIS 응답은 `kis_client.py`에서 표준 OHLCV로 변환한다.

KIS 원본:

```python
"stck_bsop_date"
"stck_clpr"
"acml_vol"
```

내부 구조 (`date`는 ISO 형식으로 정규화 — `kis_mapping.md §7` 정본):

```python
{
    "date": "2026-07-03",   # KIS 원본 "20260703" → ISO(YYYY-MM-DD)로 변환
    "open": 1000,
    "high": 1100,
    "low": 950,
    "close": 1050,
    "volume": 100000,
    "trading_value": 1000000000,
}
```

KIS 원본은 `stck_bsop_date="20260703"`(하이픈 없음)로 오지만, 내부 표준 OHLCV로 변환할 때 ISO(`2026-07-03`)로 정규화한다. 값이 전부 문자열로 오므로(`kis_mapping.md §11.3`) `open/high/low/close`는 float, `volume/trading_value`는 int로 캐스팅한다. 다른 모듈은 KIS 원본 필드명을 몰라야 한다.

### 8.3 실패는 조용히 삼키지 않는다

KIS 호출 실패, 빈 응답, 필드 누락, 숫자 변환 실패는 명확히 처리한다.

금지:

```python
except Exception:
    return []
```

좋은 예:

```python
except TimeoutError as exc:
    raise KisRequestTimeout("KIS 요청 시간이 초과되었습니다") from exc
```

---

## 9. 에러 처리 규칙

### 9.1 fail-fast가 필요한 경우

아래 경우는 즉시 실패시킨다.

- 필수 환경변수 누락
- 지원 정책 밖 종목(`is_supported_ticker`=false, 사실상 형식 오류 — allowlist 아님)
- 필수 KIS 응답 필드 누락
- 숫자 변환 불가
- 지원하지 않는 period 값
- contracts에 없는 enum 값

실패 메시지는 사람이 바로 원인을 알 수 있어야 한다.

나쁜 예:

```text
Error
```

좋은 예:

```text
Missing required KIS environment variables: KIS_API_KEY, KIS_API_SECRET
```

### 9.2 복구 가능한 실패는 fallback 경로를 둔다

복구 가능한 실패는 trace에 남기고, 문서에 정의된 fallback을 따른다.

- KIS 일봉 실패 + stale cache 있음 → stale cache 사용(200 `stale_cache`)
- KIS 응답은 왔으나 일봉이 비어 있음(데이터 부족) → 200 `data_limited`
- **KIS transport/API 장애 + 쓸 수 있는 stale cache 없음**(아무 데이터도 못 받음) → `KisApiError` 재전파 → endpoint **502 AI_UNAVAILABLE**. 인프라 장애를 `data_limited` 200으로 감싸지 않는다(장애 탐지 위해). `data_limited`는 데이터가 **일부라도 확보된** 경우에만 쓴다(`api_spec.md §8` 정합).
- 주/월봉 실패 + 일봉 정상 → 일봉 기준 분석 계속
- LLM 검증 실패 → 재생성 1회 후 템플릿 폴백

---

## 10. 타입 힌트와 데이터 모델

### 10.1 모든 public 함수에는 타입 힌트를 단다

좋은 예:

```python
def is_supported_ticker(ticker: str) -> bool:
    return bool(_TICKER_RE.fullmatch(ticker))  # 지원 정책: 형식상 유효한 ticker(allowlist 아님)
```

```python
def fetch_ohlcv(ticker: str, period: str) -> list[OHLCV]:
    ...
```

### 10.2 dict 남발을 피한다

외부 API 응답처럼 형태가 불안정한 곳은 dict를 쓸 수 있다. 하지만 내부 경계 이후에는 Pydantic model 또는 dataclass를 사용한다.

권장:

- KIS raw response: `dict`
- 내부 OHLCV: `OHLCV` dataclass 또는 Pydantic model
- report output: contracts 기반 schema

---

## 11. 가독성 규칙

### 11.1 이름만 보고 역할을 알 수 있게 한다

나쁜 예:

```python
def run(x):
    ...
```

좋은 예:

```python
def load_kis_settings() -> KISSettings:
    ...
```

```python
def map_kis_output_to_ohlcv(rows: list[dict]) -> list[OHLCV]:
    ...
```

### 11.2 약어를 남발하지 않는다

허용되는 약어:

- KIS
- RSI
- MA
- OHLCV
- TTL
- API
- DB
- LLM

그 외에는 명확한 이름을 쓴다.

### 11.3 주석은 “왜”를 설명한다

코드가 이미 말해주는 내용을 주석으로 반복하지 않는다.

나쁜 예:

```python
x = x + 1  # x에 1을 더한다
```

좋은 예:

```python
# KIS는 초당 호출 제한이 있어 재시도 사이에 백오프를 둔다.
time.sleep(backoff_seconds)
```

---

## 12. 테스트 규칙

### 12.1 외부 API 없이 테스트 가능한 구조로 만든다

KIS 실제 호출은 샘플 검증 단계에서만 사용한다. 일반 단위테스트는 mock 응답을 사용한다.

테스트해야 할 것:

- allowlist 판별
- env 필수 키 누락
- period 검증
- KIS raw → OHLCV 변환 (필드명·date ISO 정규화 포함)
- 숫자 문자열 변환 (KIS는 OHLCV 값을 전부 문자열로 반환함 — `kis_mapping.md §11.3` 실측 확인. float/int 캐스팅과 빈 문자열·비정상 값 처리를 테스트)
- 필드 누락 에러
- 지표 계산 정확성
- regime 규칙
- LLM 라벨 왜곡 검증

### 12.2 테스트가 어려운 코드는 구조가 잘못된 것이다

테스트가 어렵다면 대부분 아래 문제가 있다.

- 함수가 너무 많은 일을 한다.
- 외부 API 호출과 계산이 섞여 있다.
- 환경변수 로딩이 함수 내부 곳곳에 흩어져 있다.
- dict 구조가 여러 모듈에 퍼져 있다.
- 전역 상태가 많다.

---

## 13. 로그와 trace

### 13.1 print 대신 logger 또는 trace를 쓴다

샘플 스크립트는 `print`를 쓸 수 있다. 하지만 에이전트 본 코드에서는 logger 또는 trace를 사용한다.

금지:

```python
print("KIS 호출 성공")
```

권장:

```python
logger.info("kis_request_succeeded", extra={"ticker": ticker, "period": period})
```

### 13.2 비밀값은 로그에 남기지 않는다

아래 값은 절대 로그에 남기지 않는다.

- KIS API key
- KIS API secret
- access token
- refresh token
- 사용자 개인정보

trace에도 원본 query는 hash만 남기고, 정규화된 질문만 평문으로 남긴다.

---

## 14. 의존성 추가 규칙

새 라이브러리는 함부로 추가하지 않는다.

추가 전 확인:

1. 표준 라이브러리로 가능한가?
2. 이미 프로젝트에 있는 라이브러리로 가능한가?
3. 꼭 필요한가?
4. 팀원이 설치와 실행을 쉽게 할 수 있는가?
5. `pyproject.toml` 또는 의존성 파일에 반영했는가?

단순한 설정 로딩, dict 변환, 날짜 처리 때문에 무거운 라이브러리를 추가하지 않는다.

---

## 15. 코드 생성 도구 사용 규칙

Claude, Codex 같은 도구에 작업을 맡길 때는 항상 범위를 좁힌다.

좋은 지시:

```text
이번 단계에서는 config.py만 작성하세요.
kis_client.py, Redis, DB, LangGraph, 지표 계산은 만들지 마세요.
```

나쁜 지시:

```text
기술 분석 에이전트 만들어줘.
```

코드 생성 결과는 그대로 믿지 말고 아래를 확인한다.

- 요청하지 않은 파일을 만들었는가?
- 문서 정본과 다른 값을 넣었는가?
- 하드코딩된 값이 있는가?
- 비밀키가 노출되는가?
- 함수가 너무 많은 일을 하는가?
- DB/HTML/LLM 경계를 침범했는가?
- 테스트 없이 실제 API를 계속 호출하는가?

---

## 16. 커밋 전 체크리스트

커밋 전에 아래를 확인한다.

```bash
git status
git diff
```

체크리스트:

- [ ] 요청한 범위의 파일만 변경했는가?
- [ ] 문서 정본과 상수 이름·값이 일치하는가?
- [ ] 인증정보가 코드나 로그에 노출되지 않는가?
- [ ] 하드코딩된 수치가 없는가?
- [ ] 함수 책임이 너무 크지 않은가?
- [ ] 모듈 경계를 침범하지 않았는가?
- [ ] 외부 API 호출 없이 테스트 가능한가?
- [ ] 사용하지 않는 코드가 남아 있지 않은가?
- [ ] 새 문서를 만들었다면 정본이 둘로 쪼개지지 않는가?
- [ ] 사용자 노출 문구에 매수/매도 권유가 없는가?

---

## 17. 금지 패턴 요약

아래 패턴은 발견하면 수정한다.

```python
# 인증정보 하드코딩
API_KEY = "..."

# 책임 과다 함수
def run_everything():
    ...

# 조용히 실패 삼키기
except Exception:
    pass

# KIS 원본 필드가 여러 모듈에 퍼짐
row["stck_clpr"]

# AI 에이전트가 DB 직접 저장
session.add(...)

# AI 에이전트가 HTML 생성
return "<html>...</html>"

# LLM이 regime 직접 판단
llm.invoke("이 종목의 국면을 판단해줘")

# 일봉에서 주봉 리샘플
 daily.resample("W")
```

---

## 18. 권장 패턴 요약

```python
# config에서 상수 가져오기
from src.agents.technical.config import KIS_PERIOD_DAILY

# 작은 함수

def is_supported_ticker(ticker: str) -> bool:
    return bool(_TICKER_RE.fullmatch(ticker))  # 지원 정책(형식). BATTERY_TICKERS membership 아님

# 설정 객체
@dataclass(frozen=True)
class KISSettings:
    api_key: str
    api_secret: str
    base_url: str

# 외부 응답 → 내부 모델 변환

def map_kis_output_to_ohlcv(rows: list[dict]) -> list[OHLCV]:
    ...

# 코드가 라벨 확정, LLM은 설명만
regime = classify_regime(indicators)
interpretation = explain_regime_with_llm(regime=regime, indicators=indicators)
```

---

## 19. 최종 원칙

이 에이전트는 “많이 만든 코드”보다 “경계가 명확한 코드”가 중요하다.

- KIS는 데이터 수집만 한다.
- 지표 모듈은 계산만 한다.
- regime 모듈은 규칙 판정만 한다.
- synthesis 모듈은 신호·신뢰도·리스크만 계산한다.
- LLM은 설명만 한다.
- Backend가 저장한다.
- Frontend가 렌더링한다.

각 책임이 섞이지 않으면 코드가 작아지고, 테스트가 쉬워지고, 포트폴리오에서 설계 의도가 선명하게 보인다.
