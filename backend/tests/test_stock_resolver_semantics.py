"""Stock Resolver **의미/경계** 회귀 테스트.

강조점(문서 stock_resolver.md 와 짝):
- not_found 는 200 정상 응답(장애 아님), 비종목 문장도 안전 처리.
- stocks 에 추가한 임의 종목은 Resolver 코드 변경 없이 resolved(데이터 주도).
- Technical 지원 범위(BATTERY_TICKERS)와 무관 — Resolver 는 지원 여부/Agent/intent 를 판단하지 않는다.
- 응답 계약(Pydantic StockResolveResponse)에 agent/intent/query 키가 없다(문자열 검사 아님).
- 네트워크 호출 없음. 원문 query 미노출. 카카오 fixture 는 트랜잭션 격리(롤백).
"""

from __future__ import annotations

import pathlib

from db.models.common.stock import Stock
from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks
from src.api.constants.stocks import SUPPORTED_STOCKS
from src.api.schemas.stock_resolve import StockResolveResponse
from src.api.services.stock_resolver_service import StockResolverService

_URL = "/api/stocks/resolve"
_KAKAO = ("035720", "카카오", "KOSPI")  # bootstrap 10종/BATTERY_TICKERS 밖


async def _seed(session):
    await seed_stocks(session)
    await seed_aliases(session)
    await session.flush()


# ── 응답 계약: agent/intent/query 키 없음 (계약 기반) ─────────────────────────
def test_response_contract_has_no_agent_intent_query():
    fields = set(StockResolveResponse.model_fields)
    assert fields == {"status", "reason", "stock", "candidates"}
    for absent in ("agent", "intent", "query", "supported", "technical"):
        assert absent not in fields


# ── 비종목 문장 → 200 + not_found/no_match (거부 아님) ───────────────────────
async def test_non_stock_sentences_are_not_found_200(client, db_session):
    await _seed(db_session)
    for q in ["로제 관련 뉴스 보여줘", "2차전지 산업 뉴스"]:
        r = await client.post(_URL, json={"query": q})
        assert r.status_code == 200                       # 예외/장애 아님
        body = StockResolveResponse.model_validate(r.json())
        assert body.status == "not_found" and body.reason == "no_match"
        assert body.stock is None and body.candidates == []


# ── stocks 에 추가한 임의 종목은 코드 변경 없이 resolved (데이터 주도) ────────
async def test_arbitrary_stock_resolves_without_code_change(db_session):
    await _seed(db_session)
    code, name, market = _KAKAO
    assert code not in {s["stock_code"] for s in SUPPORTED_STOCKS}  # bootstrap/Technical 밖
    db_session.add(Stock(stock_code=code, stock_name=name, market=market))
    await db_session.flush()

    res = await StockResolverService(db_session).resolve("카카오 수급 분석해줘")
    assert res.status == "resolved" and res.reason == "exact_match"
    assert res.stock is not None
    assert (res.stock.stock_code, res.stock.stock_name, res.stock.market) == _KAKAO
    # 응답에 Agent/지원여부 결과가 없다 — 계약 키만 존재.
    assert set(res.model_dump().keys()) == {"status", "reason", "stock", "candidates"}


# ── 카카오 fixture 격리: 롤백 후 공용 DB 오염 없음 ───────────────────────────
async def test_kakao_fixture_is_isolated(db_session):
    # 앞 테스트의 카카오는 트랜잭션 롤백으로 사라졌어야 한다(이 테스트는 seed 만).
    await _seed(db_session)
    assert await db_session.get(Stock, _KAKAO[0]) is None


# ── Resolver 는 Technical 지원 여부를 판단하지 않는다 ────────────────────────
async def test_resolver_does_not_check_technical_support(db_session):
    await _seed(db_session)
    # BATTERY_TICKERS 밖(카카오)도 stocks 에 있으면 resolved — 지원 게이팅 없음.
    db_session.add(Stock(stock_code=_KAKAO[0], stock_name=_KAKAO[1], market=_KAKAO[2]))
    await db_session.flush()
    res = await StockResolverService(db_session).resolve("카카오 리포트")
    assert res.status == "resolved"  # 지원 범위와 무관하게 종목 context 제공


# ── 네트워크/AI 의존 없음 (구조적) ──────────────────────────────────────────
def test_resolver_layer_has_no_network_or_ai_import():
    import src.api.repositories.stock_repository as repo_mod
    import src.api.services.stock_resolver_service as svc_mod

    for m in (svc_mod, repo_mod):
        src = pathlib.Path(m.__file__).read_text(encoding="utf-8")
        for banned in ("httpx", "requests", "urllib", "ai_client", "AIClient", "openai"):
            assert banned not in src, f"{banned} in {m.__name__}"
