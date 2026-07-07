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
  "meta":   { "stock_name": "삼성전자", "ticker": "005930",
              "market": "KOSPI200", "base_date": "2026-07-06" },
  "signals": { "consecutive": …, "strength": …, "alignment": "동반매수",
               "daily": […], "persistence": …, "inst_detail": …,
               "ownership": […], "price_daily": […] },
  "verification": { "gate1": {passed, checks[], failures[]},
                    "gate2": {…}, "gate3": {…} },
  "interpretation": "LLM 해석 (게이트3 통과분만, 아니면 null)"
}
```

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
| `data_status` | String | **flow 미산출 — 확인 B** |
| `trace_id` | String | **= report_id 로 채움 (확인 C)** |
| `created_at` | TIMESTAMPTZ | DB now() (flow 미산출) |
- 인덱스: (ticker, base_date DESC), (trace_id)

**`flow_report_interpretations`** (1:1, FK→flow_reports.id CASCADE)
| 컬럼 | 매핑 원천 |
|---|---|
| `interpretation` | payload.interpretation (null이면 게이트3 통과 해석 없음) |
| `interpretation_source` | **flow 미산출 — 확인 D** (예: "llm" / "fallback") |
| `provider` | `"openai"` (flow가 앎 — payload에 추가 가능) |
| `model` | `"gpt-4o-mini"` (config — payload에 추가 가능) |

**`flow_report_verifications`** (1:1, FK→flow_reports.id CASCADE)
| 컬럼 | 매핑 원천 |
|---|---|
| `gate1_passed` | payload.verification.gate1.passed |
| `gate2_passed` | payload.verification.gate2.passed |
| `gate3_passed` | payload.verification.gate3.passed |
| `checks` | verification 3게이트의 checks(+failures) JSONB |
| `outcome` | **flow 미산출 — 확인 E** (예: "explained" / "fact_only") |
| `regen_count` | flow 내부 explain_retries (state에 있음 — payload에 추가 가능) |

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

## 4. 백엔드 확인 사항 (남은 것)

- **A. `flow_reports.id` 에 우리 report_id(uuid4)를 넣어도 되나?** 컬럼 default가
  `gen_random_uuid()`라 DB가 새로 만들 수 있는데, 그러면 §3-5가 깨진다. 우리 UUID를
  그대로 PK로 받아 달라.
- **B. `data_status` 값 규칙**은? flow는 게이트 결과로 파생 가능(예: 게이트2 실패→
  degraded). 원하는 enum을 알려주면 payload에 실어 준다.
- **C. `trace_id` = report_id 로 봐도 되나,** 슈퍼바이저가 전 에이전트를 묶는 상위
  추적 ID인가? 후자면 슈퍼바이저가 주입하는 값의 형식을 알려 달라.
- **D. `interpretation_source` 값 규칙**(llm/fallback 등)? null 의미(§3-4)와 정합 필요.
- **E. `outcome`·`regen_count`를 payload에서 받을지, 백엔드가 verification에서
  파생할지.** flow는 둘 다 안다(outcome=게이트3 통과 여부, regen=explain_retries) —
  payload에 추가는 쉽다. "받을지"만 정해 달라.

> B·D·E와 provider·model·regen_count는 **flow가 payload에 넣는 건 간단**하다.
> 백엔드가 "payload에서 받겠다"고 하면 flow가 다음 커밋에서 필드를 추가한다
> (version은 유지 — 추가 필드는 하위 호환). "백엔드가 파생하겠다"면 flow는 그대로 둔다.

## 5. 지금 안 만드는 것 (요구가 실물로 오면)

- signals 정규화 테이블 — "외국인 5일 연속 순매수 종목 검색" 같은 크로스 리포트
  검색이 생기면. 그 전엔 JSONB(필요 시 GIN 인덱스)로 충분.
- 게이트 통과율 모니터링 — 운영 지표 요구가 오면 flow_report_verifications에서 파생.
