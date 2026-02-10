# ECS Deployment Guide

This document describes how to deploy the RAG chatbot API to Alibaba ECS using GitHub Actions.

> **Note**: Throughout this document, `<your-ecs-ip>` is used as a placeholder for your actual ECS server IP address. Replace it with your real IP address when following the instructions. The IP address should be stored in the `ECS_HOST` GitHub secret, not hardcoded in this documentation.

## Quick Start - Next Steps

Now that you can connect to your ECS server, follow these steps in order:

### Step 1: ✅ Connect to ECS (Done!)
```bash
ssh root@<your-ecs-ip>
```

### Step 2: Install Docker and Docker Compose on ECS

While connected to your ECS server, run:

```bash
# Install Docker Engine
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Verify installation
docker version
docker compose version

# Create deployment directory
mkdir -p /opt/rag
chmod 755 /opt/rag
```

**Expected output**: You should see Docker and Docker Compose version information. If `docker compose version` shows an error, you may need to install the compose plugin separately.

### Step 3: Configure GitHub Secrets

Go to your GitHub repository: **Settings → Secrets and variables → Actions → New repository secret**

**Minimum required secrets to get started:**

1. **ECS_HOST** = `<your-ecs-ip>` (e.g., `1.2.3.4` - your ECS server IP address)
2. **ECS_USER** = `root`
3. **ECS_PASSWORD** = `<your-root-password>` (the password you use to SSH)

**Optional but recommended:**
- **ECS_PORT** = `22` (can be omitted, defaults to 22)

**Application secrets** (set these with your preferred values, or use defaults):

- **VECTOR_PROVIDER** = `milvus` (default)
- **MILVUS_URI** = `http://milvus:19530` (default - uses service name from docker-compose)
- **MILVUS_DB** = `default` (default)
- **MILVUS_COLLECTION** = `chatbot_docs` (default)
- **OLLAMA_BASE_URL** = `http://ollama:11434` (default - uses service name from docker-compose)
- **EMBED_PROVIDER** = `sentence_transformers` (default)
- **EMBED_MODEL** = `BAAI/bge-m3` (default)
- **CHAT_MODEL** = `deepseek-r1` (default)
- **TOP_K_DEFAULT** = `10` (default)
- **DEBUG_TRACES** = `0` (default)

**Note**: If you don't set the application secrets, the workflow will use the defaults listed above.

### Step 4: Configure Firewall/Security Group

In Alibaba Cloud Console:
1. Go to **ECS → Security Groups**
2. Find the security group attached to your instance
3. Add inbound rules:
   - **SSH (22/tcp)**: Allow from your IP address (or GitHub Actions IP ranges)
   - **HTTP (80/tcp)**: Allow from `0.0.0.0/0` (public access)

### Step 5: Push to Main Branch

Once all secrets are configured, push your code to the `main` branch:

```bash
git add .
git commit -m "Add ECS deployment configuration"
git push origin main
```

This will trigger the GitHub Actions workflow which will:
1. Build your Docker image
2. Push it to GitHub Container Registry (GHCR)
3. Deploy to your ECS server
4. Start all services (API, Milvus, Ollama, etc.)

### Step 6: Verify Deployment

After the workflow completes (check GitHub Actions tab), verify the deployment:

```bash
# From your local machine (replace <your-ecs-ip> with your actual ECS IP)
curl http://<your-ecs-ip>/healthz
curl http://<your-ecs-ip>/readyz

# Or SSH to ECS and check
ssh root@<your-ecs-ip>
cd /opt/rag
docker compose ps
docker compose logs api
```

---

## Prerequisites

### 1. ECS Server Setup

SSH into your ECS instance:

```bash
ssh root@<your-ecs-ip>
```

#### Install Docker and Docker Compose

```bash
# Install Docker Engine
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Verify installation
docker version
docker compose version
```

#### Create Deployment Directory

```bash
mkdir -p /opt/rag
chmod 755 /opt/rag
```

#### Configure Firewall/Security Group

In Alibaba Cloud Console, configure security group rules:

1. **SSH (Port 22)** - **Required for deployment**
   - Port: `22/tcp`
   - Source: Your IP address (or GitHub Actions IP ranges - see note below)
   - **Important**: This must be open for GitHub Actions to deploy

2. **HTTP (Port 80)** - **Required for API access**
   - Port: `80/tcp`
   - Source: `0.0.0.0/0` (public access)

3. **HTTPS (Port 443)** - Optional
   - Port: `443/tcp`
   - Source: `0.0.0.0/0` (if adding TLS later)

**Important Notes**:
- **SSH port is 22** (not 87545538 - that was a typo in the original plan)
- For GitHub Actions to deploy, port 22 must be accessible. You can either:
  - Allow from your IP address (if you're manually triggering)
  - Allow from GitHub Actions IP ranges: https://api.github.com/meta (look for `actions` IPs)
  - Or temporarily allow from `0.0.0.0/0` during deployment (less secure, but works)

### 2. GitHub Secrets Configuration

Navigate to your repository: **Settings → Secrets and variables → Actions → New repository secret**

#### Required SSH Connection Secrets

| Secret Name | Value | Description |
|------------|-------|-------------|
| `ECS_HOST` | `<your-ecs-ip>` | ECS server IP address (e.g., `1.2.3.4`) |
| `ECS_PORT` | `22` (or leave empty) | SSH port (default is 22, can be omitted) |
| `ECS_USER` | `root` | SSH username (recommend switching to deploy user later) |
| `ECS_PASSWORD` | `<your-root-password>` | SSH password (temporary, migrate to SSH key) |

#### Required Application Environment Secrets

| Secret Name | Value | Description |
|------------|-------|-------------|
| `VECTOR_PROVIDER` | `milvus` | Vector store provider (milvus or qdrant) |
| `MILVUS_URI` | `http://milvus:19530` | Milvus connection URI (use service name in compose) |
| `MILVUS_DB` | `default` | Milvus database name |
| `MILVUS_COLLECTION` | `chatbot_docs` | Default collection name |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL (use service name in compose) |
| `EMBED_PROVIDER` | `sentence_transformers` | Embedding provider (sentence_transformers or ollama) |
| `EMBED_MODEL` | `BAAI/bge-m3` | Embedding model name |
| `CHAT_MODEL` | `deepseek-r1` | Chat/LLM model name (must exist in Ollama) |
| `TOP_K_DEFAULT` | `10` | Default number of retrieval results |
| `DEBUG_TRACES` | `0` | Enable debug traces (0 or 1) |

#### Optional Secrets

| Secret Name | Value | Description |
|------------|-------|-------------|
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant URL (if using Qdrant instead of Milvus) |
| `QDRANT_API_KEY` | `<api-key>` | Qdrant API key (if required) |
| `ECS_GHCR_TOKEN` | `<github-pat>` | GitHub Personal Access Token for pulling images from GHCR (recommended over GITHUB_TOKEN) |

**Note**: If `ECS_GHCR_TOKEN` is not set, the workflow will use `GITHUB_TOKEN` (automatically provided by GitHub Actions). For production, it's recommended to create a PAT with `read:packages` permission and store it as `ECS_GHCR_TOKEN`.

## Deployment Flow

1. **Push to main branch** triggers the deployment workflow
2. **Build**: Docker image is built and pushed to `ghcr.io/<owner>/<repo>:latest`
3. **Deploy**: 
   - `deploy/docker-compose.yml` is copied to `/opt/rag/docker-compose.yml` on ECS
   - `.env` file is generated from GitHub secrets
   - Docker Compose pulls latest API image and starts all services
4. **Verify**: Health check confirms API is responding

## Services Deployed

The deployment includes:

- **API**: FastAPI service on port 80 (mapped from container port 8000)
- **Milvus**: Vector database with etcd and minio dependencies
- **Ollama**: LLM service for chat and embeddings (if configured)

All services are configured with:
- Health checks
- Restart policy: `unless-stopped`
- Named volumes for data persistence

## Post-Deployment Verification

After deployment, verify the services:

```bash
# SSH into ECS (replace <your-ecs-ip> with your actual ECS IP)
ssh root@<your-ecs-ip>

# Check service status
cd /opt/rag
docker compose ps

# Check logs
docker compose logs -f api

# Test health endpoint
curl http://localhost/healthz

# Test readiness endpoint
curl http://localhost/readyz

# Test QA endpoint
curl -X POST http://localhost/v1/qa \
  -H "Content-Type: application/json" \
  -d '{"question":"hello"}'
```

From outside the server:

```bash
# Replace <your-ecs-ip> with your actual ECS IP address
curl http://<your-ecs-ip>/healthz
curl http://<your-ecs-ip>/readyz
curl -X POST http://<your-ecs-ip>/v1/qa \
  -H "Content-Type: application/json" \
  -d '{"question":"hello"}'
```

## SSH Key Migration (Recommended)

For better security, migrate from password authentication to SSH keys:

### 1. Generate SSH Key Locally

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy
```

### 2. Copy Public Key to ECS

```bash
ssh-copy-id -i ~/.ssh/github_actions_deploy.pub root@<your-ecs-ip>
```

### 3. Update GitHub Secret

- Add `ECS_SSH_KEY` secret with the contents of `~/.ssh/github_actions_deploy` (private key)
- Update `.github/workflows/deploy.yml` to use `key` instead of `password` in SSH actions
- Remove `ECS_PASSWORD` secret

### 4. Harden SSH (Optional)

On ECS, edit `/etc/ssh/sshd_config`:

```
PasswordAuthentication no
PermitRootLogin prohibit-password
```

Then restart SSH:

```bash
systemctl restart sshd
```

Consider creating a dedicated `deploy` user with sudo access instead of using root.

## Troubleshooting

### Deployment Fails

1. Check GitHub Actions logs for specific errors
2. SSH to ECS and check logs:
   ```bash
   cd /opt/rag
   docker compose logs
   ```
3. Verify Docker is running: `systemctl status docker`
4. Check disk space: `df -h`
5. Verify network connectivity: `docker compose pull api`

### API Not Responding

1. Check if containers are running: `docker compose ps`
2. Check API logs: `docker compose logs api`
3. Verify health checks: `docker compose ps` (check health status)
4. Check port binding: `netstat -tlnp | grep 80`
5. Verify firewall rules in Alibaba Cloud Console

### Image Pull Fails

1. Verify GHCR authentication: `docker login ghcr.io`
2. Check image exists: Visit `https://github.com/<owner>/<repo>/pkgs/container/<repo>`
3. Ensure `ECS_GHCR_TOKEN` or `GITHUB_TOKEN` has `read:packages` permission
4. Check package visibility settings (private packages require authentication)

### Milvus/Ollama Not Ready

1. Check service logs: `docker compose logs milvus` or `docker compose logs ollama`
2. Verify health checks: Wait for services to become healthy (may take 1-2 minutes)
3. Check resource usage: `docker stats`
4. Verify volumes: `docker volume ls`

## Rollback

To rollback to a previous version:

1. SSH to ECS
2. Edit `/opt/rag/docker-compose.yml` to use a specific image tag:
   ```yaml
   api:
     image: ghcr.io/<owner>/<repo>:<previous-sha>
   ```
3. Run: `docker compose pull api && docker compose up -d`

Or manually pull and restart:

```bash
cd /opt/rag
docker compose pull api
docker compose up -d api
```

## Maintenance

### Update Models in Ollama

SSH to ECS and pull new models:

```bash
docker compose exec ollama ollama pull <model-name>
```

### View Logs

```bash
cd /opt/rag
docker compose logs -f [service-name]
```

### Restart Services

```bash
cd /opt/rag
docker compose restart [service-name]
```

### Backup Volumes

```bash
docker run --rm -v rag-chatbot_etcd_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/etcd_backup.tar.gz /data
```

### Clean Up

Remove unused images:

```bash
docker image prune -a
```

Remove unused volumes (⚠️ **WARNING**: This deletes data):

```bash
docker volume prune
```
