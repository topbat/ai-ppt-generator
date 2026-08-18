from app.ai.agents.key_slide_agent import freeze_slide_content
from app.ppt import design_tokens as dt
from app.ppt.layouts import ELEMENT_PAINTERS, _header, _rect, _text
from app.schemas.composition import Box
from app.schemas.scene import SceneSpec


def _color(rc, token: str) -> str:
    return {
        "primary": rc.theme.primary,
        "secondary": rc.theme.secondary,
        "accent": rc.accent_color,
        "text": rc.body_color,
        "muted": rc.muted_color,
        "surface": dt.SURFACE_COLOR,
    }[token]


def paint_scene(rc, slide, data: dict) -> bool:
    raw = (data.get("visual_plan") or {}).get("scene_spec")
    if not raw:
        return False
    scene = SceneSpec.model_validate(raw)
    from app.schemas.presentation import SlideSpec

    locked = freeze_slide_content(SlideSpec.model_validate(data))
    for primitive in sorted(scene.primitives, key=lambda item: item.z_index):
        box = Box.model_validate(primitive.box)
        x, y, width, height = box.content_rect()
        value = locked.get(primitive.content_id)
        if primitive.type == "text":
            size = dt.TYPO_ROLES[primitive.font_role][1]
            _text(
                rc,
                slide,
                primitive.text,
                x,
                y,
                width,
                height,
                size,
                _color(rc, primitive.style_token),
                bold=primitive.font_role in {"page_title", "conclusion"},
                font=getattr(rc.theme, primitive.font_token),
                role=primitive.font_role,
                page=data.get("page"),
            )
        elif primitive.type in {"chart", "table"} and isinstance(value, dict):
            ELEMENT_PAINTERS[primitive.type](
                rc, slide, value, x, y, width, height, data.get("page")
            )
        elif primitive.type == "connector":
            _rect(slide, x, y + height / 2, width, min(0.03, height), _color(rc, primitive.style_token))
        else:
            _rect(slide, x, y, width, height, _color(rc, primitive.style_token), rounded=True)
    return True


def paint_scene_page(rc, slide, data: dict) -> bool:
    if not (data.get("visual_plan") or {}).get("scene_spec"):
        return False
    _header(rc, slide, data)
    return paint_scene(rc, slide, data)
