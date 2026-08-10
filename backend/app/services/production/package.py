from __future__ import annotations

import asyncio
import math
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Topic
from app.schemas.domain import (
    AnimaticCheckData,
    AudioCueData,
    CharacterAssetData,
    CharacterAssetDraft,
    CharacterCatalogDraft,
    CinematicShotData,
    GlobalAudioPlanData,
    InternalShotData,
    NarrativeQualityData,
    ProductionPackageData,
    ProductionReadinessData,
    ShotPlanDraft,
    ShotPlanResult,
    ShotPromptBatch,
    SkillStageData,
)
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.production.compliance import (
    ComplianceHit,
    build_entity_rules,
    sanitize,
    summarize,
)
from app.services.production.skills import VerbatimSkill, load_verbatim_skill
from app.services.prompts import render_prompt
from app.services.script.context import narrative_context
from app.utils import sha256_text, stable_json

TIME_SEGMENT_PATTERN = re.compile(
    r"(?ms)^##\s*(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\s*$\n(.*?)(?=^##\s|\Z)"
)
ID_PATTERNS = {
    "fact": re.compile(r"\bfact_[a-f0-9]{16}\b"),
    "event": re.compile(r"\bevent_[a-f0-9]{16}\b"),
    "source": re.compile(r"\bsource_[a-f0-9]{16}\b"),
}
REFERENCE_TAG_PATTERN = re.compile(r"@[A-Za-z0-9_-]+")
SHOT_LABEL_PATTERN = re.compile(r"(?i)\bS(?:HOT)?\s*\d{1,3}\s*[:：\-]?\s*")
DISPLAY_DEVICE_TERMS = (
    "手机",
    "平板",
    "笔记本",
    "屏幕",
    "电脑屏幕",
    "显示器",
    "监视器",
    "电视屏幕",
    "相机显示屏",
    "车载屏幕",
    "终端屏幕",
    "电子阅读器",
)
DISPLAY_INTERACTION_TERMS = (
    "看",
    "盯",
    "凝视",
    "浏览",
    "阅读",
    "操作",
    "使用",
    "输入",
    "滑动",
    "点击",
    "敲击",
    "拿起",
    "举起",
    "握",
    "捧",
    "面对",
    "查看",
    "确认",
)
DISPLAY_GEOMETRY_HEADING = "设备可见面几何"
DISPLAY_READABLE_CAMERA_TERMS = (
    "越肩",
    "主观镜头",
    "人物主观",
    "POV",
    "INSERT CUT",
    "插入镜头",
)
DISPLAY_SURFACE_PATTERN = (
    r"(?:手机|平板|笔记本(?:电脑)?|电脑|显示器|监视器|电视|相机|车载|终端|"
    r"电子阅读器)?(?:的)?(?:屏幕|显示面)"
)
DISPLAY_DETAIL_PATTERN = (
    r"数字|数值|金额|余额|读数|数据|图表|曲线|走势图|K线|界面|页面|文字|"
    r"消息|通知|验证码|二维码|订单|账户|行情|股价|价格|收益|亏损|盈利|照片|"
    r"视频|地图|导航|邮件|标题|比分|内容"
)
DISPLAY_CONTENT_CLAUSE_PATTERN = re.compile(
    rf"[^，。；：\n]*(?:{DISPLAY_SURFACE_PATTERN})[^，。；：\n]*"
    rf"(?:{DISPLAY_DETAIL_PATTERN})[^，。；：\n]*"
    rf"|[^，。；：\n]*(?:{DISPLAY_DETAIL_PATTERN})[^，。；：\n]*"
    rf"(?:{DISPLAY_SURFACE_PATTERN})[^，。；：\n]*"
)
DISPLAY_OUTPUT_CLAUSE_PATTERN = re.compile(
    rf"[^，。；：\n]*(?:{DISPLAY_SURFACE_PATTERN})[^，。；：\n]*"
    r"(?:显示(?!面)|呈现|写着|展示|弹出|刷新出)[^，。；：\n]*"
)
DISPLAY_COLOR_CUE_CLAUSE_PATTERN = re.compile(
    rf"[^，。；：\n]*(?:{DISPLAY_SURFACE_PATTERN}|屏幕光|屏幕背光)"
    r"[^，。；：\n]*(?:红|绿|橙|涨|跌|警示)[^，。；：\n]*"
    rf"|[^，。；：\n]*(?:红|绿|橙|涨|跌|警示)[^，。；：\n]*"
    rf"(?:{DISPLAY_SURFACE_PATTERN}|屏幕光|屏幕背光)[^，。；：\n]*"
)
DISPLAY_DETAIL_COMPOUND_PATTERN = re.compile(
    r"(?:亏损|盈利|收益|账户|股价|行情|价格|订单|聊天|地图|导航|交易|邮件|"
    r"日程|比分|新闻|标题)(?:的)?(?:数值|数字|金额|余额|数据|图表|曲线|"
    r"走势图|K线|界面|页面|读数|文字|消息|通知|二维码|照片|视频|内容)"
    r"|账户余额|消息内容|邮件正文"
)
DISPLAY_STANDALONE_VISUAL_PATTERN = re.compile(
    r"K线|走势图|图表|曲线|界面|页面|读数|数值|数字|金额|余额|数据|文字|"
    r"消息|通知|验证码|二维码|订单|账户|行情|股价|价格|照片|视频|地图|导航|"
    r"邮件|标题|比分"
)
DISPLAY_CAMERA_TARGET_PATTERN = re.compile(
    rf"(?:推近|推进|靠近|拉近|对准|聚焦|跟焦|特写|近景|放大)"
    rf"[^，。；\n]{{0,20}}(?:{DISPLAY_SURFACE_PATTERN}|手机|平板|笔记本|电脑|设备)"
    rf"|(?:{DISPLAY_SURFACE_PATTERN}|手机|平板|笔记本|电脑|设备)"
    r"[^，。；\n]{0,12}(?:特写|近景|推近|推进|靠近|拉近|对准|聚焦|跟焦|放大)"
)
PROMPT_SECTION_HEADINGS = (
    "人物锚点",
    "场景上下文",
    "有效参考",
    "有效参考资产",
    "场景空间图",
    "首帧与空间调度",
    "连续性状态",
    DISPLAY_GEOMETRY_HEADING,
    "格式模式",
    "光学",
    "摄影机",
    "动作时间轴",
    "表演",
    "物理",
    "灯光",
    "正向约束",
    "音频",
)
DEFAULT_STYLE_BIBLE = (
    "真实社会纪实电影质感，自然生活化表演，克制的低对比方向光；"
    "60%环境中性色、30%深灰阴影、10%来自现场的暖色实用光，"
    "真实皮肤、布料与旧化表面，统一自然颗粒和稳定曝光。"
)


class ProductionPackageBuilder:
    def __init__(
        self,
        llm: LLMService,
        store: ProjectStore,
        llm_concurrency: int = 3,
        *,
        planning_llm: LLMService | None = None,
        llm_profile: str = "",
    ) -> None:
        self.llm = llm
        self.planning_llm = planning_llm or llm
        self.store = store
        self.llm_concurrency = max(1, llm_concurrency)
        self.llm_profile = llm_profile
        self.warnings: list[str] = []
        self.ai_successes = 0
        self.ai_failures = 0
        self.skill_sources: dict[str, VerbatimSkill] = {}
        self.compliance_hits: list[ComplianceHit] = []

    async def build(
        self,
        session: Session,
        topic: Topic,
        duration: int,
        *,
        reuse: bool = True,
    ) -> ProductionPackageData:
        self._reset_diagnostics()
        self._load_verbatim_skills()
        script = self.store.load_text(session, topic.id, "script") or ""
        if not script.strip():
            raise RuntimeError("缺少已通过审校的剧本")

        context = narrative_context(session, topic, self.store)
        story = context.get("story_arc", {})
        review = self.store.load_json(session, topic.id, "review") or {}
        script_meta = self.store.load_json(session, topic.id, "script_meta") or {}
        self._record_upstream_fallbacks(story, script_meta)
        story_quality = NarrativeQualityData.model_validate(story.get("quality") or {})
        upstream_ready = bool(
            story.get("generation_mode") == "ai_generated"
            and story_quality.passed
            and script_meta.get("generation_mode") == "ai_generated"
            and review.get("passed", False)
        )
        target_unit_count = self._target_generation_unit_count(duration)
        plan_fingerprint = self._plan_fingerprint(script, context, duration)
        previous = self._previous_package(session, topic) if reuse else None
        plan_reusable = bool(
            previous is not None
            and previous.plan_source == "ai_generated"
            and previous.plan_fingerprint
            and previous.plan_fingerprint == plan_fingerprint
            and len(previous.shots) == target_unit_count
        )
        plan_source = "template_fallback"
        if upstream_ready and plan_reusable and previous is not None:
            # 剧本、素材、时长、档位和 SKILL 原文都没变，角色与分镜两次高成本调用可以整个跳过。
            style_bible = previous.style_bible
            characters = list(previous.characters)
            shot_plan = [
                ShotPlanDraft.model_validate(
                    shot.model_dump(mode="json", include=set(ShotPlanDraft.model_fields))
                )
                for shot in previous.shots
            ]
            audio_plan = previous.audio_plan
            plan_source = "ai_generated"
        elif upstream_ready:
            planning_failures = self.ai_failures
            style_bible, characters = await self._build_characters(
                session, topic, script, context
            )
            shot_plan, audio_plan = await self._build_shot_plan(
                session,
                topic,
                script,
                context,
                characters,
                duration,
                target_unit_count,
            )
            if self.ai_failures == planning_failures:
                plan_source = "ai_generated"
        else:
            self.ai_failures += 1
            self.warnings.append(
                "上游叙事质量门未通过，已跳过高成本角色与逐生成单元模型调用；"
                "当前包只用于诊断。"
            )
            style_bible, characters = self._normalize_characters(
                self._fallback_character_catalog(context), context
            )
            raw_plan = self._fallback_shot_plan(
                script, characters, duration, context, target_unit_count
            )
            shot_plan = self._normalize_shot_plan(
                raw_plan,
                script,
                context,
                characters,
                duration,
                target_unit_count,
            )
            audio_plan = self._normalize_audio_plan(
                GlobalAudioPlanData(), shot_plan, duration
            )
        animatic = self._check_animatic(shot_plan, duration)
        shot_prompt_ready = upstream_ready and animatic.passed
        if upstream_ready and not animatic.passed:
            self.ai_failures += 1
            self.warnings.append(
                "低成本节奏样片未通过，已跳过逐生成单元高成本模型调用："
                + "；".join(animatic.issues[:3])
            )
        # 和 AI 调用同一个门。上游没过时这个包只用于诊断，掺入旧的 AI 正文会让
        # 它看起来比实际更完整。
        reusable_bodies = (
            self._reusable_bodies(
                previous, shot_plan, style_bible, characters, audio_plan, plan_fingerprint
            )
            if previous is not None and shot_prompt_ready
            else {}
        )
        if reusable_bodies:
            self.warnings.append(
                f"已复用上一版通过校验的 {len(reusable_bodies)} 个生成单元提示词，"
                "本次只重新生成缺失或失效的单元。"
            )
        shots = await self._build_shot_prompts(
            session,
            topic,
            script,
            context,
            style_bible,
            characters,
            shot_plan,
            audio_plan,
            allow_ai=shot_prompt_ready,
            reusable_bodies=reusable_bodies,
            plan_fingerprint=plan_fingerprint,
        )
        production_mode = self._generation_mode(shots)
        readiness = self._build_readiness(
            story=story,
            review=review,
            script_meta=script_meta,
            animatic=animatic,
            production_mode=production_mode,
        )
        if not readiness.passed and production_mode == "ai_optimized":
            production_mode = "mixed"
        return ProductionPackageData(
            topic_id=topic.id,
            generated_at=datetime.now(UTC).isoformat(),
            duration_seconds=duration,
            llm_profile=self.llm_profile,
            generation_unit_count=len(shots),
            internal_shot_count=sum(len(shot.internal_shots) for shot in shots),
            narrative_mode=story.get("narrative_mode", "cinematic_human_story"),
            story_generation_mode=story.get("generation_mode", "legacy"),
            script_generation_mode=script_meta.get("generation_mode", "legacy"),
            generation_mode=production_mode,
            plan_fingerprint=plan_fingerprint,
            plan_source=plan_source,
            reused_unit_count=len(reusable_bodies),
            ready_for_generation=readiness.passed,
            readiness=readiness,
            narrative_quality=story_quality,
            animatic=animatic,
            audio_plan=audio_plan,
            warnings=self._warnings_with_compliance(shots),
            style_bible=style_bible,
            skills=[
                SkillStageData(
                    order=1,
                    skill="lira-image-prompts",
                    purpose="角色、造型与参考图提示词",
                    source_sha256=self._skill_sha256("lira-image-prompts"),
                ),
                SkillStageData(
                    order=2,
                    skill="acting-ai-video",
                    purpose="角色表演主档案与生成单元内部表演适配",
                    source_sha256=self._skill_sha256("acting-ai-video"),
                ),
                SkillStageData(
                    order=3,
                    skill="cinedance-higgsfield",
                    purpose="可一次生成多个内部镜头的 10 秒调度提示词",
                    source_sha256=self._skill_sha256("cinedance-higgsfield"),
                ),
            ],
            characters=characters,
            shots=shots,
        )

    async def regenerate_shot(
        self,
        session: Session,
        topic: Topic,
        shot_id: str,
        current_prompt: str = "",
    ) -> ProductionPackageData:
        self._reset_diagnostics()
        self._load_verbatim_skills()
        raw_package = self.store.load_json(session, topic.id, "production_package")
        if not raw_package:
            raise RuntimeError("影视生成包尚未生成")
        package = ProductionPackageData.model_validate(raw_package)
        shot_index = next(
            (index for index, shot in enumerate(package.shots) if shot.shot_id == shot_id),
            None,
        )
        if shot_index is None:
            raise KeyError(shot_id)

        script = self.store.load_text(session, topic.id, "script") or ""
        if not script.strip():
            raise RuntimeError("缺少已通过审校的剧本")
        context = narrative_context(session, topic, self.store)
        story = context.get("story_arc", {})
        review = self.store.load_json(session, topic.id, "review") or {}
        script_meta = self.store.load_json(session, topic.id, "script_meta") or {}
        self._record_upstream_fallbacks(story, script_meta)
        previous = package.shots[shot_index]
        safe_current_prompt = self._prompt_body_only(
            self._replace_people(
                self._remove_internal_ids(
                    REFERENCE_TAG_PATTERN.sub("用户提供的参考角色", current_prompt)
                ),
                self._known_people(context),
                "当事人",
            )
        )
        regenerated = await self._build_shot_prompts(
            session,
            topic,
            script,
            context,
            package.style_bible,
            package.characters,
            [ShotPlanDraft.model_validate(previous.model_dump())],
            package.audio_plan,
            step_prefix=f"production:regenerate:{shot_id}:r{previous.revision + 1}",
            previous_prompts={shot_id: safe_current_prompt} if safe_current_prompt else {},
            previous_ambient={shot_id: previous.ambient_audio},
            previous_sources={shot_id: previous.prompt_source},
            plan_fingerprint=package.plan_fingerprint,
        )
        replacement = regenerated[0].model_copy(
            update={"revision": previous.revision + 1}
        )
        package.shots[shot_index] = replacement
        package.generated_at = datetime.now(UTC).isoformat()
        # 状态全部重新派生。以前这里往 blockers 里 append 且从不清除，逐个单元修完
        # 之后包也永远回不到就绪。
        package.warnings = self._warnings_with_compliance(package.shots)
        package.generation_mode = self._generation_mode(package.shots)
        package.readiness = self._build_readiness(
            story=story,
            review=review,
            script_meta=script_meta,
            animatic=package.animatic,
            production_mode=package.generation_mode,
        )
        if not package.readiness.passed and package.generation_mode == "ai_optimized":
            package.generation_mode = "mixed"
        package.ready_for_generation = package.readiness.passed
        package.reused_unit_count = 0
        return package

    async def _build_characters(
        self,
        session: Session,
        topic: Topic,
        script: str,
        context: dict,
    ) -> tuple[str, list[CharacterAssetData]]:
        required_skills = {"lira-image-prompts", "acting-ai-video"}
        if not required_skills.issubset(self.skill_sources):
            return self._normalize_characters(
                self._fallback_character_catalog(context), context
            )
        prompt = render_prompt(
            "character_assets",
            topic=topic.title,
            script=script,
            context=stable_json(context),
            lira_skill=self.skill_sources["lira-image-prompts"].content,
            acting_skill=self.skill_sources["acting-ai-video"].content,
        )
        try:
            draft = await self.llm.generate_model(
                session,
                topic.id,
                "production:characters",
                "你是 Lira 图像提示词优化师与影视表演导演。只使用已核验人物依据。",
                prompt,
                CharacterCatalogDraft,
            )
            self.ai_successes += 1
        except Exception as error:
            self._record_ai_failure("角色资产", error)
            draft = self._fallback_character_catalog(context)
        style_bible, characters = self._normalize_characters(draft, context)
        if characters or not self._known_people(context):
            return style_bible, characters
        self._record_ai_failure("角色资产", ValueError("角色依据未通过校验"))
        return self._normalize_characters(self._fallback_character_catalog(context), context)

    def _normalize_characters(
        self, draft: CharacterCatalogDraft, context: dict
    ) -> tuple[str, list[CharacterAssetData]]:
        facts = context.get("facts", [])
        valid_fact_ids = {item.get("id", "") for item in facts}
        known_people = self._known_people(context)
        characters: list[CharacterAssetData] = []
        for item in draft.characters[:6]:
            source_fact_ids = [
                fact_id
                for fact_id in dict.fromkeys(item.source_fact_ids)
                if fact_id in valid_fact_ids
            ]
            if not source_fact_ids:
                continue
            index = len(characters) + 1
            prompt_label = item.prompt_label.strip()
            if any(person and person in prompt_label for person in known_people):
                prompt_label = f"纪实还原角色 {index}"
            replacement = prompt_label or f"纪实还原角色 {index}"
            payload = item.model_dump()
            payload.update(
                {
                    "prompt_label": replacement,
                    "source_fact_ids": source_fact_ids,
                    "visual_anchor": self._replace_people(
                        item.visual_anchor, known_people, replacement
                    ),
                    "wardrobe_anchor": self._replace_people(
                        item.wardrobe_anchor, known_people, replacement
                    ),
                    "image_prompt": self._replace_people(
                        item.image_prompt, known_people, replacement
                    ),
                    "acting_profile": self._replace_people(
                        item.acting_profile, known_people, replacement
                    ),
                    "voice_prompt": self._replace_people(
                        item.voice_prompt, known_people, replacement
                    ),
                }
            )
            characters.append(
                CharacterAssetData(
                    id=f"char_{index:02d}",
                    reference_token=f"CHAR_{index:02d}",
                    **payload,
                )
            )
        return draft.style_bible.strip() or DEFAULT_STYLE_BIBLE, characters

    def _fallback_character_catalog(self, context: dict) -> CharacterCatalogDraft:
        by_person: dict[str, list[str]] = {}
        for fact in context.get("facts", []):
            for person in fact.get("people", []):
                if person:
                    by_person.setdefault(person, []).append(fact.get("id", ""))
        characters: list[CharacterAssetDraft] = []
        for index, fact_ids in enumerate(by_person.values(), 1):
            if index > 4:
                break
            label = f"纪实还原当事人 {index}"
            characters.append(
                CharacterAssetDraft(
                    prompt_label=label,
                    role="lead" if index == 1 else "supporting",
                    story_function="承载已核验个人案例的影视化还原视角",
                    source_fact_ids=[fact_id for fact_id in fact_ids if fact_id],
                    visual_anchor="成年纪实还原演员，普通真实体型与自然生活痕迹，面部和身体比例稳定",
                    wardrobe_anchor="符合事件时期与生活语境的无品牌日常服装，材质和磨损跨镜头一致",
                    image_prompt=(
                        f"三张同一位{label} 的真实棚拍照片并排组成电影选角页。"
                        "左侧为从头到脚的正面自然站姿，"
                        "中间为相同站姿的完整背面，右侧为头肩近景；三张保持同一张脸、同一体型、同一服装和生活痕迹。"
                        "平整中性灰背景，单侧柔和方向光与自然阴影衰减，真实皮肤纹理、真实布料纤维和克制的现代纪录片质感。"
                        "服装以环境中性色为主，深灰结构色辅助，现场暖色仅作小面积点缀。"
                    ),
                    acting_profile=(
                        f"{label}以低重心和略微收紧的肩背承载长期压力，行动先观察再决定，目标是让自己的选择被认真听见。"
                        "说话前会短暂吞咽并把手上的日常事务停住，压力升高时拇指缓慢摩擦指节来维持体面；掩饰时嘴角保持礼貌，"
                        "只有在核心生活代价被提及时面具才出现一瞬松动。眼神持续在对方、出口和手中物件之间微扫，真实眨眼，"
                        "视线总比头部先到目标。步态是克制的“负重步”，全脚掌落地、步幅短而稳定；面对善意时呼吸才真正放松。"
                    ),
                    voice_prompt="",
                    default_use_reference=index == 1,
                )
            )
        return CharacterCatalogDraft(style_bible=DEFAULT_STYLE_BIBLE, characters=characters)

    async def _build_shot_plan(
        self,
        session: Session,
        topic: Topic,
        script: str,
        context: dict,
        characters: list[CharacterAssetData],
        duration: int,
        target_unit_count: int,
    ) -> tuple[list[ShotPlanDraft], GlobalAudioPlanData]:
        prompt = render_prompt(
            "shot_plan",
            topic=topic.title,
            duration=duration,
            target_generation_unit_count=target_unit_count,
            script=script,
            characters=stable_json([item.model_dump(mode="json") for item in characters]),
            context=stable_json(context),
        )
        audio_draft = GlobalAudioPlanData()
        try:
            result = await self.planning_llm.generate_model(
                session,
                topic.id,
                "production:shot_plan",
                "你是严格的纪录片分镜规划师。不得改写旁白或创造现实事实。",
                prompt,
                ShotPlanResult,
            )
            if len(result.shots) != target_unit_count:
                raise ValueError("生成单元数量不符合目标")
            raw_shots = result.shots
            audio_draft = result.audio_plan
            self.ai_successes += 1
        except Exception as error:
            self._record_ai_failure("镜头规划", error)
            raw_shots = self._fallback_shot_plan(
                script, characters, duration, context, target_unit_count
            )
        normalized = self._normalize_shot_plan(
            raw_shots, script, context, characters, duration, target_unit_count
        )
        return normalized, self._normalize_audio_plan(audio_draft, normalized, duration)

    def _normalize_shot_plan(
        self,
        raw_shots: list[ShotPlanDraft],
        script: str,
        context: dict,
        characters: list[CharacterAssetData],
        duration: int,
        target_unit_count: int,
    ) -> list[ShotPlanDraft]:
        if len(raw_shots) != target_unit_count:
            raw_shots = self._fallback_shot_plan(
                script, characters, duration, context, target_unit_count
            )
        valid_character_ids = {item.id for item in characters}
        valid_event_ids = {item.get("id", "") for item in context.get("events", [])}
        valid_source_ids = {item.get("id", "") for item in context.get("sources", [])}
        beats = context.get("story_arc", {}).get("beats", [])
        beat_by_id = {beat.get("beat_id", ""): beat for beat in beats}
        windows = self._generation_unit_windows(duration, target_unit_count)
        normalized: list[ShotPlanDraft] = []
        for index, item in enumerate(raw_shots[:target_unit_count]):
            start, end = windows[index]
            beat_index = (
                min(len(beats) - 1, (index * len(beats)) // target_unit_count)
                if beats
                else 0
            )
            beat_end = (
                max(
                    beat_index + 1,
                    min(
                        len(beats),
                        ((index + 1) * len(beats)) // target_unit_count,
                    ),
                )
                if beats
                else 0
            )
            default_beats = beats[beat_index:beat_end] if beats else []
            default_beat = default_beats[0] if default_beats else {}
            requested_beat_ids = {
                value
                for value in [item.beat_id, *item.beat_ids]
                if value in beat_by_id
            }
            requested_beat_ids.update(
                beat.get("beat_id", "") for beat in default_beats
            )
            beat_ids = [
                beat.get("beat_id", "")
                for beat in beats
                if beat.get("beat_id", "") in requested_beat_ids
            ][:3]
            if not beats:
                beat_ids = list(
                    dict.fromkeys(value for value in [item.beat_id, *item.beat_ids] if value)
                )[:3]
            beat_id = beat_ids[0] if beat_ids else ""
            beat = beat_by_id.get(beat_id) or default_beat
            sequence_id = (
                item.sequence_id
                if item.beat_id and item.sequence_id
                else f"sequence_{beat_index + 1:02d}"
            )
            value_before = item.value_before or beat.get("value_before", "")
            value_after = item.value_after or beat.get("value_after", "")
            entry_state = item.entry_state or value_before or "当前局势清楚可读"
            exit_state = item.exit_state or value_after or "当前信息已改变局势"
            intensity = (
                item.intensity
                if item.beat_id or not beat
                else int(beat.get("intensity", item.intensity))
            )
            event_ids = [
                value
                for value in dict.fromkeys(item.event_ids)
                if value in valid_event_ids
            ]
            if not event_ids:
                event_ids = [
                    value
                    for grouped_beat in (default_beats or [beat])
                    for value in grouped_beat.get("event_ids", [])
                    if value in valid_event_ids
                ]
            source_ids = [
                value
                for value in dict.fromkeys(item.source_ids)
                if value in valid_source_ids
            ]
            if not source_ids:
                source_ids = [
                    value
                    for grouped_beat in (default_beats or [beat])
                    for value in grouped_beat.get("source_ids", [])
                    if value in valid_source_ids
                ]
            beat_changes = item.beat_changes or [
                f"第一拍：主体已经处于“{entry_state}”的可见状态",
                "第二拍：新信息使当前策略失效，手上事务或视线出现明确中断",
                f"第三拍：以“{exit_state}”的身体状态结束",
            ]
            narration = self._fit_script_text(item.narration, script, end - start)
            spoken_limit = max(8, math.floor((end - start) * 4.5))
            remaining_dialogue_chars = max(
                0, spoken_limit - self._spoken_char_count(narration)
            )
            dialogue = self._fit_script_text(
                item.dialogue,
                script,
                end - start,
                max_chars=remaining_dialogue_chars,
            )
            active_character_ids = [
                value
                for value in dict.fromkeys(item.active_character_ids)
                if value in valid_character_ids
            ]
            visual_brief = self._remove_shot_labels(item.visual_brief).strip()
            narrative_function = item.narrative_function or beat.get(
                "narrative_function", "叙事推进"
            )
            cut_motivation = item.cut_motivation or (
                "动作中断形成切点" if index % 2 == 0 else "视线落点形成切点"
            )
            internal_shots = self._normalize_internal_shots(
                item,
                unit_id=f"shot_{index + 1:02d}",
                unit_duration=end - start,
                unit_index=index,
                unit_count=target_unit_count,
                visual_brief=visual_brief,
                has_characters=bool(active_character_ids),
                beat_changes=beat_changes,
                entry_state=entry_state,
                exit_state=exit_state,
                cut_motivation=cut_motivation,
                intensity=intensity,
                narrative_function=narrative_function,
            )
            normalized.append(
                ShotPlanDraft(
                    shot_id=f"shot_{index + 1:02d}",
                    title=self._remove_shot_labels(item.title).strip()
                    or f"生成单元 {index + 1}",
                    start_second=start,
                    end_second=end,
                    narration=narration,
                    dialogue=dialogue,
                    visual_brief=visual_brief,
                    active_character_ids=active_character_ids,
                    event_ids=event_ids,
                    source_ids=source_ids,
                    sequence_id=sequence_id,
                    beat_id=beat_id,
                    beat_ids=beat_ids,
                    narrative_function=narrative_function,
                    objective=item.objective or beat.get("objective", "让当前信息改变局势"),
                    obstacle=item.obstacle or beat.get("obstacle", "当前策略受到现实阻碍"),
                    stakes=item.stakes or beat.get("stakes", "失败会让人物处境继续恶化"),
                    tactic=item.tactic or beat.get("tactic", "先观察，再改变行动策略"),
                    beat_changes=beat_changes[:4],
                    entry_state=entry_state,
                    exit_state=exit_state,
                    value_before=value_before,
                    value_after=value_after,
                    cause_link=item.cause_link
                    or beat.get("cause_link", "以当前可见变化回应前一问题"),
                    cut_motivation=cut_motivation,
                    audio_bridge=item.audio_bridge
                    or (
                        "当前环境声在画面结束前先行收紧"
                        if index % 2 == 0
                        else "切点后保留半秒动作余音"
                    ),
                    intensity=intensity,
                    format_mode=(
                        "single_take"
                        if len(internal_shots) == 1
                        else "controlled_multishot"
                    ),
                    internal_shots=internal_shots,
                )
            )
        return normalized

    @classmethod
    def _normalize_internal_shots(
        cls,
        item: ShotPlanDraft,
        *,
        unit_id: str,
        unit_duration: int,
        unit_index: int,
        unit_count: int,
        visual_brief: str,
        has_characters: bool,
        beat_changes: list[str],
        entry_state: str,
        exit_state: str,
        cut_motivation: str,
        intensity: int,
        narrative_function: str,
    ) -> list[InternalShotData]:
        requested = item.internal_shots[:3]
        count = len(requested) or cls._target_internal_shot_count(
            unit_index, unit_count, intensity, narrative_function
        )
        windows = cls._internal_shot_windows(
            unit_duration,
            count,
            hold_ending=unit_index == unit_count - 1,
        )
        sizes = (
            (["MS"] if has_characters else ["WS"])
            if count == 1
            else (
                (["WS", "CU"] if has_characters else ["WS", "INSERT"])
                if count == 2
                else (
                    ["WS", "MS", "CU"]
                    if has_characters
                    else ["WS", "MS", "INSERT"]
                )
            )
        )
        fovs = {
            "EWS": 107,
            "WS": 84,
            "MS": 47,
            "MCU": 29,
            "CU": 18,
            "ECU": 12,
            "INSERT": 18,
        }
        coverage = (
            ["让动作和反应在同一长镜头内完成"]
            if count == 1
            else (
                ["建立空间与正在发生的动作", "让结果落在人物反应或关键物件上"]
                if count == 2
                else [
                    "建立空间与正在发生的动作",
                    "阻碍进入并迫使当前策略改变",
                    "让结果落在人物反应或关键物件上",
                ]
            )
        )
        normalized: list[InternalShotData] = []
        carried_state = entry_state
        for internal_index, (start_offset, end_offset) in enumerate(windows):
            source = requested[internal_index] if internal_index < len(requested) else None
            is_last = internal_index == count - 1
            default_change = beat_changes[min(internal_index, len(beat_changes) - 1)]
            internal_exit = (
                exit_state
                if is_last
                else (
                    source.exit_state
                    if source and source.exit_state
                    else default_change
                )
            )
            size = source.shot_size if source else sizes[internal_index]
            fov = source.fov_degrees if source else fovs[size]
            normalized.append(
                InternalShotData(
                    internal_shot_id=f"{unit_id}_{chr(97 + internal_index)}",
                    start_offset_seconds=start_offset,
                    end_offset_seconds=end_offset,
                    shot_size=size,
                    fov_degrees=fov,
                    visual_action=(
                        source.visual_action
                        if source
                        else f"{visual_brief}；{coverage[internal_index]}；{default_change}"
                    ),
                    camera=(
                        source.camera
                        if source and source.camera
                        else cls._default_internal_camera(size, fov, has_characters)
                    ),
                    performance=(
                        source.performance
                        if source and source.performance
                        else (
                            f"可见变化：{default_change}；反应先于语言，眼神先于头部移动。"
                            if has_characters
                            else "物件或环境状态以明确物理原因发生可见变化。"
                        )
                    ),
                    entry_state=carried_state,
                    exit_state=internal_exit,
                    cut_in=(
                        "START"
                        if internal_index == 0
                        else (
                            source.cut_in
                            if source and source.cut_in != "START"
                            else "HARD CUT"
                        )
                    ),
                    cut_motivation=(
                        source.cut_motivation
                        if source and source.cut_motivation
                        else cut_motivation
                    ),
                    intensity=max(
                        0,
                        min(100, (source.intensity if source else intensity) + internal_index * 3),
                    ),
                )
            )
            carried_state = internal_exit
        return normalized

    @staticmethod
    def _default_internal_camera(
        shot_size: str, fov_degrees: int, has_characters: bool
    ) -> str:
        if shot_size in {"CU", "ECU"}:
            return (
                f"{fov_degrees}°视野，摄影机保持在人物视线轴同侧，"
                "焦点落在双眼与动作后的微反应。"
            )
        if shot_size == "INSERT":
            return (
                f"{fov_degrees}°视野，独立插入机位只记录当前关键物件的可见状态变化。"
            )
        subject = "人物与环境关系" if has_characters else "环境主体与关键物件"
        return f"{fov_degrees}°视野，摄影机稳定记录{subject}，只执行一次有动机的运动。"

    @staticmethod
    def _target_internal_shot_count(
        index: int, count: int, intensity: int, narrative_function: str
    ) -> int:
        if count <= 1 or index == count - 1:
            return 1
        if index == 0:
            return 2
        position = index / max(1, count - 1)
        if (
            index % 2 == 1
            or 0.62 <= position <= 0.86
            or intensity >= 75
            or any(marker in narrative_function for marker in ("转折", "高潮", "代价"))
        ):
            return 3
        return 2

    @staticmethod
    def _internal_shot_windows(
        duration: int, count: int, *, hold_ending: bool = False
    ) -> list[tuple[int, int]]:
        if count < 1 or count > 3 or duration < count:
            raise ValueError("内部镜头数量无法覆盖当前生成单元")
        if count == 1:
            return [(0, duration)]
        if count == 2:
            split = round(duration * (0.6 if hold_ending else 0.4))
            split = max(1, min(duration - 1, split))
            return [(0, split), (split, duration)]
        first = max(1, min(duration - 2, round(duration * 0.3)))
        second = max(first + 1, min(duration - 1, round(duration * 0.7)))
        return [(0, first), (first, second), (second, duration)]

    def _fallback_shot_plan(
        self,
        script: str,
        characters: list[CharacterAssetData],
        duration: int,
        context: dict | None = None,
        target_count: int | None = None,
    ) -> list[ShotPlanDraft]:
        target_count = target_count or self._target_generation_unit_count(duration)
        unit_windows = self._generation_unit_windows(duration, target_count)
        segments = self._script_segments(script)
        narration_chunk_chars = max(10, math.floor(duration / target_count * 4.2))
        narration_queues = {
            item["start_second"]: self._narration_chunks(
                item.get("narration", ""), narration_chunk_chars
            )
            for item in segments
        }
        event_fact_ids = {
            item.get("id", ""): set(item.get("fact_ids", []))
            for item in (context or {}).get("events", [])
        }
        beats = (context or {}).get("story_arc", {}).get("beats", [])
        shots_per_beat: dict[str, int] = {}
        plans: list[ShotPlanDraft] = []
        for index in range(target_count):
            start, end = unit_windows[index]
            midpoint = (start + end) / 2
            segment = next(
                (
                    item
                    for item in segments
                    if item["start_second"] <= midpoint < item["end_second"]
                ),
                segments[min(index, len(segments) - 1)] if segments else {},
            )
            fact_ids = set(segment.get("fact_ids", []))
            for event_id in segment.get("event_ids", []):
                fact_ids.update(event_fact_ids.get(event_id, set()))
            active = [
                character.id
                for character in characters
                if fact_ids.intersection(character.source_fact_ids)
            ]
            narration_queue = narration_queues.get(segment.get("start_second", -1), [])
            beat_index = min(
                len(beats) - 1, (index * len(beats)) // target_count
            ) if beats else 0
            beat = beats[beat_index] if beats else {}
            beat_id = beat.get("beat_id", f"beat_{beat_index + 1:02d}")
            within_beat = shots_per_beat.get(beat_id, 0)
            shots_per_beat[beat_id] = within_beat + 1
            coverage = ("空间与物件", "人物行动", "反应与结果")[within_beat % 3]
            beat_event_ids = [
                event_id
                for event_id in beat.get("event_ids", [])
                if event_id
            ]
            beat_source_ids = [
                source_id
                for source_id in beat.get("source_ids", [])
                if source_id
            ]
            visual_action = beat.get("visual_action") or segment.get(
                "visual_brief", "与已核验内容对应的克制纪实画面"
            )
            plans.append(
                ShotPlanDraft(
                    shot_id=f"shot_{index + 1:02d}",
                    title=(
                        f"生成单元 {index + 1} · "
                        f"{beat.get('narrative_function', '叙事推进')}"
                    )[:120],
                    start_second=start,
                    end_second=end,
                    narration=narration_queue.pop(0) if narration_queue else "",
                    dialogue="",
                    visual_brief=(
                        f"{visual_action}；当前 10 秒生成单元围绕同一地点、同一时间和同一动作链，"
                        f"通过“空间建立—{coverage}—结果落点”形成局部小弧线。"
                    ),
                    active_character_ids=active,
                    event_ids=beat_event_ids or segment.get("event_ids", []),
                    source_ids=beat_source_ids or segment.get("source_ids", []),
                    sequence_id=f"sequence_{beat_index + 1:02d}",
                    beat_id=beat_id,
                    narrative_function=beat.get("narrative_function", "叙事推进"),
                    objective=beat.get("objective", "让当前事实改变局势"),
                    obstacle=beat.get("obstacle", "当前策略受到阻碍"),
                    stakes=beat.get("stakes", "失败会改变人物处境"),
                    tactic=beat.get("tactic", "改变观察或行动策略"),
                    beat_changes=[
                        f"主体以“{beat.get('value_before', '当前状态')}”进入",
                        "信息到达，动作或视线出现中断",
                        f"主体以“{beat.get('value_after', '改变后的状态')}”离开",
                    ],
                    entry_state=beat.get("value_before", "当前局势清楚可读"),
                    exit_state=beat.get("value_after", "当前信息已改变局势"),
                    value_before=beat.get("value_before", ""),
                    value_after=beat.get("value_after", ""),
                    cause_link=beat.get(
                        "cause_link", "以编辑承接推进，不新增事实因果"
                    ),
                    cut_motivation=("动作中断形成切点" if index % 2 == 0 else "视线落点形成切点"),
                    audio_bridge=("环境声提前半秒收紧" if index % 2 == 0 else "保留半秒动作余音"),
                    intensity=max(
                        0,
                        min(100, int(beat.get("intensity", 50)) + (within_beat - 1) * 4),
                    ),
                )
            )
        return plans

    async def _build_shot_prompts(
        self,
        session: Session,
        topic: Topic,
        script: str,
        context: dict,
        style_bible: str,
        characters: list[CharacterAssetData],
        shot_plan: list[ShotPlanDraft],
        audio_plan: GlobalAudioPlanData,
        *,
        allow_ai: bool = True,
        step_prefix: str = "production:shots",
        previous_prompts: dict[str, str] | None = None,
        previous_ambient: dict[str, str] | None = None,
        previous_sources: dict[str, str] | None = None,
        reusable_bodies: dict[str, tuple[str, str]] | None = None,
        plan_fingerprint: str = "",
    ) -> list[CinematicShotData]:
        by_id = {item.id: item for item in characters}
        # 复用的正文直接进 generated，后处理链（人物锚点 → 设备几何 → 音频 → 合规）
        # 照常重跑，所以复用单元和新生成单元走的是完全相同的路径。
        reused = dict(reusable_bodies or {})
        generated: dict[str, tuple[str, str]] = dict(reused)
        ai_ready_ids: set[str] = set(reused)
        skill_ready = allow_ai and {
            "acting-ai-video",
            "cinedance-higgsfield",
        }.issubset(self.skill_sources)
        continuity_by_id: dict[str, dict] = {}
        for index, shot in enumerate(shot_plan):
            previous = shot_plan[index - 1] if index else None
            following = shot_plan[index + 1] if index + 1 < len(shot_plan) else None
            continuity_by_id[shot.shot_id] = {
                "current_entry_state_to_render": shot.entry_state,
                "current_exit_state_to_leave": shot.exit_state,
                "inherited_exit_state": previous.exit_state if previous else shot.entry_state,
                "current_sequence_id": shot.sequence_id,
                "current_beat_id": shot.beat_id,
                "cut_motivation": shot.cut_motivation,
                "audio_bridge": shot.audio_bridge,
                "following_entry_target": following.entry_state if following else "片尾收束",
                "internal_shots": [
                    item.model_dump(mode="json") for item in shot.internal_shots
                ],
                "rule": (
                    "最终提示词只重述当前 10 秒生成单元状态；内部镜头按明确时间点切换，"
                    "跨切保持身份、空间、视线、道具、光线和动作连续。"
                ),
            }
        # 批次必须切在"待生成集合"上。切在全量计划上的话，9 个单元命中 7 个还是发 3 批。
        pending = [shot for shot in shot_plan if shot.shot_id not in reused]
        batch_requests: list[tuple[int, list[ShotPlanDraft], str]] = []
        for offset in range(0, len(pending), 4):
            chunk = pending[offset : offset + 4]
            if not skill_ready:
                continue
            active_ids = {
                character_id for shot in chunk for character_id in shot.active_character_ids
            }
            prompt_shots = []
            prompt_previous: dict[str, str] = {}
            for item in chunk:
                previous_body = (previous_prompts or {}).get(item.shot_id, "")
                source = f"{item.visual_brief}\n{previous_body}"
                if self._is_reaction_display_shot(source, item):
                    prompt_item = item.model_copy(
                        update={
                            "visual_brief": self._neutralize_hidden_display_details(
                                item.visual_brief
                            )
                        }
                    )
                else:
                    prompt_item = item
                prompt_payload = prompt_item.model_dump(mode="json")
                prompt_payload["continuity_ledger"] = continuity_by_id[item.shot_id]
                prompt_shots.append(prompt_payload)
                if previous_body:
                    prompt_previous[item.shot_id] = self._ensure_display_geometry(
                        previous_body, item
                    )

            prompt = render_prompt(
                "cinematic_shots",
                style_bible=style_bible,
                characters=stable_json(
                    [
                        by_id[character_id].model_dump(mode="json")
                        for character_id in sorted(active_ids)
                        if character_id in by_id
                    ]
                ),
                shots=stable_json(prompt_shots),
                continuity_ledger=stable_json(
                    {
                        item.shot_id: continuity_by_id[item.shot_id]
                        for item in chunk
                    }
                ),
                audio_plan=stable_json(audio_plan.model_dump(mode="json")),
                previous_prompts=stable_json(prompt_previous),
                acting_skill=self.skill_sources["acting-ai-video"].content,
                cinedance_skill=self.skill_sources["cinedance-higgsfield"].content,
            )
            batch_requests.append((offset // 4 + 1, chunk, prompt))

        entity_rules = build_entity_rules(
            [
                name
                for item in context.get("facts", [])
                for name in item.get("organizations", [])
            ],
            [name for item in context.get("facts", []) for name in item.get("people", [])],
        )

        semaphore = asyncio.Semaphore(self.llm_concurrency)

        async def generate_batch(
            batch_number: int,
            chunk: list[ShotPlanDraft],
            prompt: str,
        ) -> tuple[int, list[ShotPlanDraft], ShotPromptBatch | None, Exception | None]:
            async with semaphore:
                try:
                    result = await self.llm.generate_model(
                        session,
                        topic.id,
                        f"{step_prefix}:{batch_number}",
                        "你是 CINEDANCE V4 电影提示词导演，并严格执行 Acting 表演系统。",
                        prompt,
                        ShotPromptBatch,
                    )
                    expected_ids = {item.shot_id for item in chunk}
                    returned_ids = {item.shot_id for item in result.shots}
                    if returned_ids != expected_ids:
                        raise ValueError("生成单元提示词返回数量或 ID 不完整")
                    return batch_number, chunk, result, None
                except Exception as error:
                    return batch_number, chunk, None, error

        outcomes = await asyncio.gather(
            *(generate_batch(*request) for request in batch_requests)
        )
        for batch_number, _chunk, result, error in outcomes:
            stage = f"生成单元提示词第 {batch_number} 批"
            if error is not None or result is None:
                self._record_ai_failure(stage, error or RuntimeError("未知错误"))
                continue
            try:
                lossless_failures: list[str] = []
                control_failures: list[str] = []
                for item in result.shots:
                    candidate = item.prompt_body_template.strip()
                    plan = next(
                        plan_item for plan_item in _chunk if plan_item.shot_id == item.shot_id
                    )
                    if not self._prompt_control_complete(candidate, plan):
                        control_failures.append(item.shot_id)
                        continue
                    previous_body = (previous_prompts or {}).get(item.shot_id, "")
                    if previous_body and not self._is_lossless_rewrite(
                        previous_body, candidate
                    ):
                        generated[item.shot_id] = (
                            previous_body,
                            (previous_ambient or {}).get(item.shot_id, ""),
                        )
                        lossless_failures.append(item.shot_id)
                    else:
                        generated[item.shot_id] = (
                            candidate,
                            item.ambient_audio.strip(),
                        )
                        ai_ready_ids.add(item.shot_id)
                if lossless_failures:
                    self._record_ai_failure(
                        stage,
                        ValueError("输出未通过无损保留校验，已保留原提示词"),
                    )
                elif control_failures:
                    self._record_ai_failure(
                        stage,
                        ValueError(
                            "输出缺少连续性、单机位、动作时间轴或表演控制："
                            + "、".join(control_failures)
                        ),
                    )
                else:
                    self.ai_successes += 1
            except Exception as batch_error:
                self._record_ai_failure(stage, batch_error)

        known_people = self._known_people(context)
        shots: list[CinematicShotData] = []
        for plan in shot_plan:
            preserved_body = (previous_prompts or {}).get(plan.shot_id, "")
            body, ambient = generated.get(
                plan.shot_id,
                (
                    preserved_body
                    or self._fallback_prompt_body(plan, by_id, style_bible),
                    (previous_ambient or {}).get(
                        plan.shot_id, "真实克制的现场环境声"
                    ),
                ),
            )
            # 复用时喂回后处理链的就是这份正文，所以它必须在任何拼接之前留存。
            prompt_body_core = body
            if plan.shot_id in ai_ready_ids:
                prompt_source = "ai_optimized"
            elif plan.shot_id in generated or preserved_body:
                # 模型这轮没交付，保留了上一版正文；来源沿用上一版的判定。
                prompt_source = (previous_sources or {}).get(plan.shot_id, "unknown")
            else:
                prompt_source = "template_fallback"
            body = REFERENCE_TAG_PATTERN.sub("参考角色", body)
            body = self._remove_shot_labels(self._remove_internal_ids(body))
            body = self._replace_people(body, known_people, "当事人")
            for character_id in plan.active_character_ids:
                character = by_id.get(character_id)
                if not character:
                    continue
                token = f"[[{character.reference_token}]]"
                if token not in body:
                    body = (
                        f"人物锚点\n{token}：{character.visual_anchor}，当前镜头保持身份与造型一致。\n\n"
                        f"{body}"
                    )
            body = self._ensure_display_geometry(body, plan)
            voice_lines = [
                f"[[{by_id[character_id].reference_token}]] 固定声线："
                f"{by_id[character_id].voice_prompt}"
                for character_id in plan.active_character_ids
                if character_id in by_id and by_id[character_id].voice_prompt
            ]
            body = self._attach_audio(
                body,
                ambient,
                plan.narration,
                plan.dialogue,
                voice_lines if plan.dialogue else [],
                plan.audio_bridge,
            )
            # 合规改写是最后一步：无损检查已经跑完，这里只换风险词面，
            # 不删控制信息，也不碰 Acting SKILL 要求的表演结构。
            body, body_hits = sanitize(body, entity_rules)
            ambient, ambient_hits = sanitize(ambient, entity_rules)
            hits = body_hits + ambient_hits
            if hits:
                self.compliance_hits.extend(hits)
            shots.append(
                CinematicShotData(
                    **plan.model_dump(),
                    duration_seconds=plan.end_second - plan.start_second,
                    prompt_body_template=body,
                    prompt_body_core=prompt_body_core,
                    prompt_source=prompt_source,
                    prompt_fingerprint=self._unit_fingerprint(
                        plan, by_id, style_bible, audio_plan, plan_fingerprint
                    ),
                    ambient_audio=ambient,
                )
            )
        return shots

    def _fallback_prompt_body(
        self,
        plan: ShotPlanDraft,
        characters: dict[str, CharacterAssetData],
        style_bible: str,
    ) -> str:
        character_lines = []
        for character_id in plan.active_character_ids:
            character = characters.get(character_id)
            if character:
                character_lines.append(
                    f"[[{character.reference_token}]]：{character.visual_anchor}，{character.wardrobe_anchor}。"
                )
        subject = "；".join(character_lines) or "画面所需的资料主体在第一帧已经清晰可见。"
        internal_shots = plan.internal_shots or self._normalize_internal_shots(
            plan,
            unit_id=plan.shot_id,
            unit_duration=plan.end_second - plan.start_second,
            unit_index=0,
            unit_count=1,
            visual_brief=plan.visual_brief,
            has_characters=bool(character_lines),
            beat_changes=plan.beat_changes or [plan.entry_state, plan.exit_state],
            entry_state=plan.entry_state,
            exit_state=plan.exit_state,
            cut_motivation=plan.cut_motivation,
            intensity=plan.intensity,
            narrative_function=plan.narrative_function,
        )
        format_mode = (
            "单一连续长镜头；摄影机沿一条明确运动路径完成动作和反应。"
            if len(internal_shots) == 1
            else (
                f"受控多镜头序列，共 {len(internal_shots)} 个内部镜头；"
                "切镜只发生在动作时间轴指定的 HARD CUT、MATCH CUT 或 INSERT CUT 点，"
                "每个内部镜头保持单一机位和单一光学特征。"
            )
        )
        optics = []
        cameras = []
        timeline = []
        for index, internal in enumerate(internal_shots):
            label = chr(65 + index)
            if index:
                timeline.append(
                    f"0:{internal.start_offset_seconds:02d} {internal.cut_in}，"
                    f"切点由{internal.cut_motivation}触发。"
                )
            optics.append(
                f"内部镜头 {label}：{internal.shot_size}，"
                f"{internal.fov_degrees}°视野，段内光学特征不漂移。"
            )
            cameras.append(f"内部镜头 {label}：{internal.camera}")
            timeline.append(
                f"0:{internal.start_offset_seconds:02d} 至 "
                f"0:{internal.end_offset_seconds:02d}，{internal.visual_action}；"
                f"入口状态“{internal.entry_state}”，出口状态“{internal.exit_state}”；"
                f"{internal.performance}"
            )
        performance = (
            f"目标：{plan.objective}。阻碍：{plan.obstacle}。失败代价：{plan.stakes}。"
            f"当前策略：{plan.tactic}。人物用手上事务承载行为，信息落下时动作中断；"
            "眼神先于头部到达目标，持续自然微扫视、真实眨眼与呼吸，反应先于语言完成。"
            if character_lines
            else (
                "当前生成单元没有人物表演；环境主体或资料物件以可见状态变化承载节拍，"
                "变化必须有明确物理原因与结果。"
            )
        )
        optics_text = " ".join(optics)
        cameras_text = " ".join(cameras)
        timeline_text = "\n".join(timeline)
        return (
            f"场景上下文\n{plan.visual_brief}\n\n"
            f"连续性状态\n当前生成单元第一帧已经处于“{plan.entry_state}”；"
            f"结束时留下“{plan.exit_state}”。价值从“{plan.value_before}”变为“{plan.value_after}”。"
            "所有内部切镜保持同一角色身份、地点地理、画面方向、视线、服装、道具手位、"
            "物件状态和主光方向，动作与情绪沿时间轴继续推进。\n\n"
            f"首帧与空间调度\n{subject}主体位于画面三分线，空间关系从第一帧即可读懂，动作已处于可见状态。\n\n"
            f"格式模式\n{format_mode}\n\n"
            f"光学\n{optics_text}\n\n"
            f"摄影机\n{cameras_text}\n\n"
            f"动作时间轴\n{timeline_text}\n\n"
            f"表演\n{performance}\n\n"
            "物理\n脚掌有真实落地、重心转移和摩擦，衣料与头发存在轻微惯性延迟，物件具有明确质量。\n\n"
            f"灯光\n{style_bible}\n\n"
            "正向约束\n身份、造型、站位、视线、道具、屏幕方向和灯光在内部切镜中保持稳定；"
            "切镜只发生在指定时间点，画面清晰自然。"
        )

    def _attach_audio(
        self,
        body: str,
        ambient: str,
        narration: str,
        dialogue: str,
        voice_lines: list[str],
        audio_bridge: str = "",
    ) -> str:
        lines = [
            body.strip(),
            "",
            "音频（使用模型原生音频）",
            ambient or "与当前环境一致的真实同期环境声。",
        ]
        if narration:
            lines.append(f"旁白逐字：\"{narration}\"")
        if dialogue:
            lines.append(f"对白逐字：\"{dialogue}\"")
            lines.extend(voice_lines)
        if audio_bridge:
            lines.append(f"声音切点：{audio_bridge}")
        lines.append("除上述内容外无额外人声，无字幕。")
        return "\n".join(lines).strip()

    def _script_segments(self, script: str) -> list[dict]:
        segments: list[dict] = []
        for match in TIME_SEGMENT_PATTERN.finditer(script):
            start = int(match.group(1)) * 60 + int(match.group(2))
            end = int(match.group(3)) * 60 + int(match.group(4))
            body = match.group(5)
            segments.append(
                {
                    "start_second": start,
                    "end_second": end,
                    "narration": self._markdown_section(body, "旁白"),
                    "visual_brief": self._markdown_section(body, "镜头").lstrip("- "),
                    "fact_ids": ID_PATTERNS["fact"].findall(body),
                    "event_ids": ID_PATTERNS["event"].findall(body),
                    "source_ids": ID_PATTERNS["source"].findall(body),
                }
            )
        return segments

    @staticmethod
    def _generation_unit_windows(
        duration: int, count: int
    ) -> list[tuple[int, int]]:
        expected = math.ceil(duration / 10)
        if count != expected:
            raise ValueError("生成单元数量必须与每 10 秒一次生成相匹配")
        return [
            (index * 10, min(duration, (index + 1) * 10))
            for index in range(count)
        ]

    @staticmethod
    def _normalize_audio_plan(
        draft: GlobalAudioPlanData,
        shots: list[ShotPlanDraft],
        duration: int,
    ) -> GlobalAudioPlanData:
        cues = [
            cue.model_copy(update={"end_second": min(cue.end_second, duration)})
            for cue in draft.cues
            if cue.start_second < duration and min(cue.end_second, duration) > cue.start_second
        ]
        silence_points = sorted(
            {point for point in draft.silence_points if 0 <= point < duration}
        )
        if draft.score_arc.strip() and len(cues) >= 3:
            return draft.model_copy(
                update={"cues": cues, "silence_points": silence_points}
            )

        peak = max(shots, key=lambda shot: shot.intensity)
        opening_end = max(1, round(duration * 0.18))
        escalation_end = max(opening_end + 1, round(duration * 0.58))
        aftermath_start = min(duration - 1, max(escalation_end + 1, round(duration * 0.80)))
        silence_start = min(duration - 1, max(0, peak.start_second))
        silence_end = min(duration, silence_start + 2)
        return GlobalAudioPlanData(
            score_arc=(
                "开场只保留低频脉冲与现场声，人物线建立后加入克制动机；"
                "升级段逐步收紧节奏，转折点抽空配乐形成短暂静默，"
                "结尾只回收一个未解决音型，不做煽情抬升。"
            ),
            music_rule="配乐不解释情绪；关键动作、转折与结尾优先让位给同期声和静默。",
            silence_points=[silence_start],
            cues=[
                AudioCueData(
                    start_second=0,
                    end_second=opening_end,
                    layer="score",
                    description="低频单音脉冲，旋律不进入，保留环境声的真实空间。",
                ),
                AudioCueData(
                    start_second=opening_end,
                    end_second=escalation_end,
                    layer="score",
                    description="一个克制的两音动机缓慢重复，随节拍升级增加质感而不增加音量。",
                ),
                AudioCueData(
                    start_second=silence_start,
                    end_second=silence_end,
                    layer="silence",
                    description="转折动作落下时抽空配乐，只保留呼吸、物件接触或房间底噪。",
                ),
                AudioCueData(
                    start_second=aftermath_start,
                    end_second=duration,
                    layer="score",
                    description="回收开场音型但保持未解决，不抬升、不总结，让环境余音完成结尾。",
                ),
                AudioCueData(
                    start_second=0,
                    end_second=duration,
                    layer="ambient_bridge",
                    description=(
                        "相邻镜头使用 J-cut 或 L-cut 衔接；"
                        "动作余音和环境声承担大部分切点。"
                    ),
                ),
            ],
        )

    @classmethod
    def _check_animatic(
        cls, shots: list[ShotPlanDraft], duration: int
    ) -> AnimaticCheckData:
        issues: list[str] = []
        severe = False
        cursor = 0
        internal_durations: list[int] = []
        internal_intensities: list[int] = []
        internal_counts: list[int] = []
        for index, shot in enumerate(shots):
            unit_duration = shot.end_second - shot.start_second
            if shot.start_second != cursor:
                issues.append(f"生成单元 {index + 1} 与前一单元不连续")
                severe = True
            cursor = shot.end_second
            if unit_duration > 10:
                issues.append(f"生成单元 {index + 1} 超过 10 秒")
                severe = True
            if not all(
                (
                    shot.sequence_id,
                    shot.beat_id,
                    shot.narrative_function,
                    shot.entry_state,
                    shot.exit_state,
                    shot.cut_motivation,
                    shot.audio_bridge,
                )
            ):
                issues.append(f"生成单元 {index + 1} 的连续性账本不完整")
            spoken = cls._spoken_char_count(f"{shot.narration}{shot.dialogue}")
            if spoken > max(8, math.floor(unit_duration * 4.5)):
                issues.append(f"生成单元 {index + 1} 的口播无法在时长内自然完成")

            internal_counts.append(len(shot.internal_shots))
            if not shot.internal_shots:
                issues.append(f"生成单元 {index + 1} 缺少内部镜头设计")
                severe = True
                continue
            if shot.format_mode == "single_take" and len(shot.internal_shots) != 1:
                issues.append(f"生成单元 {index + 1} 的长镜头模式与内部镜头数冲突")
                severe = True
            if shot.format_mode == "controlled_multishot" and len(shot.internal_shots) < 2:
                issues.append(f"生成单元 {index + 1} 的多镜头模式缺少切镜")
                severe = True

            internal_cursor = 0
            carried_state = shot.entry_state
            for internal_index, internal in enumerate(shot.internal_shots):
                if internal.start_offset_seconds != internal_cursor:
                    issues.append(
                        f"生成单元 {index + 1} 的内部镜头时间轴存在空隙或重叠"
                    )
                    severe = True
                if internal.entry_state != carried_state:
                    issues.append(
                        f"生成单元 {index + 1} 的内部镜头状态没有连续承接"
                    )
                if internal_index == 0 and internal.cut_in != "START":
                    issues.append(f"生成单元 {index + 1} 的首个内部镜头切入类型错误")
                if internal_index > 0 and internal.cut_in == "START":
                    issues.append(f"生成单元 {index + 1} 的内部切点未明确")
                internal_duration = (
                    internal.end_offset_seconds - internal.start_offset_seconds
                )
                internal_durations.append(internal_duration)
                internal_intensities.append(internal.intensity)
                internal_cursor = internal.end_offset_seconds
                carried_state = internal.exit_state
            if internal_cursor != unit_duration:
                issues.append(f"生成单元 {index + 1} 的内部镜头没有覆盖完整时长")
                severe = True
            if carried_state != shot.exit_state:
                issues.append(f"生成单元 {index + 1} 的内部镜头没有落到出口状态")
        if cursor != duration:
            issues.append(f"生成单元总时长 {cursor} 秒，没有覆盖目标 {duration} 秒")
            severe = True
        if len(shots) != cls._target_generation_unit_count(duration):
            issues.append("实际生成次数没有保持每 10 秒一次")
            severe = True
        if shots and all(count == 1 for count in internal_counts):
            issues.append("所有生成单元都只有一个画面，电影覆盖不足")
        if len(shots) >= 3 and not any(count == 3 for count in internal_counts):
            issues.append("全片缺少三镜头加速段")
        if len(shots) >= 3 and not any(count == 1 for count in internal_counts):
            issues.append("全片缺少用于情绪停留的长镜头单元")
        if len(set(internal_durations)) < min(3, len(internal_durations)):
            issues.append("内部镜头时长过于整齐，节奏仍然平直")
        if len(set(internal_intensities)) < min(4, len(internal_intensities)):
            issues.append("内部镜头强度曲线档位不足")
        for index in range(2, len(shots)):
            if (
                shots[index].visual_brief == shots[index - 1].visual_brief
                == shots[index - 2].visual_brief
            ):
                issues.append(
                    f"生成单元 {index - 1}—{index + 1} 连续重复同一画面任务"
                )
                break
        score = max(0, 100 - 12 * len(issues))
        internal_count = sum(internal_counts)
        return AnimaticCheckData(
            passed=score >= 85 and not severe,
            score=score,
            generation_unit_count=len(shots),
            internal_shot_count=internal_count,
            shot_count=internal_count,
            sequence_count=len({shot.sequence_id for shot in shots}),
            total_duration_seconds=cursor,
            average_shot_duration_seconds=(
                round(sum(internal_durations) / len(internal_durations), 2)
                if internal_durations
                else 0
            ),
            average_internal_shot_duration_seconds=(
                round(sum(internal_durations) / len(internal_durations), 2)
                if internal_durations
                else 0
            ),
            rhythm_curve=internal_intensities,
            issues=issues,
        )

    @staticmethod
    def _narration_chunks(text: str, max_chars: int = 20) -> list[str]:
        sentences = [
            match.group(0).strip()
            for match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
            if match.group(0).strip()
        ]
        chunks: list[str] = []
        for sentence in sentences:
            clauses = [
                match.group(0).strip()
                for match in re.finditer(r"[^，,]+[，,]?", sentence)
                if match.group(0).strip()
            ]
            current = ""
            for clause in clauses:
                if current and len(current) + len(clause) > max_chars:
                    chunks.append(current)
                    current = ""
                if len(clause) > max_chars:
                    chunks.append(clause)
                    continue
                current += clause
            if current:
                chunks.append(current)
        return chunks

    @staticmethod
    def _markdown_section(body: str, heading: str) -> str:
        match = re.search(
            rf"(?ms)^###\s*{re.escape(heading)}\s*$\n(.*?)(?=^###\s|\Z)", body
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _spoken_char_count(value: str) -> int:
        return len(re.sub(r"[\s，。！？、；：,.!?;:\"“”'（）()—–-]", "", value))

    @classmethod
    def _fit_script_text(
        cls,
        value: str,
        script: str,
        duration: int,
        *,
        max_chars: int | None = None,
    ) -> str:
        candidate = value.strip()
        if not candidate or candidate not in script:
            return ""
        limit = max_chars if max_chars is not None else max(8, math.floor(duration * 4.5))
        if limit <= 0:
            return ""
        if cls._spoken_char_count(candidate) <= limit:
            return candidate
        parts = [
            match.group(0).strip()
            for match in re.finditer(r"[^，,。！？!?；;]+[，,。！？!?；;]?", candidate)
            if match.group(0).strip()
        ]
        fitted = ""
        for part in parts:
            joined = f"{fitted}{part}"
            if cls._spoken_char_count(joined) > limit:
                break
            fitted = joined
        return fitted if fitted and fitted in script else ""

    @staticmethod
    def _exact_script_text(value: str, script: str) -> str:
        candidate = value.strip()
        return candidate if candidate and candidate in script else ""

    @staticmethod
    def _known_people(context: dict) -> list[str]:
        values = [
            person
            for fact in context.get("facts", [])
            for person in fact.get("people", [])
            if person
        ]
        return sorted(set(values), key=len, reverse=True)

    @staticmethod
    def _replace_people(text: str, people: list[str], replacement: str) -> str:
        result = text
        for person in people:
            result = result.replace(person, replacement)
        return result

    @staticmethod
    def _remove_internal_ids(text: str) -> str:
        result = text
        for pattern in ID_PATTERNS.values():
            result = pattern.sub("", result)
        return re.sub(r"[ \t]{2,}", " ", result).strip()

    @staticmethod
    def _remove_shot_labels(text: str) -> str:
        result = SHOT_LABEL_PATTERN.sub("", text)
        return re.sub(r"(?m)^\s*[-•]\s*", "", result).strip()

    @staticmethod
    def _has_display_interaction(source: str) -> bool:
        for segment in re.split(r"[。！？!?；;\n]+", source):
            device_positions = [
                match.start()
                for term in DISPLAY_DEVICE_TERMS
                for match in re.finditer(re.escape(term), segment)
            ]
            interaction_positions = [
                match.start()
                for term in DISPLAY_INTERACTION_TERMS
                for match in re.finditer(re.escape(term), segment)
            ]
            if any(
                abs(device_position - interaction_position) <= 36
                for device_position in device_positions
                for interaction_position in interaction_positions
            ):
                return True
        return False

    @staticmethod
    def _has_readable_display_camera(source: str) -> bool:
        for segment in re.split(r"[。！？!?；;\n]+", source):
            if not any(term in segment for term in DISPLAY_READABLE_CAMERA_TERMS):
                continue
            if re.search(r"(?:不|禁止|避免|没有|无)\S{0,6}(?:越肩|主观|POV|插入)", segment):
                continue
            return True
        return False

    @staticmethod
    def _is_reaction_display_shot(source: str, plan: ShotPlanDraft) -> bool:
        return bool(
            plan.active_character_ids
            and any(term in source for term in DISPLAY_DEVICE_TERMS)
            and ProductionPackageBuilder._has_display_interaction(source)
            and not ProductionPackageBuilder._has_readable_display_camera(source)
        )

    @staticmethod
    def _neutralize_hidden_display_details(text: str) -> str:
        """Remove visual screen semantics from a reaction-first device shot."""
        result = DISPLAY_CONTENT_CLAUSE_PATTERN.sub(
            "设备背壳始终挡在摄影机与发光显示面之间", text
        )
        result = DISPLAY_OUTPUT_CLAUSE_PATTERN.sub(
            "设备只发出稳定的中性屏幕光", result
        )
        result = DISPLAY_COLOR_CUE_CLAUSE_PATTERN.sub(
            "中性屏幕光均匀照亮人物面部", result
        )
        result = DISPLAY_DETAIL_COMPOUND_PATTERN.sub("未入镜的信息", result)
        result = re.sub(
            r"(?:显示|呈现|写着|展示|弹出|刷新出)(?:了|着)?\s*未入镜的信息",
            "只发出稳定的中性屏幕光",
            result,
        )
        result = re.sub(
            r"(?:又一次|再次|反复)?被未入镜的信息(?:拽醒|惊醒|叫醒)",
            "因持续压力再次醒来",
            result,
        )
        result = re.sub(
            r"(?:查看|确认|盯着|凝视|阅读|浏览|看清|读取)\s*未入镜的信息",
            "双眼锁定发光显示面",
            result,
        )
        result = re.sub(
            r"账户(?:亏损|盈利|收益|余额)?|(?:亏损|盈利|收益|股价|行情|价格|交易)"
            r"(?:数值|数字|金额|余额|数据|图表|曲线|走势图|K线|界面|页面|读数)?",
            "持续压力",
            result,
        )
        result = re.sub(
            r"(?:聊天)?消息|通知|验证码|邮件(?:正文)?",
            "此前发生的事",
            result,
        )
        result = re.sub(r"地图|导航(?:路线)?", "行程变化", result)
        result = ProductionPackageBuilder._rewrite_remaining_display_clauses(result)
        result = re.sub(
            r"(?:未入镜的信息|此前发生的事|行程变化)[^，。；：\n]{0,12}"
            r"(?:清晰可读|清晰可见|可读|看清|读取|刷新|滚动|跳动|闪烁|弹出)",
            "人物随即产生细微反应",
            result,
        )
        result = re.sub(
            r"(?:清晰可读|清晰可见|可读|看清|读取|突出|强调)"
            r"[^，。；：\n]{0,12}(?:未入镜的信息|此前发生的事|行程变化)",
            "人物随即产生细微反应",
            result,
        )
        result = result.replace("未入镜的信息", "此前发生的事")
        result = re.sub(
            r"反复确认[^，。；：\n]{0,16}此前发生的事",
            "反复查看设备，试图确认自己的判断",
            result,
        )
        result = re.sub(
            r"把所有注意力压在此前发生的事上",
            "把所有注意力压在屏幕中心",
            result,
        )
        result = re.sub(
            r"(?:看|查看|确认|盯住|盯着|凝视|阅读|浏览|看清|读取)"
            r"(?:那个|那条|这条|这些)?此前发生的事",
            "双眼锁定发光显示面",
            result,
        )
        result = re.sub(
            r"双眼锁定发光显示面(?:和|与)此前发生的事",
            "双眼锁定发光显示面",
            result,
        )
        result = result.replace("此前发生的事静止不动", "眼前情境没有改变")
        result = result.replace("看到此前发生的事时", "查看设备时")
        result = re.sub(r"清晰可读|清晰可见|可读", "明确", result)
        result = re.sub(
            r"(?:唯一的?)?(?:警示|涨跌|亏损|盈利)[^，。；：\n]{0,10}"
            r"(?:暖色|冷色|红色|绿色|橙色|色光|颜色)",
            "一处中性冷白反光",
            result,
        )
        for phrase in (
            "人物双眼锁定朝向自己的发光显示面并产生细微反应",
            "设备背壳始终挡在摄影机与发光显示面之间",
            "中性屏幕光均匀照亮人物面部",
        ):
            result = re.sub(
                rf"(?:{re.escape(phrase)}[，；、]?\s*){{2,}}",
                phrase,
                result,
            )
        return re.sub(r"[ \t]{2,}", " ", result).strip()

    @staticmethod
    def _rewrite_remaining_display_clauses(text: str) -> str:
        parts = re.split(r"([，。；\n])", text)
        for index in range(0, len(parts), 2):
            clause = parts[index]
            if not clause.strip():
                continue
            camera_target = DISPLAY_CAMERA_TARGET_PATTERN.search(clause)
            visual_detail = DISPLAY_STANDALONE_VISUAL_PATTERN.search(clause)
            if not camera_target and not visual_detail:
                continue

            prefix = ""
            remainder = clause
            heading_pattern = "|".join(re.escape(item) for item in PROMPT_SECTION_HEADINGS)
            heading = re.match(
                rf"^(\s*(?:{heading_pattern})(?:（[^\n）]*）)?\s*[：:]?\s*)",
                remainder,
            )
            if heading:
                prefix += heading.group(1)
                remainder = remainder[heading.end() :]
            timing = re.match(
                r"^(\s*\d{1,2}:\d{2}(?:\s*(?:至|-|—)\s*\d{1,2}:\d{2})?\s*)",
                remainder,
            )
            if timing:
                prefix += timing.group(1)

            if camera_target:
                replacement = "摄影机只靠近人物双眼与面部反应"
            elif any(term in clause for term in ("光", "照亮", "反射", "色")):
                replacement = "中性屏幕光均匀照亮人物面部"
            elif any(term in clause for term in ("约束", "背壳", "显示面")):
                replacement = "设备背壳始终挡在摄影机与发光显示面之间"
            else:
                replacement = "人物双眼锁定朝向自己的发光显示面并产生细微反应"
            parts[index] = f"{prefix}{replacement}"
        return "".join(parts)

    @staticmethod
    def _strip_display_geometry_section(body: str) -> str:
        other_headings = "|".join(
            re.escape(heading)
            for heading in PROMPT_SECTION_HEADINGS
            if heading != DISPLAY_GEOMETRY_HEADING
        )
        pattern = re.compile(
            rf"(?ms)^[ \t]*{re.escape(DISPLAY_GEOMETRY_HEADING)}"
            rf"(?:（[^\n）]*）)?[ \t]*[：:]?[ \t]*(?:\n)?"
            rf".*?(?=^[ \t]*(?:{other_headings})(?:（[^\n）]*）)?"
            rf"[ \t]*(?:[：:]|$)|\Z)"
        )
        return re.sub(r"\n{3,}", "\n\n", pattern.sub("", body)).strip()

    @staticmethod
    def _reaction_display_geometry_lock(source: str) -> str:
        locks: list[str] = []
        if "手机" in source:
            locks.append(
                "人物双眼 → 手机发光显示面 → 手机机身与背壳 → 摄影机。"
                "手机显示面法线始终指向人物双眼并背离摄影机；背板与后置镜头模组"
                "始终朝向摄影机，摄影机只记录背板、后置镜头模组和窄边。"
                "手机从拿起到放下不绕竖轴或横轴翻面。"
            )
        if "平板" in source:
            locks.append(
                "人物双眼 → 平板发光显示面 → 平板背板 → 摄影机。"
                "显示面始终朝向人物，背板始终朝向摄影机，摄影机只记录背板和窄边；"
                "平板全程不翻面。"
            )
        if "笔记本" in source:
            locks.append(
                "人物双眼 → 笔记本发光显示面 → 屏幕面板与外侧上盖 → 摄影机。"
                "人物位于键盘一侧，摄影机位于外侧上盖一侧，只记录上盖、铰链与窄边；"
                "铰链角度固定，电脑不转向摄影机。"
            )
        if any(term in source for term in ("显示器", "监视器", "电脑屏幕")):
            locks.append(
                "人物双眼 → 显示器发光显示面 → 显示器后壳 → 摄影机。"
                "摄影机只记录后壳、支架和线缆，人物与显示器相对位置全程固定。"
            )
        if "电视" in source:
            locks.append(
                "人物双眼 → 电视发光显示面 → 电视后壳 → 摄影机。"
                "摄影机只记录电视后壳、支架和人物面部反应。"
            )
        if "相机显示屏" in source:
            locks.append(
                "操作者双眼 → 相机发光显示面 → 相机外壳 → 摄影机。"
                "外部摄影机只记录相机外壳和操作者反应。"
            )
        if "车载屏幕" in source:
            locks.append(
                "使用者双眼 → 车载发光显示面 → 车载屏幕后壳 → 摄影机。"
                "摄影机保持在后壳一侧，设备固定在车辆原位。"
            )
        if any(term in source for term in ("终端屏幕", "支付终端")):
            locks.append(
                "使用者双眼 → 终端发光显示面 → 终端外壳 → 摄影机。"
                "摄影机只记录终端外壳、手部接触和使用者反应。"
            )
        if "电子阅读器" in source:
            locks.append(
                "人物双眼 → 阅读器显示面 → 阅读器背板 → 摄影机。"
                "摄影机只记录背板和窄边，阅读器全程不翻面。"
            )
        if not locks:
            locks.append(
                "人物双眼 → 发光显示面 → 设备机身与背壳 → 摄影机。"
                "显示面始终朝向人物并背离摄影机，摄影机只记录设备背壳和窄边；"
                "设备全程不翻面。"
            )
        return "".join(locks) + "旁白只进入声音轨，不改变上述空间关系。"

    @classmethod
    def _ensure_display_geometry(cls, body: str, plan: ShotPlanDraft) -> str:
        """Enforce one physically possible device face and remove conflicts."""
        source = f"{plan.visual_brief}\n{body}"
        if (
            not plan.active_character_ids
            or not any(term in source for term in DISPLAY_DEVICE_TERMS)
            or not cls._has_display_interaction(source)
        ):
            return body

        stripped = cls._strip_display_geometry_section(body)
        if cls._has_readable_display_camera(source):
            lock = (
                "这是人物同侧的越肩、主观或插入机位：摄影机与人物双眼同在屏幕"
                "显示面一侧；发光显示面仍正对人物，镜头越过肩膀自然看见屏幕内容。"
                "设备朝向、握持手、铰链角度、屏幕状态和人物视线保持稳定。"
            )
        else:
            stripped = cls._neutralize_hidden_display_details(stripped)
            lock = cls._reaction_display_geometry_lock(source)
        return (
            f"{DISPLAY_GEOMETRY_HEADING}（最高优先级）\n{lock}\n\n{stripped}"
        ).strip()

    @staticmethod
    def _split_visual_audio(prompt: str) -> tuple[str, str]:
        match = re.search(r"(?m)^音频(?:（[^\n]*）)?\s*$", prompt)
        if not match:
            return prompt.strip(), ""
        return prompt[: match.start()].strip(), prompt[match.start() :].strip()

    @classmethod
    def repair_display_prompts(
        cls, package: ProductionPackageData
    ) -> tuple[ProductionPackageData, bool]:
        """Repair saved prompts locally without another LLM generation."""
        changed = False
        shots: list[CinematicShotData] = []
        for shot in package.shots:
            plan = ShotPlanDraft.model_validate(shot.model_dump(mode="json"))
            visual, audio = cls._split_visual_audio(shot.prompt_body_template)
            repaired_visual = cls._ensure_display_geometry(visual, plan)
            repaired = (
                f"{repaired_visual}\n\n{audio}".strip() if audio else repaired_visual
            )
            if repaired != shot.prompt_body_template:
                changed = True
                shot = shot.model_copy(update={"prompt_body_template": repaired})
            shots.append(shot)
        if not changed:
            return package, False
        return package.model_copy(update={"shots": shots}), True

    def _previous_package(
        self, session: Session, topic: Topic
    ) -> ProductionPackageData | None:
        raw = self.store.load_json(session, topic.id, "production_package")
        if not raw:
            return None
        try:
            return ProductionPackageData.model_validate(raw)
        except Exception:
            # 老包 schema 对不上就当没有，重建总是安全的。
            return None

    def _plan_fingerprint(self, script: str, context: dict, duration: int) -> str:
        return sha256_text(
            stable_json(
                {
                    "script": sha256_text(script),
                    "context": sha256_text(stable_json(context)),
                    "duration": duration,
                    "llm_profile": self.llm_profile,
                    "skills": {
                        name: self._skill_sha256(name)
                        for name in (
                            "lira-image-prompts",
                            "acting-ai-video",
                            "cinedance-higgsfield",
                        )
                    },
                }
            )
        )

    def _unit_fingerprint(
        self,
        plan: ShotPlanDraft,
        by_id: dict[str, CharacterAssetData],
        style_bible: str,
        audio_plan: GlobalAudioPlanData,
        plan_fingerprint: str,
    ) -> str:
        """覆盖真正喂给模型的全部输入。

        套上 plan_fingerprint 是有意为之：它含剧本与素材摘要，所以剧本一改，所有
        单元一律失效重生成。规划层偶尔会产出字面相同的计划，只比对计划的话，旧提示词
        会挂在新剧本上——这个项目里提示词必须能追溯到那一版审校过的剧本。
        """
        return sha256_text(
            stable_json(
                {
                    "plan_fingerprint": plan_fingerprint,
                    "plan": plan.model_dump(mode="json"),
                    "style_bible": style_bible,
                    "characters": [
                        {
                            "id": by_id[character_id].id,
                            "reference_token": by_id[character_id].reference_token,
                            "visual_anchor": by_id[character_id].visual_anchor,
                            "wardrobe_anchor": by_id[character_id].wardrobe_anchor,
                            "voice_prompt": by_id[character_id].voice_prompt,
                        }
                        for character_id in sorted(plan.active_character_ids)
                        if character_id in by_id
                    ],
                    "audio_plan": audio_plan.model_dump(mode="json"),
                    "skills": {
                        name: self._skill_sha256(name)
                        for name in ("acting-ai-video", "cinedance-higgsfield")
                    },
                    "llm_profile": self.llm_profile,
                }
            )
        )

    def _reusable_bodies(
        self,
        previous: ProductionPackageData,
        shot_plan: list[ShotPlanDraft],
        style_bible: str,
        characters: list[CharacterAssetData],
        audio_plan: GlobalAudioPlanData,
        plan_fingerprint: str,
    ) -> dict[str, tuple[str, str]]:
        """挑出可以原样复用的单元：指纹一致、来源是 AI、且对新计划仍然合法。"""
        by_id = {item.id: item for item in characters}
        by_fingerprint = {
            shot.prompt_fingerprint: shot
            for shot in previous.shots
            if shot.prompt_fingerprint
            and shot.prompt_source == "ai_optimized"
            and shot.prompt_body_core.strip()
        }
        reusable: dict[str, tuple[str, str]] = {}
        for plan in shot_plan:
            candidate = by_fingerprint.get(
                self._unit_fingerprint(
                    plan, by_id, style_bible, audio_plan, plan_fingerprint
                )
            )
            if not candidate:
                continue
            # 内部镜头数量和 0:NN 时间点都在这里校验：旧正文对新计划可能已经不合法。
            if not self._prompt_control_complete(candidate.prompt_body_core, plan):
                continue
            reusable[plan.shot_id] = (
                candidate.prompt_body_core,
                candidate.ambient_audio,
            )
        return reusable

    def _reset_diagnostics(self) -> None:
        self.warnings = []
        self.ai_successes = 0
        self.ai_failures = 0
        self.compliance_hits = []
        self.skill_sources = {}

    def _load_verbatim_skills(self) -> None:
        for name in (
            "lira-image-prompts",
            "acting-ai-video",
            "cinedance-higgsfield",
        ):
            try:
                self.skill_sources[name] = load_verbatim_skill(name)
            except Exception as error:
                self._record_ai_failure(f"{name} 原文加载", error)

    def _skill_sha256(self, name: str) -> str:
        source = self.skill_sources.get(name)
        return source.sha256 if source else ""

    @classmethod
    def _prompt_body_only(cls, prompt: str) -> str:
        """从用户编辑过的整段提示词里取出正文。切法必须和落盘时的一致，否则会漂移。"""
        return cls._split_visual_audio(prompt)[0]

    @staticmethod
    def _prompt_control_complete(prompt: str, plan: ShotPlanDraft) -> bool:
        required = ("连续性状态", "首帧", "格式模式", "动作时间轴", "物理", "灯光")
        if plan.active_character_ids:
            required = (*required, "表演")
        forbidden = (
            "上一镜头",
            "下一镜头",
            "同前",
            "继续上一",
            "延续上一",
        )
        if not all(marker in prompt for marker in required) or any(
            marker in prompt for marker in forbidden
        ):
            return False
        internal_count = len(plan.internal_shots)
        if internal_count <= 1:
            return bool(
                ("单一连续" in prompt or "单镜头" in prompt)
                and not any(cut in prompt for cut in ("HARD CUT", "SMASH CUT"))
            )
        cut_count = sum(
            prompt.count(cut)
            for cut in (
                "HARD CUT",
                "SMASH CUT",
                "MATCH CUT",
                "INSERT CUT",
                "REVERSE CUT",
                "WHIP CUT",
            )
        )
        time_markers_present = all(
            f"0:{internal.start_offset_seconds:02d}" in prompt
            for internal in plan.internal_shots
        )
        return bool(
            ("受控多镜头" in prompt or "多镜头序列" in prompt)
            and cut_count >= internal_count - 1
            and time_markers_present
        )

    @staticmethod
    def _is_lossless_rewrite(previous: str, candidate: str) -> bool:
        if len(candidate) < len(previous) * 0.9:
            return False
        sections = (
            "场景上下文",
            "有效参考",
            "场景空间图",
            "首帧与空间调度",
            "格式模式",
            "光学",
            "摄影机",
            "动作时间轴",
            "物理",
            "灯光",
            "正向约束",
        )
        return all(section not in previous or section in candidate for section in sections)

    def _record_ai_failure(self, stage: str, error: Exception) -> None:
        raw_message = str(error).strip()
        lowered = raw_message.lower()
        if "401" in lowered or "authorization required" in lowered:
            message = "LLM 认证失败（401）"
        elif "403" in lowered or "forbidden" in lowered:
            message = "LLM 权限不足（403）"
        elif "429" in lowered or "rate limit" in lowered:
            message = "LLM 请求频率或额度受限（429）"
        elif "timeout" in lowered or "timed out" in lowered:
            message = "LLM 请求超时"
        else:
            message = raw_message.splitlines()[0] if raw_message else "未知错误"
            message = re.sub(r"https?://\S+", "上游接口", message)
        self.warnings.append(f"{stage}未完成 AI 优化，已使用安全模板：{message[:240]}")
        self.ai_failures += 1

    def _warnings_with_compliance(self, shots: list[CinematicShotData]) -> list[str]:
        """合规改写必须可见：这个项目不做静默修改。"""
        warnings = list(self.warnings)
        if self.compliance_hits:
            warnings.append(
                f"已按视频平台审核规则改写风险表述（{summarize(self.compliance_hits)}），"
                "表演结构与控制信息未改动。"
            )
        # 单元状态也要派生成一条可读原因。单独重做一个镜头时 self.warnings 是空的，
        # 只靠它的话界面会显示"混合优化模式"却给不出任何原因。
        pending = [shot for shot in shots if shot.prompt_source != "ai_optimized"]
        if pending:
            warnings.append(
                f"还有 {len(pending)} 个生成单元使用安全模板："
                + "、".join(shot.shot_id for shot in pending[:6])
                + "。点击“继续生成未完成的”只会重跑这些单元。"
            )
        return warnings

    @staticmethod
    def _target_generation_unit_count(duration: int) -> int:
        """One user-facing generation task per 10-second output clip."""
        return math.ceil(duration / 10)

    def _record_upstream_fallbacks(self, story: dict, script_meta: dict) -> None:
        if story.get("generation_mode") == "deterministic_fallback":
            reason = story.get("generation_note") or "故事模型未返回可用结构"
            self.warnings.append(f"故事层为确定性保底结构，不能标记为成片就绪：{reason}")
        if script_meta.get("generation_mode") == "deterministic_fallback":
            reason = script_meta.get("reason") or "剧本模型未返回可用内容"
            self.warnings.append(f"剧本层为确定性保底稿，不能标记为成片就绪：{reason}")

    @staticmethod
    def _build_readiness(
        *,
        story: dict,
        review: dict,
        script_meta: dict,
        animatic: AnimaticCheckData,
        production_mode: str,
    ) -> ProductionReadinessData:
        blockers: list[str] = []
        quality = NarrativeQualityData.model_validate(story.get("quality") or {})
        if story.get("generation_mode", "legacy") != "ai_generated":
            blockers.append("故事层不是通过质量门的 AI 版本")
        if not quality.passed:
            blockers.append("故事因果节拍质量门未通过")
        if script_meta.get("generation_mode", "legacy") != "ai_generated":
            blockers.append("剧本层不是 AI 生成或 AI 修复版本")
        if not review.get("passed", False):
            blockers.append("剧本事实与电影叙事审校未通过")
        if not animatic.passed:
            blockers.append("节奏样片检查未通过")
        if production_mode != "ai_optimized":
            blockers.append("角色或生成单元提示词存在未完成的 AI 优化")
        blockers = list(dict.fromkeys(blockers))
        return ProductionReadinessData(
            passed=not blockers,
            score=max(0, 100 - 18 * len(blockers)),
            blockers=blockers,
        )

    def _generation_mode(self, shots: list[CinematicShotData]) -> str:
        """从每个单元的实际来源推导，而不是靠调用计数累加。

        增量续跑下计数器只反映"本次做了什么"，判断成片状态必须看"现在包里是什么"。
        """
        ai_units = [shot for shot in shots if shot.prompt_source == "ai_optimized"]
        if self.ai_failures == 0 and len(ai_units) == len(shots) and shots:
            return "ai_optimized"
        if self.ai_successes == 0 and not ai_units:
            return "fallback"
        return "mixed"
