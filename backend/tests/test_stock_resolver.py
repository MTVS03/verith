"""Stock Resolver 서비스 판정 로직 테스트 (DB rollback 격리, AI/KIS/OpenAI 호출 없음)."""

from __future__ import annotations

import pytest_asyncio

from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks
from src.api.services.stock_resolver_service import StockResolverService

_NONEXISTENT = "존재하지않는테스트종목zzz"  # 실존 종목 가정에 의존하지 않는 not_found 입력


@pytest_asyncio.fixture
async def resolver(db_session):
    """stocks + aliases 를 트랜잭션 안에서 seed 하고 resolver 를 반환."""
    await seed_stocks(db_session)
    await seed_aliases(db_session)
    await db_session.flush()
    return StockResolverService(db_session)


# 1. stock_code exact
async def test_code_exact(resolver):
    r = await resolver.resolve("051910 차트 보여줘")
    assert r.status == "resolved" and r.reason == "exact_match"
    assert r.stock.stock_code == "051910"


# 2. official stock name
async def test_official_name(resolver):
    r = await resolver.resolve("LG화학 리포트 보여줘")
    assert r.status == "resolved" and r.stock.stock_code == "051910"


# 3. korean variant alias
async def test_korean_variant(resolver):
    r = await resolver.resolve("엘지화학 분석해줘")
    assert r.status == "resolved" and r.stock.stock_code == "051910"


# 4. english alias
async def test_english_alias(resolver):
    r = await resolver.resolve("LG Chem 어때")
    assert r.status == "resolved" and r.stock.stock_code == "051910"


# 5. abbreviation
async def test_abbreviation(resolver):
    r = await resolver.resolve("SKIET 리포트")
    assert r.status == "resolved" and r.stock.stock_code == "361610"


# 6. ambiguous_group: LG → 2종
async def test_ambiguous_group(resolver):
    r = await resolver.resolve("LG 리포트 보여줘")
    assert r.status == "ambiguous" and r.reason == "ambiguous_alias"
    assert {c.stock_code for c in r.candidates} == {"051910", "373220"}
    assert all(c.match_type == "ambiguous_group" for c in r.candidates)


# 7. nested longest-match: 에코프로비엠 → 247540만
async def test_nested_longest_ecopro(resolver):
    r = await resolver.resolve("에코프로비엠 분석")
    assert r.status == "resolved" and r.stock.stock_code == "247540"


# 8. nested longest-match: LG에너지솔루션 → LG 그룹 제거, 373220
async def test_nested_longest_lges(resolver):
    r = await resolver.resolve("LG에너지솔루션 흐름")
    assert r.status == "resolved" and r.stock.stock_code == "373220"


# 9. conflicting identifier: 051910(LG화학) + 삼성SDI(006400)
async def test_conflicting_identifiers(resolver):
    r = await resolver.resolve("051910 삼성SDI 분석")
    assert r.status == "ambiguous" and r.reason == "conflicting_identifiers"


# 10. multiple stocks: 이름 2종
async def test_multiple_stocks(resolver):
    r = await resolver.resolve("LG화학과 삼성SDI 비교")
    assert r.status == "ambiguous" and r.reason == "multiple_stocks"
    assert {c.stock_code for c in r.candidates} == {"051910", "006400"}


# 11. duplicate match dedup (이름+별칭 동시 → 1회)
async def test_duplicate_dedup(resolver):
    r = await resolver.resolve("LG화학 엘지화학 LG Chem 리포트")
    assert r.status == "resolved" and r.stock.stock_code == "051910"


# 12. deterministic ordering (ambiguous_group → stock_code asc)
async def test_deterministic_ordering(resolver):
    r = await resolver.resolve("LG 소식")
    assert [c.stock_code for c in r.candidates] == ["051910", "373220"]


# 13. not_found
async def test_not_found(resolver):
    r = await resolver.resolve(_NONEXISTENT)
    assert r.status == "not_found" and r.reason == "no_match"
    assert r.stock is None and r.candidates == []


# unknown 6자리 코드는 조용히 무시하지 않는다 (B-4)
async def test_unknown_code_not_silently_ignored(resolver):
    r = await resolver.resolve("999999 LG화학 분석")
    assert r.status == "ambiguous" and r.reason == "unknown_identifier"


# 17. punctuation 정규화가 실제 매칭까지 이어진다
async def test_punctuation_resolves(resolver):
    r = await resolver.resolve("L&F 리포트")
    assert r.status == "resolved" and r.stock.stock_code == "066970"
