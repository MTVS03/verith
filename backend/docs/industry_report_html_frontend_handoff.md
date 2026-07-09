# Industry Report(HTML 리포트) — Frontend Handoff

`backend/docs/industry_report_html_frontend_handoff.md`

Industry 리포트를 프론트 화면에 띄우기 위한 handoff 문서다. Technical 처럼 React 컴포넌트로
그리는 게 아니라, **AI 쪽에서 완성된 HTML 문서를 받아 `iframe` 으로 띄우는 구조**를 제안한다.
왜 그런 구조인지, 프론트가 무엇을 하면 되는지, 어디서 깨지는지를 적는다.

관련 문서: [`industry_backend_handoff.md`](industry_backend_handoff.md) ·
[`report_archive_api_contract.md`](report_archive_api_contract.md) ·
[`technical_frontend_api_contract.md`](technical_frontend_api_contract.md)

> **이 문서의 상태 표기**
> - ✅ **구현됨** — 지금 코드에 있다.
> - 🔲 **미구현(제안)** — 아직 없다. 이 문서가 제안하는 계약이다. 착수 전 백엔드/AI 담당과 합의할 것.

---

## 1. 현재 상태 (사실만)

✅ **JSON 은 이미 끝까지 흐른다.**

```
frontend ──JSON──> backend (FastAPI) ──HTTP/JSON──> ai (FastAPI) ──> Neo4j/LangGraph
                    payload 를 JSONB 로 저장           research-report.v1 반환
```

- `industry_reports.payload` 컬럼에 AI 가 반환한 `research-report.v1` payload 가 **가공 없이 그대로**
  저장된다 — `backend/src/api/services/industry_report_service.py:103`
- `GET /api/industry/reports/{id}` 가 그 payload 를 그대로 돌려준다 — 같은 파일 `:145`
- 즉 **"버튼 → DB 에서 JSON 조회"는 이미 동작한다.** 프론트가 새로 만들 필요가 없다.

✅ **HTML 렌더러도 이미 있다. 단, CLI 전용이다.**

- `ai/src/agents/industry/make_report/render.py` 의 `render_report_html(payload)` 가
  payload 를 `report_template.html` 에 주입해 **완전한 standalone HTML 문서**를 만든다.
- 이 모듈은 **표준 라이브러리만 import 한다.** Neo4j·LangGraph 없이 payload 만 있으면 HTML 이 나온다.
  → 리포트를 다시 그리려고 에이전트를 재실행할 필요가 없다. 이 사실이 아래 설계의 전제다.
- 현재는 `python -m src.agents.industry.make_report report.json --out report.html` 로만 호출된다.
  **HTTP 경로가 없다.** `ai/src/api/industry.py` 는 JSON 만 반환한다.

🔲 **없는 것 (= 이번에 만들 것)**

- Industry 리포트 **화면 자체가 없다.** `frontend/src/app/reports/industry/[reportId]/` 는
  `.gitkeep` 만 있는 빈 디렉터리다.
- `frontend/src/lib/report-links.ts:4` 는 `technical` 이 아니면 `null` 을 반환한다.
  → 보관함(archive)에서 industry 카드에 **링크조차 걸리지 않는다.**
- 프론트 전체에 `iframe` / `dangerouslySetInnerHTML` 사용처가 **하나도 없다.**
  HTML 문서를 띄우는 경로가 아예 없다.

---

## 2. 제안 구조와 그 이유

```
frontend  <iframe src="/api/industry/reports/{id}/html">
    └─> backend  GET /api/industry/reports/{id}/html
            ├─ DB 에서 payload 조회 (이미 있음)
            └─> ai  POST /internal/industry/render   (payload 를 body 로)
                    └─ render_report_html(payload) → text/html
```

**왜 AI 가 렌더링하나.** 템플릿은 `<script id="research-report-data">` 를 읽어 화면을 그리는 구조라,
렌더링은 결국 "payload 를 문서에 주입"하는 일이다. 그 주입·이스케이프·스키마 검증은
`render_report_html` 이 이미 한다. 프론트에서 하면 그 로직을 TypeScript 로 다시 쓰게 된다.

**왜 backend 가 직접 렌더링하지 않나.** `backend/src/api/clients/ai_client.py:1-8` 에
"backend 는 AI 코드를 import 하지 않고 HTTP 로만 호출한다"는 경계가 명시돼 있다. 렌더러가
stdlib 전용이라 물리적으로는 vendoring 이 가능하지만, 템플릿과 `support.js`(61KB) 까지 복제해야
하므로 권하지 않는다.

**왜 `iframe` 인가.** §5 에서 설명한다. 요약하면 템플릿이 전역 CSS 와 자체 React 런타임을 가진
완전한 문서라, 현재 페이지에 그대로 꽂으면 충돌한다.

---

## 3. API 계약 🔲 (미구현 — 합의 필요)

### `GET /api/industry/reports/{report_id}/html`

| 항목 | 값 |
|---|---|
| 응답 | `200 text/html; charset=utf-8` — `<!doctype html>` 로 시작하는 완결된 문서 |
| 본문 크기 | 약 **120KB** (§5-3) |
| `404` | 해당 `report_id` 없음 |
| `422` | 저장된 payload 가 스키마 위반 (§4) |
| `502` / `504` | AI 서비스 호출 실패 / timeout |

프론트는 이 URL 을 **`iframe` 의 `src` 로만 쓴다.** `fetch` 해서 문자열로 다룰 필요 없다.

### 기존 엔드포인트 (✅ 그대로 사용)

| Method | Path | 용도 |
|---|---|---|
| `GET` | `/api/industry/reports` | 목록 |
| `GET` | `/api/industry/reports/{id}` | payload JSON 단건 (`{ report_id, report }`) |
| `GET` | `/api/reports/archive` | 보관함 공통 카드 리스트 |

> 화면 상단의 제목·질문·생성일 같은 메타를 React 로 따로 그리고 싶으면
> `GET /api/industry/reports/{id}` 의 JSON 을 함께 쓰면 된다. `report.question.text`,
> `report.createdAt`, `report.metrics` 가 들어 있다. **다만 HTML 안에도 같은 내용이 이미
> 그려져 있으므로 중복 표시에 주의.**

---

## 4. 에러 상태 처리

`422` 는 그냥 넘기지 말 것. **의미가 있다.**

템플릿은 payload 를 못 읽으면 조용히 **하드코딩된 에코프로 목업 데이터**로 폴백한다.
그래서 잘못된 리포트가 "그럴듯한 정상 리포트"로 보인다. 이를 막으려고 렌더 직전에
`validate_payload()` 가 스키마(엣지↔노드 참조 무결성, 근거 참조, metrics 개수)를 검사하고
위반 시 예외를 던진다.

- 백엔드의 기존 `_validate_payload` 는 `schemaVersion`·`question.text`·`answer.body` 만 본다
  (`industry_report_service.py:43-54`). 렌더러 쪽 검증이 **더 엄격하다.**
- 따라서 **이미 DB 에 들어간 오래된 행이 `422` 를 낼 수 있다.** 정상이다.
- 프론트는 `422` 를 "리포트를 표시할 수 없습니다 (데이터 손상)" 로 안내하고,
  빈 iframe 을 띄우지 말 것.

---

## 5. 프론트가 부딪힐 지점

### 5-1. `iframe` 이어야 한다 — `dangerouslySetInnerHTML` 금지

템플릿은 `<html>` 부터 시작하는 완전한 문서이고, `body{margin:0;background:#eceef3}` 같은
**전역 CSS** 와 **자체 React UMD 런타임**을 싣는다. Next.js 페이지에 그대로 주입하면 스타일이
앱 전체로 새고 React 인스턴스가 충돌한다.

스크립트가 실행돼야 하므로 `sandbox` 를 쓸 거면 `allow-scripts` 가 필수다.

```tsx
// frontend/src/app/reports/industry/[reportId]/page.tsx  (스케치)
export default async function IndustryReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  return (
    <iframe
      src={`/api/industry/reports/${reportId}/html`}
      title="산업/거시 보고서"
      sandbox="allow-scripts allow-popups"
      style={{ width: "100%", height: "100vh", border: 0 }}
    />
  );
}
```

- `allow-popups` 는 근거 카드의 **"원문 열기"** 링크(DART 새 탭)를 위해 필요하다.
- `allow-same-origin` 은 넣지 말 것. 리포트는 자기 문서만 그리면 되고, 부모 DOM 에 접근할 이유가 없다.
- 높이: 리포트 길이가 payload(노드·근거 개수)에 따라 달라진다. 고정 `100vh` 로 내부 스크롤을 두거나,
  자동 높이가 필요하면 템플릿에서 `postMessage` 로 높이를 올려주는 작업이 **추가로 필요**하다(현재 없음).

### 5-2. 외부 CDN 의존이 남아 있다 ⚠️

- `support.js` 가 런타임에 **unpkg** 에서 React UMD 를 받아온다.
- 템플릿이 **jsdelivr** 에서 Pretendard 폰트를 받아온다.

현재 `frontend/next.config.ts` 에 CSP 설정이 없어서 그냥 동작한다. **CSP 를 켜거나 사내망/오프라인
환경으로 가는 순간 리포트가 백지가 된다.** 완전 self-contained 로 만들려면 React UMD 까지
`support.js` 에 번들해야 하고, 이건 별도 작업이다. CSP 도입 계획이 있으면 미리 공유해 달라.

### 5-3. 응답이 매번 ~120KB 다

`support.js` 61KB 가 문서마다 인라인된다. 지금 규모에선 문제없지만, 목록에서 리포트를 여러 개
동시에 프리뷰하는 식이면 부담이다. 필요해지면 백엔드 캐싱이나 `support.js` 정적 분리로 해결한다.

### 5-4. 템플릿 안의 `PDF` · `공유` 버튼은 목업이다

우측 상단 두 버튼은 **아무 동작도 하지 않는다.** 실제 기능이 필요하면 별도 작업이다.
프론트에서 iframe 바깥에 자체 툴바를 얹는 편이 낫다.

---

## 6. 리포트 화면에 실제로 그려지는 것

payload 기반으로 아래가 렌더링된다 (노드 8·엣지 7 payload 로 확인).

- **히어로**: 질문 텍스트, 생성일, 질문 타입, 조회 행수, 엣지 수, 검증 상태 뱃지
- **지표 카드 3종**: 관계 구성 막대, 그래프 엣지/노드 수, 검증 상태(`verified`/`경고`/`정보 없음`)
- **답변 요약**: headline, body, 태그 칩. 미검증 진술이 있으면 "경고"로 표시
- **관계 그래프**: SVG. 관계 타입별 색상(공급 파랑 실선, 경쟁 빨강 점선, 정책 수혜 초록 점선 등),
  노드/엣지 클릭 시 근거 강조. 상단에 관계별 필터 칩
- **근거 링크**: 그래프 근거(`G1`, `G2`…)와 벡터 근거(`V1`…) 카드. 각각 인용문·출처·DART 원문 링크

---

## 7. 착수 순서 (제안)

1. **AI**: `ai/src/api/industry.py` 옆에 `POST /internal/industry/render` 추가.
   body = payload, 응답 = `Response(html, media_type="text/html")`. 약 15줄.
   `ReportPayloadError` → `422`.
2. **Backend**: `ai_client` 에 메서드 하나 + `GET /api/industry/reports/{id}/html` 라우트 하나
   (`HTMLResponse` 프록시).
3. **Frontend**: `reports/industry/[reportId]/page.tsx` 생성 + `report-links.ts:4` 에
   `if (agentType === "industry") return \`/reports/industry/${reportId}\`;` 추가.
4. **검증**: DB 에 이미 있는 industry payload 로 1~2번을 먼저 돌려 `422` 가 나는 행이 없는지 확인.
   (§4 — 기존 데이터가 새 검증을 통과하는지 확인하는 단계다. 건너뛰지 말 것.)

---

## 8. 대안 — 프론트에서 직접 렌더링 (비추천)

`report_template.html` 과 `support.js` 를 `frontend/public/` 에 복사하고, 프론트가 payload JSON 을
받아 `<script id="research-report-data">` 를 직접 주입하는 방법도 있다. AI/백엔드 변경이 없다는 게
유일한 장점이다.

권하지 않는 이유:

- 주입·HTML 이스케이프·스키마 검증 로직을 TypeScript 로 다시 구현해야 한다 (`render.py` 중복).
- 템플릿과 `support.js` 사본이 `ai/` 와 `frontend/` 두 곳에 생겨 갱신 시 갈라진다.
  (이미 `ai/.../data/` 와 `make_report/` 에 사본이 갈라져 있던 걸 최근에 정리했다.)
- 검증을 빠뜨리면 잘못된 payload 가 **목업 데이터로 조용히 폴백**한다 (§4).

그래도 이 길을 택해야 한다면, `render.py` 의 두 이스케이프 처리를 반드시 옮겨야 한다:
`support.js` 인라인 시 `</script` → `<\/script`, payload 주입 시 `</` → `<\/`.
그리고 `window.__resources` 를 세팅해 `support.js` 의 self-refetch 를 꺼야 한다
(안 그러면 리포트 대신 자바스크립트 소스가 화면에 찍힌다 — `render.py:29-37` 주석 참고).
