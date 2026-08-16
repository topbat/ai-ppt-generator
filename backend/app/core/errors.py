"""错误码体系（对应文档 §6.3）。

约定：
- 每个失败 Job 必带一个 Blocker 级错误码；
- retryable 决定前端主按钮形态：resume=断点重试 / restart_with_input=更换输入后重试 / no=不可重试；
- user_message / suggestion 为面向用户的中文文案，禁止暴露堆栈与内部术语。
"""
from dataclasses import dataclass
from typing import Literal

Level = Literal["blocker", "warning", "info"]
Retryable = Literal["resume", "restart_with_input", "no"]


@dataclass(frozen=True)
class ErrorDef:
    code: str
    level: Level
    user_message: str
    suggestion: str
    retryable: Retryable


_DEFS = [
    # ---- E1xxx 输入类 ----
    ErrorDef("E1001", "blocker", "文件类型不支持", "请上传 .pptx 模板或 .pdf/.docx 主文档", "restart_with_input"),
    ErrorDef("E1002", "blocker", "文件大小超出限制", "模板不超过 50MB，文档不超过 100MB", "restart_with_input"),
    ErrorDef("E1003", "blocker", "文件已损坏或被加密，无法读取", "请上传未加密的完整文件", "restart_with_input"),
    ErrorDef("E1004", "blocker", "目标页数超出允许范围（5~100 页）", "请调整目标页数后重新提交", "restart_with_input"),
    ErrorDef("E1005", "blocker", "模板或文档尚未解析完成或解析失败", "请等待解析完成，或更换文件", "restart_with_input"),
    # ---- E2xxx 解析类 ----
    ErrorDef("E2001", "blocker", "PDF 解析失败", "请确认文件可正常打开，或转存后重新上传", "restart_with_input"),
    ErrorDef("E2002", "blocker", "DOCX 解析失败", "请确认文件可正常打开，或转存后重新上传", "restart_with_input"),
    ErrorDef("E2003", "blocker", "无法从文档提取有效文本（疑似扫描件或加密 PDF）", "请上传可复制文本的 PDF 或 DOCX 版本", "restart_with_input"),
    ErrorDef("E2004", "blocker", "PPT 模板解析失败", "请更换模板，或使用系统默认模板", "restart_with_input"),
    ErrorDef("E2005", "blocker", "模板中没有可用版式", "请更换包含正文版式的模板", "restart_with_input"),
    # ---- E3xxx AI 类 ----
    ErrorDef("E3001", "blocker", "AI 服务暂时不可用（所有模型通道均失败）", "请稍后点击重试；若持续失败请联系管理员检查模型配置", "resume"),
    ErrorDef("E3002", "blocker", "AI 返回结果格式异常且多次修复失败", "请点击重试；持续失败可尝试降低页数或更换模式", "resume"),
    ErrorDef("E3003", "blocker", "无法在目标页数约束下完成大纲规划", "请调整目标页数，或减少章节要求", "restart_with_input"),
    ErrorDef("E3004", "blocker", "页面内容生成整体失败", "请点击重试；持续失败请更换模式或联系管理员", "resume"),
    ErrorDef("E3005", "blocker", "内容触发模型安全策略被拦截", "请检查文档内容后重新提交", "restart_with_input"),
    # ---- E4xxx 渲染类 ----
    ErrorDef("E4001", "blocker", "PPT 文件渲染失败", "请点击重试；持续失败请联系管理员", "resume"),
    ErrorDef("E4002", "blocker", "字体解析失败", "请联系管理员检查容器字体配置", "resume"),
    ErrorDef("E4003", "blocker", "图表构建失败", "请点击重试", "resume"),
    # ---- E5xxx 质检修复类 ----
    ErrorDef("E5001", "blocker", "自动修复后仍存在严重布局错误", "请尝试降低内容密度或减少页数后重试", "resume"),
    # ---- E6xxx 存储类 ----
    ErrorDef("E6001", "blocker", "对象存储服务不可用", "请联系管理员检查 MinIO/OSS 服务", "resume"),
    ErrorDef("E6002", "blocker", "产物上传失败", "请点击重试", "resume"),
    ErrorDef("E6003", "warning", "预览转换服务不可用，已跳过 PDF/图片预览", "PPTX 可正常下载；请联系管理员检查转换服务", "no"),
    # ---- E7xxx 系统类 ----
    ErrorDef("E7001", "blocker", "任务执行超时", "请点击重试；持续超时请降低页数或更换极速模式", "resume"),
    ErrorDef("E7002", "blocker", "执行进程异常退出", "请点击重试", "resume"),
    ErrorDef("E7003", "blocker", "内部依赖服务故障（队列/数据库）", "请联系管理员检查服务状态", "resume"),
    ErrorDef("E7004", "blocker", "等待用户确认超时且无默认策略", "请重新发起生成并及时完成确认", "resume"),
    ErrorDef("E7005", "blocker", "任务已被取消", "可重新发起生成", "resume"),
]

ERRORS: dict[str, ErrorDef] = {e.code: e for e in _DEFS}


class PPTError(Exception):
    """业务异常：携带错误码，Orchestrator 捕获后据此落库并推送前端。"""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.definition = ERRORS.get(code) or ErrorDef(code, "blocker", "未知错误", "请联系管理员", "resume")
        # detail 仅入日志，不直接暴露给用户
        self.detail = detail
        super().__init__(f"{code} {self.definition.user_message} {detail}")

    @property
    def user_message(self) -> str:
        return self.definition.user_message
