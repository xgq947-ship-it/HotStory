from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import router
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.logging_utils import configure_logging
from app.services.artifacts import ProjectStore
from app.services.integrations import create_hotspot_provider
from app.services.pipeline import Pipeline, PipelineRunner, recover_interrupted_topics


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    with SessionLocal() as session:
        recover_interrupted_topics(session)
    pipeline = Pipeline(settings)
    app.state.pipeline = pipeline
    app.state.runner = PipelineRunner(pipeline)
    app.state.store = ProjectStore(settings)
    app.state.hotspot_provider = create_hotspot_provider(settings)
    yield


app = FastAPI(
    title="HotStory API",
    description="热点深度研究、事实核验、时间线与纪录片剧本生成",
    version=__version__,
    lifespan=lifespan,
)
settings = get_settings()
origins = {
    settings.frontend_origin,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "HotStory", "docs": "/docs", "health": "/api/health"}
