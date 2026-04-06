# sensors/Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install aiohttp pyyaml

# Copy sensor code
COPY . .

# Run the sensors
CMD ["python", "run_sensors.py"]
