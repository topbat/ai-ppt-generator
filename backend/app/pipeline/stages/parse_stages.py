"""S01~S03：输入校验 / 文档解析 / 模板解析。"""
import os
import tempfile

from app.core.database import db_session
from app.core.errors import PPTError
from app.core.logging import get_logger
from app.models.models import Document, Template, TemplateSlide
from app.parser.docx_parser import parse_docx
from app.parser.pdf_parser import parse_pdf
from app.parser.template_parser import parse_template
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.pipeline.stages.decisions import request_decision

logger = get_logger(__name__)

# 内容量预检：估算资料可支撑的页数（约 300 字支撑 1 页正文）
_CHARS_PER_PAGE = {"low": 240, "medium": 300, "high": 400}


class ValidateStage(Stage):
    code = "VALIDATE"
    weight = 2

    def run(self, ctx: JobContext) -> dict:
        tpl, doc = ctx.template_row(), ctx.document_row()
        if tpl is None or tpl.deleted_at is not None:
            raise PPTError("E1005", "模板不存在")
        if doc is None or doc.deleted_at is not None:
            raise PPTError("E1005", "文档不存在")
        if tpl.status == "failed":
            raise PPTError("E2004", f"模板解析失败: {tpl.parse_error}")
        if doc.parse_status == "failed":
            raise PPTError(doc.parse_error or "E2001", "文档预解析失败")
        logger.info("输入校验通过：模板=%s 文档=%s 页数=%d 模式=%s 密度=%s",
                    tpl.name, doc.name, ctx.target_pages, ctx.mode, ctx.density)

        # 内容量预检（文档 §19）
        warnings = []
        char_count = doc.char_count or 0
        if char_count:
            supported = max(5, char_count // _CHARS_PER_PAGE[ctx.density] + 3)
            if ctx.target_pages > supported * 1.5:
                msg = f"资料约 {char_count} 字，预计支撑 {supported} 页，目标 {ctx.target_pages} 页可能内容偏薄"
                logger.warning("内容量不足预警：%s", msg)
                if ctx.mode == "premium":
                    choice = request_decision(ctx, "content_shortage", {
                        "title": "资料量可能不足",
                        "description": msg,
                        "options": [
                            {"value": "shrink", "label": f"压缩至 {supported} 页",
                             "detail": "按资料量推荐页数生成"},
                            {"value": "continue", "label": f"继续生成 {ctx.target_pages} 页",
                             "detail": "通过拆解与可视化扩展表达，不编造事实"},
                        ]}, default_choice="continue")
                    if choice == "shrink":
                        ctx.target_pages = supported
                        logger.info("用户选择压缩页数 → %d 页", supported)
                warnings.append(msg)
        return {"warnings": warnings, "target_pages": ctx.target_pages}


class ParseDocStage(Stage):
    code = "PARSE_DOC"
    weight = 8

    def run(self, ctx: JobContext) -> dict:
        doc = ctx.document_row()
        # 上传时已预解析 → 直接复用 IR（避免重复解析大文档）
        if doc.ir_key and ctx.storage.exists(doc.ir_key):
            logger.info("复用上传时的预解析结果 ir_key=%s", doc.ir_key)
            return {"ir_key": doc.ir_key, "char_count": doc.char_count,
                    "chapter_count": doc.chapter_count, "reused": True}

        logger.info("开始解析文档 %s (%s)", doc.name, doc.file_type)
        with tempfile.TemporaryDirectory(prefix="pptdoc_") as tmp:
            local = os.path.join(tmp, f"src.{doc.file_type}")
            ctx.storage.download_to(doc.file_key, local)
            ir = parse_pdf(local, doc.name) if doc.file_type == "pdf" else parse_docx(local, doc.name)
        ir_key = f"parsed/{doc.biz_id}/ir.json"
        ctx.storage.put_json(ir_key, ir)
        with db_session() as db:
            row = db.get(Document, doc.id)
            row.ir_key = ir_key
            row.parse_status = "ready"
            row.char_count = ir["char_count"]
            row.page_count = ir["page_count"]
            row.chapter_count = len(ir["chapters"])
            row.table_count = ir["table_count"]
            row.image_count = ir["image_count"]
        ctx.set_cached("doc_ir", ir)
        ctx.set_cached("document", None)  # 失效缓存
        return {"ir_key": ir_key, "char_count": ir["char_count"],
                "chapter_count": len(ir["chapters"]), "reused": False}


class ParseTemplateStage(Stage):
    code = "PARSE_TPL"
    weight = 2

    def run(self, ctx: JobContext) -> dict:
        from app.parser.template_parser import PARSER_VERSION
        tpl = ctx.template_row()
        rows = ctx.template_slides()
        # 解析器版本一致才复用（分类规则升级后自动重解析）
        version_ok = bool(rows) and all(
            (r.layout_meta or {}).get("parser_ver") == PARSER_VERSION for r in rows)
        if tpl.status == "ready" and tpl.design_tokens and version_ok:
            logger.info("复用模板解析结果：%s（%d 个版式）", tpl.name, tpl.slide_count or 0)
            content_row = max(
                (row for row in rows if row.slide_type == "content_frame"),
                key=lambda row: float(row.confidence),
                default=(rows[0] if rows else None),
            )
            return {"design_tokens": tpl.design_tokens, "slide_count": tpl.slide_count or 0,
                    "space_contract": ((content_row.layout_meta or {}).get("space_contract")
                                       if content_row else None), "reused": True}

        logger.info("模板 %s 需要(重新)解析（解析器 v%d）", tpl.name, PARSER_VERSION)
        with tempfile.TemporaryDirectory(prefix="ppttpl_") as tmp:
            local = os.path.join(tmp, "tpl.pptx")
            ctx.storage.download_to(tpl.file_key, local)
            parsed = parse_template(local)
        with db_session() as db:
            row = db.get(Template, tpl.id)
            row.design_tokens = parsed["design_tokens"]
            row.slide_count = parsed["slide_count"]
            row.status = "ready"
            # 先解除历史任务对旧版式行的引用，再删除（避免外键冲突）
            from sqlalchemy import select as sa_select

            from app.models.models import JobSlide
            old_ids = sa_select(TemplateSlide.id).where(TemplateSlide.template_id == tpl.id)
            db.query(JobSlide).filter(JobSlide.template_slide_id.in_(old_ids)).update(
                {"template_slide_id": None}, synchronize_session=False)
            db.query(TemplateSlide).filter_by(template_id=tpl.id).delete()
            for s in parsed["slides"]:
                db.add(TemplateSlide(template_id=tpl.id, slide_index=s["slide_index"],
                                     slide_type=s["slide_type"], confidence=s["confidence"],
                                     layout_meta=s["layout_meta"]))
        ctx.set_cached("template", None)
        ctx.set_cached("template_slides", None)
        content_slide = max(
            (slide for slide in parsed["slides"] if slide["slide_type"] == "content_frame"),
            key=lambda slide: slide["confidence"],
            default=(parsed["slides"][0] if parsed["slides"] else None),
        )
        return {"design_tokens": parsed["design_tokens"],
                "slide_count": parsed["slide_count"],
                "space_contract": ((content_slide["layout_meta"] or {}).get("space_contract")
                                   if content_slide else None),
                "reused": False}
