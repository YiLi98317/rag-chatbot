#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SMOKE_BASE_URL:-http://localhost:8000}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-120}"
INTERVAL_SECONDS="${SMOKE_INTERVAL_SECONDS:-2}"

READY_URL="${BASE_URL%/}/readyz"
QA_URL="${BASE_URL%/}/v1/qa"

echo "SMOKE: base_url=${BASE_URL}"

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
while true; do
  now="$(date +%s)"
  if (( now > deadline )); then
    echo "SMOKE_FAIL: /readyz did not become ready within ${TIMEOUT_SECONDS}s" >&2
    exit 1
  fi

  code="$(curl -sS -o /dev/null -w '%{http_code}' "${READY_URL}" || true)"
  if [[ "${code}" == "200" ]]; then
    echo "SMOKE: /readyz OK"
    break
  fi
  echo "SMOKE: waiting for /readyz (status=${code})..."
  sleep "${INTERVAL_SECONDS}"
done

payload='{"question":"下单流程是什么？","top_k":5}'
echo "SMOKE: POST /v1/qa"

tmp="$(mktemp)"
http_code="$(curl -sS -o "${tmp}" -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  --data "${payload}" \
  "${QA_URL}" || true)"

if [[ "${http_code}" != "200" ]]; then
  echo "SMOKE_FAIL: /v1/qa returned status=${http_code}" >&2
  echo "Response body:" >&2
  cat "${tmp}" >&2 || true
  rm -f "${tmp}" || true
  exit 1
fi

SMOKE_BODY_PATH="${tmp}" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["SMOKE_BODY_PATH"])
raw = path.read_text(encoding="utf-8", errors="replace")
try:
    obj = json.loads(raw)
except Exception as e:
    raise SystemExit(f"SMOKE_FAIL: response is not JSON ({type(e).__name__}): {e}\nBody={raw[:500]}")

missing = [k for k in ("answer", "citations", "trace_id") if k not in obj]
if missing:
    raise SystemExit(f"SMOKE_FAIL: missing keys: {missing}. Body={raw[:500]}")

if not isinstance(obj.get("citations"), list):
    raise SystemExit(f"SMOKE_FAIL: citations is not a list. Body={raw[:500]}")

print("SMOKE_OK:", json.dumps({k: obj.get(k) for k in ('trace_id',)}, ensure_ascii=False))
PY

rm -f "${tmp}" || true
echo "SMOKE_OK"
