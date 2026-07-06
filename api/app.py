from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

# Ensure `src/` is on sys.path so `import chatbot` works when running uvicorn
# directly from the repo root (without requiring PYTHONPATH).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatbot.masanduo import respond_full as masanduo_respond_full
from chatbot.observability.logging import get_logger
from chatbot.service.qa_service import answer_question_stream
from chatbot.settings import get_settings
from chatbot.vectorstore import get_vector_store

from api.models import FeedbackRequest, FeedbackResponse, QaRequest, QaResponse


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
    """马三多工作流入口：业务意图（回收价/算租机/复合/红线等）走 masanduo 引擎，
    闲聊/未命中由引擎内部回落到现有 RAG。前端无需改动。"""
    s = get_settings()
    try:
        session_id = req.session_id or f"api-{uuid.uuid4().hex[:8]}"
        out = masanduo_respond_full(
            req.question,
            session_id=session_id,
            role=req.role or "",
            store_id=req.store_id or "",
            user_id=req.user_id or "",
            settings=s,
        )
        # trace_id 优先用 Langfuse 真实 trace（供前端反馈挂分）；未启用时回落 session_id
        return QaResponse(
            answer=out.answer,
            citations=[],
            trace_id=out.trace_id or session_id,
            sources=out.sources or None,
            confidence=out.confidence,
            need_human=out.need_human,
        )
    except Exception as e:
        logger.exception("qa_error")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/v1/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest):
    """接收前端用户反馈（👍/👎 + 原因），写入 Langfuse score。故障安全：失败返回 ok=false。"""
    try:
        from chatbot.observability.langfuse_tracing import log_feedback

        ok = log_feedback(
            trace_id=req.trace_id,
            value=float(req.value),
            reason=req.reason or "",
            comment=req.comment or "",
        )
        return FeedbackResponse(ok=bool(ok))
    except Exception:
        logger.exception("feedback_error")
        return FeedbackResponse(ok=False)


def _sse_stream_qa(req: QaRequest):
    """Generator that yields SSE lines for streaming QA."""
    s = get_settings()
    debug_traces = bool(getattr(s, "debug_traces", False))
    try:
        for event_type, payload in answer_question_stream(
            req.question,
            top_k=req.top_k,
            filters=req.filters,
            session_id=req.session_id,
            settings=s,
            debug_traces=debug_traces,
        ):
            data = json.dumps(payload, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"
    except Exception as e:
        logger.exception("qa_stream_error")
        yield f"event: error\ndata: {json.dumps({'detail': f'{type(e).__name__}: {e}'})}\n\n"


@app.post("/v1/qa/stream")
def qa_stream(req: QaRequest):
    """Stream QA response as Server-Sent Events. Events: start, chunk, done (or error)."""
    return StreamingResponse(
        _sse_stream_qa(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

