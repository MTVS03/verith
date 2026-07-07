"""Diagnose the configured Qwen OpenAI-compatible endpoint.

Run from the ai directory:
    python -m src.agents.fundamental.api_test.check_qwen

This does not print API keys. In this project QWEN_API_KEY is the Qwen base URL.
"""

from __future__ import annotations

import json

import httpx

from ..core.config import settings
from ..interpret.llm_interpreter import _call_openai_compatible
from ..interpret.prompts import build_interpret_prompt


def _safe_print(text: str) -> None:
    print(text.encode("unicode_escape", errors="replace").decode("ascii")[:2000])


def _url(path: str) -> str:
    return settings.QWEN_BASE_URL.rstrip("/") + path


def main() -> int:
    print(f"base_url={settings.QWEN_BASE_URL}")
    print(f"model={settings.QWEN_MODEL}")

    with httpx.Client(timeout=20.0) as client:
        print("\n[1] GET /models")
        try:
            response = client.get(_url("/models"))
            print(f"status={response.status_code}")
            print(response.text[:1000])
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")

        chat_payload = {
            "model": settings.QWEN_MODEL,
            "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": 'Return {"verdict":"ok","interpretation":"ok"}'},
            ],
        }
        print("\n[2] POST /chat/completions")
        try:
            response = client.post(_url("/chat/completions"), json=chat_payload)
            print(f"status={response.status_code}")
            _safe_print(response.text[:1000])
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")

        completion_payload = {
            "model": settings.QWEN_MODEL,
            "temperature": 0.2,
            "prompt": 'Return JSON only: {"verdict":"ok","interpretation":"ok"}',
        }
        print("\n[3] POST /completions")
        try:
            response = client.post(_url("/completions"), json=completion_payload)
            print(f"status={response.status_code}")
            _safe_print(response.text[:1000])
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("text") or data.get("choices", [{}])[0].get("message", {}).get("content")
                print("\nparsed_choice_content:")
                print(json.dumps(content, ensure_ascii=False)[:1000])
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")

    print("\n[4] REALISTIC interpreter prompt")
    prompt = build_interpret_prompt(
        "LG에너지솔루션",
        45,
        "moderate",
        {
            "roe": {"value": 0.28, "unit": "%", "fiscal_year": "2025"},
            "operating_margin": {"value": 5.69, "unit": "%", "fiscal_year": "2025"},
            "debt_ratio": {"value": 129.0, "unit": "%", "fiscal_year": "2025"},
            "revenue_growth": {"value": -7.6, "unit": "%", "fiscal_year": "2025"},
        },
        {"years": ["2022", "2023", "2024", "2025"], "roe": [3.79, 6.72, 1.09, 0.28]},
        ["MISSING_BPS"],
    )
    try:
        import asyncio

        verdict, interpretation = asyncio.run(
            _call_openai_compatible(
                base_url=settings.QWEN_BASE_URL,
                api_key=settings.LLM_DUMMY_KEY,
                model=settings.QWEN_MODEL,
                prompt=prompt,
                timeout=60.0,
            )
        )
        print("OK")
        print({"verdict": verdict, "interpretation": interpretation})
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")

    print("\n[5] RAW realistic /chat/completions")
    raw_payload = {
        "model": settings.QWEN_MODEL,
        "temperature": 0.2,
        "max_tokens": 1024,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": "Return only JSON with keys verdict and interpretation. No think."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = httpx.post(_url("/chat/completions"), json=raw_payload, timeout=60.0)
        print(f"status={response.status_code}")
        data = response.json()
        choice = data.get("choices", [{}])[0].get("message", {})
        print("content:")
        _safe_print(str(choice.get("content", "")))
        print("reasoning_content:")
        _safe_print(str(choice.get("reasoning_content", "")))
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")

    print("\n[6] SAMPLE payload prompt")
    sample_path = __import__("pathlib").Path(__file__).resolve().parent / "samples" / "fundamental_response_sample.json"
    if sample_path.exists():
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        sample_prompt = build_interpret_prompt(
            sample["corp_name"],
            sample["score"],
            sample["verdict_label"],
            sample["ratios"],
            sample["trend"],
            sample["risk_flags"],
        )
        try:
            import asyncio

            verdict, interpretation = asyncio.run(
                _call_openai_compatible(
                    base_url=settings.QWEN_BASE_URL,
                    api_key=settings.LLM_DUMMY_KEY,
                    model=settings.QWEN_MODEL,
                    prompt=sample_prompt,
                    timeout=60.0,
                )
            )
            print("OK")
            print({"verdict": verdict, "interpretation": interpretation})
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")
    else:
        print("SKIP no sample file")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
