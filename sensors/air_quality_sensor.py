"""Air quality (AQI) sensor (mock, 0-500)."""
import random
from sensor_base import BaseSensor, SensorReading, utc_iso_now


class AirQualitySensor(BaseSensor):
    def __init__(self, read_interval_sec: float, dispatch_interval_sec: float,
                 dispatch_batch_size: int, low: int = 0, high: int = 500):
        super().__init__(
            "air_quality",
            read_interval_sec,
            dispatch_interval_sec,
            dispatch_batch_size,
            "aqi",
        )
        self.low = low
        self.high = high

    def read(self) -> SensorReading:
        value = random.randint(self.low, min(self.high, 200))  # often moderate range
        return SensorReading(
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=utc_iso_now(),
            source="mock",
        )
