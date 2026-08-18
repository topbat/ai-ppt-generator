import json


_ART_SYSTEM = """你是企业演示文稿的整册艺术指导。
只返回视觉与叙事元数据 JSON，不得补充、推断或改写任何业务事实。
必须继承给定企业模板的字体和品牌色，只能在安全内容区域内规划构图。"""

_STORYBOARD_SYSTEM = """你是企业演示文稿的视觉分镜师。
只返回逐页叙事角色、层级、布局家族、焦点位置与内容容量。
严禁研究外部信息、创造新事实或改写页面标题；不要输出正文内容。"""


def generate_art_direction(gateway, mode, template_tokens, outline, job_id) -> dict:
    safe_tokens = {
        key: template_tokens.get(key)
        for key in (
            "primary",
            "secondary",
            "accent",
            "background",
            "font_title",
            "font_body",
        )
    }
    chapters = [item.get("chapter", "") for item in outline if isinstance(item, dict)]
    user = json.dumps(
        {
            "template_tokens": safe_tokens,
            "chapter_titles": chapters,
            "required_fields": [
                "concept",
                "visual_motif",
                "composition",
                "palette",
                "font_title",
                "font_body",
                "reading_mode",
                "rhythm",
            ],
        },
        ensure_ascii=False,
    )
    return gateway.chat_json(
        "page_content",
        mode,
        _ART_SYSTEM,
        user,
        job_id=job_id,
        temperature=0.2,
        max_tokens=1600,
    )


def generate_storyboard(gateway, mode, art_direction, page_plan, job_id) -> dict:
    pages = [
        {"page": item.get("page"), "type": item.get("type"), "title": item.get("title", "")}
        for item in page_plan
        if isinstance(item, dict)
    ]
    user = json.dumps(
        {
            "art_direction": art_direction,
            "pages": pages,
            "allowed_layout_families": [
                "single_focus",
                "split",
                "cards_grid",
                "flow",
                "structure",
                "data_focus",
                "editorial",
            ],
            "required_fields_per_page": [
                "page",
                "narrative_role",
                "importance",
                "thesis",
                "layout_family",
                "focal_element",
                "focal_position",
                "max_points",
                "max_chars",
                "key_slide_candidate",
            ],
        },
        ensure_ascii=False,
    )
    return gateway.chat_json(
        "page_content",
        mode,
        _STORYBOARD_SYSTEM,
        user,
        job_id=job_id,
        temperature=0.2,
        max_tokens=3000,
    )
