"""页面内容 Agent。

- 极速模式：generate_chapter_batch —— 一章一次调用产出整章多页内容；
- 标准/专业模式：generate_page —— 逐页生成（并行调度在 CONTENT Stage）。
元素 JSON 结构与 Presentation JSON 的受控元素完全一致（见 schemas/presentation.py）。
"""
from app.ai.gateway import LLMGateway
from app.core.logging import get_logger
from app.schemas.presentation import DENSITY_LIMITS

logger = get_logger(__name__)

_SYSTEM = (
    "你是专业 PPT 文案专家。你只输出合法 JSON。"
    "所有事实、数字必须逐字来源于给定资料原文，禁止编造或推算新数字；"
    "资料中没有的数据宁可不写。文案精炼有力，符合商务汇报语感。"
)

# 元素结构说明（提示词共用）
_ELEMENT_GUIDE = """elements 数组中每个元素的可选结构：
- {"type":"bullet_group","items":["要点1","要点2"]}
- {"type":"cards","items":[{"title":"卡片标题","desc":"说明"}]}
- {"type":"key_number","items":[{"value":"23个","label":"业务系统"}]}
- {"type":"chart","chart_type":"bar|line|pie","title":"图表标题","unit":"单位","data":[{"label":"2024","value":82}]}
- {"type":"table","headers":["列1","列2"],"rows":[["a","b"]]}
- {"type":"timeline","items":[{"time":"2026Q1","title":"阶段","desc":"说明"}]}
- {"type":"process","steps":["步骤1","步骤2"]}
- {"type":"architecture","layers":[{"title":"应用层","items":["门户","APP"]}]}
- {"type":"comparison","left":{"title":"现状","items":["..."]},"right":{"title":"目标","items":["..."]}}
- {"type":"quote","text":"引言","author":"出处"}
- {"type":"paragraph","text":"一段说明文字"}"""

# 版式 → 建议主元素（提示词内引导，Guard 兜底修正）
_TYPE_HINT = {
    "title_content": "bullet_group", "two_column": "bullet_group×2", "three_column": "cards",
    "three_cards": "cards(3项)", "four_cards": "cards(4项)", "key_number": "key_number",
    "quote": "quote", "timeline": "timeline", "process": "process", "architecture": "architecture",
    "comparison": "comparison", "table": "table", "bar_chart": "chart(bar)",
    "line_chart": "chart(line)", "pie_chart": "chart(pie)", "toc": "bullet_group", "summary": "bullet_group",
}


def _limits_text(density: str) -> str:
    lim = DENSITY_LIMITS[density]
    return (f"标题≤{lim['title']}字；副标题≤{lim['subtitle']}字；单条要点≤{lim['bullet']}字；"
            f"卡片标题≤{lim['card_title']}字、说明≤{lim['card_desc']}字；"
            f"每页要点/卡片不超过{lim['max_items']}项；全页正文合计≤{lim['body_total']}字")


def generate_chapter_batch(gw: LLMGateway, mode: str, chapter: dict, plans: list[dict],
                           density: str, job_id: int, model_override: str | None = None) -> dict:
    """极速模式：一次生成整章所有页面。"""
    plan_text = "\n".join(
        f"- 第{p['page']}页 [{p['type']}] 标题:{p['title']} 核心观点:{p.get('key_message', '')}"
        f"（建议主元素:{_TYPE_HINT.get(p['type'], 'bullet_group')}）" for p in plans)
    user = f"""请为「{chapter['title']}」章节的以下页面生成内容。

# 页面清单
{plan_text}

# 文案预算（必须遵守）
{_limits_text(density)}

# 章节资料原文
{chapter['content'][:6000]}

# {_ELEMENT_GUIDE}

# 输出 JSON
{{"slides":[{{"page":页码,"type":"与规划一致","title":"标题","subtitle":"副标题或null",
  "elements":[...]}}]}}
必须覆盖清单中的每一页。"""
    logger.info("章节批量生成(极速)：%s，共 %d 页", chapter["title"], len(plans))
    return gw.chat_json("page_content", mode, _SYSTEM, user, job_id=job_id, max_tokens=8000,
                        model_override=model_override)


def generate_page(gw: LLMGateway, mode: str, plan: dict, material: str,
                  density: str, job_id: int, facts_hint: str = "",
                  model_override: str | None = None) -> dict:
    """标准/专业模式：单页生成。material 为该页对应章节资料（专业模式为 RAG 检索结果）。"""
    facts_block = f"\n# 已核验事实（引用数字必须从中选取）\n{facts_hint}\n" if facts_hint else ""
    user = f"""请生成 PPT 第 {plan['page']} 页内容。

# 页面规划
版式: {plan['type']}（建议主元素: {_TYPE_HINT.get(plan['type'], 'bullet_group')}）
标题: {plan['title']}
核心观点: {plan.get('key_message', '')}

# 文案预算（必须遵守）
{_limits_text(density)}
{facts_block}
# 参考资料原文
{material[:5000]}

# {_ELEMENT_GUIDE}

# 输出 JSON
{{"page":{plan['page']},"type":"{plan['type']}","title":"标题","subtitle":"副标题或null","elements":[...]}}"""
    return gw.chat_json("page_content", mode, _SYSTEM, user, job_id=job_id, max_tokens=3000,
                        model_override=model_override)
