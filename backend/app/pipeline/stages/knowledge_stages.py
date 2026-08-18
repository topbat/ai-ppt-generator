"""S04~S05：内容理解（知识建模）与事实核验。

- fast    ：规则抽取关键数字（零 LLM 调用）；
- standard：+1 次 LLM 章节结构化摘要；
- premium ：+事实注册表（facts 落库）+ 冲突检测 + 用户决策交互。
"""
import re

from app.ai.gateway import get_gateway, repair_json
from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import Fact, FactConflict
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.pipeline.stages.decisions import request_decision

logger = get_logger(__name__)

# 关键事实抽取：主语(2~10字) + 数值 + 单位
_FACT_RE = re.compile(
    r"([一-龥A-Za-z]{2,10}?)(?:约|达到|达|为|是|共计|共|计)?"
    r"(\d+(?:\.\d+)?)\s*(亿元|万元|亿|万人|万|个|人|套|项|%|平方米|公里|家|台|次)")

_UNIT_NORM = {"亿元": 1e8, "亿": 1e8, "万元": 1e4, "万人": 1e4, "万": 1e4}


class KnowledgeStage(Stage):
    code = "KNOWLEDGE"
    weight = 6

    def run(self, ctx: JobContext) -> dict:
        ir = ctx.get_doc_ir()
        output: dict = {"chapter_count": len(ir["chapters"])}

        # 规则抽取关键数字（全模式，供数字回查与报告）
        fact_count = self._extract_facts(ctx, ir)
        output["fact_count"] = fact_count

        if ctx.mode in ("standard", "premium"):
            # 1 次 LLM 章节结构化摘要，提升大纲质量
            gw = get_gateway()
            brief = "\n\n".join(f"【{c['title']}】\n{c['content'][:1200]}" for c in ir["chapters"][:10])
            text = gw.chat_text(
                "doc_summary", ctx.mode,
                "你是文档分析专家，只输出JSON。",
                f"请为以下各章节输出一句话摘要与3个关键要点。\n{brief}\n\n"
                '输出JSON: {"chapters":[{"title":"章节名","summary":"摘要","key_points":["要点"]}]}',
                job_id=ctx.job_pk, max_tokens=3000, json_mode=True,
                model_override=ctx.model)
            parsed = repair_json(text)
            if parsed and parsed.get("chapters"):
                output["chapter_summaries"] = parsed["chapters"]
                logger.info("知识建模完成：%d 个章节摘要", len(parsed["chapters"]))
            else:
                logger.warning("章节摘要解析失败，跳过（不阻塞主流程）")
        return output

    def _extract_facts(self, ctx: JobContext, ir: dict) -> int:
        """规则抽取关键事实入库（premium 全量入 facts 表，其他模式仅统计）。"""
        doc = ctx.document_row()
        rows = []
        for ch in ir["chapters"]:
            pages = ch.get("source_pages") or [1]
            for m in _FACT_RE.finditer(ch["content"][:20000]):
                key, num, unit = m.group(1), m.group(2), m.group(3)
                norm = float(num) * _UNIT_NORM.get(unit, 1)
                rows.append(dict(fact_key=f"{key}", content=f"{num}{unit}",
                                 value_norm=norm, unit=unit, source_page=pages[0]))
        if ctx.mode == "premium" and rows:
            with db_session() as db:
                db.query(Fact).filter_by(job_id=ctx.job_pk).delete()
                for r in rows[:500]:  # 上限保护
                    db.add(Fact(document_id=doc.id, job_id=ctx.job_pk, grade="A", **r))
        logger.info("关键事实抽取完成：%d 条", len(rows))
        return len(rows)


class FactCheckStage(Stage):
    code = "FACT_CHECK"
    weight = 2

    def run(self, ctx: JobContext) -> dict:
        if ctx.mode != "premium":
            # fast/standard：数字回查在 ContentGuard 内完成，此处仅登记
            return {"conflicts": 0, "mode": ctx.mode}

        # premium：同键不同值 → 冲突 → 用户决策（最多弹 3 个，其余按默认策略）
        with db_session() as db:
            facts = db.query(Fact).filter_by(job_id=ctx.job_pk).all()
        by_key: dict[str, list] = {}
        for f in facts:
            by_key.setdefault(f"{f.fact_key}|{f.unit}", []).append(f)
        conflicts = {k: v for k, v in by_key.items()
                     if len({float(x.value_norm) for x in v}) > 1}
        logger.info("事实冲突检测：%d 组冲突", len(conflicts))

        resolutions = {}
        for i, (key, cands) in enumerate(sorted(conflicts.items())):
            uniq = {}
            for f in cands:
                uniq.setdefault(f.content, f)
            cand_list = list(uniq.values())
            default = max(cand_list, key=lambda f: f.source_page).content  # 默认取较后出现的值
            with db_session() as db:
                db.add(FactConflict(job_id=ctx.job_pk, fact_key=key,
                                    candidates=[{"fact_id": f.id, "content": f.content,
                                                 "page": f.source_page} for f in cand_list]))
            if i < 3:  # 只弹前 3 个，避免决策疲劳
                choice = request_decision(ctx, "fact_conflict", {
                    "title": f"「{cands[0].fact_key}」存在多个取值",
                    "description": "资料中同一事实出现不同数值，请选择正式 PPT 使用的值",
                    "options": [{"value": f.content, "label": f.content,
                                 "detail": f"来源第{f.source_page}页"} for f in cand_list]
                    + [{"value": "__discard__", "label": "都不使用", "detail": "该数字不进入正式内容"}],
                }, default_choice=default)
            else:
                choice = default
            resolutions[cands[0].fact_key] = choice
            with db_session() as db:
                row = db.query(FactConflict).filter_by(job_id=ctx.job_pk, fact_key=key).first()
                if row:
                    row.status = "resolved"
                    row.resolution = "discard" if choice == "__discard__" else "user_choice"
                    row.resolved_by = "user" if i < 3 else "system"
        return {"conflicts": len(conflicts), "resolutions": resolutions}
