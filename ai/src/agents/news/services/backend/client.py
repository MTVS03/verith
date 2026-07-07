# services/backend/client.py — 공용 HTTP 계층 (backend :8000)
"""backend 와 통신하는 유일한 저수준 계층. 타임아웃·재시도·상태검사·JSON 파싱을 한 곳에 격리한다.

⚠️ HTTP 경계 규칙(절대규칙 1, TASK 08 §3.2): httpx 등 HTTP 라이브러리는 **오직 이 파일**에서만
   import 한다. save_client / query_client / providers 는 이 BackendClient 만 쓴다. DB 드라이버·
   SQL·Cypher 는 이 에이전트 어디에도 없다 — backend 가 DB 를 소유하고, 여기서는 HTTP 만 한다.

설계:
- 모든 호출은 `_request()` 하나를 지난다(단일 책임, CLAUDE.md §7). 재시도 로직을 save/query/provider
  가 각자 복제하지 않는다. HTTP 클라이언트 교체(requests↔httpx, 동기↔비동기)도 이 파일만 고치면 된다.
- 원시 라이브러리 예외(httpx.HTTPError)는 밖으로 흘리지 않고 **BackendError** 로 변환해 올린다 —
  상위 계층이 httpx 에 결합되지 않게. 그래야 provider 는 BackendError 만 잡아 degrade 할 수 있다.
- 인증 헤더 주입 지점을 미리 마련해 둔다(BACKEND_AUTH_TOKEN). 확정 전에는 비어 있어 내부망 전제로 운용.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config import (
    BACKEND_AUTH_TOKEN,
    BACKEND_BASE_URL,
    BACKEND_MAX_RETRIES,
    BACKEND_RETRY_BACKOFF,
    BACKEND_TIMEOUT,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class BackendError(Exception):
    """backend HTTP 실패를 감싸는 예외.

    원시 라이브러리 예외(연결·타임아웃·상태코드)를 이 타입 하나로 통일해 올린다 — 호출측(provider·
    save/query)이 httpx 에 결합되지 않고 이 예외만 보고 degrade/보고 분기를 한다(TASK 08 §3.2).
    """


class BackendClient:
    """BACKEND_BASE_URL 기준 세션을 들고, `_request()` 하나로 모든 backend 호출을 처리한다."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff: float | None = None,
        auth_token: str | None = None,
    ) -> None:
        """설정(config)에서 접속·타임아웃·재시도를 읽어 세션을 구성한다(인자로 override 가능 — 테스트용)."""
        self._base_url = (base_url or BACKEND_BASE_URL).rstrip("/")
        self._timeout = timeout if timeout is not None else BACKEND_TIMEOUT
        self._max_retries = max_retries if max_retries is not None else BACKEND_MAX_RETRIES
        self._backoff = backoff if backoff is not None else BACKEND_RETRY_BACKOFF
        # None 이면 config 기본값(잠정 내부망: 비어 있음). "" 명시 전달과 config None 을 모두 흡수.
        self._auth_token = auth_token if auth_token is not None else BACKEND_AUTH_TOKEN
        # 커넥션 재사용을 위한 세션(base_url 을 들고 상대 경로로 호출). 실제 네트워크는 _request 에서만.
        self._session = httpx.Client(base_url=self._base_url, timeout=self._timeout)

    def close(self) -> None:
        """세션 종료(장기 실행 프로세스에서 명시적으로 닫을 때)."""
        self._session.close()

    # -- 헤더 --------------------------------------------------------------
    def _build_headers(self) -> dict[str, str]:
        """공통 헤더(User-Agent·Accept) + (설정 시) 인증 토큰. 인증은 잠정 미도입(내부망)."""
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    # -- 단일 경로 ---------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        json: Any | None = None,
        params: dict | None = None,
    ) -> Any:
        """모든 backend 호출의 단일 경로. 타임아웃·재시도(지수 backoff)·상태검사·JSON 파싱을 처리한다.

        - 전송 오류(연결 실패·타임아웃)·5xx 는 재시도(총 시도 = 1 + BACKEND_MAX_RETRIES), 소진 시 BackendError.
        - 4xx 는 재시도해도 소용없으므로 즉시 BackendError(클라이언트 요청 오류).
        - 2xx 는 JSON 파싱해 반환(본문 없으면 None). 파싱 실패도 BackendError.
        - 원시 httpx 예외를 밖으로 흘리지 않는다(호출측이 라이브러리에 결합되지 않게, §3.2).
        """
        headers = self._build_headers()
        total = self._max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(total):
            try:
                resp = self._session.request(
                    method, path, json=json, params=params, headers=headers,
                )
            except httpx.HTTPError as exc:  # 연결 실패·타임아웃 등 전송 오류 → 재시도
                last_exc = exc
                logger.warning(
                    "backend 전송 실패 %s %s (attempt %d/%d): %s",
                    method, path, attempt + 1, total, exc,
                )
                if attempt < self._max_retries:
                    time.sleep(self._backoff * (2 ** attempt))
                    continue
                raise BackendError(f"backend 연결 실패: {method} {path}") from exc

            status = resp.status_code
            if status >= 500:  # 서버 오류 → 재시도
                logger.warning(
                    "backend 5xx(%d) %s %s (attempt %d/%d)",
                    status, method, path, attempt + 1, total,
                )
                if attempt < self._max_retries:
                    time.sleep(self._backoff * (2 ** attempt))
                    continue
                raise BackendError(f"backend 서버 오류 {status}: {method} {path}")
            if status >= 400:  # 클라이언트 오류 → 재시도 무의미, 즉시 실패
                logger.error("backend 4xx(%d) %s %s", status, method, path)
                raise BackendError(f"backend 요청 오류 {status}: {method} {path}")

            return self._parse_json(resp)

        # 도달 불가(방어): 루프가 반드시 return/raise 로 끝난다.
        raise BackendError(f"backend 호출 실패: {method} {path}") from last_exc

    @staticmethod
    def _parse_json(resp: httpx.Response) -> Any:
        """2xx 응답 본문을 JSON 으로 파싱. 본문 없음(204 등)은 None, 파싱 실패는 BackendError."""
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:  # json.JSONDecodeError ⊂ ValueError
            raise BackendError(f"backend 응답 JSON 파싱 실패: {resp.request.method} {resp.request.url}") from exc
