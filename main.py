import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from analytics.db import AnalyticsDB
from analytics.writer import AnalyticsWriter
from config import settings
from rate_limiter import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize analytics DB on startup, close on shutdown."""
    # Validate required config
    if not settings.app_api_key:
        raise RuntimeError("APP_API_KEY env var is required but not set")
    if not settings.get_api_key("zai-coding"):
        logger.warning(
            "No effective z.ai key (ZAI_CODING_API_KEY/LLM_API_KEY) — "
            "GLM routes degrade to Manifest"
        )
    if not settings.get_api_key("manifest"):
        logger.warning(
            "No effective Manifest key (MANIFEST_API_KEY/LLM_API_KEY) — "
            "non-GLM requests will fail upstream"
        )

    # Startup
    db_path = settings.analytics_db_path
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise RuntimeError(f"ANALYTICS_DB_PATH parent directory is not writable: {parent}")
    db = AnalyticsDB(db_path)
    await db.initialize()
    writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size)
    writer.start()
    app.state.analytics_db = db
    app.state.analytics_writer = writer
    logger.info("LLM Gateway started — analytics DB at %s", db_path)
    yield
    # Shutdown: writer drains BEFORE db closes — reversed order silently drops
    # the drained tail (log_request no-ops on a closed connection)
    await writer.stop()
    await db.close()

app = FastAPI(title="LLM Gateway", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Mount route routers (deferred imports to avoid circular deps)
from routes.chat import router as chat_router  # noqa: E402
from routes.analytics import router as analytics_router, analytics_router as analytics_api_router  # noqa: E402

app.include_router(chat_router)
app.include_router(analytics_router)
app.include_router(analytics_api_router)


@app.get("/playground")
async def playground():
    return FileResponse("static/playground/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
