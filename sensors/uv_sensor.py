"""UV index sensor (mock, 0-11)."""
import random
from sensor_base import BaseSensor, SensorReading, utc_iso_now


class UVIndexSensor(BaseSensor):
    def __init__(self, read_interval_sec: float, dispatch_interval_sec: float,
                 dispatch_batch_size: int, low: int = 0, high: int = 11):
        super().__init__(
            "uv_index",
            read_interval_sec,
            dispatch_interval_sec,
            dispatch_batch_size,
            "index",
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
