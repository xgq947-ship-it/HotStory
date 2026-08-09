from __future__ import annotations

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Source, Topic
from app.schemas.domain import ReviewData
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.utils import stable_json

ID_PATTERN = re.compile(r"\b(?:event|source)_[a-f0-9]{16}\b")
BEAT_ID_PATTERN = re.compile(r"\bbeat_\d{2}\b")
TIME_SEGMENT_PATTERN = re.compile(
    r"(?ms)^##\s*(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\s*$\n(.*?)(?=^##\s|\Z)"
)
BLOCKING_ISSUE_MARKERS = (
    "无来源",
    "无法核验",
    "无效",
    "错误",
    "异常",
    "笔误",
    "虚构",
    "不完整",
    "缺少",
    "事实依据",
    "来源id",
    "违反",
    "说教",
    "因果",
    "节奏",
    "连续性",
    "起伏",
    "口播",
)
PREACHY_ENDING_MARKERS = (
    "这告诉我们",
    "值得深思",
    "真正重要的是",
    "愿每个人",
    "归根结底",
    "我们应该",
)


def review_issue_is_blocking(issue: str) -> bool:
    normalized = issue.lower()
    return any(marker in normalized for marker in BLOCKING_ISSUE_MARKERS)


def _section(body: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^###\s*{re.escape(heading)}\s*$\n(.*?)(?=^###\s|\Z)", body
    )
    return match.group(1).strip() if match else ""


def _spoken_char_count(value: str) -> int:
    return len(re.sub(r"[\s，。！？、；：,.!?;:\"“”'（）()—–-]", "", value))


class ScriptReviewer:
    def __init__(self, llm: LLMService, store: ProjectStore | None = None) -> None:
        self.llm = llm
        self.store = store

    def structural_review(self, session: Session, topic: Topic, script: str) -> ReviewData:
        event_ids = set(session.scalars(select(Event.id).where(Event.topic_id == topic.id)))
        source_ids = set(session.scalars(select(Source.id).where(Source.topic_id == topic.id)))
        allowed = event_ids | source_ids
        used = set(ID_PATTERN.findall(script))
        fact_issues: list[str] = []
        causality_issues: list[str] = []
        rhythm_issues: list[str] = []
        ending_issues: list[str] = []
        narration_issues: list[str] = []

        invalid = sorted(used - allowed)
        if invalid:
            fact_issues.append(f"存在无效事实引用：{', '.join(invalid)}")
        if not used:
            fact_issues.append("剧本没有 event_id / source_id 事实引用")
        for heading in ("旁白", "镜头", "叙事功能", "事实依据"):
            if f"### {heading}" not in script:
                fact_issues.append(f"缺少逐段{heading}")
        if "## 结尾" not in script:
            ending_issues.append("缺少结尾")

        segments: list[dict] = []
        for match in TIME_SEGMENT_PATTERN.finditer(script):
            start = int(match.group(1)) * 60 + int(match.group(2))
            end = int(match.group(3)) * 60 + int(match.group(4))
            body = match.group(5)
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "body": body,
                    "narration": _section(body, "旁白"),
                    "dialogue": _section(body, "对白"),
                    "function": _section(body, "叙事功能"),
                    "ids": ID_PATTERN.findall(_section(body, "事实依据")),
                }
            )

        if not segments:
            rhythm_issues.append("缺少规范时间码")
        else:
            if segments[0]["start"] != 0 or segments[0]["end"] > 6:
                rhythm_issues.append("开场钩子必须从 0 秒开始并在 6 秒内完成")
            if not 6 <= len(segments) <= 10:
                rhythm_issues.append("正文必须保持 6—10 个连续叙事段落")
            for index, segment in enumerate(segments):
                if segment["end"] <= segment["start"]:
                    rhythm_issues.append(f"第 {index + 1} 段时间码无效")
                    continue
                if index and segment["start"] != segments[index - 1]["end"]:
                    rhythm_issues.append(f"第 {index + 1} 段与上一段存在空隙或重叠")
                if not segment["ids"]:
                    fact_issues.append(f"第 {index + 1} 段没有逐段事实依据")
                function = segment["function"]
                if not BEAT_ID_PATTERN.search(function):
                    causality_issues.append(f"第 {index + 1} 段没有绑定 beat_id")
                if index and "承接" not in function:
                    causality_issues.append(f"第 {index + 1} 段没有说明与上一节拍的承接")
                if "价值变化" not in function or "→" not in function:
                    causality_issues.append(f"第 {index + 1} 段没有可见价值状态变化")
                duration = segment["end"] - segment["start"]
                spoken = _spoken_char_count(
                    f"{segment['narration']}{segment['dialogue']}"
                )
                max_spoken = max(12, math.floor(duration * 4.5))
                if spoken > max_spoken:
                    narration_issues.append(
                        f"第 {index + 1} 段口播过载：{spoken} 字 / {duration} 秒"
                    )
            if segments[-1]["end"] != topic.requested_duration:
                rhythm_issues.append(
                    f"时间码没有完整覆盖目标时长：{segments[-1]['end']} 秒 / "
                    f"{topic.requested_duration} 秒"
                )
            durations = [segment["end"] - segment["start"] for segment in segments]
            if len(set(durations)) < min(3, len(durations)):
                rhythm_issues.append("段落时长过于整齐，缺少张弛变化")

        story = (
            self.store.load_json(session, topic.id, "story_arc")
            if self.store is not None
            else None
        ) or {}
        expected_beats = [
            beat.get("beat_id", "") for beat in story.get("beats", []) if beat.get("beat_id")
        ]
        used_beats = list(dict.fromkeys(BEAT_ID_PATTERN.findall(script)))
        if expected_beats:
            minimum_coverage = min(
                len(expected_beats), max(4, math.ceil(len(expected_beats) * 0.6))
            )
            if len(set(used_beats) & set(expected_beats)) < minimum_coverage:
                causality_issues.append("剧本没有覆盖足够的因果节拍")
            expected_order = {beat_id: index for index, beat_id in enumerate(expected_beats)}
            ordered = [expected_order[item] for item in used_beats if item in expected_order]
            if ordered != sorted(ordered):
                causality_issues.append("剧本打乱了已通过质量门的节拍顺序")

        ending_match = re.search(r"(?ms)^##\s*结尾\s*$\n(.*?)(?=^##\s|\Z)", script)
        ending = ending_match.group(1).strip() if ending_match else ""
        if any(marker in ending for marker in PREACHY_ENDING_MARKERS):
            ending_issues.append("结尾存在总结式说教，必须改为行动、余波、静默或回环")
        if ending and len(ending) > 180:
            ending_issues.append("结尾说明过长，余韵被解释替代")

        issues = list(
            dict.fromkeys(
                [
                    *fact_issues,
                    *causality_issues,
                    *rhythm_issues,
                    *ending_issues,
                    *narration_issues,
                ]
            )
        )
        causality_score = max(0, 100 - 14 * len(causality_issues))
        rhythm_score = max(0, 100 - 14 * len(rhythm_issues))
        ending_score = max(0, 100 - 20 * len(ending_issues))
        narration_fit_score = max(0, 100 - 18 * len(narration_issues))
        fact_score = max(0, 100 - 18 * len(fact_issues))
        score = min(
            fact_score,
            round(
                causality_score * 0.32
                + rhythm_score * 0.28
                + ending_score * 0.18
                + narration_fit_score * 0.22
            ),
        )
        return ReviewData(
            score=score,
            issues=issues,
            passed=score >= 85 and not issues,
            causality_score=causality_score,
            rhythm_score=rhythm_score,
            ending_score=ending_score,
            narration_fit_score=narration_fit_score,
        )

    async def review(self, session: Session, topic: Topic, script: str) -> ReviewData:
        structural = self.structural_review(session, topic, script)
        event_ids = list(session.scalars(select(Event.id).where(Event.topic_id == topic.id)))
        source_ids = list(session.scalars(select(Source.id).where(Source.topic_id == topic.id)))
        prompt = render_prompt(
            "script_review",
            allowed_ids=stable_json({"events": event_ids, "sources": source_ids}),
            script=script,
        )
        try:
            llm_review = await self.llm.generate_model(
                session,
                topic.id,
                "script_review",
                "严格核验事实、因果、人物连续性、节奏曲线、口播负载与非说教式结尾。",
                prompt,
                ReviewData,
            )
            issues = list(dict.fromkeys([*structural.issues, *llm_review.issues]))
            score = min(structural.score, llm_review.score)
            blocking = bool(structural.issues) or any(
                review_issue_is_blocking(issue) for issue in llm_review.issues
            )
            return ReviewData(
                score=score,
                issues=issues,
                passed=score >= 85 and llm_review.passed and not blocking,
                causality_score=min(
                    structural.causality_score, llm_review.causality_score
                ),
                rhythm_score=min(structural.rhythm_score, llm_review.rhythm_score),
                ending_score=min(structural.ending_score, llm_review.ending_score),
                narration_fit_score=min(
                    structural.narration_fit_score, llm_review.narration_fit_score
                ),
            )
        except Exception:
            return structural
