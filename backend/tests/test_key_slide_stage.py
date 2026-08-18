import json
from types import SimpleNamespace

from app.pipeline.stages.key_slide_stage import KeySlideDesignStage, freeze_slide_content
from app.schemas.presentation import PresentationSpec, SlideSpec


class FakeStorage:
    def __init__(self):
        self.saved = {}

    def put_json(self, key, value):
        self.saved[key] = value


class SceneGateway:
    def __init__(self, valid):
        self.valid = valid
        self.calls = 0

    def chat_json(self, *args, **kwargs):
        self.calls += 1
        if not self.valid:
            return {"invalid": True}
        payload = json.loads(args[3])
        content_id, value = next(
            (key, value)
            for key, value in payload["locked_content"].items()
            if isinstance(value, str) and value
        )
        return {
            "page": payload["page"],
            "content_hash": payload["content_hash"],
            "primitives": [
                {
                    "id": "hero_text",
                    "type": "text",
                    "content_id": content_id,
                    "text": value,
                    "box": {"x": 1.1, "y": 2.0, "width": 5.0, "height": 1.2},
                    "style_token": "primary",
                    "font_token": "font_body",
                }
            ],
        }


def _ctx():
    slide = SlideSpec(
        page=3,
        chapter_id="ch1",
        type="title_content",
        title="核心结论",
        elements=[{"type": "bullet_group", "items": ["已覆盖23个系统", "协同效率提升"]}],
        layout_recipe="editorial_aside",
        visual_plan={"layout_family": "editorial", "regions": []},
    )
    spec = PresentationSpec(title="方案", total_pages=1, mode="premium", slides=[slide])
    storage = FakeStorage()
    return SimpleNamespace(
        job_pk=8,
        biz_id="ppt_key",
        storage=storage,
        _cache={"presentation_spec": spec},
        data={
            "LAYOUT": {"pjson_key": "jobs/ppt_key/presentation.json"},
            "PARSE_TPL": {
                "space_contract": {
                    "page_width": 13.33,
                    "page_height": 7.5,
                    "safe_zone": {"x": 0.7, "y": 1.4, "width": 11.93, "height": 5.5},
                }
            },
            "PLAN": {"plan": [{"page": 3, "chapter_idx": 1, "type": "title_content"}]},
            "STORYBOARD": {
                "slides": [
                    {
                        "page": 3,
                        "narrative_role": "conclusion",
                        "importance": "primary",
                        "thesis": "核心结论",
                        "layout_family": "editorial",
                        "focal_element": "bullet_group",
                        "focal_position": "center",
                        "key_slide_candidate": True,
                    }
                ]
            },
            "COMPOSE": {"composition_by_page": {"3": {"family": "editorial"}}},
        },
    )


def test_freeze_slide_content_creates_stable_locked_ids():
    ctx = _ctx()

    first = freeze_slide_content(ctx._cache["presentation_spec"].slides[0])
    second = freeze_slide_content(ctx._cache["presentation_spec"].slides[0])

    assert first == second
    assert "bullet:0" in first and first["bullet:0"] == "已覆盖23个系统"


def test_valid_scene_is_applied_and_persisted():
    ctx = _ctx()
    result = KeySlideDesignStage(SceneGateway(valid=True)).run(ctx)

    assert result["selected"] == [3]
    assert result["applied"] == [3]
    assert result["fallback"] == []
    assert ctx._cache["presentation_spec"].slides[0].visual_plan["scene_spec"]
    assert ctx.storage.saved[ctx.data["LAYOUT"]["pjson_key"]]


def test_two_invalid_scene_attempts_preserve_ordinary_composition():
    ctx = _ctx()
    before = ctx._cache["presentation_spec"].model_dump()
    gateway = SceneGateway(valid=False)

    result = KeySlideDesignStage(gateway).run(ctx)

    assert gateway.calls == 2
    assert result["selected"] == [3]
    assert result["applied"] == []
    assert result["fallback"] == [3]
    assert ctx._cache["presentation_spec"].model_dump() == before
