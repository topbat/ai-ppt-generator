"""模板注册服务：统一处理"字节 → 存储 → 解析 → 入库 → 缩略图调度"。

被三处复用：用户上传、系统默认模板、AI 生成模板（画廊/入口）。
"""
import os
import tempfile

from app.core.database import db_session
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import Template, TemplateSlide
from app.parser.template_parser import parse_template
from app.services.storage import get_storage

logger = get_logger(__name__)


def register_template_bytes(name: str, data: bytes, is_system: bool = False) -> str:
    """注册模板（同步解析，适用于程序生成的小模板）。返回 biz_id。"""
    biz_id = new_biz_id("tpl")
    file_key = f"templates/{biz_id}/source.pptx"
    get_storage().put_bytes(
        file_key, data,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    with tempfile.TemporaryDirectory(prefix="tplreg_") as tmp:
        path = os.path.join(tmp, "t.pptx")
        with open(path, "wb") as f:
            f.write(data)
        parsed = parse_template(path)
    with db_session() as db:
        row = Template(biz_id=biz_id, name=name[:120], file_key=file_key,
                       file_size=len(data), status="ready", is_system=is_system,
                       slide_count=parsed["slide_count"],
                       design_tokens=parsed["design_tokens"])
        db.add(row)
        db.flush()
        for s in parsed["slides"]:
            db.add(TemplateSlide(template_id=row.id, slide_index=s["slide_index"],
                                 slide_type=s["slide_type"], confidence=s["confidence"],
                                 layout_meta=s["layout_meta"]))
        template_pk = row.id
    schedule_thumbnail(template_pk)
    logger.info("模板注册完成：%s（%s）", name, biz_id)
    return biz_id


def schedule_thumbnail(template_pk: int) -> None:
    """调度封面缩略图生成（worker 内用 LibreOffice 渲染首页）。失败不阻塞。"""
    try:
        from app.worker import template_thumbnail
        template_thumbnail.delay(template_pk)
    except Exception as e:
        logger.warning("缩略图任务调度失败(忽略)：%s", e)
