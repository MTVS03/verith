"""Step 3 review-loop automation — LLM entity resolution (alias-map generation).

Hand-growing ``normalize.EXTRA_ALIASES`` by eyeballing ``nodes.csv`` does not
scale. This module hands that job to the LLM: the distinct *dictionary-
normalized* node names per type go to ``with_structured_output``, which groups
names referring to the same real-world entity (한/영 표기, 접사, 오탈자) and
flags names that are not entities of that type at all. The result is written to
``data/extracted/llm_aliases.json``, which :mod:`normalize` loads and applies
after the hand-curated maps.

Review workflow: run this, then skim the printed mappings (or the JSON). Delete
a wrong merge from the JSON by hand, or — since a re-run regenerates the file
from scratch — promote stubborn cases into ``EXTRA_ALIASES``/junk filters,
which always override the machine map.

Run:
    uv run python -m src.agents.industry.resolve            # generate + rebuild outputs
    uv run python -m src.agents.industry.resolve --dry-run  # inspect groups only
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import normalize
from .companies import COMPANIES
from .config import get_chat_llm
from .extract import (
    Triple,
    extract_ownstake_triples,
    load_raw_cache,
    merge_triples,
    raw_to_triples,
    write_outputs,
)
from .normalize import EXTRA_ALIASES, _key, build_company_alias_map

# Product/Person are too few/minor to justify an LLM pass (MVP scope).
RESOLVE_TYPES = ["Company", "Industry", "Policy"]

KIND_KO = {"Company": "기업", "Industry": "산업", "Policy": "정책"}
KIND_RULES = {
    "Company": (
        "**같은 법인의 표기 차이만** 묶어라: 한/영 표기(삼성에스디아이 = Samsung SDI), "
        "오탈자(Samaung SDI = Samsung SDI), 법인형태 접미사만 다른 경우"
        "(StarPlus Energy = StarPlus Energy LLC).\n"
        "   묶으면 안 되는 것:\n"
        "   - 모회사 ≠ 자회사 ≠ 계열사 ≠ 합작사. 지역·국가명이 덧붙은 이름은 그 지역의 "
        "**별도 법인**이다 (Samsung SDI Hungary ≠ 삼성SDI, LG Chem Poland ≠ LG화학).\n"
        "   - 브랜드가 같아도 다른 회사다 (SK온 ≠ SK아이이테크놀로지 ≠ SK에너지 ≠ SK이노베이션, "
        "에코프로비엠 ≠ 에코프로머티리얼즈 ≠ 에코프로).\n"
        "   junk에는 **특정 기업을 지칭하지 않는 일반 명사·범주만** 담아라"
        "(예: 수용가, 항공사, 고객사, 미군, 한전 자회사, Oil Major). "
        "실존하는 특정 회사는 배터리 산업과 무관해도 junk가 **아니다** "
        "(Tesla, 삼성전자, 현대자동차, 포스코 등은 모두 유지)."
    ),
    "Industry": (
        "상위 산업과 하위 산업은 **다른 노드**다(예: 이차전지 ≠ 양극재 ≠ 전구체). "
        "같은 산업을 가리키는 표기 차이만 묶어라. "
        "junk 예시: 산업이 아닌 회사명·제품명·일반 문구."
    ),
    "Policy": (
        "국가가 다르거나 대상이 다른 정책은 **다른 노드**다(예: 미국 IRA ≠ EU CRMA). "
        "같은 정책·법을 가리키는 표기 차이(약칭/원어명/설명형 표현)만 묶어라. "
        "junk 예시: 특정 정책·법·규제가 아닌 일반 문구(예: '정부 정책', '각국 규제')."
    ),
}

SYSTEM_PROMPT = """\
너는 지식그래프의 엔티티 정규화(entity resolution) 엔진이다.
한국 배터리 산업 지식그래프에서 추출된 {kind_ko} 노드 이름 목록이 주어진다.
같은 실체(entity)를 가리키는 서로 다른 표기들을 그룹으로 묶어라.

[규칙]
1. **확실한 경우에만** 묶어라: 한/영 표기 차이, 접사·공백·오탈자 차이, 널리 쓰이는 약칭.
   조금이라도 다른 실체일 가능성이 있으면 묶지 마라.
2. {kind_rules}
3. canonical(대표명)은 그룹에서 가장 공식적인 명칭으로 하되, 한국어 명칭을 우선하라.
4. 그룹은 표기가 2개 이상 있을 때만 출력하라.
5. junk는 이름이 {kind_ko} 실체가 **아닐 때만** 쓴다. 그룹에 묶이지 않은 정상적인
   {kind_ko} 이름을 담는 곳이 아니다 — 변형도 없고 junk도 아닌 이름은 아무 데도 넣지 마라.

[출력 형식]
다음 JSON 하나만 출력하라. 설명·주석 금지:
{{"groups": [{{"canonical": "대표명", "variants": ["다른 표기", ...]}}, ...], "junk": ["이름", ...]}}
"""


class AliasGroup(BaseModel):
    """One real-world entity that appears under multiple spellings."""

    canonical: str = Field(description="그룹의 대표명 (가장 공식적인 명칭, 한국어 우선)")
    variants: list[str] = Field(description="canonical과 같은 실체를 가리키는 다른 표기들")


class Resolution(BaseModel):
    """Full entity-resolution result for one node type."""

    groups: list[AliasGroup] = Field(default_factory=list)
    junk: list[str] = Field(default_factory=list, description="해당 타입의 실체가 아닌 이름")


def build_baseline_triples() -> list[Triple]:
    """Rebuild triples with dictionary-only normalization (LLM map cleared)."""
    normalize.set_llm_aliases(None)
    return merge_triples(raw_to_triples(load_raw_cache()) + extract_ownstake_triples())


def collect_names(triples: list[Triple]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = defaultdict(set)
    for t in triples:
        names[t.source_type].add(t.source)
        names[t.target_type].add(t.target)
    return names


def _parse_resolution(content: str) -> Resolution:
    """Parse the model's JSON answer, repairing common LLM glitches.

    This Qwen server intermittently emits malformed JSON — trailing commas, a
    stray doubled ``{``, prose or ``json`` fences around the object. ``strict``
    ``model_validate_json`` chokes on these, so we run the text through
    ``json_repair`` (tolerant parser) first and validate the recovered object.
    """
    from json_repair import loads as repair_loads

    start = content.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {content[:200]!r}")
    return Resolution.model_validate(repair_loads(content[start:]))


# Names per LLM call. The full Company list (~400) makes the answer overrun the
# server's output cap; batches keep each answer comfortably small. Variant pairs
# split across batches are missed — acceptable, they're tail nodes (hub names
# are dictionary-owned).
BATCH_SIZE = 130


def resolve_type(kind: str, names: list[str], llm) -> Resolution:
    # Plain-text JSON, not with_structured_output: function-calling mode made the
    # model loop until max_tokens on exactly this task (the same prompt answers
    # fine as text).
    system = SYSTEM_PROMPT.format(kind_ko=KIND_KO[kind], kind_rules=KIND_RULES[kind])
    if kind == "Company":
        inscope = ", ".join(c.canonical for c in COMPANIES)
        system += f"\n[분석 대상 기업 공식 명칭 — 대표명으로 우선 사용]\n{inscope}\n"

    merged = Resolution()
    batches = [names[i : i + BATCH_SIZE] for i in range(0, len(names), BATCH_SIZE)]
    for bi, batch in enumerate(batches, 1):
        human = (f"{KIND_KO[kind]} 이름 목록 ({len(batch)}개):\n"
                 + "\n".join(f"- {n}" for n in batch))
        reply = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        res = _parse_resolution(reply.content)
        merged.groups += res.groups
        merged.junk += res.junk
        if len(batches) > 1:
            print(f"    batch {bi}/{len(batches)}: {len(res.groups)} groups, {len(res.junk)} junk")
    return merged


# Legal-form tokens that never distinguish two companies.
_LEGAL_TOKENS = {
    "llc", "ltd", "inc", "corp", "co", "company", "corporation", "limited",
    "pte", "plc", "gmbh", "kft", "zrt", "sas", "sarl", "srl", "bhd", "sdn",
    "bv", "nv", "sa", "ag", "주식회사",
}

_TOKEN_RE = re.compile(r"[0-9a-z가-힣&]+")


def _company_merge_ok(variant: str, canonical: str) -> bool:
    """Allow only spelling-level merges (the LLM's judgment stops here).

    The model insists on folding subsidiaries/JVs into parents (Samsung SDI
    Hungary -> 삼성SDI, 에코프로이엠 -> 에코프로) no matter how the prompt forbids
    it, which destroys ownership structure. So a proposed pair is accepted only
    when the *strings* say it's the same name: identical keys, identical token
    sets modulo legal-form suffixes, or near-identical characters (typos).
    """
    kv, kc = _key(variant), _key(canonical)
    if kv == kc:
        return True
    tv = set(_TOKEN_RE.findall(variant.lower())) - _LEGAL_TOKENS
    tc = set(_TOKEN_RE.findall(canonical.lower())) - _LEGAL_TOKENS
    if tv and tv == tc:
        return True
    # Fuzzy (typo) merge only when both keys are long enough for a high ratio to
    # be meaningful. On short keys 0.85 conflates genuinely different companies
    # (e.g. two 4-char names sharing 3 chars clear the bar); those must go
    # through exact-key or token-set equality above, never the fuzzy path.
    if len(kv) < 5 or len(kc) < 5:
        return False
    return SequenceMatcher(None, kv, kc).ratio() >= 0.85


def curated_company_map() -> dict[str, str]:
    """Every human-curated company key -> canonical (in-scope + EXTRA_ALIASES)."""
    cmap = build_company_alias_map()
    for variant, canonical in EXTRA_ALIASES.items():
        cmap[_key(variant)] = canonical
        cmap.setdefault(_key(canonical), canonical)
    return cmap


def validate(
    kind: str, res: Resolution, name_set: set[str], curated: dict[str, str]
) -> dict[str, str]:
    """Filter the LLM's proposal down to safe, applicable mappings.

    Drops hallucinated variants (not in the actual name set), anything touching
    a human-curated company identity (dictionary owns those — the LLM once
    proposed SK온 -> SK아이이테크놀로지, which would destroy a hub node), and
    Company merges that fail the spelling-level guard. ``res.junk`` is ignored
    entirely: the model junk-flags every real-but-off-topic company (Tesla,
    삼성전자) despite instructions; junk lives in normalize.py's filters.
    """
    protected = set(curated.values())
    aliases: dict[str, str] = {}
    for g in res.groups:
        canonical = g.canonical.strip()
        if kind == "Company":
            canonical = curated.get(_key(canonical), canonical)
        for v in (x.strip() for x in g.variants):
            if not v or v == canonical or v not in name_set:
                continue
            if kind == "Company" and (v in protected or _key(v) in curated):
                continue
            if kind == "Company" and not _company_merge_ok(v, canonical):
                continue
            aliases.setdefault(v, canonical)
    return aliases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM entity resolution: generate llm_aliases.json and rebuild Step 3 outputs."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="print proposed mappings; write nothing")
    parser.add_argument("--only", choices=RESOLVE_TYPES,
                        help="resolve a single node type (others kept from the existing file)")
    args = parser.parse_args()

    # Baseline from dictionary-only normalization so the generated file is
    # reproducible from scratch (permanent fixes belong in normalize.py, not here).
    print("Building baseline (dictionary-only) node names from cache ...")
    base = build_baseline_triples()
    names_by_type = collect_names(base)
    curated = curated_company_map()

    # 16384: the Company answer (groups + junk over ~400 names) overflows 8192.
    llm = get_chat_llm(temperature=0, max_tokens=16384)

    # Partial runs (--only / a mid-run failure) keep previous results for the
    # other types instead of silently dropping them.
    out: dict[str, dict] = {}
    if normalize.LLM_ALIASES_FILE.exists():
        out = json.loads(normalize.LLM_ALIASES_FILE.read_text(encoding="utf-8"))

    kinds = [args.only] if args.only else RESOLVE_TYPES
    for kind in kinds:
        names = sorted(names_by_type.get(kind, ()))
        if not names:
            continue
        print(f"\n[{kind}] {len(names)} distinct names -> LLM ...")
        try:
            res = resolve_type(kind, names, llm)
        except Exception:
            import traceback

            traceback.print_exc()
            print(f"  [{kind}] FAILED — keeping previous result if any")
            continue
        proposed = sum(len(g.variants) for g in res.groups)
        aliases = validate(kind, res, set(names), curated)
        print(f"  kept {len(aliases)}/{proposed} proposed variant mappings "
              f"({len(set(aliases.values()))} canonicals)")
        for v, c in sorted(aliases.items(), key=lambda x: (x[1], x[0])):
            print(f"    {v}  ->  {c}")
        out[kind] = {"aliases": aliases}

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    normalize.LLM_ALIASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    normalize.LLM_ALIASES_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {normalize.LLM_ALIASES_FILE}")

    # Rebuild Step 3 outputs with the new map installed.
    normalize.reload_llm_aliases()
    merged = merge_triples(raw_to_triples(load_raw_cache()) + extract_ownstake_triples())
    write_outputs(merged)
    after = collect_names(merged)
    for kind in sorted(names_by_type):
        print(f"  {kind}: {len(names_by_type[kind])} -> {len(after.get(kind, ()))} nodes")


if __name__ == "__main__":
    main()
