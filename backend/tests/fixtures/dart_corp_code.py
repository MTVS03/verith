"""DART corpCode.xml fake fixture 빌더 (실 네트워크 없음).

`corp_xml()` 은 CORPCODE.xml bytes 를, `corp_zip()` 은 그것을 담은 ZIP bytes 를 만든다.
파서/클라이언트/sync 테스트가 공유한다.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile


def corp_xml(rows: list[dict]) -> bytes:
    """rows(dict: corp_code/corp_name/stock_code/modify_date) → CORPCODE.xml bytes.

    키를 생략하면 해당 태그를 비운다(예: 비상장이면 stock_code="")."""
    root = ET.Element("result")
    for r in rows:
        node = ET.SubElement(root, "list")
        for tag in ("corp_code", "corp_name", "stock_code", "modify_date"):
            child = ET.SubElement(node, tag)
            child.text = r.get(tag, "")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def corp_zip(xml_bytes: bytes, name: str = "CORPCODE.xml") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, xml_bytes)
    return buf.getvalue()


# ── 표준 fixture: 상장 2건 + 비상장 1건 + modify_date 형식 이상 1건 ──────────────
ROWS = [
    {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930", "modify_date": "20230101"},
    {"corp_code": "00164742", "corp_name": "카카오", "stock_code": "035720", "modify_date": "20240315"},
    # 비상장(빈 stock_code) → 제외 대상
    {"corp_code": "00999999", "corp_name": "비상장법인", "stock_code": "", "modify_date": "20200101"},
    # 상장이지만 modify_date 형식 이상 → NULL 처리(제외 아님)
    {"corp_code": "00111111", "corp_name": "엘지화학", "stock_code": "051910", "modify_date": "2024-03-15"},
]

CORP_XML = corp_xml(ROWS)
CORP_ZIP = corp_zip(CORP_XML)

# stock_code → (corp_code, corp_name, modify_date|None) 기대 매핑(상장만)
EXPECTED = {
    "005930": ("00126380", "삼성전자", "20230101"),
    "035720": ("00164742", "카카오", "20240315"),
    "051910": ("00111111", "엘지화학", None),   # 형식 이상 → NULL
}
