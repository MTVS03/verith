"""DART corpCode.xml 파서 (순수 — XML bytes → records, 네트워크 없음).

DART OpenAPI `corpCode.xml` 응답(ZIP 해제 후 `CORPCODE.xml`)의 각 `<list>` 노드에서
`corp_code`·`corp_name`·`stock_code`·`modify_date` 를 읽는다.

이번 계층 대상은 **`stock_code` 가 있는 상장사만**이다. 비상장/기타 법인(빈 `stock_code`)은 제외.
정책:
- 빈 `stock_code` → 제외(non_listed count).
- `modify_date` 는 8자리 숫자(YYYYMMDD)면 원문 보존, 아니면 **NULL + count**(제외 아님, 실패 아님).
- 상장 행에 `corp_code`/`corp_name` 이 비면 이상치 → **fail-fast**.
- 같은 `stock_code` 중복 / 같은 `corp_code` 중복 → 이상치 → **fail-fast**.

AI 패키지 import 없음. 파싱 규칙은 DART 공식 응답 포맷을 근거로 backend 가 독자 구현한다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


class CorpCodeParseError(RuntimeError):
    """corpCode.xml 파싱 이상치(손상 XML·상장행 필드 결측·중복 stock_code/corp_code)."""


@dataclass(frozen=True)
class CorpCodeRecord:
    stock_code: str            # 6자리 상장 종목코드(앞자리 0 보존)
    corp_code: str             # 8자리 DART 법인코드
    corp_name_from_dart: str   # DART 공시명 원문(정본 아님)
    modify_date: str | None    # YYYYMMDD 원문 또는 형식 이상 시 None


@dataclass
class CorpCodeParseResult:
    records: list[CorpCodeRecord]
    non_listed: int = 0            # stock_code 빈 값 → 제외(비상장/기타 법인)
    invalid_modify_date: int = 0   # modify_date 형식 이상 → NULL 처리(제외 아님)


def _text(node: ET.Element, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def _valid_modify_date(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def parse_corp_code(xml_bytes: bytes) -> CorpCodeParseResult:
    """CORPCODE.xml bytes → 상장사 record 목록. 이상치는 fail-fast."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CorpCodeParseError(f"corpCode.xml 파싱 실패: {type(exc).__name__}") from exc

    records: list[CorpCodeRecord] = []
    non_listed = 0
    invalid_modify_date = 0
    seen_stock: set[str] = set()
    seen_corp: set[str] = set()

    for node in root.iter("list"):
        stock_code = _text(node, "stock_code")
        if not stock_code:
            non_listed += 1               # 비상장/기타 법인 — 이번 계층 대상 아님
            continue

        corp_code = _text(node, "corp_code")
        corp_name = _text(node, "corp_name")
        if not corp_code:
            raise CorpCodeParseError(f"상장 행에 corp_code 결측: stock_code={stock_code}")
        if not corp_name:
            raise CorpCodeParseError(f"상장 행에 corp_name 결측: stock_code={stock_code}")

        if stock_code in seen_stock:
            raise CorpCodeParseError(f"중복 stock_code: {stock_code}")
        if corp_code in seen_corp:
            raise CorpCodeParseError(f"중복 corp_code: {corp_code}")
        seen_stock.add(stock_code)
        seen_corp.add(corp_code)

        raw_date = _text(node, "modify_date")
        if raw_date and _valid_modify_date(raw_date):
            modify_date: str | None = raw_date
        else:
            if raw_date:
                invalid_modify_date += 1   # 형식 이상 → NULL(실패 아님)
            modify_date = None

        records.append(
            CorpCodeRecord(
                stock_code=stock_code,
                corp_code=corp_code,
                corp_name_from_dart=corp_name,
                modify_date=modify_date,
            )
        )

    return CorpCodeParseResult(
        records=records,
        non_listed=non_listed,
        invalid_modify_date=invalid_modify_date,
    )
