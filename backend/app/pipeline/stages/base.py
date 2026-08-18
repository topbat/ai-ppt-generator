"""Stage 统一接口：幂等、可 checkpoint、自报耗时（计时由 Orchestrator 统一落库）。"""
from app.pipeline.context import JobContext

# 阶段中文名（前端展示用）
STAGE_NAMES = {
    "VALIDATE": "输入校验", "PARSE_DOC": "文档解析", "PARSE_TPL": "模板解析",
    "KNOWLEDGE": "内容理解", "FACT_CHECK": "事实核验", "OUTLINE": "目录生成",
    "PLAN": "页面规划", "ART_DIRECTION": "整册艺术指导", "STORYBOARD": "视觉分镜",
    "CONTENT": "页面内容生成", "MATCH": "模板匹配",
    "LAYOUT": "版面组装", "RENDER": "PPT渲染", "BEAUTIFY": "视觉优化",
    "CONVERT": "预览转换",
    "QA": "质量检查", "REPAIR": "自动修复", "PUBLISH": "上传归档",
}


class Stage:
    code: str = ""
    resumable: bool = True   # False 的阶段断点重试时必定重跑（如 RENDER）
    weight: int = 5          # 总进度权重

    @property
    def name(self) -> str:
        return STAGE_NAMES.get(self.code, self.code)

    def run(self, ctx: JobContext) -> dict:
        """返回轻量可序列化输出（即 checkpoint 内容）。业务失败抛 PPTError。"""
        raise NotImplementedError
