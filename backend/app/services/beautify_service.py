"""历史任务一键美化（docs/04-VISUAL-OPTIMIZATION.md §6.2）。

以原任务为父创建新版本 Job：复制父任务的可复用 checkpoint（内容/规划/版面全保留），
子任务以 resume 方式入队 → 断点机制自动跳过 LAYOUT 及之前的全部阶段，
只跑 RENDER → BEAUTIFY → CONVERT → QA → REPAIR → PUBLISH。

隔离原则：父任务的 checkpoint 对象**复制**到子任务命名空间后再引用，
子任务后续写入（美化后 JSON/修复改写）绝不污染父任务产物。
"""
from sqlalchemy.orm import Session

from app.core.ids import new_biz_id
from app.core.logging import get_logger
from app.models.models import GenerationJob, JobSlide, JobStage
from app.services.storage import get_storage

logger = get_logger(__name__)

# 可继承的阶段（与流水线前段一致；RENDER 起必定重跑）
_INHERIT_STAGES = ["VALIDATE", "PARSE_DOC", "PARSE_TPL", "KNOWLEDGE", "FACT_CHECK",
                   "OUTLINE", "PLAN", "CONTENT", "MATCH", "LAYOUT"]


def _rewrite_refs(obj, parent_prefix: str, child_prefix: str, storage, copied: set):
    """递归重写 checkpoint 内指向父任务命名空间的对象键：复制对象 → 换引用。"""
    if isinstance(obj, str) and obj.startswith(parent_prefix):
        new_key = child_prefix + obj[len(parent_prefix):]
        if new_key not in copied:
            try:
                storage.put_bytes(new_key, storage.get_bytes(obj))
                copied.add(new_key)
            except Exception as e:
                logger.warning("父任务对象复制失败，保留原引用 %s：%s", obj, e)
                return obj
        return new_key
    if isinstance(obj, dict):
        return {k: _rewrite_refs(v, parent_prefix, child_prefix, storage, copied)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_refs(v, parent_prefix, child_prefix, storage, copied) for v in obj]
    return obj


def fork_job_for_beautify(db: Session, parent: GenerationJob) -> GenerationJob:
    """创建美化子任务并继承父任务的内容成果。返回已提交的子 Job。"""
    # 极速任务升格为标准流水线（才有 BEAUTIFY 闭环阶段）；标准/专业保持原模式
    child_mode = "standard" if parent.mode == "fast" else parent.mode
    child = GenerationJob(
        biz_id=new_biz_id("ppt"), template_id=parent.template_id,
        document_id=parent.document_id, target_pages=parent.target_pages,
        mode=child_mode, density=parent.density,
        options={**(parent.options or {}), "beautify_of": parent.biz_id},
        status="pending", parent_job_id=parent.id, version_no=parent.version_no + 1)
    db.add(child)
    db.flush()  # 拿到 child.id

    # 1) 复制页面行（CONTENT 阶段被跳过时，子任务仍具备完整页级数据）
    slides = db.query(JobSlide).filter_by(job_id=parent.id).all()
    for r in slides:
        db.add(JobSlide(job_id=child.id, page_no=r.page_no, chapter_id=r.chapter_id,
                        slide_type=r.slide_type, template_slide_id=r.template_slide_id,
                        plan=r.plan, content=r.content, sources=r.sources,
                        status="generated", qa_issues=None))

    # 2) 复制可继承阶段的 checkpoint（对象复制到子命名空间 + 引用重写）
    from app.pipeline.orchestrator import _load_completed
    completed = _load_completed(parent.id)
    storage = get_storage()
    parent_prefix, child_prefix = f"jobs/{parent.biz_id}/", f"jobs/{child.biz_id}/"
    copied: set[str] = set()
    inherited = 0
    for seq, stage_code in enumerate(_INHERIT_STAGES, start=1):
        key = completed.get(stage_code)
        if not key:
            continue
        try:
            data = storage.get_json(key)
        except Exception as e:
            logger.warning("父任务 checkpoint 读取失败，跳过继承 %s：%s", stage_code, e)
            continue
        data = _rewrite_refs(data, parent_prefix, child_prefix, storage, copied)
        child_key = f"{child_prefix}checkpoints/{stage_code}.0.json"
        storage.put_json(child_key, data)
        db.add(JobStage(job_id=child.id, stage_code=stage_code, seq=seq, attempt=0,
                        status="success", duration_ms=0, output_key=child_key,
                        meta={"inherited_from": parent.biz_id}))
        inherited += 1

    db.commit()
    logger.info("一键美化任务已创建：%s → %s（v%d，模式 %s，继承 %d 个阶段 / %d 页 / 复制对象 %d 个）",
                parent.biz_id, child.biz_id, child.version_no, child_mode,
                inherited, len(slides), len(copied))
    return child
