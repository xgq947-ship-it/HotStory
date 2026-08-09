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
    # (字段名, "值1|值2")：只有当那个字段取到其中一个值时才显示本项
    depends_on: tuple[str, str] | None = None


SETTING_FIELDS: tuple[SettingField, ...] = (
    # 只保留真正需要用户决定的东西。其余按默认值跑，不进设置界面——
    # 每多一个可填项，用户就多一次犹豫。
    SettingField(
        "llm_provider",
        "生成模型",
        "model",
        kind="select",
        options=("deepseek", "codex_cli"),
        help="DeepSeek 需要 API Key；Codex 用本机已登录的 Codex CLI，不花钱。",
    ),
    SettingField(
        "deepseek_api_key",
        "DeepSeek API Key",
        "model",
        kind="password",
        secret=True,
        depends_on=("llm_provider", "deepseek"),
        help="在 platform.deepseek.com 创建。",
    ),
    SettingField(
        "codex_cli_path",
        "Codex CLI 路径",
        "model",
        placeholder="留空自动查找",
        depends_on=("llm_provider", "codex_cli"),
        help="留空会自动查找；找不到时点下面的按钮检测。",
    ),
    SettingField(
        "search_provider",
        "搜索来源",
        "research",
        kind="select",
        options=("duckduckgo", "tavily", "brave", "serper"),
        help="DuckDuckGo 免费但容易限流；换成其他的需要填 Key。",
    ),
    SettingField(
        "search_api_key",
        "搜索 API Key",
        "research",
        kind="password",
        secret=True,
        depends_on=("search_provider", "tavily|brave|serper"),
    ),
)

GROUP_LABELS: dict[str, str] = {
    "model": "生成模型",
    "research": "资料来源",
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
    depends_on: list[str] | None = None
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
            depends_on=list(item.depends_on) if item.depends_on else None,
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
