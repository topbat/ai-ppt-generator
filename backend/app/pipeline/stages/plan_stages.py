"""S06~S07：大纲生成与页面规划。

极速模式：OUTLINE 一次 LLM 调用产出"大纲+逐页规划"（PLAN 阶段仅做骨架重建，零调用）；
标准/专业：OUTLINE 与 PLAN 各一次调用。
页数硬约束最终由 PageGuard(build_page_plan) 以确定性骨架保证。
"""
from app.ai.agents.outline_agent import generate_outline, outline_plan_combo, plan_slides
from app.ai.gateway import get_gateway
from app.core.errors import PPTError
from app.core.logging import get_logger
from app.pipeline.context import JobContext
from app.pipeline.guards.guards import build_page_plan
from app.pipeline.stages.base import Stage

logger = get_logger(__name__)


def _chapters_for_ai(ctx: JobContext) -> list[dict]:
    """优先用知识建模的章节摘要增强原始章节内容。"""
    ir = ctx.get_doc_ir()
    chapters = [dict(c) for c in ir["chapters"]]
    summaries = (ctx.data.get("KNOWLEDGE") or {}).get("chapter_summaries") or []
    for i, s in enumerate(summaries):
        if i < len(chapters) and s.get("summary"):
            chapters[i]["content"] = (f"[摘要] {s['summary']} [要点] {'；'.join(s.get('key_points', []))}\n"
                                      + chapters[i]["content"])
    return chapters


class OutlineStage(Stage):
    code = "OUTLINE"
    weight = 12

    def run(self, ctx: JobContext) -> dict:
        gw = get_gateway()
        ir = ctx.get_doc_ir()
        chapters = _chapters_for_ai(ctx)

        if ctx.mode == "fast":
            result = outline_plan_combo(gw, ctx.mode, ir["title"], chapters,
                                        ctx.target_pages, ctx.density, ctx.job_pk,
                                        model_override=ctx.model)
            outline = result.get("outline") or []
            ai_slides = result.get("slides") or []
        else:
            result = generate_outline(gw, ctx.mode, ir["title"], chapters,
                                      ctx.target_pages, ctx.job_pk, model_override=ctx.model)
            outline = result.get("outline") or []
            ai_slides = []

        # OutlineGuard：大纲基础校验与修正
        outline = [o for o in outline if isinstance(o, dict) and o.get("chapter")]
        if not outline:
            raise PPTError("E3003", "大纲生成为空")
        max_chapters = max(1, ctx.target_pages - 4)  # 每章至少 1 正文页 + 固定 3 页
        if len(outline) > max_chapters:
            logger.warning("OutlineGuard：章节数 %d 超上限，截断为 %d", len(outline), max_chapters)
            outline = outline[:max_chapters]
        # 补齐并校验来源章节映射（AI 未给或给出列表/字符串等非法值时按顺序对应）
        chapter_count = len(ctx.get_doc_ir()["chapters"])
        for i, o in enumerate(outline):
            si = o.get("source_chapter_idx")
            if isinstance(si, list):  # LLM 偶发返回列表（如 [2,3]）：取首个
                si = si[0] if si else None
            try:
                si = int(si)
            except (TypeError, ValueError):
                si = None
            o["source_chapter_idx"] = si if si and 0 < si <= chapter_count else (
                i + 1 if i < chapter_count else None)
        logger.info("大纲生成完成：%d 章 %s", len(outline), [o["chapter"] for o in outline])
        return {"outline": outline, "ai_slides": ai_slides, "doc_title": ir["title"]}


class PlanStage(Stage):
    code = "PLAN"
    weight = 5

    def run(self, ctx: JobContext) -> dict:
        out = ctx.data["OUTLINE"]
        outline, ai_slides = out["outline"], out["ai_slides"]

        if ctx.mode != "fast":
            # 标准/专业：独立调用 Slide Planner
            gw = get_gateway()
            result = plan_slides(gw, ctx.mode, outline, _chapters_for_ai(ctx),
                                 ctx.target_pages, ctx.job_pk, model_override=ctx.model)
            ai_slides = result.get("slides") or []

        # 模板含"感谢聆听"类尾页时，末页保留为模板尾页
        has_ending = any(r.slide_type == "ending" for r in ctx.template_slides())
        # PageGuard：确定性骨架重建，页数分毫不差
        plan, warnings = build_page_plan([dict(o) for o in outline], ai_slides,
                                         ctx.target_pages, out["doc_title"],
                                         has_ending=has_ending)
        logger.info("页面规划完成：共 %d 页（含模板尾页=%s，Guard 修正 %d 处）",
                    len(plan), has_ending, len(warnings))
        return {"plan": plan, "warnings": warnings}
