import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

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


@app.exception_handler(psycopg.OperationalError)
async def db_unavailable_handler(request: Request, exc: psycopg.OperationalError) -> JSONResponse:
    logger.error("Database unreachable while handling %s: %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable — try again shortly."})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
