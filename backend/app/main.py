from __future__ import annotations

import logging
import platform
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import router, settings_api
from app.config import get_settings
from app.db import SessionLocal, checkpoint_wal, init_db
from app.logging_utils import configure_logging
from app.services.artifacts import ProjectStore
from app.services.integrations import create_hotspot_provider
from app.services.pipeline import Pipeline, PipelineRunner, recover_interrupted_topics
from app.webui import mount_webui

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, access_log=settings.access_log)
    init_db()
    with SessionLocal() as session:
        recovered = recover_interrupted_topics(session)
    pipeline = Pipeline(settings)
    runner = PipelineRunner(pipeline)
    app.state.pipeline = pipeline
    app.state.runner = runner
    app.state.store = ProjectStore(settings)
    app.state.hotspot_provider = create_hotspot_provider(settings)
    logger.info(
        "hotstory started",
        extra={
            "provider": (
                f"llm={pipeline.llm_provider.name}:{pipeline.llm_provider.model} "
                f"search={pipeline.search_provider.name} "
                f"crawler={pipeline.crawler_provider.name} "
                f"python={platform.python_version()} "
                f"arch={platform.machine()} "
                f"version={__version__} "
                f"recovered={recovered}"
            )
        },
    )
    try:
        yield
    finally:
        await runner.shutdown()
        try:
            checkpoint_wal()
        except Exception:
            logger.warning("wal checkpoint on shutdown failed")
        logger.info("hotstory stopped")


app = FastAPI(
    title="HotStory API",
    description="热点深度研究、事实核验、时间线与纪录片剧本生成",
    version=__version__,
    lifespan=lifespan,
)
# 2048 以下不压缩：/status 这类高频小响应压了纯粹是浪费事件循环上的 CPU。
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.include_router(router)
app.include_router(settings_api)


# 必须放在所有 API 路由之后：catch-all 会吞掉后面注册的一切。
if not mount_webui(app):

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": "HotStory", "docs": "/docs", "health": "/api/health"}
