# Smart Outfit Recommendation Based on Environment

A **Fog and Edge** style cloud application: sensors → fog node(s) → cloud backend, with configurable sensor frequency and dispatch rates, and a scalable backend with queues and dashboards.

## Concept

- **Sensors** detect environment (temperature, humidity, UV, air quality, activity).
- **Fog node** forwards sensor data to the cloud on each ingest; outfit recommendation (comfort index, fabric, suggestions) is **on-demand** via a dashboard button, not on every ingest.
- **Cloud** stores sensor data and recommendation history; dashboard shows sensor gauges, time-series charts, and a "Suggest outfit" button.

---

## Architecture

```
[Sensors] ----(HTTP)----> [Fog Node] ----(HTTP)----> [Cloud Backend]
   (5 types)              forwards readings             SQS queue
   configurable            /recommend on-demand           Worker → DB
   frequency/dispatch      (when user clicks)             Dashboard + Suggest outfit
```

### Sensor layer
- **5 sensor types**: outdoor temperature, humidity, UV index, air quality, user activity level.
- **Configurable**: read interval, dispatch interval, batch size per sensor (see `sensors/config.yaml`).
- Data is sent to the fog node `/ingest` endpoint.

### Fog node
- Receives sensor readings; aggregates latest per type.
- Computes **comfort index** (0–100).
- Decides **recommended fabric type** (e.g. wool, cotton, linen, moisture_wicking).
- Produces **immediate clothing suggestions** (e.g. “Light jacket”, “Sunscreen”).
- On **ingest**: forwards only sensor data (source, timestamp, readings) to the cloud; no recommendation is computed. **On-demand**: `GET /recommend` computes comfort index, fabric, and suggestions from latest readings when the user clicks "Suggest outfit" on the dashboard.

### Cloud backend
- **Scalable**: ingest endpoint pushes sensor payloads to an **AWS SQS queue**; workers poll SQS and write sensor snapshots to the DB.
- **Storage**: SQLite (default; replace with Postgres in production).
- **APIs**: sensor latest/series, `GET /api/recommend` (proxies to fog), `POST /api/recommendation` (save from fog), recommendation history.
- **Dashboard**: sensor gauges, time-series charts, "Suggest outfit" button, and recommendation history.

---

## Quick start (local)

### 1. (Optional) Create an SQS queue and set URL
For queue-based ingest, create an SQS Standard Queue in AWS and set:
```bash
export SQS_QUEUE_URL=https://sqs.REGION.amazonaws.com/ACCOUNT_ID/QUEUE_NAME
```
If `SQS_QUEUE_URL` is not set, the ingest endpoint falls back to writing directly to the DB (sync).

### 2. Start cloud backend
```bash
cd cloud-backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000 for the dashboard, http://localhost:8000/docs for API.

### 3. Start queue worker (separate terminal)
```bash
cd cloud-backend
python -m app.worker
```
The worker polls SQS when `SQS_QUEUE_URL` is set; otherwise it idles.

### 4. Start fog node
```bash
cd fog-node
pip install -r requirements.txt
export CLOUD_BACKEND_URL=http://localhost:8000
uvicorn fog_node:app --reload --port 8001
```

### 5. Run sensors (sends to fog)
```bash
cd sensors
pip install -r requirements.txt
# Edit sensors/config.yaml if needed: fog.url = http://localhost:8001
python run_sensors.py
```

Data will flow: sensors → fog → cloud (queue) → worker → DB. Refresh the dashboard to see sensor values, series charts, seasonal stats, and recommendation history.

---

## Full stack with Docker Compose

From the project root:

```bash
docker compose up -d
```

This starts:
- **Cloud backend** on port 8000 (dashboard at http://localhost:8000)
- **Cloud worker** (polls SQS and writes to DB when `SQS_QUEUE_URL` is set)
- **Fog node** on port 8001
- **Sensor simulator** (sends data to the fog node internally)

Set `SQS_QUEUE_URL` in the environment (or in a `.env` file) to use the queue; otherwise ingest writes to the DB synchronously.

All data will flow automatically. You can view the dashboard at http://localhost:8000.

---

## Configuration

### Sensors (`sensors/config.yaml`)
- Enable/disable each sensor.
- `read_interval_sec`, `dispatch_interval_sec`, `dispatch_batch_size` per sensor.
- `fog.url`: fog node base URL.
- Optional: plug in real APIs (e.g. OpenWeather, Purple Air) by extending the sensor classes.

### Fog node
- `CLOUD_BACKEND_URL`: cloud API base URL (default `http://localhost:8000`).

### Cloud backend
- `SQS_QUEUE_URL`: AWS SQS queue URL for ingest (e.g. `https://sqs.region.amazonaws.com/account/queue-name`). If unset, ingest falls back to synchronous DB write.
- `DB_PATH`: path to SQLite file (default `cloud-backend/data/outfit.db`).
- `FOG_NODE_URL`: fog node base URL for on-demand recommendation (default `http://localhost:8001`). Used when the dashboard "Suggest outfit" button is clicked.

---

## Deployment to public cloud

- **Azure**: see [deploy/azure-container-apps.md](deploy/azure-container-apps.md) (Container Apps, Redis, optional autoscaling).
- **AWS**: see [deploy/aws-ecs.md](deploy/aws-ecs.md) (ECS Fargate, SQS).
- **AWS low-cost option (EC2 + Nginx)**: see [deploy/ec2/README.md](deploy/ec2/README.md).

The design (queue + workers, stateless API) supports horizontal scaling and FaaS (e.g. Azure Functions or Lambda for ingest/worker).

---

## Project layout

```
fog-edge-project/
├── sensors/           # Sensor simulators (configurable frequency & dispatch)
│   ├── config.yaml
│   ├── run_sensors.py
│   ├── sensor_base.py
│   ├── temperature_sensor.py
│   ├── humidity_sensor.py
│   ├── uv_sensor.py
│   ├── air_quality_sensor.py
│   └── activity_sensor.py
├── fog-node/          # Virtual fog node
│   ├── fog_node.py
│   ├── comfort_index.py
│   ├── fabric_recommender.py
│   └── requirements.txt
├── cloud-backend/     # Scalable web service
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── database.py
│   │   ├── queue.py
│   │   ├── worker.py
│   │   └── dashboard/
│   │       └── index.html
│   ├── requirements.txt
│   └── Dockerfile
├── deploy/
│   ├── azure-container-apps.md
│   └── aws-ecs.md
├── docker-compose.yml
└── README.md
```

---

## Testing

1. **Sensors + Fog**: Start fog and cloud, then run sensors; check fog logs for comfort index and suggestions; check cloud `/api/analytics/recommendation-history` for stored recommendations.
2. **Dashboard**: Open http://localhost:8000; confirm latest sensor values, charts, seasonal fabric stats, and recommendation history update.
3. **Scalability**: Run multiple workers; ingest multiple payloads; confirm queue length via `/api/queue/length` and that all are processed.

This solution aligns with the Fog and Edge module: sensor and fog layers with configurable data generation and dispatch, virtual fog node processing, and a scalable cloud backend with queues, workers, and responsive dashboards, deployable to Azure or AWS.
