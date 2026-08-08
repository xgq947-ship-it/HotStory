from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Source, Topic
from app.schemas.domain import ReviewData
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.utils import stable_json

ID_PATTERN = re.compile(r"\b(?:event|source)_[a-f0-9]{16}\b")
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
)


def review_issue_is_blocking(issue: str) -> bool:
    normalized = issue.lower()
    return any(marker in normalized for marker in BLOCKING_ISSUE_MARKERS)


class ScriptReviewer:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def structural_review(self, session: Session, topic: Topic, script: str) -> ReviewData:
        event_ids = set(session.scalars(select(Event.id).where(Event.topic_id == topic.id)))
        source_ids = set(session.scalars(select(Source.id).where(Source.topic_id == topic.id)))
        allowed = event_ids | source_ids
        used = set(ID_PATTERN.findall(script))
        issues: list[str] = []
        invalid = sorted(used - allowed)
        if invalid:
            issues.append(f"存在无效事实引用：{', '.join(invalid)}")
        if not used:
            issues.append("剧本没有 event_id / source_id 事实引用")
        if "### 事实依据" not in script:
            issues.append("缺少逐段事实依据")
        if "### 镜头" not in script:
            issues.append("缺少镜头建议")
        if "## 结尾" not in script:
            issues.append("缺少结尾")
        timecodes = re.findall(r"##\s+(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})", script)
        if not timecodes:
            issues.append("缺少规范时间码")
        else:
            end_seconds = max(
                int(minutes) * 60 + int(seconds) for _, _, minutes, seconds in timecodes
            )
            if end_seconds > topic.requested_duration + 3:
                issues.append(
                    f"时间码超过目标时长：{end_seconds} 秒 > {topic.requested_duration} 秒"
                )
        score = max(0, 100 - 12 * len(issues))
        return ReviewData(score=score, issues=issues, passed=score >= 85 and not issues)

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
                "严格核验来源引用和纪录片质量。真实性问题必须扣分。",
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
            )
        except Exception:
            return structural
