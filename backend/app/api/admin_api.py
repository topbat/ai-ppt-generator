"""管理端统计 API：任务量/成功率/各模式耗时（Grafana 之外的轻量视图）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import GenerationJob, LLMCall
from app.schemas.dto import ok

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    rows = db.execute(select(GenerationJob.status, func.count())
                      .group_by(GenerationJob.status)).all()
    by_status = {s: c for s, c in rows}
    mode_rows = db.execute(
        select(GenerationJob.mode, func.count(), func.avg(GenerationJob.duration_ms))
        .where(GenerationJob.status == "succeeded").group_by(GenerationJob.mode)).all()
    llm = db.execute(select(LLMCall.provider, func.count(),
                            func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                            func.coalesce(func.sum(LLMCall.completion_tokens), 0))
                     .group_by(LLMCall.provider)).all()
    return ok({
        "total": sum(by_status.values()),
        "succeeded": by_status.get("succeeded", 0),
        "failed": by_status.get("failed", 0),
        "running": by_status.get("running", 0) + by_status.get("waiting_user", 0),
        "pending": by_status.get("pending", 0),
        "by_mode": {m: c for m, c, _a in mode_rows},
        "avg_duration_ms": {m: int(a or 0) for m, _c, a in mode_rows},
        "llm": {p: {"calls": c, "prompt_tokens": int(pt), "completion_tokens": int(ct)}
                for p, c, pt, ct in llm},
    })
