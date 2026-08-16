"""大纲与页面规划 Agent。

- 极速模式：outline_plan_combo —— 1 次调用同时产出大纲+逐页规划（省调用数）；
- 标准/专业模式：generate_outline 与 plan_slides 分两步（质量优先）。
输出一律为 JSON，由 PageGuard 做页数硬约束修正。
"""
from app.ai.gateway import LLMGateway
from app.core.logging import get_logger
from app.schemas.presentation import SLIDE_TYPES

logger = get_logger(__name__)

# 正文页可用版式（排除结构页 cover/toc/section/summary）
CONTENT_TYPES = [t for t in SLIDE_TYPES if t not in ("cover", "toc", "section", "summary", "image_text")]

_SYSTEM = (
    "你是资深咨询顾问与演示文稿策划专家。你只输出合法 JSON，不输出任何解释文字。"
    "所有内容必须严格来源于给定资料，禁止编造事实、数字与案例。"
)


def _chapters_brief(chapters: list[dict], per_chapter_chars: int, total_chars: int = 14000) -> str:
    """拼接章节资料摘要，控制总输入长度避免超上下文。"""
    parts, used = [], 0
    for i, ch in enumerate(chapters):
        content = ch["content"][:per_chapter_chars]
        if used + len(content) > total_chars:
            content = content[: max(200, total_chars - used)]
        used += len(content)
        parts.append(f"【章节{i + 1}：{ch['title']}】\n{content}")
    return "\n\n".join(parts)


def outline_plan_combo(gw: LLMGateway, mode: str, doc_title: str, chapters: list[dict],
                       target_pages: int, density: str, job_id: int) -> dict:
    """极速模式：大纲 + 逐页规划一次产出。"""
    n = len(chapters)
    content_pages = max(1, target_pages - 3 - n)  # 封面+目录+总结=3，章节页=n
    user = f"""请为以下资料规划一份 {target_pages} 页的汇报 PPT。

# 硬性约束
- 总页数必须恰好 {target_pages} 页：第1页 cover(封面)、第2页 toc(目录)、最后一页 summary(总结)；
- 每个章节以 1 页 section(章节页) 开头，其后是该章的正文页；
- 正文页共 {content_pages} 页，按章节信息量分配；
- 正文页 type 只能从这些取值中选择：{CONTENT_TYPES}；
- 一页只表达一个核心观点；标题不超过18个字。

# 资料（文档标题：{doc_title}）
{_chapters_brief(chapters, per_chapter_chars=1500)}

# 输出 JSON 格式（极致精简：summary/key_message ≤20字，不输出任何多余字段与解释）
{{"outline": [{{"chapter": "章节名", "pages": 正文页数, "summary": "本章一句话摘要"}}],
  "slides": [{{"page": 页码, "chapter_idx": 所属章节序号从1开始(封面/目录/总结填0),
              "type": "版式", "title": "页面标题", "key_message": "本页核心观点一句话"}}]}}
slides 必须覆盖全部 {target_pages} 页（含 cover/toc/section/summary）。"""
    logger.info("调用大纲+规划合并 Agent(极速)：目标 %d 页 / %d 章节", target_pages, n)
    return gw.chat_json("outline", mode, _SYSTEM, user, job_id=job_id, max_tokens=3500)


def generate_outline(gw: LLMGateway, mode: str, doc_title: str, chapters: list[dict],
                     target_pages: int, job_id: int) -> dict:
    """标准/专业模式：仅产出章节大纲与页数分配。"""
    n = len(chapters)
    content_pages = max(1, target_pages - 3 - n)
    user = f"""请为以下资料设计 PPT 章节大纲。

# 约束
- 总页数 {target_pages}：封面1 + 目录1 + 章节页{n} + 正文{content_pages} + 总结1；
- outline 各章 pages 之和必须等于 {content_pages}；
- 保持汇报叙事线：背景→问题→方案→架构→实施→效果（按资料实际内容裁剪）。

# 资料（文档标题：{doc_title}）
{_chapters_brief(chapters, per_chapter_chars=2000)}

# 输出 JSON
{{"outline": [{{"chapter": "章节名", "pages": 正文页数, "summary": "本章重点", "source_chapter_idx": 对应资料章节序号从1开始}}]}}"""
    logger.info("调用大纲 Agent：目标 %d 页 / %d 章节", target_pages, n)
    return gw.chat_json("outline", mode, _SYSTEM, user, job_id=job_id, max_tokens=3000)


def plan_slides(gw: LLMGateway, mode: str, outline: list[dict], chapters: list[dict],
                target_pages: int, job_id: int) -> dict:
    """标准/专业模式：大纲 → 逐页规划。"""
    outline_text = "\n".join(
        f"{i + 1}. {o['chapter']}（正文{o['pages']}页）：{o.get('summary', '')}" for i, o in enumerate(outline))
    user = f"""基于以下确认过的大纲，输出逐页规划。

# 大纲
{outline_text}

# 硬性约束
- 总页数恰好 {target_pages}：第1页 cover、第2页 toc、每章 1 页 section 开头、最后一页 summary；
- 正文页 type 只能取：{CONTENT_TYPES}；
- 一页一个核心观点；数据多的页优先用 bar_chart/table，流程用 process/timeline，
  系统结构用 architecture，对比用 comparison，成果亮点用 key_number。

# 参考资料摘要
{_chapters_brief(chapters, per_chapter_chars=800, total_chars=8000)}

# 输出 JSON（精简：title ≤18字，key_message ≤20字，不输出任何解释）
{{"slides": [{{"page": 页码, "chapter_idx": 章节序号从1开始(结构页填0),
             "type": "版式", "title": "页面标题", "key_message": "核心观点"}}]}}"""
    logger.info("调用页面规划 Agent：目标 %d 页", target_pages)
    return gw.chat_json("outline", mode, _SYSTEM, user, job_id=job_id, max_tokens=3500)
