"""成片提示词的合规改写。

AI 视频平台驳回提示词的原因集中在几类：真实企业/媒体标识（商标与肖像）、
自伤与死亡的直白描写、血腥暴力、金融诱导话术、露骨身体描写。
参考公开资料对违规风险的归类：显性词汇（暴力、色情、歧视、极端言论、虚假宣传）
与隐性风险（商标/人物肖像未授权、血腥画面、群体刻板印象、医疗与投资夸大）。

这里做两件事：
1. 把风险表达换成同义的、可拍的客观描写——只替换风险片段，不删减控制信息。
2. 真实机构名与人名从当前主题的事实里动态取出并泛化，因为它们随主题变化，
   写死清单没有意义。

不碰表演结构：Acting SKILL 要求的目标、阻碍、策略变化、视线、手部与节拍
全部原样保留，替换只发生在词面。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 通用风险词 → 可拍的客观替代。替代必须仍然是"能拍出来的行为"，
# 而不是把信息删掉，否则镜头会失去控制信息。
LEXICON: tuple[tuple[str, str, str], ...] = (
    # 自伤与死亡
    ("自杀", "失去联系", "self_harm"),
    ("轻生", "失去联系", "self_harm"),
    ("自尽", "失去联系", "self_harm"),
    ("跳楼", "站在高处久久不动", "self_harm"),
    ("上吊", "独自待在房间", "self_harm"),
    ("割腕", "独自待在房间", "self_harm"),
    ("遗书", "一封没有寄出的信", "self_harm"),
    ("尸体", "空着的座位", "self_harm"),
    ("身亡", "此后再无消息", "self_harm"),
    ("丧命", "此后再无消息", "self_harm"),
    ("死亡", "离开", "self_harm"),
    ("寻死", "长时间沉默", "self_harm"),
    # 血腥与暴力
    ("鲜血", "深色污渍", "violence"),
    ("流血", "手上有擦伤痕迹", "violence"),
    ("血迹", "深色污渍", "violence"),
    ("伤口", "包扎过的手背", "violence"),
    ("殴打", "推搡", "violence"),
    ("打斗", "争执", "violence"),
    ("厮打", "争执", "violence"),
    ("持刀", "握紧手中的物件", "violence"),
    ("枪口", "镜头前的金属物件", "violence"),
    ("爆炸", "远处的闷响", "violence"),
    # 极端情绪的直白标签（表演要靠行为，不靠标签，这条同时也是 Acting 的要求）
    ("精神崩溃", "长时间无法集中", "distress"),
    ("崩溃大哭", "背过身去平复呼吸", "distress"),
    ("崩溃", "情绪失去支撑", "distress"),
    ("绝望", "看不到出路", "distress"),
    ("痛不欲生", "彻夜无法入睡", "distress"),
    ("发疯", "反复检查同一条信息", "distress"),
    # 金融诱导与夸大
    ("暴富", "短期获利", "financial_claim"),
    ("稳赚", "被宣传为低风险", "financial_claim"),
    ("翻倍", "大幅上涨", "financial_claim"),
    ("内幕", "未经证实的消息", "financial_claim"),
    ("荐股", "投资建议", "financial_claim"),
    ("一夜暴富", "短期获利", "financial_claim"),
    # 露骨身体描写
    ("裸体", "穿着家居服", "explicit"),
    ("赤身", "穿着家居服", "explicit"),
    ("裸露", "露出手臂", "explicit"),
)

# 可识别的真实标识：这些即使不在事实里也常被模型写进画面。
GENERIC_MARKS: tuple[tuple[str, str, str], ...] = (
    (r"(?:新闻|电视|财经)台标", "无标识的播报画面", "trademark"),
    (r"\bLOGO\b|logo|标志牌", "无品牌标识的招牌", "trademark"),
    (r"(?:某|各大)?品牌(?:标|logo)", "无品牌标识", "trademark"),
)

MIN_ORG_LENGTH = 2
# 指数与代码类：写进画面就是可识别的真实金融标识。
# 不能用 \b：中英混排时「KOSPI指数」里 CJK 也算 word 字符，词边界不成立。
INDEX_PATTERN = re.compile(
    r"(?:KOSPI|KOSDAQ|NASDAQ|NYSE|S&P\s?500|道琼斯|纳斯达克|标普500|标普|"
    r"上证指数|深证成指|恒生指数|日经225|日经)",
    re.IGNORECASE,
)


@dataclass
class ComplianceHit:
    category: str
    matched: str
    replacement: str

    def describe(self) -> str:
        return f"{self.matched} → {self.replacement}"


def _generic_org(name: str) -> str:
    """按名字里的行业线索给一个不可识别的替代。"""
    if any(key in name for key in ("银行", "证券", "基金", "保险", "交易所")):
        return "一家金融机构"
    if any(key in name for key in ("电子", "半导体", "科技", "网络", "通信")):
        return "一家大型科技公司"
    if any(key in name for key in ("日报", "新闻", "电视", "通讯社", "媒体", "报")):
        return "一家新闻机构"
    if any(key in name for key in ("部", "厅", "局", "委员会", "政府", "监管")):
        return "监管部门"
    return "一家大型企业"


def build_entity_rules(
    organizations: list[str], people: list[str]
) -> list[tuple[str, str, str]]:
    """真实机构名与人名随主题变化，从事实里取，不写死清单。"""
    rules: list[tuple[str, str, str]] = []
    for name in sorted({item.strip() for item in organizations if item}, key=len, reverse=True):
        if len(name) < MIN_ORG_LENGTH:
            continue
        rules.append((name, _generic_org(name), "trademark"))
    for name in sorted({item.strip() for item in people if item}, key=len, reverse=True):
        if len(name) < MIN_ORG_LENGTH:
            continue
        rules.append((name, "当事人", "real_person"))
    return rules


def sanitize(
    text: str, entity_rules: list[tuple[str, str, str]] | None = None
) -> tuple[str, list[ComplianceHit]]:
    """返回改写后的文本与命中的风险项。只替换词面，不截断、不概括。"""
    if not text:
        return text, []
    hits: list[ComplianceHit] = []
    result = text

    # 指数名要先处理：它们往往也出现在机构列表里，
    # 先跑实体规则会把「KOSPI指数」变成「一家大型企业指数」。
    def _swap_index(match: re.Match[str]) -> str:
        hits.append(ComplianceHit("trademark", match.group(0), "大盘"))
        return "大盘"

    result = INDEX_PATTERN.sub(_swap_index, result)

    for pattern, replacement, category in entity_rules or []:
        if pattern and pattern in result:
            result = result.replace(pattern, replacement)
            hits.append(ComplianceHit(category, pattern, replacement))

    for word, replacement, category in LEXICON:
        if word in result:
            result = result.replace(word, replacement)
            hits.append(ComplianceHit(category, word, replacement))

    for pattern, replacement, category in GENERIC_MARKS:
        if re.search(pattern, result):
            result = re.sub(pattern, replacement, result)
            hits.append(ComplianceHit(category, pattern, replacement))

    return result, hits


def summarize(hits: list[ComplianceHit]) -> str:
    if not hits:
        return ""
    by_category: dict[str, int] = {}
    for hit in hits:
        by_category[hit.category] = by_category.get(hit.category, 0) + 1
    labels = {
        "trademark": "可识别真实标识",
        "real_person": "真实人名",
        "self_harm": "自伤与死亡",
        "violence": "血腥暴力",
        "distress": "极端情绪标签",
        "financial_claim": "金融夸大",
        "explicit": "露骨描写",
    }
    parts = [f"{labels.get(key, key)}×{count}" for key, count in sorted(by_category.items())]
    return "、".join(parts)


__all__ = ["ComplianceHit", "build_entity_rules", "sanitize", "summarize"]
