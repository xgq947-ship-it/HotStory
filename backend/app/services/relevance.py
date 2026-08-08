from __future__ import annotations

import re

from app.models import Fact, Source

CJK_RE = re.compile(r"[\u3400-\u9fff]+")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)

GENERIC_TERMS = {
    "事件",
    "热点",
    "新闻",
    "社会",
    "相关",
    "问题",
    "市场",
    "重大",
    "大量",
    "投资",
    "遭遇",
    "这些",
    "这个",
    "之后",
    "背后",
}

TOPIC_ALIASES = {
    "炒股": {"股票", "股市", "散户", "股民"},
    "杠杆": {"融资", "爆仓", "强平", "平仓", "ETF"},
    "亏损": {"赔钱", "损失", "浮亏"},
    "年轻人": {"青年", "上班族", "20岁", "30岁"},
    "韩国": {"韩股", "KOSPI", "韩元", "首尔"},
    "消费": {"消费者", "退款", "收费", "价格"},
    "职场": {"员工", "公司", "裁员", "加班"},
    "人数": {"人次", "共有", "总计"},
    "公布": {"官方", "数据", "发布"},
}


def topic_terms(topic: str) -> set[str]:
    terms = {word.lower() for word in WORD_RE.findall(topic)}
    for run in CJK_RE.findall(topic):
        for size in (2, 3):
            terms.update(run[index : index + size] for index in range(len(run) - size + 1))
    terms.difference_update(GENERIC_TERMS)
    for anchor, aliases in TOPIC_ALIASES.items():
        if anchor in topic:
            terms.update(alias.lower() for alias in aliases)
    return {term for term in terms if len(term) >= 2}


def text_matches_topic(topic: str, text: str) -> bool:
    terms = topic_terms(topic)
    if not terms:
        return True
    normalized = text.lower()
    matches = sum(term in normalized for term in terms)
    required = 2 if len(terms) >= 4 else 1
    return matches >= required


def fact_matches_topic(fact: Fact, topic: str, sources_by_id: dict[str, Source]) -> bool:
    source_context = " ".join(
        f"{sources_by_id[source_id].title} {sources_by_id[source_id].snippet}"
        for source_id in fact.source_ids
        if source_id in sources_by_id
    )
    context = " ".join(
        [
            fact.statement,
            *fact.people,
            *fact.organizations,
            *fact.locations,
            source_context,
        ]
    )
    return text_matches_topic(topic, context)
