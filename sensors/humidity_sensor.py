"""Humidity sensor (mock, 0-100%)."""
import random
from sensor_base import BaseSensor, SensorReading, utc_iso_now


class HumiditySensor(BaseSensor):
    def __init__(self, read_interval_sec: float, dispatch_interval_sec: float,
                 dispatch_batch_size: int, low: int = 0, high: int = 100):
        super().__init__(
            "humidity",
            read_interval_sec,
            dispatch_interval_sec,
            dispatch_batch_size,
            "percent",
        )
        self.low = low
        self.high = high

    def read(self) -> SensorReading:
        value = random.randint(self.low, self.high)
        return SensorReading(
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=utc_iso_now(),
            source="mock",
        )
