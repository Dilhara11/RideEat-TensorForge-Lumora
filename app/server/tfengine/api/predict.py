"""`POST /predict` and `POST /predict/batch` (API key required)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..schemas import BatchResponseDoc, PredictRequestDoc, PredictResponseDoc, error_responses
from .deps import get_engine, require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])

# Request bodies are read manually (see JsonBodyReader), so describe them for /docs explicitly.
_TICKET_SCHEMA = PredictRequestDoc.model_json_schema()
_PREDICT_BODY = {"requestBody": {"required": True, "content": {"application/json": {"schema": _TICKET_SCHEMA}}}}
_BATCH_BODY = {"requestBody": {"required": True, "content": {"application/json": {"schema": {
    "type": "object", "required": ["tickets"],
    "properties": {"tickets": {"type": "array", "minItems": 1, "maxItems": 100, "items": _TICKET_SCHEMA}},
}}}}}


@router.post("/predict", tags=["Core"], response_model=PredictResponseDoc, openapi_extra=_PREDICT_BODY,
             responses=error_responses(400, 401, 413, 415, 422))
async def predict(request: Request) -> JSONResponse:
    """Classify one ticket.

    Example: {"channel": "chat", "text": "bro mage order eka hour ekakata late, refund ekak denna"}
          -> {"category": "delivery_delay", "secondary_category": "payment_refund",
              "team": "Delivery Operations", "is_urgent": false, "confidence": 0.82, "model_version": "v1.0-..."}
    """
    engine = get_engine(request)
    body = await engine.body_reader.read(request, engine.settings.max_predict_bytes)
    ticket = engine.validator.single(body)
    [prediction] = await engine.inference.predict([ticket])
    return JSONResponse(prediction)


@router.post("/predict/batch", tags=["Evaluation"], response_model=BatchResponseDoc, openapi_extra=_BATCH_BODY,
             responses=error_responses(400, 401, 413, 415, 422))
async def predict_batch(request: Request) -> JSONResponse:
    """Classify 1–100 tickets synchronously; predictions[i] corresponds to tickets[i].

    Example: {"tickets": [{"ticket_id": "A", ...}, {"ticket_id": "B", ...}]}
          -> {"predictions": [{"ticket_id": "A", ...}, {"ticket_id": "B", ...}],
              "meta": {"count": 2, "model_version": "v1.0-...", "processing_time_ms": 143}}
    """
    engine = get_engine(request)
    t0 = time.perf_counter()
    body = await engine.body_reader.read(request, engine.settings.max_batch_bytes)
    tickets = engine.validator.many(body, max_items=engine.settings.max_batch_items)
    predictions = await engine.inference.predict(tickets)
    meta = {
        "count": len(predictions),
        "model_version": engine.inference.model_version,
        "processing_time_ms": int((time.perf_counter() - t0) * 1000),
    }
    return JSONResponse({"predictions": predictions, "meta": meta})
