from __future__ import annotations

import json
from collections import deque
from typing import Any

from app.services.llm.provider import LLMProvider, LLMResponse


class MockLLMProvider(LLMProvider):
    """Deterministic provider for tests; never selected in production by default."""

    name = "mock"
    model = "deterministic-test-model"

    def __init__(self, responses: list[dict[str, Any] | str] | None = None) -> None:
        self.responses: deque[dict[str, Any] | str] = deque(responses or [])
        self.calls = 0

    def _next(self, user_prompt: str, json_mode: bool) -> str:
        self.calls += 1
        if self.responses:
            value = self.responses.popleft()
            return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        if not json_mode:
            return (
                "# 测试剧本\n\n## 00:00 - 00:10\n\n### 旁白\n基于已核验事实。"
                "\n\n### 事实依据\n- event_test\n- source_test"
            )
        lowered = user_prompt.lower()
        if "research_questions" in lowered:
            return json.dumps(
                {
                    "research_questions": [f"研究问题 {index}" for index in range(1, 11)],
                    "keywords": {"zh": ["测试热点"], "en": ["test topic"], "local": []},
                },
                ensure_ascii=False,
            )
        if '"facts"' in lowered or "事实核查员" in user_prompt:
            return json.dumps({"facts": []}, ensure_ascii=False)
        if '"events"' in lowered:
            return json.dumps({"events": []}, ensure_ascii=False)
        if '"timeline"' in lowered:
            return json.dumps({"timeline": []}, ensure_ascii=False)
        if "central_theme" in lowered:
            return json.dumps(
                {
                    "central_theme": "测试主题",
                    "core_conflict": "选择与风险",
                    "story_arc": [],
                    "selected_events": [],
                    "selected_cases": [],
                    "selected_data": [],
                },
                ensure_ascii=False,
            )
        if "human_lesson" in lowered:
            return json.dumps(
                {
                    "human_lesson": ["保持理性"],
                    "positive_values": ["责任"],
                    "ending_direction": "回到普通生活",
                    "ending_sentence_candidates": ["让选择服务生活。"],
                },
                ensure_ascii=False,
            )
        if '"score"' in lowered:
            return json.dumps({"score": 95, "issues": [], "passed": True}, ensure_ascii=False)
        return "{}"

    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        content = self._next(user_prompt, json_mode=False)
        return LLMResponse(
            content=content, provider=self.name, model=self.model, raw={"mock": True}
        )

    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        content = self._next(user_prompt, json_mode=True)
        return LLMResponse(
            content=content, provider=self.name, model=self.model, raw={"mock": True}
        )
