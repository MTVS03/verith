"""DART corp code 클라이언트 단위 테스트 (unzip·검증만, 실 네트워크 없음).

fetch_corp_code 의 네트워크 경로는 수동 smoke 전용이라 여기서 호출하지 않는다. ZIP 해제(순수)와
key 부재 검증만 테스트한다.
"""

from __future__ import annotations

import pytest

from src.api.clients.dart_corp_code_client import DartCorpCodeClient, DartCorpCodeError
from tests.fixtures.dart_corp_code import CORP_XML, corp_zip


def test_unzip_extracts_corpcode_member():
    out = DartCorpCodeClient._unzip_corpcode(corp_zip(CORP_XML))
    assert out == CORP_XML


def test_unzip_prefers_corpcode_over_other_members():
    # 다른 멤버가 앞에 있어도 CORPCODE.xml 을 골라야 한다(대소문자 무관).
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", b"noise")
        zf.writestr("corpcode.xml", CORP_XML)
    out = DartCorpCodeClient._unzip_corpcode(buf.getvalue())
    assert out == CORP_XML


def test_unzip_bad_zip_raises():
    # 키 오류 등으로 DART 가 ZIP 대신 XML 오류를 반환한 경우도 여기로 온다.
    with pytest.raises(DartCorpCodeError):
        DartCorpCodeClient._unzip_corpcode(b"not-a-zip")


def test_fetch_without_key_raises():
    client = DartCorpCodeClient(api_key="")
    with pytest.raises(DartCorpCodeError):
        client.fetch_corp_code()
