"""KIS 마스터 클라이언트 단위 테스트 (unzip·검증만, 실 네트워크 없음).

fetch_mst 의 네트워크 경로는 수동 smoke 전용이라 여기서 호출하지 않는다. ZIP 해제(순수)와
market 검증만 테스트한다.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.api.clients.kis_master_client import KisMasterClient, KisMasterError
from src.api.constants.kis_master import MARKET_KOSPI


def _zip_of(payload: bytes, name: str = "kospi_code.mst") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def test_unzip_single_returns_member_bytes():
    payload = "005930삼성전자".encode("cp949")
    out = KisMasterClient._unzip_single(_zip_of(payload), MARKET_KOSPI)
    assert out == payload


def test_unzip_bad_zip_raises():
    with pytest.raises(KisMasterError):
        KisMasterClient._unzip_single(b"not-a-zip", MARKET_KOSPI)


def test_fetch_unknown_market_raises():
    with pytest.raises(ValueError):
        KisMasterClient().fetch_mst("NASDAQ")
