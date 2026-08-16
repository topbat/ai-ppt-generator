"""模板管理 API：上传即触发后台解析（生成时直接复用解析结果）。"""
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import db_session, get_db
from app.core.errors import PPTError
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import Template, TemplateSlide
from app.parser.template_parser import parse_template
from app.schemas.dto import err, ok
from app.services.storage import get_storage

router = APIRouter(prefix="/templates", tags=["templates"])
logger = get_logger(__name__)

_MAX_SIZE = 120 * 1024 * 1024  # 120MB（图片型企业模板普遍较大）


@router.post("")
async def upload_template(file: UploadFile, background: BackgroundTasks,
                          db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".pptx"):
        return err(1001, "文件类型不支持，请上传 .pptx 模板")
    data = await file.read()
    if len(data) > _MAX_SIZE:
        return err(1002, "模板文件超过 120MB 限制")

    biz_id = new_biz_id("tpl")
    file_key = f"templates/{biz_id}/source.pptx"
    get_storage().put_bytes(file_key, data,
                            "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    row = Template(biz_id=biz_id, name=os.path.splitext(file.filename)[0][:120],
                   file_key=file_key, file_size=len(data), status="parsing")
    db.add(row)
    db.commit()
    logger.info("模板上传成功 %s（%s，%.1fKB），开始后台解析", row.name, biz_id, len(data) / 1024)
    background.add_task(_parse_template_task, row.id, data)
    return ok(_template_dto(row))


def _parse_template_task(template_pk: int, data: bytes):
    """后台解析模板；失败写入 parse_error（生成前 VALIDATE 阶段会拦截）。"""
    try:
        with tempfile.TemporaryDirectory(prefix="tplparse_") as tmp:
            path = os.path.join(tmp, "tpl.pptx")
            with open(path, "wb") as f:
                f.write(data)
            parsed = parse_template(path)
        with db_session() as db:
            row = db.get(Template, template_pk)
            row.design_tokens = parsed["design_tokens"]
            row.slide_count = parsed["slide_count"]
            row.status = "ready"
            # 先解除历史任务对旧版式行的引用，再删除（避免外键冲突）
            from sqlalchemy import select as sa_select

            from app.models.models import JobSlide
            old_ids = sa_select(TemplateSlide.id).where(TemplateSlide.template_id == template_pk)
            db.query(JobSlide).filter(JobSlide.template_slide_id.in_(old_ids)).update(
                {"template_slide_id": None}, synchronize_session=False)
            db.query(TemplateSlide).filter_by(template_id=template_pk).delete()
            for s in parsed["slides"]:
                db.add(TemplateSlide(template_id=template_pk, slide_index=s["slide_index"],
                                     slide_type=s["slide_type"], confidence=s["confidence"],
                                     layout_meta=s["layout_meta"]))
        logger.info("模板后台解析完成 template_pk=%s：%d 个版式", template_pk, parsed["slide_count"])
        from app.services.template_service import schedule_thumbnail
        schedule_thumbnail(template_pk)  # 解析成功后生成封面缩略图
    except PPTError as e:
        logger.error("模板后台解析失败 template_pk=%s：%s", template_pk, e)
        with db_session() as db:
            row = db.get(Template, template_pk)
            row.status = "failed"
            row.parse_error = e.code
    except Exception as e:
        logger.exception("模板后台解析未知异常 template_pk=%s", template_pk)
        with db_session() as db:
            row = db.get(Template, template_pk)
            row.status = "failed"
            row.parse_error = "E2004"


# 生成正文常用的版式类型（用于计算缺失版式警告）
_EXPECT_TYPES = ["cover", "toc", "section", "title_content", "three_cards",
                 "bar_chart", "timeline", "architecture", "comparison", "table"]


def _template_dto(t: Template) -> dict:
    return {"id": t.biz_id, "template_id": t.biz_id, "name": t.name, "status": t.status,
            "is_system": t.is_system, "slide_count": t.slide_count,
            "design_tokens": t.design_tokens, "parse_error": t.parse_error,
            "thumbnail_url": f"/api/v1/templates/{t.biz_id}/thumbnail" if t.thumbnail_key else None,
            "created_at": t.created_at.isoformat() if t.created_at else None}


@router.get("")
def list_templates(q: str | None = None, db: Session = Depends(get_db)):
    query = select(Template).where(Template.deleted_at.is_(None))
    if q:
        query = query.where(Template.name.ilike(f"%{q}%"))  # 模板搜索
    rows = db.execute(query.order_by(Template.is_system.desc(),
                                     Template.created_at.desc())).scalars().all()
    return ok([_template_dto(t) for t in rows])


@router.get("/ai-options")
def ai_options_api():
    """AI 生成模板的八维参数可选项（行业/用户群/风格/数据内容/国家/季节；主题与关键字为自由文本）。"""
    from app.ppt.template_gallery import ai_options
    return ok(ai_options())


@router.post("/ai-generate")
def ai_generate(body: dict, db: Session = Depends(get_db)):
    """AI 生成模板：按八维参数生成（封面+目录+章节页+5~8内容页+尾页，名称以 AI 为前缀）。"""
    from app.ppt.template_gallery import build_ai_template, normalize_params, template_name
    from app.services.template_service import register_template_bytes
    params = normalize_params(body or {})
    logger.info("收到 AI 生成模板请求：行业=%s 风格=%s 数据=%s 主题=%s 国家=%s 季节=%s",
                params["industry"], params["style"], params["data_content"],
                params["theme"] or "-", params["country"], params["season"])
    data = build_ai_template(params)
    biz_id = register_template_bytes(template_name(params), data, is_system=False)
    t = db.execute(select(Template).where(Template.biz_id == biz_id)).scalar_one()
    logger.info("AI 生成模板已注册入库：%s（%s）", t.name, biz_id)
    return ok(_template_dto(t))


@router.post("/batch-delete")
def batch_delete_templates(body: dict, db: Session = Depends(get_db)):
    """批量删除模板（软删）。body: {ids: [biz_id, ...]}"""
    from datetime import datetime, timezone
    ids = [str(i) for i in (body or {}).get("ids") or []][:200]
    if not ids:
        return err(400, "未指定要删除的模板")
    rows = db.execute(select(Template).where(Template.biz_id.in_(ids),
                                             Template.deleted_at.is_(None))).scalars().all()
    skipped = [t.biz_id for t in rows if t.is_system]
    deleted = 0
    now = datetime.now(timezone.utc)
    for t in rows:
        if t.is_system:
            continue
        t.deleted_at = now
        deleted += 1
    db.commit()
    logger.info("模板批量删除完成：删除 %d 个，跳过系统模板 %d 个", deleted, len(skipped))
    return ok({"deleted": deleted, "skipped": skipped})


@router.get("/{biz_id}/download")
def download_template(biz_id: str, db: Session = Depends(get_db)):
    """模板源文件下载（个人/AI 模板通用，后端代理输出，文件名保留模板名）。"""
    from app.api.object_response import object_response
    t = db.execute(select(Template).where(Template.biz_id == biz_id,
                                          Template.deleted_at.is_(None))).scalar_one_or_none()
    if t is None or not t.file_key:
        return err(404, "模板不存在")
    return object_response(t.file_key, filename=f"{t.name}.pptx", download=True)


@router.get("/{biz_id}/thumbnail")
def template_thumbnail(biz_id: str, db: Session = Depends(get_db)):
    from app.api.object_response import object_response
    t = db.execute(select(Template).where(Template.biz_id == biz_id)).scalar_one_or_none()
    if t is None or not t.thumbnail_key:
        return err(404, "缩略图尚未生成")
    return object_response(t.thumbnail_key, cache=True)


@router.get("/{biz_id}/slides/{slide_index}/image")
def template_slide_image(biz_id: str, slide_index: int, db: Session = Depends(get_db)):
    """模板单页大图（逐页预览用）：后端代理输出（局域网可达）。"""
    from app.api.object_response import object_response
    t = db.execute(select(Template).where(Template.biz_id == biz_id)).scalar_one_or_none()
    if t is None:
        return err(404, "模板不存在")
    row = db.execute(select(TemplateSlide).where(
        TemplateSlide.template_id == t.id,
        TemplateSlide.slide_index == slide_index)).scalar_one_or_none()
    if row is None or not row.thumbnail_key:
        return err(404, "该页预览图尚未生成")
    return object_response(row.thumbnail_key, cache=True)


@router.get("/{biz_id}")
def get_template(biz_id: str, db: Session = Depends(get_db)):
    t = db.execute(select(Template).where(Template.biz_id == biz_id)).scalar_one_or_none()
    if t is None:
        return err(404, "模板不存在")
    slides = db.execute(select(TemplateSlide).where(TemplateSlide.template_id == t.id)
                        .order_by(TemplateSlide.slide_index)).scalars().all()
    dto = _template_dto(t)
    dto["layouts"] = [{"slide_index": s.slide_index, "slide_type": s.slide_type,
                       "confidence": float(s.confidence),
                       "thumbnail_url": (f"/api/v1/templates/{t.biz_id}/slides/{s.slide_index}/image"
                                         if s.thumbnail_key else None)} for s in slides]
    have = {s.slide_type for s in slides}
    dto["missing_layouts"] = [x for x in _EXPECT_TYPES if x not in have]
    return ok(dto)


@router.delete("/{biz_id}")
def delete_template(biz_id: str, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    t = db.execute(select(Template).where(Template.biz_id == biz_id)).scalar_one_or_none()
    if t is None:
        return err(404, "模板不存在")
    if t.is_system:
        return err(403, "系统默认模板不可删除")
    t.deleted_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("模板已删除（软删）：%s", biz_id)
    return ok()
