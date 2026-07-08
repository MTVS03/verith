"""Stock Resolver boundary-aware 회귀 테스트.

전체 종목 확장 대비: (1) 무공백 결합형·mixed-script·우선주 표기가 안 깨지고, (2) 흔한 단어 종목명이
일반 문장 안에 박혀도 오탐하지 않으며, (3) 동일 이름 다코드는 조건부로 ambiguous 임을 검증한다.
DB rollback 격리, 실 네트워크 없음.
"""

from __future__ import annotations

import pytest_asyncio

from db.models.common.stock import Stock
from db.models.common.stock_alias import StockAlias
from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks
from src.api.services.stock_resolver_service import StockResolverService

# 부트스트랩 밖 + 결합형/우선주 검증용 종목(테스트 DB에만 in-tx 추가).
_EXTRA = [
    ("035720", "카카오", "KOSPI"),
    ("035420", "NAVER", "KOSPI"),
    ("005490", "POSCO홀딩스", "KOSPI"),
    ("005930", "삼성전자", "KOSPI"),
    ("005935", "삼성전자우", "KOSPI"),
    ("005387", "현대차2우B", "KOSPI"),
    ("001680", "대상", "KOSPI"),        # 흔한 단어 종목명(len2 오탐 위험)
    ("006040", "동원산업", "KOSPI"),
    ("049770", "동원F&B", "KOSDAQ"),
]


@pytest_asyncio.fixture
async def resolver(db_session):
    await seed_stocks(db_session)
    await seed_aliases(db_session)
    for code, name, market in _EXTRA:
        db_session.add(Stock(stock_code=code, stock_name=name, market=market))
    await db_session.flush()
    return StockResolverService(db_session)


# ── 무공백 결합형 / mixed-script / 우선주 표기 (깨지면 안 됨) ─────────────────
async def test_concat_context_suffix(resolver):
    assert (await resolver.resolve("카카오주가")).stock.stock_code == "035720"
    assert (await resolver.resolve("NAVER차트")).stock.stock_code == "035420"
    assert (await resolver.resolve("POSCO홀딩스실적")).stock.stock_code == "005490"


async def test_concat_josa_suffix(resolver):
    assert (await resolver.resolve("LG화학은 어때")).stock.stock_code == "051910"


async def test_preferred_stock_exact(resolver):
    # "우"/"2우B"는 승인 접미가 아니므로 우선주 공식명 그대로 매칭(삼성전자로 축약 안 됨).
    assert (await resolver.resolve("삼성전자우 분석")).stock.stock_code == "005935"
    assert (await resolver.resolve("현대차2우B 리포트")).stock.stock_code == "005387"


# ── 흔한 단어 종목명 오탐 방지 (핵심) ────────────────────────────────────────
async def test_short_name_in_word_not_resolved(resolver):
    r = await resolver.resolve("투자 대상을 알려줘")     # "대상"이 "대상을" token, 문맥 없음
    assert r.status == "not_found" and r.reason == "no_match"


async def test_short_name_with_context_resolves(resolver):
    r = await resolver.resolve("대상 주가 알려줘")        # len2 + 문맥 "주가"
    assert r.status == "resolved" and r.stock.stock_code == "001680"


async def test_short_name_without_context_rejected(resolver):
    r = await resolver.resolve("대상은 어때")             # len2 + 조사만, 문맥 없음
    assert r.status == "not_found"


# ── 동일 이름 다코드: 조건부 ambiguous ───────────────────────────────────────
async def test_same_name_not_found_without_alias(resolver, db_session):
    # 공식명은 "동원산업"/"동원F&B" — "동원" alias/group 이 없으면 "동원 뉴스"는 not_found.
    r = await resolver.resolve("동원 뉴스")
    assert r.status == "not_found"


async def test_same_name_ambiguous_with_group_alias(resolver, db_session):
    # "동원" ambiguous_group alias 가 두 코드에 있으면 ambiguous/multiple_stocks.
    for code in ("006040", "049770"):
        db_session.add(
            StockAlias(stock_code=code, alias="동원", normalized_alias="동원", alias_type="ambiguous_group")
        )
    await db_session.flush()
    r = await resolver.resolve("동원 뉴스")
    assert r.status == "ambiguous"
    assert {c.stock_code for c in r.candidates} == {"006040", "049770"}
