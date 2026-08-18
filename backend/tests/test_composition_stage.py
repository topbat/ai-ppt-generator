from types import SimpleNamespace

from app.ppt.recipe_selector import RecipeSelection, select_recipe
from app.pipeline.stages.composition_stage import CompositionStage
from app.schemas.composition import Box, LayoutRecipe, LayoutRegion


class FakeContext(SimpleNamespace):
    def get_pages_content(self):
        return self.pages


def _ctx():
    return FakeContext(
        biz_id="ppt_compose",
        data={
            "PARSE_TPL": {
                "space_contract": {
                    "page_width": 13.33,
                    "page_height": 7.5,
                    "safe_zone": {"x": 0.7, "y": 1.3, "width": 11.93, "height": 5.6},
                }
            },
            "PLAN": {
                "plan": [
                    {"page": 1, "type": "cover", "title": "封面"},
                    {"page": 2, "type": "title_content", "title": "关键判断"},
                ]
            },
            "STORYBOARD": {
                "slides": [
                    {
                        "page": 1,
                        "narrative_role": "opening",
                        "importance": "primary",
                        "thesis": "封面",
                        "layout_family": "single_focus",
                        "focal_element": "bullet_group",
                        "focal_position": "full",
                    },
                    {
                        "page": 2,
                        "narrative_role": "evidence",
                        "importance": "primary",
                        "thesis": "关键判断",
                        "layout_family": "editorial",
                        "focal_element": "bullet_group",
                        "focal_position": "left",
                    },
                ]
            },
            "MATCH": {"matches": {"1": 1, "2": 2}},
        },
        pages={
            "1": {"page": 1, "type": "cover", "title": "封面", "elements": []},
            "2": {
                "page": 2,
                "type": "title_content",
                "title": "关键判断",
                "elements": [{"type": "bullet_group", "items": ["观点一", "观点二"]}],
            },
        },
    )


def _invalid_selection():
    recipe = LayoutRecipe(
        id="invalid",
        family="editorial",
        allowed_elements=["bullet_group"],
        regions=[
            LayoutRegion(
                id="outside",
                role="primary",
                importance="primary",
                box=Box(x=12.8, y=1.3, width=1.0, height=2.0),
            )
        ],
    )
    return RecipeSelection(recipe=recipe, score=100, score_breakdown={})


def test_composition_projects_recipe_and_records_zero_guard_violations():
    result = CompositionStage().run(_ctx())

    body = result["composition_by_page"]["2"]
    assert body["recipe_id"]
    assert body["visual_plan"]["layout_family"] == "editorial"
    assert body["guard_issues"] == []
    assert body["fallback"] is False
    assert "1" not in result["composition_by_page"]


def test_composition_reselects_when_first_recipe_fails_guard():
    calls = []

    def selector(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _invalid_selection()
        return select_recipe(**kwargs)

    result = CompositionStage(selector=selector).run(_ctx())

    assert len(calls) == 2
    assert result["composition_by_page"]["2"]["fallback"] is False
    assert result["composition_by_page"]["2"]["recipe_id"] != "invalid"


def test_composition_falls_back_to_title_content_when_all_recipes_fail():
    result = CompositionStage(selector=lambda **_: _invalid_selection()).run(_ctx())

    body = result["composition_by_page"]["2"]
    assert body["fallback"] is True
    assert body["recipe_id"] is None
    assert body["fallback_layout"] == "title_content"
