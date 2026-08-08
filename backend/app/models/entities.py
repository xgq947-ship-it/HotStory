from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    input_mode: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="CREATED", index=True, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    requested_duration: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    research_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    sources: Mapped[list[Source]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    facts: Mapped[list[Fact]] = relationship(back_populates="topic", cascade="all, delete-orphan")
    events: Mapped[list[Event]] = relationship(back_populates="topic", cascade="all, delete-orphan")
    steps: Mapped[list[StepRun]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class StepRun(Base):
    __tablename__ = "step_runs"
    __table_args__ = (UniqueConstraint("topic_id", "step", name="uq_step_topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))

    topic: Mapped[Topic] = relationship(back_populates="steps")


class SearchRun(Base):
    __tablename__ = "search_runs"
    __table_args__ = (UniqueConstraint("topic_id", "query", name="uq_search_topic_query"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    round_name: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str] = mapped_column(String(700), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("topic_id", "normalized_url", name="uq_source_topic_url"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    published_at: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    author: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="news", nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, default=0.65, nullable=False)
    crawler: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    fetch_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    fetch_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    topic: Mapped[Topic] = relationship(back_populates="sources")


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    date: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    people: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    organizations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    numbers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), default="uncertain", nullable=False
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    topic: Mapped[Topic] = relationship(back_populates="facts")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(800), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    people: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    emotion: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    topic: Mapped[Topic] = relationship(back_populates="events")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("topic_id", "kind", name="uq_artifact_topic_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    json_data: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    text_content: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parsed_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
