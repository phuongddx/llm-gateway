import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analytics.db import AnalyticsDB
from config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize analytics DB on startup, close on shutdown."""
    # Startup
    db_path = settings.analytics_db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = AnalyticsDB(db_path)
    await db.initialize()
    app.state.analytics_db = db
    logger.info("LLM Gateway started — analytics DB at %s", db_path)
    yield
    # Shutdown
    await db.close()


app = FastAPI(title="LLM Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
