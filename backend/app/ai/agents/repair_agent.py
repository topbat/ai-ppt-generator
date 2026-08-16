"""修复 Agent：针对 QA 发现的文案类问题做定向改写（压缩超长文本等）。

布局类问题由 Layout Engine 确定性修复，不经过 LLM；
本 Agent 只做"改写更短"这一件事，改写后仍需过 ContentGuard。
"""
from app.ai.gateway import LLMGateway
from app.core.logging import get_logger

logger = get_logger(__name__)

_SYSTEM = (
    "你是 PPT 文案压缩专家。只输出合法 JSON。"
    "压缩时保留全部关键事实与数字，删除修饰性表达；禁止新增任何事实。"
)


def compress_slide_text(gw: LLMGateway, mode: str, slide_content: dict,
                        issues: list[str], job_id: int) -> dict:
    """输入整页内容 JSON 与问题清单，输出压缩后的同结构 JSON。"""
    import json
    user = f"""以下 PPT 页面存在问题：{'；'.join(issues)}。
请在保持 JSON 结构与字段完全不变的前提下压缩文字（可删除次要要点），解决上述问题。

# 页面内容
{json.dumps(slide_content, ensure_ascii=False)}

# 输出：与输入同结构的完整 JSON"""
    logger.info("修复 Agent 压缩第 %s 页文案，问题数=%d", slide_content.get("page"), len(issues))
    return gw.chat_json("repair", mode, _SYSTEM, user, job_id=job_id, max_tokens=3000)
