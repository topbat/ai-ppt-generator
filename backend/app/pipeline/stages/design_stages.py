from app.ai.agents.design_agent import generate_art_direction, generate_storyboard
from app.core.logging import get_logger
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.schemas.composition import DeckArtDirection, SlideVisualPlan

logger = get_logger(__name__)


def _gateway_or_default(gateway):
    if gateway is not None:
        return gateway
    from app.ai.gateway import get_gateway

    return get_gateway()


def _default_art_direction(tokens: dict) -> DeckArtDirection:
    palette = [
        tokens.get("primary") or "1677FF",
        tokens.get("secondary") or "13234E",
        tokens.get("accent") or "36CFC9",
        tokens.get("background") or "FFFFFF",
    ]
    return DeckArtDirection(
        concept="品牌一致的清晰叙事",
        visual_motif="企业网格与重点标记",
        composition="品牌外壳内的受控非对称构图",
        palette=palette,
        font_title=tokens.get("font_title") or "Microsoft YaHei",
        font_body=tokens.get("font_body") or "Microsoft YaHei",
        reading_mode="balanced",
        rhythm=["establish", "explain", "focus", "resolve"],
    )


def _default_visual_plan(page: dict, index: int) -> SlideVisualPlan:
    slide_type = page.get("type") or "title_content"
    structural = {
        "cover": ("opening", "single_focus", "full", "primary"),
        "toc": ("navigation", "editorial", "left", "secondary"),
        "section": ("chapter_transition", "single_focus", "full", "primary"),
        "summary": ("conclusion", "editorial", "center", "primary"),
        "ending": ("closing", "single_focus", "full", "supporting"),
    }
    type_family = {
        "bar_chart": "data_focus",
        "line_chart": "data_focus",
        "pie_chart": "data_focus",
        "table": "data_focus",
        "timeline": "flow",
        "process": "flow",
        "architecture": "structure",
        "comparison": "structure",
        "three_cards": "cards_grid",
        "four_cards": "cards_grid",
        "key_number": "single_focus",
        "two_column": "split",
        "three_column": "cards_grid",
    }
    focal_by_type = {
        "bar_chart": "chart",
        "line_chart": "chart",
        "pie_chart": "chart",
        "table": "table",
        "timeline": "timeline",
        "process": "process",
        "architecture": "architecture",
        "comparison": "comparison",
        "key_number": "key_number",
        "three_cards": "cards",
        "four_cards": "cards",
    }
    if slide_type in structural:
        narrative_role, family, focal_position, importance = structural[slide_type]
    else:
        rotation = ["editorial", "split", "cards_grid", "data_focus", "structure", "flow"]
        narrative_role = "evidence"
        family = type_family.get(slide_type, rotation[index % len(rotation)])
        focal_position = ["left", "right", "center"][index % 3]
        importance = "primary" if slide_type in {
            "bar_chart",
            "line_chart",
            "pie_chart",
            "architecture",
            "comparison",
        } else "secondary"
    return SlideVisualPlan(
        page=int(page.get("page") or index + 1),
        narrative_role=narrative_role,
        importance=importance,
        thesis=page.get("key_message") or page.get("title") or f"第{index + 1}页",
        layout_family=family,
        focal_element=focal_by_type.get(slide_type, "bullet_group"),
        focal_position=focal_position,
        max_points=4 if slide_type in structural else 5,
        max_chars=120 if slide_type in structural else 180,
        key_slide_candidate=slide_type in {
            "bar_chart",
            "line_chart",
            "pie_chart",
            "architecture",
            "comparison",
            "key_number",
        },
    )


class ArtDirectionStage(Stage):
    code = "ART_DIRECTION"
    weight = 3

    def __init__(self, gateway=None):
        self.gateway = gateway

    def run(self, ctx: JobContext) -> dict:
        tokens = (ctx.data.get("PARSE_TPL") or {}).get("design_tokens") or {}
        default = _default_art_direction(tokens)
        if ctx.mode == "fast":
            return {"art_direction": default.model_dump(), "source": "default", "degraded": False}
        try:
            raw = generate_art_direction(
                _gateway_or_default(self.gateway),
                ctx.mode,
                tokens,
                (ctx.data.get("OUTLINE") or {}).get("outline") or [],
                ctx.job_pk,
            )
            direction = DeckArtDirection.model_validate(raw.get("art_direction") or raw)
            return {"art_direction": direction.model_dump(), "source": "model", "degraded": False}
        except Exception as error:
            logger.warning("整册艺术指导生成失败，使用模板继承默认值: %s", error)
            return {
                "art_direction": default.model_dump(),
                "source": "default",
                "degraded": True,
                "warning": str(error),
            }


class StoryboardStage(Stage):
    code = "STORYBOARD"
    weight = 4

    def __init__(self, gateway=None):
        self.gateway = gateway

    def run(self, ctx: JobContext) -> dict:
        page_plan = (ctx.data.get("PLAN") or {}).get("plan") or []
        raw_slides = []
        degraded = False
        warning = None
        if ctx.mode != "fast":
            try:
                raw = generate_storyboard(
                    _gateway_or_default(self.gateway),
                    ctx.mode,
                    (ctx.data.get("ART_DIRECTION") or {}).get("art_direction") or {},
                    page_plan,
                    ctx.job_pk,
                )
                raw_slides = raw.get("slides") or []
            except Exception as error:
                degraded = True
                warning = str(error)
                logger.warning("视觉分镜生成失败，使用确定性分镜: %s", error)

        raw_by_page = {
            item.get("page"): item
            for item in raw_slides
            if isinstance(item, dict) and isinstance(item.get("page"), int)
        }
        slides = []
        completed_pages = []
        for index, page in enumerate(page_plan):
            default = _default_visual_plan(page, index)
            supplied = raw_by_page.get(default.page)
            if supplied is None:
                plan = default
                completed_pages.append(default.page)
            else:
                try:
                    plan = SlideVisualPlan.model_validate({**default.model_dump(), **supplied})
                except Exception:
                    plan = default
                    completed_pages.append(default.page)
                    degraded = True
            slides.append(plan.model_dump())
        result = {
            "slides": slides,
            "completed_pages": completed_pages,
            "source": "default" if ctx.mode == "fast" or not raw_slides else "model",
            "degraded": degraded,
        }
        if warning:
            result["warning"] = warning
        return result
