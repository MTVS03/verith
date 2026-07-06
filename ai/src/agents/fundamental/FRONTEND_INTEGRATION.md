# Fundamental Frontend Integration Guide

이 문서는 공용 `frontend`를 직접 수정하지 않고, merge 담당자가 fundamental 리포트를 붙일 때 참고하는 계약입니다.

## Primary Payload

`analyze_fundamental()` 결과의 핵심 필드:

| field | frontend use |
| --- | --- |
| `score` | 절대 재무점수. ROE, 마진, 안정성, 성장성을 보수적으로 합산한 100점 기준 |
| `score_breakdown.peer_relative` | 10개사 배치에서 생성되는 동종군 상대 위치 |
| `meta.sector_relative_score` | 동종군 백분위 점수. 낮은 절대점수를 보완하는 표시용 점수 |
| `verdict_label` | 내부 라벨: `strong`, `moderate`, `weak`, `insufficient_data` |
| `ratios` | 지표 카드용 데이터. `value`, `unit`, `display_value`, `label`, `reason` 포함 |
| `trend` | 4개년 차트용 데이터. `years`, `revenue`, `op_income`, `roe`, `display` 포함 |
| `insights` | 배당, 주주구성, 감사의견 등 DART 추가 인사이트 |
| `evidence` | DART 원문 근거 링크, 계정 바인딩, `display_value` |
| `risk_flags` | 데이터 누락, fallback, 검증 경고 |
| `report_html` | 격리 삽입 가능한 기본 HTML 리포트 블록 |

## Recommended Layout

프론트에서는 `report_html`을 그대로 붙일 수 있지만, 최종 UI에서는 아래 구조로 분해 렌더링하는 편이 좋습니다.

| section | source |
| --- | --- |
| 상단 점수 카드 | `score`, `verdict_label`, `confidence`, `meta.sector_relative_score` |
| 핵심 재무지표 카드 | `ratios` |
| 4개년 추세 차트 | `trend.revenue`, `trend.op_income`, `trend.roe` |
| Qwen 분석 문장 | `verdict`, `interpretation` |
| DART 추가 인사이트 | `insights.dividend`, `insights.major_holder`, `insights.minor_holder`, `insights.audit` |
| 근거/리스크 | `evidence`, `risk_flags` |

## Storage Payload Contract

`meta.erd_payload`는 백엔드 저장 미리보기입니다. 현재 ERD보다 agent 쪽 payload가 더 넓게 나가는 필드는 백엔드에서 무시해도 됩니다.

백엔드 무시 가능 확장 필드:

- `fundamental_report.request_id`, `verdict_label`, `risk_flags`
- `report_ratios.status`, `reason`, `display_value`, `unit`, `category`, `basis`
- `report_evidence.currency`, `display_value`, `raw`
- `report_interpretation.interpretation_source`
- `report_verification.regen_count`
- 최상위 `retrieval_summary`

`report_id`는 `trace_id`, `stock_code`, `bsns_year`, `reprt_code` 기반으로 생성되어 실행마다 새 행을 남기는 이력 보존 모델입니다. 종목당 최신 1건만 필요하면 백엔드에서 `(stock_code, bsns_year, reprt_code)` 기준으로 dedupe 하세요.

## Score Display Rule

`score`는 절대 재무 건강도입니다. 2차전지 업황처럼 적자, 역성장, 마진 압박이 많은 구간에서는 전반적으로 낮게 나올 수 있습니다.

프론트 표시 권장:

- 메인 숫자: `score`
- 보조 배지: `meta.sector_relative_score` 또는 `score_breakdown.peer_relative.percentile`
- 설명 문구: `score_breakdown.score_explanation`

예시:

```text
절대 재무점수 45점
2차전지 10개사 기준 동종군 백분위 88.9점
```

## Formatting Rule

원화 총액은 `formatting.format_krw()` 기준으로 표시합니다.
프론트는 가능하면 `display_value`와 `trend.display`를 우선 사용하고, raw `value`는 차트/정렬/계산용으로만 사용합니다.

예시:

| raw | display |
| ---: | --- |
| `23671759000000` | `23조 6,717억 5,900만원` |
| `575387000000` | `5,753억 8,700만원` |
| `125306.31` | `125,306.31원` |

## Local Artifacts

검증 산출물:

| path | note |
| --- | --- |
| `api_test/samples/fundamental_response_sample.json` | 단일 기업 샘플 payload |
| `api_test/samples/fundamental_report_sample.html` | 기본 HTML 리포트 |
| `api_test/samples/qwen_output_sample.md` | Notion 공유용 Qwen 출력 샘플 |
| `api_test/out/summary.md` | 10개사 배치 비교표 |

## Verification Command

```bat
cd /d C:\verith\ai
C:\verith\ai\src\agents\fundamental\api_test\run_checks.bat
```
