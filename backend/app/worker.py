"""Celery Worker：generate 队列（生成主任务）+ convert 队列（异步预览转换）。

可靠性配置：
- acks_late + reject_on_worker_lost：Worker 崩溃任务自动回队重派；
- 阶段幂等 + checkpoint：重派不重复消耗已完成的 LLM 调用；
- max-tasks-per-child 在 compose 启动参数中设置，防内存泄漏。
"""
from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

settings = get_settings()
logger = get_logger(__name__)

celery_app = Celery("ppt-generator", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,           # 生成任务重，禁止预取囤积
    task_time_limit=2100,                   # 硬超时兜底（模式级超时在 Orchestrator 内）
    task_soft_time_limit=1980,
    broker_transport_options={"visibility_timeout": 3600},
    task_routes={
        "app.worker.generate_ppt": {"queue": "generate"},
        "app.worker.convert_preview": {"queue": "convert"},
        # 模板封面缩略图必须显式路由：不配置会进默认 celery 队列，而 Worker 只消费
        # generate/convert 两个队列，导致封面图永远不生成
        "app.worker.template_thumbnail": {"queue": "convert"},
    },
    timezone="Asia/Shanghai",
)


@celery_setup_logging.connect
def _setup_celery_logging(**_kwargs):
    """接管 Celery 日志，统一走结构化中文日志。"""
    setup_logging()


_db_ready = False


def _ensure_db():
    global _db_ready
    if not _db_ready:
        from app.core.database import init_db
        init_db()
        _db_ready = True


@celery_app.task(name="app.worker.generate_ppt", bind=True)
def generate_ppt(self, job_pk: int, resume: bool = False):
    """生成主任务：整条流水线在单任务内执行（内部线程并行）。"""
    setup_logging()
    _ensure_db()
    logger.info("Worker 领取生成任务 job_pk=%s resume=%s (celery_id=%s)", job_pk, resume, self.request.id)
    from app.pipeline.orchestrator import run_job
    run_job(job_pk, resume=resume)


@celery_app.task(name="app.worker.template_thumbnail")
def template_thumbnail(template_pk: int):
    """生成模板预览图：封面缩略图 + 全部页面逐页大图（供逐页预览翻看）。"""
    import os
    import tempfile

    setup_logging()
    _ensure_db()
    from app.core.database import db_session
    from app.models.models import Template, TemplateSlide
    from app.services import convert
    from app.services.storage import get_storage

    with db_session() as db:
        tpl = db.get(Template, template_pk)
        if tpl is None:
            return
        biz_id, file_key = tpl.biz_id, tpl.file_key
    try:
        storage = get_storage()
        with tempfile.TemporaryDirectory(prefix="tplthumb_") as tmp:
            local = os.path.join(tmp, "t.pptx")
            storage.download_to(file_key, local)
            pdf = convert.pptx_to_pdf(local, tmp)
            if pdf is None:
                logger.warning("模板预览图转换失败(跳过) template=%s", biz_id)
                return
            import pymupdf
            from PIL import Image
            doc = pymupdf.open(pdf)
            slide_keys: dict[int, str] = {}
            cover_key = f"templates/{biz_id}/cover.png"
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9))
                png = os.path.join(tmp, f"p{i}.png")
                pix.save(png)
                key = f"templates/{biz_id}/slides/{i}.png"
                storage.put_file(key, png, "image/png")
                slide_keys[i] = key
                if i == 0:  # 封面另存缩小版（列表卡片用）
                    with Image.open(png) as im:
                        ratio = 480 / im.width
                        im.resize((480, max(1, int(im.height * ratio)))).save(png)
                    storage.put_file(cover_key, png, "image/png")
            doc.close()
        with db_session() as db:
            tpl = db.get(Template, template_pk)
            tpl.thumbnail_key = cover_key
            for row in db.query(TemplateSlide).filter_by(template_id=template_pk).all():
                if row.slide_index in slide_keys:
                    row.thumbnail_key = slide_keys[row.slide_index]
        logger.info("模板预览图生成完成：%s（封面 + %d 页逐页大图）", biz_id, len(slide_keys))
    except Exception as e:
        logger.warning("模板预览图生成失败(忽略) template=%s: %s", biz_id, e)


@celery_app.task(name="app.worker.convert_preview")
def convert_preview(job_pk: int):
    """异步预览转换（极速模式主链路外补齐 PDF/PNG）。失败仅记 Warning。"""
    setup_logging()
    _ensure_db()
    from app.core.database import db_session, get_session_factory
    from app.models.models import GenerationJob
    from app.pipeline.stages.render_stages import do_convert
    from app.services.progress import ProgressPublisher
    from app.services.storage import get_storage

    with db_session() as db:
        job = db.get(GenerationJob, job_pk)
        if job is None or not job.pptx_key:
            logger.warning("异步转换跳过：任务不存在或无 PPTX job_pk=%s", job_pk)
            return
        biz_id, pptx_key = job.biz_id, job.pptx_key
    try:
        publisher = ProgressPublisher(job_pk, biz_id, get_session_factory())
        do_convert(job_pk, biz_id, pptx_key, get_storage(), publisher)
    except Exception as e:
        logger.warning("异步预览转换失败(E6003 降级，不影响交付): %s", e)
