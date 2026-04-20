#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env.ecs}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}"
  echo "Copy ${SCRIPT_DIR}/.env.ecs.example to ${SCRIPT_DIR}/.env.ecs and fill values."
  exit 1
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1"
    exit 1
  fi
}

require_cmd aws

AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-smart-outfit}"
CLUSTER_NAME="${CLUSTER_NAME:-${PROJECT_NAME}}"
SERVICE_SG_NAME="${SERVICE_SG_NAME:-${PROJECT_NAME}-ecs-sg}"

CLOUD_SERVICE_NAME="${CLOUD_SERVICE_NAME:-cloud-backend}"
WORKER_SERVICE_NAME="${WORKER_SERVICE_NAME:-worker}"
FOG_SERVICE_NAME="${FOG_SERVICE_NAME:-fog-node}"
SENSORS_SERVICE_NAME="${SENSORS_SERVICE_NAME:-sensor-simulator}"

CLOUD_ALB_NAME="${CLOUD_ALB_NAME:-${PROJECT_NAME}-cloud-alb}"
CLOUD_TG_NAME="${CLOUD_TG_NAME:-${PROJECT_NAME}-cloud-tg}"
FOG_ALB_NAME="${FOG_ALB_NAME:-${PROJECT_NAME}-fog-alb}"
FOG_TG_NAME="${FOG_TG_NAME:-${PROJECT_NAME}-fog-tg}"

CLOUD_TASK_CPU="${CLOUD_TASK_CPU:-256}"
CLOUD_TASK_MEMORY="${CLOUD_TASK_MEMORY:-512}"
WORKER_TASK_CPU="${WORKER_TASK_CPU:-256}"
WORKER_TASK_MEMORY="${WORKER_TASK_MEMORY:-512}"
FOG_TASK_CPU="${FOG_TASK_CPU:-256}"
FOG_TASK_MEMORY="${FOG_TASK_MEMORY:-512}"
SENSORS_TASK_CPU="${SENSORS_TASK_CPU:-256}"
SENSORS_TASK_MEMORY="${SENSORS_TASK_MEMORY:-512}"

CLOUD_DESIRED_COUNT="${CLOUD_DESIRED_COUNT:-1}"
WORKER_DESIRED_COUNT="${WORKER_DESIRED_COUNT:-1}"
FOG_DESIRED_COUNT="${FOG_DESIRED_COUNT:-1}"
SENSORS_DESIRED_COUNT="${SENSORS_DESIRED_COUNT:-1}"

CPU_ARCH="${CPU_ARCH:-ARM64}"

if [[ -z "${AWS_ACCOUNT_ID:-}" ]]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
fi

if [[ -z "${TASK_EXECUTION_ROLE_ARN:-}" ]]; then
  echo "TASK_EXECUTION_ROLE_ARN is required in ${ENV_FILE}."
  exit 1
fi

if [[ -z "${TASK_ROLE_ARN:-}" ]]; then
  echo "TASK_ROLE_ARN is required in ${ENV_FILE}."
  exit 1
fi

if [[ -z "${SQS_QUEUE_URL:-}" ]]; then
  echo "SQS_QUEUE_URL is required in ${ENV_FILE}."
  exit 1
fi

if [[ -z "${CLOUD_IMAGE:-}" || -z "${FOG_IMAGE:-}" || -z "${SENSORS_IMAGE:-}" ]]; then
  echo "CLOUD_IMAGE, FOG_IMAGE, and SENSORS_IMAGE are required in ${ENV_FILE}."
  exit 1
fi

echo "Using AWS account: ${AWS_ACCOUNT_ID}"
echo "Using region: ${AWS_REGION}"

if [[ -z "${VPC_ID:-}" ]]; then
  VPC_ID="$(aws ec2 describe-vpcs \
    --region "${AWS_REGION}" \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' \
    --output text)"
fi

if [[ -z "${VPC_ID}" || "${VPC_ID}" == "None" ]]; then
  echo "Could not determine VPC_ID. Set VPC_ID in ${ENV_FILE}."
  exit 1
fi

if [[ -z "${SUBNET_IDS:-}" ]]; then
  SUBNET_IDS="$(aws ec2 describe-subnets \
    --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${VPC_ID}" \
    --query 'Subnets[0:2].SubnetId' \
    --output text | tr '\t' ',')"
fi

if [[ -z "${SUBNET_IDS}" ]]; then
  echo "Could not determine SUBNET_IDS. Set SUBNET_IDS in ${ENV_FILE} as comma-separated values."
  exit 1
fi

IFS=',' read -r -a SUBNET_ARRAY <<< "${SUBNET_IDS}"
if [[ ${#SUBNET_ARRAY[@]} -lt 2 ]]; then
  echo "Need at least 2 subnets in SUBNET_IDS."
  exit 1
fi

echo "Ensuring ECS cluster exists: ${CLUSTER_NAME}"
CLUSTER_ARN="$(aws ecs describe-clusters --region "${AWS_REGION}" --clusters "${CLUSTER_NAME}" --query 'clusters[0].clusterArn' --output text 2>/dev/null || true)"
if [[ -z "${CLUSTER_ARN}" || "${CLUSTER_ARN}" == "None" || "${CLUSTER_ARN}" != arn:* ]]; then
  aws ecs create-cluster --region "${AWS_REGION}" --cluster-name "${CLUSTER_NAME}" >/dev/null
fi

echo "Ensuring security group exists: ${SERVICE_SG_NAME}"
SG_ID="$(aws ec2 describe-security-groups \
  --region "${AWS_REGION}" \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=${SERVICE_SG_NAME}" \
  --query 'SecurityGroups[0].GroupId' \
  --output text)"

if [[ -z "${SG_ID}" || "${SG_ID}" == "None" ]]; then
  SG_ID="$(aws ec2 create-security-group \
    --region "${AWS_REGION}" \
    --group-name "${SERVICE_SG_NAME}" \
    --description "${PROJECT_NAME} ECS services + ALB SG" \
    --vpc-id "${VPC_ID}" \
    --query 'GroupId' \
    --output text)"
fi

allow_ingress() {
  local port="$1"
  aws ec2 authorize-security-group-ingress \
    --region "${AWS_REGION}" \
    --group-id "${SG_ID}" \
    --protocol tcp \
    --port "${port}" \
    --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
}

allow_sg_ingress() {
  local port="$1"
  aws ec2 authorize-security-group-ingress \
    --region "${AWS_REGION}" \
    --group-id "${SG_ID}" \
    --protocol tcp \
    --port "${port}" \
    --source-group "${SG_ID}" >/dev/null 2>&1 || true
}

allow_ingress 80
allow_sg_ingress 8000
allow_sg_ingress 8001

create_or_get_alb() {
  local name="$1"
  local arn
  arn="$(aws elbv2 describe-load-balancers --region "${AWS_REGION}" --names "${name}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
  if [[ -z "${arn}" || "${arn}" == "None" ]]; then
    arn="$(aws elbv2 create-load-balancer \
      --region "${AWS_REGION}" \
      --name "${name}" \
      --type application \
      --scheme internet-facing \
      --subnets "${SUBNET_ARRAY[@]}" \
      --security-groups "${SG_ID}" \
      --query 'LoadBalancers[0].LoadBalancerArn' \
      --output text)"
  fi
  echo "${arn}"
}

create_or_get_tg() {
  local name="$1"
  local port="$2"
  local health_path="$3"
  local arn
  arn="$(aws elbv2 describe-target-groups --region "${AWS_REGION}" --names "${name}" --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
  if [[ -z "${arn}" || "${arn}" == "None" ]]; then
    arn="$(aws elbv2 create-target-group \
      --region "${AWS_REGION}" \
      --name "${name}" \
      --protocol HTTP \
      --port "${port}" \
      --vpc-id "${VPC_ID}" \
      --target-type ip \
      --health-check-path "${health_path}" \
      --query 'TargetGroups[0].TargetGroupArn' \
      --output text)"
  fi
  echo "${arn}"
}

ensure_listener() {
  local alb_arn="$1"
  local tg_arn="$2"
  local existing
  existing="$(aws elbv2 describe-listeners --region "${AWS_REGION}" --load-balancer-arn "${alb_arn}" --query 'Listeners[?Port==`80`].ListenerArn' --output text)"
  if [[ -z "${existing}" || "${existing}" == "None" ]]; then
    aws elbv2 create-listener \
      --region "${AWS_REGION}" \
      --load-balancer-arn "${alb_arn}" \
      --protocol HTTP \
      --port 80 \
      --default-actions "Type=forward,TargetGroupArn=${tg_arn}" >/dev/null
  fi
}

echo "Ensuring ALBs and target groups exist"
CLOUD_ALB_ARN="$(create_or_get_alb "${CLOUD_ALB_NAME}")"
FOG_ALB_ARN="$(create_or_get_alb "${FOG_ALB_NAME}")"
CLOUD_TG_ARN="$(create_or_get_tg "${CLOUD_TG_NAME}" 8000 /api/health)"
FOG_TG_ARN="$(create_or_get_tg "${FOG_TG_NAME}" 8001 /health)"
ensure_listener "${CLOUD_ALB_ARN}" "${CLOUD_TG_ARN}"
ensure_listener "${FOG_ALB_ARN}" "${FOG_TG_ARN}"

CLOUD_ALB_DNS="$(aws elbv2 describe-load-balancers --region "${AWS_REGION}" --load-balancer-arns "${CLOUD_ALB_ARN}" --query 'LoadBalancers[0].DNSName' --output text)"
FOG_ALB_DNS="$(aws elbv2 describe-load-balancers --region "${AWS_REGION}" --load-balancer-arns "${FOG_ALB_ARN}" --query 'LoadBalancers[0].DNSName' --output text)"

for group in cloud-backend worker fog-node sensor-simulator; do
  aws logs create-log-group --region "${AWS_REGION}" --log-group-name "/ecs/${PROJECT_NAME}/${group}" >/dev/null 2>&1 || true
done

TMP_DIR="${ROOT_DIR}/.tmp-ecs"
mkdir -p "${TMP_DIR}"

emit_taskdef() {
  local out_file="$1"
  local family="$2"
  local cpu="$3"
  local memory="$4"
  local container_name="$5"
  local image="$6"
  local container_port="${7:-}"
  local command_json="${8:-[]}"
  local env_json="$9"
  local log_group="${10}"

  {
    echo "{"
    echo "  \"family\": \"${family}\","
    echo "  \"networkMode\": \"awsvpc\","
    echo "  \"requiresCompatibilities\": [\"FARGATE\"],"
    echo "  \"cpu\": \"${cpu}\","
    echo "  \"memory\": \"${memory}\","
    echo "  \"executionRoleArn\": \"${TASK_EXECUTION_ROLE_ARN}\","
    echo "  \"taskRoleArn\": \"${TASK_ROLE_ARN}\","
    echo "  \"containerDefinitions\": ["
    echo "    {"
    echo "      \"name\": \"${container_name}\","
    echo "      \"image\": \"${image}\","
    echo "      \"essential\": true,"
    if [[ -n "${container_port}" ]]; then
      echo "      \"portMappings\": [{\"containerPort\": ${container_port}, \"protocol\": \"tcp\"}],"
    fi
    if [[ "${command_json}" != "[]" ]]; then
      echo "      \"command\": ${command_json},"
    fi
    echo "      \"environment\": ${env_json},"
    echo "      \"logConfiguration\": {"
    echo "        \"logDriver\": \"awslogs\","
    echo "        \"options\": {"
    echo "          \"awslogs-region\": \"${AWS_REGION}\","
    echo "          \"awslogs-group\": \"${log_group}\","
    echo "          \"awslogs-stream-prefix\": \"ecs\""
    echo "        }"
    echo "      }"
    echo "    }"
    echo "  ],"
    echo "  \"runtimePlatform\": {"
    echo "    \"operatingSystemFamily\": \"LINUX\","
    echo "    \"cpuArchitecture\": \"${CPU_ARCH}\""
    echo "  }"
    echo "}"
  } > "${out_file}"
}

echo "Rendering task definitions"
emit_taskdef "${TMP_DIR}/cloud-taskdef.json" \
  "${PROJECT_NAME}-cloud-backend" "${CLOUD_TASK_CPU}" "${CLOUD_TASK_MEMORY}" \
  "cloud-backend" "${CLOUD_IMAGE}" 8000 "[]" \
  "[{\"name\":\"AWS_REGION\",\"value\":\"${AWS_REGION}\"},{\"name\":\"SQS_QUEUE_URL\",\"value\":\"${SQS_QUEUE_URL}\"},{\"name\":\"DYNAMODB_TABLE_RECOMMENDATIONS\",\"value\":\"${DYNAMODB_TABLE_RECOMMENDATIONS}\"},{\"name\":\"DYNAMODB_TABLE_SENSORS\",\"value\":\"${DYNAMODB_TABLE_SENSORS}\"},{\"name\":\"FOG_NODE_URL\",\"value\":\"http://${FOG_ALB_DNS}\"}]" \
  "/ecs/${PROJECT_NAME}/cloud-backend"

emit_taskdef "${TMP_DIR}/worker-taskdef.json" \
  "${PROJECT_NAME}-worker" "${WORKER_TASK_CPU}" "${WORKER_TASK_MEMORY}" \
  "worker" "${CLOUD_IMAGE}" "" "[\"python\",\"-m\",\"app.worker\"]" \
  "[{\"name\":\"AWS_REGION\",\"value\":\"${AWS_REGION}\"},{\"name\":\"SQS_QUEUE_URL\",\"value\":\"${SQS_QUEUE_URL}\"},{\"name\":\"DYNAMODB_TABLE_RECOMMENDATIONS\",\"value\":\"${DYNAMODB_TABLE_RECOMMENDATIONS}\"},{\"name\":\"DYNAMODB_TABLE_SENSORS\",\"value\":\"${DYNAMODB_TABLE_SENSORS}\"}]" \
  "/ecs/${PROJECT_NAME}/worker"

emit_taskdef "${TMP_DIR}/fog-taskdef.json" \
  "${PROJECT_NAME}-fog-node" "${FOG_TASK_CPU}" "${FOG_TASK_MEMORY}" \
  "fog-node" "${FOG_IMAGE}" 8001 "[]" \
  "[{\"name\":\"CLOUD_BACKEND_URL\",\"value\":\"http://${CLOUD_ALB_DNS}\"}]" \
  "/ecs/${PROJECT_NAME}/fog-node"

emit_taskdef "${TMP_DIR}/sensors-taskdef.json" \
  "${PROJECT_NAME}-sensor-simulator" "${SENSORS_TASK_CPU}" "${SENSORS_TASK_MEMORY}" \
  "sensor-simulator" "${SENSORS_IMAGE}" "" "[]" \
  "[{\"name\":\"FOG_URL\",\"value\":\"http://${FOG_ALB_DNS}\"}]" \
  "/ecs/${PROJECT_NAME}/sensor-simulator"

echo "Registering task definitions"
aws ecs register-task-definition --region "${AWS_REGION}" --cli-input-json "file://${TMP_DIR}/cloud-taskdef.json" >/dev/null
aws ecs register-task-definition --region "${AWS_REGION}" --cli-input-json "file://${TMP_DIR}/worker-taskdef.json" >/dev/null
aws ecs register-task-definition --region "${AWS_REGION}" --cli-input-json "file://${TMP_DIR}/fog-taskdef.json" >/dev/null
aws ecs register-task-definition --region "${AWS_REGION}" --cli-input-json "file://${TMP_DIR}/sensors-taskdef.json" >/dev/null

upsert_service() {
  local service_name="$1"
  local task_family="$2"
  local desired_count="$3"
  local lb_arg="${4:-}"
  local grace="${5:-}"

  local service_arn
  service_arn="$(aws ecs describe-services \
    --region "${AWS_REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --services "${service_name}" \
    --query 'services[0].serviceArn' \
    --output text 2>/dev/null || true)"

  if [[ -z "${service_arn}" || "${service_arn}" == "None" ]]; then
    if [[ -n "${lb_arg}" ]]; then
      aws ecs create-service \
        --region "${AWS_REGION}" \
        --cluster "${CLUSTER_NAME}" \
        --service-name "${service_name}" \
        --task-definition "${task_family}" \
        --desired-count "${desired_count}" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SG_ID}],assignPublicIp=ENABLED}" \
        --load-balancers "${lb_arg}" \
        --health-check-grace-period-seconds "${grace}" >/dev/null
    else
      aws ecs create-service \
        --region "${AWS_REGION}" \
        --cluster "${CLUSTER_NAME}" \
        --service-name "${service_name}" \
        --task-definition "${task_family}" \
        --desired-count "${desired_count}" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SG_ID}],assignPublicIp=ENABLED}" >/dev/null
    fi
  else
    aws ecs update-service \
      --region "${AWS_REGION}" \
      --cluster "${CLUSTER_NAME}" \
      --service "${service_name}" \
      --task-definition "${task_family}" \
      --desired-count "${desired_count}" \
      --force-new-deployment >/dev/null
  fi
}

echo "Creating or updating ECS services"
upsert_service "${CLOUD_SERVICE_NAME}" "${PROJECT_NAME}-cloud-backend" "${CLOUD_DESIRED_COUNT}" "targetGroupArn=${CLOUD_TG_ARN},containerName=cloud-backend,containerPort=8000" 60
upsert_service "${WORKER_SERVICE_NAME}" "${PROJECT_NAME}-worker" "${WORKER_DESIRED_COUNT}"
upsert_service "${FOG_SERVICE_NAME}" "${PROJECT_NAME}-fog-node" "${FOG_DESIRED_COUNT}" "targetGroupArn=${FOG_TG_ARN},containerName=fog-node,containerPort=8001" 60
upsert_service "${SENSORS_SERVICE_NAME}" "${PROJECT_NAME}-sensor-simulator" "${SENSORS_DESIRED_COUNT}"

echo
echo "Deployment started."
echo "Cloud ALB: http://${CLOUD_ALB_DNS}"
echo "Fog ALB:   http://${FOG_ALB_DNS}"
echo
echo "Health checks:"
echo "  http://${CLOUD_ALB_DNS}/api/health"
echo "  http://${FOG_ALB_DNS}/health"
