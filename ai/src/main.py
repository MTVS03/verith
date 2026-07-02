from fastapi import FastAPI

app = FastAPI(title="verith-ai")


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai"}
