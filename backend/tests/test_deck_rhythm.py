from collections import Counter

from app.ppt.deck_rhythm import (
    rebalance_families,
    rhythm_issues,
    select_key_slides,
)
from app.ppt.layout_recipes import RECIPE_CATALOG
from app.schemas.composition import SlideVisualPlan


def _plans(count, family="editorial", focal="left"):
    return [
        SlideVisualPlan(
            page=page,
            narrative_role="evidence",
            importance="primary" if page % 3 == 0 else "secondary",
            thesis=f"第{page}页结论",
            layout_family=family,
            focal_element="bullet_group",
            focal_position=focal,
            key_slide_candidate=page % 2 == 0,
        )
        for page in range(1, count + 1)
    ]


def _recipe(family):
    return next(recipe for recipe in RECIPE_CATALOG if recipe.family == family)


def test_adjacent_layout_fingerprints_may_not_match():
    plans = _plans(2)
    recipes = {1: _recipe("editorial"), 2: _recipe("editorial")}

    issues = rhythm_issues(plans, recipes)

    assert "adjacent_fingerprint_duplicate" in {issue.code for issue in issues}


def test_dominant_family_over_thirty_percent_is_reported():
    plans = _plans(10)
    recipes = {
        page: _recipe("editorial" if page <= 4 else ["split", "flow", "structure"][page % 3])
        for page in range(1, 11)
    }

    issues = rhythm_issues(plans, recipes)

    assert "dominant_family_ratio" in {issue.code for issue in issues}


def test_three_consecutive_slides_may_not_keep_same_focal_position():
    plans = _plans(3, focal="center")
    recipes = {page: _recipe(family) for page, family in enumerate(
        ["editorial", "split", "single_focus"], start=1
    )}

    issues = rhythm_issues(plans, recipes)

    assert "focal_position_streak" in {issue.code for issue in issues}


def test_rebalancer_caps_a_family_at_thirty_percent_when_alternatives_exist():
    plans = _plans(10)
    families = ["single_focus", "split", "cards_grid", "flow", "structure", "data_focus", "editorial"]
    candidates = {plan.page: [_recipe(family) for family in families] for plan in plans}

    selected = rebalance_families(plans, candidates, "ppt_rhythm")
    counts = Counter(recipe.family for recipe in selected.values())

    assert max(counts.values()) / len(plans) <= 0.30


def test_key_slide_count_is_eighteen_percent_capped_at_five():
    selected = select_key_slides(_plans(20), {page: f"chapter-{page // 4}" for page in range(1, 21)})

    assert len(selected) == 4


def test_short_deck_selects_at_most_one_key_slide():
    selected = select_key_slides(_plans(7), {page: f"chapter-{page}" for page in range(1, 8)})

    assert len(selected) <= 1


def test_key_slides_are_non_adjacent_and_one_per_chapter():
    chapters = {page: f"chapter-{(page - 1) // 4}" for page in range(1, 21)}

    selected = select_key_slides(_plans(20), chapters)

    assert all(right - left > 1 for left, right in zip(selected, selected[1:]))
    assert len({chapters[page] for page in selected}) == len(selected)
