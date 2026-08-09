from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FactType(StrEnum):
    BACKGROUND = "BACKGROUND"
    DATA = "DATA"
    POLICY = "POLICY"
    MEDIA = "MEDIA"
    SOCIAL = "SOCIAL"
    PERSONAL_CASE = "PERSONAL_CASE"
    TURNING_POINT = "TURNING_POINT"
    CONSEQUENCE = "CONSEQUENCE"
    RESPONSE = "RESPONSE"


class KeywordGroups(BaseModel):
    zh: list[str] = Field(default_factory=list)
    en: list[str] = Field(default_factory=list)
    local: list[str] = Field(default_factory=list)


class ResearchPlanData(BaseModel):
    research_questions: list[str] = Field(min_length=10)
    keywords: KeywordGroups


class SearchResultData(BaseModel):
    title: str
    url: str
    snippet: str = ""
    publisher: str = ""
    published_at: str = ""
    language: str = ""

    @field_validator("url")
    @classmethod
    def valid_http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("search result URL must be HTTP(S)")
        return value


class ResearchResultData(BaseModel):
    plan: ResearchPlanData
    sources: list[SearchResultData] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class CrawledDocumentData(BaseModel):
    url: str
    title: str = ""
    published_at: str = ""
    author: str = ""
    raw_text: str = ""
    markdown: str = ""
    language: str = ""
    crawler: str


class FactDraft(BaseModel):
    statement: str = Field(min_length=5)
    fact_type: FactType
    date: str = ""
    people: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class FactExtractionResult(BaseModel):
    facts: list[FactDraft] = Field(default_factory=list)


class FactVerificationGroup(BaseModel):
    fact_ids: list[str] = Field(min_length=2)
    relationship: Literal["same_claim", "conflicting"]
    reason: str = ""


class FactVerificationResult(BaseModel):
    groups: list[FactVerificationGroup] = Field(default_factory=list)


class EventDraft(BaseModel):
    title: str
    summary: str
    date: str = ""
    event_type: FactType
    fact_ids: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    emotion: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class EventClusterResult(BaseModel):
    events: list[EventDraft] = Field(default_factory=list)


class TimelineItemData(BaseModel):
    date: str = ""
    title: str
    description: str
    event_ids: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0, le=1)


class TimelineResult(BaseModel):
    timeline: list[TimelineItemData] = Field(default_factory=list)


class StoryStage(BaseModel):
    stage: str
    event_ids: list[str] = Field(default_factory=list)


class StoryArcData(BaseModel):
    central_theme: str
    core_conflict: str
    story_arc: list[StoryStage] = Field(default_factory=list)
    selected_events: list[str] = Field(default_factory=list)
    selected_cases: list[str] = Field(default_factory=list)
    selected_data: list[str] = Field(default_factory=list)


class ValueDirectionData(BaseModel):
    human_lesson: list[str] = Field(default_factory=list)
    positive_values: list[str] = Field(default_factory=list)
    ending_direction: str
    ending_sentence_candidates: list[str] = Field(default_factory=list)


class ReviewData(BaseModel):
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    passed: bool


class CharacterImageSettings(BaseModel):
    model: str = "Higgsfield Soul 2.0"
    aspect_ratio: str = "16:9"
    quality: str = "2k"
    consistency: str = "首张满意后创建 Soul ID，并在后续镜头中复用"


class CharacterAssetDraft(BaseModel):
    prompt_label: str = Field(min_length=2, max_length=80)
    role: Literal["lead", "supporting"]
    story_function: str = Field(min_length=2, max_length=300)
    source_fact_ids: list[str] = Field(default_factory=list)
    visual_anchor: str = Field(min_length=10)
    wardrobe_anchor: str = Field(min_length=5)
    image_prompt: str = Field(min_length=30)
    acting_profile: str = Field(min_length=30)
    voice_prompt: str = ""
    default_use_reference: bool = True


class CharacterCatalogDraft(BaseModel):
    style_bible: str = Field(min_length=10)
    characters: list[CharacterAssetDraft] = Field(default_factory=list, max_length=6)


class CharacterAssetData(CharacterAssetDraft):
    id: str
    reference_token: str
    identity_basis: Literal["verified_role_visualization"] = "verified_role_visualization"
    disclosure: str = "影视化还原角色，不代表真实人物的实际外貌。"
    image_settings: CharacterImageSettings = Field(default_factory=CharacterImageSettings)
    optimized_by: str = "lira-image-prompts + acting-ai-video"


class ShotPlanDraft(BaseModel):
    shot_id: str = Field(min_length=3, max_length=40)
    title: str = Field(min_length=2, max_length=120)
    start_second: int = Field(ge=0, le=180)
    end_second: int = Field(ge=1, le=180)
    narration: str = Field(default="", max_length=1200)
    dialogue: str = Field(default="", max_length=800)
    visual_brief: str = Field(min_length=5, max_length=1500)
    active_character_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shot_window(self) -> ShotPlanDraft:
        duration = self.end_second - self.start_second
        if duration < 1:
            raise ValueError("镜头结束时间必须晚于开始时间")
        if duration > 10:
            raise ValueError("单个镜头不得超过 10 秒")
        return self


class ShotPlanResult(BaseModel):
    shots: list[ShotPlanDraft] = Field(min_length=1, max_length=18)


class ShotPromptDraft(BaseModel):
    shot_id: str
    prompt_body_template: str = Field(min_length=80)
    ambient_audio: str = ""


class ShotPromptBatch(BaseModel):
    shots: list[ShotPromptDraft] = Field(default_factory=list, max_length=4)


class CinematicShotData(ShotPlanDraft):
    duration_seconds: int = Field(ge=1, le=10)
    prompt_body_template: str
    ambient_audio: str = ""
    target_model: str = "Seedance 2.0 / Higgsfield Seedance"
    optimized_by: str = "acting-ai-video + cinedance-higgsfield"
    revision: int = Field(default=1, ge=1)


class SkillStageData(BaseModel):
    order: int
    skill: str
    purpose: str
    instruction_mode: Literal["verbatim"] = "verbatim"
    source_sha256: str = ""


class ProductionPackageData(BaseModel):
    version: str = "1.2"
    topic_id: str
    generated_at: str
    duration_seconds: int
    llm_profile: str = ""
    max_shot_duration_seconds: Literal[10] = 10
    generation_mode: Literal["ai_optimized", "mixed", "fallback"] = "ai_optimized"
    warnings: list[str] = Field(default_factory=list)
    prompt_preservation: Literal["lossless"] = "lossless"
    style_bible: str
    skills: list[SkillStageData]
    characters: list[CharacterAssetData] = Field(default_factory=list)
    shots: list[CinematicShotData] = Field(default_factory=list)


class HotspotData(BaseModel):
    title: str
    platform: str
    rank: int = 0
    heat: int | float | str = 0
    url: str = ""
    summary: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    story_score: int = Field(default=0, ge=0, le=100)


class TopicCreate(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    input_mode: Literal["manual", "hotspot"] = "manual"


class TopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    input_mode: str
    status: str
    current_step: str | None
    error: str | None
    requested_duration: int
    research_depth: int
    created_at: datetime
    updated_at: datetime


class ResearchRequest(BaseModel):
    duration: Literal[60, 90, 180] = 90


class StepStatus(BaseModel):
    step: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    retry_count: int = 0


class TopicStatusResponse(BaseModel):
    topic: TopicRead
    steps: list[StepStatus]
    counts: dict[str, int]
    material_ready: bool
    minimums: dict[str, int]
    # kind -> version。前端靠它决定要不要重新拉 artifact，而不是每 2.5 秒全量拉一遍。
    # regenerate_shot 只改 artifact 不动 StepRun，只看步骤状态会漏掉它。
    artifact_versions: dict[str, int] = Field(default_factory=dict)


class RewriteScriptRequest(BaseModel):
    duration: Literal[60, 90, 180] = 90


class RegenerateShotRequest(BaseModel):
    current_prompt: str = ""


class AcceptedResponse(BaseModel):
    accepted: bool = True
    topic_id: str
    message: str


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    llm_model: str
    llm_profile: str
    llm_ready: bool
    search_provider: str
    crawler_provider: str
    version: str
    # 只有 ?probe=true 时才会真的调一次 LLM；平时保持 None，避免启动/健康检查变慢变脆。
    llm_probe_ok: bool | None = None
    llm_probe_error: str | None = None


JsonValue = dict[str, Any] | list[Any]


class SettingFieldState(BaseModel):
    name: str
    label: str
    group: str
    kind: str
    secret: bool
    options: list[str] = Field(default_factory=list)
    help: str = ""
    placeholder: str = ""
    restart_required: bool = False
    editable: bool = True
    depends_on: list[str] | None = None
    value: Any = ""
    configured: bool = False
    source: str = "default"


class SettingsResponse(BaseModel):
    groups: dict[str, str]
    fields: list[SettingFieldState]
    version: str
    repository_url: str


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)


class CodexDetectRequest(BaseModel):
    path: str = ""


class CodexStatusResponse(BaseModel):
    available: bool
    path: str = ""
    version: str = ""
    error: str = ""
    searched: list[str] = Field(default_factory=list)


class ReleaseInfo(BaseModel):
    tag_name: str
    name: str
    html_url: str
    body: str = ""
    published_at: str = ""


class UpdateCheckResponse(BaseModel):
    current_version: str
    latest: ReleaseInfo | None = None
    update_available: bool = False
    releases: list[ReleaseInfo] = Field(default_factory=list)
    error: str = ""
