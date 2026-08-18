from types import SimpleNamespace

from app.pipeline.stages.design_stages import ArtDirectionStage, StoryboardStage
from app.schemas.composition import DeckArtDirection, SlideVisualPlan


class FakeGateway:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def chat_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def _ctx(mode="standard"):
    return SimpleNamespace(
        mode=mode,
        job_pk=17,
        biz_id="ppt_design",
        data={
            "PARSE_TPL": {
                "design_tokens": {
                    "primary": "123456",
                    "secondary": "223344",
                    "accent": "FF8800",
                    "background": "FFFFFF",
                    "font_title": "思源黑体",
                    "font_body": "思源黑体",
                }
            },
            "OUTLINE": {"outline": [{"chapter": "背景"}, {"chapter": "方案"}]},
            "PLAN": {
                "plan": [
                    {"page": 1, "type": "cover", "title": "年度方案"},
                    {"page": 2, "type": "toc", "title": "目录"},
                    {"page": 3, "type": "title_content", "title": "核心挑战"},
                    {"page": 4, "type": "bar_chart", "title": "增长结果"},
                ]
            },
        },
    )


def test_standard_mode_parses_valid_art_direction_and_storyboard():
    gateway = FakeGateway([
        {
            "concept": "稳健增长",
            "visual_motif": "上升轨迹",
            "composition": "企业网格中的不对称焦点",
            "palette": ["123456", "FF8800", "FFFFFF"],
            "font_title": "思源黑体",
            "font_body": "思源黑体",
            "reading_mode": "balanced",
            "rhythm": ["quiet", "focus", "data"],
        },
        {
            "slides": [
                {
                    "page": 3,
                    "narrative_role": "problem",
                    "importance": "primary",
                    "thesis": "核心挑战来自协同成本",
                    "layout_family": "editorial",
                    "focal_element": "bullet_group",
                    "focal_position": "left",
                    "max_points": 4,
                    "max_chars": 150,
                    "key_slide_candidate": True,
                }
            ]
        },
    ])
    ctx = _ctx()

    art = ArtDirectionStage(gateway).run(ctx)
    ctx.data["ART_DIRECTION"] = art
    storyboard = StoryboardStage(gateway).run(ctx)

    assert DeckArtDirection.model_validate(art["art_direction"]).concept == "稳健增长"
    assert len(storyboard["slides"]) == 4
    assert SlideVisualPlan.model_validate(storyboard["slides"][2]).thesis == "核心挑战来自协同成本"


def test_malformed_art_direction_soft_falls_back_to_template_tokens():
    result = ArtDirectionStage(FakeGateway([{"unexpected": True}])).run(_ctx())

    direction = DeckArtDirection.model_validate(result["art_direction"])
    assert result["degraded"] is True
    assert direction.font_title == "思源黑体"
    assert direction.palette[0] == "123456"


def test_storyboard_completes_pages_missing_from_model_output():
    gateway = FakeGateway([{"slides": []}])
    ctx = _ctx()
    ctx.data["ART_DIRECTION"] = ArtDirectionStage(FakeGateway([{"bad": True}])).run(ctx)

    result = StoryboardStage(gateway).run(ctx)

    assert [slide["page"] for slide in result["slides"]] == [1, 2, 3, 4]
    assert result["completed_pages"] == [1, 2, 3, 4]


def test_fast_mode_uses_defaults_without_calling_gateway():
    gateway = FakeGateway()
    ctx = _ctx(mode="fast")

    art = ArtDirectionStage(gateway).run(ctx)
    ctx.data["ART_DIRECTION"] = art
    storyboard = StoryboardStage(gateway).run(ctx)

    assert gateway.calls == []
    assert art["source"] == "default"
    assert len(storyboard["slides"]) == 4


def test_every_storyboard_page_has_hierarchy_focal_point_and_capacity():
    ctx = _ctx(mode="fast")
    ctx.data["ART_DIRECTION"] = ArtDirectionStage(FakeGateway()).run(ctx)

    result = StoryboardStage(FakeGateway()).run(ctx)

    for raw in result["slides"]:
        plan = SlideVisualPlan.model_validate(raw)
        assert plan.thesis
        assert plan.importance in {"primary", "secondary", "supporting"}
        assert plan.focal_position in {"left", "center", "right", "full"}
        assert plan.max_points >= 1
        assert plan.max_chars >= 40
