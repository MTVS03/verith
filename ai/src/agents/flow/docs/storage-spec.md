# flow 리포트 저장 명세 — payload ↔ 백엔드 스키마 매핑

작성: flow 담당 · 2026-07-07 갱신 · payload version 1 기준
성격: 백엔드가 통합 스키마(마이그레이션 `705a5833d4a3`)에서 flow 3테이블을
**이미 생성**했다. 이 문서는 그 실제 스키마에 우리 payload를 **어떻게
매핑하는지**와 남은 확인 사항을 정의한다. (이전 버전의 "단일 payload 테이블
ERD 초안"은 폐기 — 백엔드는 3테이블 분리 구조로 확정했다.)

## 0. 역할 분담 (확정)

- **flow 에이전트**: `AgentOutput.payload`(JSON)를 만들어 내보낸다. **저장은 하지 않는다.**
- **백엔드**: payload를 받아 아래 3테이블로 매핑·저장한다(저장 service는 후속 브랜치).
- **프론트**: 저장된 JSON을 읽어 리포트 화면을 **다시 그린다**. HTML은 저장하지 않는다.
  → flow는 HTML을 계속 **생성**하되(lab QA·디자인 기준), DB에는 넣지 않는다.
  프론트는 flow의 HTML/템플릿(`render/`)을 **디자인 레퍼런스**로 참고한다.

## 1. payload 구조 (version 1)

```json
{
  "version": 1,
  "report_id": "uuid4 문자열",
  "trace_id":  "uuid4 문자열 (기본 = report_id · 상관관계 ID)",
  "meta":   { "stock_name": "삼성전자", "ticker": "005930",
              "market": "KOSPI200", "base_date": "2026-07-06" },
  "signals": { "consecutive": …, "strength": …, "alignment": "동반매수",
               "daily": […], "persistence": …, "inst_detail": …,
               "ownership": […], "price_daily": […] },
  "verification": { "gate1": {passed, checks[], failures[]},
                    "gate2": {…}, "gate3": {…},
                    "outcome": "explained | fact_only",
                    "regen_count": 0 },
  "interpretation": "LLM 해석 (게이트3 통과분만, 아니면 null)",
  "interpretation_meta": { "source": "llm | fallback",
                           "provider": "openai | null",
                           "model": "gpt-5.4-mini | null" }
}
```

- 2026-07-08 추가 필드(version 유지 — additive/하위 호환): `trace_id`,
  `verification.outcome`·`regen_count`, `interpretation_meta`. 모두 flow 가 이미
  아는 값을 옮겨 담은 것(새 계산 아님). `outcome`/`interpretation_meta.source` 는
  게이트3 통과 여부의 재표현이고, `provider`/`model` 은 해석이 실린 경우에만
  채워진다(interpretation null ↔ provider/model null, 출처 정합). `data_status`
  는 아직 미포함 — enum 이 백엔드 소관이라 확인 B 합의 후 추가.

- `signals`의 키는 한글이다(개인·외국인·기관·증권…). 화면·검증 문장과 같은
  어휘로 대조되게 하려는 의도 — 바꾸지 말 것. 화면의 모든 숫자는 이 signals에서
  나온다(프론트 재그리기의 데이터 원천).
- `price_daily`: 날짜별 시세(종가·전일비·등락률·거래량·기관/외국인 순매매량[주]).
- `verification`이 이 프로젝트의 정체성이다: 모든 숫자에 "무엇으로 검증됐는지"의
  문장(checks)이 붙는다. signals와 verification은 분리 저장돼도 **함께 조회**돼야 한다.

## 2. 백엔드 실제 스키마 (마이그레이션 705a5833d4a3)

**`flow_reports`** (root)
| 컬럼 | 타입 | 매핑 원천 |
|---|---|---|
| `id` | UUID PK | payload.`report_id` (아래 확인 A) |
| `ticker` | String | payload.meta.ticker |
| `stock_name` | String | payload.meta.stock_name |
| `market` | String | payload.meta.market |
| `base_date` | Date | payload.meta.base_date |
| `alignment` | String | payload.signals.alignment (승격 복사) |
| `signals` | JSONB | payload.signals (통짜) |
| `data_status` | String | **flow 미산출 — 확인 B (미결)** |
| `trace_id` | String | payload.`trace_id` (기본=report_id) ✅ 실림 |
| `created_at` | TIMESTAMPTZ | DB now() (flow 미산출) |
- 인덱스: (ticker, base_date DESC), (trace_id)

**`flow_report_interpretations`** (1:1, FK→flow_reports.id CASCADE)
| 컬럼 | 매핑 원천 |
|---|---|
| `interpretation` | payload.interpretation (null이면 게이트3 통과 해석 없음) |
| `interpretation_source` | payload.`interpretation_meta.source` ("llm"/"fallback") ✅ |
| `provider` | payload.`interpretation_meta.provider` ("openai", 해석 실릴 때만) ✅ |
| `model` | payload.`interpretation_meta.model` ("gpt-5.4-mini", 해석 실릴 때만) ✅ |

**`flow_report_verifications`** (1:1, FK→flow_reports.id CASCADE)
| 컬럼 | 매핑 원천 |
|---|---|
| `gate1_passed` | payload.verification.gate1.passed |
| `gate2_passed` | payload.verification.gate2.passed |
| `gate3_passed` | payload.verification.gate3.passed |
| `checks` | verification 3게이트의 checks(+failures) JSONB |
| `outcome` | payload.`verification.outcome` ("explained"/"fact_only") ✅ |
| `regen_count` | payload.`verification.regen_count` (explain_retries) ✅ |

## 3. 불변식 (저장·조회가 지켜야 할 요구)

1. **payload는 저장 후 불변**. 검증된 사실의 스냅샷 — 수정은 새 report_id로.
2. **signals ↔ verification 함께 조회**. 세 테이블로 분리됐어도, signals만 떼어
   주는 조회는 "검증 없는 숫자"가 된다(FK CASCADE가 삭제는 묶지만 조회는 API 몫).
3. **승격 컬럼(ticker·stock_name·market·base_date·alignment)과 payload는 같은 값**.
   어긋나면 payload가 정답 — 저장 시 payload에서 뽑아 채울 것(두 소스 금지).
4. **interpretation null 의미 유지**: null = "게이트3 통과 해석 없음". 빈 문자열로
   바꾸지 말 것. interpretation_source도 이 의미와 정합해야 한다(확인 D).
5. **report_id 는 AI 서버 발급 uuid4가 관통**. 로그·검증·저장·조회를 한 ID가
   꿰뚫는 상관관계 ID — 저장 시 새 ID를 만들면 추적이 끊긴다.

## 4. 백엔드 확인 사항

**flow 측 반영 완료 (2026-07-08, C·D·E) — payload 에 실려 나감:**
- **C. `trace_id`** = payload.trace_id(기본 report_id). 슈퍼바이저가 상위 추적 ID를
  주면 `build_payload(trace_id=…)` 로 대체 가능(형식만 알려주면 됨).
- **D. `interpretation_source`** = payload.interpretation_meta.source =
  "llm"(게이트3 통과) / "fallback"(생략·상한초과). null 의미(§3-4)와 정합:
  interpretation null ↔ source "fallback" ↔ provider/model null.
- **E. `outcome`·`regen_count`** = payload.verification.outcome("explained"/
  "fact_only") · regen_count(explain_retries). 백엔드는 파생 말고 이 값을 그대로 저장.

**남은 것 (백엔드 답 필요):**
- **A. `flow_reports.id` 에 우리 report_id(uuid4)를 넣어도 되나?** 컬럼 default가
  `gen_random_uuid()`라 DB가 새로 만들 수 있는데, 그러면 §3-5가 깨진다. 우리 UUID를
  그대로 PK로 받아 달라(technical 선례처럼 백엔드가 자체 PK를 만들면 우리 report_id는
  최소한 trace_id 로 보존됨 — 이미 payload 에 있음).
- **B. `data_status` 값 규칙 (미결)**: flow는 게이트 결과로 파생 가능(예: 게이트2
  실패→degraded, 정상→ok). **원하는 enum을 정해 주면** payload 에 실어 준다 —
  enum 어휘가 백엔드 소관이라 지금 커밋에서 뺐다(추측 값으로 굳히면 재작업).

## 5. 지금 안 만드는 것 (요구가 실물로 오면)

- signals 정규화 테이블 — "외국인 5일 연속 순매수 종목 검색" 같은 크로스 리포트
  검색이 생기면. 그 전엔 JSONB(필요 시 GIN 인덱스)로 충분.
- 게이트 통과율 모니터링 — 운영 지표 요구가 오면 flow_report_verifications에서 파생.
