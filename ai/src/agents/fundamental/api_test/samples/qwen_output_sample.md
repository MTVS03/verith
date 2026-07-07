# Fundamental Agent Qwen 출력 샘플

## 실행 명령어

```bat
cd C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.make_sample_payload
```

## 실행 결과 요약

- 기업: LG에너지솔루션 (`373220`)
- LLM provider: `qwen`
- LLM model: `Qwen3.6-35B-A3B-UD-Q6_K.gguf`
- score: `45`
- verdict_label: `moderate`
- confidence: `0.9`
- risk_flags: 없음

## Qwen 생성 문장

### Verdict

LG에너지솔루션은 2025년 기준 수익성 지표가 낮아지고 매출이 감소하는 등 성장 모멘텀이 약화되었으나, 영업이익은 반등하며 안정성을 유지하고 있는 중립적 상태입니다.

### Interpretation

수익성 측면에서 ROE는 0.28%, 영업이익률은 5.69%, 순이익률은 0.34%로 전년 대비 낮아진 수준을 보이고 있습니다. 안정성 지표인 부채비율은 129.0%, 유동비율은 109.69%로 재무 구조가 비교적 안정적입니다. 성장성에서는 매출이 -7.6% 감소했으나 영업이익은 133.95% 증가하여 수익성 개선이 이루어졌습니다. 다만 EPS가 -4585원으로 적자 상태이며, 최대주주인 ㈜LG화학의 지분율이 79.38%로 매우 높아 소수주주의 영향력이 제한적입니다.

## 주요 재무 지표

| metric | value | fiscal_year | 산출불가 사유 |
| --- | ---: | --- | --- |
| `roe` | 0.28% | 2025 |  |
| `operating_margin` | 5.69% | 2025 |  |
| `net_margin` | 0.34% | 2025 |  |
| `debt_ratio` | 129% | 2025 |  |
| `current_ratio` | 109.69% | 2025 |  |
| `revenue_growth` | -7.6% | 2025 |  |
| `operating_income_growth` | 133.95% | 2025 |  |
| `eps` | -4,585원 | 2025 |  |
| `bps` | 125,306.31원 | 2025 |  |

## Evidence / DART 출처

| metric | value | fiscal_year | rcept_no | account_ids |
| --- | ---: | --- | --- | --- |
| `roe` | 0.28% | 2025 | `20260312000217` | `ifrs-full_ProfitLoss` |
| `operating_margin` | 5.69% | 2025 | `20260312000217` | `dart_OperatingIncomeLoss` |
| `net_margin` | 0.34% | 2025 | `20260312000217` | `ifrs-full_ProfitLoss` |
| `debt_ratio` | 129% | 2025 | `20260312000217` | `ifrs-full_Liabilities` |
| `current_ratio` | 109.69% | 2025 | `20260312000217` | `ifrs-full_CurrentAssets` |
| `revenue_growth` | -7.6% | 2025 | `20260312000217` | `ifrs-full_Revenue`, `ifrs-full_RevenueFromContractsWithCustomers`, `dart_OperatingRevenue` |
| `operating_income_growth` | 133.95% | 2025 | `20260312000217` | `dart_OperatingIncomeLoss` |
| `eps` | -4,585원 | 2025 | `20260312000217` | `ifrs-full_BasicEarningsLossPerShare` |
| `bps` | 125,306.31원 | 2025 | `20260312000217` | `ifrs-full_Equity`, `stockTotqySttus:istc_totqy` |

## 프론트/백엔드 연동 참고 필드

- `ratios`: 비율 그리드 렌더링
- `trend`: 차트 렌더링
- `evidence`: DART 원문 링크와 수치 출처
- `report_html`: 격리 삽입용 financial HTML block
- `meta.llm_provider`: Qwen/OpenAI/template 사용 여부 확인
