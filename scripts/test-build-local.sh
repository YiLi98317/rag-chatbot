#!/bin/bash
set -e

# Local build and test script for Docker image
# This allows testing the build without pushing to GitHub Container Registry

echo "🔨 Building Docker image locally..."

# Get repository name (defaults to current directory name)
REPO_NAME="${GITHUB_REPOSITORY:-$(basename $(pwd))}"
IMAGE_NAME="rag-chatbot:local-test"
FULL_IMAGE_NAME="ghcr.io/${REPO_NAME}:local-test"

# Build the image
echo "Building image: ${IMAGE_NAME}"
docker build -t "${IMAGE_NAME}" -t "${FULL_IMAGE_NAME}" .

echo "✅ Build successful!"
echo ""
echo "Image tags created:"
echo "  - ${IMAGE_NAME}"
echo "  - ${FULL_IMAGE_NAME}"
echo ""

# Optionally test the image
if [ "${TEST_IMAGE:-true}" = "true" ]; then
    echo "🧪 Testing image..."
    
    # Check if image runs
    echo "Running container to verify it starts..."
    CONTAINER_ID=$(docker run -d --rm -p 8001:8000 "${IMAGE_NAME}")
    
    # Wait a bit for the container to start
    sleep 5
    
    # Check if container is still running
    if docker ps | grep -q "${CONTAINER_ID}"; then
        echo "✅ Container is running"
        
        # Try to hit the health endpoint
        if command -v curl &> /dev/null; then
            echo "Checking health endpoint..."
            if curl -f http://localhost:8001/healthz > /dev/null 2>&1; then
                echo "✅ Health check passed"
            else
                echo "⚠️  Health check failed (container may still be starting)"
            fi
        fi
        
        # Show logs
        echo ""
        echo "Container logs:"
        docker logs "${CONTAINER_ID}" | tail -20
        
        # Stop the test container
        echo ""
        echo "Stopping test container..."
        docker stop "${CONTAINER_ID}" > /dev/null
    else
        echo "❌ Container failed to start"
        docker logs "${CONTAINER_ID}"
        exit 1
    fi
fi

echo ""
echo "✅ Local build test completed successfully!"
echo ""
echo "To test with docker-compose locally, run:"
echo "  docker compose up --build"
echo ""
echo "To push to GHCR (after fixing permissions), run:"
echo "  docker login ghcr.io"
echo "  docker push ${FULL_IMAGE_NAME}"
