"""stock_code(6자리) -> DART corp_code(8자리) 변환 + 원문 무결성 검증."""
import io
import xml.etree.ElementTree as ET
import zipfile

import httpx

from ..config import CORP_CODE_MAP, settings


class UnknownStockCodeError(KeyError):
    """지원 유니버스(10종목) 밖의 종목코드."""


def resolve(stock_code: str) -> str:
    try:
        return CORP_CODE_MAP[stock_code]
    except KeyError:
        raise UnknownStockCodeError(f"unsupported stock_code: {stock_code}") from None


def verify_map_against_dart() -> dict[str, tuple[str, str]]:
    """config 맵을 corpCode.xml 원문과 대조. 반환이 빈 dict면 무결.

    반환: {stock_code: (config값, DART원문값)} — 불일치 항목만.
    """
    resp = httpx.get(
        f"{settings.DART_BASE_URL}/corpCode.xml",
        params={"crtfc_key": settings.DART_API_KEY},
        timeout=30.0,
    )
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    root = ET.fromstring(zf.read("CORPCODE.xml"))

    dart_map: dict[str, str] = {}
    for node in root.iter("list"):
        sc = (node.findtext("stock_code") or "").strip()
        if sc in CORP_CODE_MAP:
            dart_map[sc] = (node.findtext("corp_code") or "").strip()

    return {
        sc: (cc, dart_map.get(sc, "MISSING"))
        for sc, cc in CORP_CODE_MAP.items()
        if dart_map.get(sc) != cc
    }


if __name__ == "__main__":
    diff = verify_map_against_dart()
    print("corp_code 무결성:", "OK (10/10 일치)" if not diff else f"불일치 발견: {diff}")