# EC2 + Nginx deployment (no ECS/ALB)

This setup deploys all services to one EC2 instance and exposes only Nginx (port 80/443):

- `cloud-backend` (FastAPI) internal on `127.0.0.1:8000`
- `fog-node` internal on `127.0.0.1:8001`
- `cloud-worker` and `sensor-simulator` internal
- Nginx forwards public traffic to `cloud-backend`

## 1) Provision EC2

- Ubuntu 22.04
- Security Group inbound:
  - `22` from your IP
  - `80` from `0.0.0.0/0`
  - `443` from `0.0.0.0/0` (when SSL is enabled)
- Assign an Elastic IP

## 2) Copy project to EC2

```bash
ssh -i <key.pem> ubuntu@<ec2-ip>
sudo mkdir -p /opt/smart-outfit
sudo chown -R ubuntu:ubuntu /opt/smart-outfit
exit

rsync -avz --delete -e "ssh -i <key.pem>" ./ ubuntu@<ec2-ip>:/opt/smart-outfit/
```

## 3) Add runtime env file on EC2

Create `/opt/smart-outfit/.env`:

```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>
AWS_SESSION_TOKEN=<your_session_token>
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<account-id>/outfit-ingest-queue
DYNAMODB_TABLE_RECOMMENDATIONS=outfit-recommendations
DYNAMODB_TABLE_SENSORS=outfit-sensor-snapshots
```

## 4) Install system dependencies

```bash
ssh -i <key.pem> ubuntu@<ec2-ip>
cd /opt/smart-outfit
chmod +x deploy/ec2/setup-ec2.sh deploy/ec2/deploy-ec2.sh
sudo ./deploy/ec2/setup-ec2.sh
```

## 5) Deploy containers

```bash
cd /opt/smart-outfit
./deploy/ec2/deploy-ec2.sh
```

## 6) Verify

```bash
docker ps
curl -f http://localhost:8000/api/health
curl -f http://localhost:8001/health
curl -f http://localhost/api/health
```

Public URL:

- `http://<elastic-ip>/`
- `http://<elastic-ip>/docs`

## 8) CI/CD via GitHub Actions (SSM, no SSH)

Workflow file:

- `.github/workflows/ec2-deploy.yml`

This pipeline does:

1. Builds all three Docker images as CI smoke tests.
2. Sends an SSM command to EC2 to update code to the pushed commit.
3. Runs `deploy/ec2/deploy-ec2.sh` on the instance.
4. Verifies `http://<EC2_PUBLIC_HOST>/api/health`.

Add these GitHub repo secrets:

- `EC2_INSTANCE_ID` (e.g. `i-0a8d4e3fa1c8ab083`)
- `EC2_PUBLIC_HOST` (Elastic IP or domain, e.g. `52.200.228.79`)
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN`

Important:

- Keep `/opt/smart-outfit/.env` on EC2.
- EC2 must be an SSM-managed instance (IAM role with `AmazonSSMManagedInstanceCore`).
- Trigger: push to `main` (or run manually via `workflow_dispatch`).

## 7) Optional HTTPS

If DNS points to your instance:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <your-domain>
```
