"""S09~S10：模板匹配与版面组装（产出最终 Presentation JSON）。"""
from app.core.database import db_session
from app.core.errors import PPTError
from app.core.logging import get_logger
from app.models.models import JobSlide
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.schemas.presentation import PresentationSpec, SlideSpec, ThemeSpec

logger = get_logger(__name__)


class MatchStage(Stage):
    code = "MATCH"
    weight = 2

    def run(self, ctx: JobContext) -> dict:
        """把每页绑定到模板中最合适的版式页（评分：类型匹配 + 识别置信度）。
        匹配不到 → template_slide_id=None（渲染时使用系统版式，Info 记录）。"""
        plan = ctx.data["PLAN"]["plan"]
        tpl_slides = ctx.template_slides()
        by_type: dict[str, list] = {}
        for ts in tpl_slides:
            by_type.setdefault(ts.slide_type, []).append(ts)

        matches: dict[str, int | None] = {}
        fallback_pages: list[int] = []
        structural = ("cover", "toc", "section", "summary", "ending")
        for p in plan:
            cands = by_type.get(p["type"]) or []
            # 正文类型无同型模板页时绑定"内容框架页"（克隆底版）
            if not cands and p["type"] not in structural:
                cands = by_type.get("content_frame") or []
            if not cands and p["type"] == "summary":
                cands = by_type.get("content_frame") or []
            if cands:
                best = max(cands, key=lambda t: float(t.confidence))
                matches[str(p["page"])] = best.id
            else:
                matches[str(p["page"])] = None
                fallback_pages.append(p["page"])
        if fallback_pages:
            logger.info("模板匹配：%d/%d 页无对应版式，将使用系统版式(兜底)",
                        len(fallback_pages), len(plan))
        with db_session() as db:
            for row in db.query(JobSlide).filter_by(job_id=ctx.job_pk).all():
                row.template_slide_id = matches.get(str(row.page_no))
        return {"matches": matches, "fallback_pages": fallback_pages,
                "template_hit_rate": round(1 - len(fallback_pages) / max(1, len(plan)), 3)}


class LayoutStage(Stage):
    code = "LAYOUT"
    weight = 3

    def run(self, ctx: JobContext) -> dict:
        """组装最终 PresentationSpec（Pydantic 严校验，非法数据在此拦截而非渲染时炸）。"""
        plan = ctx.data["PLAN"]["plan"]
        pages = ctx.get_pages_content()
        tokens = ctx.data["PARSE_TPL"]["design_tokens"]
        matches = ctx.data["MATCH"]["matches"]

        theme = ThemeSpec(
            primary=tokens.get("primary", "1677FF"), secondary=tokens.get("secondary", "13234E"),
            accent=tokens.get("accent", "36CFC9"),
            font_title=tokens.get("font_title", "Microsoft YaHei"),
            font_body=tokens.get("font_body", "Microsoft YaHei"))

        slides = []
        with db_session() as db:
            slide_rows = {r.page_no: r for r in
                          db.query(JobSlide).filter_by(job_id=ctx.job_pk).all()}
        for p in plan:
            c = pages.get(str(p["page"])) or {}
            row = slide_rows.get(p["page"])
            try:
                slides.append(SlideSpec(
                    page=p["page"], chapter_id=f"ch{p.get('chapter_idx') or 0}",
                    type=c.get("type", p["type"]), template_slide_id=matches.get(str(p["page"])),
                    title=c.get("title", p.get("title", "")), subtitle=c.get("subtitle"),
                    key_message=p.get("key_message"), section_no=c.get("section_no") or p.get("section_no"),
                    elements=c.get("elements", []),
                    sources=(row.sources if row else []) or []))
            except Exception as e:
                # 单页 Schema 非法 → 降级要点页（不阻塞）
                logger.warning("第 %d 页 Schema 校验失败，降级为要点页: %s", p["page"], e)
                slides.append(SlideSpec(
                    page=p["page"], type="title_content", title=p.get("title", ""),
                    elements=[{"type": "bullet_group",
                               "items": [p.get("key_message") or p.get("title", "")]}]))

        spec = PresentationSpec(
            title=ctx.data["OUTLINE"]["doc_title"], total_pages=ctx.target_pages,
            mode=ctx.mode, density=ctx.density, theme=theme, slides=slides)
        if len(spec.slides) != ctx.target_pages:
            raise PPTError("E3003", f"组装页数 {len(spec.slides)} != 目标 {ctx.target_pages}")

        pjson_key = ctx.key(f"presentation.{ctx.attempt}.json")
        ctx.storage.put_json(pjson_key, spec.model_dump())
        ctx.set_cached("presentation_spec", spec)
        logger.info("版面组装完成：%d 页，Presentation JSON 已存 %s", len(slides), pjson_key)
        return {"pjson_key": pjson_key}
