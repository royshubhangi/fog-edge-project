"""Outdoor temperature sensor (mock with configurable range)."""
import random
from sensor_base import BaseSensor, SensorReading, utc_iso_now


class TemperatureSensor(BaseSensor):
    def __init__(self, read_interval_sec: float, dispatch_interval_sec: float,
                 dispatch_batch_size: int, low: float = -5, high: float = 45):
        super().__init__(
            "temperature",
            read_interval_sec,
            dispatch_interval_sec,
            dispatch_batch_size,
            "celsius",
        )
        self.low = low
        self.high = high

    def read(self) -> SensorReading:
        value = round(random.uniform(self.low, self.high), 1)
        return SensorReading(
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=utc_iso_now(),
            source="mock",
        )
