# 06. 개발·실행 가이드

## 환경변수

값은 `.env` 또는 환경변수로 주입하며 문서나 코드에 시크릿을 쓰지 않습니다.

| 변수 | 용도 |
| --- | --- |
| `DART_API_KEY` | OpenDART API key |
| `DART_BASE_URL` | DART API base URL |
| `DART_TIMEOUT` | DART HTTP timeout |
| `QWEN_API_KEY` | 팀 관례상 Qwen OpenAI-compatible base URL alias |
| `QWEN_BASE_URL` | Qwen base URL local override |
| `QWEN_MODEL` | Qwen model name |
| `OPENAI_API_KEY` | Qwen 실패 시 OpenAI fallback |
| `OPENAI_MODEL` | OpenAI fallback model |
| `LLM_TIMEOUT` | LLM timeout. planner/critic은 절반 timeout 사용 |

## 테스트

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -q
```

## ask_agent

사용자 질문 형식으로 fundamental 워커를 실행합니다. 결과는 `api_test/out/ask_agent/` 아래 Markdown, user HTML, debug HTML로 저장됩니다.

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --question "포스코퓨처엠 최근 4개년 재무 분석해줘"
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --latest --ticker 003670 --years 4 "포스코퓨처엠 최신 공시 기준 재무 리포트"
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent
```

주요 옵션:

| 옵션 | 의미 |
| --- | --- |
| `--question`, `-q` | 사용자 질문 |
| `--ticker` | 6자리 종목코드 강제 |
| `--years` | 분석 연수, 1~6 |
| `--no-cache` | 로컬 DART cache bypass |
| `--latest` | 최신 DART 보고서 탐색 |
| `--intent` | `fundamental_health`, `profitability`, `stability`, `growth`, `valuation` |

## annual vs latest 실행 기준

기본 실행 모드는 `annual`입니다. 별도 옵션이나 최신 요청 표현이 없으면 연간 사업보고서 기준으로 분석합니다.

| 실행 방식 | 선택 모드 | 예시 |
| --- | --- | --- |
| 기본 실행 | `annual` | `포스코퓨처엠 최근 4개년 재무 분석해줘` |
| `--latest` 옵션 | `latest` | `--latest --ticker 003670 "포스코퓨처엠 재무 리포트"` |
| 질문에 최신 요청 표현 포함 | `latest` | `포스코퓨처엠 최신 공시 기준으로 재무 분석해줘` |

### 연간 재무 보고서 예시

연간 사업보고서 기준으로 안정적인 4개년 추세를 보고 싶을 때 사용합니다.

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --ticker 003670 --years 4 "포스코퓨처엠 최근 4개년 재무 분석해줘"
```

사용자 프롬프트 예시:

```text
포스코퓨처엠 최근 4개년 재무 분석해줘
LG에너지솔루션 연간 사업보고서 기준으로 재무 체력 봐줘
삼성SDI 최근 4개년 수익성과 안정성 중심으로 분석해줘
```

### 최신 보고서 예시

DART에 올라온 최신 1분기/반기/3분기/사업보고서 기준으로 보고 싶을 때 사용합니다.

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.ask_agent --latest --ticker 003670 --years 4 "포스코퓨처엠 최신 공시 기준 재무 리포트"
```

사용자 프롬프트 예시:

```text
포스코퓨처엠 최신 공시 기준으로 재무 리포트 만들어줘
LG에너지솔루션 실시간으로 새로 가져와서 분석해줘
삼성SDI 캐시 없이 다시 가져와서 최신 보고서 기준으로 봐줘
에코프로 fresh 기준으로 재무 상태 확인해줘
```

`api_test/ask_agent.py`는 질문에 아래 표현이 들어오면 latest 모드로 감지합니다.

```text
최신, 실시간, 새로, 다시 가져, 캐시 없이, fresh
```

latest 모드는 "시퀀스 보고서"가 아니라 DART 최신 보고서 탐색입니다. 결과는 1분기보고서, 반기보고서, 3분기보고서, 사업보고서 중 현재 가장 최신으로 확인된 보고서가 될 수 있습니다. 실제 선택 결과는 응답의 `meta.report_mode`, `meta.reprt_code`, `meta.reprt_name`, `meta.period_basis`, `meta.fresh_dart`에서 확인합니다.

## batch_demo

고정 10개 종목 또는 단일 종목을 E2E 실행합니다. 결과는 `api_test/out/`에 저장됩니다.

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo --ticker 003670
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo --years 4 --no-cache
```

산출물:

| 파일 | 내용 |
| --- | --- |
| `{ticker}_{corp_name}.json` | `FundamentalResponse` 전체 dump |
| `{ticker}_{corp_name}_debug.html` | debug audience `report_html` |
| `summary.md` | 10개사 비교표 |

## report_html preview 생성

기존 JSON에서 user HTML만 다시 만들 때:

```bat
cd /d C:\verith\ai
C:\verith\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from src.agents.fundamental.core.contract import Evidence; from src.agents.fundamental.emit.html_builder import build_report_html; p=Path('src/agents/fundamental/api_test/out/003670_포스코퓨처엠.json'); d=json.loads(p.read_text(encoding='utf-8')); e=[Evidence.model_validate(x) for x in d.get('evidence', [])]; html=build_report_html(corp_name=d['corp_name'], ticker=d['ticker'], score=d['score'], label=d['verdict_label'], confidence=d['confidence'], ratios=d.get('ratios') or {}, trend=d.get('trend') or {}, interpretation=d.get('interpretation') or '', evidence=e, risk_flags=d.get('risk_flags') or [], insights=d.get('insights') or {}, score_breakdown=d.get('score_breakdown') or {}, analyst_plan=d.get('analyst_plan') or {}, evidence_graph=d.get('evidence_graph') or {}, meta=d.get('meta') or {}, audience='user'); Path('src/agents/fundamental/api_test/out/_redesign_preview_user.html').write_text(html, encoding='utf-8')"
```

## 코드 컨벤션

- 숫자, 점수, 라벨은 결정론 코드에서만 생성합니다.
- planner/critic structured output에는 숫자 필드를 두지 않습니다.
- LLM 문장에는 raw HTML을 넣지 않고, `report_html` 동적 텍스트는 `escape()`를 유지합니다.
- `report_html`은 JS 0줄, 외부 CDN/웹폰트/라이브러리 0개를 유지합니다.
- 프론트/백엔드 연동은 JSON 계약을 기준으로 합니다.
