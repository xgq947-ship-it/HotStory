from __future__ import annotations

import asyncio
import logging
import random
from collections import OrderedDict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SearchRun
from app.schemas.domain import KeywordGroups, ResearchPlanData, SearchResultData
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.research.engine import ResearchEngine
from app.services.search.provider import SearchProvider
from app.utils import normalize_url

logger = logging.getLogger(__name__)

RATE_LIMIT_MARKERS = ("ratelimit", "rate limit", "429", "too many requests", "202 ratelimit")


def is_rate_limited(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def heuristic_plan(topic: str) -> ResearchPlanData:
    questions = [
        f"{topic}最早从何时开始，直接起因是什么？",
        "事件此前有哪些长期背景和结构性原因？",
        "有哪些权威统计数据能说明事件规模和变化？",
        "事件涉及哪些真实个人案例，各自来源是什么？",
        "是否存在正面、负面和不同处境的代表性案例？",
        "哪些关键节点推动事件扩大或改变方向？",
        "媒体观点和公众讨论如何随时间变化？",
        "专家、机构或利益相关方有哪些相互冲突的观点？",
        "政府、监管部门或行业机构作出了哪些正式回应？",
        "事件造成了哪些短期后果和长期影响？",
        "哪些说法尚未证实或存在来源冲突？",
        "事件最终如何回到普通人的日常选择与风险？",
    ]
    english = [topic, f"{topic} timeline", f"{topic} data cases official response"]
    local: list[str] = []
    if "韩国" in topic or "韩" in topic:
        local = ["한국 청년 주식 투자", "한국 주식 빚투 손실", "금융당국 공식 발표"]
    elif "日本" in topic:
        local = ["日本 ニュース 統計", "政府 公式発表"]
    return ResearchPlanData(
        research_questions=questions,
        keywords=KeywordGroups(
            zh=[
                topic,
                f"{topic} 时间线",
                f"{topic} 数据",
                f"{topic} 真实案例",
                f"{topic} 官方回应",
            ],
            en=english,
            local=local,
        ),
    )


class NativeResearchEngine(ResearchEngine):
    name = "native"

    def __init__(
        self,
        session: Session,
        topic_id: str,
        llm: LLMService,
        search_provider: SearchProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.topic_id = topic_id
        self.llm = llm
        self.search_provider = search_provider
        self.settings = settings

    async def build_plan(self, topic: str) -> ResearchPlanData:
        prompt = render_prompt("research_planner", topic=topic)
        try:
            return await self.llm.generate_model(
                self.session,
                self.topic_id,
                "research_plan",
                "你是资深调查记者。只制定调查计划，不把推测写成事实。",
                prompt,
                ResearchPlanData,
            )
        except Exception:
            logger.warning(
                "LLM research plan failed; using deterministic fallback",
                extra={"topic_id": self.topic_id, "step": "plan"},
                exc_info=True,
            )
            return heuristic_plan(topic)

    def _queries(self, topic: str, plan: ResearchPlanData, depth: int) -> list[tuple[str, str]]:
        questions = plan.research_questions
        keywords = plan.keywords.zh + plan.keywords.en + plan.keywords.local
        rounds: list[tuple[str, list[str]]] = [
            ("background", [topic, *questions[:2], *keywords[:2]]),
            ("data", [*questions[2:3], f"{topic} 统计 数据 报告", f"{topic} statistics report"]),
            (
                "cases",
                [*questions[3:5], f"{topic} 真实人物 案例", f"{topic} personal case interview"],
            ),
            ("turning", [*questions[5:7], f"{topic} 转折 后果 时间线"]),
            (
                "response",
                [*questions[7:10], f"{topic} 官方 回应 监管", f"{topic} official response"],
            ),
        ]
        if depth > 0:
            deep_rounds = [
                (
                    "deep_cases",
                    [f"{topic} 当事人 采访 细节", f"{topic} victim profile case study"],
                ),
                (
                    "primary_sources",
                    [f"{topic} site:gov official data", f"{topic} original report PDF"],
                ),
                ("local_sources", plan.keywords.local + [f"{topic} 当地媒体"]),
            ]
            deeper_rounds: list[tuple[str, list[str]]] = []
            if depth >= 2:
                deeper_rounds = [
                    (
                        f"personal_cases_depth_{depth}",
                        [
                            f"{topic} 当事人 采访 姓名 真实经历",
                            f"{topic} 负债 亏损 人物故事",
                            f"{topic} personal interview named investor",
                            "韩国年轻人 杠杆炒股 当事人 采访",
                            "韩国散户 爆仓 真实人物 案例",
                            "South Korea young leveraged investor loss interview",
                            "한국 청년 빚투 손실 인터뷰 사례",
                            "한국 20대 주식 레버리지 손실 사례",
                        ],
                    ),
                    (
                        f"primary_sources_depth_{depth}",
                        [
                            f"{topic} 原始采访 报道",
                            f"{topic} site:co.kr interview",
                            f"{topic} site:go.kr 통계",
                        ],
                    ),
                ]
            rounds = deeper_rounds + deep_rounds + rounds
        output: list[tuple[str, str]] = []
        seen: set[str] = set()
        for round_name, values in rounds:
            for query in values:
                normalized = " ".join(query.split())
                if len(normalized) < 3 or normalized.lower() in seen:
                    continue
                seen.add(normalized.lower())
                output.append((round_name, normalized))
        return output

    async def _search_once(self, query: str) -> list[SearchResultData]:
        """限流是搜索失败的主要原因；退避重试一次比整轮搜空便宜得多。"""
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self.search_provider.search(
                    query, limit=self.settings.search_results_per_query
                )
            except Exception as error:
                last_error = error
                if attempt >= 1 or not is_rate_limited(error):
                    raise
                await asyncio.sleep(3 + random.uniform(0, 2))
        raise last_error or RuntimeError("搜索失败")

    async def search(
        self, topic: str, plan: ResearchPlanData, depth: int = 0
    ) -> tuple[list[SearchResultData], list[str]]:
        deduplicated: OrderedDict[str, SearchResultData] = OrderedDict()
        executed_queries: list[str] = []
        attempted = 0
        failed = 0
        last_error = ""
        for round_name, query in self._queries(topic, plan, depth):
            existing = self.session.scalar(
                select(SearchRun).where(
                    SearchRun.topic_id == self.topic_id, SearchRun.query == query
                )
            )
            if existing and existing.status == "SUCCESS":
                rows = [SearchResultData.model_validate(item) for item in existing.results_json]
            else:
                run = existing or SearchRun(
                    topic_id=self.topic_id, round_name=round_name, query=query, status="RUNNING"
                )
                if not existing:
                    self.session.add(run)
                else:
                    run.status = "RUNNING"
                    run.error = None
                self.session.commit()
                attempted += 1
                pause = self.settings.search_query_pause_seconds
                if pause > 0:
                    await asyncio.sleep(pause * random.uniform(0.5, 1.5))
                try:
                    rows = await self._search_once(query)
                    run.status = "SUCCESS"
                    run.results_json = [row.model_dump(mode="json") for row in rows]
                    run.completed_at = datetime.now(UTC)
                    self.session.commit()
                except Exception as error:
                    failed += 1
                    last_error = str(error)[:200]
                    run.status = "FAILED"
                    run.error = str(error)[:2000]
                    self.session.commit()
                    logger.warning(
                        "search query failed",
                        extra={
                            "topic_id": self.topic_id,
                            "step": "search",
                            "provider": self.search_provider.name,
                        },
                    )
                    continue
            executed_queries.append(query)
            for row in rows:
                deduplicated.setdefault(normalize_url(row.url), row)
                if len(deduplicated) >= self.settings.max_search_results:
                    break
            if len(deduplicated) >= self.settings.max_search_results:
                break
        # 不在这里报错的话，后面会以 "没有成功抓取到任何有效正文" 的名义失败在 fetch 步，
        # 指向错误的原因。
        if attempted and (attempted - failed) / attempted < self.settings.search_min_success_ratio:
            raise RuntimeError(
                f"搜索几乎全部失败（{attempted - failed}/{attempted} 成功，"
                f"provider={self.search_provider.name}）：{last_error or '未知错误'}"
            )
        if not deduplicated:
            raise RuntimeError(
                f"搜索没有返回任何结果（provider={self.search_provider.name}）："
                f"{last_error or '请检查网络或更换 SEARCH_PROVIDER'}"
            )
        return list(deduplicated.values()), executed_queries
