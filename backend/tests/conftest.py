from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import Base


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        llm_provider="mock",
        search_provider="duckduckgo",
        crawler_provider="simple_http",
        max_search_results=10,
        search_results_per_query=10,
        min_valid_sources=3,
        min_verified_facts=5,
        min_personal_cases=1,
        min_key_data=2,
        max_retries=0,
        search_query_pause_seconds=0,
        llm_raw_retention=0,
    )


@pytest.fixture
def session_factory(test_settings: Settings) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(test_settings.resolved_database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    yield factory
    engine.dispose()
