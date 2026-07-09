"""Entity-name normalization — the #1 GraphRAG risk (CLAUDE.md rule 1).

The same company under variant names ("삼성SDI" / "삼성에스디아이" / "㈜삼성SDI")
splits into separate nodes and breaks multi-hop paths. This module is the single
normalizer shared by extraction (Step 3) and ingestion (Step 4), so a name maps
to the same node identity everywhere.

Seeds come from :data:`companies.COMPANIES` (canonical + aliases). Out-of-scope
companies (SK온, 에코프로머티리얼즈, Ronbay, …) are *kept* as nodes — they are
essential for the multi-hop / hub benchmark questions — but their variants must
still collapse to one name. :data:`EXTRA_ALIASES` is the hand-grown map for those.

Hand-growing that map does not scale, so :mod:`resolve` has the LLM generate a
second, machine-made map (``data/extracted/llm_aliases.json``) from the distinct
node names. It is loaded here at import and applied *after* the hand-curated
maps (human curation always wins); regenerate it with
``uv run python -m src.agents.industry.resolve``.
"""

from __future__ import annotations

import json
import re

from .companies import COMPANIES
from .config import EXTRACTED_DIR

# Corporate affixes stripped before matching/aliasing (case-insensitive).
_AFFIX_PATTERNS = [
    r"주식회사",
    r"㈜",
    r"\(주\)",
    r"\(유\)",
    r"유한회사",
    r"社",
    # Latin/European legal-form affixes: word-boundaried so "Corp" doesn't eat
    # "Corporation" -> "oration". Kept in sync with resolve._LEGAL_TOKENS so a
    # name like "StarPlus Energy LLC" collapses to the same node as without it,
    # deterministically (not left to LLM batch luck). GmbH/Kft/Zrt matter here:
    # battery makers' Hungarian/German subsidiaries carry them — stripping the
    # legal form still leaves the geography, so subsidiaries stay separate nodes.
    r"\bCo\b\.?,?\s*Ltd\b\.?",
    r"\b(?:Corp|Inc|Ltd|LLC|PLC|GmbH|Kft|Zrt|SARL|SAS|SRL|Pte|Sdn|Bhd"
    r"|Limited|Corporation|Company)\b\.?,?",
    # Deliberately NOT stripped: standalone 2-letter forms (Co, SA, AG, BV, NV).
    # They're too easily a real token mid-name; resolve._LEGAL_TOKENS still drops
    # them at the token-set merge step.
]
_AFFIX_RE = re.compile("|".join(_AFFIX_PATTERNS), flags=re.IGNORECASE)

# DART report footnote markers that ride along on names, e.g. "... 주2)", "(*1)".
_FOOTNOTE_RE = re.compile(r"주\d+\)|\(\*\d+\)")

# Trailing parenthetical notes: footnotes "(주1,2)" and former-name notes
# "(구 SK USA, )" / "(구, 삼성엔지니어링)". Legit parens like "(Nanjing)" survive.
_PAREN_NOTE_RE = re.compile(r"\(\s*(주[\d,\s]*|구[,\s][^)]*)\)?\s*$")

# LLM sometimes leaks the schema type into the name, e.g. "환경 산업 / Industry".
_TYPE_LEAK_RE = re.compile(r"\s*/\s*(Company|Industry|Product|Policy|Person)\s*$", re.IGNORECASE)

# Trailing Korean particles (josa), stripped only for self-reference detection.
_JOSA_RE = re.compile(r"(에서|으로|는|은|이|가|의|를|을|도|와|과|에)$")


def _clean(name: str) -> str:
    """Strip footnote markers and corporate affixes; tidy punctuation/whitespace."""
    name = _TYPE_LEAK_RE.sub("", name)
    name = _FOOTNOTE_RE.sub("", name)
    name = _PAREN_NOTE_RE.sub("", name)
    name = _AFFIX_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.strip(" ,.(")


def _key(name: str) -> str:
    """Lookup key: cleaned, lowercased, spaces removed."""
    return _clean(name).lower().replace(" ", "")


def normalize_lookup_key(name: str) -> str:
    """Public lookup-key normalizer (clean, lowercase, spaces removed)."""
    return _key(name)


# Out-of-scope-but-recurring entities: variant -> canonical. Keys are written
# human-readable and normalized to lookup keys at import. Most duplicates are
# now caught by the machine-generated map (resolve.py); promote a mapping here
# only when the LLM keeps getting it wrong — this map overrides the LLM's.
EXTRA_ALIASES: dict[str, str] = {
    "SK on": "SK온",
    "SK 온": "SK온",
    "에스케이온": "SK온",
    "포스코케미칼": "포스코퓨처엠",
    "POSCO": "포스코퓨처엠",
    "에코프로 BM": "에코프로비엠",
    "SK E&S": "SK이앤에스",
    "Sk이엔에스": "SK이앤에스",
    "에스케이이엔에스": "SK이앤에스",
}

# Product / Policy canonicalization — intentionally small (MVP focuses on Company).
_PRODUCT_ALIASES: dict[str, str] = {
    "양극활물질": "양극재",
    "양극소재": "양극재",
    "cathode": "양극재",
    "음극활물질": "음극재",
    "anode": "음극재",
    "전해액": "전해질",
    "electrolyte": "전해질",
    "separator": "분리막",
}
_POLICY_ALIASES: dict[str, str] = {
    "인플레이션 감축법": "IRA",
    "inflation reduction act": "IRA",
}

# Industry names fragment badly ("양극재 산업" / "이차전지 양극재 소재 산업"). Strip the
# trailing category word, then collapse to a canonical battery-value-chain node by
# keyword (specific component wins over the generic "이차전지").
_INDUSTRY_SUFFIX_RE = re.compile(r"\s*(산업|시장|부문|밸류\s*체인|섹터|업종|분야)$")
_INDUSTRY_KEYWORDS = [
    ("양극", "양극재"),
    ("음극", "음극재"),
    ("분리막", "분리막"),
    ("전해", "전해질"),
    ("이차전지", "이차전지"),
    ("2차전지", "이차전지"),
    ("리튬이온", "이차전지"),
    ("배터리", "이차전지"),
]


def _normalize_industry(cleaned: str) -> str:
    base = _INDUSTRY_SUFFIX_RE.sub("", cleaned).strip()
    for kw, canon in _INDUSTRY_KEYWORDS:
        if kw in base:
            return canon
    return base or cleaned


def _normalize_policy(cleaned: str, key: str) -> str:
    if key in _POLICY_KEYED:
        return _POLICY_KEYED[key]
    if "ira" in cleaned.lower() or "인플레이션" in cleaned:  # "미국 인플레이션감축법" -> IRA
        return "IRA"
    return cleaned


def build_company_alias_map() -> dict[str, str]:
    """variant-key -> canonical, seeded from the in-scope company list."""
    amap: dict[str, str] = {}
    for c in COMPANIES:
        amap[_key(c.canonical)] = c.canonical
        for alias in c.aliases:
            amap[_key(alias)] = c.canonical
    return amap


_COMPANY_ALIAS_MAP = build_company_alias_map()
_EXTRA_KEYED = {_key(k): v for k, v in EXTRA_ALIASES.items()}
_PRODUCT_KEYED = {_key(k): v for k, v in _PRODUCT_ALIASES.items()}
_POLICY_KEYED = {_key(k): v for k, v in _POLICY_ALIASES.items()}

# --- Machine-generated alias map (resolve.py output) --------------------------
# {"Company": {"aliases": {variant: canonical}}, ...}
# Applied after the hand-curated maps above. Alias-only by design: resolve.py
# deliberately does NOT emit junk (the model junk-flags real off-topic companies
# like Tesla/삼성전자), so junk classification lives solely in this file's
# filters below — never in the machine map.

LLM_ALIASES_FILE = EXTRACTED_DIR / "llm_aliases.json"

_LLM_ALIASES: dict[str, dict[str, str]] = {}


def set_llm_aliases(data: dict | None) -> None:
    """Install (or clear, with ``None``) the machine-generated alias map."""
    _LLM_ALIASES.clear()
    for typ, block in (data or {}).items():
        amap: dict[str, str] = {}
        for variant, canonical in block.get("aliases", {}).items():
            if typ == "Company":  # canonical must itself be canonical
                canonical = _COMPANY_ALIAS_MAP.get(_key(canonical), canonical)
            if _key(variant) != _key(canonical):
                amap[_key(variant)] = canonical
        _LLM_ALIASES[typ] = amap


def reload_llm_aliases() -> bool:
    """(Re)load llm_aliases.json if present; True if a map was installed."""
    if LLM_ALIASES_FILE.exists():
        set_llm_aliases(json.loads(LLM_ALIASES_FILE.read_text(encoding="utf-8")))
        return True
    set_llm_aliases(None)
    return False


reload_llm_aliases()


def _llm_resolve(name: str, kind: str) -> str:
    """Apply the machine-generated map to an already dictionary-normalized name."""
    return _LLM_ALIASES.get(kind, {}).get(_key(name), name)

# Aggregate rows and generic placeholders that are not real entities. Dropped
# (normalize_name -> "") so the extractor skips them.
_JUNK_KEYS = {
    _key(x)
    for x in [
        "합계", "소계", "계", "기타", "-",           # CSV subtotal/placeholder rows
        "Cell제조업체", "셀제조업체", "고객사",         # generic customer categories
        "완성차업체", "전방업체", "협력사", "공급사",
        "수용가", "항공사", "미군", "한국군", "해경청",  # generic counterparties
        "Oil Major", "한전 자회사",
        "A 계열", "B 계열", "C 계열",                # anonymized customer labels
    ]
}

# Filer self-references in Korean filings -> resolve to the reporting company.
_SELF_REF_KEYS = {
    _key(x)
    for x in ["당사", "본사", "동사", "당그룹", "당사그룹", "폐사",
              "지배기업", "지배회사", "연결회사", "연결실체"]
}

# Geographies (whole-name match) that must never become Company nodes. The huge
# SK이노베이션 filing lists global subsidiaries alongside their country/region.
_GEO = {
    "미국", "미국내", "한국", "대한민국", "국내", "해외", "중국", "일본", "유럽",
    "북미", "남미", "아시아", "중동", "스페인", "오스트레일리아", "호주", "헝가리",
    "폴란드", "조지아", "조지아주", "캐나다", "인도", "인도네시아", "독일", "프랑스",
    "영국", "이탈리아", "대만", "베트남", "말레이시아", "태국", "브라질", "칠레",
    "아르헨티나", "콩고", "모로코", "싱가포르", "네덜란드", "체코", "러시아", "멕시코",
    "튀르키예", "사우디", "천진", "남경", "난징", "무석", "창저우", "후이저우",
    "켄터키", "애리조나", "오스트리아", "스위스",
}
# Facilities / physical assets (substring match) — not companies.
_FACILITY_RE = re.compile(r"(공장|공항|발전소|사업소|캠퍼스|산업단지|산단|물류센터|터미널|광산|유전|가스전)")
# Generic role/org descriptors ending a name — not a specific company.
_GENERIC_SUFFIX_RE = re.compile(
    r"(고객사|매출처|수요가|제조사|공급사|협력사|업체|본부|담당|사업부문|사업부|부문|개발"
    r"|판매법인|생산법인|현지법인)$"
)
# Financial counterparties (banks/funds) wrongly surfaced from finance sections.
# 펀드/조합/투자신탁 etc. cover the many fund vehicles in holdings.csv — real
# OWNS_STAKE targets, but pure noise for a supply-chain graph.
_FINANCE_RE = re.compile(
    r"(은행|증권|캐피탈|캐피털|보험|파트너스|자산운용|Bank|Morgan|Citibank"
    r"|펀드|조합|투자신탁|사모투자|인베스트먼트|Fund\b)",
    re.IGNORECASE,
)


def _is_junk_company(cleaned: str) -> bool:
    """True if a cleaned name is a geography/facility/org-unit/financier, not a company."""
    if not cleaned:
        return True
    tokens = cleaned.split()
    if tokens and all(t in _GEO for t in tokens):
        return True
    return bool(
        _FACILITY_RE.search(cleaned)
        or _GENERIC_SUFFIX_RE.search(cleaned)
        or _FINANCE_RE.search(cleaned)
    )


def is_self_reference(raw: str) -> bool:
    """True if a name is the filer referring to itself (당사, 지배기업, …)."""
    key = _JOSA_RE.sub("", _clean(raw)).lower().replace(" ", "")
    return key in _SELF_REF_KEYS


def normalize_name(raw: str, kind: str = "Company") -> str:
    """Return the canonical node identity for a raw extracted name.

    Company: strip affixes -> in-scope alias map -> EXTRA_ALIASES -> cleaned name.
    Product/Policy: small canonical dicts. Others: cleaned name. Junk -> "".
    """
    if not raw or not raw.strip():
        return ""
    cleaned = _clean(raw)
    key = _key(raw)
    if not cleaned or key in _JUNK_KEYS:
        return ""
    if kind == "Company":
        canonical = _COMPANY_ALIAS_MAP.get(key) or _EXTRA_KEYED.get(key)
        if canonical:
            return canonical
        if _is_junk_company(cleaned):
            return ""
        return _llm_resolve(cleaned, kind)
    if kind == "Industry":
        return _llm_resolve(_normalize_industry(cleaned), kind)
    if kind == "Product":
        return _llm_resolve(_PRODUCT_KEYED.get(key, cleaned), kind)
    if kind == "Policy":
        return _llm_resolve(_normalize_policy(cleaned, key), kind)
    return cleaned

