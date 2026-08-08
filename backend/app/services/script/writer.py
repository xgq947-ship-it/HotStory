from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Topic
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.script.context import narrative_context
from app.utils import stable_json

FACT_ID_PATTERN = re.compile(r"\bfact_[a-f0-9]{16}\b")
SECOND_RANGE_HEADING = re.compile(
    r"(?m)^###\s*(\d{1,3})\s*[—–-]\s*(\d{1,3})\s*秒\s*$"
)


def normalize_script_format(script: str) -> str:
    """Keep model prose while enforcing the public event/source citation format."""

    def timecode(match: re.Match[str]) -> str:
        start, end = (int(match.group(1)), int(match.group(2)))
        return f"## {start // 60:02d}:{start % 60:02d} - {end // 60:02d}:{end % 60:02d}"

    normalized = SECOND_RANGE_HEADING.sub(timecode, script)
    normalized = re.sub(rf"{FACT_ID_PATTERN.pattern}\s*/\s*", "", normalized)
    normalized = re.sub(rf"\s*/\s*{FACT_ID_PATTERN.pattern}", "", normalized)
    normalized = FACT_ID_PATTERN.sub("", normalized)
    normalized = re.sub(r"(?m)^-\s*$\n?", "", normalized)
    return normalized.strip()


class ScriptWriter:
    def __init__(self, llm: LLMService, store: ProjectStore) -> None:
        self.llm = llm
        self.store = store

    async def write(self, session: Session, topic: Topic, duration: int) -> str:
        context = narrative_context(session, topic, self.store)
        prompt = render_prompt("script_writer", duration=duration, context=stable_json(context))
        try:
            script = await self.llm.generate_text(
                session,
                topic.id,
                f"script_writer:{duration}",
                "真实性高于戏剧性。剧本只能使用输入中的已核验事实和真实 ID。",
                prompt,
            )
            return normalize_script_format(script)
        except Exception:
            return self._fallback(context, duration)

    def safe_fallback(self, session: Session, topic: Topic, duration: int) -> str:
        return self._fallback(narrative_context(session, topic, self.store), duration)

    def _fallback(self, context: dict, duration: int) -> str:
        available = context["events"]
        preferred = [
            *available[:1],
            *[event for event in available if event["event_type"] == "DATA"][:1],
            *[event for event in available if event["event_type"] == "PERSONAL_CASE"][:2],
            *available[1:],
        ]
        events = list({event["id"]: event for event in preferred}.values())[
            : min(8, max(3, duration // 20))
        ]
        lines = [
            f"# {context['topic']}",
            "",
            "## 基本信息",
            "",
            f"预计时长：{duration} 秒",
            "",
            f"核心主题：{context.get('story_arc', {}).get('central_theme', context['topic'])}",
            "",
            "---",
        ]
        segment = max(8, duration // max(len(events), 1))
        cursor = 0
        for index, event in enumerate(events, 1):
            end = duration if index == len(events) else min(duration, cursor + segment)
            lines.extend(
                [
                    "",
                    f"## {cursor // 60:02d}:{cursor % 60:02d} - {end // 60:02d}:{end % 60:02d}",
                    "",
                    "### 旁白",
                    "",
                    event["summary"],
                    "",
                    "### 镜头",
                    "",
                    f"- S{index:02d}：与该事件对应的公开资料画面",
                    "",
                    "### 事实依据",
                    "",
                    f"- {event['id']}",
                    *[f"- {source_id}" for source_id in event["source_ids"]],
                    "",
                    "---",
                ]
            )
            cursor = end
        lines.extend(
            [
                "",
                "## 结尾",
                "",
                context.get("value", {}).get("ending_direction")
                or "在风险面前，先保住生活，再谈收益。",
                "",
                "## 使用到的真实案例",
                "",
                *[
                    f"- {event['title']}（{event['id']}）"
                    for event in events
                    if event["event_type"] == "PERSONAL_CASE"
                ],
                "",
                "## 使用到的关键数据",
                "",
                *[
                    f"- {event['summary']}（{event['id']}）"
                    for event in events
                    if event["event_type"] == "DATA"
                ],
                "",
                "## 来源",
                "",
                *[
                    f"- [{source['title']}]({source['url']})（{source['id']}）"
                    for source in context["sources"]
                ],
            ]
        )
        return "\n".join(lines)

    async def rewrite(
        self, session: Session, topic: Topic, script: str, issues: list[str], duration: int
    ) -> str:
        context = narrative_context(session, topic, self.store)
        context["duration"] = duration
        prompt = render_prompt(
            "rewrite_script",
            context=stable_json(context),
            script=script,
            issues=stable_json(issues),
        )
        script = await self.llm.generate_text(
            session,
            topic.id,
            f"script_rewrite:{duration}",
            "只修复审校问题，不创造新事实。",
            prompt,
        )
        return normalize_script_format(script)
