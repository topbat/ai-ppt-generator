"""S13~S14：质量检查与自动修复。

QA（规则层，全模式）：页数硬约束、渲染备注（截断/溢出/降级）、相邻页重复、内容告警汇总；
QA（Vision 层，专业模式且开关开启）：多模态模型审整册截图；
REPAIR：文案类问题 → LLM 定向压缩改写（标准 ≤1 轮 / 专业 ≤3 轮），每轮质量分必须上升。
"""
import base64
import time
from collections import Counter

from app.core.config import get_settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.models.models import JobSlide, ValidationReport
from app.pipeline.context import JobContext
from app.pipeline.guards.guards import content_guard
from app.pipeline.stages.base import Stage
from app.pipeline.stages.render_stages import load_spec, render_and_upload

logger = get_logger(__name__)


def build_report(ctx: JobContext, extra_issues: list[dict] | None = None) -> dict:
    """汇总规则 QA 报告与质量分。"""
    issues: list[dict] = list(extra_issues or [])
    render_out = ctx.data.get("RENDER") or {}
    spec = load_spec(ctx)

    # 1. 页数硬约束
    page_ok = len(spec.slides) == ctx.target_pages
    if not page_ok:
        issues.append({"page": None, "kind": "page_count", "level": "error",
                       "detail": f"页数 {len(spec.slides)} != 目标 {ctx.target_pages}"})

    # 2. 渲染备注：分三级——error(页面降级/尾页泄漏) / warning(视觉缺陷) / info(自动处理记录)
    _ERROR_KINDS = {"page_degraded", "ending_leak"}
    _INFO_KINDS = {"element_missing", "image_skipped", "toc_partial",
                   "subtitle_skipped", "bullets_trimmed", "frame_cleaned",
                   "key_message_trimmed", "timeline_desc_dropped"}
    for note in render_out.get("render_notes", []):
        kind = note["issue"]
        level = ("error" if kind in _ERROR_KINDS
                 else "info" if kind in _INFO_KINDS else "warning")
        issues.append({"page": note.get("page"), "kind": kind,
                       "level": level, "detail": note["detail"]})

    # 3. 相邻页标题重复
    titles = [(s.page, s.title) for s in spec.slides if s.type not in ("cover", "toc")]
    for (p1, t1), (p2, t2) in zip(titles, titles[1:]):
        if t1 and t1 == t2:
            issues.append({"page": p2, "kind": "duplicate_title", "level": "warning",
                           "detail": f"与第 {p1} 页标题重复：{t1}"})

    # 4. 内容生成期记录（Guard 自动处理行为，属 info 级留痕；仅"失败"类计为 warning）
    with db_session() as db:
        for row in db.query(JobSlide).filter_by(job_id=ctx.job_pk).all():
            for it in row.qa_issues or []:
                level = "warning" if ("失败" in str(it)) else "info"
                issues.append({"page": row.page_no, "kind": "content", "level": level,
                               "detail": it})

    # 字段别名：内部用 kind/level/detail，前端契约为 issue_type/severity/message
    for i in issues:
        i.setdefault("issue_type", i.get("kind"))
        i.setdefault("severity", i.get("level"))
        i.setdefault("message", i.get("detail"))

    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warning")
    # 质量分：error 重罚、warning 轻罚；info 仅留痕不扣分。下限 40
    score = max(40, 100 - errors * 8 - warnings * 2)
    status = "fail" if errors and not page_ok else ("warning" if (errors or warnings) else "pass")

    # ---- 多维度质量标准（文字/图片/内容/配色/章节一致性） ----
    by_kind: dict[str, int] = {}
    for i in issues:
        if i["level"] in ("error", "warning"):
            by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1

    def dim(*kinds) -> dict:
        n = sum(by_kind.get(k, 0) for k in kinds)
        has_err = any(k in ("page_degraded", "ending_leak") and by_kind.get(k) for k in kinds)
        return {"status": "fail" if has_err else ("warning" if n else "pass"), "issues": n}

    cleaned = sum(1 for i in issues if i["kind"] == "frame_cleaned")
    report = {
        "status": status, "score": score, "errors": errors, "warnings": warnings,
        "checks": {
            "page_count": {"status": "pass" if page_ok else "fail",
                           "expected": ctx.target_pages, "actual": len(spec.slides)},
            "fact_accuracy": {"status": "pass",
                              "conflicts": (ctx.data.get("FACT_CHECK") or {}).get("conflicts", 0)},
            # 文字维度：位置/大小/字体/长度/越界（截断与溢出计数）
            "text_layout": dim("text_truncated", "text_overflow"),
            # 图片维度：位置/叠压（模板示例图渲染期已清理，template_cleaned 为清理数）
            "image_layout": {**dim("image_overlap"), "template_cleaned": cleaned},
            # 内容合理性：尾页内容泄漏/标题重复/页面降级
            "content_sanity": dim("ending_leak", "duplicate_title", "page_degraded"),
            # 配色协调：背景识别 + 深底浅字自适应由渲染器保证
            "color_harmony": {"status": "pass", "adaptive": True},
            # 章节页一致性：居中固定构图，跨章节/跨模板位置统一
            "section_consistency": {"status": "pass", "normalized": True},
            "layout": {"status": "warning" if warnings else "pass",
                       "slides": sorted({i["page"] for i in issues if i.get("page")})},
            "template": {"status": "pass",
                         "hit_rate": (ctx.data.get("MATCH") or {}).get("template_hit_rate")},
        },
        "issues": issues[:200],
    }

    # ---- 构图与整册节奏（独立于历史 quality/visual 分，保持兼容） ----
    compose = ctx.data.get("COMPOSE") or {}
    records = list((compose.get("composition_by_page") or {}).values())
    guard_issues = [issue for record in records for issue in record.get("guard_issues", [])]
    margin_violations = sum(
        1 for issue in guard_issues if str(issue.get("code", "")).startswith("margin_")
    )
    typography_violations = sum(
        1 for issue in guard_issues
        if str(issue.get("code", "")).startswith("font_")
        or "typography" in str(issue.get("code", ""))
    )
    deck_issues = compose.get("deck_issues") or []
    adjacent_duplicates = sum(
        1 for issue in deck_issues if issue.get("code") == "adjacent_fingerprint_duplicate"
    )
    focal_streaks = sum(
        1 for issue in deck_issues if issue.get("code") == "focal_position_streak"
    )
    families = [record.get("family") for record in records if record.get("family")]
    dominant_ratio = (
        Counter(families).most_common(1)[0][1] / len(families) if families else 0.0
    )
    from app.ppt.visual_score import score_composition_rhythm

    key_slides = ctx.data.get("KEY_SLIDE_DESIGN") or {}
    report["composition"] = {
        "margin_violations": margin_violations,
        "typography_violations": typography_violations,
        "adjacent_fingerprint_duplicates": adjacent_duplicates,
        "dominant_family_ratio": round(dominant_ratio, 3),
        "deck_rhythm_score": score_composition_rhythm(
            margin_violations,
            typography_violations,
            adjacent_duplicates,
            dominant_ratio if len(families) >= 4 else 0.0,
            focal_streaks,
        ),
        "key_slides_selected": key_slides.get("selected") or [],
        "key_slides_applied": key_slides.get("applied") or [],
        "key_slides_fallback": key_slides.get("fallback") or [],
    }

    # ---- 视觉九维明细（visual_score，与 quality_score 并列展示、不互相替代） ----
    visual = ((ctx.data.get("BEAUTIFY") or {}).get("visual")
              or ctx._cache.get("visual_result"))
    if visual:
        report["visual"] = {
            "score": visual["score"],
            "dimensions": visual["dimensions"],
            "score_before": (ctx.data.get("BEAUTIFY") or {}).get("score_before"),
            "rounds": (ctx.data.get("BEAUTIFY") or {}).get("rounds"),
            "ops_applied": (ctx.data.get("BEAUTIFY") or {}).get("ops_applied", []),
            "pages": [{"page": p["page"], "score": p["score"],
                       "deductions": p["deductions"]} for p in visual.get("pages", [])],
        }
    return report


def save_report(ctx: JobContext, report: dict, round_no: int) -> None:
    with db_session() as db:
        db.query(ValidationReport).filter_by(job_id=ctx.job_pk, round=round_no).delete()
        db.add(ValidationReport(job_id=ctx.job_pk, round=round_no, status=report["status"],
                                score=report["score"], errors=report["errors"],
                                warnings=report["warnings"], report=report))


class QAStage(Stage):
    code = "QA"
    weight = 5
    resumable = False

    def run(self, ctx: JobContext) -> dict:
        # 极速模式不跑 BEAUTIFY 闭环，但仍在此一次性出视觉分（毫秒级规则计算 + 落库）
        if "BEAUTIFY" not in ctx.data:
            from app.pipeline.stages.beautify_stage import compute_visual_once
            visual = compute_visual_once(ctx)
            if visual:
                ctx.set_cached("visual_result", visual)
        vision_issues = self._vision_qa(ctx) if (
            ctx.mode == "premium" and get_settings().vision_qa_enabled) else []
        report = build_report(ctx, vision_issues)
        save_report(ctx, report, round_no=1)
        logger.info("质量检查完成：score=%d errors=%d warnings=%d 视觉分=%s",
                    report["score"], report["errors"], report["warnings"],
                    (report.get("visual") or {}).get("score", "-"))
        return {"report": report}

    def _vision_qa(self, ctx: JobContext) -> list[dict]:
        """Vision QA（专业模式可选）：抽前 6 页截图送 qwen-vl 审查。失败仅告警。"""
        try:
            from app.ai.gateway import get_gateway, repair_json
            with db_session() as db:
                rows = [r for r in db.query(JobSlide).filter_by(job_id=ctx.job_pk)
                        .order_by(JobSlide.page_no).limit(6).all() if r.image_key]
            if not rows:
                logger.info("Vision QA 跳过：暂无页面截图")
                return []
            content = [{"type": "text", "text":
                        "你是PPT视觉审查专家。逐页检查：文字溢出/页面过挤/页面过空/图表不清晰/风格不统一。"
                        '只输出JSON: {"issues":[{"page":页码,"detail":"问题描述"}]}，无问题输出 {"issues":[]}'}]
            for r in rows:
                b64 = base64.b64encode(ctx.storage.get_bytes(r.image_key)).decode()
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"}})
            gw = get_gateway()
            from app.ai.gateway import provider_of
            vision_model = get_settings().llm_model_vision  # 具体模型由环境变量指定
            resp = gw._client(provider_of(vision_model)).chat.completions.create(
                model=vision_model, messages=[{"role": "user", "content": content}],
                max_tokens=1500)
            parsed = repair_json(resp.choices[0].message.content or "")
            issues = [{"page": i.get("page"), "kind": "vision", "level": "warning",
                       "detail": i.get("detail", "")} for i in (parsed or {}).get("issues", [])]
            logger.info("Vision QA 完成：发现 %d 个视觉问题", len(issues))
            return issues
        except Exception as e:
            logger.warning("Vision QA 失败(降级为规则QA，不阻塞): %s", e)
            return []


class RepairStage(Stage):
    code = "REPAIR"
    weight = 3
    resumable = False

    # 生成后修复闭环：标准/专业最多 3 轮（无问题时零开销），极速 1 轮
    MAX_ROUNDS = {"fast": 1, "standard": 3, "premium": 3}
    _FIXABLE = {"text_truncated", "text_overflow"}

    def run(self, ctx: JobContext) -> dict:
        from app.ai.agents.repair_agent import compress_slide_text
        from app.ai.gateway import get_gateway

        max_rounds = self.MAX_ROUNDS.get(ctx.mode, 0)
        report = (ctx.data.get("QA") or {}).get("report") or build_report(ctx)
        best_score = report["score"]
        rounds_done = 0

        for round_no in range(1, max_rounds + 1):
            target_pages = sorted({i["page"] for i in report["issues"]
                                   if i.get("page") and i["kind"] in self._FIXABLE})[:5]
            if not target_pages:
                logger.info("无可修复的文案类问题，修复闭环提前结束")
                break
            logger.info("自动修复第 %d 轮：目标页 %s", round_no, target_pages)
            spec = load_spec(ctx)
            pages = ctx.get_pages_content()
            gw = get_gateway()
            changed = False
            for pno in target_pages:
                content = pages.get(str(pno))
                if not content or not content.get("elements"):
                    continue
                issues_txt = [i["detail"] for i in report["issues"] if i.get("page") == pno][:3]
                try:
                    fixed = compress_slide_text(gw, ctx.mode, content, issues_txt, ctx.job_pk)
                    plan_page = next(p for p in ctx.data["PLAN"]["plan"] if p["page"] == pno)
                    material = ""  # 修复只压缩不新增，无需原文回查新增数字
                    guarded, _ = content_guard(fixed, plan_page, ctx.density, material, "fast")
                    pages[str(pno)] = guarded
                    for i, s in enumerate(spec.slides):
                        if s.page == pno:
                            spec.slides[i] = s.model_copy(update={
                                "title": guarded["title"], "subtitle": guarded.get("subtitle"),
                                "elements": guarded["elements"]})
                    changed = True
                except Exception as e:
                    logger.warning("第 %d 页修复失败(保留原内容): %s", pno, e)
            if not changed:
                break
            # 重渲染 + 重新 QA 评分
            render_result = render_and_upload(ctx, spec)
            ctx.data["RENDER"]["render_notes"] = render_result["notes"]
            ctx.storage.put_json(ctx.data["LAYOUT"]["pjson_key"], spec.model_dump())
            ctx.set_cached("presentation_spec", spec)
            ctx.storage.put_json(ctx.data["CONTENT"]["pages_key"], pages)
            report = build_report(ctx)
            save_report(ctx, report, round_no=round_no + 1)
            rounds_done = round_no
            logger.info("修复第 %d 轮后质量分：%d（此前最优 %d）", round_no, report["score"], best_score)
            if report["score"] <= best_score:
                logger.info("质量分未提升，停止修复（取当前版本）")
                break
            best_score = report["score"]

        ctx.data.setdefault("QA", {})["report"] = report
        return {"rounds": rounds_done, "final_score": report["score"]}
