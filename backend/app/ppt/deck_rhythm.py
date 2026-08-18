import hashlib
import math
from collections import Counter

from app.ppt.layout_guard import GuardIssue
from app.schemas.composition import LayoutRecipe, SlideVisualPlan


def _stable_int(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)


def layout_fingerprint(plan: SlideVisualPlan, recipe: LayoutRecipe) -> str:
    raw = ":".join(
        [
            recipe.family,
            recipe.id,
            str(len(recipe.regions)),
            str(recipe.mirrored),
            plan.focal_position,
            plan.background,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def rhythm_issues(
    plans: list[SlideVisualPlan],
    recipes: dict[int, LayoutRecipe],
) -> list[GuardIssue]:
    ordered = sorted(plans, key=lambda plan: plan.page)
    issues = []
    fingerprints = []
    for plan in ordered:
        recipe = recipes.get(plan.page)
        if recipe is not None:
            fingerprints.append((plan.page, layout_fingerprint(plan, recipe)))
    for (left_page, left), (right_page, right) in zip(fingerprints, fingerprints[1:]):
        if left == right:
            issues.append(
                GuardIssue(
                    "adjacent_fingerprint_duplicate",
                    f"pages {left_page} and {right_page} share fingerprint {left}",
                )
            )

    families = [recipes[plan.page].family for plan in ordered if plan.page in recipes]
    if len(families) >= 4:
        family, count = Counter(families).most_common(1)[0]
        ratio = count / len(families)
        if ratio > 0.30 + 1e-9:
            issues.append(
                GuardIssue(
                    "dominant_family_ratio",
                    f"family {family} occupies {ratio:.1%} of body slides",
                )
            )

    for start in range(max(0, len(ordered) - 2)):
        window = ordered[start:start + 3]
        if len({plan.focal_position for plan in window}) == 1:
            issues.append(
                GuardIssue(
                    "focal_position_streak",
                    f"pages {window[0].page}-{window[-1].page} keep {window[0].focal_position}",
                )
            )
    return issues


def rebalance_families(
    plans: list[SlideVisualPlan],
    candidates_by_page: dict[int, list[LayoutRecipe]],
    job_seed: str,
) -> dict[int, LayoutRecipe]:
    ordered = sorted(plans, key=lambda plan: plan.page)
    cap = max(1, math.floor(len(ordered) * 0.30))
    family_counts: Counter = Counter()
    selected = {}
    previous_family = None

    for plan in ordered:
        candidates = candidates_by_page.get(plan.page) or []
        if not candidates:
            continue
        ranked = sorted(
            candidates,
            key=lambda recipe: (
                family_counts[recipe.family],
                recipe.family == previous_family,
                recipe.family != plan.layout_family,
                _stable_int(f"{job_seed}:{plan.page}:{recipe.id}"),
            ),
        )
        choice = next(
            (recipe for recipe in ranked if family_counts[recipe.family] < cap),
            ranked[0],
        )
        selected[plan.page] = choice
        family_counts[choice.family] += 1
        previous_family = choice.family
    return selected


def _key_slide_score(plan: SlideVisualPlan) -> int:
    business_importance = {"primary": 35, "secondary": 18, "supporting": 5}[plan.importance]
    structural_complexity = 20 if (
        plan.layout_family in {"flow", "structure", "data_focus"}
        or plan.focal_element in {"chart", "table", "architecture", "process", "timeline"}
    ) else 5
    role = plan.narrative_role.lower()
    climax_need = 20 if any(word in role for word in ("climax", "conclusion", "summary", "decision")) else 5
    ordinary_dissatisfaction = 15 if plan.key_slide_candidate else 0
    rhythm_contribution = 10 if plan.focal_position in {"center", "full"} else 5
    return (
        business_importance
        + structural_complexity
        + climax_need
        + ordinary_dissatisfaction
        + rhythm_contribution
    )


def select_key_slides(
    plans: list[SlideVisualPlan],
    chapter_by_page: dict[int, str],
) -> list[int]:
    if not plans:
        return []
    target = min(5, math.ceil(len(plans) * 0.18))
    if len(plans) < 8:
        target = min(target, 1)
    ranked = sorted(
        plans,
        key=lambda plan: (
            -_key_slide_score(plan),
            _stable_int(f"key-slide:{plan.page}:{plan.thesis}"),
        ),
    )
    selected = []
    used_chapters = set()
    for plan in ranked:
        chapter = chapter_by_page.get(plan.page, f"page-{plan.page}")
        if chapter in used_chapters:
            continue
        if any(abs(plan.page - page) <= 1 for page in selected):
            continue
        selected.append(plan.page)
        used_chapters.add(chapter)
        if len(selected) >= target:
            break
    return sorted(selected)
