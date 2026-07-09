from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.graph import close_driver, ensure_constraints
from src.api.config import settings
from src.api.routes import news, reports, stocks, technical_reports
from src.api.routes import fundamental_reports


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # 시작: Neo4j 노드 정체성 키 유니크 제약 보장(멱등).
    await ensure_constraints()
    yield
    # 종료: Neo4j 드라이버 커넥션 풀 정리.
    await close_driver()


app = FastAPI(title="verith-backend", lifespan=lifespan)

# 프론트(다른 origin)의 브라우저 직접 호출 허용. 허용 origin 은 settings(CORS_ORIGINS, env override).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],   # GET/POST/DELETE/OPTIONS 등
    allow_headers=["*"],
)

app.include_router(technical_reports.router)
app.include_router(fundamental_reports.router)
app.include_router(reports.router)
app.include_router(news.router)
app.include_router(stocks.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "backend"}
