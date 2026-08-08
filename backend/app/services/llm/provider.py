from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    name: str
    model: str

    @property
    def ready(self) -> bool:
        return True

    @abstractmethod
    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        raise NotImplementedError
