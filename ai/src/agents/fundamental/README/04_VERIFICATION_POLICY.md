# 04. 검증 정책

검증 계층의 목적은 LLM이 결정론 코드의 숫자·점수·라벨 경계를 넘지 못하게 하는 것입니다. `verify_node.py`는 최종 응답 전에 `verification_summary`와 `risk_flags`를 갱신합니다.

## verification_summary

| 키 | 의미 |
| --- | --- |
| `binding_passed` | `EVIDENCE_UNBOUND_EXCLUDED`가 없으면 통과 |
| `consistency_passed` | `VERIFY_BALANCE_IDENTITY_FAILED_*`, `CONSISTENCY_EPS_MISMATCH`가 없으면 통과 |
| `guard_passed` | `verdict_guard` 위반이 없으면 통과 |
| `verdict_stable` | 최종 verdict 문구의 라벨 의미가 결정론 라벨과 충돌하지 않으면 통과 |
| `outcome` | stability 결과. 현재 `passed`, `guarded`, insufficient 응답의 `insufficient_data` |
| `reasons` | stability 또는 insufficient 사유 |
| `consistency_notes` | EPS 대조 등 consistency 상세 note |
| `regen_count` | verify 단계 retry 횟수 |
| `initial_provider`, `initial_model` | 검증 전 LLM provider/model |
| `final_provider`, `final_model` | 검증 후 provider/model |
| `cost_summary` | LLM call, token, DART/probe call 요약 |

## Guard 구성

| 구성 | 구현 | 목적 |
| --- | --- | --- |
| Evidence binding | `verify/binding.py` | DART 접수번호, 계정 ID, source URL 없는 evidence 제외 |
| Consistency | `verify/consistency.py` | 재무상태표 항등식과 EPS 대조 |
| Verdict guard | `verify/verdict_guard.py` | 투자 권유 표현, 미지원 지표(PER/PBR/ROIC/주가/시가총액), 허용되지 않은 숫자 검출 |
| Stability | `verify/stability.py` | verdict 문구 또는 LLM label이 결정론 label과 충돌하는지 확인 |

Guard 실패 시 `verify_node.py`는 critic revision을 이미 쓰지 않았고 LLM 호출 상한에 여유가 있을 때 한 번 재생성을 시도합니다. 이후에도 위반이 남으면 `build_fallback_interpretation()`으로 template fallback하고 `VERIFY_LLM_OUTPUT_REJECTED`, `LLM_FALLBACK_TEMPLATE`을 추가합니다.

## risk_flags 사전

| 플래그 | 의미 | 발생 위치 |
| --- | --- | --- |
| `UNSUPPORTED_TICKER` | `core/config.py`의 지원 종목에 없는 티커 | `nodes/collect_node.py` |
| `DART_EMPTY_DATA` | DART에서 계산 가능한 재무제표 행을 찾지 못함 | `nodes/collect_node.py` |
| `OFS_FALLBACK` | CFS 행이 없어 OFS로 재조회 | `nodes/collect_node.py` |
| `STALE_DART_CACHE_FALLBACK` | DART refresh 실패 후 stale cache 사용 | `nodes/collect_node.py` |
| `DERIVED_LIABILITIES` | 부채총계가 파생 계정으로 계산됨 | `ratios/calculators.py` |
| `MISSING_ROE` | ROE 계산 불가 | `ratios/calculators.py` |
| `MISSING_OPERATING_MARGIN` | 영업이익률 계산 불가 | `ratios/calculators.py` |
| `MISSING_NET_MARGIN` | 순이익률 계산 불가 | `ratios/calculators.py` |
| `MISSING_DEBT_RATIO` | 부채비율 계산 불가 | `ratios/calculators.py` |
| `MISSING_CURRENT_RATIO` | 유동비율 계산 불가 | `ratios/calculators.py` |
| `MISSING_REVENUE_GROWTH` | 매출성장률 계산 불가 | `ratios/calculators.py` |
| `MISSING_OPERATING_INCOME_GROWTH` | 영업이익성장률 계산 불가 | `ratios/calculators.py` |
| `MISSING_EPS` | DART EPS 계정 식별 실패 | `ratios/calculators.py` |
| `MISSING_BPS` | 발행주식수 또는 자기자본 기반 BPS 계산 불가 | `ratios/calculators.py` |
| `NOT_MEANINGFUL_REVENUE_GROWTH` | 매출성장률을 퍼센트로 표시하면 왜곡됨 | `ratios/calculators.py` |
| `NOT_MEANINGFUL_OPERATING_INCOME_GROWTH` | 영업이익성장률을 퍼센트로 표시하면 왜곡됨 | `ratios/calculators.py` |
| `EVIDENCE_UNBOUND_EXCLUDED` | DART binding이 부족한 evidence 제외 | `verify/binding.py` |
| `VERIFY_BALANCE_IDENTITY_FAILED_{year}` | 자산과 부채+자본 항등식 차이가 허용 범위 초과 | `verify/consistency.py` |
| `CONSISTENCY_EPS_MISMATCH` | 계산 EPS와 배당 공시 EPS 차이가 허용 범위 초과 | `verify/consistency.py` |
| `VERIFY_LLM_OUTPUT_REJECTED` | LLM 출력이 guard를 최종 통과하지 못함 | `nodes/verify_node.py` |
| `VERDICT_STABILITY_GUARDED` | verdict 문구와 결정론 라벨의 의미가 충돌 | `nodes/verify_node.py` |
| `LLM_FALLBACK_OPENAI` | Qwen 대신 OpenAI fallback 경로 사용 또는 시도 | `interpret/llm_interpreter.py` |
| `LLM_QWEN_CIRCUIT_OPEN` | Qwen skip window 동안 Qwen 호출 생략 | `interpret/llm_interpreter.py` |
| `LLM_FALLBACK_TEMPLATE` | LLM 대신 규칙 기반 template 문장 사용 | `interpret/llm_interpreter.py`, `nodes/verify_node.py` |

`CONSISTENCY_EPS_SKIPPED_PERIOD_MISMATCH`와 `CONSISTENCY_EPS_MATCH`는 `consistency_notes`의 `code`이며, 현재 `risk_flags`로 추가되지는 않습니다.

## report_html 표현

`emit/html_builder.py`는 이 정책을 시각적으로 분리합니다. 코드 계산 영역은 teal, LLM 서술 영역은 보라색으로 표시하고, `meta.verification_summary`가 결정론적으로 통과했을 때만 `검증됨` 뱃지를 표시합니다.
