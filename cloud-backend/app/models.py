"""Data models for ingest payload and storage."""
from typing import Any, Dict, List
from pydantic import BaseModel


class IngestPayload(BaseModel):
    """Payload from fog on each sensor ingest (no recommendation)."""
    source: str
    timestamp: str
    readings: Dict[str, Any]


class RecommendationPayload(BaseModel):
    """Payload when saving an on-demand recommendation from fog."""
    source: str
    timestamp: str
    readings: Dict[str, Any]
    comfort_index: float
    recommended_fabric: str
    clothing_suggestions: List[str]
