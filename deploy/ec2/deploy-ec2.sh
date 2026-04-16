#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/smart-outfit"
ENV_FILE="${PROJECT_DIR}/.env"
COMPOSE_FILE="${PROJECT_DIR}/deploy/ec2/docker-compose.ec2.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Create it first."
  exit 1
fi

cd "${PROJECT_DIR}"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull || true
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --build
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps

echo "Deployment complete."
