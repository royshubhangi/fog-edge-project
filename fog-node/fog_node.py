"""
Fog node: receives sensor data, computes comfort index + fabric + clothing suggestion,
dispatches to cloud backend.
"""
import os
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from comfort_index import compute_comfort_index
from fabric_recommender import recommend_fabric, clothing_suggestion

app = FastAPI(title="Smart Outfit Fog Node", version="1.0")

# Latest readings per sensor type (single value each for aggregation)
latest: Dict[str, Any] = {}
# Cloud backend URL (env or default)
CLOUD_URL = os.environ.get("CLOUD_BACKEND_URL", "http://localhost:8000")


class ReadingItem(BaseModel):
    sensor_type: str
    value: Any
    unit: str
    timestamp: str
    source: str = "mock"


class IngestBody(BaseModel):
    readings: List[ReadingItem]


def _merge_readings(readings: List[ReadingItem]) -> None:
    for r in readings:
        latest[r.sensor_type] = {"value": r.value, "unit": r.unit, "timestamp": r.timestamp}


def _readings_map() -> Dict[str, Any]:
    m = {}
    for k, v in latest.items():
        if isinstance(v, dict) and "value" in v:
            m[k] = v["value"]
    return m


async def _dispatch_to_cloud(payload: dict) -> None:
    url = f"{CLOUD_URL.rstrip('/')}/api/ingest"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


@app.post("/ingest")
async def ingest(body: IngestBody):
    """Receive sensor readings from sensors layer and forward to cloud (no recommendation)."""
    if not body.readings:
        raise HTTPException(status_code=400, detail="readings required")
    _merge_readings(body.readings)
    readings_map = _readings_map()
    if not readings_map:
        return {"status": "ok", "message": "readings stored"}

    payload = {
        "source": "fog_node_1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readings": readings_map,
    }
    try:
        await _dispatch_to_cloud(payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cloud dispatch failed: {e}")
    return {"status": "ok"}


async def _send_recommendation_to_cloud(payload: dict) -> None:
    """POST recommendation payload to cloud (for on-demand save)."""
    url = f"{CLOUD_URL.rstrip('/')}/api/recommendation"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


@app.get("/recommend")
async def recommend():
    """Compute outfit recommendation from latest sensor data (on-demand). Does not run on ingest."""
    readings_map = _readings_map()
    if not readings_map:
        raise HTTPException(status_code=400, detail="No sensor data yet. Start sensors and wait for data.")
    comfort = compute_comfort_index(readings_map)
    fabric = recommend_fabric(readings_map)
    suggestion = clothing_suggestion(readings_map)
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": "fog_node_1",
        "timestamp": ts,
        "readings": readings_map,
        "comfort_index": comfort,
        "recommended_fabric": fabric,
        "clothing_suggestions": suggestion,
    }
    try:
        await _send_recommendation_to_cloud(payload)
    except Exception:
        pass  # still return result even if save fails
    return {"comfort_index": comfort, "recommended_fabric": fabric, "clothing_suggestions": suggestion, "ts": ts}


@app.get("/health")
def health():
    return {"status": "ok", "service": "fog-node"}
