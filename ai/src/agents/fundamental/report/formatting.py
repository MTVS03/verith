"""Display formatting helpers for fundamental reports."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_number(value: Any, max_decimals: int = 2) -> str:
    number = _as_decimal(value)
    if number is None:
        return "산출 불가" if value is None else str(value)

    if number == number.to_integral_value():
        return f"{int(number):,}"

    quant = Decimal("1").scaleb(-max_decimals)
    rounded = number.quantize(quant, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{max_decimals}f}".rstrip("0").rstrip(".")


def format_krw(value: Any) -> str:
    number = _as_decimal(value)
    if number is None:
        return "산출 불가" if value is None else str(value)

    if abs(number) < Decimal("100000000"):
        return f"{format_number(number)}원"

    sign = "-" if number < 0 else ""
    won = int(abs(number).to_integral_value(rounding=ROUND_HALF_UP))
    parts: list[str] = []
    for unit_value, unit_name in ((10**12, "조"), (10**8, "억"), (10**4, "만")):
        amount, won = divmod(won, unit_value)
        if amount:
            parts.append(f"{amount:,}{unit_name}")
    if won:
        parts.append(f"{won:,}원")
        return sign + " ".join(parts)
    return sign + " ".join(parts) + "원" if parts else "0원"


def format_krw_compact(value: Any) -> str:
    number = _as_decimal(value)
    if number is None:
        return "산출 불가" if value is None else str(value)

    if abs(number) < Decimal("100000000"):
        return f"{format_number(number)}원"

    sign = "-" if number < 0 else ""
    eok = int((abs(number) / Decimal("100000000")).to_integral_value(rounding=ROUND_HALF_UP))
    jo, eok_remainder = divmod(eok, 10000)
    parts: list[str] = []
    if jo:
        parts.append(f"{jo:,}조")
    if eok_remainder:
        parts.append(f"{eok_remainder:,}억원")
    if not parts:
        return "0원"
    return sign + " ".join(parts)


def format_metric_value(value: Any, unit: str = "") -> str:
    if value is None:
        return format_number(None)
    if unit == "원":
        return format_krw(value)
    if unit:
        return f"{format_number(value)}{unit}"
    return format_number(value)


def attach_display_fields(ratios: dict[str, Any], trend: dict[str, Any], evidence: list[Any]) -> None:
    for item in ratios.values():
        if isinstance(item, dict):
            if item.get("display_value") and item.get("value") is None:
                continue
            item["display_value"] = format_metric_value(item.get("value"), item.get("unit", ""))

    trend["display"] = {
        "revenue": [format_krw_compact(value) for value in trend.get("revenue", [])],
        "op_income": [format_krw_compact(value) for value in trend.get("op_income", [])],
        "roe": [f"{format_number(value, 2)}%" if value is not None else "산출 불가" for value in trend.get("roe", [])],
    }

    for item in evidence:
        item.display_value = format_metric_value(item.value, item.unit)
