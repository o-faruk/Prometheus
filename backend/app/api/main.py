from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.logging_config import configure_logging

configure_logging()

app = FastAPI(title="Prometheus Grid API", version="0.1.0")

# Wide open for now — this is a read-only public dashboard API with no auth or write
# endpoints, so CORS risk is low. Worth tightening to the real frontend origin before
# deployment, noted in NOTES.md rather than guessing the deployed URL now.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
