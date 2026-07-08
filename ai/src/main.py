from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from src.api.errors import AppError, app_error_handler, validation_exception_handler
from src.api.fundamental import router as fundamental_router
from src.api.technical import router as technical_router

app = FastAPI(title="verith-ai")

# 내부 Technical Agent endpoint(api_spec §7)와 §9 error envelope 핸들러 등록.
app.include_router(technical_router)
app.include_router(fundamental_router)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai"}
