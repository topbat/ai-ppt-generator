"""PPT 专业级视觉美化 API（独立于生成流水线的对外能力）。

POST /api/v1/beautify：上传 PPTX → 九维视觉评分 → 确定性美化 → 复评 →
产物存 MinIO + 记录入库，返回 before/after 报告 + 下载链接。同步处理（30 页 ≈ 2~5s）。
GET  /api/v1/beautify：美化记录列表（倒序）。
GET  /api/v1/beautify/{biz_id}/download：产物下载（后端代理输出）。
"""
import os
import tempfile

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.object_response import object_response
from app.core.database import get_db
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import BeautifyRecord
from app.schemas.dto import err, ok

router = APIRouter(prefix="/beautify", tags=["beautify"])
logger = get_logger(__name__)

_MAX_SIZE = 60 * 1024 * 1024  # 60MB
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _record_dto(r: BeautifyRecord) -> dict:
    fixes = r.fixes or {}
    return {
        "beautify_id": r.biz_id, "filename": r.filename, "source_name": r.source_name,
        "file_size": r.file_size, "total_pages": r.total_pages,
        "score_before": r.score_before, "score_after": r.score_after,
        "fixes": fixes,
        "fix_count": sum(v for v in fixes.values() if isinstance(v, (int, float))),
        "download_url": f"/api/v1/beautify/{r.biz_id}/download",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("")
async def beautify_ppt(file: UploadFile, db: Session = Depends(get_db)):
    """对上传的 PPT 进行专业级视觉美化，返回美化报告与产物下载链接。"""
    name = file.filename or "presentation.pptx"
    if not name.lower().endswith(".pptx"):
        return err(1001, "文件类型不支持，请上传 .pptx 文件")
    data = await file.read()
    if len(data) > _MAX_SIZE:
        return err(1002, "文件超过 60MB 限制")

    from app.ppt.beautify_external import beautify_pptx
    from app.services.storage import get_storage
    biz_id = new_biz_id("bty")
    stem = os.path.splitext(os.path.basename(name))[0][:80]
    logger.info("收到 PPT 美化请求：%s（%.1fKB）→ %s", name, len(data) / 1024, biz_id)

    try:
        with tempfile.TemporaryDirectory(prefix="pptbeautify_") as tmp:
            in_path = os.path.join(tmp, "in.pptx")
            out_path = os.path.join(tmp, "out.pptx")
            with open(in_path, "wb") as f:
                f.write(data)
            report = beautify_pptx(in_path, out_path)
            out_size = os.path.getsize(out_path)
            out_name = f"{stem}_美化.pptx"
            key = f"beautify/{biz_id}/{out_name}"
            get_storage().put_file(key, out_path, _PPTX_MIME)
    except Exception as e:
        logger.exception("PPT 美化失败：%s", name)
        return err(4001, f"PPT 美化失败：文件可能损坏或格式不受支持（{e}）")

    def _score(v):
        return int(round(v)) if isinstance(v, (int, float)) else None

    row = BeautifyRecord(biz_id=biz_id, source_name=name[:250], filename=out_name,
                         file_key=key, file_size=out_size,
                         total_pages=report.get("total_pages"),
                         score_before=_score(report.get("score_before")),
                         score_after=_score(report.get("score_after")),
                         fixes=report.get("fixes") or {})
    db.add(row)
    db.commit()
    logger.info("PPT 美化完成并入库：%s 视觉分 %s → %s",
                biz_id, report.get("score_before"), report.get("score_after"))

    return ok({
        "beautify_id": biz_id,
        "filename": out_name,
        "download_url": f"/api/v1/beautify/{biz_id}/download",
        **report,
    })


@router.get("")
def list_beautify(page: int = 1, page_size: int = 10, db: Session = Depends(get_db)):
    """美化记录列表（创建时间倒序）。"""
    total = db.execute(select(func.count()).select_from(BeautifyRecord)).scalar_one()
    rows = db.execute(select(BeautifyRecord).order_by(BeautifyRecord.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return ok({"items": [_record_dto(r) for r in rows], "total": total})


@router.get("/{biz_id}/download")
def download_beautify(biz_id: str, db: Session = Depends(get_db)):
    row = db.execute(select(BeautifyRecord).where(
        BeautifyRecord.biz_id == biz_id)).scalar_one_or_none()
    if row is None:
        return err(404, "美化记录不存在")
    return object_response(row.file_key, filename=row.filename, download=True)
