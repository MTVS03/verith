"""AI 내부 API 공통 에러 — `api_spec.md §9` error envelope 정본.

응답은 항상 `{"error": {code, message, request_id, trace_id}}` 형태다. **exception str·API key·
raw prompt/response·OpenAI raw error를 절대 노출하지 않는다** — code별 고정 safe message만 쓴다.
`trace_id`는 AI trace가 생성된 경우에만 채우며(생성 전 실패면 null), 여기서는 대부분 null이다
(내부 trace_id는 supervisor가 만들고 예외 경로에서는 회수하지 않는다).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """내부 API 에러 — code·HTTP status·고정 safe message를 담는다(api_spec §9)."""

    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(code)  # 원문 message는 __str__에 담지 않는다(로그 leak 방지 위해 code만)
        self.code = code
        self.status_code = status_code
        self.safe_message = message
        self.request_id = request_id
        self.trace_id = trace_id


# ── code별 팩토리 (고정 safe message, api_spec §9) ─────────────────────────────
def invalid_request(request_id: str | None = None) -> AppError:
    return AppError("INVALID_REQUEST", 400, "Invalid request payload.", request_id=request_id)


def validation_error(request_id: str | None = None) -> AppError:
    return AppError("VALIDATION_ERROR", 422, "Request validation failed.", request_id=request_id)


def out_of_scope_ticker(request_id: str | None = None) -> AppError:
    return AppError("OUT_OF_SCOPE_TICKER", 422, "Ticker is outside the supported scope.",
                    request_id=request_id)


def ai_unavailable(request_id: str | None = None) -> AppError:
    return AppError("AI_UNAVAILABLE", 502, "AI service is temporarily unavailable.",
                    request_id=request_id)


def ai_timeout(request_id: str | None = None) -> AppError:
    return AppError("AI_TIMEOUT", 504, "AI processing timed out.", request_id=request_id)


def internal_error(request_id: str | None = None) -> AppError:
    return AppError("INTERNAL_ERROR", 500, "Internal server error.", request_id=request_id)


def error_response(err: AppError) -> JSONResponse:
    """AppError → api_spec §9 envelope JSONResponse."""
    return JSONResponse(
        status_code=err.status_code,
        content={"error": {
            "code": err.code,
            "message": err.safe_message,
            "request_id": err.request_id,
            "trace_id": err.trace_id,
        }},
    )


# ── FastAPI exception handlers ────────────────────────────────────────────────
async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """AppError → §9 envelope. (핸들러 시그니처상 Exception으로 받되 AppError만 등록한다.)"""
    assert isinstance(exc, AppError)
    return error_response(exc)


async def validation_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """RequestValidationError → 400(INVALID_REQUEST, JSON 파싱 실패) 또는 422(VALIDATION_ERROR).

    api_spec §8: JSON 파싱 실패는 400, 필수값 누락/형식 오류는 422로 구분한다.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    if any(e.get("type") == "json_invalid" for e in errors):
        return error_response(invalid_request())
    return error_response(validation_error())
