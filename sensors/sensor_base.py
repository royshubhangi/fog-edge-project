"""
Base sensor and dispatcher logic.
Configurable read frequency and dispatch rate (interval + batch size).
"""
import asyncio
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, List

@dataclass
class SensorReading:
    sensor_type: str
    value: Any
    unit: str
    timestamp: str
    source: str = "mock"


def utc_iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class BaseSensor(ABC):
    """Base class for sensors with configurable read and dispatch."""

    def __init__(
        self,
        sensor_type: str,
        read_interval_sec: float,
        dispatch_interval_sec: float,
        dispatch_batch_size: int,
        unit: str,
    ):
        self.sensor_type = sensor_type
        self.read_interval_sec = read_interval_sec
        self.dispatch_interval_sec = dispatch_interval_sec
        self.dispatch_batch_size = dispatch_batch_size
        self.unit = unit
        self._buffer: List[SensorReading] = []
        self._running = False

    @abstractmethod
    def read(self) -> SensorReading:
        """Produce one reading (mock or real)."""
        pass

    async def run_loop(self, on_dispatch: Callable[[List[dict]], Any]):
        """Read at read_interval, dispatch at dispatch_interval with up to dispatch_batch_size."""
        self._running = True
        last_dispatch = time.monotonic()
        while self._running:
            reading = self.read()
            self._buffer.append(reading)
            # Dispatch when interval elapsed or buffer >= batch_size
            now = time.monotonic()
            if (
                len(self._buffer) >= self.dispatch_batch_size
                or (now - last_dispatch) >= self.dispatch_interval_sec
            ):
                to_send = self._buffer[: self.dispatch_batch_size]
                self._buffer = self._buffer[self.dispatch_batch_size :]
                last_dispatch = now
                payload = [
                    {
                        "sensor_type": r.sensor_type,
                        "value": r.value,
                        "unit": r.unit,
                        "timestamp": r.timestamp,
                        "source": r.source,
                    }
                    for r in to_send
                ]
                try:
                    await on_dispatch(payload)
                except Exception as e:
                    print(f"[{self.sensor_type}] dispatch error: {e}")
            await asyncio.sleep(self.read_interval_sec)

    def stop(self):
        self._running = False
