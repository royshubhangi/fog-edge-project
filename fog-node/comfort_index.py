"""
Comfort index: 0-100 from temperature, humidity, UV, air quality, activity.
Higher = more comfortable for outdoor wear.
"""
from typing import Dict, Any


def _norm_temp(t_c: float) -> float:
    """0-1: optimal around 20-24°C."""
    if t_c <= 5:
        return 0.2
    if t_c <= 15:
        return 0.2 + (t_c - 5) / 25
    if t_c <= 24:
        return 0.6 + (t_c - 15) / 22.5
    if t_c <= 30:
        return 0.8 + (30 - t_c) / 30
    return max(0.2, 0.9 - (t_c - 30) / 50)


def _norm_humidity(pct: int) -> float:
    """0-1: best 30-60%."""
    if pct <= 30:
        return 0.5 + pct / 60
    if pct <= 60:
        return 1.0
    if pct <= 80:
        return 1.0 - (pct - 60) / 40
    return max(0.2, 0.5 - (pct - 80) / 100)


def _norm_uv(idx: int) -> float:
    """0-1: lower UV = more comfortable."""
    if idx <= 2:
        return 1.0
    if idx <= 5:
        return 1.0 - (idx - 2) / 6
    if idx <= 8:
        return 0.5 - (idx - 5) / 6
    return max(0.1, 0.2 - (idx - 8) / 15)


def _norm_aqi(aqi: int) -> float:
    """0-1: lower AQI better."""
    if aqi <= 50:
        return 1.0
    if aqi <= 100:
        return 1.0 - (aqi - 50) / 100
    if aqi <= 150:
        return 0.5 - (aqi - 100) / 100
    if aqi <= 200:
        return 0.2
    return max(0.05, 0.2 - (aqi - 200) / 500)


def _activity_factor(level: str) -> float:
    """Multiplier: intense = need lighter clothes -> lower comfort for heavy fabrics."""
    level = (level or "light").lower() if isinstance(level, str) else "light"
    m = {"sedentary": 1.0, "light": 0.95, "moderate": 0.85, "active": 0.75, "intense": 0.6}
    return m.get(level, 0.8)


def compute_comfort_index(readings_map: Dict[str, Any]) -> float:
    """
    readings_map: { "temperature": float, "humidity": int, "uv_index": int, "air_quality": int, "activity": str }
    Returns 0-100.
    """
    t = _norm_temp(float(readings_map.get("temperature", 20)))
    h = _norm_humidity(int(readings_map.get("humidity", 50)))
    u = _norm_uv(int(readings_map.get("uv_index", 3)))
    a = _norm_aqi(int(readings_map.get("air_quality", 50)))
    act = _activity_factor(str(readings_map.get("activity", "light")))
    raw = (t * 0.3 + h * 0.2 + u * 0.25 + a * 0.25) * act
    return round(min(100, max(0, raw * 100)), 1)
