from __future__ import annotations

REPORT_SHORT_LABELS = {
    "11011": "FY",
    "11013": "1Q",
    "11012": "1H",
    "11014": "3Q",
}


def period_suffix(reprt_code: str | None) -> str:
    return REPORT_SHORT_LABELS.get(reprt_code or "11011", "FY")


def is_interim_report(reprt_code: str | None) -> bool:
    return (reprt_code or "11011") != "11011"


def period_label(year: str | int, reprt_code: str | None) -> str:
    suffix = period_suffix(reprt_code)
    return str(year) if suffix == "FY" else f"{year} {suffix}"


def period_labels(years: list[str], reprt_code: str | None) -> list[str]:
    return [period_label(year, reprt_code) for year in years]


def period_basis(bsns_year: int | str, reprt_code: str | None, reprt_name: str | None) -> dict[str, str | bool]:
    name = reprt_name or "사업보고서"
    label = period_label(bsns_year, reprt_code)
    interim = is_interim_report(reprt_code)
    return {
        "label": label,
        "report_name": name,
        "reprt_code": reprt_code or "11011",
        "is_interim": interim,
        "description": f"{label} {name} 기준",
        "llm_instruction": (
            f"이 분석은 {label} {name} 기준입니다. "
            "분기/반기 보고서이면 연간 실적처럼 표현하지 말고 해당 기간 기준 수치라고 명시하십시오."
        ),
    }
