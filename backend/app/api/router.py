from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
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
    ProductionPackageData,
    RegenerateShotRequest,
    ResearchRequest,
    RewriteScriptRequest,
    StepStatus,
    TopicCreate,
    TopicRead,
    TopicStatusResponse,
)
from app.services.artifacts import ProjectStore
from app.services.materials import material_counts, material_ready, minimums
from app.services.pipeline import PipelineBusyError, PipelineRunner
from app.services.production.package import ProductionPackageBuilder
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


def require_capacity(runner: PipelineRunner, topic_id: str) -> None:
    """必须在 prepare_* 之前调用：那些函数会删 StepRun 并直接提交，
    先改后 409 会让目标主题卡在非终态却没有任务在跑。"""
    try:
        runner.ensure_capacity(topic_id)
    except PipelineBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def start_pipeline(runner: PipelineRunner, topic_id: str) -> bool:
    try:
        return runner.start(topic_id)
    except PipelineBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    probe: bool = Query(
        default=False,
        description="真的调一次 LLM 来验证 Key 可用（会消耗少量额度），默认只报配置状态",
    ),
) -> HealthResponse:
    pipeline = request.app.state.pipeline
    provider = pipeline.llm_provider
    profile = provider.model
    if provider.name == "deepseek" and pipeline.settings.deepseek_thinking_enabled:
        profile = f"{provider.model} · {pipeline.settings.deepseek_reasoning_effort.upper()}"
    probe_ok: bool | None = None
    probe_error: str | None = None
    if probe:
        # ready 只说明配了 Key，不代表 Key 能用。这一步不放在启动里，
        # 否则上游一抖动整个应用就起不来。
        try:
            await provider.generate_text("你是连通性检查器。", "只回复 OK。")
            probe_ok = True
        except Exception as error:
            probe_ok = False
            probe_error = str(error)[:500]
    return HealthResponse(
        status="ok",
        llm_provider=provider.name,
        llm_model=provider.model,
        llm_profile=profile,
        llm_ready=provider.ready,
        search_provider=pipeline.search_provider.name,
        crawler_provider=pipeline.crawler_provider.name,
        version=__version__,
        llm_probe_ok=probe_ok,
        llm_probe_error=probe_error,
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
    require_capacity(runner, topic_id)
    topic.requested_duration = payload.duration
    session.commit()
    started = start_pipeline(runner, topic_id)
    return AcceptedResponse(
        accepted=started,
        topic_id=topic_id,
        message="研究已开始" if started else "研究任务已在运行",
    )


@router.get("/topics/{topic_id}/status", response_model=TopicStatusResponse)
def topic_status(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
) -> TopicStatusResponse:
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
        artifact_versions=store.versions(session, topic_id),
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


def _etag(kind: str, version: int | None) -> str:
    return f'W/"{kind}-{version or 0}"'


def _artifact_response(
    store: ProjectStore,
    session: Session,
    topic_id: str,
    kind: str,
    if_none_match: str | None,
    response: Response,
):
    """artifact 只在重新生成时才变；带上 ETag 后前端复查一次只花一个 304。"""
    require_topic(topic_id, session)
    tag = _etag(kind, store.version(session, topic_id, kind))
    if if_none_match and if_none_match.strip() == tag:
        return Response(status_code=304, headers={"ETag": tag})
    value = store.load_json(session, topic_id, kind)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{kind} 尚未生成")
    response.headers["ETag"] = tag
    return value


def _load_repaired_production_package(
    store: ProjectStore, session: Session, topic_id: str
) -> ProductionPackageData:
    value = store.load_json(session, topic_id, "production_package")
    if value is None:
        raise HTTPException(status_code=404, detail="影视生成包尚未生成")
    package = ProductionPackageData.model_validate(value)
    repaired, changed = ProductionPackageBuilder.repair_display_prompts(package)
    if changed:
        store.save_json(session, topic_id, "production_package", repaired)
        session.commit()
    return repaired


@router.get("/topics/{topic_id}/timeline")
def get_timeline(
    topic_id: str,
    response: Response,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _artifact_response(store, session, topic_id, "timeline", if_none_match, response)


@router.get("/topics/{topic_id}/story")
def get_story(
    topic_id: str,
    response: Response,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    return _artifact_response(store, session, topic_id, "story_arc", if_none_match, response)


@router.get("/topics/{topic_id}/script")
def get_script(
    topic_id: str,
    response: Response,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    require_topic(topic_id, session)
    tag = _etag("script", store.version(session, topic_id, "script"))
    if if_none_match and if_none_match.strip() == tag:
        return Response(status_code=304, headers={"ETag": tag})
    script = store.load_text(session, topic_id, "script")
    if script is None:
        raise HTTPException(status_code=404, detail="script 尚未生成")
    response.headers["ETag"] = tag
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


@router.get(
    "/topics/{topic_id}/production-package",
    response_model=ProductionPackageData,
)
def get_production_package(
    topic_id: str,
    response: Response,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    require_topic(topic_id, session)
    package = _load_repaired_production_package(store, session, topic_id)
    tag = _etag("production_package", store.version(session, topic_id, "production_package"))
    if if_none_match and if_none_match.strip() == tag:
        return Response(status_code=304, headers={"ETag": tag})
    response.headers["ETag"] = tag
    return package


@router.get("/topics/{topic_id}/production-package/download")
def download_production_package(
    topic_id: str,
    session: Session = Depends(get_session),
    store: ProjectStore = Depends(get_store),
) -> FileResponse:
    require_topic(topic_id, session)
    _load_repaired_production_package(store, session, topic_id)
    path = store.topic_dir(topic_id) / "production_package.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="影视生成包尚未生成")
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"{topic_id}-production-package.json",
    )


@router.post(
    "/topics/{topic_id}/production-package",
    response_model=AcceptedResponse,
    status_code=202,
)
async def generate_production_package(
    topic_id: str,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
    store: ProjectStore = Depends(get_store),
) -> AcceptedResponse:
    require_topic(topic_id, session)
    if runner.running(topic_id):
        return AcceptedResponse(
            accepted=False, topic_id=topic_id, message="研究任务已在运行"
        )
    if not store.load_text(session, topic_id, "script"):
        raise HTTPException(status_code=409, detail="剧本尚未生成")
    require_capacity(runner, topic_id)
    runner.pipeline.prepare_production(topic_id)
    start_pipeline(runner, topic_id)
    return AcceptedResponse(topic_id=topic_id, message="正在生成逐镜头影视包")


@router.post(
    "/topics/{topic_id}/production-package/shots/{shot_id}/regenerate",
    response_model=ProductionPackageData,
)
async def regenerate_production_shot(
    topic_id: str,
    shot_id: str,
    payload: RegenerateShotRequest,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
) -> ProductionPackageData:
    require_topic(topic_id, session)
    if runner.running(topic_id):
        raise HTTPException(status_code=409, detail="研究任务运行中，请稍后再试")
    try:
        return await runner.pipeline.regenerate_production_shot(
            topic_id, shot_id, payload.current_prompt
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="镜头不存在") from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/topics/{topic_id}/continue", response_model=AcceptedResponse, status_code=202)
async def continue_research(
    topic_id: str,
    session: Session = Depends(get_session),
    runner: PipelineRunner = Depends(get_runner),
) -> AcceptedResponse:
    require_topic(topic_id, session)
    if runner.running(topic_id):
        return AcceptedResponse(accepted=False, topic_id=topic_id, message="研究任务已在运行")
    require_capacity(runner, topic_id)
    runner.pipeline.prepare_continue(topic_id)
    start_pipeline(runner, topic_id)
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
    require_capacity(runner, topic_id)
    runner.pipeline.prepare_rewrite(topic_id, payload.duration)
    start_pipeline(runner, topic_id)
    return AcceptedResponse(topic_id=topic_id, message=f"正在重新生成 {payload.duration} 秒剧本")


@router.get("/hotspots", response_model=list[HotspotData])
async def get_hotspots(request: Request) -> list[HotspotData]:
    try:
        return await request.app.state.hotspot_provider.fetch_hotspots()
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"热点来源暂时不可用：{error}") from error
