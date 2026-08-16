"""Presentation JSON —— 系统最核心的中间层数据结构。

铁律（对应文档 §3.4）：
- AI 只能产出/修改本 Schema 描述的数据；Renderer 只消费本数据；
- slide.type 只能取 SLIDE_TYPES 受控枚举，枚举外类型在 ContentGuard 直接拒绝；
- 文案长度上限按内容密度取 DENSITY_LIMITS。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# 受控版式（ending=模板尾页"感谢聆听"，模板含尾页时自动追加）
SLIDE_TYPES = [
    "cover", "toc", "section", "title_content", "two_column", "three_column",
    "three_cards", "four_cards", "key_number", "quote", "timeline", "process",
    "architecture", "comparison", "table", "bar_chart", "line_chart", "pie_chart",
    "image_text", "summary", "ending",
]

# 元素类型（受控）
ELEMENT_TYPES = [
    "bullet_group",   # {items: [str]}
    "cards",          # {items: [{title, desc}]}
    "key_number",     # {items: [{value, label}]}
    "chart",          # {chart_type, title, unit, data: [{label, value}]}
    "table",          # {headers: [str], rows: [[str]]}
    "timeline",       # {items: [{time, title, desc}]}
    "process",        # {steps: [str]}
    "architecture",   # {layers: [{title, items}]}
    "comparison",     # {left: {title, items}, right: {title, items}}
    "quote",          # {text, author}
    "paragraph",      # {text}
]

# 内容密度 → 文案预算（字符数，中文全角计 1）
DENSITY_LIMITS = {
    "low":    {"title": 18, "subtitle": 30, "card_title": 12, "card_desc": 40, "bullet": 30, "body_total": 120, "max_items": 3},
    "medium": {"title": 18, "subtitle": 30, "card_title": 12, "card_desc": 50, "bullet": 40, "body_total": 180, "max_items": 5},
    "high":   {"title": 20, "subtitle": 34, "card_title": 14, "card_desc": 60, "bullet": 48, "body_total": 240, "max_items": 6},
}


class SlideSpec(BaseModel):
    page: int
    chapter_id: str | None = None
    type: str
    template_slide_id: int | None = None   # 绑定模板版式页；None=系统版式
    title: str = ""
    subtitle: str | None = None
    key_message: str | None = None
    section_no: int | None = None   # 章节页序号（section 版式用）
    elements: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)  # [{document_id, pages}]
    notes: str | None = None

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in SLIDE_TYPES:
            raise ValueError(f"非受控版式类型: {v}")
        return v

    @field_validator("elements")
    @classmethod
    def _check_elements(cls, v: list[dict]) -> list[dict]:
        for el in v:
            if not isinstance(el, dict) or el.get("type") not in ELEMENT_TYPES:
                raise ValueError(f"非受控元素类型: {el.get('type') if isinstance(el, dict) else el}")
        return v


class ThemeSpec(BaseModel):
    primary: str = "1677FF"          # 十六进制色值（不带#）
    secondary: str = "13234E"
    accent: str = "36CFC9"
    text: str = "1F1F1F"
    text_light: str = "8C8C8C"
    background: str = "FFFFFF"
    font_title: str = "Microsoft YaHei"
    font_body: str = "Microsoft YaHei"


class PresentationSpec(BaseModel):
    schema_version: str = "1.0"
    title: str
    page_size: Literal["16:9", "4:3"] = "16:9"
    total_pages: int
    mode: str = "fast"
    density: str = "medium"
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    slides: list[SlideSpec] = Field(default_factory=list)
