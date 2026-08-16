"""PDF 解析器（PyMuPDF）：产出统一 Document IR。

Document IR 结构：
{
  "title": str, "page_count": int, "char_count": int, "image_count": int,
  "table_count": int, "is_scanned": bool,
  "pages": [{"page": int, "text": str}],
  "chapters": [{"title": str, "content": str, "source_pages": [int]}]
}

章节识别策略：按字号统计找出显著大于正文的标题行；识别不出时按页数
均分为伪章节（保证下游流程始终有章节结构可用）。
"""
import math
import re
import statistics

import fitz

from app.core.errors import PPTError
from app.core.logging import get_logger

logger = get_logger(__name__)

# 扫描件判定阈值：全文有效字符低于该值视为无文本
MIN_TEXT_CHARS = 50


def parse_pdf(path: str, filename: str = "") -> dict:
    try:
        doc = fitz.open(path)
    except Exception as e:
        logger.error("PDF 打开失败: %s", e)
        raise PPTError("E2001", str(e)) from e

    if doc.needs_pass:
        doc.close()
        raise PPTError("E1003", "PDF 已加密")

    try:
        pages, spans, image_count, table_count = [], [], 0, 0
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            pages.append({"page": i + 1, "text": text})
            image_count += len(page.get_images())
            try:  # find_tables 在部分版本可能不可用/报错，不影响主流程
                table_count += len(page.find_tables().tables)
            except Exception:
                pass
            # 收集带字号的文本行用于标题识别
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    line_text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                    sizes = [s.get("size", 0) for s in line.get("spans", [])]
                    if line_text and sizes:
                        spans.append({"page": i + 1, "text": line_text, "size": max(sizes)})

        char_count = sum(len(p["text"]) for p in pages)
        is_scanned = char_count < MIN_TEXT_CHARS
        if is_scanned:
            # OCR 未启用时直接明确报错（禁止"解析失败→AI 编内容"）
            logger.warning("PDF 无有效文本(共 %d 字符)，判定为扫描件", char_count)
            raise PPTError("E2003", f"有效字符数 {char_count}")

        chapters = _detect_chapters(spans, pages)
        import os as _os
        clean_name = _os.path.splitext(filename)[0] if filename else ""
        title = _guess_title(spans) or clean_name or "未命名文档"
        ir = {
            "title": title, "page_count": len(pages), "char_count": char_count,
            "image_count": image_count, "table_count": table_count, "is_scanned": is_scanned,
            "pages": pages, "chapters": chapters,
        }
        logger.info("PDF 解析完成：%d 页 / %d 字 / %d 章节 / %d 表格 / %d 图片",
                    len(pages), char_count, len(chapters), table_count, image_count)
        return ir
    finally:
        doc.close()


def _guess_title(spans: list[dict]) -> str | None:
    """取首页字号最大的短行作为文档标题（清理"第X部分："类结构前缀）。"""
    first = [s for s in spans if s["page"] == 1 and 2 <= len(s["text"]) <= 50]
    if not first:
        return None
    title = max(first, key=lambda s: s["size"])["text"]
    return re.sub(r"^第[一二三四五六七八九十\d]+(?:部分|章|节)[：:、\s]*", "", title).strip() or title


# 常见中文章节标题模式（如"第一章""一、""1. "）
_HEADING_RE = re.compile(r"^(第[一二三四五六七八九十百\d]+[章节部分篇]|[一二三四五六七八九十]+[、.．]|\d{1,2}[、.．\s])")


def _detect_chapters(spans: list[dict], pages: list[dict]) -> list[dict]:
    headings = []
    if spans:
        body_size = statistics.median(s["size"] for s in spans)
        for s in spans:
            text = s["text"]
            if len(text) > 40:
                continue
            # 字号显著大于正文，或命中章节标题模式
            if s["size"] >= body_size * 1.25 or (_HEADING_RE.match(text) and s["size"] >= body_size):
                headings.append(s)
    # 去掉第 1 页的候选（多为封面标题），并按页码排序去重
    headings = [h for h in headings if h["page"] > 1]
    seen, uniq = set(), []
    for h in sorted(headings, key=lambda x: x["page"]):
        if h["text"] not in seen:
            seen.add(h["text"])
            uniq.append(h)

    if len(uniq) >= 2:
        chapters = []
        # 边界兜底：首个标题之前的页面若有大量正文（非纯封面），并入"引言"章节，避免内容丢失
        first_page = uniq[0]["page"]
        if first_page > 1:
            head_text = "\n".join(p["text"] for p in pages if p["page"] < first_page)
            if len(head_text) > 200:
                chapters.append({"title": "引言", "content": head_text,
                                 "source_pages": list(range(1, first_page))})
        for idx, h in enumerate(uniq):
            start = h["page"]
            end = uniq[idx + 1]["page"] - 1 if idx + 1 < len(uniq) else pages[-1]["page"]
            end = max(start, end)
            content = "\n".join(p["text"] for p in pages if start <= p["page"] <= end)
            chapters.append({"title": h["text"][:40], "content": content,
                             "source_pages": list(range(start, end + 1))})
        logger.info("按标题识别出 %d 个章节", len(chapters))
        return chapters

    # 兜底：识别不出章节 → 按页均分为伪章节（Fallback，保证下游可用）
    n = max(2, min(6, math.ceil(len(pages) / 8)))
    size = math.ceil(len(pages) / n)
    chapters = []
    for i in range(0, len(pages), size):
        seg = pages[i:i + size]
        chapters.append({
            "title": f"第{len(chapters) + 1}部分",
            "content": "\n".join(p["text"] for p in seg),
            "source_pages": [p["page"] for p in seg],
        })
    logger.info("未识别到章节标题，按页均分为 %d 个伪章节(兜底)", len(chapters))
    return chapters
