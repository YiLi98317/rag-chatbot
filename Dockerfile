FROM python:3.12-slim

WORKDIR /app

# System deps (minimal; keep small for v0)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Pre-download embed model into a fixed dir so the image works on ECS without outbound internet.
# Do not set HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE here or the build cannot download.
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers
RUN mkdir -p /app/models/bge-m3 && python - << 'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="BAAI/bge-m3",
    local_dir="/app/models/bge-m3",
    local_dir_use_symlinks=False,
)
print("Downloaded BAAI/bge-m3 into /app/models/bge-m3")
PY

# At runtime use cache only (no network).
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV EMBED_MODEL_LOCAL_PATH=/app/models/bge-m3

COPY src /app/src
COPY api /app/api
COPY scripts /app/scripts

ENV PYTHONPATH=/app/src
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

