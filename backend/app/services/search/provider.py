from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.domain import SearchResultData


class SearchProvider(ABC):
    name: str

    @property
    def ready(self) -> bool:
        return True

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        raise NotImplementedError
