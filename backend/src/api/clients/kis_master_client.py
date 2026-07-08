"""KIS 종목마스터 다운로더 (외부 HTTP).

KOSPI/KOSDAQ 마스터 ZIP 을 받아 압축 해제한 **raw .mst bytes** 를 돌려준다(파싱은 parser 책임).
- timeout 필수, 응답 크기 상한, HTTP 오류 전파, 무제한 재시도 없음(재시도 안 함).
- 테스트는 이 클라이언트를 쓰지 않고 `fetch_mst` 를 fake 로 주입한다(실 네트워크 금지).
- 앱 startup 에서 호출하지 않는다 — 수동 script/운영 job 전용.
"""

from __future__ import annotations

import io
import zipfile

import httpx

from src.api.constants.kis_master import MARKET_KOSDAQ, MARKET_KOSPI

_URL = "https://new.real.download.dws.co.kr/common/master/{name}.mst.zip"
_MST_NAME = {MARKET_KOSPI: "kospi_code", MARKET_KOSDAQ: "kosdaq_code"}
_DEFAULT_TIMEOUT = 15.0
_DEFAULT_MAX_BYTES = 30 * 1024 * 1024  # ZIP 응답 상한(안전장치)


class KisMasterError(RuntimeError):
    """마스터 다운로드/해제 실패."""


class KisMasterClient:
    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def fetch_mst(self, market: str) -> bytes:
        """market 의 raw .mst bytes(cp949). 네트워크 호출 — 수동 실행 전용."""
        if market not in _MST_NAME:
            raise ValueError(f"unknown market: {market!r}")
        url = _URL.format(name=_MST_NAME[market])
        try:
            resp = httpx.get(url, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise KisMasterError(f"마스터 다운로드 실패({market}): {type(exc).__name__}") from exc

        if len(resp.content) > self._max_bytes:
            raise KisMasterError(f"마스터 응답이 상한 초과({market})")
        return self._unzip_single(resp.content, market)

    @staticmethod
    def _unzip_single(zip_bytes: bytes, market: str) -> bytes:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                names = zf.namelist()
                if not names:
                    raise KisMasterError(f"빈 ZIP({market})")
                return zf.read(names[0])
        except zipfile.BadZipFile as exc:
            raise KisMasterError(f"손상된 ZIP({market})") from exc
