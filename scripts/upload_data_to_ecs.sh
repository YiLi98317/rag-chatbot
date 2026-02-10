#!/usr/bin/env bash
set -euo pipefail

# ====== CONFIG ======
# Repo-local source directory (relative to repo root)
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data"
# ECS destination directory (on server)
DEST_DIR="/data/company_docs"

# SSH target - set via env var or edit here
: "${ECS_HOST:?Set ECS_HOST (e.g., export ECS_HOST=47.110.33.91)}"
: "${ECS_USER:=deploy}"
: "${ECS_PORT:=22}"

# Optional: path to SSH key
# export ECS_SSH_KEY=~/.ssh/id_rsa
SSH_KEY_ARG=""
if [[ -n "${ECS_SSH_KEY:-}" ]]; then
  SSH_KEY_ARG="-i ${ECS_SSH_KEY}"
fi

# ====== VALIDATION ======
if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: Source directory does not exist: $SRC_DIR"
  exit 1
fi

echo "Uploading data..."
echo " Source: $SRC_DIR/"
echo "  Target: ${ECS_USER}@${ECS_HOST}:${DEST_DIR}/"

# Ensure dest dir exists on ECS
ssh -p "$ECS_PORT" $SSH_KEY_ARG "${ECS_USER}@${ECS_HOST}" "sudo mkdir -p '${DEST_DIR}' && sudo chown -R ${ECS_USER}:${ECS_USER} '${DEST_DIR}'"

# Rsync (incremental)
rsync -avz --delete \
  -e "ssh -p ${ECS_PORT} ${SSH_KEY_ARG}" \
  "${SRC_DIR}/" "${ECS_USER}@${ECS_HOST}:${DEST_DIR}/"

echo "Done. Remote data now at: ${DEST_DIR}/"
