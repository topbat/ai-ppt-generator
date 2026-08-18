from dataclasses import dataclass

from app.ppt.design_tokens import TYPO_ROLES
from app.schemas.composition import Box, LayoutRecipe, TemplateSpaceContract


@dataclass(frozen=True)
class GuardIssue:
    code: str
    detail: str
    severity: str = "error"


def boxes_overlap(a: Box, b: Box, tolerance: float = 0.01) -> bool:
    return not (
        a.x + a.width <= b.x + tolerance
        or b.x + b.width <= a.x + tolerance
        or a.y + a.height <= b.y + tolerance
        or b.y + b.height <= a.y + tolerance
    )


def check_box(child: Box, parent: Box, tolerance: float = 0.01) -> list[GuardIssue]:
    left, top, width, height = parent.content_rect()
    right = left + width
    bottom = top + height
    child_right = child.x + child.width
    child_bottom = child.y + child.height
    issues = []
    if child.y < top - tolerance:
        issues.append(GuardIssue("margin_top", f"top {child.y:.3f} < {top:.3f}"))
    if child_right > right + tolerance:
        issues.append(GuardIssue("margin_right", f"right {child_right:.3f} > {right:.3f}"))
    if child_bottom > bottom + tolerance:
        issues.append(GuardIssue("margin_bottom", f"bottom {child_bottom:.3f} > {bottom:.3f}"))
    if child.x < left - tolerance:
        issues.append(GuardIssue("margin_left", f"left {child.x:.3f} < {left:.3f}"))
    return issues


def check_page_box(box: Box, contract: TemplateSpaceContract) -> list[GuardIssue]:
    page = Box(x=0, y=0, width=contract.page_width, height=contract.page_height)
    issues = check_box(box, page)
    issues.extend(check_box(box, contract.safe_zone))
    for zone in contract.protected_zones:
        if boxes_overlap(box, zone.box):
            issues.append(
                GuardIssue(
                    "protected_zone_collision",
                    f"box overlaps protected {zone.role} zone",
                )
            )
    return issues


def check_typography(
    role: str,
    size_pt: float,
    levels_on_page: int,
    emphasis_count: int = 0,
) -> list[GuardIssue]:
    issues = []
    minimum, maximum = TYPO_ROLES.get(role, TYPO_ROLES["body"])
    if size_pt < minimum:
        issues.append(
            GuardIssue("font_too_small", f"{role} {size_pt:g}pt < {minimum}pt")
        )
    if size_pt > maximum:
        issues.append(
            GuardIssue(
                "font_too_large",
                f"{role} {size_pt:g}pt > {maximum}pt",
                severity="warning",
            )
        )
    if levels_on_page > 4:
        issues.append(
            GuardIssue("too_many_type_levels", f"{levels_on_page} typography levels > 4")
        )
    if emphasis_count > 3:
        issues.append(
            GuardIssue("too_many_emphases", f"{emphasis_count} emphasis styles > 3")
        )
    return issues


def guard_regions(recipe: LayoutRecipe, contract: TemplateSpaceContract) -> list[GuardIssue]:
    issues = []
    for region in recipe.regions:
        for issue in check_page_box(region.box, contract):
            issues.append(
                GuardIssue(
                    issue.code,
                    f"region {region.id}: {issue.detail}",
                    issue.severity,
                )
            )
    return issues
