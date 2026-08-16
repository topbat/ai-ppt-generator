"""Guard 层：所有边界条件的集中校验与确定性修正（文档 §30 铁律：不散落在 Agent 中）。

- PageGuard  : 页数硬约束——以确定性骨架重建页面计划，保证总页数分毫不差；
- ContentGuard: 受控类型/文案预算/数字回查；
- 数字回查   : 生成文案中的数字必须能在原文中找到，专业模式剔除查不到的条目。
"""
import re

from app.core.logging import get_logger
from app.schemas.presentation import DENSITY_LIMITS, ELEMENT_TYPES, SLIDE_TYPES

logger = get_logger(__name__)


# ================= PageGuard =================

def build_page_plan(outline: list[dict], ai_slides: list[dict], target_pages: int,
                    doc_title: str, has_ending: bool = False) -> tuple[list[dict], list[str]]:
    """以确定性骨架重建逐页计划（页数硬约束的最终保证）。

    骨架：第1页 cover + 第2页 toc + 每章[section + 正文页] + summary
          （+ ending 尾页，模板含"感谢聆听"类尾页时启用）。
    AI 产出的正文页规划按章节回填；不足补默认页，超出截断。
    返回 (plan, warnings)。
    """
    warnings: list[str] = []
    fixed_base = 3 + (1 if has_ending else 0)  # 封面+目录+总结(+尾页)
    n_chapters = len(outline)
    content_budget = target_pages - fixed_base - n_chapters
    if content_budget < n_chapters:  # 每章至少 1 页正文
        # 页数预算冲突的确定性降级：合并尾部章节直至可行（文档 §40 选项2）
        merged_names: list[str] = []
        while len(outline) > 1 and target_pages - fixed_base - len(outline) < len(outline):
            merged = outline.pop()
            merged_names.insert(0, str(merged.get("chapter", "")))
            outline[-1]["pages"] = outline[-1].get("pages", 1) + merged.get("pages", 1)
        if merged_names:
            base = str(outline[-1]["chapter"])
            combined = base + "与" + "与".join(merged_names)
            # 合并名过长时用概括命名，避免目录出现"A与B与C与D"长串
            outline[-1]["chapter"] = combined if len(combined) <= 14 else \
                f"{base}及其他{len(merged_names)}项工作"
        n_chapters = len(outline)
        content_budget = target_pages - fixed_base - n_chapters
        warnings.append(f"章节数超出页数预算，已自动合并为 {n_chapters} 章")
        logger.warning("Page Budget 冲突：自动合并章节至 %d 章", n_chapters)
    content_budget = max(content_budget, n_chapters)

    # 按大纲比例分配各章正文页数（余数从前往后补）
    raw = [max(1, int(o.get("pages", 1))) for o in outline]
    total_raw = sum(raw)
    alloc = [max(1, round(r * content_budget / total_raw)) for r in raw]
    while sum(alloc) > content_budget:
        alloc[alloc.index(max(alloc))] -= 1
    i = 0
    while sum(alloc) < content_budget:
        alloc[i % n_chapters] += 1
        i += 1

    # AI 正文页规划按章节归组
    by_chapter: dict[int, list[dict]] = {}
    for s in ai_slides or []:
        idx = s.get("chapter_idx") or 0
        if idx >= 1 and s.get("type") in SLIDE_TYPES and s.get("type") not in (
                "cover", "toc", "section", "summary"):
            by_chapter.setdefault(int(idx), []).append(s)

    def _unique_title(raw: str, key_message: str, chapter: str, last: str) -> str:
        """标题去重：正文页标题不得与章节名/上一页标题重复（消除 duplicate_title）。"""
        title = (raw or "").strip()[:24] or chapter
        if title in (chapter, last):
            km = (key_message or "").strip()
            if 4 <= len(km) <= 24 and km not in (chapter, last):
                title = km
            elif title == last:
                title = f"{title}（续）"[:26]
            else:
                title = f"{title}·详解"[:26]
        return title

    plan: list[dict] = []
    page = 1
    plan.append({"page": page, "type": "cover", "title": doc_title, "chapter_idx": 0})
    page += 1
    plan.append({"page": page, "type": "toc", "title": "目录", "chapter_idx": 0,
                 "toc_items": [o["chapter"] for o in outline]})
    page += 1
    last_title = ""  # 跨章节全局去重：不同章节的正文页标题也不得重复
    for ci, (o, count) in enumerate(zip(outline, alloc), start=1):
        plan.append({"page": page, "type": "section", "title": o["chapter"], "chapter_idx": ci,
                     "section_no": ci, "key_message": o.get("summary", "")})
        page += 1
        candidates = by_chapter.get(ci, [])
        if len(candidates) < count:
            warnings.append(f"章节「{o['chapter']}」AI 规划页不足，已补充 {count - len(candidates)} 页默认版式")
        for k in range(count):
            if k < len(candidates):
                c = candidates[k]
                title = _unique_title(str(c.get("title", "")), str(c.get("key_message", "")),
                                      o["chapter"], last_title)
                plan.append({"page": page, "type": c["type"], "title": title,
                             "chapter_idx": ci, "key_message": c.get("key_message", "")})
            else:  # 兜底默认页
                title = f"{o['chapter'][:18]}·要点{k + 1}"
                plan.append({"page": page, "type": "title_content", "title": title,
                             "chapter_idx": ci, "key_message": o.get("summary", "")})
            last_title = title
            page += 1
        if len(candidates) > count:
            warnings.append(f"章节「{o['chapter']}」AI 规划页超出预算，截断 {len(candidates) - count} 页")
    plan.append({"page": page, "type": "summary", "title": "总结", "chapter_idx": 0,
                 "summary_items": [f"{o['chapter']}：{o.get('summary', '')}" for o in outline]})
    if has_ending:
        page += 1
        plan.append({"page": page, "type": "ending", "title": "感谢聆听", "chapter_idx": 0})

    # 终检后处理：相邻页标题若仍相同（如正文页标题恰与下一章章节名一致），
    # 修改其中的正文页标题（结构页标题即章节名，不可改）
    _structural = ("section", "cover", "toc", "summary", "ending")
    for prev, cur in zip(plan, plan[1:]):
        if not cur.get("title") or cur["title"] != prev.get("title"):
            continue
        target = cur if cur["type"] not in _structural else (
            prev if prev["type"] not in _structural else None)
        if target is None:
            continue
        km = str(target.get("key_message") or "").strip()
        if 4 <= len(km) <= 24 and km != prev["title"]:
            target["title"] = km
        else:
            target["title"] = (target["title"] + "·详解")[:26]

    assert len(plan) == target_pages, f"PageGuard 内部错误: {len(plan)} != {target_pages}"
    logger.info("PageGuard 完成：%d 页计划（%d 章，正文 %d 页），修正 %d 处",
                target_pages, n_chapters, content_budget, len(warnings))
    return plan, warnings


# ================= ContentGuard =================

def _truncate(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def content_guard(page_content: dict, plan: dict, density: str,
                  source_text: str, mode: str) -> tuple[dict, list[str]]:
    """单页内容校验与修正。返回 (修正后内容, 问题列表)。

    1. 版式/元素类型必须在受控枚举内（枚举外直接剔除/回退）；
    2. 文案按密度预算截断；
    3. 数字回查：premium 剔除查不到的条目，其他模式记 Warning。
    """
    issues: list[str] = []
    lim = DENSITY_LIMITS[density]
    out = {
        "page": plan["page"],
        "type": page_content.get("type") or plan["type"],
        "title": _truncate(page_content.get("title") or plan.get("title", ""), lim["title"]),
        "subtitle": _truncate(page_content.get("subtitle") or "", lim["subtitle"]) or None,
        "elements": [],
    }
    if out["type"] not in SLIDE_TYPES:
        issues.append(f"非受控版式 {out['type']} 已回退为 title_content")
        out["type"] = "title_content"

    src_numbers = _numbers_of(source_text)
    for el in page_content.get("elements") or []:
        if not isinstance(el, dict) or el.get("type") not in ELEMENT_TYPES:
            issues.append(f"剔除非受控元素: {el.get('type') if isinstance(el, dict) else el}")
            continue
        el = _apply_limits(el, lim, issues)
        el, num_issues = _verify_numbers(el, src_numbers, mode)
        issues.extend(num_issues)
        if el is not None:
            out["elements"].append(el)

    if not out["elements"]:
        # 空页兜底：以核心观点生成要点，避免出现空白页
        issues.append("页面无有效元素，已用核心观点兜底")
        out["elements"] = [{"type": "bullet_group",
                            "items": [plan.get("key_message") or plan.get("title", "")]}]
    return out, issues


def _apply_limits(el: dict, lim: dict, issues: list[str]) -> dict:
    """按密度预算截断各类元素文案。"""
    t = el["type"]
    if t == "bullet_group":
        items = [_truncate(i, lim["bullet"]) for i in (el.get("items") or [])][: lim["max_items"]]
        if len(el.get("items") or []) > lim["max_items"]:
            issues.append(f"要点数超预算，截断至 {lim['max_items']} 条")
        return {"type": t, "items": items}
    if t == "cards":
        items = [{"title": _truncate(i.get("title"), lim["card_title"]),
                  "desc": _truncate(i.get("desc"), lim["card_desc"])}
                 for i in (el.get("items") or []) if isinstance(i, dict)][: lim["max_items"]]
        return {"type": t, "items": items}
    if t == "key_number":
        items = [{"value": _truncate(i.get("value"), 10), "label": _truncate(i.get("label"), 14)}
                 for i in (el.get("items") or []) if isinstance(i, dict)][:4]
        return {"type": t, "items": items}
    if t == "process":
        return {"type": t, "steps": [_truncate(s, 12) for s in (el.get("steps") or [])][:6]}
    if t == "timeline":
        items = [{"time": _truncate(i.get("time"), 10), "title": _truncate(i.get("title"), 12),
                  "desc": _truncate(i.get("desc"), 24)}
                 for i in (el.get("items") or []) if isinstance(i, dict)][:6]
        return {"type": t, "items": items}
    if t == "architecture":
        layers = [{"title": _truncate(y.get("title"), 10),
                   "items": [_truncate(x, 10) for x in (y.get("items") or [])][:5]}
                  for y in (el.get("layers") or []) if isinstance(y, dict)][:5]
        return {"type": t, "layers": layers}
    if t == "comparison":
        def side(s):
            s = s or {}
            return {"title": _truncate(s.get("title"), 12),
                    "items": [_truncate(x, lim["bullet"]) for x in (s.get("items") or [])][:5]}
        return {"type": t, "left": side(el.get("left")), "right": side(el.get("right"))}
    if t == "paragraph":
        return {"type": t, "text": _truncate(el.get("text"), lim["body_total"])}
    if t == "quote":
        return {"type": t, "text": _truncate(el.get("text"), 60), "author": _truncate(el.get("author"), 20)}
    return el  # chart/table 结构在渲染层清洗


# ================= 数字回查 =================

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers_of(text: str) -> set[str]:
    return set(_NUM_RE.findall((text or "").replace(",", "").replace("，", "")))


def _texts_of_element(el: dict) -> list[str]:
    t = el.get("type")
    if t == "bullet_group":
        return el.get("items", [])
    if t == "cards":
        return [f"{i.get('title', '')}{i.get('desc', '')}" for i in el.get("items", [])]
    if t == "key_number":
        return [f"{i.get('value', '')}{i.get('label', '')}" for i in el.get("items", [])]
    if t == "paragraph":
        return [el.get("text", "")]
    return []


def _verify_numbers(el: dict, src_numbers: set[str], mode: str) -> tuple[dict | None, list[str]]:
    """数字回查：文案中 2 位以上数字必须存在于原文。

    - premium：剔除含未验证数字的条目（宁缺毋假）；
    - fast/standard：保留但记 Warning（进质检报告）。
    图表数据同样校验（数据点级）。
    """
    issues: list[str] = []

    def unverified(text: str) -> list[str]:
        return [n for n in _NUM_RE.findall(str(text).replace(",", ""))
                if len(n.replace(".", "")) >= 2 and n not in src_numbers]

    if el.get("type") == "chart":
        data = el.get("data") or []
        bad = [d for d in data if isinstance(d, dict) and unverified(str(d.get("value", "")))]
        if bad:
            if mode == "premium":
                el["data"] = [d for d in data if d not in bad]
                issues.append(f"图表剔除 {len(bad)} 个原文无法验证的数据点")
            else:
                issues.append(f"图表存在 {len(bad)} 个原文未验证数据点(保留并标注)")
        return el, issues

    texts = _texts_of_element(el)
    bad_idx = [i for i, t in enumerate(texts) if unverified(t)]
    if not bad_idx:
        return el, issues
    if mode == "premium":
        t = el.get("type")
        if t == "bullet_group":
            el["items"] = [x for i, x in enumerate(el["items"]) if i not in bad_idx]
        elif t in ("cards", "key_number"):
            el["items"] = [x for i, x in enumerate(el["items"]) if i not in bad_idx]
        issues.append(f"剔除 {len(bad_idx)} 条原文无法验证数字的内容(专业模式宁缺毋假)")
        if not el.get("items") and t in ("bullet_group", "cards", "key_number"):
            return None, issues
    else:
        issues.append(f"{len(bad_idx)} 条内容含原文未验证数字(保留并进入质检报告)")
    return el, issues
