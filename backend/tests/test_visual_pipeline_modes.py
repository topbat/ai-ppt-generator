from app.pipeline.modes.pipelines import PIPELINES


def _codes(mode):
    return [stage.code for group in PIPELINES[mode] for stage in group]


def test_fast_mode_keeps_existing_stage_sequence():
    codes = _codes("fast")

    assert "ART_DIRECTION" not in codes
    assert "STORYBOARD" not in codes
    assert "COMPOSE" not in codes
    assert "KEY_SLIDE_DESIGN" not in codes
    assert codes.index("CONTENT") + 1 == codes.index("MATCH")


def test_standard_mode_adds_visual_direction_storyboard_and_composition():
    codes = _codes("standard")

    assert codes.index("ART_DIRECTION") > codes.index("PLAN")
    assert codes.index("STORYBOARD") < codes.index("CONTENT")
    assert codes.index("COMPOSE") > codes.index("MATCH")
    assert codes.index("COMPOSE") < codes.index("LAYOUT")
    assert "KEY_SLIDE_DESIGN" not in codes


def test_premium_mode_places_key_slide_design_after_layout_before_render():
    codes = _codes("premium")

    assert codes.index("ART_DIRECTION") > codes.index("PLAN")
    assert codes.index("STORYBOARD") < codes.index("CONTENT")
    assert codes.index("COMPOSE") < codes.index("LAYOUT")
    assert codes.index("LAYOUT") < codes.index("KEY_SLIDE_DESIGN") < codes.index("RENDER")


def test_premium_pipeline_uses_real_non_resumable_key_slide_stage():
    stage = next(
        stage
        for group in PIPELINES["premium"]
        for stage in group
        if stage.code == "KEY_SLIDE_DESIGN"
    )

    assert stage.__class__.__name__ == "KeySlideDesignStage"
    assert stage.resumable is False
