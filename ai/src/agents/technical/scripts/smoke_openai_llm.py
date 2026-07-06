"""수동 smoke — OpenAI LLM adapter 단독 연결 확인(`services/openai_llm_client.py`).

목적(단위 테스트 아님): 실제 OPENAI_API_KEY로 `default_openai_client().complete(prompt)`가
동작하고 응답 text가 비어 있지 않은지 사람이 확인한다. normalize→focus→interpret 전체 run smoke는
후속 AI endpoint/integration에서 한다 — 이 스크립트는 adapter 단독 smoke만 다룬다.

⚠️ 비용: 실제 OpenAI API를 호출하므로 **토큰 비용이 발생**한다(기본 프롬프트는 최소 토큰).
secret-safe: API key·raw prompt·raw response body를 **출력하지 않는다**(모델/지연/토큰수/길이만).

실행:
  cd ai
  uv run python src/agents/technical/scripts/smoke_openai_llm.py
  uv run python src/agents/technical/scripts/smoke_openai_llm.py --model gpt-5.4-mini
  OPENAI_API_KEY=... uv run python src/agents/technical/scripts/smoke_openai_llm.py

pytest/CI에는 포함하지 않는다(real OpenAI env 필요·비용 발생). OPENAI_API_KEY가 없으면 친절히 종료한다.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 스탠드얼론 스크립트라 ai/ 를 sys.path에 올려 `src...` import가 되게 한다.
# 이 파일 위치: ai/src/agents/technical/scripts/ → parents[4] = ai/
_AI_ROOT = Path(__file__).resolve().parents[4]
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from src.agents.technical.config import OPENAI_API_KEY_ENV, OPENAI_MODEL  # noqa: E402
from src.agents.technical.nodes._llm_utils import LlmCallError  # noqa: E402
from src.agents.technical.services.openai_llm_client import default_openai_client  # noqa: E402

# 최소 토큰 기본 프롬프트(비용 최소화). 응답 내용 자체는 검증 목적이 아니라 "비어 있지 않음"만 본다.
_DEFAULT_PROMPT = "연결 확인용입니다. '연결 확인 완료'라고만 한 줄로 답하세요."


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI LLM adapter 단독 smoke")
    parser.add_argument("--model", default=None, help=f"모델 override(기본: {OPENAI_MODEL})")
    parser.add_argument("--prompt", default=_DEFAULT_PROMPT, help="테스트 프롬프트(내용은 출력하지 않음)")
    args = parser.parse_args()

    if not (os.getenv(OPENAI_API_KEY_ENV) or "").strip():
        print(f"[smoke] {OPENAI_API_KEY_ENV} 가 없습니다. ai/.env 에 설정한 뒤 다시 실행하세요.")
        print(f"        예: {OPENAI_API_KEY_ENV}=sk-... uv run python {Path(__file__).name}")
        return 0  # 키 없음은 실패가 아니라 skip

    print("⚠️  실제 OpenAI API를 호출합니다(토큰 비용 발생).")
    try:
        client = default_openai_client(model=args.model)
    except RuntimeError as exc:  # config error(키 누락 등) — 메시지엔 secret 없음
        print(f"[smoke] client 생성 실패(config): {exc}")
        return 1

    started = time.perf_counter()
    try:
        text = client.complete(args.prompt)
    except LlmCallError as exc:  # 호출 실패 — secret-free 메시지
        print(f"[smoke] LLM 호출 실패: {exc}")
        return 1
    duration_ms = int((time.perf_counter() - started) * 1000)

    # raw response는 출력하지 않는다 — 성공 여부·길이·토큰·지연만.
    ok = bool(text and text.strip())
    print(f"[smoke] success={ok} model={client.model} duration_ms={duration_ms}")
    print(f"[smoke] response_chars={len(text)} usage={client.last_usage}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
