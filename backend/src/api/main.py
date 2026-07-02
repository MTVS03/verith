from fastapi import FastAPI

app = FastAPI(title="verith-backend")


@app.get("/health")
def health():
    return {"status": "ok", "service": "backend"}
