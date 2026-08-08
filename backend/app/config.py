from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    frontend_origin: str = "http://localhost:3000"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/hotstory.db"
    data_dir: Path = PROJECT_ROOT / "data"
    research_engine: str = "native"

    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    search_provider: str = "duckduckgo"
    search_api_key: SecretStr | None = None
    crawler_provider: str = "auto"
    hotspot_provider: str = "auto"
    dailyhot_api_base_url: str = "https://api-hot.imsyy.top"
    trendradar_api_base_url: str = ""

    max_search_results: int = Field(default=60, ge=10, le=200)
    search_results_per_query: int = Field(default=8, ge=1, le=20)
    min_valid_sources: int = Field(default=10, ge=1)
    min_verified_facts: int = Field(default=12, ge=1)
    min_personal_cases: int = Field(default=2, ge=0)
    min_key_data: int = Field(default=2, ge=0)
    enable_playwright_fallback: bool = True
    request_timeout_seconds: float = Field(default=25, ge=3, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)
    llm_timeout_seconds: float = Field(default=60, ge=10, le=300)
    llm_max_retries: int = Field(default=1, ge=0, le=4)
    fetch_concurrency: int = Field(default=5, ge=1, le=12)
    llm_concurrency: int = Field(default=2, ge=1, le=8)

    codex_cli_path: str = "codex"
    codex_cli_model: str = ""
    codex_cli_timeout_seconds: int = Field(default=480, ge=30, le=1800)

    @property
    def resolved_database_url(self) -> str:
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            relative = self.database_url.removeprefix(prefix)
            return f"sqlite:///{(PROJECT_ROOT / relative).resolve()}"
        return self.database_url

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    def secret_for_llm(self) -> str:
        if self.llm_provider.lower() == "deepseek" and self.deepseek_api_key:
            return self.deepseek_api_key.get_secret_value()
        if self.llm_provider.lower() == "anthropic" and self.anthropic_api_key:
            return self.anthropic_api_key.get_secret_value()
        return self.llm_api_key.get_secret_value() if self.llm_api_key else ""

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
