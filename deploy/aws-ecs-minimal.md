# Minimal AWS ECS (Fargate) deployment (LabRole)

This project runs as **3 ECS Fargate services** + **2 ALBs**:

- **cloud-backend** (FastAPI) behind ALB #1
- **fog-node** (FastAPI) behind ALB #2
- **sensor-simulator** (sensors container) as a service (no ALB)
- **worker** (queue consumer) as a service (no ALB)

Data plane:
- Sensors → fog-node `/ingest`
- fog-node → cloud-backend `/api/ingest` (SQS enqueue + DynamoDB)
- cloud-backend `/api/recommend` → fog-node `/recommend`

## Prereqs

- AWS account access via **LabRole** (AWS Academy/Vocareum)
- AWS CLI configured and using **`us-east-1`**
- Docker Desktop (Apple Silicon users: see **linux/amd64** note below)
- ECR repos already created:
  - `smart-outfit/cloud-backend`
  - `smart-outfit/fog-node`
  - `smart-outfit/sensor-simulator`

## 0) Variables (your account already)

Account: `121332300574`  
Region: `us-east-1`

ECR:
- `121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/cloud-backend:latest`
- `121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/fog-node:latest`
- `121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/sensor-simulator:latest`

## 1) Create SQS queue

```bash
aws sqs create-queue --region us-east-1 --queue-name outfit-ingest-queue
aws sqs get-queue-url --region us-east-1 --queue-name outfit-ingest-queue
```

Queue URL (example from lab):
`https://sqs.us-east-1.amazonaws.com/121332300574/outfit-ingest-queue`

## 2) Create DynamoDB tables (if not already created)

```bash
aws dynamodb create-table \
  --region us-east-1 \
  --table-name outfit-recommendations \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

aws dynamodb create-table \
  --region us-east-1 \
  --table-name outfit-sensor-snapshots \
  --attribute-definitions AttributeName=sensor_type,AttributeType=S AttributeName=ts,AttributeType=S \
  --key-schema AttributeName=sensor_type,KeyType=HASH AttributeName=ts,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
```

## 3) Login to ECR

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 121332300574.dkr.ecr.us-east-1.amazonaws.com
```

## 4) Build + push images

### Important for Apple Silicon (M1/M2/M3)

ECS Fargate in this lab expects **`linux/amd64`**. If you push ARM-only images, tasks fail with:

`CannotPullContainerError: ... descriptor matching platform 'linux/amd64'`

Use `buildx`:

```bash
docker buildx create --use 2>/dev/null || true
```

Build/push:

```bash
docker buildx build --platform linux/amd64 \
  -t 121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/cloud-backend:latest \
  "/Users/shubhangiroy/Documents/NCI/F&E/fog-edge-project/cloud-backend" \
  --push

docker buildx build --platform linux/amd64 \
  -t 121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/fog-node:latest \
  "/Users/shubhangiroy/Documents/NCI/F&E/fog-edge-project/fog-node" \
  --push

docker buildx build --platform linux/amd64 \
  -t 121332300574.dkr.ecr.us-east-1.amazonaws.com/smart-outfit/sensor-simulator:latest \
  "/Users/shubhangiroy/Documents/NCI/F&E/fog-edge-project/sensors" \
  --push
```

## 5) Create ECS cluster

```bash
aws ecs create-cluster --region us-east-1 --cluster-name smart-outfit
```

## 6) Use default VPC + pick two public subnets

```bash
aws ec2 describe-vpcs --region us-east-1 --filters Name=isDefault,Values=true
aws ec2 describe-subnets --region us-east-1 --filters Name=vpc-id,Values=<DEFAULT_VPC_ID>
```

Example used:
- VPC: `vpc-0ef4cb7293f97f6ca`
- Subnets: `subnet-0c274ee0bb6cb6701` and `subnet-0f6b3145040f642ca`

## 7) Security group

Create SG:

```bash
aws ec2 create-security-group \
  --region us-east-1 \
  --group-name smart-outfit-sg \
  --description "Smart outfit SG" \
  --vpc-id <DEFAULT_VPC_ID>
```

Allow inbound HTTP:

```bash
aws ec2 authorize-security-group-ingress \
  --region us-east-1 --group-id <SG_ID> \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
```

Allow ALB-to-task traffic:

```bash
# cloud-backend container port
aws ec2 authorize-security-group-ingress \
  --region us-east-1 --group-id <SG_ID> \
  --protocol tcp --port 8000 --source-group <SG_ID>

# fog-node container port
aws ec2 authorize-security-group-ingress \
  --region us-east-1 --group-id <SG_ID> \
  --protocol tcp --port 8001 --source-group <SG_ID>
```

## 8) Cloud ALB (cloud-backend)

Create ALB:

```bash
aws elbv2 create-load-balancer \
  --region us-east-1 \
  --name smart-outfit-alb \
  --type application \
  --scheme internet-facing \
  --subnets <SUBNET_1> <SUBNET_2> \
  --security-groups <SG_ID>
```

Create target group (port 8000, health check `/api/health`):

```bash
aws elbv2 create-target-group \
  --region us-east-1 \
  --name smart-outfit-cloud-tg \
  --protocol HTTP \
  --port 8000 \
  --vpc-id <DEFAULT_VPC_ID> \
  --target-type ip \
  --health-check-path /api/health
```

Create listener:

```bash
aws elbv2 create-listener \
  --region us-east-1 \
  --load-balancer-arn <CLOUD_ALB_ARN> \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=<CLOUD_TG_ARN>
```

## 9) Fog ALB (fog-node)

Create ALB:

```bash
aws elbv2 create-load-balancer \
  --region us-east-1 \
  --name smart-outfit-fog-alb \
  --type application \
  --scheme internet-facing \
  --subnets <SUBNET_1> <SUBNET_2> \
  --security-groups <SG_ID>
```

Create target group (port 8001, health check `/health`):

```bash
aws elbv2 create-target-group \
  --region us-east-1 \
  --name smart-outfit-fog-tg \
  --protocol HTTP \
  --port 8001 \
  --vpc-id <DEFAULT_VPC_ID> \
  --target-type ip \
  --health-check-path /health
```

Create listener:

```bash
aws elbv2 create-listener \
  --region us-east-1 \
  --load-balancer-arn <FOG_ALB_ARN> \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=<FOG_TG_ARN>
```

## 10) CloudWatch log groups (optional but recommended)

```bash
aws logs create-log-group --region us-east-1 --log-group-name /ecs/smart-outfit/cloud-backend || true
aws logs create-log-group --region us-east-1 --log-group-name /ecs/smart-outfit/worker || true
aws logs create-log-group --region us-east-1 --log-group-name /ecs/smart-outfit/fog-node || true
aws logs create-log-group --region us-east-1 --log-group-name /ecs/smart-outfit/sensor-simulator || true
```

## 11) ECS task definitions

We used JSON task definitions stored in repo root:

- `cloud-taskdef.json` (cloud-backend)
- `worker-taskdef.json` (worker)
- `fog-taskdef.json` (fog-node)
- `sensors-taskdef.json` (sensor-simulator)

Key env vars:

**cloud-backend**
- `SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/121332300574/outfit-ingest-queue`
- `DYNAMODB_TABLE_RECOMMENDATIONS=outfit-recommendations`
- `DYNAMODB_TABLE_SENSORS=outfit-sensor-snapshots`
- `FOG_NODE_URL=http://<FOG_ALB_DNS>`

**fog-node**
- `CLOUD_BACKEND_URL=http://<CLOUD_ALB_DNS>`

**sensor-simulator**
- `FOG_URL=http://<FOG_ALB_DNS>`

Register task definitions:

```bash
aws ecs register-task-definition --region us-east-1 --cli-input-json file://cloud-taskdef.json
aws ecs register-task-definition --region us-east-1 --cli-input-json file://worker-taskdef.json
aws ecs register-task-definition --region us-east-1 --cli-input-json file://fog-taskdef.json
aws ecs register-task-definition --region us-east-1 --cli-input-json file://sensors-taskdef.json
```

## 12) ECS services (Fargate)

### cloud-backend (behind cloud ALB)

```bash
aws ecs create-service \
  --region us-east-1 \
  --cluster smart-outfit \
  --service-name cloud-backend \
  --task-definition smart-outfit-cloud-backend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_1>,<SUBNET_2>],securityGroups=[<SG_ID>],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=<CLOUD_TG_ARN>,containerName=cloud-backend,containerPort=8000" \
  --health-check-grace-period-seconds 60
```

### worker (no ALB)

```bash
aws ecs create-service \
  --region us-east-1 \
  --cluster smart-outfit \
  --service-name worker \
  --task-definition smart-outfit-worker \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_1>,<SUBNET_2>],securityGroups=[<SG_ID>],assignPublicIp=ENABLED}"
```

### fog-node (behind fog ALB)

```bash
aws ecs create-service \
  --region us-east-1 \
  --cluster smart-outfit \
  --service-name fog-node \
  --task-definition smart-outfit-fog-node \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_1>,<SUBNET_2>],securityGroups=[<SG_ID>],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=<FOG_TG_ARN>,containerName=fog-node,containerPort=8001"
```

### sensor-simulator (no ALB)

```bash
aws ecs create-service \
  --region us-east-1 \
  --cluster smart-outfit \
  --service-name sensor-simulator \
  --task-definition smart-outfit-sensor-simulator \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<SUBNET_1>,<SUBNET_2>],securityGroups=[<SG_ID>],assignPublicIp=ENABLED}"
```

## 13) Update env vars and redeploy (when wiring URLs)

When fog-node got an ALB DNS name, we updated `FOG_NODE_URL` in `cloud-taskdef.json`,
registered a new task revision, and redeployed:

```bash
aws ecs register-task-definition --region us-east-1 --cli-input-json file://cloud-taskdef.json
aws ecs update-service --region us-east-1 --cluster smart-outfit --service cloud-backend --task-definition smart-outfit-cloud-backend --force-new-deployment
```

## 14) Health checks and final URLs

Find ALB DNS names:

```bash
aws elbv2 describe-load-balancers --region us-east-1 --names smart-outfit-alb smart-outfit-fog-alb --query 'LoadBalancers[].{Name:LoadBalancerName,DNS:DNSName}'
```

Verify target health:

```bash
aws elbv2 describe-target-health --region us-east-1 --target-group-arn <CLOUD_TG_ARN>
aws elbv2 describe-target-health --region us-east-1 --target-group-arn <FOG_TG_ARN>
```

Endpoints:
- Cloud backend:
  - `http://<CLOUD_ALB_DNS>/api/health`
  - `http://<CLOUD_ALB_DNS>/docs`
  - `http://<CLOUD_ALB_DNS>/api/recommend`
- Fog node:
  - `http://<FOG_ALB_DNS>/health`
  - `http://<FOG_ALB_DNS>/ingest`

