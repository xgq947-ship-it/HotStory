from __future__ import annotations

from app.services.relevance import text_matches_topic

TOPIC = "韩国年轻人杠杆炒股，市场大跌后大量投资者遭遇重大亏损"


def test_topic_relevance_rejects_unrelated_government_material() -> None:
    assert not text_matches_topic(
        TOPIC,
        "美国国税局公布2025年报税截止日期和追加供款限额。",
    )
    assert not text_matches_topic(TOPIC, "韩国ASMR博主发布夏日打水枪视频。")


def test_topic_relevance_keeps_named_case_and_market_data() -> None:
    assert text_matches_topic(
        TOPIC,
        "凤凰网报道韩国散户朴宇哲在股票暴跌后重新评估家庭开支。",
    )
    assert text_matches_topic(TOPIC, "韩股杠杆ETF触发强制平仓，多个账户出现亏损。")
