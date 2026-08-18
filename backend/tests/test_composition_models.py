import pytest
from pydantic import ValidationError

from app.schemas.composition import Box, Insets, TemplateSpaceContract


def test_box_content_rect_subtracts_all_four_margins():
    box = Box(
        x=1.0,
        y=2.0,
        width=6.0,
        height=3.0,
        padding=Insets(top=0.2, right=0.3, bottom=0.4, left=0.5),
    )

    assert box.content_rect() == pytest.approx((1.5, 2.2, 5.2, 2.4))


def test_box_rejects_padding_that_consumes_container():
    with pytest.raises(ValidationError):
        Box(
            x=0,
            y=0,
            width=1,
            height=1,
            padding=Insets(top=0.6, right=0.6, bottom=0.6, left=0.6),
        )


def test_space_contract_rejects_safe_zone_outside_page():
    with pytest.raises(ValidationError):
        TemplateSpaceContract(
            page_width=13.33,
            page_height=7.5,
            safe_zone=Box(x=12, y=1, width=2, height=3),
        )
