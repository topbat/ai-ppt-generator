"""S08 CONTENT：页面内容生成 —— 全系统最耗时阶段，并行是速度的关键。

- fast    ：章节级批量（1 章 1 次 LLM 调用），章节间线程并行；
- standard：页级并行；
- premium ：页级并行 + 事实提示注入（facts_hint）。
结构页（cover/toc/section/summary）全部确定性生成，零 LLM 调用、零编造风险。
单页/单章失败：重试 1 次 → 降级为要点页（绝不阻塞整册，文档 §66-8）。
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.ai.agents.content_agent import generate_chapter_batch, generate_page
from app.ai.gateway import get_gateway
from app.core.config import get_settings
from app.core.database import db_session
from app.core.errors import PPTError
from app.core.logging import get_logger
from app.models.models import Fact, JobSlide
from app.pipeline.context import JobContext
from app.pipeline.guards.capacity_guard import extract_numbers, fit_page_capacity
from app.pipeline.guards.guards import content_guard
from app.pipeline.stages.base import Stage

logger = get_logger(__name__)


class ContentStage(Stage):
    code = "CONTENT"
    weight = 32

    def run(self, ctx: JobContext) -> dict:
        plan = ctx.data["PLAN"]["plan"]
        outline = ctx.data["OUTLINE"]["outline"]
        ir = ctx.get_doc_ir()
        started = time.monotonic()

        pages: dict[str, dict] = {}
        issues_by_page: dict[int, list[str]] = {}
        degraded: list[int] = []

        # ---- 1. 结构页确定性生成（零 LLM）----
        for p in plan:
            if p["type"] == "cover":
                pages[str(p["page"])] = {"page": p["page"], "type": "cover", "title": p["title"],
                                         "subtitle": ctx.options.get("subtitle") or "汇报材料",
                                         "elements": []}
            elif p["type"] == "toc":
                pages[str(p["page"])] = {"page": p["page"], "type": "toc", "title": "目录",
                                         "elements": [{"type": "bullet_group",
                                                       "items": p.get("toc_items", [])}]}
            elif p["type"] == "section":
                pages[str(p["page"])] = {"page": p["page"], "type": "section", "title": p["title"],
                                         "section_no": p.get("section_no"),
                                         "key_message": p.get("key_message"), "elements": []}
            elif p["type"] == "summary":
                pages[str(p["page"])] = {"page": p["page"], "type": "summary", "title": "总结",
                                         "elements": [{"type": "bullet_group",
                                                       "items": p.get("summary_items", [])[:6]}]}
            elif p["type"] == "ending":
                pages[str(p["page"])] = {"page": p["page"], "type": "ending",
                                         "title": p.get("title", "感谢聆听"), "elements": []}

        for page_key, content in list(pages.items()):
            fitted, moved = self._fit_storyboard_capacity(ctx, int(page_key), content)
            pages[page_key] = fitted
            if moved:
                issues_by_page.setdefault(int(page_key), []).append(
                    f"内容容量超限，{moved} 条支持材料已移至演讲者备注"
                )

        content_plan = [p for p in plan
                        if p["type"] not in ("cover", "toc", "section", "summary", "ending")]
        logger.info("开始生成正文页：共 %d 页（模式=%s，结构页 %d 页已确定性生成）",
                    len(content_plan), ctx.mode, len(plan) - len(content_plan))

        # ---- 2. 正文页并行生成 ----
        material_of = self._material_resolver(outline, ir)
        branches: list[dict] = []
        if ctx.mode == "fast":
            self._run_fast(ctx, content_plan, material_of, pages, issues_by_page, degraded, branches)
        else:
            self._run_paged(ctx, content_plan, material_of, pages, issues_by_page, degraded, branches)

        # 全部正文页失败才判任务失败（文档 §13：容忍部分降级）
        if content_plan and len(degraded) >= len(content_plan):
            raise PPTError("E3004", f"全部 {len(content_plan)} 个正文页生成失败")

        # ---- 3. 落库 job_slides + 保存内容全集 ----
        self._save_slides(ctx, plan, pages, issues_by_page, degraded, material_of)
        pages_key = ctx.key(f"checkpoints/pages.{ctx.attempt}.json")
        ctx.storage.put_json(pages_key, pages)
        ctx.set_cached("pages_content", pages)

        elapsed = int((time.monotonic() - started) * 1000)
        logger.info("页面内容生成完成：%d 页 / 降级 %d 页 / 耗时 %dms",
                    len(pages), len(degraded), elapsed)
        return {"pages_key": pages_key, "degraded_pages": degraded,
                "issue_count": sum(len(v) for v in issues_by_page.values()),
                "branches": branches}

    # ---- 章节资料定位 ----
    def _material_resolver(self, outline, ir):
        chapters = ir["chapters"]
        full_text = "\n".join(c["content"] for c in chapters)

        def resolve(chapter_idx) -> dict:
            # 序号统一强转 int：LLM 产出（含断点续跑恢复的历史 checkpoint）
            # 可能是列表/字符串等非法类型，直接比较会炸掉整个阶段
            ci = _as_index(chapter_idx)
            o = outline[ci - 1] if 0 < ci <= len(outline) else None
            si = _as_index((o or {}).get("source_chapter_idx"))
            if 0 < si <= len(chapters):
                return chapters[si - 1]
            if 0 < ci <= len(chapters):
                return chapters[ci - 1]
            return {"title": (o or {}).get("chapter", ""), "content": full_text[:6000],
                    "source_pages": []}
        return resolve

    # ---- fast：章节批量并行 ----
    def _run_fast(self, ctx, content_plan, material_of, pages, issues_by_page, degraded, branches):
        gw = get_gateway()
        by_chapter: dict[int, list[dict]] = {}
        for p in content_plan:
            by_chapter.setdefault(p.get("chapter_idx") or 0, []).append(p)

        def gen_chapter(ci: int, plans: list[dict]):
            t0 = time.monotonic()
            material = material_of(ci)
            try:
                result = generate_chapter_batch(gw, ctx.mode, material, plans, ctx.density, ctx.job_pk)
                got = {int(s["page"]): s for s in result.get("slides", []) if s.get("page")}
            except Exception as e:
                logger.warning("章节 %d 批量生成失败，整章降级: %s", ci, e)
                got = {}
            for p in plans:
                raw = got.get(p["page"])
                self._accept_page(ctx, p, raw, material, pages, issues_by_page, degraded)
            return {"key": f"ch{ci}", "pages": [p["page"] for p in plans],
                    "duration_ms": int((time.monotonic() - t0) * 1000)}

        workers = min(get_settings().content_parallelism, max(1, len(by_chapter)))
        logger.info("章节并行生成：%d 章 / 并发 %d", len(by_chapter), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(gen_chapter, ci, plans) for ci, plans in by_chapter.items()]
            for f in as_completed(futures):
                branches.append(f.result())
                self._publish_progress(ctx, pages, issues_by_page)

    # ---- standard/premium：页级并行 ----
    def _run_paged(self, ctx, content_plan, material_of, pages, issues_by_page, degraded, branches):
        gw = get_gateway()
        facts_hint = self._facts_hint(ctx) if ctx.mode == "premium" else ""

        def gen_one(p: dict):
            t0 = time.monotonic()
            material = material_of(p.get("chapter_idx") or 0)
            raw = None
            for attempt in (1, 2):  # 单页失败重试 1 次
                try:
                    raw = generate_page(gw, ctx.mode, p, material["content"], ctx.density,
                                        ctx.job_pk, facts_hint=facts_hint)
                    break
                except Exception as e:
                    logger.warning("第 %d 页生成失败(第%d次): %s", p["page"], attempt, e)
            self._accept_page(ctx, p, raw, material, pages, issues_by_page, degraded)
            return {"key": f"p{p['page']}", "pages": [p["page"]],
                    "duration_ms": int((time.monotonic() - t0) * 1000)}

        workers = min(get_settings().content_parallelism, max(1, len(content_plan)))
        logger.info("页级并行生成：%d 页 / 并发 %d", len(content_plan), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(gen_one, p) for p in content_plan]
            done = 0
            for f in as_completed(futures):
                branches.append(f.result())
                done += 1
                if done % 2 == 0 or done == len(futures):
                    self._publish_progress(ctx, pages, issues_by_page)

    # ---- 单页收口：Guard 校验 + 降级兜底 + 事件推送 ----
    def _accept_page(self, ctx, plan_page, raw, material, pages, issues_by_page, degraded):
        page_no = plan_page["page"]
        if raw:
            content, issues = content_guard(raw, plan_page, ctx.density,
                                            material.get("content", ""), ctx.mode)
        else:
            # 降级为要点页：标题 + 核心观点（绝不留空、绝不编造）
            content = {"page": page_no, "type": "title_content", "title": plan_page.get("title", ""),
                       "subtitle": None,
                       "elements": [{"type": "bullet_group",
                                     "items": [plan_page.get("key_message") or plan_page.get("title", "")]}]}
            issues = ["页面生成失败，已降级为要点页"]
            degraded.append(page_no)
        content, moved = self._fit_storyboard_capacity(ctx, page_no, content)
        if moved:
            issues.append(f"内容容量超限，{moved} 条支持材料已移至演讲者备注")
        pages[str(page_no)] = content
        if issues:
            issues_by_page[page_no] = issues
        ctx.publisher.page_done(page_no, {
            "title": content.get("title", ""),
            "bullets": _preview_bullets(content)})

    def _fit_storyboard_capacity(self, ctx, page_no: int, content: dict) -> tuple[dict, int]:
        raw_plans = (ctx.data.get("STORYBOARD") or {}).get("slides") or []
        visual = next((plan for plan in raw_plans if plan.get("page") == page_no), None)
        if visual is None:
            return content, 0
        result = fit_page_capacity(
            content=content,
            max_points=int(visual.get("max_points") or 5),
            max_chars=int(visual.get("max_chars") or 180),
            source_numbers=extract_numbers(content),
        )
        visible = result.visible
        visible["visual_plan"] = visual
        if result.notes["moved_count"]:
            visible["speaker_notes"] = result.notes
        return visible, result.notes["moved_count"]

    def _publish_progress(self, ctx, pages, issues_by_page):
        done = len(pages)
        ctx.publisher.stage_update("CONTENT", "running",
                                   progress={"done": done, "total": ctx.target_pages})

    def _facts_hint(self, ctx) -> str:
        """premium：把已核验事实（含冲突决议）注入内容生成提示。"""
        resolutions = (ctx.data.get("FACT_CHECK") or {}).get("resolutions") or {}
        lines = [f"- {k}: {v}" for k, v in resolutions.items() if v != "__discard__"]
        with db_session() as db:
            facts = db.query(Fact).filter_by(job_id=ctx.job_pk).limit(40).all()
            keys_resolved = set(resolutions.keys())
            for f in facts:
                if f.fact_key not in keys_resolved:
                    lines.append(f"- {f.fact_key}: {f.content}（来源第{f.source_page}页）")
        return "\n".join(lines[:40])

    def _save_slides(self, ctx, plan, pages, issues_by_page, degraded, material_of):
        doc = ctx.document_row()
        with db_session() as db:
            db.query(JobSlide).filter_by(job_id=ctx.job_pk).delete()
            for p in plan:
                content = pages.get(str(p["page"])) or {}
                material = material_of(p.get("chapter_idx") or 0)
                db.add(JobSlide(
                    job_id=ctx.job_pk, page_no=p["page"],
                    chapter_id=f"ch{p.get('chapter_idx') or 0}",
                    slide_type=content.get("type", p["type"]), plan=p, content=content,
                    sources=[{"document_id": doc.biz_id, "name": doc.name,
                              "pages": material.get("source_pages", [])}]
                    if p.get("chapter_idx") else [],
                    status="degraded" if p["page"] in degraded else "generated",
                    degrade_reason="生成失败降级要点页" if p["page"] in degraded else None,
                    qa_issues=issues_by_page.get(p["page"]) or [],
                ))


def _as_index(v) -> int:
    """章节序号安全转 int：列表取首个，非法值归 0（视为无效走兜底）。"""
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _preview_bullets(content: dict) -> list[str]:
    """提取前 3 条要点作为前端"边生成边看"的内容卡片。"""
    for el in content.get("elements", []):
        if el.get("type") == "bullet_group":
            return [str(i) for i in el.get("items", [])[:3]]
        if el.get("type") == "cards":
            return [i.get("title", "") for i in el.get("items", [])[:3]]
    return [content.get("subtitle") or ""]
