"""
SQS queue for scalable ingest: API pushes to queue, worker(s) process.
Enables FaaS-style workers and autoscaling.
"""
import os
import json
import asyncio
from typing import Optional, Tuple

SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
# Default visibility timeout (seconds) for long polling
SQS_WAIT_TIME = 20

_sqs_client = None


def _get_sqs_client():
    global _sqs_client
    if _sqs_client is None:
        import boto3
        _sqs_client = boto3.client("sqs")
    return _sqs_client


async def enqueue(payload: dict) -> bool:
    """Push ingest payload to queue. Returns True on success."""
    if not SQS_QUEUE_URL:
        return False
    try:
        client = _get_sqs_client()
        body = json.dumps(payload)
        await asyncio.to_thread(
            client.send_message,
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=body,
        )
        return True
    except Exception:
        return False


async def dequeue(timeout: float = 1.0) -> Optional[Tuple[dict, str]]:
    """Receive one message from queue. Returns (payload, receipt_handle) or None if empty/error."""
    if not SQS_QUEUE_URL:
        return None
    wait = min(int(timeout), 20)  # SQS long poll max 20s
    try:
        client = _get_sqs_client()
        response = await asyncio.to_thread(
            client.receive_message,
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait,
            VisibilityTimeout=30,
        )
        messages = response.get("Messages") or []
        if not messages:
            return None
        msg = messages[0]
        body = msg.get("Body", "{}")
        receipt_handle = msg.get("ReceiptHandle", "")
        payload = json.loads(body)
        return (payload, receipt_handle)
    except Exception:
        return None


async def delete_message(receipt_handle: str) -> bool:
    """Delete a message from the queue after successful processing."""
    if not SQS_QUEUE_URL or not receipt_handle:
        return False
    try:
        client = _get_sqs_client()
        await asyncio.to_thread(
            client.delete_message,
            QueueUrl=SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle,
        )
        return True
    except Exception:
        return False


async def queue_length() -> int:
    """Return approximate number of messages in queue. -1 if unavailable."""
    if not SQS_QUEUE_URL:
        return -1
    try:
        client = _get_sqs_client()
        response = await asyncio.to_thread(
            client.get_queue_attributes,
            QueueUrl=SQS_QUEUE_URL,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        attrs = response.get("Attributes") or {}
        return int(attrs.get("ApproximateNumberOfMessages", 0))
    except Exception:
        return -1
