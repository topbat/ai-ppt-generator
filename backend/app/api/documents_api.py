"""主说明文档 API：上传即后台预解析（Input Guard：解析失败绝不进入生成流程）。"""
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import db_session, get_db
from app.core.errors import PPTError
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import Document
from app.parser.docx_parser import parse_docx
from app.parser.pdf_parser import parse_pdf
from app.schemas.dto import err, ok
from app.services.storage import get_storage

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger(__name__)

_MAX_SIZE = 100 * 1024 * 1024  # 100MB
# 建议页数估算：约 300 字/页（medium 密度）
_CHARS_PER_PAGE = 300


@router.post("")
async def upload_document(file: UploadFile, background: BackgroundTasks,
                          db: Session = Depends(get_db)):
    name = file.filename or ""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ("pdf", "docx"):
        return err(1001, "文件类型不支持，请上传 PDF 或 DOCX")
    data = await file.read()
    if len(data) > _MAX_SIZE:
        return err(1002, "文档超过 100MB 限制")

    biz_id = new_biz_id("doc")
    file_key = f"uploads/{biz_id}.{ext}"
    get_storage().put_bytes(file_key, data, "application/octet-stream")
    row = Document(biz_id=biz_id, name=name[:250], file_key=file_key, file_type=ext,
                   file_size=len(data), parse_status="parsing")
    db.add(row)
    db.commit()
    logger.info("文档上传成功 %s（%s，%.1fKB），开始后台预解析", name, biz_id, len(data) / 1024)
    background.add_task(_parse_document_task, row.id, data, ext, name)
    return ok({"id": biz_id, "document_id": biz_id, "name": name,
               "file_type": ext, "parse_status": "parsing"})


def _parse_document_task(doc_pk: int, data: bytes, ext: str, name: str):
    try:
        with tempfile.TemporaryDirectory(prefix="docparse_") as tmp:
            path = os.path.join(tmp, f"src.{ext}")
            with open(path, "wb") as f:
                f.write(data)
            ir = parse_pdf(path, name) if ext == "pdf" else parse_docx(path, name)
        storage = get_storage()
        with db_session() as db:
            row = db.get(Document, doc_pk)
            ir_key = f"parsed/{row.biz_id}/ir.json"
            storage.put_json(ir_key, ir)
            row.ir_key = ir_key
            row.parse_status = "ready"
            row.char_count = ir["char_count"]
            row.page_count = ir["page_count"]
            row.chapter_count = len(ir["chapters"])
            row.table_count = ir["table_count"]
            row.image_count = ir["image_count"]
            row.is_scanned = ir["is_scanned"]
            # 建议页数区间（供前端展示）
            base = max(5, ir["char_count"] // _CHARS_PER_PAGE + 3)
            row.suggest_pages_min = max(5, int(base * 0.7))
            row.suggest_pages_max = min(100, int(base * 1.3))
        logger.info("文档预解析完成 doc_pk=%s：%d 字 / %d 章节", doc_pk,
                    ir["char_count"], len(ir["chapters"]))
    except PPTError as e:
        logger.error("文档预解析失败 doc_pk=%s：%s", doc_pk, e)
        with db_session() as db:
            row = db.get(Document, doc_pk)
            row.parse_status = "failed"
            row.parse_error = e.code
    except Exception:
        logger.exception("文档预解析未知异常 doc_pk=%s", doc_pk)
        with db_session() as db:
            row = db.get(Document, doc_pk)
            row.parse_status = "failed"
            row.parse_error = "E2001" if ext == "pdf" else "E2002"


@router.get("/{biz_id}")
def get_document(biz_id: str, db: Session = Depends(get_db)):
    d = db.execute(select(Document).where(Document.biz_id == biz_id)).scalar_one_or_none()
    if d is None:
        return err(404, "文档不存在")
    from app.core.errors import ERRORS
    error_def = ERRORS.get(d.parse_error) if d.parse_error else None
    return ok({
        "id": d.biz_id, "document_id": d.biz_id, "name": d.name, "file_type": d.file_type,
        "parse_status": d.parse_status, "parse_error": d.parse_error,
        "parse_error_message": error_def.user_message if error_def else None,
        "page_count": d.page_count, "char_count": d.char_count,
        "chapter_count": d.chapter_count, "table_count": d.table_count,
        "image_count": d.image_count, "is_scanned": d.is_scanned,
        "suggest_pages": [d.suggest_pages_min, d.suggest_pages_max]
        if d.suggest_pages_min else None,
    })
