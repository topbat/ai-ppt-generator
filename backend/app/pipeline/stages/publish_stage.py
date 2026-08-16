"""S15 PUBLISH：产物归档 —— 报告上传、任务字段回填；极速模式在此触发异步预览转换。"""
import time

from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import GenerationJob
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.pipeline.stages.qa_stages import build_report

logger = get_logger(__name__)


class PublishStage(Stage):
    code = "PUBLISH"
    weight = 2
    resumable = False

    def run(self, ctx: JobContext) -> dict:
        report = (ctx.data.get("QA") or {}).get("report") or build_report(ctx)
        report_key = ctx.key("report.json")
        ctx.storage.put_json(report_key, report)

        with db_session() as db:
            job = db.get(GenerationJob, ctx.job_pk)
            job.pptx_key = ctx.data["RENDER"]["pptx_key"]
            job.pdf_key = (ctx.data.get("CONVERT") or {}).get("pdf_key") or job.pdf_key
            job.report_key = report_key
            job.pjson_key = ctx.data["LAYOUT"]["pjson_key"]
            job.actual_pages = ctx.target_pages
            job.quality_score = report["score"]

        if ctx.mode == "fast":
            # 极速模式：PPTX 就绪即成功，PDF/PNG 预览异步补齐（不占主链路时间）
            from app.worker import convert_preview
            convert_preview.delay(ctx.job_pk)
            logger.info("极速模式：预览转换已转入后台异步执行")
        logger.info("产物归档完成：pptx=%s 质量分=%d", ctx.data["RENDER"]["pptx_key"], report["score"])
        return {"report_key": report_key, "quality_score": report["score"]}
