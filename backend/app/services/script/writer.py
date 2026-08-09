from __future__ import annotations

import math
import re
from datetime import UTC, datetime

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
REQUIRED_SCRIPT_MARKERS = (
    "### 旁白",
    "### 镜头",
    "### 叙事功能",
    "### 事实依据",
    "## 结尾",
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


def script_is_complete(script: str) -> bool:
    return bool(
        len(script.strip()) >= 200
        and all(marker in script for marker in REQUIRED_SCRIPT_MARKERS)
        and re.search(r"##\s+00:00\s*-\s*00:\d{2}", script)
        and re.search(r"\b(?:event|source)_[a-f0-9]{16}\b", script)
    )


def _safe_error(error: Exception) -> str:
    message = re.sub(r"https?://\S+", "上游接口", str(error).strip())
    return (message.splitlines()[0] if message else "上游未返回可用内容")[:240]


class ScriptWriter:
    def __init__(self, llm: LLMService, store: ProjectStore) -> None:
        self.llm = llm
        self.store = store

    async def write(self, session: Session, topic: Topic, duration: int) -> str:
        context = narrative_context(session, topic, self.store)
        prompt = render_prompt("script_writer", duration=duration, context=stable_json(context))
        try:
            script = normalize_script_format(
                await self.llm.generate_text(
                    session,
                    topic.id,
                    f"script_writer:{duration}",
                    (
                        "真实性高于戏剧性。以因果节拍推进，事实因果与编辑承接必须区分；"
                        "影视化合成动作不得冒充真实行为。"
                    ),
                    prompt,
                )
            )
            if not script_is_complete(script):
                raise RuntimeError("上游剧本为空或缺少因果节拍格式")
            self._save_meta(session, topic, "ai_generated")
            return script
        except Exception as error:
            script = self._fallback(context, duration)
            self._save_meta(
                session, topic, "deterministic_fallback", reason=_safe_error(error)
            )
            return script

    def safe_fallback(
        self,
        session: Session,
        topic: Topic,
        duration: int,
        reason: str = "剧本重写未通过质量门",
    ) -> str:
        script = self._fallback(narrative_context(session, topic, self.store), duration)
        self._save_meta(session, topic, "deterministic_fallback", reason=reason)
        return script

    def _save_meta(
        self,
        session: Session,
        topic: Topic,
        mode: str,
        *,
        reason: str = "",
    ) -> None:
        self.store.save_json(
            session,
            topic.id,
            "script_meta",
            {
                "generation_mode": mode,
                "reason": reason,
                "provider": self.llm.provider.name,
                "model": self.llm.provider.model,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )

    def _fallback(self, context: dict, duration: int) -> str:
        events = context.get("events", [])
        if not events:
            raise RuntimeError("没有可用于编写剧本的已核验事件")
        event_by_id = {event["id"]: event for event in events}
        story = context.get("story_arc", {})
        beats = story.get("beats", []) or self._legacy_beats(events)
        target_segments = min(len(beats), 10 if duration >= 180 else 8)
        target_segments = max(6, target_segments)
        selected_beats = [beats[index % len(beats)] for index in range(target_segments)]
        windows = self._segment_windows(duration, target_segments)

        lines = [
            f"# {context['topic']}",
            "",
            "## 基本信息",
            "",
            f"预计时长：{duration} 秒",
            "",
            "叙事模式：人物纪实电影；事实层只使用已核验素材，合成还原只存在于镜头设计。",
            "",
            f"戏剧问题：{story.get('dramatic_question') or '一个具体选择如何面对现实后果？'}",
            "",
            "---",
        ]
        used_events: list[dict] = []
        for index, (beat, (start, end)) in enumerate(zip(selected_beats, windows, strict=True)):
            beat_event_ids = [
                event_id for event_id in beat.get("event_ids", []) if event_id in event_by_id
            ]
            event = (
                event_by_id.get(beat_event_ids[0])
                if beat_event_ids
                else events[index % len(events)]
            )
            used_events.append(event)
            beat_id = beat.get("beat_id") or f"beat_{index + 1:02d}"
            function = beat.get("narrative_function") or f"推进节点 {index + 1}"
            narration = self._beat_narration(event, function, end - start, index)
            visual = beat.get("visual_action") or self._fallback_visual(event, index)
            cause_link = beat.get("cause_link") or (
                "结果先出现，暂不解释。"
                if index == 0
                else "承接上一段留下的问题，以编辑关系推进，不新增事实因果。"
            )
            source_ids = list(
                dict.fromkeys([*beat.get("source_ids", []), *event.get("source_ids", [])])
            )
            lines.extend(
                [
                    "",
                    f"## {start // 60:02d}:{start % 60:02d} - {end // 60:02d}:{end % 60:02d}",
                    "",
                    "### 旁白",
                    "",
                    narration,
                    "",
                    "### 镜头",
                    "",
                    f"- {visual}",
                    "",
                    "### 叙事功能",
                    "",
                    f"- 节拍：{beat_id} / {function}",
                    f"- 承接：{cause_link}",
                    (
                        f"- 价值变化：{beat.get('value_before', '未知')} → "
                        f"{beat.get('value_after', '改变')}"
                    ),
                    (
                        "- 合成说明：这是影视化合成还原，只承载已核验处境，"
                        "不代表真实人物外貌或真实动作复刻。"
                        if beat.get("dramatization_mode") == "composite_reenactment"
                        else "- 画面依据：公开资料、环境或可核验数据。"
                    ),
                    "",
                    "### 事实依据",
                    "",
                    f"- {event['id']}",
                    *[f"- {source_id}" for source_id in source_ids],
                    "",
                    "---",
                ]
            )

        unique_events = list({event["id"]: event for event in used_events}.values())
        lines.extend(
            [
                "",
                "## 结尾",
                "",
                story.get("ending_device")
                or "停在最后一个已核验事实之后的未完成动作与环境余音，不追加道理总结。",
                "",
                "## 使用到的真实案例",
                "",
                *[
                    f"- {event['title']}（{event['id']}）"
                    for event in unique_events
                    if event.get("event_type") == "PERSONAL_CASE"
                ],
                "",
                "## 使用到的关键数据",
                "",
                *[
                    f"- {event['summary']}（{event['id']}）"
                    for event in unique_events
                    if event.get("event_type") == "DATA"
                ],
                "",
                "## 来源",
                "",
                *[
                    f"- [{source['title']}]({source['url']})（{source['id']}）"
                    for source in context.get("sources", [])
                ],
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _legacy_beats(events: list[dict]) -> list[dict]:
        functions = (
            "结果前置钩子",
            "人物起点",
            "承诺与机会",
            "压力升级",
            "局势转折",
            "代价显现",
            "选择与回应",
            "余波与行动收束",
        )
        return [
            {
                "beat_id": f"beat_{index + 1:02d}",
                "narrative_function": function,
                "event_ids": [events[index % len(events)]["id"]],
                "source_ids": events[index % len(events)].get("source_ids", []),
                "value_before": f"状态 {index + 1}",
                "value_after": f"状态 {index + 2}",
                "dramatization_mode": "archive_or_data",
            }
            for index, function in enumerate(functions)
        ]

    @staticmethod
    def _segment_windows(duration: int, count: int) -> list[tuple[int, int]]:
        first_end = min(5, duration - (count - 1))
        windows = [(0, first_end)]
        cursor = first_end
        for index in range(count - 1):
            slots = count - 1 - index
            length = math.ceil((duration - cursor) / slots)
            end = duration if index == count - 2 else min(duration, cursor + length)
            windows.append((cursor, end))
            cursor = end
        return windows

    @classmethod
    def _beat_narration(
        cls, event: dict, function: str, segment_duration: int, index: int
    ) -> str:
        prefixes = (
            "结果先出现。",
            "要理解它，先回到一个具体的人。",
            "当时，机会看起来正在打开。",
            "但新的事实让风险开始累积。",
            "直到局势改变，原来的判断失效。",
            "代价随后落回生活本身。",
            "回应出现了，但问题没有立刻结束。",
            "最后留下的，是事件之后仍在继续的现实。",
        )
        prefix = prefixes[min(index, len(prefixes) - 1)]
        raw = re.sub(r"\s+", "", event.get("summary") or event.get("title") or "")
        max_chars = max(12, int(segment_duration * 4.5))
        candidate = f"{prefix}{raw}"
        return cls._fit_spoken_text(candidate, max_chars, fallback=prefix)

    @staticmethod
    def _fit_spoken_text(text: str, max_chars: int, *, fallback: str) -> str:
        if len(text) <= max_chars:
            return text
        clauses = [
            match.group(0)
            for match in re.finditer(r"[^。！？；]+[。！？；]?", text)
            if match.group(0).strip()
        ]
        result = ""
        for clause in clauses:
            if len(result) + len(clause) > max_chars:
                break
            result += clause
        return result or fallback

    @staticmethod
    def _fallback_visual(event: dict, index: int) -> str:
        if event.get("event_type") == "PERSONAL_CASE":
            return (
                "影视化合成还原：成年还原演员在与素材相容的生活空间里完成一项日常事务；"
                "信息进入时手上动作停住，镜头留在反应，不宣称该动作真实发生。"
            )
        modes = (
            "从支持该事实的公开资料主体切入，以一个明确细节建立悬念。",
            "用可核验数据与现实环境的尺度关系推进，不堆叠说明图。",
            "用空间中的一个真实物件状态承接事实，避免空泛城市空镜。",
        )
        return modes[index % len(modes)]

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
        rewritten = normalize_script_format(
            await self.llm.generate_text(
                session,
                topic.id,
                f"script_rewrite:{duration}",
                "只修复审校问题，不创造新事实，不把编辑承接写成现实因果。",
                prompt,
            )
        )
        if not script_is_complete(rewritten):
            raise RuntimeError("重写结果为空或缺少因果节拍格式")
        self._save_meta(session, topic, "ai_generated")
        return rewritten
