from app.core.logging import get_logger
from app.pipeline.context import JobContext
from app.pipeline.stages.base import Stage
from app.ppt.deck_rhythm import rebalance_families, rhythm_issues
from app.ppt.layout_guard import guard_regions
from app.ppt.layout_recipes import RECIPE_CATALOG, project_recipe
from app.ppt.recipe_selector import select_recipe
from app.schemas.composition import Box, SlideVisualPlan, TemplateSpaceContract

logger = get_logger(__name__)

_STRUCTURAL = {"cover", "toc", "section", "summary", "ending"}


def _default_contract() -> TemplateSpaceContract:
    return TemplateSpaceContract(
        page_width=13.333,
        page_height=7.5,
        safe_zone=Box(x=0.9, y=1.5, width=11.533, height=5.45),
    )


class CompositionStage(Stage):
    code = "COMPOSE"
    weight = 4

    def __init__(self, selector=None):
        self.selector = selector or select_recipe

    def run(self, ctx: JobContext) -> dict:
        raw_contract = (ctx.data.get("PARSE_TPL") or {}).get("space_contract")
        try:
            contract = TemplateSpaceContract.model_validate(raw_contract)
        except Exception:
            contract = _default_contract()
        storyboard = {
            raw.get("page"): raw
            for raw in (ctx.data.get("STORYBOARD") or {}).get("slides", [])
            if isinstance(raw, dict)
        }
        pages = ctx.get_pages_content()
        body_plans = []
        composition = {}
        previous_families = []

        for page in (ctx.data.get("PLAN") or {}).get("plan", []):
            if page.get("type") in _STRUCTURAL:
                continue
            page_no = int(page["page"])
            raw_visual = storyboard.get(page_no)
            if raw_visual is None:
                continue
            visual = SlideVisualPlan.model_validate(raw_visual)
            body_plans.append(visual)
            content = pages.get(str(page_no)) or {}
            element_types = [
                element.get("type")
                for element in content.get("elements", [])
                if element.get("type")
            ] or ["bullet_group"]
            accepted = None
            attempted_issues = []
            for requested in (visual.layout_family, None):
                try:
                    selected = self.selector(
                        page=page_no,
                        job_seed=ctx.biz_id,
                        requested_family=requested,
                        element_types=element_types,
                        contract=contract,
                        previous_families=previous_families,
                    )
                    issues = guard_regions(selected.recipe, contract)
                    attempted_issues.extend(issue.__dict__ for issue in issues)
                    if not any(issue.severity == "error" for issue in issues):
                        accepted = selected.recipe
                        break
                except Exception as error:
                    attempted_issues.append(
                        {"code": "recipe_selection_failed", "detail": str(error), "severity": "error"}
                    )
            if accepted is None:
                composition[str(page_no)] = {
                    "page": page_no,
                    "recipe_id": None,
                    "family": "title_content",
                    "visual_plan": visual.model_dump(),
                    "regions": [],
                    "guard_issues": attempted_issues,
                    "fallback": True,
                    "fallback_layout": "title_content",
                }
                continue
            previous_families.append(accepted.family)
            composition[str(page_no)] = self._record(visual, accepted)

        accepted_plans = [plan for plan in body_plans if not composition.get(str(plan.page), {}).get("fallback")]
        candidates_by_page = {}
        for plan in accepted_plans:
            content = pages.get(str(plan.page)) or {}
            element_types = [element.get("type") for element in content.get("elements", []) if element.get("type")]
            candidates_by_page[plan.page] = [
                projected
                for recipe in RECIPE_CATALOG
                if all(element_type in recipe.allowed_elements for element_type in element_types)
                for projected in [project_recipe(recipe, contract)]
                if not guard_regions(projected, contract)
            ]
        balanced = rebalance_families(accepted_plans, candidates_by_page, ctx.biz_id)
        for plan in accepted_plans:
            if plan.page in balanced:
                composition[str(plan.page)] = self._record(plan, balanced[plan.page])

        selected_recipes = {
            int(page): balanced.get(int(page))
            for page, record in composition.items()
            if not record.get("fallback") and balanced.get(int(page)) is not None
        }
        deck_issues = [issue.__dict__ for issue in rhythm_issues(accepted_plans, selected_recipes)]
        return {
            "space_contract": contract.model_dump(),
            "composition_by_page": composition,
            "deck_issues": deck_issues,
            "fallback_pages": [int(page) for page, value in composition.items() if value["fallback"]],
        }

    @staticmethod
    def _record(visual: SlideVisualPlan, recipe) -> dict:
        regions = [region.model_dump() for region in recipe.regions]
        return {
            "page": visual.page,
            "recipe_id": recipe.id,
            "family": recipe.family,
            "visual_plan": {**visual.model_dump(), "regions": regions},
            "regions": regions,
            "guard_issues": [],
            "fallback": False,
            "fallback_layout": None,
        }
