"""ChargePlus — Python ML Online Inference Service.

Standalone FastAPI HTTP microservice exposing real-time ML inference and model status.
Reuses the verified backend.ml modules, registry, and data maturity gates.

Endpoints:
    GET  /health  — Service liveness probe
    GET  /ready   — Model registry readiness probe & data maturity status
    POST /predict — Authenticated busy-probability prediction
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.ml.gates import DEFAULT_GATE_CONFIG, MLUnavailableReason
from backend.ml.inference import InferenceService, PredictionResult
from backend.ml.registry import ModelRegistry

logger = logging.getLogger("chargeplus.ml.service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Environment configuration
ARTIFACT_DIR = os.getenv("ML_ARTIFACT_DIR", "backend/ml/artifacts")
API_SECRET = os.getenv("PYTHON_API_SECRET", os.getenv("INTERNAL_SERVICE_SECRET", ""))

# App definition
app = FastAPI(
    title="ChargePlus ML Inference Service",
    version="1.0.0",
    docs_url=None,  # Disabled in production for security
    redoc_url=None,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    features: dict[str, Any] = Field(..., description="Feature map (hour_of_day, day_of_week, etc.)")
    latest_observation_at: Optional[str] = Field(None, description="ISO-8601 timestamp of newest observation")
    as_of: Optional[str] = Field(None, description="Optional evaluation reference time")


def get_inference_service() -> InferenceService:
    registry = ModelRegistry(ARTIFACT_DIR)
    return InferenceService(registry, gate_config=DEFAULT_GATE_CONFIG)


def verify_internal_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Enforce shared bearer token if configured in environment."""
    if not API_SECRET:
        # Development mode without shared secret configured
        return True
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "Missing Authorization header"},
        )
    token = authorization.replace("Bearer ", "").strip()
    if token != API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "Invalid service authentication token"},
        )
    return True


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    # Cap request body at 64KB to prevent memory exhaustion
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 65_536:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"success": False, "error": "Request body too large (max 64KB)"},
        )
    return await call_next(request)


@app.get("/health")
def health():
    """Liveness probe: verifies the HTTP service process is running."""
    return {
        "status": "healthy",
        "service": "chargeplus-ml-inference",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def readiness(service: InferenceService = Depends(get_inference_service)):
    """Readiness probe: reports model registry status and whether an approved model is ready."""
    registry = ModelRegistry(ARTIFACT_DIR)
    active = registry.get_active()
    return {
        "ready": active is not None,
        "artifact_dir": ARTIFACT_DIR,
        "active_model": active,
        "gate_status": "COLD" if active is None else "READY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/predict")
def predict(
    payload: PredictRequest,
    _auth: bool = Depends(verify_internal_auth),
    service: InferenceService = Depends(get_inference_service),
):
    """Executes busy-probability prediction using the registry-approved model."""
    as_of = None
    if payload.as_of:
        try:
            as_of = datetime.fromisoformat(payload.as_of.replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    result: PredictionResult = service.predict(
        payload.features,
        latest_observation_at=payload.latest_observation_at,
        as_of=as_of,
    )
    res_dict = result.to_dict()

    # Honest HTTP status: unavailable prediction is HTTP 200 with success=false (valid answer)
    return JSONResponse(content=res_dict, status_code=status.HTTP_200_OK)


def run_cli():
    global ARTIFACT_DIR
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="ChargePlus ML Inference Service")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--artifact-dir", default=ARTIFACT_DIR, help="Model artifact directory")
    args = parser.parse_args()

    ARTIFACT_DIR = args.artifact_dir

    logger.info("Starting ChargePlus ML service on %s:%d (artifacts: %s)", args.host, args.port, ARTIFACT_DIR)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    run_cli()
