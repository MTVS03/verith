"""Canonical company list for the secondary-battery (2차전지) MVP scope.

This module is the **single source of truth** for the ~10 companies in scope.
Companies are queried from DART by *stock code* (not name) so the same company
never wavers at the collection stage. The ``aliases`` here are the seed for the
Step 4 entity-normalization dictionary — the top-priority convention in
CLAUDE.md — so keep them here rather than duplicating a list elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Company:
    """A single in-scope company.

    Attributes:
        canonical: The canonical Korean name used as the graph node identity.
        stock_code: 6-digit KRX ticker; used as the DART query key and as the
            per-company output directory name under ``data/raw/``.
        aliases: Alternative spellings/languages that must resolve to
            ``canonical`` during normalization (never become separate nodes).
    """

    canonical: str
    stock_code: str
    aliases: list[str] = field(default_factory=list)


# Order matters: `--limit N` collects the first N. LG화학 / LG에너지솔루션 lead so a
# `--limit 2` smoke test hits two large, well-formed reports.
COMPANIES: list[Company] = [
    Company("LG화학", "051910", ["LG Chem", "엘지화학"]),
    Company("LG에너지솔루션", "373220", ["LG엔솔", "LG Energy Solution", "엘지에너지솔루션"]),
    Company("삼성SDI", "006400", ["삼성에스디아이", "Samsung SDI"]),
    Company("SK이노베이션", "096770", ["SK innovation", "에스케이이노베이션"]),
    Company("에코프로", "086520", ["Ecopro"]),
    Company("에코프로비엠", "247540", ["에코프로BM", "Ecopro BM"]),
    Company("포스코퓨처엠", "003670", ["포스코케미칼", "POSCO Future M"]),
    Company("엘앤에프", "066970", ["L&F", "엘엔에프"]),
    Company("엔켐", "348370", ["Enchem"]),
    Company("SK아이이테크놀로지", "361610", ["SKIET", "SK IE Technology", "에스케이아이이테크놀로지"]),
]


def by_stock_code(stock_code: str) -> Company | None:
    """Return the in-scope company for a ticker, or None if not tracked."""
    return next((c for c in COMPANIES if c.stock_code == stock_code), None)
