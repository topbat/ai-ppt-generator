"""三模式流水线 DAG 定义（文档 §4）。

三种模式共用同一批 Stage 实现，差异体现在：
1. 阶段编排不同（fast 无 CONVERT/REPAIR 主链路阶段）；
2. Stage 内部按 ctx.mode 选择策略（章节批量 vs 页级并行、LLM 档位、修复轮次）。
PARSE_DOC 与 PARSE_TPL 声明为并行组，由 Orchestrator 并发执行。
"""
from app.pipeline.stages.assemble_stages import LayoutStage, MatchStage
from app.pipeline.stages.base import Stage
from app.pipeline.stages.beautify_stage import BeautifyStage
from app.pipeline.stages.content_stage import ContentStage
from app.pipeline.stages.composition_stage import CompositionStage
from app.pipeline.stages.design_stages import ArtDirectionStage, StoryboardStage
from app.pipeline.stages.knowledge_stages import FactCheckStage, KnowledgeStage
from app.pipeline.stages.parse_stages import ParseDocStage, ParseTemplateStage, ValidateStage
from app.pipeline.stages.plan_stages import OutlineStage, PlanStage
from app.pipeline.stages.publish_stage import PublishStage
from app.pipeline.stages.qa_stages import QAStage, RepairStage
from app.pipeline.stages.render_stages import ConvertStage, RenderStage


def _stages(*classes) -> list[Stage]:
    return [cls() for cls in classes]


class KeySlideDesignPlaceholderStage(Stage):
    """专业关键页 Agent 的流水线插槽；下一阶段替换为受约束实现。"""

    code = "KEY_SLIDE_DESIGN"
    weight = 5

    def run(self, ctx) -> dict:
        return {"selected": [], "applied": [], "fallback": []}


# 编排为"组"的列表：组内多个阶段并行执行，组间串行
PIPELINES: dict[str, list[list[Stage]]] = {
    # ⚡ 极速：最少调用+最大并行；CONVERT 移出主链路（PUBLISH 后异步）
    "fast": [
        _stages(ValidateStage),
        _stages(ParseDocStage, ParseTemplateStage),   # 并行组
        _stages(KnowledgeStage),
        _stages(FactCheckStage),
        _stages(OutlineStage),                        # 大纲+规划合并调用
        _stages(PlanStage),                           # 零调用，仅骨架重建
        _stages(ContentStage),                        # 章节批量并行
        _stages(MatchStage),
        _stages(LayoutStage),
        _stages(RenderStage),
        _stages(QAStage),                             # 仅规则 QA
        _stages(PublishStage),
    ],
    # 🚀 标准：页级并行 + BEAUTIFY 规则闭环(≤2轮) + 预览进主链路 + 1 轮修复
    "standard": [
        _stages(ValidateStage),
        _stages(ParseDocStage, ParseTemplateStage),
        _stages(KnowledgeStage),
        _stages(FactCheckStage),
        _stages(OutlineStage),
        _stages(PlanStage),
        _stages(ArtDirectionStage),
        _stages(StoryboardStage),
        _stages(ContentStage),
        _stages(MatchStage),
        _stages(CompositionStage),
        _stages(LayoutStage),
        _stages(RenderStage),
        _stages(BeautifyStage),                       # 视觉优化闭环（管"好不好看"）
        _stages(ConvertStage),
        _stages(QAStage),
        _stages(RepairStage),
        _stages(PublishStage),
    ],
    # 💎 专业：事实冲突交互 + BEAUTIFY 闭环(+Vision Critic) + Vision QA + ≤3 轮修复
    "premium": [
        _stages(ValidateStage),
        _stages(ParseDocStage, ParseTemplateStage),
        _stages(KnowledgeStage),
        _stages(FactCheckStage),
        _stages(OutlineStage),
        _stages(PlanStage),
        _stages(ArtDirectionStage),
        _stages(StoryboardStage),
        _stages(ContentStage),
        _stages(MatchStage),
        _stages(CompositionStage),
        _stages(LayoutStage),
        _stages(KeySlideDesignPlaceholderStage),
        _stages(RenderStage),
        _stages(BeautifyStage),                       # 规则闭环 ≤2 轮 + Vision Critic 1 轮
        _stages(ConvertStage),
        _stages(QAStage),
        _stages(RepairStage),
        _stages(PublishStage),
    ],
}


def total_weight(mode: str) -> int:
    return sum(s.weight for group in PIPELINES[mode] for s in group)
