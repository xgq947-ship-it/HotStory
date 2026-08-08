from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.domain import CrawledDocumentData


class CrawlerProvider(ABC):
    name: str

    @abstractmethod
    async def fetch(self, url: str) -> CrawledDocumentData:
        raise NotImplementedError
