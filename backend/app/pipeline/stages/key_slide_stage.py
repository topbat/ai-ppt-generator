from app.ai.agents.key_slide_agent import (
    freeze_slide_content,
    request_scene,
    validate_scene,
)
from app.core.logging import get_logger
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.ppt.deck_rhythm import select_key_slides
from app.schemas.composition import Box, SlideVisualPlan, TemplateSpaceContract
from app.schemas.scene import SceneSpec

logger = get_logger(__name__)


def _gateway_or_default(gateway):
    if gateway is not None:
        return gateway
    from app.ai.gateway import get_gateway

    return get_gateway()


def _default_contract():
    return TemplateSpaceContract(
        page_width=13.333,
        page_height=7.5,
        safe_zone=Box(x=0.9, y=1.5, width=11.533, height=5.45),
    )


class KeySlideDesignStage(Stage):
    code = "KEY_SLIDE_DESIGN"
    weight = 5
    resumable = False

    def __init__(self, gateway=None):
        self.gateway = gateway

    def run(self, ctx: JobContext) -> dict:
        spec = ctx._cache.get("presentation_spec")
        if spec is None:
            from app.pipeline.stages.render_stages import load_spec

            spec = load_spec(ctx)
        slides_by_page = {slide.page: slide for slide in spec.slides}
        plans = []
        for raw in (ctx.data.get("STORYBOARD") or {}).get("slides") or []:
            try:
                if raw.get("page") in slides_by_page and slides_by_page[raw["page"]].type not in {
                    "cover", "toc", "section", "summary", "ending"
                }:
                    plans.append(SlideVisualPlan.model_validate(raw))
            except Exception:
                continue
        chapter_by_page = {
            int(page["page"]): f"ch{page.get('chapter_idx') or 0}"
            for page in (ctx.data.get("PLAN") or {}).get("plan") or []
        }
        selected = select_key_slides(plans, chapter_by_page)
        try:
            contract = TemplateSpaceContract.model_validate(
                (ctx.data.get("PARSE_TPL") or {}).get("space_contract")
            )
        except Exception:
            contract = _default_contract()
        tokens = {
            key: value
            for key, value in ((ctx.data.get("PARSE_TPL") or {}).get("design_tokens") or {}).items()
            if key in {"primary", "secondary", "accent", "text", "background", "font_title", "font_body"}
        }
        applied = []
        fallback = []
        gateway = _gateway_or_default(self.gateway) if selected else None
        compose = (ctx.data.get("COMPOSE") or {}).get("composition_by_page") or {}

        for page in selected:
            slide = slides_by_page[page]
            locked = freeze_slide_content(slide)
            adjacent = [
                str((compose.get(str(candidate)) or {}).get("family") or "")
                for candidate in (page - 1, page + 1)
            ]
            accepted = None
            for attempt in range(2):
                try:
                    raw = request_scene(
                        gateway,
                        page,
                        locked,
                        tokens,
                        contract,
                        adjacent,
                        ctx.job_pk,
                    )
                    scene = SceneSpec.model_validate(raw.get("scene") or raw)
                    accepted = validate_scene(scene, locked, contract)
                    break
                except Exception as error:
                    logger.warning("第 %d 页关键页设计第 %d 次失败: %s", page, attempt + 1, error)
            if accepted is None:
                fallback.append(page)
                continue
            slide.visual_plan = {
                **(slide.visual_plan or {}),
                "scene_spec": accepted.model_dump(),
            }
            applied.append(page)

        if applied:
            pjson_key = ctx.data["LAYOUT"]["pjson_key"]
            ctx.storage.put_json(pjson_key, spec.model_dump())
            ctx._cache["presentation_spec"] = spec
        return {"selected": selected, "applied": applied, "fallback": fallback}
