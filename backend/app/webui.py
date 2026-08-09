"""托管前端静态导出产物。

打包后前后端同源：Next.js 用 output: "export" 产出纯静态文件，
由 FastAPI 直接发出去，运行时不再需要 Node 进程。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


def frontend_dir() -> Path | None:
    """打包时前端产物放在应用内；开发时在 frontend/out。"""
    candidates = [
        PROJECT_ROOT / "frontend" / "out",
        PROJECT_ROOT / "webui",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_webui(app: FastAPI) -> bool:
    directory = frontend_dir()
    if directory is None:
        logger.info("未找到前端静态产物，只提供 API；开发模式请用 next dev")
        return False

    app.mount(
        "/_next",
        StaticFiles(directory=directory / "_next"),
        name="next-assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> Response:
        # /topic/ 这类导出目录取其 index.html；其余落到根 index.html。
        relative = full_path.strip("/")
        # 打错的 API 路径必须还是 404，否则前端会拿到一坨 HTML 当 JSON 解析。
        if relative.startswith(("api/", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not Found")
        if relative:
            direct = directory / relative
            if direct.is_file():
                return FileResponse(direct)
            nested = directory / relative / "index.html"
            if nested.is_file():
                return FileResponse(nested)
            html = directory / f"{relative}.html"
            if html.is_file():
                return FileResponse(html)
        return FileResponse(directory / "index.html")

    logger.info("已挂载前端静态产物", extra={"step": str(directory)})
    return True
