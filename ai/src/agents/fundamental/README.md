# Fundamental Agent

`ai/src/agents/fundamental`은 veriθ 멀티에이전트 중 재무·펀더멘털 워커입니다. DART 공시를 수집하고, 결정론 코드로 재무 지표·점수·라벨을 산출한 뒤, LLM은 그 결과를 해석 문장으로만 정리합니다. 최종 산출의 주 계약은 `FundamentalResponse` JSON이며, `report_html`은 로컬 검수와 디버그를 위한 부가 산출물입니다. 데이터가 부족하면 추정하지 않고 `insufficient_data` 응답으로 닫습니다.

## 문서 맵

| 문서 | 내용 |
| --- | --- |
| [01_OVERVIEW.md](README/01_OVERVIEW.md) | 폴더의 의미, 책임 범위, 결정론/LLM 경계 |
| [02_ARCHITECTURE_NODES.md](README/02_ARCHITECTURE_NODES.md) | LangGraph 워크플로와 노드별 역할 |
| [03_DATA_CONTRACT.md](README/03_DATA_CONTRACT.md) | `FundamentalResponse`, `erd_payload`, 프론트 JSON 계약 |
| [04_VERIFICATION_POLICY.md](README/04_VERIFICATION_POLICY.md) | 검증 게이트, verdict guard, risk flags |
| [05_MERGE_GUIDE.md](README/05_MERGE_GUIDE.md) | develop 머지 전 확인 사항과 커밋 포함 대상 |
| [06_DEV_GUIDE.md](README/06_DEV_GUIDE.md) | 로컬 실행, 테스트, HTML preview 생성법 |
| [07_SUPERVISOR_CONTRACT.md](README/07_SUPERVISOR_CONTRACT.md) | 공개 입력 계약, Supervisor 연결, insufficient_data 정책, ERD 크로스체크, corp_code 후속 debt |

## 빠른 시작

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -q
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
```

실행 옵션과 preview 생성법은 위 문서 맵의 `06_DEV_GUIDE.md`를 참고하세요.
