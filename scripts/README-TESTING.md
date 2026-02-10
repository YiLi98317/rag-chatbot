# Local Build Testing Guide

## Quick Start

Test your Docker build locally before pushing to main:

```bash
# Run the local test script
./scripts/test-build-local.sh
```

This will:
- Build the Docker image locally
- Test that it runs successfully
- Check the health endpoint
- Show container logs

## Manual Testing

### Build Only
```bash
docker build -t rag-chatbot:local .
```

### Build and Test with Docker Compose
```bash
# Test with local docker-compose.yml (builds from source)
docker compose up --build

# Test with deploy/docker-compose.yml (uses pre-built image)
# First build the image:
docker build -t ghcr.io/yili98317/rag-chatbot:latest .
# Then update deploy/docker-compose.yml to use local image, or:
IMAGE_NAME=rag-chatbot:latest docker compose -f deploy/docker-compose.yml up
```

### Test Image Manually
```bash
# Build
docker build -t rag-chatbot:test .

# Run
docker run -d -p 8001:8000 --name rag-test rag-chatbot:test

# Check health
curl http://localhost:8001/healthz

# View logs
docker logs rag-test

# Stop and remove
docker stop rag-test && docker rm rag-test
```

## GitHub Actions Testing

### Test Build Workflow (No Push Required)
The `test-build.yml` workflow can be triggered manually or on PRs:
- Go to Actions → test-build → Run workflow
- This builds without pushing, so no permissions needed

### Fix GHCR Permissions Issue

If you see `denied: installation not allowed to Create organization package`:

1. **Check Repository Settings:**
   - Go to your repository → Settings → Actions → General
   - Under "Workflow permissions", ensure "Read and write permissions" is selected
   - Check "Allow GitHub Actions to create and approve pull requests"

2. **Check Package Permissions:**
   - Go to your repository → Settings → Actions → General
   - Scroll to "Workflow permissions"
   - Ensure "Read and write permissions" includes package access

3. **Alternative: Use Personal Access Token**
   - Create a Personal Access Token (PAT) with `write:packages` permission
   - Add it as a secret named `GHCR_TOKEN`
   - Update the workflow to use: `password: ${{ secrets.GHCR_TOKEN }}`

4. **For Organization Repositories:**
   - Organization admins need to allow GitHub Actions to create packages
   - Go to Organization Settings → Actions → General
   - Enable "Allow GitHub Actions to create and approve pull requests"
   - Check package creation permissions

## Environment Variables

When testing locally, ensure you have a `.env` file or set environment variables:

```bash
# Copy example .env if it exists, or create one
cp .env.example .env  # if available

# Or set variables manually
export VECTOR_PROVIDER=milvus
export MILVUS_URI=http://localhost:19530
export OLLAMA_BASE_URL=http://localhost:11434
# ... etc
```

## Troubleshooting

### Build Fails Locally
- Check Docker is running: `docker ps`
- Check Dockerfile syntax: `docker build --no-cache -t test .`
- Review error messages for missing files or dependencies

### Image Won't Start
- Check logs: `docker logs <container-id>`
- Verify port isn't in use: `lsof -i :8000`
- Check environment variables are set correctly

### Health Check Fails
- Wait longer for services to start (may take 30-60 seconds)
- Check dependent services (Milvus, Ollama) are running
- Review API logs for errors
