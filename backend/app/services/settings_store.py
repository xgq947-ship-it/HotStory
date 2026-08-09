"""本机设置存储。

优先级：设置界面手动填写 > 环境变量 / .env > 代码默认值。
手动填写的值存在 data/config/settings.json（仅属主可读写），
密钥只以掩码形式返回给前端，永远不回传明文。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr

from app.config import PROJECT_ROOT, Settings

logger = logging.getLogger(__name__)

FieldKind = Literal["text", "password", "number", "boolean", "select"]


@dataclass(frozen=True)
class SettingField:
    name: str
    label: str
    group: str
    kind: FieldKind = "text"
    secret: bool = False
    options: tuple[str, ...] = ()
    help: str = ""
    placeholder: str = ""
    # 引擎在模块导入时就建好了，这些改完必须重启才生效
    restart_required: bool = False
    editable: bool = True


SETTING_FIELDS: tuple[SettingField, ...] = (
    # —— 模型 ——
    SettingField(
        "llm_provider",
        "LLM Provider",
        "model",
        kind="select",
        options=("deepseek", "codex_cli", "openai", "anthropic", "openai_compatible", "mock"),
        help="codex_cli 使用本机已登录的 Codex CLI，不需要 API Key。",
    ),
    SettingField("llm_model", "模型名称", "model", placeholder="deepseek-v4-flash"),
    SettingField(
        "llm_base_url", "Base URL", "model", placeholder="https://api.deepseek.com"
    ),
    SettingField("deepseek_api_key", "DeepSeek API Key", "model", kind="password", secret=True),
    SettingField("anthropic_api_key", "Anthropic API Key", "model", kind="password", secret=True),
    SettingField(
        "llm_api_key",
        "通用 API Key",
        "model",
        kind="password",
        secret=True,
        help="OpenAI / OpenAI 兼容 Provider 使用；DeepSeek 与 Anthropic 优先用上面各自的 Key。",
    ),
    SettingField("deepseek_thinking_enabled", "启用深度思考", "model", kind="boolean"),
    SettingField(
        "deepseek_reasoning_effort",
        "思考强度",
        "model",
        kind="select",
        options=("high", "max"),
    ),
    SettingField(
        "production_deepseek_reasoning_effort",
        "影视包思考强度",
        "model",
        kind="select",
        options=("high", "max"),
    ),
    # —— Codex CLI ——
    SettingField(
        "codex_cli_path",
        "Codex CLI 路径",
        "codex",
        placeholder="codex",
        help="留空使用 codex；可点击“自动检测”从本机常见安装位置查找。",
    ),
    SettingField("codex_cli_model", "Codex 模型", "codex", placeholder="留空使用 CLI 默认模型"),
    SettingField("codex_cli_timeout_seconds", "Codex 超时（秒）", "codex", kind="number"),
    # —— 搜索与抓取 ——
    SettingField(
        "search_provider",
        "搜索 Provider",
        "research",
        kind="select",
        options=("duckduckgo", "tavily", "brave", "serper"),
        help="duckduckgo 不需要 Key，但容易限流。",
    ),
    SettingField("search_api_key", "搜索 API Key", "research", kind="password", secret=True),
    SettingField(
        "crawler_provider",
        "抓取 Provider",
        "research",
        kind="select",
        options=("auto", "simple_http", "crawl4ai"),
    ),
    SettingField(
        "hotspot_provider",
        "热榜来源",
        "research",
        kind="select",
        options=("auto", "dailyhot", "trendradar"),
    ),
    SettingField("dailyhot_api_base_url", "DailyHot API", "research"),
    SettingField("trendradar_api_base_url", "TrendRadar API", "research"),
    # —— 质量阈值 ——
    SettingField("min_valid_sources", "最少有效来源", "quality", kind="number"),
    SettingField("min_verified_facts", "最少已核验事实", "quality", kind="number"),
    SettingField("min_personal_cases", "最少个人案例", "quality", kind="number"),
    SettingField("min_key_data", "最少关键数据", "quality", kind="number"),
    SettingField("max_search_results", "最多搜索结果", "quality", kind="number"),
    SettingField("search_results_per_query", "每条查询结果数", "quality", kind="number"),
    # —— 性能 ——
    SettingField("llm_timeout_seconds", "LLM 超时（秒）", "performance", kind="number"),
    SettingField("llm_max_retries", "LLM 重试次数", "performance", kind="number"),
    SettingField("llm_max_output_tokens", "LLM 最大输出 token", "performance", kind="number"),
    SettingField("llm_concurrency", "LLM 并发", "performance", kind="number"),
    SettingField("fetch_concurrency", "抓取并发", "performance", kind="number"),
    SettingField("request_timeout_seconds", "抓取超时（秒）", "performance", kind="number"),
    SettingField("max_retries", "抓取重试次数", "performance", kind="number"),
    SettingField(
        "max_concurrent_pipelines",
        "同时运行的任务数",
        "performance",
        kind="number",
        help="本地建议保持 1；两条管道会让所有开销翻倍。",
    ),
    SettingField("search_query_pause_seconds", "搜索间隔（秒）", "performance", kind="number"),
    # —— 维护 ——
    SettingField("llm_raw_retention", "保留原始响应数", "maintenance", kind="number"),
    SettingField(
        "log_level",
        "日志级别",
        "maintenance",
        kind="select",
        options=("DEBUG", "INFO", "WARNING", "ERROR"),
        restart_required=True,
    ),
    SettingField(
        "access_log",
        "记录 HTTP 访问日志",
        "maintenance",
        kind="boolean",
        restart_required=True,
    ),
    SettingField(
        "sqlite_busy_timeout_ms",
        "SQLite 忙等待（毫秒）",
        "maintenance",
        kind="number",
        restart_required=True,
        editable=False,
        help="数据库引擎在进程启动时建立，修改需要重启应用。",
    ),
)

GROUP_LABELS: dict[str, str] = {
    "model": "模型与密钥",
    "codex": "Codex CLI",
    "research": "搜索与抓取",
    "quality": "质量阈值",
    "performance": "性能",
    "maintenance": "维护",
}

FIELDS_BY_NAME = {item.name: item for item in SETTING_FIELDS}
EDITABLE_FIELDS = {item.name for item in SETTING_FIELDS if item.editable}


def config_path() -> Path:
    """不能依赖 Settings：这个文件本身要在构造 Settings 之前读出来。"""
    raw = os.getenv("DATA_DIR", "").strip()
    data_dir = Path(raw).expanduser() if raw else PROJECT_ROOT / "data"
    return data_dir / "config" / "settings.json"


def load_overrides() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("读取本机设置失败，忽略覆盖值：%s", error)
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        name: value
        for name, value in parsed.items()
        if name in FIELDS_BY_NAME and value not in (None, "")
    }


def save_overrides(values: dict[str, Any], clear: list[str] | None = None) -> dict[str, Any]:
    current = load_overrides()
    for name, value in values.items():
        if name not in EDITABLE_FIELDS:
            continue
        if isinstance(value, str):
            value = value.strip()
        if value in (None, ""):
            continue
        current[name] = value
    for name in clear or []:
        current.pop(name, None)

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(current, ensure_ascii=False, indent=2)
    # 这里面是明文密钥，只允许属主读写。
    path.write_text(payload + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - Windows 上没有 POSIX 权限位
        pass
    return current


def env_files() -> tuple[str, ...]:
    """打包后 PROJECT_ROOT 在 .app 内部，那里不该放密钥，也会被覆盖安装抹掉。
    所以额外读取数据目录旁边的 .env（~/Library/Application Support/HotStory/.env）。
    列表越靠后优先级越高。"""
    files = [str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / "backend" / ".env")]
    raw = os.getenv("DATA_DIR", "").strip()
    if raw:
        files.append(str(Path(raw).expanduser().parent / ".env"))
    return tuple(files)


def build_settings() -> Settings:
    """init 参数在 pydantic-settings 里优先级最高，正好实现 手动 > 环境变量 > 默认。"""
    overrides = load_overrides()
    try:
        return Settings(_env_file=env_files(), **overrides)
    except Exception as error:
        logger.warning("本机设置无效，已回退到环境变量配置：%s", error)
        return Settings(_env_file=env_files())


def _field_default(name: str):
    info = Settings.model_fields.get(name)
    if info is None:
        return None
    return info.get_default(call_default_factory=True)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return f"••••••••{value[-4:]}" if len(value) > 4 else "••••••••"


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


@dataclass
class FieldState:
    name: str
    label: str
    group: str
    kind: str
    secret: bool
    options: list[str] = field(default_factory=list)
    help: str = ""
    placeholder: str = ""
    restart_required: bool = False
    editable: bool = True
    value: Any = ""
    configured: bool = False
    source: str = "default"


def describe_settings(settings: Settings, overrides: dict[str, Any] | None = None) -> list[dict]:
    overrides = load_overrides() if overrides is None else overrides
    described: list[dict] = []
    for item in SETTING_FIELDS:
        raw = getattr(settings, item.name, None)
        plain = _plain(raw)
        manual = item.name in overrides
        # .env 是被 pydantic 直接读走的，不进 os.environ，所以不能只看环境变量：
        # 值和代码默认值不同就说明来自 .env 或环境变量。
        if manual:
            source = "manual"
        elif os.getenv(item.name.upper()):
            source = "env"
        elif plain != _plain(_field_default(item.name)):
            source = "env_file"
        else:
            source = "default"
        state = FieldState(
            name=item.name,
            label=item.label,
            group=item.group,
            kind=item.kind,
            secret=item.secret,
            options=list(item.options),
            help=item.help,
            placeholder=item.placeholder,
            restart_required=item.restart_required,
            editable=item.editable,
            configured=bool(plain),
            source=source,
        )
        if item.secret:
            # 明文永远不出后端。
            state.value = mask_secret(plain)
        elif item.kind == "boolean":
            state.value = bool(raw)
        elif item.kind == "number":
            state.value = raw
        else:
            state.value = plain
        described.append(state.__dict__)
    return described


__all__ = [
    "GROUP_LABELS",
    "SETTING_FIELDS",
    "build_settings",
    "config_path",
    "describe_settings",
    "load_overrides",
    "mask_secret",
    "save_overrides",
]
