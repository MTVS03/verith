"""DART corpCode.xml 다운로더 (외부 HTTP).

DART OpenAPI `corpCode.xml` 을 받아 ZIP 을 해제한 **raw CORPCODE.xml bytes** 를 돌려준다
(파싱은 parser 책임). 입력은 `crtfc_key`(= `DART_API_KEY`), 응답은 ZIP(안에 `CORPCODE.xml`).

- timeout 필수, 응답 크기 상한, HTTP 오류 전파, 재시도 안 함.
- `crtfc_key` 는 **secret** — URL/예외 메시지에 노출하지 않는다(존재 여부만 검증).
- 테스트는 이 클라이언트를 쓰지 않고 fixture bytes/fake fetch 로 대체한다(실 네트워크 금지).
- 앱 startup 에서 호출하지 않는다 — 수동 sync script 전용. `DART_API_KEY` 는 startup 필수값 아님.
"""

from __future__ import annotations

import io
import zipfile

import httpx

from src.api.config import settings

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_BYTES = 30 * 1024 * 1024  # ZIP 응답 상한(안전장치)
_MEMBER_NAME = "CORPCODE.xml"


class DartCorpCodeError(RuntimeError):
    """corpCode.xml 다운로드/해제 실패 (secret 은 메시지에 싣지 않는다)."""


class DartCorpCodeClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        # 기본은 settings 에서 읽되, startup 이 아니라 fetch 시점에 존재를 검증한다.
        self._api_key = api_key if api_key is not None else settings.DART_API_KEY
        self._base_url = (base_url or settings.DART_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._max_bytes = max_bytes

    def fetch_corp_code(self) -> bytes:
        """CORPCODE.xml raw bytes. 네트워크 호출 — 수동 실행 전용."""
        if not self._api_key:
            raise DartCorpCodeError(
                "DART_API_KEY 가 설정되지 않았습니다(.env). sync 전용 값이므로 실행 시에만 필요합니다."
            )
        url = f"{self._base_url}/corpCode.xml"
        try:
            resp = httpx.get(url, params={"crtfc_key": self._api_key}, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            # exc 에 크리덴셜이 담긴 URL 이 섞일 수 있으므로 타입명만 노출한다.
            raise DartCorpCodeError(f"corpCode.xml 다운로드 실패: {type(exc).__name__}") from None

        if len(resp.content) > self._max_bytes:
            raise DartCorpCodeError("corpCode.xml 응답이 상한 초과")
        return self._unzip_corpcode(resp.content)

    @staticmethod
    def _unzip_corpcode(zip_bytes: bytes) -> bytes:
        """ZIP 에서 CORPCODE.xml 멤버 추출. DART 오류 응답(비 ZIP)이면 BadZipFile."""
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                names = zf.namelist()
                if not names:
                    raise DartCorpCodeError("빈 ZIP")
                # 표준은 CORPCODE.xml — 대소문자 무관 매칭, 없으면 첫 멤버.
                target = next(
                    (n for n in names if n.lower() == _MEMBER_NAME.lower()), names[0]
                )
                return zf.read(target)
        except zipfile.BadZipFile as exc:
            # 키 오류 등으로 DART 가 ZIP 대신 XML 오류를 반환한 경우도 여기로 온다.
            raise DartCorpCodeError("손상된 ZIP 또는 비 ZIP 응답(키/요청 확인)") from exc
