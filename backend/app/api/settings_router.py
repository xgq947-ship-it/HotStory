from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app import __version__
from app.config import reload_settings
from app.schemas.domain import (
    CodexDetectRequest,
    CodexStatusResponse,
    ReleaseInfo,
    SettingsResponse,
    SettingsUpdateRequest,
    UpdateCheckResponse,
)
from app.services.artifacts import ProjectStore
from app.services.codex_cli_paths import describe_codex
from app.services.integrations import create_hotspot_provider
from app.services.pipeline import Pipeline, PipelineRunner
from app.services.settings_store import (
    GROUP_LABELS,
    describe_settings,
    save_overrides,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
RELEASES_API = "https://api.github.com/repos/xgq947-ship-it/HotStory/releases"
REPOSITORY_URL = "https://github.com/xgq947-ship-it/HotStory"


def local_only(request: Request) -> None:
    """设置接口会经手明文密钥，只允许本机工作台访问。
    参考 AI 画布 server/routes/settings.js 的同源限制。"""
    origin = request.headers.get("origin")
    if not origin:
        return
    hostname = urlsplit(origin).hostname or ""
    if hostname in LOCAL_HOSTS:
        return
    raise HTTPException(status_code=403, detail="设置只允许从本机工作台访问")


def _current(request: Request) -> SettingsResponse:
    settings = request.app.state.pipeline.settings
    return SettingsResponse(
        groups=GROUP_LABELS,
        fields=describe_settings(settings),
        version=__version__,
        repository_url=REPOSITORY_URL,
    )


@router.get("", response_model=SettingsResponse)
def read_settings(
    request: Request, _guard: None = Depends(local_only)
) -> SettingsResponse:
    return _current(request)


@router.post("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    _guard: None = Depends(local_only),
) -> SettingsResponse:
    runner: PipelineRunner = request.app.state.runner
    active = runner.active_topic_ids()
    if active:
        # 换 Provider 会关掉正在跑的任务手里的 httpx 客户端。
        raise HTTPException(
            status_code=409, detail=f"有任务正在运行（{active[0]}），请等它结束再保存设置。"
        )

    values: dict[str, Any] = dict(payload.values)
    try:
        save_overrides(values, payload.clear)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"设置写入失败：{error}") from error

    settings = reload_settings()
    old_pipeline: Pipeline = request.app.state.pipeline
    try:
        pipeline = Pipeline(settings)
    except Exception as error:
        # 配置本身非法（比如不支持的 Provider）：回滚到旧管道，把原因告诉用户。
        logger.warning("按新设置重建管道失败：%s", error)
        raise HTTPException(status_code=400, detail=f"设置无法生效：{error}") from error

    request.app.state.pipeline = pipeline
    runner.pipeline = pipeline
    request.app.state.store = ProjectStore(settings)
    request.app.state.hotspot_provider = create_hotspot_provider(settings)
    await old_pipeline.aclose()
    logger.info(
        "settings reloaded",
        extra={
            "provider": (
                f"llm={pipeline.llm_provider.name} search={pipeline.search_provider.name}"
            )
        },
    )
    return _current(request)


@router.post("/codex/detect", response_model=CodexStatusResponse)
def detect_codex(
    payload: CodexDetectRequest,
    _guard: None = Depends(local_only),
) -> CodexStatusResponse:
    return CodexStatusResponse(**describe_codex(payload.path))


@router.get("/updates", response_model=UpdateCheckResponse)
async def check_updates(_guard: None = Depends(local_only)) -> UpdateCheckResponse:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            response = await client.get(
                RELEASES_API,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as error:
        return UpdateCheckResponse(
            current_version=__version__,
            error=f"无法连接 GitHub Releases：{error}",
        )

    releases = [
        ReleaseInfo(
            tag_name=item.get("tag_name", ""),
            name=item.get("name") or item.get("tag_name", ""),
            html_url=item.get("html_url", REPOSITORY_URL),
            body=item.get("body") or "",
            published_at=item.get("published_at") or "",
        )
        for item in payload
        if isinstance(item, dict) and not item.get("draft") and not item.get("prerelease")
    ]
    latest = releases[0] if releases else None
    # 仓库还没有任何 Release 时是空列表，不是错误——这条路径必须报"已是最新"。
    return UpdateCheckResponse(
        current_version=__version__,
        latest=latest,
        update_available=bool(latest and _newer(latest.tag_name, __version__)),
        releases=releases[:10],
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV").split("-")[0]
    parts: list[int] = []
    for chunk in cleaned.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) or (0,)


def _newer(candidate: str, current: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)
