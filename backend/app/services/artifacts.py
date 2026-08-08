from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Artifact

ARTIFACT_FILES = {
    "topic": "topic.json",
    "research_plan": "research_plan.json",
    "search_results": "search_results.json",
    "sources": "sources.json",
    "facts": "facts.json",
    "events": "events.json",
    "timeline": "timeline.json",
    "story_arc": "story_arc.json",
    "value": "value.json",
    "review": "review.json",
    "script": "script.md",
}


def _serializable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serializable(item) for item in value]
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    return value


class ProjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def topic_dir(self, topic_id: str) -> Path:
        path = self.settings.projects_dir / topic_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def llm_dir(self, topic_id: str) -> Path:
        path = self.topic_dir(topic_id) / "llm_raw"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_json_file(self, topic_id: str, kind: str, value: Any) -> Path:
        filename = ARTIFACT_FILES.get(kind, f"{kind}.json")
        path = self.topic_dir(topic_id) / filename
        payload = json.dumps(_serializable(value), ensure_ascii=False, indent=2, default=str)
        self._atomic_write(path, payload + "\n")
        return path

    def save_text_file(self, topic_id: str, kind: str, content: str) -> Path:
        filename = ARTIFACT_FILES.get(kind, f"{kind}.md")
        path = self.topic_dir(topic_id) / filename
        self._atomic_write(path, content.rstrip() + "\n")
        return path

    def save_json(self, session: Session, topic_id: str, kind: str, value: Any) -> Path:
        data = _serializable(value)
        artifact = session.scalar(
            select(Artifact).where(Artifact.topic_id == topic_id, Artifact.kind == kind)
        )
        if artifact:
            artifact.json_data = data
            artifact.text_content = None
            artifact.version += 1
        else:
            artifact = Artifact(topic_id=topic_id, kind=kind, json_data=data, version=1)
            session.add(artifact)
        session.flush()
        return self.save_json_file(topic_id, kind, data)

    def save_text(self, session: Session, topic_id: str, kind: str, content: str) -> Path:
        artifact = session.scalar(
            select(Artifact).where(Artifact.topic_id == topic_id, Artifact.kind == kind)
        )
        if artifact:
            artifact.text_content = content
            artifact.json_data = None
            artifact.version += 1
        else:
            artifact = Artifact(topic_id=topic_id, kind=kind, text_content=content, version=1)
            session.add(artifact)
        session.flush()
        return self.save_text_file(topic_id, kind, content)

    def load_json(self, session: Session, topic_id: str, kind: str) -> Any | None:
        artifact = session.scalar(
            select(Artifact).where(Artifact.topic_id == topic_id, Artifact.kind == kind)
        )
        return artifact.json_data if artifact else None

    def load_text(self, session: Session, topic_id: str, kind: str) -> str | None:
        artifact = session.scalar(
            select(Artifact).where(Artifact.topic_id == topic_id, Artifact.kind == kind)
        )
        return artifact.text_content if artifact else None
