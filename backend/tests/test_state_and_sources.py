from __future__ import annotations

from app.models import Topic
from app.services.sources import estimate_credibility
from app.services.state import StepTracker
from app.utils import new_id


def test_extract_source_retry_restores_extracting_status(session_factory) -> None:
    with session_factory() as session:
        topic = Topic(id=new_id("topic"), title="断点状态测试")
        session.add(topic)
        session.commit()
        tracker = StepTracker()

        tracker.fail(session, topic, "extract_source:source_a:0", "")
        assert topic.status == "FAILED"
        assert topic.error == "请求失败（上游未返回错误详情）"

        tracker.start(session, topic, "extract_source:source_b:0")
        assert topic.status == "EXTRACTING"
        assert topic.error is None


def test_source_credibility_distinguishes_primary_media_and_community() -> None:
    assert estimate_credibility("https://news.cctv.com/report") == 0.9
    assert estimate_credibility("https://finance.sina.com.cn/report") == 0.8
    assert estimate_credibility("https://zhuanlan.zhihu.com/p/123") == 0.45
