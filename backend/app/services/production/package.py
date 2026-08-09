from __future__ import annotations

import asyncio
import math
import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Topic
from app.schemas.domain import (
    CharacterAssetData,
    CharacterAssetDraft,
    CharacterCatalogDraft,
    CinematicShotData,
    ProductionPackageData,
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
from app.utils import stable_json

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
        self, session: Session, topic: Topic, duration: int
    ) -> ProductionPackageData:
        self._reset_diagnostics()
        self._load_verbatim_skills()
        script = self.store.load_text(session, topic.id, "script") or ""
        if not script.strip():
            raise RuntimeError("缺少已通过审校的剧本")

        context = narrative_context(session, topic, self.store)
        style_bible, characters = await self._build_characters(
            session, topic, script, context
        )
        target_shot_count = max(1, min(18, math.ceil(duration / 10)))
        shot_plan = await self._build_shot_plan(
            session,
            topic,
            script,
            context,
            characters,
            duration,
            target_shot_count,
        )
        shots = await self._build_shot_prompts(
            session, topic, script, context, style_bible, characters, shot_plan
        )
        return ProductionPackageData(
            topic_id=topic.id,
            generated_at=datetime.now(UTC).isoformat(),
            duration_seconds=duration,
            llm_profile=self.llm_profile,
            generation_mode=self._generation_mode(),
            warnings=self._warnings_with_compliance(),
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
                    purpose="角色表演主档案与逐镜头表演适配",
                    source_sha256=self._skill_sha256("acting-ai-video"),
                ),
                SkillStageData(
                    order=3,
                    skill="cinedance-higgsfield",
                    purpose="可直接生成视频的镜头调度提示词",
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
            step_prefix=f"production:regenerate:{shot_id}:r{previous.revision + 1}",
            previous_prompts={shot_id: safe_current_prompt} if safe_current_prompt else {},
            previous_ambient={shot_id: previous.ambient_audio},
        )
        replacement = regenerated[0].model_copy(
            update={"revision": previous.revision + 1}
        )
        package.shots[shot_index] = replacement
        package.generated_at = datetime.now(UTC).isoformat()
        if self.warnings:
            package.warnings = list(dict.fromkeys([*package.warnings, *self.warnings]))
            if package.generation_mode == "ai_optimized":
                package.generation_mode = "mixed"
        elif package.generation_mode == "fallback":
            package.generation_mode = "mixed"
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
        target_shot_count: int,
    ) -> list[ShotPlanDraft]:
        prompt = render_prompt(
            "shot_plan",
            topic=topic.title,
            duration=duration,
            target_shot_count=target_shot_count,
            script=script,
            characters=stable_json([item.model_dump(mode="json") for item in characters]),
            context=stable_json(context),
        )
        try:
            result = await self.planning_llm.generate_model(
                session,
                topic.id,
                "production:shot_plan",
                "你是严格的纪录片分镜规划师。不得改写旁白或创造现实事实。",
                prompt,
                ShotPlanResult,
            )
            if len(result.shots) != target_shot_count:
                raise ValueError("镜头数量不符合目标")
            raw_shots = result.shots
            self.ai_successes += 1
        except Exception as error:
            self._record_ai_failure("镜头规划", error)
            raw_shots = self._fallback_shot_plan(script, characters, duration, context)
        return self._normalize_shot_plan(
            raw_shots, script, context, characters, duration, target_shot_count
        )

    def _normalize_shot_plan(
        self,
        raw_shots: list[ShotPlanDraft],
        script: str,
        context: dict,
        characters: list[CharacterAssetData],
        duration: int,
        target_shot_count: int,
    ) -> list[ShotPlanDraft]:
        if len(raw_shots) != target_shot_count:
            raw_shots = self._fallback_shot_plan(script, characters, duration, context)
        valid_character_ids = {item.id for item in characters}
        valid_event_ids = {item.get("id", "") for item in context.get("events", [])}
        valid_source_ids = {item.get("id", "") for item in context.get("sources", [])}
        normalized: list[ShotPlanDraft] = []
        for index, item in enumerate(raw_shots[:target_shot_count]):
            start, end = self._shot_window(index, duration, target_shot_count)
            normalized.append(
                ShotPlanDraft(
                    shot_id=f"shot_{index + 1:02d}",
                    title=self._remove_shot_labels(item.title).strip()
                    or f"镜头 {index + 1}",
                    start_second=start,
                    end_second=end,
                    narration=self._exact_script_text(item.narration, script),
                    dialogue=self._exact_script_text(item.dialogue, script),
                    visual_brief=self._remove_shot_labels(item.visual_brief).strip(),
                    active_character_ids=[
                        value
                        for value in dict.fromkeys(item.active_character_ids)
                        if value in valid_character_ids
                    ],
                    event_ids=[
                        value
                        for value in dict.fromkeys(item.event_ids)
                        if value in valid_event_ids
                    ],
                    source_ids=[
                        value
                        for value in dict.fromkeys(item.source_ids)
                        if value in valid_source_ids
                    ],
                )
            )
        return normalized

    def _fallback_shot_plan(
        self,
        script: str,
        characters: list[CharacterAssetData],
        duration: int,
        context: dict | None = None,
    ) -> list[ShotPlanDraft]:
        target_count = max(1, min(18, math.ceil(duration / 10)))
        segments = self._script_segments(script)
        narration_queues = {
            item["start_second"]: self._narration_chunks(item.get("narration", ""))
            for item in segments
        }
        event_fact_ids = {
            item.get("id", ""): set(item.get("fact_ids", []))
            for item in (context or {}).get("events", [])
        }
        plans: list[ShotPlanDraft] = []
        for index in range(target_count):
            start, end = self._shot_window(index, duration, target_count)
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
            plans.append(
                ShotPlanDraft(
                    shot_id=f"shot_{index + 1:02d}",
                    title=segment.get("visual_brief", "纪录片资料画面")[:120]
                    or "纪录片资料画面",
                    start_second=start,
                    end_second=end,
                    narration=narration_queue.pop(0) if narration_queue else "",
                    dialogue="",
                    visual_brief=segment.get("visual_brief", "与已核验内容对应的克制纪实画面")
                    or "与已核验内容对应的克制纪实画面",
                    active_character_ids=active,
                    event_ids=segment.get("event_ids", []),
                    source_ids=segment.get("source_ids", []),
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
        *,
        step_prefix: str = "production:shots",
        previous_prompts: dict[str, str] | None = None,
        previous_ambient: dict[str, str] | None = None,
    ) -> list[CinematicShotData]:
        by_id = {item.id: item for item in characters}
        generated: dict[str, tuple[str, str]] = {}
        skill_ready = {
            "acting-ai-video",
            "cinedance-higgsfield",
        }.issubset(self.skill_sources)
        batch_requests: list[tuple[int, list[ShotPlanDraft], str]] = []
        for offset in range(0, len(shot_plan), 4):
            chunk = shot_plan[offset : offset + 4]
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
                prompt_shots.append(prompt_item.model_dump(mode="json"))
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
                        raise ValueError("逐镜头提示词返回数量或 ID 不完整")
                    return batch_number, chunk, result, None
                except Exception as error:
                    return batch_number, chunk, None, error

        outcomes = await asyncio.gather(
            *(generate_batch(*request) for request in batch_requests)
        )
        for batch_number, _chunk, result, error in outcomes:
            stage = f"逐镜头提示词第 {batch_number} 批"
            if error is not None or result is None:
                self._record_ai_failure(stage, error or RuntimeError("未知错误"))
                continue
            try:
                lossless_failures: list[str] = []
                for item in result.shots:
                    candidate = item.prompt_body_template.strip()
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
                if lossless_failures:
                    self._record_ai_failure(
                        stage,
                        ValueError("输出未通过无损保留校验，已保留原提示词"),
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
        lens = (
            "29°短长焦人物镜头，摄影机距人物约 5 米，人物清晰，背景轻度压缩并柔和虚化"
            if character_lines
            else "47°自然标准镜头，摄影机距主体约 4 米，透视接近人眼，环境关系清楚"
        )
        return (
            f"场景上下文\n{plan.visual_brief}\n\n"
            f"首帧与空间调度\n{subject}主体位于画面三分线，空间关系从第一帧即可读懂，动作已处于可见状态。\n\n"
            f"光学\n{lens}，稳定保持同一光学特征。\n\n"
            "摄影机\n摄影机保持在主体动作可读的一侧，只执行一次缓慢、有人体重量感的微推进；焦点跟随主要动作。\n\n"
            "动作时间轴\n"
            f"0:00 至 0:{plan.end_second - plan.start_second:02d}，"
            "人物以真实重心和克制反应完成当前唯一动作；"
            "眼神先于头部到达目标，眨眼和呼吸持续自然，手中事务在信息落下时短暂停住。\n\n"
            "物理\n脚掌有真实落地、重心转移和摩擦，衣料与头发存在轻微惯性延迟，物件具有明确质量。\n\n"
            f"灯光\n{style_bible}\n\n"
            "正向约束\n身份、造型、站位、视线和道具状态保持稳定，画面清晰自然。"
        )

    def _attach_audio(
        self,
        body: str,
        ambient: str,
        narration: str,
        dialogue: str,
        voice_lines: list[str],
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
    def _shot_window(index: int, duration: int, count: int) -> tuple[int, int]:
        start = (index * duration) // count
        end = ((index + 1) * duration) // count
        return start, end

    @staticmethod
    def _narration_chunks(text: str, max_chars: int = 42) -> list[str]:
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
                while len(clause) > max_chars:
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.append(clause[:max_chars])
                    clause = clause[max_chars:]
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

    @staticmethod
    def _prompt_body_only(prompt: str) -> str:
        return re.split(r"\n音频(?:（[^\n]*）)?\s*\n", prompt, maxsplit=1)[0].strip()

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

    def _warnings_with_compliance(self) -> list[str]:
        """合规改写必须可见：这个项目不做静默修改。"""
        warnings = list(self.warnings)
        if self.compliance_hits:
            warnings.append(
                f"已按视频平台审核规则改写风险表述（{summarize(self.compliance_hits)}），"
                "表演结构与控制信息未改动。"
            )
        return warnings

    def _generation_mode(self) -> str:
        if self.ai_failures == 0:
            return "ai_optimized"
        if self.ai_successes == 0:
            return "fallback"
        return "mixed"
