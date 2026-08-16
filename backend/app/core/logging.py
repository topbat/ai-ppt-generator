"""结构化日志：所有生成链路日志自动携带 job_id / stage 上下文，输出中文。

约定：
- 业务日志一律中文，便于运维排查；
- 通过 contextvars 贯穿 job_id 与 stage，Worker 内无需手工传递；
- 生产环境输出单行 JSON（便于采集），开发环境输出可读文本。
"""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from app.core.config import get_settings

# 生成链路上下文（Worker 执行任务时设置）
ctx_job_id: ContextVar[str] = ContextVar("job_id", default="-")
ctx_stage: ContextVar[str] = ContextVar("stage", default="-")


class ContextFilter(logging.Filter):
    """把 contextvars 中的 job_id / stage 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = ctx_job_id.get()
        record.stage = ctx_stage.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "job_id": getattr(record, "job_id", "-"),
            "stage": getattr(record, "stage", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


_initialized = False


def setup_logging() -> None:
    """进程级初始化，API 与 Worker 启动时各调用一次。"""
    global _initialized
    if _initialized:
        return
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    if settings.env == "dev":
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)-5s [%(job_id)s][%(stage)s] %(name)s: %(message)s"
        )
        handler.setFormatter(fmt)
    else:
        handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    root.handlers = [handler]
    # 降低三方库噪音
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "openai", "celery.utils"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
