"""Orchestrator：状态机驱动器（文档 §6.1）。

职责：
- 按模式 DAG 逐组执行 Stage（组内并行、组间串行）；
- 统一计时落库（job_stages）+ 进度事件发布；
- 断点重试：成功阶段从 checkpoint 回灌，只重跑失败点之后；
- 统一异常收口：PPTError → 错误码落库 + job_failed 事件。
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import db_session, get_session_factory
from app.core.errors import ERRORS, PPTError
from app.core.logging import ctx_job_id, ctx_stage, get_logger
from app.models.models import GenerationJob, JobStage
from app.pipeline import checkpoint
from app.pipeline.context import JobContext
from app.pipeline.modes.pipelines import PIPELINES, total_weight
from app.pipeline.stages.base import Stage
from app.services.progress import ProgressPublisher
from app.services.storage import get_storage

logger = get_logger(__name__)

_MODE_TIMEOUT = {"fast": "job_timeout_fast", "standard": "job_timeout_standard",
                 "premium": "job_timeout_premium"}


def run_job(job_pk: int, resume: bool = False) -> None:
    with db_session() as db:
        job = db.get(GenerationJob, job_pk)
        if job is None:
            logger.error("任务不存在 job_pk=%s", job_pk)
            return
        if job.status in ("canceled", "succeeded"):
            logger.info("任务状态为 %s，跳过执行", job.status)
            return
        biz_id, mode = job.biz_id, job.mode
        attempt = job.retry_count + 1

    ctx_job_id.set(biz_id)
    settings = get_settings()
    publisher = ProgressPublisher(job_pk, biz_id, get_session_factory())
    ctx = JobContext(
        job_pk=job_pk, biz_id=biz_id, mode=mode, density=job.density,
        target_pages=job.target_pages, template_pk=job.template_id,
        document_pk=job.document_id, options=job.options or {}, attempt=attempt,
        storage=get_storage(), publisher=publisher)

    # 断点重试：收集历史成功阶段的 checkpoint
    completed: dict[str, str] = {}
    if resume:
        completed = _load_completed(job_pk)
        logger.info("断点重试(第 %d 次尝试)：可复用阶段 %s", attempt, list(completed) or "无")

    now = datetime.now(timezone.utc)
    with db_session() as db:
        row = db.get(GenerationJob, job_pk)
        row.status = "running"
        if row.queue_ms is None:  # 首次执行才计排队耗时
            row.queue_ms = int((now - row.created_at).total_seconds() * 1000)
        row.started_at = now
        row.error_code = None
        row.error_message = None
        row.failed_stage = None

    deadline = time.monotonic() + getattr(settings, _MODE_TIMEOUT[mode])
    total_w, done_w, seq = total_weight(mode), 0, 0
    logger.info("任务开始执行：模式=%s 目标=%d页 尝试=%d", mode, ctx.target_pages, attempt)

    current_stage_code = None
    try:
        for group in PIPELINES[mode]:
            if ctx.cancel_requested():
                raise PPTError("E7005")
            if time.monotonic() > deadline:
                raise PPTError("E7001", f"超过 {mode} 模式硬超时")
            if len(group) == 1:
                seq += 1
                current_stage_code = group[0].code
                _run_stage(ctx, group[0], seq, completed)
            else:
                # 并行组（如 文档解析 ‖ 模板解析）
                logger.info("并行执行阶段组：%s", [s.code for s in group])
                with ThreadPoolExecutor(max_workers=len(group)) as pool:
                    futures = []
                    for s in group:
                        seq += 1
                        futures.append(pool.submit(_run_stage, ctx, s, seq, completed))
                    for f in futures:
                        f.result()  # 任一失败向上抛
            done_w += sum(s.weight for s in group)
            with db_session() as db:
                row = db.get(GenerationJob, job_pk)
                row.progress = min(99, int(done_w / total_w * 100))
                row.current_stage = group[-1].code
        _finalize_success(ctx)
    except PPTError as e:
        _finalize_failure(ctx, e, current_stage_code)
    except Exception as e:  # 未知异常统一 E7002
        logger.exception("任务执行出现未知异常")
        _finalize_failure(ctx, PPTError("E7002", str(e)), current_stage_code)
    finally:
        ctx_stage.set("-")


def _load_completed(job_pk: int) -> dict[str, str]:
    """取各阶段最近一次成功执行的 checkpoint 键。"""
    with db_session() as db:
        rows = db.execute(select(JobStage).where(JobStage.job_id == job_pk)
                          .order_by(JobStage.attempt)).scalars().all()
    completed: dict[str, str] = {}
    for r in rows:
        if r.status in ("success", "warning", "skipped") and r.output_key:
            completed[r.stage_code] = r.output_key
        elif r.status == "failed":
            completed.pop(r.stage_code, None)
    return completed


def _run_stage(ctx: JobContext, stage: Stage, seq: int, completed: dict[str, str]) -> None:
    ctx_stage.set(stage.code)
    now = datetime.now(timezone.utc)

    # 断点复用：可恢复阶段直接回灌 checkpoint
    if stage.resumable and stage.code in completed:
        out = checkpoint.load(ctx, completed[stage.code])
        if out is not None:
            ctx.data[stage.code] = out
            _record_stage(ctx, stage, seq, "skipped", now, now, 0,
                          output_key=completed[stage.code], meta={"resumed": True})
            ctx.publisher.stage_update(stage.code, "success", elapsed_ms=0)
            logger.info("阶段 %s 从 checkpoint 恢复，跳过执行", stage.code)
            return

    _record_stage(ctx, stage, seq, "running", now, None, None)
    ctx.publisher.stage_update(stage.code, "running")
    t0 = time.monotonic()
    try:
        out = stage.run(ctx) or {}
    except PPTError as e:
        duration = int((time.monotonic() - t0) * 1000)
        _record_stage(ctx, stage, seq, "failed", now, datetime.now(timezone.utc), duration,
                      error_code=e.code, error_message=e.user_message)
        ctx.publisher.stage_update(stage.code, "failed", elapsed_ms=duration)
        logger.error("阶段 %s 失败(%s)：%s | %s", stage.code, e.code, e.user_message, e.detail)
        raise
    duration = int((time.monotonic() - t0) * 1000)
    ctx.data[stage.code] = out
    output_key = checkpoint.save(ctx, stage.code, out)
    _record_stage(ctx, stage, seq, "success", now, datetime.now(timezone.utc), duration,
                  output_key=output_key,
                  meta={"branches": out.get("branches")} if out.get("branches") else {})
    ctx.publisher.stage_update(stage.code, "success", elapsed_ms=duration)
    logger.info("阶段 %s 完成，耗时 %.1fs", stage.code, duration / 1000)


def _record_stage(ctx: JobContext, stage: Stage, seq: int, status: str,
                  started_at, finished_at, duration_ms, error_code=None,
                  error_message=None, output_key=None, meta=None) -> None:
    """阶段记录 upsert（同 job/code/attempt 覆盖写）。"""
    with db_session() as db:
        db.query(JobStage).filter_by(job_id=ctx.job_pk, stage_code=stage.code,
                                     attempt=ctx.attempt).delete()
        db.add(JobStage(job_id=ctx.job_pk, stage_code=stage.code, seq=seq, attempt=ctx.attempt,
                        status=status, started_at=started_at, finished_at=finished_at,
                        duration_ms=duration_ms, error_code=error_code,
                        error_message=error_message, output_key=output_key, meta=meta or {}))


def _finalize_success(ctx: JobContext) -> None:
    now = datetime.now(timezone.utc)
    score = (ctx.data.get("PUBLISH") or {}).get("quality_score")
    with db_session() as db:
        job = db.get(GenerationJob, ctx.job_pk)
        job.status = "succeeded"
        job.progress = 100
        job.current_stage = None
        job.finished_at = now
        job.duration_ms = int((now - job.started_at).total_seconds() * 1000)
    ctx.publisher.job_done(score)
    with db_session() as db:
        job = db.get(GenerationJob, ctx.job_pk)
        logger.info("✅ 任务成功：质量分=%s 执行耗时=%.1fs（排队 %.1fs）",
                    score, (job.duration_ms or 0) / 1000, (job.queue_ms or 0) / 1000)


def _finalize_failure(ctx: JobContext, e: PPTError, stage_code: str | None) -> None:
    now = datetime.now(timezone.utc)
    canceled = e.code == "E7005"
    with db_session() as db:
        job = db.get(GenerationJob, ctx.job_pk)
        job.status = "canceled" if canceled else "failed"
        job.error_code = e.code
        job.error_message = e.user_message
        job.failed_stage = stage_code
        job.finished_at = now
        if job.started_at:
            job.duration_ms = int((now - job.started_at).total_seconds() * 1000)
    if not canceled:
        ctx.publisher.job_failed(e.code, e.user_message, stage_code)
    logger.error("❌ 任务%s：code=%s stage=%s 原因=%s",
                 "已取消" if canceled else "失败", e.code, stage_code, e.user_message)
