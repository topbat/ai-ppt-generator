from app.ppt.layout_guard import boxes_overlap, check_box, check_page_box, check_typography
from app.schemas.composition import Box, Insets, ProtectedZone, TemplateSpaceContract


def test_guard_reports_each_violated_edge_margin():
    parent = Box(
        x=0,
        y=0,
        width=5,
        height=4,
        padding=Insets(top=0.2, right=0.3, bottom=0.4, left=0.5),
    )
    child = Box(x=0.2, y=0.1, width=4.4, height=3.7)

    issues = check_box(child, parent)

    assert {issue.code for issue in issues} == {"margin_top", "margin_left", "margin_bottom"}


def test_typography_rejects_body_below_sixteen_points():
    issues = check_typography(role="body", size_pt=15, levels_on_page=3)

    assert [issue.code for issue in issues] == ["font_too_small"]


def test_touching_boxes_do_not_overlap():
    assert not boxes_overlap(
        Box(x=0, y=0, width=1, height=1),
        Box(x=1, y=0, width=1, height=1),
    )


def test_page_guard_reports_protected_zone_collision():
    contract = TemplateSpaceContract(
        page_width=13.33,
        page_height=7.5,
        safe_zone=Box(x=0.7, y=1.2, width=11.9, height=5.7),
        protected_zones=[ProtectedZone(role="logo", box=Box(x=11.7, y=1.25, width=0.7, height=0.4))],
    )

    issues = check_page_box(Box(x=11.6, y=1.2, width=0.6, height=0.6), contract)

    assert {issue.code for issue in issues} == {"protected_zone_collision"}
