from __future__ import annotations

from app.services.research.native_engine import NativeResearchEngine, heuristic_plan

from .fakes import FakeSearchProvider, ScenarioLLMProvider


def test_second_deep_dive_prioritizes_new_personal_case_queries(
    session_factory, test_settings
) -> None:
    with session_factory() as session:
        engine = NativeResearchEngine(
            session,
            "topic_test",
            ScenarioLLMProvider(),  # type: ignore[arg-type]
            FakeSearchProvider(),
            test_settings,
        )
        queries = engine._queries("韩国年轻人杠杆炒股", heuristic_plan("韩国年轻人杠杆炒股"), 2)

    assert queries[0][0] == "personal_cases_depth_2"
    assert any("한국 청년" in query for _, query in queries[:8])
