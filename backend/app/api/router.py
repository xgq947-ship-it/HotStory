from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.db import get_session
from app.models import Event, Fact, Source, StepRun, Topic
from app.schemas.domain import (
    AcceptedResponse,
    HealthResponse,
    HotspotData,
    ResearchRequest,
    RewriteScriptRequest,
    StepStatus,
    TopicCreate,
    TopicRead,
    TopicStatusResponse,
)
from app.services.artifacts import ProjectStore
from app.services.materials import material_counts, material_ready, minimums
from app.services.pipeline import PipelineRunner
from app.services.serialization import event_dict, fact_dict, source_dict, topic_dict
from app.services.state import PIPELINE_STEPS
from app.utils import new_id

router = APIRouter(prefix="/api")


def get_runner(request: Request) -> PipelineRunner:
    return request.app.state.runner


def get_store(request: Request) -> ProjectStore:
    return request.app.state.store


def require_topic(topic_id: str, session: Session) -> Topic:
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic 不存在")
    return topic


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    provider = request.app.state.pipeline.llm_provider
    return HealthResponse(
        status="ok",
        llm_provider=provider.name,
        llm_ready=provider.ready,
        search_provider=request.app.state.pipeline.search_provider.name,
        crawler_provider=request.app.state.pipeline.crawler_provider.name,
        version=__version__,
    )


@router.post("/topics", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
def create_topic(
    payload: TopicCreate,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
) -> Topic:
    topic = Topic(id=new_id("topic"), title=payload.title.strip(), input_mode=payload.input_mode)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    store.save_json(session, topic.id, "topic", topic_dict(topic))
    session.commit()
    return topic


@router.get("/topics", response_model=list[TopicRead])
def list_topics(session: Session = Depends(get_session)) -> list[Topic]:
    return list(session.scalars(select(Topic).order_by(Topic.created_at.desc())))


@router.get("/topics/{topic_id}", response_model=TopicRead)
def get_topic(topic_id: str, session: Session = Depends(get_session)) -> Topic:
    return require_topic(topic_id, session)


@router.post("/topics/{topic_id}/research", response_model=AcceptedResponse, status_code=202)
async def start_research(
    topic_id: str,
    payload: ResearchRequest,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
) -> AcceptedResponse:
    topic = require_topic(topic_id, session)
    if topic.status == "COMPLETED":
        raise HTTPException(status_code=409, detail="该主题已完成；如需新版本请使用重新生成剧本")
    topic.requested_duration = payload.duration
    session.commit()
    started = runner.start(topic_id)
    return AcceptedResponse(
        accepted=started,
        topic_id=topic_id,
        message="研究已开始" if started else "研究任务已在运行",
    )


@router.get("/topics/{topic_id}/status", response_model=TopicStatusResponse)
def topic_status(topic_id: str, session: Session = Depends(get_session)) -> TopicStatusResponse:
    topic = require_topic(topic_id, session)
    runs = list(
        session.scalars(
            select(StepRun)
            .where(StepRun.topic_id == topic_id, StepRun.step.in_(PIPELINE_STEPS))
            .order_by(StepRun.id)
        )
    )
    by_name = {run.step: run for run in runs}
    steps = [
        StepStatus(
            step=name,
            status=by_name[name].status if name in by_name else "PENDING",
            started_at=by_name[name].started_at if name in by_name else None,
            completed_at=by_name[name].completed_at if name in by_name else None,
            error=by_name[name].error if name in by_name else None,
            retry_count=by_name[name].retry_count if name in by_name else 0,
        )
        for name in PIPELINE_STEPS
    ]
    counts = material_counts(session, topic_id)
    settings = get_settings()
    return TopicStatusResponse(
        topic=TopicRead.model_validate(topic),
        steps=steps,
        counts=counts,
        material_ready=material_ready(counts, settings),
        minimums=minimums(settings),
    )


@router.get("/topics/{topic_id}/sources")
def get_sources(
    topic_id: str,
    include_content: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict]:
    require_topic(topic_id, session)
    rows = list(
        session.scalars(
            select(Source)
            .where(Source.topic_id == topic_id)
            .order_by(Source.credibility_score.desc())
        )
    )
    return [source_dict(row, include_content=include_content) for row in rows]


@router.get("/topics/{topic_id}/facts")
def get_facts(
    topic_id: str,
    verified_only: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[dict]:
    require_topic(topic_id, session)
    statement = select(Fact).where(Fact.topic_id == topic_id)
    if verified_only:
        statement = statement.where(Fact.verified.is_(True))
    return [fact_dict(row) for row in session.scalars(statement.order_by(Fact.id))]


@router.get("/topics/{topic_id}/events")
def get_events(topic_id: str, session: Session = Depends(get_session)) -> list[dict]:
    require_topic(topic_id, session)
    return [
        event_dict(row)
        for row in session.scalars(
            select(Event).where(Event.topic_id == topic_id).order_by(Event.date)
        )
    ]


def _artifact_or_404(store: ProjectStore, session: Session, topic_id: str, kind: str):
    require_topic(topic_id, session)
    value = store.load_json(session, topic_id, kind)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{kind} 尚未生成")
    return value


@router.get("/topics/{topic_id}/timeline")
def get_timeline(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
):
    return _artifact_or_404(store, session, topic_id, "timeline")


@router.get("/topics/{topic_id}/story")
def get_story(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
):
    return _artifact_or_404(store, session, topic_id, "story_arc")


@router.get("/topics/{topic_id}/script")
def get_script(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
) -> dict:
    require_topic(topic_id, session)
    script = store.load_text(session, topic_id, "script")
    if script is None:
        raise HTTPException(status_code=404, detail="script 尚未生成")
    return {"script": script, "review": store.load_json(session, topic_id, "review")}


@router.get("/topics/{topic_id}/script/download")
def download_script(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
) -> FileResponse:
    require_topic(topic_id, session)
    path = store.topic_dir(topic_id) / "script.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="script 尚未生成")
    return FileResponse(path, media_type="text/markdown", filename=f"{topic_id}-script.md")


@router.post("/topics/{topic_id}/continue", response_model=AcceptedResponse, status_code=202)
async def continue_research(
    topic_id: str,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
) -> AcceptedResponse:
    require_topic(topic_id, session)
    if runner.running(topic_id):
        return AcceptedResponse(accepted=False, topic_id=topic_id, message="研究任务已在运行")
    runner.pipeline.prepare_continue(topic_id)
    runner.start(topic_id)
    return AcceptedResponse(topic_id=topic_id, message="已从现有结果继续深挖")


@router.post("/topics/{topic_id}/rewrite-script", response_model=AcceptedResponse, status_code=202)
async def rewrite_script(
    topic_id: str,
    payload: RewriteScriptRequest,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
) -> AcceptedResponse:
    require_topic(topic_id, session)
    if runner.running(topic_id):
        return AcceptedResponse(accepted=False, topic_id=topic_id, message="研究任务已在运行")
    runner.pipeline.prepare_rewrite(topic_id, payload.duration)
    runner.start(topic_id)
    return AcceptedResponse(topic_id=topic_id, message=f"正在重新生成 {payload.duration} 秒剧本")


@router.get("/hotspots", response_model=list[HotspotData])
async def get_hotspots(request: Request) -> list[HotspotData]:
    try:
        return await request.app.state.hotspot_provider.fetch_hotspots()
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"热点来源暂时不可用：{error}") from error
