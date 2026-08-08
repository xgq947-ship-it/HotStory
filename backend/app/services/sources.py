from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source
from app.schemas.domain import SearchResultData
from app.utils import new_id, normalize_url, publisher_from_url, sha256_text

HIGH_CREDIBILITY_MARKERS = (
    ".gov",
    ".edu",
    "reuters.com",
    "apnews.com",
    "bbc.",
    "who.int",
    "un.org",
    "oecd.org",
    "worldbank.org",
    "stats.gov",
    "gov.cn",
    "people.com.cn",
    "xinhuanet.com",
    "news.cctv.com",
    "stcn.com",
    "cnfin.com",
    "cs.com.cn",
    "21jingji.com",
    "yna.co.kr",
    "kostat.go.kr",
    "fsc.go.kr",
    "bok.or.kr",
    "koreatimes.co.kr",
    "koreaherald.com",
    "chosun.com",
    "joongang.co.kr",
    "hani.co.kr",
    "mk.co.kr",
)
MEDIUM_CREDIBILITY_MARKERS = (
    "sina.com.cn",
    "sina.cn",
    "thepaper.cn",
    "ifeng.com",
    "yicai.com",
    "163.com",
    "qq.com",
)
LOW_CREDIBILITY_MARKERS = (
    "weibo.com",
    "x.com",
    "twitter.com",
    "reddit.com",
    "zhihu.com",
    "xueqiu.com",
    "baike.baidu.com",
    "aduptaihafy.net",
    "blog",
    "forum",
)


def estimate_credibility(url: str) -> float:
    host = publisher_from_url(url)
    if any(marker in host for marker in HIGH_CREDIBILITY_MARKERS):
        return 0.9
    if any(marker in host for marker in MEDIUM_CREDIBILITY_MARKERS):
        return 0.8
    if any(marker in host for marker in LOW_CREDIBILITY_MARKERS):
        return 0.45
    return 0.68


def refresh_credibility_scores(session: Session, topic_id: str) -> None:
    sources = list(session.scalars(select(Source).where(Source.topic_id == topic_id)))
    for source in sources:
        source.credibility_score = estimate_credibility(source.url)
    session.commit()


def upsert_search_results(
    session: Session, topic_id: str, results: list[SearchResultData]
) -> list[Source]:
    sources: list[Source] = []
    for result in results:
        normalized = normalize_url(result.url)
        source = session.scalar(
            select(Source).where(Source.topic_id == topic_id, Source.normalized_url == normalized)
        )
        if source:
            if not source.title and result.title:
                source.title = result.title
            if not source.snippet and result.snippet:
                source.snippet = result.snippet
            sources.append(source)
            continue
        source = Source(
            id=new_id("source"),
            topic_id=topic_id,
            title=result.title,
            url=result.url,
            normalized_url=normalized,
            publisher=result.publisher or publisher_from_url(result.url),
            published_at=result.published_at,
            language=result.language,
            snippet=result.snippet,
            credibility_score=estimate_credibility(result.url),
        )
        session.add(source)
        sources.append(source)
    session.commit()
    return sources


def remove_content_duplicates(session: Session, topic_id: str) -> int:
    sources = list(
        session.scalars(
            select(Source)
            .where(Source.topic_id == topic_id, Source.fetch_status == "SUCCESS")
            .order_by(Source.credibility_score.desc(), Source.id)
        )
    )
    kept: list[Source] = []
    removed = 0
    for source in sources:
        duplicate = False
        for existing in kept:
            same_hash = bool(source.content_hash and source.content_hash == existing.content_hash)
            same_title = (
                source.title
                and existing.title
                and SequenceMatcher(None, source.title.lower(), existing.title.lower()).ratio()
                >= 0.94
                and source.publisher == existing.publisher
            )
            if same_hash or same_title:
                duplicate = True
                break
        if duplicate:
            session.delete(source)
            removed += 1
        else:
            kept.append(source)
    session.commit()
    return removed


def apply_crawled_content(source: Source, document) -> None:  # type: ignore[no-untyped-def]
    source.url = document.url or source.url
    source.publisher = publisher_from_url(source.url) or source.publisher
    source.credibility_score = estimate_credibility(source.url)
    source.title = document.title or source.title
    source.published_at = document.published_at or source.published_at
    source.author = document.author or source.author
    source.language = document.language or source.language
    source.content = document.raw_text
    source.markdown = document.markdown
    source.content_hash = (
        sha256_text(document.raw_text.strip()) if document.raw_text.strip() else ""
    )
    source.crawler = document.crawler
    source.fetch_status = "SUCCESS" if len(document.raw_text.strip()) >= 160 else "FAILED"
    source.fetch_error = None if source.fetch_status == "SUCCESS" else "正文过短"
