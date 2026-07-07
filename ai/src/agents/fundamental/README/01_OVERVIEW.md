# 01. 개요

`fundamental` 폴더는 veriθ 멀티에이전트 안에서 재무·펀더멘털 분석을 담당하는 워커입니다. 뉴스·심리 워커, 가격·기술 워커와 병렬 관계에 있으며, 이 워커의 입력과 출력은 백엔드/프론트 연동에서 JSON으로 다뤄집니다.

## 책임 범위

| 단계 | 책임 |
| --- | --- |
| DART 수집 | 종목코드 해석, 재무제표 행 수집, latest/annual 모드 선택, 주식수·배당·주주·감사 인사이트 보강 |
| 결정론 계산 | ROE, 영업이익률, 순이익률, 부채비율, 유동비율, 성장률, EPS, BPS 계산 |
| 점수·라벨 | `ratios/scorer.py`에서 0~100점과 `strong/moderate/weak/insufficient_data` 라벨 산출 |
| LLM 해석 | planner/interpret/critic이 계산된 값과 근거를 바탕으로 한국어 설명을 작성 |
| 검증 | binding, consistency, verdict guard, verdict stability를 확인하고 필요 시 retry/template fallback |
| 출력 | `FundamentalResponse` JSON과 검수용 `report_html` 생성 |

## 핵심 원칙

1. 숫자, 점수, 판정 라벨은 코드만 만든다.
2. LLM은 해석 문장만 작성하며 점수·라벨·지표 값을 바꿀 수 없다.
3. 데이터가 부족하면 추정하지 않고 `insufficient_data` 또는 `risk_flags`로 명시한다.
4. 프론트/백엔드의 주 계약은 `FundamentalResponse` JSON이다.
5. `report_html`은 디버그·검수용 부가 산출물이며, 프론트가 지표·점수·라벨을 HTML에서 파싱하면 안 된다.

## 지원 범위

현재 고정 10개 2차전지 관련 종목은 `core/config.py`의 `CORP_CODE_MAP`, `STOCK_NAME_MAP`에 정의되어 있습니다. 지원하지 않는 종목은 `collect_node`에서 `UNSUPPORTED_TICKER` 플래그와 `insufficient_data` 응답으로 처리됩니다.
