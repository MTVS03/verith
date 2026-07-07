# flow 리포트 저장 명세 (ERD 초안) — 백엔드 전달용

작성: flow 담당 · 2026-07-07 · payload version 1 기준
성격: **요구 명세**다. 최종 DB 설계(엔진·타입·파티셔닝)는 백엔드 판단.
"이렇게 저장돼야 잘 불러와진다"의 요구와 불변식만 정의한다.

## 0. 저장 대상 — payload가 진실이다

flow 에이전트의 산출물은 `AgentOutput`이며, 저장 관점에서 핵심은
`payload`(JSON, 현재 ~4KB)다. 구조(version 1):

```json
{
  "version": 1,
  "report_id": "uuid 문자열",
  "meta":   { "stock_name": "삼성전자", "ticker": "005930",
              "market": "KOSPI200", "base_date": "2026-07-06" },
  "signals": { "consecutive": …, "strength": …, "alignment": "동반매수",
               "daily": […], "persistence": …, "inst_detail": …,
               "ownership": […] },
  "verification": { "gate1": {passed, checks[], failures[]},
                    "gate2": {…}, "gate3": {…} },
  "interpretation": "LLM 해석 (게이트3 통과분만, 아니면 null)"
}
```

- `signals`의 키는 한글이다(개인·외국인·기관·증권…). 리포트 화면·검증
  문장과 같은 어휘로 대조되게 하기 위한 의도적 선택 — 바꾸지 말 것.
- `verification`이 이 프로젝트의 정체성이다: 모든 숫자에 "무엇으로
  검증됐는지"의 문장(checks 전문)이 붙어 있다. **저장·조회 과정에서
  signals와 verification이 분리되면 안 된다** (검증 없는 숫자가 됨).

## 1. ERD 초안

```
┌──────────────────────────────────────────────┐
│ reports                                      │
├──────────────────────────────────────────────┤
│ report_id   UUID        PK                   │
│ ticker      CHAR(6)     NOT NULL             │
│ stock_name  VARCHAR(64) NOT NULL             │
│ market      VARCHAR(32) NULL                 │
│ base_date   DATE        NOT NULL             │
│ version     SMALLINT    NOT NULL             │
│ payload     JSONB       NOT NULL             │
│ html        TEXT        NULL     (계약 미정) │
│ created_at  TIMESTAMPTZ NOT NULL DEFAULT now │
├──────────────────────────────────────────────┤
│ INDEX (ticker, base_date DESC)               │
│ INDEX (created_at)                           │
└──────────────────────────────────────────────┘
```

테이블 하나로 시작한다. 정규화(파생 테이블)는 §4 참고.

### 컬럼 근거
- **report_id = AI 서버 발급 UUID(uuid4)가 그대로 PK**. DB 자동증가 금지 —
  에이전트가 생성 순간 ID를 붙여 로그·검증·저장·조회를 한 ID가 관통한다
  (상관관계 ID). 저장 시 새 ID를 만들면 이 추적이 끊긴다.
- **ticker·stock_name·market·base_date** = payload.meta의 **승격(promotion) 복사**.
  목록·필터 조회를 위한 인덱스용이며, 진실은 payload다(§2 불변식 3).
  stock_name은 요청 당시 스냅샷(종목명은 바뀔 수 있음). market은 KIS 원본
  문자열('KOSPI200'·'KSQ150' 등)이고 null 가능.
- **version** = payload 스키마 세대. 구조가 바뀌면 flow가 +1 한다.
  불러오는 쪽은 version으로 분기한다(마이그레이션 열쇠).
- **payload = JSONB 통짜 저장**. 정규화하지 않는 이유: 스키마가 아직
  진화 중(M2 직후)이고, version 필드가 세대를 구분해 주므로 JSONB가
  변경에 가장 강하다. 검색 요구가 실물로 생기면 그때 파생 테이블(§4).
- **html** = 출력 계약(HTML vs JSON) 확정 전이라 NULL 허용으로 자리만.
  계약이 HTML이면 NOT NULL로 승격, JSON이면 컬럼 제거.
- **created_at = DB가 찍는다**. flow는 생성 시각을 payload에 넣지 않는다
  (계산·검증된 값이 아닌 "새 값"을 만들지 않는 원칙). 저장 시각은 저장
  주체의 사실이므로 DB 몫.

## 2. 불변식 (지켜져야 "잘 불러와진다")

1. **payload는 저장 후 불변(immutable)**. 검증된 사실의 스냅샷이다.
   수정이 필요하면 새 리포트(새 report_id)를 만든다 — 검증 이력 훼손 금지.
2. **signals와 verification은 함께만 반환한다**. signals만 잘라 주는 API를
   만들면 "검증 없는 숫자"가 되어 이 프로젝트의 정체성이 깨진다.
3. **승격 컬럼(ticker 등 4개)과 payload.meta는 항상 같은 값**. 어긋나면
   payload가 정답이다. (저장 시 payload에서 뽑아 채우는 것을 권장 —
   두 소스에서 따로 받지 말 것.)
4. **interpretation은 payload 밖으로 꺼내 별도 저장하더라도 null 의미 유지**:
   null = "게이트3(해석↔팩트 검증)을 통과한 해석이 없었음"이다.
   빈 문자열 등으로 바꾸면 의미가 사라진다.

## 3. 예상 조회 패턴 (인덱스 근거)

| 패턴 | 쿼리 형태 |
|---|---|
| 리포트 열람 | `WHERE report_id = ?` (PK) |
| 종목 최신 리포트 | `WHERE ticker=? ORDER BY base_date DESC, created_at DESC LIMIT 1` |
| 종목 이력 목록 | `WHERE ticker=? ORDER BY base_date DESC` |
| 특정일 전체 종목 | `WHERE base_date=?` (필요 시 인덱스 추가) |

동일 (ticker, base_date) 재생성은 **허용**을 제안한다(이력 보존 —
재실행하면 KIS 데이터가 같아도 해석이 다를 수 있음). 최신만 보여주는
것은 조회 쪽 규칙(created_at DESC)으로.

## 4. 지금 안 만드는 것 (요구가 실물로 오면)

- signals 정규화 테이블(예: 일별 순매수 행 테이블) — "외국인 5일 연속
  순매수 종목 검색" 같은 크로스 리포트 검색이 생기면. 그 전엔 JSONB
  (필요 시 GIN 인덱스)로 충분할 것으로 예상.
- 게이트 통과율 모니터링 테이블 — 운영 지표 요구가 오면
  verification에서 파생.

## 5. 백엔드에 묻는 것 (열린 질문)

1. 출력 계약: HTML도 저장하나, payload만 저장하나? (html 컬럼의 운명)
2. 사용자↔리포트 연결(누가 요청했나)은 백엔드 소관으로 이해 — 맞나?
3. 보존 기간/용량 정책 (리포트당 ~4KB + HTML ~36KB)
4. DB 엔진 전제: 이 명세는 PostgreSQL(JSONB) 기준 표기 — 다른 엔진이면
   JSONB→JSON/TEXT로 읽어 달라(요구는 동일).
