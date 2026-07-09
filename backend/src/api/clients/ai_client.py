"""AI(technical) 서버 HTTP 클라이언트.

backend 는 AI 코드를 **import 하지 않고** HTTP 로만 호출한다(coding_guidelines §1.2).
`POST {AI_SERVICE_URL}/internal/technical/analyze` 를 호출하고 raw JSON(dict)을 돌려준다.
AI 의 §9 error envelope/타임아웃을 backend 도메인 예외로 매핑한다.

secret 미로깅: 예외 메시지에 요청 payload(원 질의 등)·응답 본문을 싣지 않는다.
"""

from __future__ import annotations

import httpx

_ANALYZE_PATH = "/internal/technical/analyze"
_FUNDAMENTAL_ANALYZE_PATH = "/internal/fundamental/analyze"
_INDUSTRY_ANALYZE_PATH = "/internal/industry/analyze"


class AIClientError(Exception):
    """AI 호출 실패의 베이스."""


class AITimeoutError(AIClientError):
    """AI 응답이 timeout(또는 504)."""


class AIUnavailableError(AIClientError):
    """AI 서버 연결 불가/5xx(502/503) 등 일시적 장애."""


class AIValidationError(AIClientError):
    """요청이 AI 계약 검증에 실패(422). 예: 범위 밖 ticker·형식 오류.

    status_code=422 응답을 그대로 전달하기 위한 예외.
    """


class AIContractError(AIClientError):
    """AI 의 200 응답이 계약을 위반(구조/범위/정합성). upstream 오류 → 502 로 매핑.

    예: 필수 필드 누락, 수치 범위 초과, indicator 중복, 요청↔응답 ticker/request_id 불일치.
    """


class AIClient:
    """technical AI 서버 호출기. 요청마다 짧게 AsyncClient 를 연다."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport  # 테스트에서 MockTransport 주입용

    async def analyze_technical(self, payload: dict) -> dict:
        """`/internal/technical/analyze` 호출 → 응답 JSON(dict) 반환.

        payload 는 TechnicalAgentInput 형태(ticker/query/request_id/as_of).
        """
        url = self._base_url + _ANALYZE_PATH
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AITimeoutError("AI 서버 응답 timeout") from exc
        except httpx.HTTPError as exc:
            # 연결 실패 등 — 메시지에 payload/URL 세부는 싣지 않는다.
            raise AIUnavailableError(f"AI 서버 연결 실패: {type(exc).__name__}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 422:
            raise AIValidationError("AI 요청 검증 실패(422)")
        if resp.status_code == 504:
            raise AITimeoutError("AI 서버 timeout(504)")
        if resp.status_code in (502, 503):
            raise AIUnavailableError(f"AI 서버 사용 불가({resp.status_code})")
        raise AIUnavailableError(f"AI 서버 오류({resp.status_code})")

    async def analyze_fundamental(self, payload: dict) -> dict:
        """`/internal/fundamental/analyze` 호출 → 응답 JSON(dict) 반환.

        payload 는 FundamentalAgentInput 형태(request_id/trace_id/ticker/query).
        """
        url = self._base_url + _FUNDAMENTAL_ANALYZE_PATH
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AITimeoutError("AI 서버 응답 timeout") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"AI 서버 연결 실패: {type(exc).__name__}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 422:
            raise AIValidationError("AI 요청 검증 실패(422)")
        if resp.status_code == 504:
            raise AITimeoutError("AI 서버 timeout(504)")
        if resp.status_code in (502, 503):
            raise AIUnavailableError(f"AI 서버 사용 불가({resp.status_code})")
        raise AIUnavailableError(f"AI 서버 오류({resp.status_code})")

    async def analyze_industry(self, payload: dict) -> dict:
        """`/internal/industry/analyze` 호출 → research-report.v1 JSON(dict) 반환."""
        url = self._base_url + _INDUSTRY_ANALYZE_PATH
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AITimeoutError("AI 서버 응답 timeout") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"AI 서버 연결 실패: {type(exc).__name__}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 422:
            raise AIValidationError("AI 요청 검증 실패(422)")
        if resp.status_code == 504:
            raise AITimeoutError("AI 서버 timeout(504)")
        if resp.status_code in (502, 503):
            raise AIUnavailableError(f"AI 서버 사용 불가({resp.status_code})")
        raise AIUnavailableError(f"AI 서버 오류({resp.status_code})")
