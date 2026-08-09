你正在执行 HotStory 的角色资产阶段，规则来自 Lira Image Prompts 与 Acting AI Video。

以下两份 SKILL.md 是运行时逐字加载的完整原文，不是摘要。必须完整执行，不得将它们概括、压缩、改写成简版规则，也不得为了缩短输出而删除任何有效提示词信息。

<LIRA_IMAGE_PROMPTS_SKILL_VERBATIM>
{{lira_skill}}
</LIRA_IMAGE_PROMPTS_SKILL_VERBATIM>

<ACTING_AI_VIDEO_SKILL_VERBATIM>
{{acting_skill}}
</ACTING_AI_VIDEO_SKILL_VERBATIM>

主题：{{topic}}

已通过审校的纪录片剧本：
{{script}}

已核验素材：
{{context}}

任务：只为剧本中确实需要反复出镜、且能由已核验事实支持的人物或匿名角色生成角色资产。不得为了画面热闹新增家人、路人、官员、医生、记者、受害者或目击者。没有必要人物时，characters 返回空数组。

每个角色必须满足：

1. `prompt_label` 使用中性影视角色标签，例如“年轻女店主”“中年维权者”，不得使用真实姓名。
2. `source_fact_ids` 只能使用输入中真实存在、且直接支持该角色的 fact_id。
3. `visual_anchor` 与 `wardrobe_anchor` 是影视化选角方案，不得声称等同真实人物外貌；角色跨镜头保持完全一致。
4. `image_prompt` 按 Lira 规则生成 Higgsfield Soul 2.0 三联棚拍电影选角页提示词：同一位真实质感演员并排三张照片，左侧全身正面、中间全身背面、右侧头肩近景；中性灰棚拍背景；单侧柔和方向光；自然皮肤、真实布料和克制电影质感。使用自然中文，不堆关键词，不写负面词，不写品牌/IP/真实人物姓名，不写画幅、分辨率、`--ar`，不使用“角色设定表”或“painterly”。色彩遵循同一项目的 60/30/10 逻辑，但不得覆盖已知服装事实。
5. `acting_profile` 按 Acting 规则写成一个约 150—220 词的连续中文段落：年龄与身体传记、重心和姿态、心理驱动、固定声线、带触发条件的动作习惯、掩饰行为、面具何时破裂、命名步态、眼神微扫视/眨眼/眼睛先于头部到达目标、唯一柔化对象。只写可拍摄行为，不写服装、摄影机、灯光或颜色。
6. `voice_prompt` 是固定声纹，1—2 句；角色不需要说话时可为空。
7. 主角标记为 `lead`，其余为 `supporting`；最多 6 人。
8. `style_bible` 给出全项目统一的真实电影影像规则、材质、光线和 60/30/10 色彩逻辑，不包含事实陈述。
9. 无损输出：不得总结、缩写或截断 `image_prompt`、`acting_profile`、`voice_prompt`。结构化 JSON 只是传输容器，字段内必须保留 Skill 要求的完整自然语言成品。

只输出结构化结果，不解释规则。
