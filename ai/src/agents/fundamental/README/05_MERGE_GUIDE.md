# 05. 머지 가이드

## ERD 동결 전제

DB ERD는 동결 상태입니다. 이 브랜치를 머지할 때 백엔드 스키마 변경을 함께 요구하지 않습니다. 저장 연동은 `meta.erd_payload` 미리보기 계약을 기준으로 별도 단계에서 맞춥니다.

## 머지 범위

`git diff --name-only develop...HEAD` 기준 커밋된 변경은 `ai/src/agents/fundamental/`이 대부분이며, 저장소 루트의 `.gitignore`, `ai/pyproject.toml`, `ai/uv.lock`도 포함되어 있습니다. 작업 트리에는 `ai/src/main.py` 수정도 보이므로, 라우팅/등록 관련 변경인지 팀에서 확인한 뒤 함께 머지할지 결정해야 합니다. 이 문서화 작업에서는 `.gitignore`를 수정하지 않았습니다.

## 충돌 예상 지점

| 위치 | 이유 |
| --- | --- |
| `ai/src/main.py` | 앱 라우팅 또는 에이전트 등록 변경과 충돌 가능 |
| `ai/src/agents/fundamental/core/contract.py` | JSON 계약 필드가 프론트/백엔드 기대와 직접 연결 |
| `ai/src/agents/fundamental/nodes/workflow.py` | LangGraph 노드 순서 변경 시 테스트/문서 동시 갱신 필요 |
| `ai/src/agents/fundamental/emit/html_builder.py` | `report_html` 표현 계층이 자주 바뀌며 JS 0줄/escape 규율 유지 필요 |
| `ai/src/agents/fundamental/api_test/out/` | 산출물 디렉터리. 저장소 포함 대상 아님 |

## 머지 전 체크리스트

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -q
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
C:\verith\.venv\Scripts\python.exe -m ruff check src\agents\fundamental
```

배치 데모는 `done: ok=10 fail=0`을 확인하고, `api_test/out/summary.md`와 기업별 HTML을 육안 검수합니다.

## 권장 커밋 분리

공개 전 커밋은 한 번에 몰아넣지 말고, 리뷰어가 변경 목적을 따라갈 수 있게 폴더/논리 단위로 나눕니다. 아래 메시지는 예시이며, 실제 staged 파일 범위와 맞춰 조정합니다.

| 커밋 메시지 예시 | 포함 범위 |
| --- | --- |
| `feat(fundamental-core): 상태·결정·실패 관측 계약 추가` | `core/state.py`, `core/decisions.py`, `core/failures.py`, `core/run_history.py` |
| `feat(fundamental-agent): planner/critic 노드와 LLM 호출 경계 추가` | `nodes/plan_node.py`, `nodes/critic_node.py`, `nodes/workflow.py`, `interpret/planner.py`, `interpret/critic.py`, `interpret/llm_client.py`, `interpret/llm_interpreter.py`, `interpret/prompts.py` |
| `feat(fundamental-evidence): 근거 경로 선택과 검증 흐름 보강` | `evidence/path_selector.py`, `nodes/verify_node.py`, `verify/verdict_guard.py`, 관련 테스트 |
| `feat(fundamental-report): report_html 표현 계층 개선` | `emit/html_builder.py`, `tests/test_html_builder.py` |
| `fix(fundamental-data): latest BPS fallback과 저기저 성장률 처리` | `nodes/collect_node.py`, `ratios/calculators.py`, `ratios/scorer.py`, 관련 테스트 |
| `docs(fundamental): 공식 README 문서 체계 정리` | `README.md`, `README/`, `MERGE_HANDOFF.md`, `FRONTEND_INTEGRATION.md`, `nodes/README.md`, `workflow_graph.md` 삭제 |
| `test(fundamental): agent finalization 회귀 테스트 추가` | `tests/test_agent_finalization.py`와 순수 테스트 보강 |

`api_test/out/`, `data/.runs/`, 개인 REVIEW/AUDIT/HANDOFF 문서는 커밋하지 않습니다. `.gitignore`, `ai/src/main.py`, `ai/pyproject.toml`, `ai/uv.lock`처럼 fundamental 바깥 영향이 있는 파일은 별도 커밋으로 분리하거나 팀 결정 후 포함합니다.

## gitignore 대상 산출물

아래는 로컬 산출물 또는 개인 검토 문서로 저장소 커밋 대상이 아닙니다.

| 경로 | 의미 |
| --- | --- |
| `ai/src/agents/fundamental/api_test/out/` | batch/ask_agent 실행 결과 |
| `ai/src/agents/fundamental/data/.runs/` | 로컬 실행 이력 |
| `ai/src/agents/fundamental/REVIEW_*.md`, `AUDIT_*.md`, `DOCTOR_HANDOFF_*.md`, `AGENT_FINALIZATION_*.md` | 개인 작업·감사·인수인계 문서 |

## 반드시 포함할 신규 모듈

최종 커밋 전에 아래 새 파이썬 모듈이 누락되지 않았는지 확인합니다.

| 파일 | 역할 |
| --- | --- |
| `core/decisions.py` | agent decision 기록 |
| `core/failures.py` | failure payload 기록 |
| `core/run_history.py` | 로컬 run history |
| `evidence/path_selector.py` | evidence path 선택 |
| `interpret/planner.py` | LLM planner structured output |
| `interpret/critic.py` | LLM critic structured output |
| `interpret/llm_client.py` | structured LLM client |
| `nodes/plan_node.py` | planner 노드 |
| `nodes/critic_node.py` | critic 노드 |
| `tests/test_agent_finalization.py` | T18~T25 회귀 테스트 |

## 머지 후 확인

프론트/백엔드는 `FundamentalResponse` JSON을 기준으로 연동합니다. `report_html`은 검수용 부가 산출물이며, 프론트가 HTML에서 점수·라벨·지표 값을 파싱하지 않습니다.
