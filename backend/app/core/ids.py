"""业务 ID 生成：对外统一使用 biz_id（如 ppt_20260813_a3k9x），不暴露数据库自增主键。"""
import secrets
import string
from datetime import datetime, timezone

_ALPHABET = string.ascii_lowercase + string.digits


def new_biz_id(prefix: str) -> str:
    """prefix: ppt(任务) / tpl(模板) / doc(文档) / dc(决策)"""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand = "".join(secrets.choice(_ALPHABET) for _ in range(6))
    return f"{prefix}_{date}_{rand}"
