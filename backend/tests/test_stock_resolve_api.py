"""POST /api/stocks/resolve API 테스트 (검증/상태/보안). AI/KIS/OpenAI 호출 없음."""

from __future__ import annotations

import pathlib

from scripts.seed_stock_aliases import seed as seed_aliases
from scripts.seed_stocks import seed as seed_stocks

_URL = "/api/stocks/resolve"


async def _seed(db_session):
    await seed_stocks(db_session)
    await seed_aliases(db_session)
    await db_session.flush()


async def test_api_resolved(client, db_session):
    await _seed(db_session)
    r = await client.post(_URL, json={"query": "LG화학 리포트 보여줘"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved" and body["stock"]["stock_code"] == "051910"


async def test_api_ambiguous(client, db_session):
    await _seed(db_session)
    r = await client.post(_URL, json={"query": "LG 리포트"})
    assert r.status_code == 200 and r.json()["status"] == "ambiguous"


async def test_api_not_found(client, db_session):
    await _seed(db_session)
    r = await client.post(_URL, json={"query": "존재하지않는테스트문자열zzz"})
    assert r.status_code == 200 and r.json()["status"] == "not_found"


# 14. empty/whitespace query → 422
async def test_api_blank_query_422(client):
    assert (await client.post(_URL, json={"query": ""})).status_code == 422           # min_length
    assert (await client.post(_URL, json={"query": "   "})).status_code == 422         # 정규화 빈값


# 15. 300자 초과 → 422
async def test_api_too_long_422(client):
    assert (await client.post(_URL, json={"query": "가" * 301})).status_code == 422


# extra field 거부
async def test_api_extra_forbid_422(client):
    assert (await client.post(_URL, json={"query": "LG화학", "x": 1})).status_code == 422


# 22. 원문 query 가 응답에 노출되지 않는다
async def test_api_query_not_echoed(client, db_session):
    await _seed(db_session)
    secret = "비밀질의문구zzz"
    r = await client.post(_URL, json={"query": f"{secret} LG화학"})
    assert r.status_code == 200
    assert secret not in r.text


# 23. resolver 는 AI 코드를 import 하지 않는다(=AI/KIS/OpenAI 호출 없음, 구조적 보장)
def test_resolver_has_no_ai_dependency():
    import src.api.services.stock_resolver_service as m

    src = pathlib.Path(m.__file__).read_text(encoding="utf-8")
    assert "ai_client" not in src and "AIClient" not in src and "openai" not in src.lower()
