"""
Run all configured sensors and dispatch readings to the fog node.
Usage: python run_sensors.py [--config config.yaml]
"""
import asyncio
import argparse
import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Allow running from project root or from sensors/
sys_path = Path(__file__).resolve().parent
if str(sys_path) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(sys_path))

from temperature_sensor import TemperatureSensor
from humidity_sensor import HumiditySensor
from uv_sensor import UVIndexSensor
from air_quality_sensor import AirQualitySensor
from activity_sensor import ActivitySensor


def load_config(path: str) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    if not yaml:
        raise RuntimeError("PyYAML required: pip install pyaml")
    with open(path) as f:
        return yaml.safe_load(f)


async def dispatch_to_fog(fog_url: str, timeout: float, payload: list):
    """POST sensor payload to fog node /ingest."""
    import aiohttp
    url = f"{fog_url.rstrip('/')}/ingest"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"readings": payload}, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()


def build_sensors(config: dict):
    sensors = []
    cfg = config.get("sensors", {})
    fog_url = os.environ.get("FOG_URL", config.get("fog", {}).get("url", "http://localhost:8001"))
    timeout = config.get("fog", {}).get("timeout_sec", 5)

    if cfg.get("temperature", {}).get("enabled", True):
        t = cfg["temperature"]
        sensors.append((
            TemperatureSensor(
                t.get("read_interval_sec", 5),
                t.get("dispatch_interval_sec", 10),
                t.get("dispatch_batch_size", 2),
                *t.get("range", [-5, 45]),
            ),
            fog_url,
            timeout,
        ))
    if cfg.get("humidity", {}).get("enabled", True):
        h = cfg["humidity"]
        sensors.append((
            HumiditySensor(
                h.get("read_interval_sec", 5),
                h.get("dispatch_interval_sec", 10),
                h.get("dispatch_batch_size", 2),
                *h.get("range", [0, 100]),
            ),
            fog_url,
            timeout,
        ))
    if cfg.get("uv_index", {}).get("enabled", True):
        u = cfg["uv_index"]
        sensors.append((
            UVIndexSensor(
                u.get("read_interval_sec", 10),
                u.get("dispatch_interval_sec", 15),
                u.get("dispatch_batch_size", 1),
                *u.get("range", [0, 11]),
            ),
            fog_url,
            timeout,
        ))
    if cfg.get("air_quality", {}).get("enabled", True):
        a = cfg["air_quality"]
        sensors.append((
            AirQualitySensor(
                a.get("read_interval_sec", 8),
                a.get("dispatch_interval_sec", 16),
                a.get("dispatch_batch_size", 2),
                *a.get("range", [0, 500]),
            ),
            fog_url,
            timeout,
        ))
    if cfg.get("activity", {}).get("enabled", True):
        ac = cfg["activity"]
        sensors.append((
            ActivitySensor(
                ac.get("read_interval_sec", 6),
                ac.get("dispatch_interval_sec", 12),
                ac.get("dispatch_batch_size", 1),
                ac.get("levels", ActivitySensor.LEVELS),
            ),
            fog_url,
            timeout,
        ))
    return sensors


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(Path(__file__).parent, "config.yaml"))
    args = parser.parse_args()
    config = load_config(args.config)
    sensors_with_fog = build_sensors(config)
    if not sensors_with_fog:
        print("No sensors enabled in config.")
        return

    async def make_dispatch(fog_url: str, timeout: float):
        def _dispatch(payload: list):
            return dispatch_to_fog(fog_url, timeout, payload)
        return _dispatch

    tasks = []
    for sensor, fog_url, timeout in sensors_with_fog:
        on_dispatch = await make_dispatch(fog_url, timeout)
        tasks.append(sensor.run_loop(on_dispatch))
        print(f"Started {sensor.sensor_type} (read every {sensor.read_interval_sec}s, dispatch every {sensor.dispatch_interval_sec}s)")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
