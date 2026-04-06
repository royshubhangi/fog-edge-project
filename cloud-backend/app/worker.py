"""
Queue worker: polls SQS, persists to DB. Run as separate process/container for scalability.
Only writes sensor snapshots (never recommendations). Recommendations are saved only via
POST /api/recommendation when the user clicks "Suggest outfit" on the dashboard.
"""
import asyncio
import sys
from pathlib import Path

# Ensure app is on path when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.queue import dequeue, delete_message
from app.database import insert_sensor_snapshots


async def process_one(payload: dict) -> None:
    """Persist only sensor data from ingest. Do not write to recommendations table."""
    await insert_sensor_snapshots(
        payload.get("readings", {}),
        payload.get("timestamp", ""),
    )


async def run_worker(poll_interval: float = 0.5):
    print("Worker started. Polling SQS queue...")
    while True:
        result = await dequeue(timeout=2.0)
        if result:
            payload, receipt_handle = result
            try:
                await process_one(payload)
                await delete_message(receipt_handle)
                print("Processed one payload")
            except Exception as e:
                print(f"Error processing: {e}")
                # Do not delete message so it can be retried after visibility timeout
        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(run_worker())
