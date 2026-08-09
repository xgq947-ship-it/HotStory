from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import StepRun, Topic

PIPELINE_STEPS = [
    "plan",
    "search",
    "fetch",
    "extract",
    "cluster",
    "verify",
    "timeline",
    "story",
    "value",
    "write",
    "review",
    "production",
    "export",
]

TOPIC_STATUS_BY_STEP = {
    "plan": "PLANNING",
    "search": "SEARCHING",
    "fetch": "FETCHING",
    "extract": "EXTRACTING",
    "extract_source": "EXTRACTING",
    "cluster": "CLUSTERING",
    "verify": "VERIFYING",
    "timeline": "TIMELINE",
    "story": "STORY",
    "value": "VALUE",
    "write": "WRITING",
    "review": "REVIEWING",
    "production": "DIRECTING",
    "export": "DIRECTING",
}


class StepTracker:
    def get(self, session: Session, topic_id: str, step: str) -> StepRun | None:
        return session.scalar(
            select(StepRun).where(StepRun.topic_id == topic_id, StepRun.step == step)
        )

    def is_complete(self, session: Session, topic_id: str, step: str) -> bool:
        run = self.get(session, topic_id, step)
        return bool(run and run.status == "SUCCESS")

    def start(self, session: Session, topic: Topic, step: str, force: bool = False) -> bool:
        run = self.get(session, topic.id, step)
        if run and run.status == "SUCCESS" and not force:
            return False
        now = datetime.now(UTC)
        if run:
            run.retry_count += 1 if run.status == "FAILED" else 0
            run.status = "RUNNING"
            run.started_at = now
            run.completed_at = None
            run.error = None
        else:
            run = StepRun(topic_id=topic.id, step=step, status="RUNNING", started_at=now)
            session.add(run)
        topic.status = TOPIC_STATUS_BY_STEP.get(step.split(":", 1)[0], topic.status)
        topic.current_step = step
        topic.error = None
        session.commit()
        return True

    def complete(self, session: Session, topic: Topic, step: str, output_hash: str = "") -> None:
        run = self.get(session, topic.id, step)
        if not run:
            run = StepRun(topic_id=topic.id, step=step)
            session.add(run)
        run.status = "SUCCESS"
        run.completed_at = datetime.now(UTC)
        run.error = None
        run.output_hash = output_hash or None
        topic.current_step = step
        session.commit()

    def fail(self, session: Session, topic: Topic, step: str, error: str) -> None:
        error = error.strip() or "请求失败（上游未返回错误详情）"
        run = self.get(session, topic.id, step)
        if not run:
            run = StepRun(topic_id=topic.id, step=step)
            session.add(run)
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        run.error = error[:4000]
        topic.status = "FAILED"
        topic.current_step = step
        topic.error = error[:4000]
        session.commit()

    def reset_from(self, session: Session, topic: Topic, step: str) -> None:
        start = PIPELINE_STEPS.index(step)
        targets = PIPELINE_STEPS[start:]
        session.execute(
            delete(StepRun).where(StepRun.topic_id == topic.id, StepRun.step.in_(targets))
        )
        topic.status = TOPIC_STATUS_BY_STEP[step]
        topic.current_step = step
        topic.error = None
        session.commit()
