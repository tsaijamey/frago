#!/bin/sh
# Test install.sh in a clean Docker container
#
# Usage:
#   ./scripts/test-docker.sh              # Test with Ubuntu
#   ./scripts/test-docker.sh debian       # Test with Debian
#   ./scripts/test-docker.sh alpine       # Test with Alpine (may have issues)
#
# This creates a completely isolated environment to test the install script.

set -e

IMAGE="${1:-ubuntu:latest}"

echo ""
echo "━━━ Docker Install Test ━━━"
echo ""
echo "Image: $IMAGE"
echo ""

# For local testing, mount the install.sh from current directory
# For production testing, use curl from URL

if [ -f "install.sh" ]; then
    echo "Testing local install.sh..."
    docker run -it --rm \
        -v "$(pwd)/install.sh:/tmp/install.sh:ro" \
        "$IMAGE" \
        sh -c '
            # Install curl if needed (for Alpine)
            if command -v apk >/dev/null 2>&1; then
                apk add --no-cache curl bash >/dev/null 2>&1
            elif command -v apt-get >/dev/null 2>&1; then
                apt-get update >/dev/null 2>&1 && apt-get install -y curl >/dev/null 2>&1
            fi

            echo "Running install.sh..."
            sh /tmp/install.sh
        '
else
    echo "Testing from URL (production)..."
    docker run -it --rm \
        "$IMAGE" \
        sh -c '
            # Install curl
            if command -v apk >/dev/null 2>&1; then
                apk add --no-cache curl bash
            elif command -v apt-get >/dev/null 2>&1; then
                apt-get update && apt-get install -y curl
            fi

            curl -fsSL https://frago.ai/install.sh | sh
        '
fi
