from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.domain import ResearchPlanData, ResearchResultData, SearchResultData


class ResearchEngine(ABC):
    name: str

    @abstractmethod
    async def build_plan(self, topic: str) -> ResearchPlanData:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self, topic: str, plan: ResearchPlanData, depth: int = 0
    ) -> tuple[list[SearchResultData], list[str]]:
        raise NotImplementedError

    async def research(self, topic: str) -> ResearchResultData:
        plan = await self.build_plan(topic)
        sources, queries = await self.search(topic, plan)
        return ResearchResultData(plan=plan, sources=sources, queries=queries)
