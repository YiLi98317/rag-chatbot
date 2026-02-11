FROM python:3.12-slim

WORKDIR /app

# System deps (minimal; keep small for v0)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Pre-download embed model so the image works on ECS without outbound internet (e.g. reingest workflow).
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
RUN mkdir -p /app/.cache && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY src /app/src
COPY api /app/api
COPY scripts /app/scripts

ENV PYTHONPATH=/app/src
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

