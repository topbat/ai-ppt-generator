import pytest

from app.pipeline.guards.capacity_guard import extract_numbers, fit_page_capacity
from app.schemas.presentation import SlideSpec


def test_capacity_keeps_primary_items_and_moves_supporting_details_to_notes():
    result = fit_page_capacity(
        content={
            "title": "结论",
            "elements": [
                {
                    "type": "bullet_group",
                    "items": ["核心事实23个系统", "次要解释一", "次要解释二", "次要解释三"],
                }
            ],
        },
        max_points=2,
        max_chars=80,
        source_numbers={"23"},
    )

    assert result.visible["elements"][0]["items"] == ["核心事实23个系统", "次要解释一"]
    assert result.notes["details"] == ["次要解释二", "次要解释三"]
    assert result.notes["moved_count"] == 2
    assert result.fact_numbers == {"23"}


def test_capacity_uses_character_budget_after_point_budget():
    result = fit_page_capacity(
        content={
            "title": "判断",
            "elements": [
                {"type": "bullet_group", "items": ["第一条核心观点", "第二条补充说明", "第三条支持材料"]}
            ],
        },
        max_points=3,
        max_chars=12,
        source_numbers=set(),
    )

    assert result.visible["elements"][0]["items"] == ["第一条核心观点"]
    assert result.notes["details"] == ["第二条补充说明", "第三条支持材料"]


def test_changed_verified_number_is_rejected():
    with pytest.raises(ValueError, match="verified numbers"):
        fit_page_capacity(
            content={"title": "结果", "elements": [{"type": "paragraph", "text": "已覆盖24个系统"}]},
            max_points=3,
            max_chars=80,
            source_numbers={"23"},
        )


def test_missing_proprietary_name_is_rejected():
    with pytest.raises(ValueError, match="protected names"):
        fit_page_capacity(
            content={"title": "方案", "elements": [{"type": "paragraph", "text": "统一平台"}]},
            max_points=3,
            max_chars=80,
            source_numbers=set(),
            source_names={"星云中台"},
        )


def test_number_extraction_handles_percentages_and_decimals():
    assert extract_numbers({"text": "增长12.5%，覆盖23个系统"}) == {"12.5", "23"}


def test_slide_spec_accepts_composition_metadata_backwards_compatibly():
    old = SlideSpec(page=1, type="title_content", title="旧数据")
    upgraded = SlideSpec(
        page=2,
        type="title_content",
        title="新数据",
        visual_plan={"layout_family": "editorial"},
        layout_recipe="editorial_aside",
        speaker_notes={"details": ["补充材料"]},
    )

    assert old.visual_plan is None
    assert upgraded.speaker_notes["details"] == ["补充材料"]
