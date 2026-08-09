from __future__ import annotations

import json
import os

import pytest
from fastapi import HTTPException

from app.api.settings_router import _newer, check_updates, local_only, update_settings
from app.config import Settings
from app.schemas.domain import SettingsUpdateRequest
from app.services import settings_store
from app.services.codex_cli_paths import resolve_codex_bin


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_save_and_load_roundtrip(config_dir) -> None:
    settings_store.save_overrides({"llm_provider": "  codex_cli  ", "search_provider": "tavily"})
    assert settings_store.load_overrides() == {
        "llm_provider": "codex_cli",
        "search_provider": "tavily",
    }


def test_config_file_is_owner_only(config_dir) -> None:
    settings_store.save_overrides({"llm_provider": "codex_cli"})
    path = settings_store.config_path()
    assert path.stat().st_mode & 0o777 == 0o600, "密钥文件不能对同机其他用户可读"


def test_unknown_and_readonly_fields_are_rejected(config_dir) -> None:
    # llm_concurrency 等参数已经不进设置界面了，只按默认值跑
    settings_store.save_overrides(
        {"llm_provider": "codex_cli", "not_a_field": "x", "llm_concurrency": 8}
    )
    stored = json.loads(settings_store.config_path().read_text(encoding="utf-8"))
    assert stored == {"llm_provider": "codex_cli"}


def test_clear_removes_override(config_dir) -> None:
    settings_store.save_overrides({"deepseek_api_key": "sk-secret-value"})
    settings_store.save_overrides({}, clear=["deepseek_api_key"])
    assert "deepseek_api_key" not in settings_store.load_overrides()


def test_manual_value_beats_environment(config_dir, monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    settings_store.save_overrides({"search_provider": "tavily"})
    assert settings_store.build_settings().search_provider == "tavily"


def test_environment_used_when_no_override(config_dir, monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    assert settings_store.build_settings().search_provider == "brave"


def test_secrets_are_masked_and_never_returned_plain(config_dir) -> None:
    settings_store.save_overrides({"deepseek_api_key": "sk-abcdefgh1234"})
    settings = settings_store.build_settings()
    described = settings_store.describe_settings(settings)
    row = next(item for item in described if item["name"] == "deepseek_api_key")
    assert row["value"] == "••••••••1234"
    assert row["configured"] is True
    assert "sk-abcdefgh1234" not in json.dumps(described, ensure_ascii=False)


def test_broken_config_file_falls_back_instead_of_crashing(config_dir) -> None:
    path = settings_store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert settings_store.load_overrides() == {}
    assert isinstance(settings_store.build_settings(), Settings)


def test_invalid_override_value_falls_back(config_dir) -> None:
    # 非法值不能让整个应用起不来
    settings_store.config_path().parent.mkdir(parents=True, exist_ok=True)
    settings_store.config_path().write_text(
        json.dumps({"search_provider": "duckduckgo", "llm_provider": "deepseek"}),
        encoding="utf-8",
    )
    assert settings_store.build_settings().llm_provider == "deepseek"


def test_codex_resolution_finds_non_path_install(tmp_path) -> None:
    fake = tmp_path / ".local" / "bin" / "codex"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    resolved = resolve_codex_bin("", {"HOME": str(tmp_path), "PATH": "/nonexistent"})
    assert resolved == str(fake), "装在 ~/.local/bin 的 codex 不能被判成没装"


def test_codex_resolution_never_returns_a_nonexistent_path(tmp_path) -> None:
    # 本机可能真的装了 ChatGPT.app 里的 codex，所以不能断言一定为空；
    # 要保证的是：返回值要么为空，要么真的存在且可执行。
    resolved = resolve_codex_bin("", {"HOME": str(tmp_path), "PATH": "/nonexistent"})
    if resolved:
        assert os.access(resolved, os.X_OK)


class _Request:
    def __init__(self, origin: str | None) -> None:
        self.headers = {"origin": origin} if origin else {}


def test_settings_endpoints_reject_remote_origins() -> None:
    local_only(_Request("http://127.0.0.1:63115"))  # type: ignore[arg-type]
    local_only(_Request("tauri://localhost"))  # type: ignore[arg-type]
    local_only(_Request(None))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as error:
        local_only(_Request("https://evil.example.com"))  # type: ignore[arg-type]
    assert error.value.status_code == 403


def test_version_comparison() -> None:
    assert _newer("v0.2.0", "0.1.0") is True
    assert _newer("0.1.0", "0.1.0") is False
    assert _newer("v0.1.0", "0.2.0") is False


@pytest.mark.asyncio
async def test_saving_settings_is_refused_while_a_task_runs(config_dir, test_settings) -> None:
    class Runner:
        def active_topic_ids(self) -> list[str]:
            return ["topic_running"]

    class State:
        pass

    class App:
        state = State()

    class Request:
        headers: dict[str, str] = {}
        app = App()

    Request.app.state.runner = Runner()
    Request.app.state.pipeline = type("P", (), {"settings": test_settings})()

    with pytest.raises(HTTPException) as error:
        await update_settings(
            SettingsUpdateRequest(values={"llm_provider": "codex_cli"}),
            Request(),  # type: ignore[arg-type]
        )
    assert error.value.status_code == 409
    # 关键：被拒绝时不能已经写盘
    assert settings_store.load_overrides() == {}


@pytest.mark.asyncio
async def test_update_check_reports_current_when_no_releases(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> list:
            return []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    import app.api.settings_router as module

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: FakeClient())
    payload = await check_updates()
    assert payload.update_available is False
    assert payload.error == "", "空的 Release 列表是'已是最新'，不是错误"


def test_only_two_models_are_offered() -> None:
    provider = next(f for f in settings_store.SETTING_FIELDS if f.name == "llm_provider")
    assert set(provider.options) == {"deepseek", "codex_cli"}


def test_settings_stay_small_and_conditional() -> None:
    # 设置项越少越好；需要填的才显示。
    assert len(settings_store.SETTING_FIELDS) <= 6
    conditional = [f.name for f in settings_store.SETTING_FIELDS if f.depends_on]
    assert set(conditional) == {"deepseek_api_key", "codex_cli_path", "search_api_key"}
