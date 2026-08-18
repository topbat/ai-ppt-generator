"""生成任务 API：创建/查询/取消/重试/决策/页面/产物。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.object_response import object_response
from app.core.config import (beautify_selectable_model, default_selectable_model, get_settings,
                             selectable_models, validate_selectable_model)
from app.core.database import get_db
from app.core.errors import ERRORS
from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import (Document, GenerationJob, JobDecision, JobSlide, JobStage,
                               Template, ValidationReport)
from app.pipeline.stages.base import STAGE_NAMES
from app.schemas.dto import DecisionReq, JobCreateReq, JobRetryReq, err, ok

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = get_logger(__name__)


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _output_filename(job: GenerationJob, doc: Document | None) -> str | None:
    """产物文件名（列表展示与下载共用同一规则，保证两处一致）。"""
    if not job.pptx_key:
        return None
    from datetime import timedelta
    ts = (job.finished_at or job.created_at) + timedelta(hours=8)  # 北京时间
    base = doc.name.rsplit(".", 1)[0] if doc else "presentation"
    return f"{base}_{ts:%m%d-%H%M%S}.pptx"


def _job_dto(job: GenerationJob, db: Session, with_stages: bool = False) -> dict:
    tpl = db.get(Template, job.template_id)
    doc = db.get(Document, job.document_id)
    error_def = ERRORS.get(job.error_code) if job.error_code else None
    first_thumb = db.execute(select(JobSlide.thumb_key).where(
        JobSlide.job_id == job.id, JobSlide.page_no == 1)).scalar_one_or_none()
    dto = {
        "id": job.biz_id, "biz_id": job.biz_id, "job_id": job.biz_id,
        "status": job.status, "mode": job.mode, "density": job.density, "model": job.model,
        "target_pages": job.target_pages, "actual_pages": job.actual_pages,
        "progress": job.progress, "current_stage": job.current_stage,
        "current_stage_name": STAGE_NAMES.get(job.current_stage or "", job.current_stage),
        "error_code": job.error_code, "error_message": job.error_message,
        "suggestion": error_def.suggestion if error_def else None,
        "failed_stage": job.failed_stage,
        "failed_stage_name": STAGE_NAMES.get(job.failed_stage or "", job.failed_stage),
        "retryable": (error_def.retryable if error_def else None) if job.status == "failed" else None,
        "retry_count": job.retry_count, "version_no": job.version_no,
        "quality_score": job.quality_score, "visual_score": job.visual_score,
        "created_at": _iso(job.created_at), "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "queue_ms": job.queue_ms, "duration_ms": job.duration_ms,
        "template_id": tpl.biz_id if tpl else None, "template_name": tpl.name if tpl else None,
        "document_id": doc.biz_id if doc else None, "document_name": doc.name if doc else None,
        # 展示文件名与下载文件名一致（同一规则生成）
        "output_filename": _output_filename(job, doc),
        "thumb_url": f"/api/v1/jobs/{job.biz_id}/pages/1/thumb" if first_thumb else None,
        # 前端列表用的字段名（保持两个别名兼容）
        "thumbnail_url": f"/api/v1/jobs/{job.biz_id}/pages/1/thumb" if first_thumb else None,
    }
    if with_stages:
        rows = db.execute(select(JobStage).where(JobStage.job_id == job.id)).scalars().all()
        latest: dict[str, JobStage] = {}
        for r in rows:  # 每个阶段取最近一次尝试
            if r.stage_code not in latest or r.attempt > latest[r.stage_code].attempt:
                latest[r.stage_code] = r
        dto["stages"] = [{
            "stage_code": r.stage_code, "name": STAGE_NAMES.get(r.stage_code, r.stage_code),
            "status": r.status, "attempt": r.attempt, "seq": r.seq,
            "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
            "duration_ms": r.duration_ms, "error_code": r.error_code,
            "error_message": r.error_message, "meta": r.meta or {},
        } for r in sorted(latest.values(), key=lambda x: x.seq)]
    return dto


@router.get("/options")
def get_options():
    settings = get_settings()
    return ok({
        "models": selectable_models(settings),
        "default_model": default_selectable_model(settings),
        "beautify_model": beautify_selectable_model(settings),
    })


@router.post("")
def create_job(req: JobCreateReq, db: Session = Depends(get_db)):
    try:
        model = validate_selectable_model(req.model)
    except ValueError as exc:
        return err(1001, str(exc))
    tpl = db.execute(select(Template).where(Template.biz_id == req.template_id,
                                            Template.deleted_at.is_(None))).scalar_one_or_none()
    doc = db.execute(select(Document).where(Document.biz_id == req.document_id,
                                            Document.deleted_at.is_(None))).scalar_one_or_none()
    if tpl is None:
        return err(1005, "模板不存在")
    if doc is None:
        return err(1005, "文档不存在")
    if tpl.status == "parsing":
        return err(1005, "模板正在解析中，请稍候")
    if tpl.status == "failed":
        return err(2004, "模板解析失败，请更换模板")
    if doc.parse_status == "parsing":
        return err(1005, "文档正在解析中，请稍候")
    if doc.parse_status == "failed":
        error_def = ERRORS.get(doc.parse_error or "E2001")
        return err(2001, f"文档解析失败：{error_def.user_message if error_def else ''}")

    job = GenerationJob(biz_id=new_biz_id("ppt"), template_id=tpl.id, document_id=doc.id,
                        target_pages=req.pages, mode=req.mode, density=req.density,
                        model=model, options=req.options, status="pending")
    db.add(job)
    db.commit()
    # 入队（异步执行，接口秒回）
    from app.worker import generate_ppt
    generate_ppt.delay(job.id, False)
    logger.info("生成任务已创建并入队：%s 模式=%s 模型=%s 页数=%d 模板=%s 文档=%s",
                job.biz_id, req.mode, model, req.pages, tpl.name, doc.name)
    return ok({"job_id": job.biz_id})


@router.get("")
def list_jobs(status: str | None = None, mode: str | None = None,
              page: int = 1, page_size: int = 10, db: Session = Depends(get_db)):
    q = select(GenerationJob).where(GenerationJob.deleted_at.is_(None))
    if status:
        q = q.where(GenerationJob.status == status)
    if mode:
        q = q.where(GenerationJob.mode == mode)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(GenerationJob.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return ok({"items": [_job_dto(j, db) for j in rows], "total": total})


def _get_job(biz_id: str, db: Session) -> GenerationJob | None:
    return db.execute(select(GenerationJob).where(
        GenerationJob.biz_id == biz_id)).scalar_one_or_none()


@router.get("/{biz_id}")
def get_job(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    return ok(_job_dto(job, db, with_stages=True))


@router.post("/{biz_id}/cancel")
def cancel_job(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    if job.status in ("succeeded", "failed", "canceled"):
        return err(400, f"任务已处于终态（{job.status}），无法取消")
    if job.status == "pending":
        job.status = "canceled"
        job.finished_at = datetime.now(timezone.utc)
    else:
        job.cancel_requested = True  # 运行中：由 Orchestrator 在阶段间检查并停止
    db.commit()
    logger.info("收到取消请求：%s（原状态 %s）", biz_id, job.status)
    return ok()


@router.post("/{biz_id}/retry")
def retry_job(biz_id: str, req: JobRetryReq, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    if job.status not in ("failed", "canceled", "succeeded"):
        return err(400, "任务尚未结束，无法重试")

    from app.worker import generate_ppt
    if req.strategy == "resume":
        if job.status == "succeeded":
            return err(400, "任务已成功，请使用重新生成（restart）")
        job.retry_count += 1
        job.status = "pending"
        job.cancel_requested = False
        db.commit()
        generate_ppt.delay(job.id, True)
        logger.info("断点重试已入队：%s（第 %d 次重试）", biz_id, job.retry_count)
        return ok({"job_id": job.biz_id, "strategy": "resume"})

    # restart / restart_with_input：新任务 + 版本链
    tpl_id, doc_id = job.template_id, job.document_id
    if req.strategy == "restart_with_input":
        if req.template_id:
            tpl = db.execute(select(Template).where(
                Template.biz_id == req.template_id)).scalar_one_or_none()
            if tpl is None or tpl.status != "ready":
                return err(1005, "新模板不存在或未就绪")
            tpl_id = tpl.id
        if req.document_id:
            doc = db.execute(select(Document).where(
                Document.biz_id == req.document_id)).scalar_one_or_none()
            if doc is None or doc.parse_status != "ready":
                return err(1005, "新文档不存在或未就绪")
            doc_id = doc.id
    new = GenerationJob(biz_id=new_biz_id("ppt"), template_id=tpl_id, document_id=doc_id,
                        target_pages=job.target_pages, mode=job.mode, density=job.density,
                        model=job.model, options=job.options, status="pending",
                        parent_job_id=job.id, version_no=job.version_no + 1)
    db.add(new)
    db.commit()
    generate_ppt.delay(new.id, False)
    logger.info("重新生成已入队：%s → 新任务 %s（v%d）", biz_id, new.biz_id, new.version_no)
    return ok({"job_id": new.biz_id, "strategy": req.strategy})


@router.post("/{biz_id}/beautify")
def beautify_job(biz_id: str, db: Session = Depends(get_db)):
    """历史任务一键美化：以原任务为父创建新版本 Job，复用内容、只跑渲染+视觉优化链路。"""
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    if job.status != "succeeded":
        return err(400, "仅生成成功的任务支持一键美化")
    if not job.pptx_key:
        return err(400, "任务产物缺失，无法美化")

    from app.services.beautify_service import fork_job_for_beautify
    from app.worker import generate_ppt
    child = fork_job_for_beautify(db, job)
    generate_ppt.delay(child.id, True)   # resume：自动跳过已继承阶段
    logger.info("一键美化已入队：%s → 新任务 %s（v%d）", biz_id, child.biz_id, child.version_no)
    return ok({"job_id": child.biz_id})


@router.post("/{biz_id}/decisions/{decision_id}")
def answer_decision(biz_id: str, decision_id: str, req: DecisionReq,
                    db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    row = db.execute(select(JobDecision).where(JobDecision.job_id == job.id,
                                               JobDecision.decision_id == decision_id)).scalar_one_or_none()
    if row is None:
        return err(404, "决策不存在")
    if row.status != "open":
        return err(400, "该决策已处理（可能已超时按默认策略执行）")
    row.status = "answered"
    row.answer = {"choice": req.choice}
    row.answered_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("用户决策已提交：%s/%s choice=%s", biz_id, decision_id, req.choice)
    return ok()


@router.get("/{biz_id}/slides")
def list_slides(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    rows = db.execute(select(JobSlide).where(JobSlide.job_id == job.id)
                      .order_by(JobSlide.page_no)).scalars().all()
    items = []
    for r in rows:
        content = r.content or {}
        bullets = []
        for el in content.get("elements", []):
            if el.get("type") == "bullet_group":
                bullets = [str(i) for i in el.get("items", [])[:3]]
                break
        # sources 内部存 name 字段，前端契约为 document_name
        sources = [{"document_id": s.get("document_id"), "document_name": s.get("name"),
                    "pages": s.get("pages", [])} for s in (r.sources or [])]
        items.append({
            "page_no": r.page_no, "slide_type": r.slide_type,
            "title": content.get("title", ""), "status": r.status,
            "degrade_reason": r.degrade_reason, "sources": sources,
            "qa_issues": r.qa_issues or [], "visual_score": r.visual_score,
            "thumb_url": f"/api/v1/jobs/{biz_id}/pages/{r.page_no}/thumb" if r.thumb_key else None,
            "image_url": f"/api/v1/jobs/{biz_id}/pages/{r.page_no}/image" if r.image_key else None,
            "content_card": {"title": content.get("title", ""), "bullets": bullets},
        })
    return ok(items)


@router.get("/{biz_id}/pages/{page_no}/thumb")
def page_thumb(biz_id: str, page_no: int, db: Session = Depends(get_db)):
    return _page_image(biz_id, page_no, db, thumb=True)


@router.get("/{biz_id}/pages/{page_no}/image")
def page_image(biz_id: str, page_no: int, db: Session = Depends(get_db)):
    return _page_image(biz_id, page_no, db, thumb=False)


def _page_image(biz_id: str, page_no: int, db: Session, thumb: bool):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    row = db.execute(select(JobSlide).where(JobSlide.job_id == job.id,
                                            JobSlide.page_no == page_no)).scalar_one_or_none()
    key = (row.thumb_key if thumb else row.image_key) if row else None
    if not key:
        return err(404, "页面图片尚未生成")
    # 后端代理输出（预签名地址绑定 localhost，局域网用户不可达）。
    # 不加缓存：REPAIR/美化会以同一对象键重渲染页面图，缓存会看到旧图
    return object_response(key)


@router.get("/{biz_id}/output")
def job_output(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    if not job.pptx_key:
        return err(400, "PPT 尚未生成完成")
    doc = db.get(Document, job.document_id)
    # 文件名 = 原文档名（含版本号）+ 生成时间；与列表展示名同源（_output_filename）
    filename = _output_filename(job, doc) or "presentation.pptx"
    # 相对地址：经前端 nginx /api 反代，局域网任意机器可达
    return ok({
        "filename": filename,
        "pptx_url": f"/api/v1/jobs/{biz_id}/download/pptx",
        "pdf_url": f"/api/v1/jobs/{biz_id}/download/pdf" if job.pdf_key else None,
        "report_url": f"/api/v1/jobs/{biz_id}/download/report" if job.report_key else None,
    })


@router.get("/{biz_id}/download/{kind}")
def job_download(biz_id: str, kind: str, db: Session = Depends(get_db)):
    """产物下载：pptx | pdf | report，后端代理输出对象存储内容。"""
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    key = {"pptx": job.pptx_key, "pdf": job.pdf_key, "report": job.report_key}.get(kind)
    if not key:
        return err(404, "产物不存在或尚未生成")
    doc = db.get(Document, job.document_id)
    stem = (_output_filename(job, doc) or "presentation.pptx").rsplit(".", 1)[0]
    filename = {"pptx": f"{stem}.pptx", "pdf": f"{stem}.pdf",
                "report": f"{stem}_质检报告.json"}[kind]
    return object_response(key, filename=filename, download=True)


@router.get("/{biz_id}/report")
def job_report(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    row = db.execute(select(ValidationReport).where(ValidationReport.job_id == job.id)
                     .order_by(ValidationReport.round.desc())).scalars().first()
    if row is None:
        return err(404, "质检报告尚未生成")
    return ok(row.report)


@router.get("/{biz_id}/versions")
def job_versions(biz_id: str, db: Session = Depends(get_db)):
    job = _get_job(biz_id, db)
    if job is None:
        return err(404, "任务不存在")
    # 上溯至版本链根，再收集全部后代
    root = job
    while root.parent_job_id:
        parent = db.get(GenerationJob, root.parent_job_id)
        if parent is None:
            break
        root = parent
    chain, frontier = [root], [root.id]
    while frontier:
        children = db.execute(select(GenerationJob).where(
            GenerationJob.parent_job_id.in_(frontier))).scalars().all()
        chain.extend(children)
        frontier = [c.id for c in children]
    chain.sort(key=lambda j: j.version_no)
    return ok({"items": [_job_dto(j, db) for j in chain]})
