# Deploy to AWS (ECS Fargate + SQS)

## Prerequisites
- AWS CLI configured
- ECR repositories for cloud-backend and fog-node images
- SQS Standard Queue created (note the queue URL)

## Steps

### 1. Create SQS queue
```bash
aws sqs create-queue --queue-name outfit-ingest-queue
# Note the QueueUrl from the output (e.g. https://sqs.region.amazonaws.com/account/outfit-ingest-queue)
```

### 2. Create ECR repos and push images
```bash
aws ecr create-repository --repository-name smart-outfit-cloud
aws ecr create-repository --repository-name smart-outfit-fog
# Build, tag, push (use your account ID and region)
docker build -t smart-outfit-cloud:latest ./cloud-backend
docker tag smart-outfit-cloud:latest <account>.dkr.ecr.<region>.amazonaws.com/smart-outfit-cloud:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/smart-outfit-cloud:latest
# Same for fog-node
```

### 3. Create VPC and ECS cluster
- Create a VPC (or use default) and subnets.
- Create ECS cluster (Fargate).

### 4. Task definitions
- **Cloud backend**: Fargate task, container port 8000, env `SQS_QUEUE_URL`, `DB_PATH`, `FOG_NODE_URL` (use EFS for persistence or RDS/S3 for analytics if needed).
- **Worker**: Same image, command `python -m app.worker`, env `SQS_QUEUE_URL`, `DB_PATH`.
- **Fog node**: Fog image, env `CLOUD_BACKEND_URL` = ALB URL of cloud backend.

Ensure the task role has SQS permissions: `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on the ingest queue.

### 5. Load balancer and services
- Application Load Balancer in front of cloud backend (port 80/443 → 8000).
- ECS services: cloud-backend (min 1, max 10), worker (min 0 or 1, max 5), fog-node (min 1).

### 6. Autoscaling
- Target tracking scaling on ALB request count or CPU for cloud-backend.
- Optional: scale worker by SQS queue depth using custom metric or Step Functions.

## Alternative: Lambda + API Gateway
- Ingest API can be implemented as Lambda (POST /api/ingest) pushing to SQS.
- Worker can be Lambda triggered by SQS queue for FaaS-style processing.
