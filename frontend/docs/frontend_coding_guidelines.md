# veriθ Frontend — 코드 작성 규칙

`docs/frontend_coding_guidelines.md`

이 문서는 veriθ 프론트엔드를 구현할 때 지켜야 할 코드 작성 기준을 정리한다. 목적은 **UI 하드코딩, API 계약 불일치, 화면 로직 과밀, 분석값 임의 생성, 비밀값 노출, 재사용 불가능한 컴포넌트**를 방지하는 것이다.

프론트엔드는 veriθ에서 **백엔드가 제공한 JSON을 사용자에게 이해하기 쉽게 렌더링하는 계층**이다. 프론트는 기술적 지표를 직접 계산하거나 AI 해석을 새로 만들지 않는다.

---

## 1. 기본 원칙

### 1.1 문서가 먼저, 화면은 그다음

프론트 화면 구조와 라벨은 문서가 정본이다.

- JSON 구조는 `docs/contracts.md`를 따른다.
- API 요청·응답은 `docs/api_spec.md`를 따른다.
- 화면 섹션과 라벨은 `docs/frontend_mapping.md`를 따른다.
- enum 코드값과 한글 라벨은 `docs/enums.md`를 따른다.

프론트가 임의로 새 필드나 새 라벨을 만들지 않는다.

### 1.2 프론트는 렌더링 계층이다

프론트의 책임은 다음이다.

1. 사용자 입력 수집
2. 백엔드 API 호출
3. 로딩·에러·빈 상태 표시
4. 백엔드 JSON 렌더링
5. enum 코드값을 사용자 친화 라벨로 표시
6. 차트와 카드 UI 구성

프론트는 regime, signal_score, confidence, risk를 직접 계산하지 않는다.

---

## 2. 하드코딩 금지

### 2.1 금지하는 하드코딩

아래 값은 컴포넌트 내부에 직접 박아 넣지 않는다.

- API base URL
- enum 코드값 한글 라벨
- risk flag 라벨
- regime 라벨
- confidence 구간 라벨
- status 문구
- 차트 period 목록
- 색상 토큰
- spacing 값 반복
- 임시 report id
- 테스트용 ticker

나쁜 예:

```tsx
<span>상승 추세 유지</span>
```

좋은 예:

```tsx
<span>{REGIME_LABELS[report.regime.final_regime]}</span>
```

### 2.2 환경변수는 public 값만 둔다

프론트 환경변수에는 공개되어도 되는 값만 둔다.

허용:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

금지:

```bash
KIS_API_SECRET=...
JWT_SECRET=...
DB_PASSWORD=...
```

프론트 번들에 들어가는 값은 사용자 브라우저에서 볼 수 있다고 생각한다.

---

## 3. 화면 책임 경계

### 3.1 프론트가 하지 말아야 할 것

프론트는 아래 일을 하지 않는다.

- KIS API 직접 호출
- AI 서버 직접 호출
- RSI, MA, Bollinger 계산
- regime 판정
- signal_score 계산
- confidence 계산
- risk flag 생성
- LLM 해석 생성
- DB 직접 접근

프론트는 백엔드 API만 호출한다.

### 3.2 분석값을 임의로 보정하지 않는다

금지:

```tsx
const finalRegime = report.signal_score > 0.5 ? "uptrend_intact" : "sideways";
```

허용:

```tsx
const finalRegime = report.regime.final_regime;
```

프론트에서 할 수 있는 것은 **표시 변환**뿐이다.

---

## 4. 폴더 구조와 모듈화

### 4.1 권장 구조

실제 프로젝트 구조에 맞추되, 책임은 분리한다.

```text
frontend/src/
├── api/              # 백엔드 API client
├── components/       # 재사용 UI 컴포넌트
├── pages/            # 라우트 단위 화면
├── features/         # 도메인별 화면 묶음
├── types/            # API/도메인 타입
├── constants/        # enum label, UI constants
├── hooks/            # 데이터 조회와 상태 훅
├── utils/            # 순수 유틸 함수
└── styles/           # 디자인 토큰, 공통 스타일
```

| 영역 | 책임 | 하지 말아야 할 것 |
| --- | --- | --- |
| `api/` | HTTP 요청 함수 | UI 렌더링 |
| `types/` | contract 기반 타입 | API 호출 |
| `constants/` | 라벨·색상·상수 | 상태 관리 |
| `components/` | 재사용 UI | 직접 API 호출 남발 |
| `pages/` | 화면 조립 | 세부 렌더 로직 과밀 |
| `hooks/` | 데이터 조회·상태 | 라벨 하드코딩 |
| `utils/` | 순수 함수 | API 호출, 전역 상태 변경 |

### 4.2 컴포넌트를 작게 나눈다

한 컴포넌트에서 아래 일을 모두 처리하지 않는다.

- API 호출
- 데이터 변환
- 카드 렌더링
- 차트 렌더링
- 에러 처리
- 모달 처리

나쁜 예:

```tsx
function ReportPage() {
  // fetch
  // map labels
  // draw chart
  // render risk cards
  // handle errors
  // modal state
}
```

좋은 예:

```tsx
function ReportPage() {
  const { data, isLoading, error } = useTechnicalReport(reportId);

  return <TechnicalReportView report={data} />;
}
```

---

## 5. API 호출 규칙

### 5.1 API client를 분리한다

컴포넌트 안에서 `fetch` 또는 `axios`를 직접 반복하지 않는다.

나쁜 예:

```tsx
useEffect(() => {
  fetch("/api/technical/reports");
}, []);
```

좋은 예:

```tsx
const report = await technicalReportApi.createReport(payload);
```

### 5.2 요청·응답 타입을 명확히 둔다

백엔드 응답은 타입으로 관리한다.

```ts
export type TechnicalReportResponse = {
  report_id: string;
  report: TechnicalReport;
};
```

가능하면 `docs/contracts.md`와 1:1로 맞춘다.

### 5.3 로딩·에러·빈 상태를 반드시 둔다

모든 API 화면은 다음 상태를 가진다.

- loading
- success
- empty
- error
- data_limited
- stale_cache
- regime_unavailable
- out_of_scope_ticker
- template_fallback

문서상 정상 상태인 `data_limited`, `stale_cache`, `regime_unavailable`, `out_of_scope_ticker`, `template_fallback`을 무조건 에러 화면으로 처리하지 않는다. (`out_of_scope_ticker`는 allowlist 밖 종목 안내, `template_fallback`은 LLM 검증 실패 후 템플릿으로 대체된 정상 문장이다 — `enums.md §8·§9`.)

---

## 6. 라벨과 문구 규칙

### 6.1 enum 라벨은 중앙에서 관리한다

나쁜 예:

```tsx
{report.final_regime === "sideways" ? "횡보" : "상승"}
```

좋은 예:

```ts
export const REGIME_LABELS = {
  oversold_rebound_watch: "과매도 반등 관찰",
  overheated: "과열",
  bullish_reversal_watch: "상승 전환 관찰",
  uptrend_intact: "상승 추세 유지",
  downtrend: "하락 추세",
  sideways: "횡보",
  unavailable: "판단 불가",
} as const;
```

컴포넌트는 이 상수를 가져다 쓴다.

라벨 맵은 REGIME_LABELS 하나만이 아니다. `enums.md`에 정의된 모든 열거형이 중앙 상수 대상이다: regime, consensus(신호 종합), signal(지표별), trend(주/월봉 추세), alignment_flag, confidence_level, risk_flags, data_status, source(해석 출처), period(차트 기간). 각 라벨 맵의 코드값·한글 라벨은 `enums.md`를 1:1로 따르고, 프론트가 임의 라벨을 만들지 않는다. `neutral`은 regime이 아니라 `consensus`·`alignment_flag`에 속하는 값임에 주의한다(축을 섞지 않는다).

### 6.2 투자 권유 표현 금지

사용자 노출 문구에 아래 표현을 쓰지 않는다.

- 매수
- 매도
- 사라
- 팔아라
- 추천주
- 급등 보장
- 목표 수익률
- 예상 수익률
- 적중률
- 실시간 (KIS는 준실시간이므로 "장중/준실시간"으로 표기)

단, **과거 등락률·변동률처럼 데이터 기반 값은 허용**한다(`enums.md` 사용규약 3). 금지 대상은 미래 수익률을 예측·보장하는 표현이지, 이미 발생한 과거 데이터가 아니다.

대체 표현:

| 피해야 할 표현 | 대체 표현 |
| --- | --- |
| 매수 신호 | 긍정 신호 |
| 매도 신호 | 부정 신호 |
| 사도 된다 | 긍정 요인이 관찰됩니다 |
| 팔아야 한다 | 부정 요인이 관찰됩니다 |
| 급등 가능 | 변동성 확대 가능성이 있습니다 |
| 실시간 시세 | 장중 시세 / 준실시간 시세 |

---

## 7. 차트 렌더링 규칙

### 7.1 차트 데이터는 백엔드/AI JSON을 그대로 사용한다

프론트에서 OHLCV를 다시 계산하거나 annotation을 새로 만들지 않는다.

금지:

```tsx
const rsi = calculateRsi(candles);
```

허용:

```tsx
const rsiSeries = report.charts[0].chart_data.subcharts.rsi;
```

### 7.2 차트가 없어도 화면이 깨지지 않게 한다

차트 데이터는 상태에 따라 비어 있을 수 있다.

- `data_limited`
- `regime_unavailable`
- KIS 일부 실패
- 특정 period 미지원

빈 배열, null, undefined에 대해 안전하게 처리한다.

---

## 8. 상태 관리 규칙

### 8.1 서버 상태와 UI 상태를 구분한다

서버에서 가져온 데이터와 화면 내부 상태를 섞지 않는다.

서버 상태 예:

- report detail
- report list
- trace detail

UI 상태 예:

- 선택된 tab
- modal open 여부
- chart period 선택
- filter 값

### 8.2 서버 응답을 불필요하게 복사하지 않는다

나쁜 예:

```tsx
const [finalRegime, setFinalRegime] = useState(report.final_regime);
```

좋은 예:

```tsx
const finalRegime = report.final_regime;
```

편집 가능한 값이 아니라면 state로 복사하지 않는다.

---

## 9. 스타일 규칙

### 9.1 색상과 spacing은 토큰화한다

컴포넌트마다 임의 색상을 반복하지 않는다.

나쁜 예:

```tsx
<div style={{ color: "#22c55e", marginTop: "17px" }} />
```

좋은 예:

```tsx
<div className="text-positive mt-4" />
```

또는 프로젝트 스타일 시스템의 토큰을 사용한다.

### 9.2 정보 위계가 먼저다

리포트 화면은 예쁘기 전에 읽기 쉬워야 한다.

권장 정보 순서:

1. 종목명·기준일
2. 최종 국면
3. 신호 요약
4. 신뢰도
5. 리스크 관찰점
6. 지표별 기술 신호
7. 차트
8. 검증/trace 정보

---

## 10. 접근성과 사용성

### 10.1 색상만으로 의미를 전달하지 않는다

긍정/부정/중립은 색상뿐 아니라 텍스트·아이콘·라벨로도 전달한다.

나쁜 예:

```tsx
<span className="green-dot" />
```

좋은 예:

```tsx
<StatusBadge label="긍정 우세" tone="positive" />
```

### 10.2 로딩 시간이 긴 작업은 진행 상태를 보여준다

AI 분석 생성은 시간이 걸릴 수 있으므로 사용자가 멈춘 것으로 느끼지 않게 한다.

- 분석 요청 중
- 데이터 수집 중
- 리포트 생성 중
- 결과 저장 중

단, 실제 backend/AI 상태와 맞지 않는 가짜 단계는 만들지 않는다.

---

## 11. 테스트 규칙

### 11.1 순수 함수는 단위테스트한다

테스트 대상:

- enum label mapping
- confidence level 표시 변환
- API response parser
- 날짜 포맷 변환
- 숫자 포맷 변환
- empty state 판정

### 11.2 컴포넌트는 핵심 상태를 테스트한다

테스트 대상:

- loading 화면
- error 화면
- data_limited 안내
- stale_cache 안내
- regime_unavailable 안내
- risk card 렌더링
- chart 데이터 없음 처리

### 11.3 테스트에서 실제 백엔드를 호출하지 않는다

프론트 테스트는 mock API를 사용한다.

---

## 12. 코드 생성 도구 사용 규칙

Claude/Codex에게 프론트 작업을 맡길 때는 화면 단위와 책임을 좁힌다.

좋은 지시:

```text
TechnicalReportCard 컴포넌트만 작성하세요.
API 호출, 차트 구현, 상태 관리는 만들지 마세요.
props로 받은 report summary만 렌더링하세요.
```

나쁜 지시:

```text
프론트 만들어줘.
```

검토 기준:

- 컴포넌트에서 API를 직접 호출했는가?
- 라벨을 하드코딩했는가?
- 분석값을 직접 계산했는가?
- 문서에 없는 필드를 사용했는가?
- 로딩/에러/빈 상태가 빠졌는가?
- 비밀값을 프론트 env에 넣었는가?

---

## 13. 커밋 전 체크리스트

```bash
git status
git diff
```

체크리스트:

- [ ] API 계약과 타입이 일치하는가?
- [ ] 컴포넌트가 너무 많은 일을 하지 않는가?
- [ ] enum 라벨이 중앙 상수에서 관리되는가?
- [ ] 프론트가 분석값을 직접 계산하지 않는가?
- [ ] KIS/AI/DB를 직접 호출하지 않는가?
- [ ] 비밀값이 번들에 들어가지 않는가?
- [ ] 로딩·에러·빈 상태가 있는가?
- [ ] `data_limited`, `stale_cache`, `regime_unavailable`을 정상 상태로 렌더링하는가?
- [ ] 사용자 노출 문구에 투자 권유 표현이 없는가?

---

## 14. 최종 원칙

프론트는 분석 엔진이 아니라 **해석 가능한 화면 계층**이다.

- Backend API만 호출한다.
- 받은 JSON을 문서 기준으로 렌더링한다.
- 라벨과 문구는 중앙에서 관리한다.
- 분석값을 임의로 만들지 않는다.
- 사용자가 상태를 이해할 수 있게 보여준다.

프론트가 계산과 판단을 가져가기 시작하면 백엔드·AI와 결과가 어긋난다. 프론트는 보기 좋게 만드는 것보다 **정확하게 보여주는 것**이 먼저다.
