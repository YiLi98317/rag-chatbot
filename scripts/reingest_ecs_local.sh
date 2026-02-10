#!/usr/bin/env bash
# Run ingestion on ECS from your machine (SSH + docker run). Same as the GitHub Action but local.
# Usage: ./scripts/reingest_ecs_local.sh [incremental|full]
# Requires: ECS_HOST, ECS_USER, ECS_PASSWORD (or ECS_SSH_KEY), RAG_IMAGE in .env or environment.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

: "${ECS_HOST:?Set ECS_HOST in .env or export}"
: "${ECS_USER:=deploy}"
: "${ECS_PORT:=22}"
: "${RAG_IMAGE:?Set RAG_IMAGE in .env (e.g. ghcr.io/owner/rag-chatbot:latest)}"

DATA_PATH="${DATA_PATH:-/data/company_docs}"
MODE="${1:-incremental}"

RECREATE=""
if [[ "${MODE}" == "full" ]]; then
  RECREATE="--recreate"
fi

SSH_KEY_ARG=""
if [[ -n "${ECS_SSH_KEY:-}" ]]; then
  SSH_KEY_ARG="-i ${ECS_SSH_KEY}"
fi

echo "Re-ingesting on ECS (mode=${MODE}) from ${DATA_PATH}..."
ssh -p "$ECS_PORT" $SSH_KEY_ARG "${ECS_USER}@${ECS_HOST}" "set -e
  test -d '${DATA_PATH}' || { echo 'ERROR: Directory not found: ${DATA_PATH}'; exit 1; }
  NETWORK=\$(docker inspect rag_api --format '{{range \$k, \$v := .NetworkSettings.Networks}}{\$k}{{end}}' 2>/dev/null || echo 'rag_default')
  docker run --rm --network \${NETWORK} \
    --env-file /opt/rag/.env \
    -e DATA_DIR=/data \
    -v '${DATA_PATH}:/data:ro' \
    '${RAG_IMAGE}' \
    python -m chatbot.cli.ingest ${RECREATE}
"
echo "Done."
