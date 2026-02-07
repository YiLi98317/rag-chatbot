from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Ensure `src/` is on sys.path so `import chatbot` works when running uvicorn
# directly from the repo root (without requiring PYTHONPATH).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatbot.observability.logging import get_logger
from chatbot.service.qa_service import answer_question
from chatbot.settings import get_settings
from chatbot.vectorstore import get_vector_store

from api.models import QaRequest, QaResponse


logger = get_logger("chatbot.api")

app = FastAPI(title="chatbot-api", version="0.1.0")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    s = get_settings()
    store = get_vector_store(s)
    if not store.healthcheck():
        raise HTTPException(status_code=503, detail="vector_store_unhealthy")

    # Verify collection exists/accessible (do not create it here).
    try:
        if s.vector_provider == "qdrant":
            try:
                ok = bool(store.client.collection_exists(collection_name=s.default_collection))  # type: ignore[attr-defined]
            except Exception:
                ok = True  # best-effort, avoid false-negative across client versions
            if not ok:
                raise HTTPException(status_code=503, detail="collection_missing")
        else:
            # For Milvus server, this is best-effort; for Milvus Lite, existence check is optional.
            try:
                from pymilvus import MilvusClient  # type: ignore

                if getattr(s, "milvus_lite_db", None):
                    client = MilvusClient(s.milvus_lite_db)
                else:
                    client = MilvusClient(uri=s.milvus_uri, db_name=s.milvus_db)
                if not client.has_collection(s.default_collection):
                    raise HTTPException(status_code=503, detail="collection_missing")
            except HTTPException:
                raise
            except Exception:
                # If the check fails due to SDK differences, treat as best-effort.
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ready_check_failed:{type(e).__name__}")

    return {"ok": True}


@app.post("/v1/qa", response_model=QaResponse)
def qa(req: QaRequest):
    s = get_settings()
    debug_traces = bool(getattr(s, "debug_traces", False))
    try:
        result = answer_question(
            req.question,
            top_k=req.top_k,
            filters=req.filters,
            session_id=req.session_id,
            settings=s,
            debug_traces=debug_traces,
        )
        return QaResponse(
            answer=result.answer,
            citations=result.citations,  # pydantic will coerce dict->Citation
            trace_id=result.trace_id,
            retrieval=result.retrieval if debug_traces else None,
        )
    except Exception as e:
        logger.exception("qa_error")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

