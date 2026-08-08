from __future__ import annotations

from urllib.parse import urlparse

from app.schemas.domain import ResearchPlanData, SearchResultData
from app.services.research.engine import ResearchEngine
from app.services.research.native_engine import NativeResearchEngine


class GPTResearcherEngine(ResearchEngine):
    """Optional adapter; all third-party values are normalized to HotStory schemas."""

    name = "gpt_researcher"

    def __init__(self, native: NativeResearchEngine) -> None:
        self.native = native

    async def build_plan(self, topic: str) -> ResearchPlanData:
        return await self.native.build_plan(topic)

    async def search(
        self, topic: str, plan: ResearchPlanData, depth: int = 0
    ) -> tuple[list[SearchResultData], list[str]]:
        try:
            from gpt_researcher import GPTResearcher
        except ImportError as error:
            raise RuntimeError(
                "GPT Researcher 未安装；请安装 backend/requirements-optional.txt，或使用 native"
            ) from error
        researcher = GPTResearcher(query=topic, report_type="research_report")
        await researcher.conduct_research()
        urls = list(dict.fromkeys(getattr(researcher, "visited_urls", []) or []))
        normalized: list[SearchResultData] = []
        for url in urls:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            normalized.append(
                SearchResultData(
                    title=urlparse(url).netloc,
                    url=url,
                    publisher=urlparse(url).netloc.removeprefix("www."),
                )
            )
        if not normalized:
            return await self.native.search(topic, plan, depth)
        return normalized[: self.native.settings.max_search_results], [topic]
