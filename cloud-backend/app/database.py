"""
DynamoDB store for recommendations and sensor snapshots.
Tables: outfit-recommendations (PK, SK), outfit-sensor-snapshots (sensor_type, ts).
"""
import asyncio
import aioboto3
import logging
import os
import json
import uuid
from typing import List, Dict, Any

from botocore.exceptions import ClientError

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_RECOMMENDATIONS = os.environ.get("DYNAMODB_TABLE_RECOMMENDATIONS", "outfit-recommendations")
TABLE_SENSORS = os.environ.get("DYNAMODB_TABLE_SENSORS", "outfit-sensor-snapshots")
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL")  # e.g. DynamoDB Local
SENSOR_TYPES = [
    s.strip()
    for s in os.environ.get(
        "SENSOR_TYPES",
        "outdoor_temperature,humidity,uv_index,air_quality,activity_level",
    ).split(",")
    if s.strip()
]

_dynamo_resource = None


async def _get_dynamo():
    global _dynamo_resource
    if _dynamo_resource is None:
        session = aioboto3.Session()
        kwargs = {"region_name": AWS_REGION}
        if AWS_ENDPOINT_URL:
            kwargs["endpoint_url"] = AWS_ENDPOINT_URL
        _dynamo_resource = await session.resource("dynamodb", **kwargs).__aenter__()
    return _dynamo_resource


async def init_db():
    """Validate DynamoDB connectivity; tables are created separately in AWS."""
    try:
        dynamo = await _get_dynamo()
        client = dynamo.meta.client
        await client.describe_table(TableName=TABLE_RECOMMENDATIONS)
        await client.describe_table(TableName=TABLE_SENSORS)
    except ClientError as e:
        logging.warning("DynamoDB init check failed (app starting anyway): %s", e)


async def insert_recommendation(payload: Dict[str, Any]) -> int:
    item_id = str(uuid.uuid4())
    id_num = abs(hash(item_id)) % (10 ** 9)
    created_at = payload.get("timestamp") or ""
    sk = f"{created_at}#{item_id}"
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_RECOMMENDATIONS)
    comfort_index = payload.get("comfort_index")
    item = {
        "PK": "RECOMMENDATION",
        "SK": sk,
        "id": id_num,
        "source": payload.get("source", ""),
        "ts": payload.get("timestamp", ""),
        "comfort_index": comfort_index if comfort_index is not None else None,
        "recommended_fabric": payload.get("recommended_fabric", ""),
        "clothing_suggestions": json.dumps(payload.get("clothing_suggestions", [])),
        "readings": json.dumps(payload.get("readings", {})),
        "created_at": created_at,
    }
    item = {k: v for k, v in item.items() if v is not None}
    await table.put_item(Item=item)
    return id_num


async def insert_sensor_snapshots(readings: Dict[str, Any], ts: str):
    if not readings:
        return
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_SENSORS)
    for sensor_type, value in readings.items():
        await table.put_item(
            Item={
                "sensor_type": sensor_type,
                "ts": ts,
                "value": str(value),
                "unit": "",
            }
        )


async def get_recommendation_history(limit: int = 100) -> List[Dict]:
    """Only returns on-demand recommendations (comfort_index IS NOT NULL)."""
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_RECOMMENDATIONS)
    resp = await table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "RECOMMENDATION"},
        ScanIndexForward=False,
        Limit=limit * 2,
    )
    items = resp.get("Items", [])
    # Filter and take up to limit
    out = []
    for r in items:
        if r.get("comfort_index") is None:
            continue
        out.append({
            "id": int(r["id"]) if r.get("id") is not None else 0,
            "source": r.get("source", ""),
            "ts": r.get("ts", ""),
            "comfort_index": r.get("comfort_index"),
            "recommended_fabric": r.get("recommended_fabric", ""),
            "clothing_suggestions": json.loads(r.get("clothing_suggestions") or "[]"),
            "readings": json.loads(r.get("readings") or "{}"),
            "created_at": r.get("created_at", ""),
        })
        if len(out) >= limit:
            break
    return out


async def get_seasonal_fabric_stats() -> Dict[str, Any]:
    """Fabric recommendations by month; implemented via query + aggregate."""
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_RECOMMENDATIONS)
    resp = await table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "RECOMMENDATION"},
        ProjectionExpression="ts, recommended_fabric",
    )
    items = resp.get("Items", [])
    while resp.get("LastEvaluatedKey"):
        resp = await table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": "RECOMMENDATION"},
            ProjectionExpression="ts, recommended_fabric",
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    # Aggregate: (month, fabric) -> count
    counts: Dict[str, Dict[str, int]] = {}
    for r in items:
        ts = r.get("ts") or ""
        fabric = (r.get("recommended_fabric") or "").strip()
        if not ts or not fabric:
            continue
        month = ts[:7] if len(ts) >= 7 else ""
        if not month:
            continue
        if month not in counts:
            counts[month] = {}
        counts[month][fabric] = counts[month].get(fabric, 0) + 1
    by_month: Dict[str, List[Dict]] = {}
    for month, fabric_counts in counts.items():
        by_month[month] = [{"fabric": f, "count": c} for f, c in fabric_counts.items()]
        by_month[month].sort(key=lambda x: -x["count"])
    return by_month


async def get_sensor_series(sensor_type: str, limit: int = 200) -> List[Dict]:
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_SENSORS)
    resp = await table.query(
        KeyConditionExpression="sensor_type = :st",
        ExpressionAttributeValues={":st": sensor_type},
        ScanIndexForward=False,
        Limit=limit,
    )
    items = resp.get("Items", [])
    # Return chronological (oldest first) to match original behaviour
    items.reverse()
    return [{"ts": r.get("ts", ""), "value": r.get("value", ""), "unit": r.get("unit", "")} for r in items]


async def get_latest_by_sensor() -> Dict[str, Any]:
    """Latest value per sensor type via key query (fast path)."""
    dynamo = await _get_dynamo()
    table = await dynamo.Table(TABLE_SENSORS)

    async def _query_latest(sensor_type: str):
        resp = await table.query(
            KeyConditionExpression="sensor_type = :st",
            ExpressionAttributeValues={":st": sensor_type},
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return sensor_type, None
        row = items[0]
        return sensor_type, {
            "value": str(row.get("value") or ""),
            "unit": str(row.get("unit") or ""),
            "ts": str(row.get("ts") or ""),
        }

    results = await asyncio.gather(*[_query_latest(sensor_type) for sensor_type in SENSOR_TYPES])
    return {sensor_type: data for sensor_type, data in results if data is not None}
