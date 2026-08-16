"""BEAUTIFY 阶段：视觉优化闭环（docs/04-VISUAL-OPTIMIZATION.md §5~§6）。

位置：RENDER 之后、CONVERT 之前。与 REPAIR 独立——REPAIR 管"对不对"，BEAUTIFY 管"好不好看"。

闭环：视觉评分（规则九维）→ Fix Ops → 确定性调整 → 重渲染 → 复评（分数必须上升，
≤2 轮，取历史最优）；专业模式追加 Vision Critic（qwen-vl 建议受控 Ops）再执行 1 轮。
极速模式不进本阶段（仅 Token 化渲染一次性正确），但 QA 阶段仍会调用
compute_visual_once() 出分落库（分数可见、不追加耗时闭环）。
"""
import base64
import os
import tempfile

from app.core.config import get_settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import GenerationJob, JobSlide
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.pipeline.stages.render_stages import _template_render_info, load_spec
from app.ppt.visual_ops import (SPEC_OPS, apply_spec_ops, derive_ops, polish_pptx,
                                validate_ops)
from app.ppt.visual_score import score_presentation
from app.schemas.presentation import PresentationSpec

logger = get_logger(__name__)


def persist_visual(job_pk: int, visual: dict) -> None:
    """视觉分落库：generation_jobs.visual_score（册级）+ job_slides.visual_score（页级）。"""
    with db_session() as db:
        job = db.get(GenerationJob, job_pk)
        if job is not None:
            job.visual_score = visual.get("score")
        rows = {r.page_no: r for r in db.query(JobSlide).filter_by(job_id=job_pk).all()}
        for p in visual.get("pages", []):
            row = rows.get(p["page"])
            if row is not None:
                row.visual_score = p["score"]
    logger.info("视觉分已落库：册级 %s 分 / 页级 %d 页", visual.get("score"),
                len(visual.get("pages", [])))


def compute_visual_once(ctx: JobContext) -> dict | None:
    """一次性视觉评分（极速模式用）：下载渲染产物 → 规则九维出分 → 落库。失败不阻塞。"""
    try:
        spec = load_spec(ctx)
        pptx_key = (ctx.data.get("RENDER") or {}).get("pptx_key")
        if not pptx_key:
            return None
        with tempfile.TemporaryDirectory(prefix="pptvscore_") as tmp:
            local = os.path.join(tmp, "final.pptx")
            ctx.storage.download_to(pptx_key, local)
            visual = score_presentation(spec, local,
                                        (ctx.data.get("RENDER") or {}).get("render_notes", []))
        persist_visual(ctx.job_pk, visual)
        return visual
    except Exception as e:
        logger.warning("一次性视觉评分失败（不阻塞主链路）：%s", e)
        return None


class BeautifyStage(Stage):
    code = "BEAUTIFY"
    weight = 6
    resumable = False

    MAX_ROUNDS = 2          # 规则闭环轮次上限（标准/专业）
    TARGET_SCORE = 90       # 达标分：达到即提前收束

    def run(self, ctx: JobContext) -> dict:
        from app.ppt.renderer import render_presentation

        spec = load_spec(ctx)
        render_notes = (ctx.data.get("RENDER") or {}).get("render_notes", [])
        ops_applied: list[dict] = []
        rounds_done = 0

        with tempfile.TemporaryDirectory(prefix="pptbeauty_") as tmp:
            template = _template_render_info(ctx, tmp)
            cur_path = os.path.join(tmp, "round0.pptx")
            ctx.storage.download_to(ctx.data["RENDER"]["pptx_key"], cur_path)

            result = score_presentation(spec, cur_path, render_notes)
            score0 = result["score"]
            best = {"score": score0, "spec": spec, "path": cur_path,
                    "result": result, "notes": render_notes}
            logger.info("BEAUTIFY 开始：初始视觉分 %d（目标 ≥%d，闭环 ≤%d 轮）",
                        score0, self.TARGET_SCORE, self.MAX_ROUNDS)

            # ---- 规则闭环（≤2 轮，分数必须上升，取历史最优） ----
            for rnd in range(1, self.MAX_ROUNDS + 1):
                if best["score"] >= self.TARGET_SCORE:
                    logger.info("视觉分 %d 已达标（≥%d），闭环提前收束", best["score"], self.TARGET_SCORE)
                    break
                ops = derive_ops(best["result"], best["spec"].model_dump())
                spec_ops = [o for o in ops if o["op"] in SPEC_OPS]
                if not spec_ops:
                    logger.info("BEAUTIFY 第 %d 轮：无可执行的 spec 级修复指令，闭环结束", rnd)
                    break
                improved = self._apply_and_rescore(
                    ctx, best, spec_ops, os.path.join(tmp, f"round{rnd}.pptx"),
                    template, render_presentation, tag=f"规则闭环第 {rnd} 轮")
                rounds_done = rnd
                if improved is None:
                    break
                best, applied = improved
                ops_applied += applied

            # ---- 专业模式：Vision Critic 补充受控 Ops，再执行 1 轮 ----
            if ctx.mode == "premium" and get_settings().vision_qa_enabled:
                vops = self._vision_critic(ctx, best, tmp)
                spec_vops = [o for o in vops if o["op"] in SPEC_OPS]
                if spec_vops:
                    improved = self._apply_and_rescore(
                        ctx, best, spec_vops, os.path.join(tmp, "vision.pptx"),
                        template, render_presentation, tag="Vision Critic 轮")
                    if improved is not None:
                        best, applied = improved
                        ops_applied += applied

            # ---- 归档最优版本：final.pptx + 美化后 Presentation JSON + 视觉分落库 ----
            pptx_key = ctx.key("final.pptx")
            ctx.storage.put_file(
                pptx_key, best["path"],
                "application/vnd.openxmlformats-officedocument.presentationml.presentation")
            pjson_key = ctx.key(f"presentation.beautified.{ctx.attempt}.json")
            ctx.storage.put_json(pjson_key, best["spec"].model_dump())
            ctx.data["LAYOUT"]["pjson_key"] = pjson_key      # 下游（REPAIR/PUBLISH）以美化版为准
            ctx.data["RENDER"]["pptx_key"] = pptx_key
            ctx.data["RENDER"]["render_notes"] = best["notes"]
            ctx.set_cached("presentation_spec", best["spec"])

        persist_visual(ctx.job_pk, best["result"])
        delta = best["score"] - score0
        logger.info("✨ BEAUTIFY 完成：视觉分 %d → %d（%s%d）｜闭环 %d 轮｜应用 Ops %d 条",
                    score0, best["score"], "+" if delta >= 0 else "", delta,
                    rounds_done, len(ops_applied))
        return {"visual": best["result"], "score_before": score0,
                "score_after": best["score"], "rounds": rounds_done,
                "ops_applied": ops_applied}

    # ---- 单轮：应用 ops → 重渲染 → 微调 → 复评；分数上升才采纳 ----
    def _apply_and_rescore(self, ctx, best, spec_ops, out_path, template,
                           render_presentation, tag: str):
        new_dict, applied, skipped = apply_spec_ops(
            best["spec"].model_dump(), spec_ops, ctx.density)
        if not applied:
            logger.info("%s：全部 %d 条指令无法应用（跳过 %d），闭环结束", tag, len(spec_ops), len(skipped))
            return None
        try:
            new_spec = PresentationSpec.model_validate(new_dict)
            render_result = render_presentation(new_spec, out_path, template=template)
            polish_pptx(out_path)
            new_result = score_presentation(new_spec, out_path, render_result["notes"])
        except Exception as e:
            logger.warning("%s：重渲染/复评失败（保留上一版本）：%s", tag, e)
            return None
        if new_result["score"] > best["score"]:
            logger.info("%s：视觉分 %d → %d（应用 %d 条 Ops），采纳新版本",
                        tag, best["score"], new_result["score"], len(applied))
            return ({"score": new_result["score"], "spec": new_spec, "path": out_path,
                     "result": new_result, "notes": render_result["notes"]}, applied)
        logger.info("%s：复评 %d ≤ 当前最优 %d，回退取历史最优版本",
                    tag, new_result["score"], best["score"])
        return None

    # ---- Vision Critic：截图 → qwen-vl → 只允许建议枚举内 op ----
    def _vision_critic(self, ctx, best, tmp: str) -> list[dict]:
        try:
            from app.ai.gateway import get_gateway, provider_of, repair_json
            from app.services import convert

            pdf = convert.pptx_to_pdf(best["path"], tmp)
            if pdf is None:
                logger.warning("Vision Critic 跳过：预览转换不可用（E6003 同类降级）")
                return []
            images = {im["page"]: im["image_path"] for im in convert.pdf_to_images(pdf, tmp)}
            # 优先审查评分最低的 6 页（问题密度最高，token 花在刀刃上）
            worst_pages = [p["page"] for p in
                           sorted(best["result"]["pages"], key=lambda p: p["score"])[:6]
                           if p["page"] in images]
            if not worst_pages:
                return []
            content = [{"type": "text", "text": (
                "你是PPT视觉审查专家。以下是演示文稿中视觉评分最低的几页截图（页码依次为 "
                f"{worst_pages}）。请指出视觉问题并给出修复指令。"
                "修复指令只能从以下枚举中选择：snap_align(对齐锚线)、apply_spacing(间距吸附)、"
                "font_token(内容精简恢复字号)、reduce_palette(收敛配色)、"
                "upgrade_layout(低密度页升格大字报)、rebalance(两栏配平)。"
                '只输出JSON：{"ops":[{"op":"枚举值","page":页码,"detail":"问题描述"}]}，'
                '无问题输出 {"ops":[]}')}]
            for pno in worst_pages:
                b64 = base64.b64encode(open(images[pno], "rb").read()).decode()
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"}})
            gw = get_gateway()
            vision_model = get_settings().llm_model_vision
            resp = gw._client(provider_of(vision_model)).chat.completions.create(
                model=vision_model, messages=[{"role": "user", "content": content}],
                max_tokens=1500)
            parsed = repair_json(resp.choices[0].message.content or "") or {}
            ops = validate_ops(parsed.get("ops"), total_pages=ctx.target_pages)
            logger.info("Vision Critic 完成：审查 %d 页，建议受控 Ops %d 条", len(worst_pages), len(ops))
            return ops
        except Exception as e:
            logger.warning("Vision Critic 失败（降级为纯规则闭环，不阻塞）：%s", e)
            return []
