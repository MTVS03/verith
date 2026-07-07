"""normalize_stock_text 단위 테스트 (DB 불필요)."""

from __future__ import annotations

import pytest

from src.api.text_normalize import normalize_stock_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" LG Chem ", "lgchem"),          # 공백 제거 + casefold
        ("LG 에너지 솔루션", "lg에너지솔루션"),
        ("엘지 화학", "엘지화학"),
        ("SK-IET", "skiet"),               # 구두점 제거 (punctuation)
        ("L&F", "lf"),                     # & 제거
        ("삼성SDI", "삼성sdi"),            # casefold
        ("051910", "051910"),             # 숫자 보존
        ("!!! @@@", ""),                  # 허용문자 없음 → 빈 문자열
    ],
)
def test_normalize(raw: str, expected: str):
    assert normalize_stock_text(raw) == expected


def test_nfkc_fullwidth():
    # 전각 문자 NFKC → 반각.
    assert normalize_stock_text("ＬＧ화학") == "lg화학"
