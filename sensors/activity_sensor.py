"""User activity level sensor (mock: sedentary -> intense)."""
import random
from sensor_base import BaseSensor, SensorReading, utc_iso_now


class ActivitySensor(BaseSensor):
    LEVELS = ["sedentary", "light", "moderate", "active", "intense"]

    def __init__(self, read_interval_sec: float, dispatch_interval_sec: float,
                 dispatch_batch_size: int, levels: list = None):
        super().__init__(
            "activity",
            read_interval_sec,
            dispatch_interval_sec,
            dispatch_batch_size,
            "level",
        )
        self.levels = levels or self.LEVELS

    def read(self) -> SensorReading:
        value = random.choice(self.levels)
        return SensorReading(
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=utc_iso_now(),
            source="mock",
        )
