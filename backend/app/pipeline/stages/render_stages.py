"""S11~S12：PPT 渲染与预览转换。

RENDER 不可断点复用（重跑成本低且必须与最新内容一致）；
CONVERT 失败仅降级预览（E6003 Warning），绝不影响 PPTX 交付。
fast 模式 CONVERT 不在主链路（PUBLISH 后异步补齐，见 worker.convert_preview）。
"""
import os
import tempfile

from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import GenerationJob, JobSlide
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.schemas.presentation import PresentationSpec
from app.services import convert
from app.services.progress import ProgressPublisher

logger = get_logger(__name__)


def load_spec(ctx: JobContext) -> PresentationSpec:
    cached = ctx._cache.get("presentation_spec")
    if cached is not None:
        return cached
    pjson_key = ctx.data["LAYOUT"]["pjson_key"]
    spec = PresentationSpec.model_validate(ctx.storage.get_json(pjson_key))
    ctx.set_cached("presentation_spec", spec)
    return spec


def _template_render_info(ctx: JobContext, tmp_dir: str) -> dict | None:
    """构造模板克隆渲染所需信息：下载模板文件 + 角色页清单。"""
    rows = ctx.template_slides()
    if not rows:
        return None
    tpl = ctx.template_row()
    local = os.path.join(tmp_dir, "template.pptx")
    try:
        ctx.storage.download_to(tpl.file_key, local)
    except Exception as e:
        logger.warning("模板文件下载失败，退回系统渲染路径: %s", e)
        return None
    return {"path": local, "slides": [
        {"slide_index": r.slide_index, "role": r.slide_type,
         "confidence": float(r.confidence),
         "title_geo": (r.layout_meta or {}).get("title_geo"),
         "space_contract": (r.layout_meta or {}).get("space_contract"),
         "bg_is_dark": (r.layout_meta or {}).get("bg_is_dark", False)} for r in rows]}


def render_and_upload(ctx: JobContext, spec: PresentationSpec) -> dict:
    """渲染 → 几何微调（一次性正确）→ 上传 final.pptx。REPAIR 阶段复用本函数重渲染。"""
    from app.ppt.renderer import render_presentation
    from app.ppt.visual_ops import polish_pptx
    with tempfile.TemporaryDirectory(prefix="pptrender_") as tmp:
        out_path = os.path.join(tmp, "final.pptx")
        template = _template_render_info(ctx, tmp)
        result = render_presentation(spec, out_path, template=template)
        try:
            # 渲染期视觉微调：对齐锚线/8pt 网格吸附（V-M1 一次性正确，全模式生效）
            result["polish"] = polish_pptx(out_path)
        except Exception as e:
            logger.warning("渲染期几何微调失败（跳过，不影响交付）：%s", e)
        pptx_key = ctx.key("final.pptx")
        ctx.storage.put_file(pptx_key, out_path,
                             "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    result["pptx_key"] = pptx_key
    return result


class RenderStage(Stage):
    code = "RENDER"
    weight = 8
    resumable = False

    def run(self, ctx: JobContext) -> dict:
        spec = load_spec(ctx)
        result = render_and_upload(ctx, spec)
        with db_session() as db:
            for row in db.query(JobSlide).filter_by(job_id=ctx.job_pk).all():
                if row.status != "degraded":
                    row.status = "rendered"
        logger.info("PPTX 已上传：%s（渲染路径=%s）", result["pptx_key"],
                    result.get("render_path"))
        return {"pptx_key": result["pptx_key"], "render_notes": result["notes"],
                "degraded_pages": result["degraded_pages"], "render_ms": result["duration_ms"],
                "render_path": result.get("render_path")}


class ConvertStage(Stage):
    code = "CONVERT"
    weight = 8
    resumable = False

    def run(self, ctx: JobContext) -> dict:
        return do_convert(ctx.job_pk, ctx.biz_id, ctx.data["RENDER"]["pptx_key"],
                          ctx.storage, ctx.publisher)


def do_convert(job_pk: int, biz_id: str, pptx_key: str, storage, publisher: ProgressPublisher) -> dict:
    """转换主体：PPTX→PDF→PNG→缩略图，逐页推送 thumbnail_ready。
    同时供 CONVERT 阶段（标准/专业）与异步任务（极速）调用。"""
    with tempfile.TemporaryDirectory(prefix="pptconv_") as tmp:
        local_pptx = os.path.join(tmp, "final.pptx")
        storage.download_to(pptx_key, local_pptx)
        pdf_path = convert.pptx_to_pdf(local_pptx, tmp)
        if pdf_path is None:
            # 预览降级（E6003 Warning）：PPTX 照常交付
            logger.warning("预览转换失败（E6003），跳过 PDF/PNG，仅交付 PPTX")
            return {"pdf_key": None, "warning": "E6003"}
        pdf_key = f"jobs/{biz_id}/preview.pdf"
        storage.put_file(pdf_key, pdf_path, "application/pdf")

        images = convert.pdf_to_images(pdf_path, tmp)
        with db_session() as db:
            rows = {r.page_no: r for r in db.query(JobSlide).filter_by(job_id=job_pk).all()}
            job = db.get(GenerationJob, job_pk)
            job.pdf_key = pdf_key
            for im in images:
                image_key = f"jobs/{biz_id}/pages/page-{im['page']}.png"
                thumb_key = f"jobs/{biz_id}/thumbs/page-{im['page']}.png"
                storage.put_file(image_key, im["image_path"], "image/png")
                storage.put_file(thumb_key, im["thumb_path"], "image/png")
                row = rows.get(im["page"])
                if row:
                    row.image_key = image_key
                    row.thumb_key = thumb_key
        for im in images:
            publisher.thumbnail_ready(im["page"], f"/api/v1/jobs/{biz_id}/pages/{im['page']}/thumb")
        logger.info("预览转换完成：PDF + %d 页 PNG", len(images))
        return {"pdf_key": pdf_key, "page_images": len(images)}
