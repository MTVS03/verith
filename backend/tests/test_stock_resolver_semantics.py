"""Stock Resolver **의미/경계** 회귀 테스트.

강조점(문서 stock_resolver.md 와 짝):
- not_found 는 200 정상 응답(장애 아님), 비종목 문장도 안전 처리.
- stocks 에 추가한 임의 종목은 Resolver 코드 변경 없이 resolved(데이터 주도).
- Technical 지원 범위(BATTERY_TICKERS)와 무관 — Resolver 는 지원 여부/Agent/intent 를 판단하지 않는다.
- 응답 계약(Pydantic StockResolveResponse)에 agent/intent/query 키가 없다(문자열 검사 아님).
- 네트워크 호출 없음. 원문 query 미노출. "임의 종목" fixture 는 **synthetic 코드**(실존 종목 아님)로
  트랜잭션 격리(롤백)한다 — 실존 대표 종목(카카오/삼성전자)은 canonical seed 로 승격됐으므로 여기서
  "아직 없는 임의 종목" 예시로 쓰지 않는다(역할 분리).

이 테스트는 **Resolver 자체의 방어 동작**만 검증한다. 실제 Top Supervisor 가 비종목 질의에서
Resolver 를 조건부로 호출/미호출하는지는 **Step 4 의 AI 테스트**에서 검증하며, 여기서는 Supervisor
동작을 가정하거나 흉내 내지 않는다(stock_resolver.md §6).
"""

from __future__ import annotations

import pathlib

from db.models.common.stock import Stock
from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks
from src.api.constants.stocks import REPRESENTATIVE_STOCKS, SUPPORTED_STOCKS
from src.api.schemas.stock_resolve import StockResolveResponse
from src.api.services.stock_resolver_service import StockResolverService

_URL = "/api/stocks/resolve"
# synthetic(실존 아님) 임의 종목 — seed/commit 되지 않아 격리·데이터주도 검증에 안전. 990xxx 대역.
_SYNTHETIC = ("990001", "합성테스트종목", "KOSPI")
_SEEDED_CODES = {s["stock_code"] for s in (*SUPPORTED_STOCKS, *REPRESENTATIVE_STOCKS)}


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
    """방어 테스트: 실제 Supervisor 는 비종목 질의에서 Resolver 를 호출하지 않을 수 있으나,
    실수로/복합 질의로 호출되더라도 비종목 문장을 **장애가 아닌 안전한 not_found** 로 반환한다.
    (Supervisor 의 조건부 호출 자체는 Step 4 AI 테스트 범위 — 여기서 가정하지 않는다.)
    """
    await _seed(db_session)
    for q in ["로제 관련 뉴스 보여줘", "2차전지 산업 뉴스"]:
        r = await client.post(_URL, json={"query": q})
        assert r.status_code == 200                       # 예외/장애 아님
        body = StockResolveResponse.model_validate(r.json())
        assert body.status == "not_found" and body.reason == "no_match"
        assert body.stock is None and body.candidates == []


# ── stocks 에 추가한 임의(synthetic) 종목은 코드 변경 없이 resolved (데이터 주도) ────────
async def test_arbitrary_stock_resolves_without_code_change(db_session):
    await _seed(db_session)
    code, name, market = _SYNTHETIC
    assert code not in _SEEDED_CODES  # seed(battery+representative) 밖의 임의 종목
    db_session.add(Stock(stock_code=code, stock_name=name, market=market))
    await db_session.flush()

    res = await StockResolverService(db_session).resolve(f"{name} 수급 분석해줘")
    assert res.status == "resolved" and res.reason == "exact_match"
    assert res.stock is not None
    assert (res.stock.stock_code, res.stock.stock_name, res.stock.market) == _SYNTHETIC
    # 응답에 Agent/지원여부 결과가 없다 — 계약 키만 존재.
    assert set(res.model_dump().keys()) == {"status", "reason", "stock", "candidates"}


# ── synthetic fixture 격리: 롤백 후 공용 DB 오염 없음 ────────────────────────
async def test_synthetic_fixture_is_isolated(db_session):
    # 앞 테스트의 synthetic 종목은 트랜잭션 롤백으로 사라졌어야 한다(seed 만; 990xxx 는 commit 안 됨).
    await _seed(db_session)
    assert await db_session.get(Stock, _SYNTHETIC[0]) is None


# ── Resolver 는 Technical 지원 여부를 판단하지 않는다 ────────────────────────
async def test_resolver_does_not_check_technical_support(db_session):
    await _seed(db_session)
    # 지원 정책과 무관하게 stocks 에 있으면 resolved — Resolver 는 지원 게이팅을 하지 않는다.
    code, name, market = _SYNTHETIC
    db_session.add(Stock(stock_code=code, stock_name=name, market=market))
    await db_session.flush()
    res = await StockResolverService(db_session).resolve(f"{name} 리포트")
    assert res.status == "resolved"  # 지원 범위와 무관하게 종목 context 제공


# ── 네트워크/AI 의존 없음 (구조적) ──────────────────────────────────────────
def test_resolver_layer_has_no_network_or_ai_import():
    import src.api.repositories.stock_repository as repo_mod
    import src.api.services.stock_resolver_service as svc_mod

    for m in (svc_mod, repo_mod):
        src = pathlib.Path(m.__file__).read_text(encoding="utf-8")
        for banned in ("httpx", "requests", "urllib", "ai_client", "AIClient", "openai"):
            assert banned not in src, f"{banned} in {m.__name__}"
