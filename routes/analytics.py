"""Analytics REST endpoints and model listing."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from analytics.routing import MODEL_ROUTING
from routes.chat import verify_auth

# Combine all endpoints under one router
router = APIRouter()


def _get_db(request: Request):
    """Safely get analytics DB from app state."""
    db = getattr(request.app.state, "analytics_db", None)
    if not db:
        raise HTTPException(status_code=503, detail="Analytics database not available")
    return db


@router.get("/v1/models")
async def list_models(_auth=Depends(verify_auth)):
    """OpenAI-compatible model listing from routing table."""
    models = []
    for model_name, (provider, _) in MODEL_ROUTING.items():
        models.append({
            "id": model_name,
            "object": "model",
            "owned_by": provider,
        })
    return {"object": "list", "data": models}


analytics_router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@analytics_router.get("/summary")
async def get_summary(
    request: Request,
    since: str | None = Query(None, description="ISO 8601 datetime filter"),
    _auth=Depends(verify_auth),
):
    """Aggregate stats across all requests."""
    db = _get_db(request)
    return await db.get_summary(since)


@analytics_router.get("/models")
async def get_model_stats(
    request: Request,
    since: str | None = Query(None),
    provider: str | None = Query(None),
    _auth=Depends(verify_auth),
):
    """Per-model stats grouped by model name."""
    db = _get_db(request)
    return await db.get_model_stats(since, provider)


@analytics_router.get("/requests")
async def get_requests(
    request: Request,
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auth=Depends(verify_auth),
):
    """Paginated list of recent requests."""
    db = _get_db(request)
    return await db.get_recent(limit, offset, since)
