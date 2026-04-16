"""
Cloud backend: scalable web service.
- /api/ingest: receives sensor payload from fog, pushes to SQS queue (or sync write if SQS unavailable).
- Worker processes queue -> DB (sensor snapshots only).
- /api/recommend: proxies to fog for on-demand outfit recommendation.
- Dashboard: sensor data and "Suggest outfit" button.
"""
import logging
import os
import httpx
from contextlib import asynccontextmanager
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.models import IngestPayload, RecommendationPayload
from app.database import (
    init_db,
    insert_recommendation,
    insert_sensor_snapshots,
    get_sensor_series,
    get_latest_by_sensor,
    get_recommendation_history,
)
from app.queue import enqueue, queue_length

FOG_NODE_URL = os.environ.get("FOG_NODE_URL", "http://localhost:8001")

logger = logging.getLogger(__name__)


def _dynamo_client_error(exc: ClientError) -> HTTPException:
    err = exc.response.get("Error", {}) if exc.response else {}
    code = err.get("Code", "ClientError")
    msg = err.get("Message", str(exc))
    logger.warning("DynamoDB error: %s — %s", code, msg)
    return HTTPException(
        status_code=503,
        detail={"service": "dynamodb", "error": code, "message": msg},
    )


def _aws_backend_error(exc: Exception) -> HTTPException:
    """Map boto/network errors to JSON responses (aioboto3 may raise BotoCoreError, not only ClientError)."""
    if isinstance(exc, ClientError):
        return _dynamo_client_error(exc)
    if isinstance(exc, BotoCoreError):
        logger.warning("AWS SDK error: %s", exc)
        return HTTPException(
            status_code=503,
            detail={"service": "aws", "error": type(exc).__name__, "message": str(exc)},
        )
    logger.exception("Unexpected error in API handler")
    return HTTPException(
        status_code=503,
        detail={"service": "backend", "error": type(exc).__name__, "message": str(exc)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    pass


app = FastAPI(title="Smart Outfit Cloud Backend", version="1.0", lifespan=lifespan)


@app.post("/api/ingest")
async def ingest(payload: IngestPayload):
    """Receive sensor payload from fog node. Push to queue for async processing. Only sensor data is stored; no recommendation is written on ingest."""
    payload_dict = payload.model_dump()
    ok = await enqueue(payload_dict)
    if ok:
        return {"status": "queued"}
    # Fallback: process synchronously if SQS unavailable (e.g. dev without SQS_QUEUE_URL)
    try:
        await insert_sensor_snapshots(payload_dict.get("readings", {}), payload_dict.get("timestamp", ""))
    except Exception as e:
        raise _aws_backend_error(e) from e
    return {"status": "processed"}


@app.get("/api/queue/length")
async def get_queue_length():
    n = await queue_length()
    return {"length": n} if n >= 0 else {"error": "queue unavailable"}


@app.get("/api/sensors/latest")
async def sensors_latest():
    """Latest value per sensor type for dashboard."""
    try:
        return await get_latest_by_sensor()
    except Exception as e:
        raise _aws_backend_error(e) from e


@app.get("/api/sensors/{sensor_type}/series")
async def sensor_series(sensor_type: str, limit: int = 200):
    try:
        data = await get_sensor_series(sensor_type, limit=limit)
        return {"sensor_type": sensor_type, "data": data}
    except Exception as e:
        raise _aws_backend_error(e) from e


@app.get("/api/recommend")
async def recommend():
    """Proxy to fog node for on-demand outfit recommendation (uses latest sensor data)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{FOG_NODE_URL.rstrip('/')}/recommend")
            resp.raise_for_status()
            return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Fog node unreachable: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.post("/api/recommendation")
async def save_recommendation(payload: RecommendationPayload):
    """Save an on-demand recommendation from the fog node."""
    payload_dict = payload.model_dump()
    try:
        await insert_recommendation(payload_dict)
    except Exception as e:
        raise _aws_backend_error(e) from e
    return {"status": "saved"}


@app.get("/api/analytics/recommendation-history")
async def recommendation_history(limit: int = 100):
    """History of on-demand recommendations (from Suggest outfit button)."""
    try:
        return await get_recommendation_history(limit=limit)
    except Exception as e:
        raise _aws_backend_error(e) from e


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "cloud-backend"}


# Dashboard: serve static HTML
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index = DASHBOARD_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Cloud Backend</h1><p>Dashboard not found. API: <a href='/docs'>/docs</a></p>")
    return HTMLResponse(index.read_text())
