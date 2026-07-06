from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountSpec:
    canonical: str
    account_ids: tuple[str, ...]
    name_tokens: tuple[str, ...]


ACCOUNT_SPECS = (
    AccountSpec("assets", ("ifrs-full_Assets",), ("자산총계",)),
    AccountSpec("equity_and_liabilities", ("ifrs-full_EquityAndLiabilities",), ("자본과부채총계",)),
    AccountSpec(
        "revenue",
        (
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
            "dart_OperatingRevenue",
        ),
        ("매출액", "영업수익"),
    ),
    AccountSpec("operating_income", ("dart_OperatingIncomeLoss",), ("영업이익",)),
    AccountSpec("profit_loss", ("ifrs-full_ProfitLoss",), ("당기순이익", "분기순이익")),
    AccountSpec("equity", ("ifrs-full_Equity",), ("자본총계",)),
    AccountSpec("liabilities", ("ifrs-full_Liabilities",), ("부채총계",)),
    AccountSpec("current_assets", ("ifrs-full_CurrentAssets",), ("유동자산",)),
    AccountSpec("current_liabilities", ("ifrs-full_CurrentLiabilities",), ("유동부채",)),
    AccountSpec("basic_eps", ("ifrs-full_BasicEarningsLossPerShare",), ("기본주당이익", "기본주당순이익")),
)


def canonical_metric(row: dict[str, Any]) -> str | None:
    account_id = (row.get("account_id") or "").strip()
    account_nm = (row.get("account_nm") or "").strip()
    if "Preferred" in account_id and "EarningsLossPerShare" in account_id:
        return None
    for spec in ACCOUNT_SPECS:
        if account_id in spec.account_ids:
            return spec.canonical
    for spec in ACCOUNT_SPECS:
        if spec.canonical == "revenue":
            if account_nm in spec.name_tokens:
                return spec.canonical
            continue
        if any(token in account_nm for token in spec.name_tokens):
            return spec.canonical
    return None


def account_ids_for(metric: str) -> list[str]:
    for spec in ACCOUNT_SPECS:
        if spec.canonical == metric:
            return list(spec.account_ids)
    return []
