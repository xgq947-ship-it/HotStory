from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Topic
from app.schemas.domain import ValueDirectionData
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.utils import stable_json


class ValueBuilder:
    def __init__(self, llm: LLMService, store: ProjectStore) -> None:
        self.llm = llm
        self.store = store

    async def build(self, session: Session, topic: Topic) -> ValueDirectionData:
        story = self.store.load_json(session, topic.id, "story_arc") or {}
        timeline = self.store.load_json(session, topic.id, "timeline") or {}
        context = {"topic": topic.title, "story": story, "timeline": timeline}
        prompt = render_prompt("value_builder", context=stable_json(context))
        try:
            return await self.llm.generate_model(
                session,
                topic.id,
                "value_builder",
                "只从真实事件自然提炼价值，不空洞说教、不消费悲剧。",
                prompt,
                ValueDirectionData,
            )
        except Exception:
            financial = any(
                word in topic.title
                for word in ("股票", "股市", "杠杆", "期货", "加密", "贷款", "炒房")
            )
            if financial:
                return ValueDirectionData(
                    human_lesson=["风险最终会回到普通人的生活承受能力"],
                    positive_values=["理性", "风险意识", "量力而行", "长期主义"],
                    ending_direction="让投资服务生活，而不是拿生活赌一次投资",
                    ending_sentence_candidates=["市场还有下一次机会，生活却不该成为筹码。"],
                )
            return ValueDirectionData(
                human_lesson=["公共事件与每个普通人的选择相连"],
                positive_values=["理性", "责任", "独立思考"],
                ending_direction="回到普通人的生活与长期选择",
                ending_sentence_candidates=["真正重要的，是让每一次选择经得起时间。"],
            )
