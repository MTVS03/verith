from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.graph import close_driver, ensure_constraints
from src.api.routes import industry_reports, news, reports, stocks, technical_reports
from src.api.routes import fundamental_reports


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # 시작: Neo4j 노드 정체성 키 유니크 제약 보장(멱등).
    await ensure_constraints()
    yield
    # 종료: Neo4j 드라이버 커넥션 풀 정리.
    await close_driver()


app = FastAPI(title="verith-backend", lifespan=lifespan)

app.include_router(technical_reports.router)
app.include_router(fundamental_reports.router)
app.include_router(industry_reports.router)
app.include_router(reports.router)
app.include_router(news.router)
app.include_router(stocks.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "backend"}
