from app.ppt.layout_guard import guard_regions
from app.ppt.layout_recipes import RECIPE_CATALOG, project_recipe
from app.ppt.recipe_selector import select_recipe
from app.schemas.composition import Box, TemplateSpaceContract


def _contract():
    return TemplateSpaceContract(
        page_width=13.33,
        page_height=7.5,
        safe_zone=Box(x=0.7, y=1.25, width=11.93, height=5.7),
    )


def test_every_catalog_recipe_projects_inside_safe_zone():
    contract = _contract()

    assert len(RECIPE_CATALOG) >= 12
    assert {recipe.family for recipe in RECIPE_CATALOG} == {
        "single_focus",
        "split",
        "cards_grid",
        "flow",
        "structure",
        "data_focus",
        "editorial",
    }
    for recipe in RECIPE_CATALOG:
        assert guard_regions(project_recipe(recipe, contract), contract) == []


def test_selector_rejects_recipes_incompatible_with_all_elements():
    selection = select_recipe(
        page=4,
        job_seed="ppt_abc",
        requested_family="flow",
        element_types=["table"],
        contract=_contract(),
        previous_families=[],
    )

    assert selection.recipe.family != "flow"
    assert "table" in selection.recipe.allowed_elements


def test_selector_honors_requested_family_when_it_fits():
    selection = select_recipe(
        page=7,
        job_seed="ppt_abc",
        requested_family="editorial",
        element_types=["bullet_group", "key_number"],
        contract=_contract(),
        previous_families=["cards_grid"],
    )

    assert selection.recipe.family == "editorial"


def test_selector_prefers_a_family_not_used_on_previous_slide():
    selection = select_recipe(
        page=5,
        job_seed="ppt_repeat",
        requested_family=None,
        element_types=["bullet_group"],
        contract=_contract(),
        previous_families=["cards_grid"],
    )

    assert selection.recipe.family != "cards_grid"


def test_recipe_variant_is_deterministic_for_page_and_job():
    kwargs = dict(
        page=6,
        job_seed="ppt_stable",
        requested_family="split",
        element_types=["bullet_group"],
        contract=_contract(),
        previous_families=["editorial"],
    )

    first = select_recipe(**kwargs)
    second = select_recipe(**kwargs)

    assert (first.recipe.id, first.recipe.mirrored) == (
        second.recipe.id,
        second.recipe.mirrored,
    )
