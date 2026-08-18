"""ORM 模型（对应文档 §8 表设计）。

注意：
- 时间字段一律 TIMESTAMPTZ（timezone=True），由后端统一产生，前端只做展示；
- JSON 字段使用 SQLAlchemy 通用 JSON 类型（PostgreSQL 下即 JSONB 语义）；
- doc_chunks.embedding 以 JSON 数组存储、Python 内做余弦检索（小规模够用，
  规模上来后切 pgvector，见文档 §8.10 注释）。
"""
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
                        Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Template(Base, TimestampMixin):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biz_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 预留多租户
    name: Mapped[str] = mapped_column(String(128))
    file_key: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing|ready|failed
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    slide_count: Mapped[int | None] = mapped_column(Integer)
    design_tokens: Mapped[dict | None] = mapped_column(JSON)  # 主色/字体/字号
    parse_error: Mapped[str | None] = mapped_column(String(64))
    thumbnail_key: Mapped[str | None] = mapped_column(String(512))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TemplateSlide(Base):
    __tablename__ = "template_slides"
    __table_args__ = (
        UniqueConstraint("template_id", "slide_index"),
        Index("idx_tpl_slides_type", "template_id", "slide_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    slide_index: Mapped[int] = mapped_column(Integer)
    slide_type: Mapped[str] = mapped_column(String(32))       # 20 种受控枚举 | unknown
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))  # 识别置信度 0~1
    layout_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    capacity: Mapped[dict | None] = mapped_column(JSON)
    thumbnail_key: Mapped[str | None] = mapped_column(String(512))


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biz_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(256))
    file_key: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(8))          # pdf | docx
    file_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int | None] = mapped_column(Integer)
    table_count: Mapped[int | None] = mapped_column(Integer)
    image_count: Mapped[int | None] = mapped_column(Integer)
    chapter_count: Mapped[int | None] = mapped_column(Integer)
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing|ready|failed
    parse_error: Mapped[str | None] = mapped_column(String(64))
    ir_key: Mapped[str | None] = mapped_column(String(512))    # Document IR 在对象存储的键
    suggest_pages_min: Mapped[int | None] = mapped_column(Integer)
    suggest_pages_max: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GenerationJob(Base, TimestampMixin):
    """生成任务核心表。created_at 即提交时间。"""
    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint("target_pages BETWEEN 5 AND 100"),
        Index("idx_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biz_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    target_pages: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16), default="fast")      # fast|standard|premium
    density: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high
    model: Mapped[str | None] = mapped_column(String(64))
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending|running|waiting_user|succeeded|failed|canceled
    current_stage: Mapped[str | None] = mapped_column(String(24))
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)     # 0~100
    # 失败信息
    error_code: Mapped[str | None] = mapped_column(String(8))
    error_message: Mapped[str | None] = mapped_column(Text)
    failed_stage: Mapped[str | None] = mapped_column(String(24))
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    parent_job_id: Mapped[int | None] = mapped_column(ForeignKey("generation_jobs.id"))
    version_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # 产物
    pptx_key: Mapped[str | None] = mapped_column(String(512))
    pdf_key: Mapped[str | None] = mapped_column(String(512))
    report_key: Mapped[str | None] = mapped_column(String(512))
    pjson_key: Mapped[str | None] = mapped_column(String(512))
    actual_pages: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[int | None] = mapped_column(SmallInteger)
    visual_score: Mapped[int | None] = mapped_column(SmallInteger)  # 视觉分（册级，九维规则引擎）
    # 全链路时间（FR-9）
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queue_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobStage(Base):
    """阶段执行记录（FR-9 核心）。并行分支耗时写入 meta.branches。"""
    __tablename__ = "job_stages"
    __table_args__ = (
        UniqueConstraint("job_id", "stage_code", "attempt"),
        Index("idx_stages_job", "job_id", "seq", "attempt"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"))
    stage_code: Mapped[str] = mapped_column(String(24))
    seq: Mapped[int] = mapped_column(SmallInteger)
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[str] = mapped_column(String(12))  # pending|running|success|warning|failed|skipped
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(8))
    error_message: Mapped[str | None] = mapped_column(Text)
    output_key: Mapped[str | None] = mapped_column(String(512))  # checkpoint 键（断点重试）
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class JobSlide(Base):
    __tablename__ = "job_slides"
    __table_args__ = (UniqueConstraint("job_id", "page_no"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    chapter_id: Mapped[str | None] = mapped_column(String(16))
    slide_type: Mapped[str] = mapped_column(String(32))
    template_slide_id: Mapped[int | None] = mapped_column(ForeignKey("template_slides.id"))
    plan: Mapped[dict | None] = mapped_column(JSON)
    content: Mapped[dict | None] = mapped_column(JSON)
    sources: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending|generated|rendered|degraded|failed
    degrade_reason: Mapped[str | None] = mapped_column(String(64))
    qa_issues: Mapped[list | None] = mapped_column(JSON)
    visual_score: Mapped[int | None] = mapped_column(SmallInteger)  # 视觉分（页级）
    image_key: Mapped[str | None] = mapped_column(String(512))
    thumb_key: Mapped[str | None] = mapped_column(String(512))
    gen_duration_ms: Mapped[int | None] = mapped_column(Integer)


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("idx_facts_doc_key", "document_id", "fact_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("generation_jobs.id"))
    fact_key: Mapped[str] = mapped_column(String(128))   # 归一键，如"项目投资金额"
    content: Mapped[str] = mapped_column(Text)           # 原文表述，如"1.2亿元"
    value_norm: Mapped[float | None] = mapped_column(Numeric)  # 单位统一后的数值
    unit: Mapped[str | None] = mapped_column(String(16))
    source_page: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(1), default="A")  # A|B|C|D
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FactConflict(Base):
    __tablename__ = "fact_conflicts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    fact_key: Mapped[str] = mapped_column(String(128))
    candidates: Mapped[list] = mapped_column(JSON)       # [{fact_id, content, page}]
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|resolved|expired
    resolution: Mapped[str | None] = mapped_column(String(16))  # user_choice|default_latest|discard
    chosen_fact_id: Mapped[int | None] = mapped_column(BigInteger)
    resolved_by: Mapped[str | None] = mapped_column(String(16))  # user|system
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobDecision(Base):
    """用户决策（事实冲突/页数预算/内容不足），超时按默认策略执行。"""
    __tablename__ = "job_decisions"
    __table_args__ = (UniqueConstraint("job_id", "decision_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    decision_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(24))  # fact_conflict|page_budget|content_shortage
    payload: Mapped[dict] = mapped_column(JSON)
    default_choice: Mapped[str | None] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|answered|defaulted
    answer: Mapped[dict | None] = mapped_column(JSON)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LLMCall(Base):
    """LLM 调用计量：成本与性能分析的数据源。"""
    __tablename__ = "llm_calls"
    __table_args__ = (Index("idx_llm_stat", "provider", "model", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    stage_code: Mapped[str | None] = mapped_column(String(24))
    task_type: Mapped[str] = mapped_column(String(24))
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(48))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))  # success|failed|fallback
    error_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationReport(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (UniqueConstraint("job_id", "round"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    round: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[str] = mapped_column(String(12))  # pass|warning|fail
    score: Mapped[int | None] = mapped_column(SmallInteger)
    errors: Mapped[int] = mapped_column(SmallInteger, default=0)
    warnings: Mapped[int] = mapped_column(SmallInteger, default=0)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobEvent(Base):
    """进度事件流水：SSE 断线重连回放（Last-Event-ID）+ 审计。"""
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocChunk(Base):
    """专业模式 RAG 分块。embedding 存 JSON 数组，Python 内余弦检索（V1 规模够用）。"""
    __tablename__ = "doc_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source_pages: Mapped[list] = mapped_column(JSON)
    embedding: Mapped[list | None] = mapped_column(JSON)


class BeautifyRecord(Base, TimestampMixin):
    """PPT 美化记录（独立于生成流水线的上传美化能力，产物存对象存储）。"""
    __tablename__ = "beautify_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biz_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(256))       # 上传原文件名
    filename: Mapped[str] = mapped_column(String(256))          # 美化后产物文件名
    file_key: Mapped[str] = mapped_column(String(512))          # 产物对象键
    file_size: Mapped[int] = mapped_column(BigInteger)
    total_pages: Mapped[int | None] = mapped_column(Integer)
    score_before: Mapped[int | None] = mapped_column(Integer)   # 九维视觉分（美化前）
    score_after: Mapped[int | None] = mapped_column(Integer)    # 九维视觉分（美化后）
    fixes: Mapped[dict | None] = mapped_column(JSON)            # 修复统计（对齐/网格/黑字）


class PptMasterJob(Base, TimestampMixin):
    """ppt-master 生成任务（独立于生成流水线：以子进程驱动 Agent 在 ppt-master 仓库内执行）。

    异步提交 → 轮询状态；产物（PPTX/预览/日志）上传对象存储，键前缀 pptmaster/{biz_id}/。
    """
    __tablename__ = "pptmaster_jobs"
    __table_args__ = (Index("idx_pm_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    biz_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    input_mode: Mapped[str] = mapped_column(String(16))          # files|topic|text|url
    route: Mapped[str] = mapped_column(String(24))               # generate|template_fill|beautify|enhance|image_to_pptx|create_template
    profile: Mapped[str] = mapped_column(String(16))             # quick|default
    agent: Mapped[str] = mapped_column(String(16))               # claude|codex|mock
    model: Mapped[str | None] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)     # 提交时全部参数
    prompt: Mapped[str | None] = mapped_column(Text)             # 实际发给 Agent 的提示词
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|running|succeeded|failed|canceled
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    stage: Mapped[str | None] = mapped_column(String(128))       # 当前阶段中文描述
    log_tail: Mapped[str | None] = mapped_column(Text)           # 最近约 4KB 日志
    error_message: Mapped[str | None] = mapped_column(Text)
    source_files: Mapped[list] = mapped_column(JSON, default=list)   # [{name,size,key}]
    template_name: Mapped[str | None] = mapped_column(String(256))
    template_key: Mapped[str | None] = mapped_column(String(512))
    outputs: Mapped[list] = mapped_column(JSON, default=list)        # [{kind,name,size,key}]
    preview_keys: Mapped[list] = mapped_column(JSON, default=list)   # 逐页预览对象键（svg/png）
    log_key: Mapped[str | None] = mapped_column(String(512))
    page_count: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    project_dir: Mapped[str | None] = mapped_column(String(512))     # Worker 本地工作区路径
    agent_pid: Mapped[int | None] = mapped_column(Integer)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
