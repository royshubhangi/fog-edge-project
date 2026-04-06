"""
Recommend fabric type and immediate clothing suggestion from sensor readings.
"""
from typing import Dict, Any, List


def _temp_category(t_c: float) -> str:
    if t_c < 5:
        return "freezing"
    if t_c < 15:
        return "cold"
    if t_c < 22:
        return "mild"
    if t_c < 30:
        return "warm"
    return "hot"


def _humidity_category(pct: int) -> str:
    if pct < 40:
        return "dry"
    if pct < 70:
        return "moderate"
    return "humid"


def _uv_category(idx: int) -> str:
    if idx <= 2:
        return "low"
    if idx <= 5:
        return "moderate"
    if idx <= 8:
        return "high"
    return "extreme"


def recommend_fabric(readings_map: Dict[str, Any]) -> str:
    """
    Returns recommended fabric type: cotton, wool, linen, synthetic, breathable_blend, etc.
    """
    t_c = float(readings_map.get("temperature", 20))
    humidity = int(readings_map.get("humidity", 50))
    uv = int(readings_map.get("uv_index", 3))
    activity = str(readings_map.get("activity", "light")).lower()

    temp_cat = _temp_category(t_c)
    hum_cat = _humidity_category(humidity)
    uv_cat = _uv_category(uv)

    if temp_cat == "freezing":
        return "wool"
    if temp_cat == "cold":
        if hum_cat == "humid":
            return "merino_wool"
        return "wool"
    if temp_cat == "mild":
        if activity in ("active", "intense"):
            return "breathable_blend"
        if hum_cat == "humid":
            return "linen"
        return "cotton"
    if temp_cat == "warm":
        if uv_cat in ("high", "extreme"):
            return "light_cotton_spf"
        if activity in ("active", "intense"):
            return "moisture_wicking"
        return "linen"
    # hot
    if activity in ("active", "intense"):
        return "moisture_wicking"
    if uv_cat in ("high", "extreme"):
        return "light_cotton_spf"
    return "linen"


def clothing_suggestion(readings_map: Dict[str, Any]) -> List[str]:
    """
    Returns a short list of immediate clothing suggestions (e.g. "Light jacket", "Sunscreen").
    """
    t_c = float(readings_map.get("temperature", 20))
    humidity = int(readings_map.get("humidity", 50))
    uv = int(readings_map.get("uv_index", 3))
    aqi = int(readings_map.get("air_quality", 50))
    activity = str(readings_map.get("activity", "light")).lower()

    suggestions = []

    if t_c < 10:
        suggestions.append("Warm coat or heavy jacket")
    elif t_c < 18:
        suggestions.append("Light jacket or sweater")
    elif t_c > 28:
        suggestions.append("Light, loose clothing")

    if humidity > 70:
        suggestions.append("Breathable fabrics to avoid stickiness")

    if uv >= 6:
        suggestions.append("Sunscreen and hat recommended")
    elif uv >= 3:
        suggestions.append("Consider sunscreen")

    if aqi > 100:
        suggestions.append("Consider a mask if outdoors for long")

    if activity in ("active", "intense"):
        suggestions.append("Moisture-wicking layers")

    if not suggestions:
        suggestions.append("Comfortable everyday wear")
    return suggestions[:5]
