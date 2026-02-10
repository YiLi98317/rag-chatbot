#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Load ECS_* from .env if present (so you don't need to export)
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

# ====== CONFIG ======
# Repo-local source: only data/target/* (not all of data/)
SRC_DIR="${REPO_ROOT}/data/target"
# ECS destination directory (on server)
DEST_DIR="/data/company_docs"

# SSH target - set via env var or .env
: "${ECS_HOST:?Set ECS_HOST in .env or export ECS_HOST=your-ecs-ip}"
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

# Upload via tar over SSH (rsync not required on server)
tar cf - -C "${SRC_DIR}" . | ssh -p "$ECS_PORT" $SSH_KEY_ARG "${ECS_USER}@${ECS_HOST}" "rm -rf ${DEST_DIR}/* ${DEST_DIR}/.[!.]* 2>/dev/null; mkdir -p ${DEST_DIR} && tar xf - -C ${DEST_DIR}"

echo "Done. Remote data now at: ${DEST_DIR}/"
