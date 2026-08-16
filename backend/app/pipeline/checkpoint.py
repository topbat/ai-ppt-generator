"""阶段 Checkpoint：断点重试的基础。

每个 Stage 成功后把轻量输出写入对象存储（jobs/{biz}/checkpoints/{stage}.{attempt}.json），
键记录在 job_stages.output_key；resume 时按成功阶段逐一回灌 ctx.data。
"""
from app.core.logging import get_logger
from app.pipeline.context import JobContext

logger = get_logger(__name__)


def save(ctx: JobContext, stage_code: str, output: dict) -> str:
    key = ctx.key(f"checkpoints/{stage_code}.{ctx.attempt}.json")
    ctx.storage.put_json(key, output)
    return key


def load(ctx: JobContext, output_key: str) -> dict | None:
    """checkpoint 缺失/损坏返回 None，调用方自动降级为重跑该阶段。"""
    try:
        if not ctx.storage.exists(output_key):
            logger.warning("checkpoint 不存在，将重跑该阶段: %s", output_key)
            return None
        return ctx.storage.get_json(output_key)
    except Exception as e:
        logger.warning("checkpoint 读取失败，将重跑该阶段 %s: %s", output_key, e)
        return None
