from fastapi import FastAPI

from src.api.routes import reports, technical_reports

app = FastAPI(title="verith-backend")

app.include_router(technical_reports.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "backend"}
