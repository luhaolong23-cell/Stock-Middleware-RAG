from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_chat import router as chat_router
from app.api.routes_docs import router as docs_router
from app.core.config import settings
from app.core.database import initialize_database
from app.core.logger import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    initialize_database()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/api-docs",
    redoc_url="/api-redoc",
)
app.include_router(docs_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}
