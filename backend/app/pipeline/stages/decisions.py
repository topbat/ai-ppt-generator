"""用户决策交互：任务暂停(waiting_user) → 前端弹窗 → 用户选择/超时默认策略 → 继续。

注意：等待期间占用一个 Worker 槽位（V1 取舍，见文档 §13 风险表）；
超时时间由 DECISION_TIMEOUT_SECONDS 控制，默认 10 分钟。
"""
import time
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.database import db_session
from app.core.errors import PPTError
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import GenerationJob, JobDecision
from app.pipeline.context import JobContext

logger = get_logger(__name__)

_POLL_INTERVAL = 2  # 秒


def request_decision(ctx: JobContext, kind: str, payload: dict,
                     default_choice: str | None) -> str:
    """阻塞等待用户决策，返回最终 choice。超时按默认策略（无默认策略则报 E7004）。"""
    settings = get_settings()
    decision_id = new_biz_id("dc")
    deadline = datetime.now(timezone.utc) + timedelta(seconds=settings.decision_timeout_seconds)

    with db_session() as db:
        db.add(JobDecision(job_id=ctx.job_pk, decision_id=decision_id, kind=kind,
                           payload=payload, default_choice=default_choice, deadline_at=deadline))
        job = db.get(GenerationJob, ctx.job_pk)
        job.status = "waiting_user"

    ctx.publisher.decision_required(decision_id, kind, payload, deadline.isoformat(), default_choice)
    logger.info("等待用户决策 kind=%s decision_id=%s（超时 %d 秒后按默认策略「%s」）",
                kind, decision_id, settings.decision_timeout_seconds, default_choice)

    try:
        while True:
            time.sleep(_POLL_INTERVAL)
            if ctx.cancel_requested():
                raise PPTError("E7005", "等待决策期间任务被取消")
            with db_session() as db:
                row = db.query(JobDecision).filter_by(job_id=ctx.job_pk,
                                                      decision_id=decision_id).first()
                if row and row.status == "answered":
                    choice = (row.answer or {}).get("choice", "")
                    logger.info("收到用户决策 kind=%s choice=%s", kind, choice)
                    return choice
                if datetime.now(timezone.utc) >= deadline:
                    if default_choice is None:
                        row.status = "expired"
                        raise PPTError("E7004", f"决策超时且无默认策略 kind={kind}")
                    row.status = "defaulted"
                    row.answered_at = datetime.now(timezone.utc)
                    logger.warning("用户决策超时，按默认策略执行: %s", default_choice)
                    return default_choice
    finally:
        # 恢复运行状态（取消场景由上层处理）
        with db_session() as db:
            job = db.get(GenerationJob, ctx.job_pk)
            if job.status == "waiting_user":
                job.status = "running"
