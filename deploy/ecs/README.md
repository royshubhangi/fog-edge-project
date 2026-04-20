# ECS + ALB Quick Start

This folder contains an idempotent bootstrap script to start deployment of the full stack to ECS Fargate with ALBs.

It provisions or reuses:
- ECS cluster
- Security group
- Cloud ALB + target group + listener
- Fog ALB + target group + listener
- CloudWatch log groups
- Task definitions (cloud, worker, fog, sensors)
- ECS services (cloud, worker, fog, sensors)

## 1) Prepare environment file

```bash
cd deploy/ecs
cp .env.ecs.example .env.ecs
```

Set the required values in `.env.ecs`:
- `TASK_EXECUTION_ROLE_ARN`
- `TASK_ROLE_ARN`
- `SQS_QUEUE_URL`
- `CLOUD_IMAGE`
- `FOG_IMAGE`
- `SENSORS_IMAGE`

Optional values are auto-discovered or defaulted:
- `AWS_ACCOUNT_ID` (auto from STS if empty)
- `VPC_ID` and `SUBNET_IDS` (default VPC + first two subnets if empty)

## 2) Run deployment bootstrap

From project root:

```bash
bash deploy/ecs/start-ecs-alb.sh
```

Or with an explicit env file:

```bash
bash deploy/ecs/start-ecs-alb.sh deploy/ecs/.env.ecs
```

The script is safe to re-run and will update existing ECS services with a forced new deployment.

## 3) Validate

After the script completes, verify:
- Cloud health: `http://<CLOUD_ALB_DNS>/api/health`
- Fog health: `http://<FOG_ALB_DNS>/health`

You can also check ECS service status:

```bash
aws ecs describe-services \
  --region <AWS_REGION> \
  --cluster <CLUSTER_NAME> \
  --services cloud-backend worker fog-node sensor-simulator
```
