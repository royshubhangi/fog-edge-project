#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
NAME_PREFIX="${NAME_PREFIX:-smart-outfit-ec2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
KEY_PATH="${KEY_PATH:-$HOME/.ssh/${NAME_PREFIX}.pem}"
AMI_ID="${AMI_ID:-}"

echo "Region: ${REGION}"
echo "Name prefix: ${NAME_PREFIX}"
echo "Instance type: ${INSTANCE_TYPE}"

if [[ -z "${AMI_ID}" ]]; then
  AMI_ID="$(aws ssm get-parameters --region "${REGION}" --names /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query 'Parameters[0].Value' --output text)"
fi
if [[ -z "${AMI_ID}" || "${AMI_ID}" == "None" ]]; then
  AMI_ID="$(aws ec2 describe-images \
    --region "${REGION}" \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text)"
fi
if [[ -z "${AMI_ID}" || "${AMI_ID}" == "None" ]]; then
  echo "Could not discover a valid Ubuntu AMI. Set AMI_ID and retry."
  exit 1
fi
echo "Using AMI: ${AMI_ID}"

VPC_ID="$(aws ec2 describe-vpcs --region "${REGION}" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
SUBNET_ID="$(aws ec2 describe-subnets --region "${REGION}" --filters Name=vpc-id,Values="${VPC_ID}" Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text)"

echo "Default VPC: ${VPC_ID}"
echo "Subnet: ${SUBNET_ID}"

MY_IP="$(curl -s https://checkip.amazonaws.com | tr -d '\n')/32"
echo "SSH allowed from: ${MY_IP}"

KEY_NAME="${NAME_PREFIX}-key"
if aws ec2 describe-key-pairs --region "${REGION}" --key-names "${KEY_NAME}" >/dev/null 2>&1; then
  echo "Key pair ${KEY_NAME} already exists in AWS."
else
  aws ec2 create-key-pair --region "${REGION}" --key-name "${KEY_NAME}" --query 'KeyMaterial' --output text > "${KEY_PATH}"
  chmod 400 "${KEY_PATH}"
  echo "Created key at ${KEY_PATH}"
fi

SG_NAME="${NAME_PREFIX}-sg"
SG_ID="$(aws ec2 describe-security-groups --region "${REGION}" --filters Name=group-name,Values="${SG_NAME}" Name=vpc-id,Values="${VPC_ID}" --query 'SecurityGroups[0].GroupId' --output text)"
if [[ "${SG_ID}" == "None" || -z "${SG_ID}" ]]; then
  SG_ID="$(aws ec2 create-security-group --region "${REGION}" --group-name "${SG_NAME}" --description "Security group for ${NAME_PREFIX}" --vpc-id "${VPC_ID}" --query 'GroupId' --output text)"
fi

aws ec2 authorize-security-group-ingress --region "${REGION}" --group-id "${SG_ID}" --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP},Description=SSH from current IP}]" >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --region "${REGION}" --group-id "${SG_ID}" --ip-permissions "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTP}]" >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --region "${REGION}" --group-id "${SG_ID}" --ip-permissions "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTPS}]" >/dev/null 2>&1 || true

INSTANCE_ID="$(aws ec2 run-instances \
  --region "${REGION}" \
  --image-id "${AMI_ID}" \
  --instance-type "${INSTANCE_TYPE}" \
  --key-name "${KEY_NAME}" \
  --security-group-ids "${SG_ID}" \
  --subnet-id "${SUBNET_ID}" \
  --associate-public-ip-address \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_PREFIX}}]" \
  --query 'Instances[0].InstanceId' \
  --output text)"

echo "Instance created: ${INSTANCE_ID}"
aws ec2 wait instance-running --region "${REGION}" --instance-ids "${INSTANCE_ID}"

ALLOC_ID="$(aws ec2 allocate-address --region "${REGION}" --domain vpc --query 'AllocationId' --output text)"
aws ec2 associate-address --region "${REGION}" --instance-id "${INSTANCE_ID}" --allocation-id "${ALLOC_ID}" >/dev/null

PUBLIC_IP="$(aws ec2 describe-addresses --region "${REGION}" --allocation-ids "${ALLOC_ID}" --query 'Addresses[0].PublicIp' --output text)"

echo
echo "Provisioned successfully."
echo "INSTANCE_ID=${INSTANCE_ID}"
echo "SECURITY_GROUP_ID=${SG_ID}"
echo "ELASTIC_IP=${PUBLIC_IP}"
echo "KEY_PATH=${KEY_PATH}"
echo
echo "Next: ssh -i ${KEY_PATH} ubuntu@${PUBLIC_IP}"
