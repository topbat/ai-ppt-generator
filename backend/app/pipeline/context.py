"""JobContext：一次生成任务的执行上下文，贯穿全部 Stage。

数据约定：
- ctx.data[stage_code] 存放各阶段的**轻量**输出（可 JSON 序列化，即 checkpoint 内容）；
- 重量级数据（Document IR、页面内容全集）存对象存储，checkpoint 只存引用键，
  通过 get_doc_ir() 等惰性方法读取并进程内缓存。
"""
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import Document, GenerationJob, Template, TemplateSlide
from app.services.progress import ProgressPublisher
from app.services.storage import S3Storage

logger = get_logger(__name__)


@dataclass
class JobContext:
    job_pk: int
    biz_id: str
    mode: str
    density: str
    target_pages: int
    template_pk: int
    document_pk: int
    options: dict
    attempt: int
    storage: S3Storage
    publisher: ProgressPublisher
    data: dict[str, Any] = field(default_factory=dict)   # stage_code -> 轻量输出
    _cache: dict[str, Any] = field(default_factory=dict)  # 进程内重数据缓存

    # ---- 对象存储键约定 ----
    def key(self, name: str) -> str:
        return f"jobs/{self.biz_id}/{name}"

    # ---- 基础信息（set_cached(name, None) 即失效缓存，下次访问重新查库） ----
    def template_row(self) -> Template:
        if self._cache.get("template") is None:
            with db_session() as db:
                self._cache["template"] = db.get(Template, self.template_pk)
        return self._cache["template"]

    def document_row(self) -> Document:
        if self._cache.get("document") is None:
            with db_session() as db:
                self._cache["document"] = db.get(Document, self.document_pk)
        return self._cache["document"]

    def template_slides(self) -> list[TemplateSlide]:
        if self._cache.get("template_slides") is None:
            with db_session() as db:
                rows = db.execute(select(TemplateSlide).where(
                    TemplateSlide.template_id == self.template_pk)
                    .order_by(TemplateSlide.slide_index)).scalars().all()
                self._cache["template_slides"] = list(rows)
        return self._cache["template_slides"]

    # ---- 重量级数据惰性读取 ----
    def get_doc_ir(self) -> dict:
        if "doc_ir" not in self._cache:
            ir_key = (self.data.get("PARSE_DOC") or {}).get("ir_key")
            if not ir_key:
                raise RuntimeError("PARSE_DOC 阶段尚未产出 Document IR")
            self._cache["doc_ir"] = self.storage.get_json(ir_key)
        return self._cache["doc_ir"]

    def get_pages_content(self) -> dict:
        """CONTENT 阶段产出的全部页面内容 {页码字符串: 内容dict}"""
        if "pages_content" not in self._cache:
            key = (self.data.get("CONTENT") or {}).get("pages_key")
            if not key:
                raise RuntimeError("CONTENT 阶段尚未产出页面内容")
            self._cache["pages_content"] = self.storage.get_json(key)
        return self._cache["pages_content"]

    def set_cached(self, name: str, value: Any) -> None:
        self._cache[name] = value

    # ---- 取消检查（每阶段前与长循环内调用） ----
    def cancel_requested(self) -> bool:
        with db_session() as db:
            job = db.get(GenerationJob, self.job_pk)
            return bool(job and (job.cancel_requested or job.status == "canceled"))
