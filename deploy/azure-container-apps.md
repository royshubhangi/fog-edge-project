# Deploy to Azure Container Apps

## Prerequisites
- Azure CLI (`az login`)
- Docker Hub or Azure Container Registry (ACR)

## Steps

### 1. Build and push images
```bash
# From project root
export REGISTRY=yourregistry.azurecr.io  # or docker.io/youruser
docker build -t $REGISTRY/smart-outfit-cloud:latest ./cloud-backend
docker build -t $REGISTRY/smart-outfit-fog:latest ./fog-node
docker build -t $REGISTRY/smart-outfit-sensors:latest ./sensors
docker push $REGISTRY/smart-outfit-cloud:latest
docker push $REGISTRY/smart-outfit-fog:latest
docker push $REGISTRY/smart-outfit-sensors:latest
```

### 2. Create resource group
```bash
az group create -n rg-smart-outfit -l westeurope
```
Ensure you have an SQS queue URL (e.g. from AWS) for `SQS_QUEUE_URL`; the app uses SQS for the ingest queue.

### 3. Create Container Apps environment
```bash
az containerapp env create -g rg-smart-outfit -n env-smart-outfit
```

### 4. Deploy cloud backend (with scaling)
```bash
az containerapp create -g rg-smart-outfit -n ca-cloud-backend \
  --environment env-smart-outfit \
  --image $REGISTRY/smart-outfit-cloud:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 --max-replicas 10 \
  --env-vars SQS_QUEUE_URL=https://sqs.... DB_PATH=/data/outfit.db \
  --cpu 0.5 --memory 1Gi
```

### 5. Deploy fog node (points to cloud backend URL)
```bash
# Get cloud backend FQDN first
az containerapp create -g rg-smart-outfit -n ca-fog-node \
  --environment env-smart-outfit \
  --image $REGISTRY/smart-outfit-fog:latest \
  --target-port 8001 \
  --ingress external \
  --env-vars CLOUD_BACKEND_URL=https://<cloud-backend-fqdn>
```

### 6. Deploy sensors (for evaluation/automated data generation)
```bash
az containerapp create -g rg-smart-outfit -n ca-sensors \
  --environment env-smart-outfit \
  --image $REGISTRY/smart-outfit-sensors:latest \
  --env-vars FOG_URL=https://<fog-node-fqdn>
```

### 7. Deploy worker (optional; scale to 0 when idle with KEDA)
Run the same cloud image with command override: `python -m app.worker`, and set `SQS_QUEUE_URL`.

## Autoscaling
Container Apps scales by default on HTTP request load. For queue-based scaling (worker), use a KEDA scale rule on SQS queue depth (e.g. ApproximateNumberOfMessagesVisible).
