import hashlib
from dataclasses import dataclass

from app.ppt.layout_guard import guard_regions
from app.ppt.layout_recipes import RECIPE_CATALOG, project_recipe
from app.schemas.composition import LayoutRecipe, TemplateSpaceContract


@dataclass(frozen=True)
class RecipeSelection:
    recipe: LayoutRecipe
    score: int
    score_breakdown: dict[str, int]


def _compatible(recipe: LayoutRecipe, element_types: list[str]) -> bool:
    return all(element_type in recipe.allowed_elements for element_type in element_types)


def _tie_break(job_seed: str, page: int, recipe_id: str) -> int:
    digest = hashlib.sha256(f"{job_seed}:{page}:{recipe_id}".encode("utf-8")).hexdigest()
    return int(digest, 16)


def select_recipe(
    page: int,
    job_seed: str,
    requested_family: str | None,
    element_types: list[str],
    contract: TemplateSpaceContract,
    previous_families: list[str],
) -> RecipeSelection:
    candidates = []
    recent = set(previous_families[-2:])
    for normalized in RECIPE_CATALOG:
        if not _compatible(normalized, element_types):
            continue
        recipe = project_recipe(normalized, contract)
        issues = guard_regions(recipe, contract)
        if any(issue.severity == "error" for issue in issues):
            continue
        breakdown = {
            "content_compatibility": 40,
            "recent_family_diversity": 25 if recipe.family not in recent else 0,
            "contract_fit": 20,
            "rhythm_contribution": 15 if requested_family == recipe.family else 8,
        }
        score = sum(breakdown.values())
        candidates.append((score, _tie_break(job_seed, page, recipe.id), recipe, breakdown))

    if not candidates:
        raise ValueError(f"no compatible layout recipe for elements: {element_types}")
    _, _, recipe, breakdown = max(candidates, key=lambda item: (item[0], item[1]))
    return RecipeSelection(recipe=recipe, score=sum(breakdown.values()), score_breakdown=breakdown)
