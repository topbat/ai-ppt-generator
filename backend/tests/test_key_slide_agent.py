import pytest
from pydantic import ValidationError

from app.ai.agents.key_slide_agent import (
    canonical_content_hash,
    validate_scene,
)
from app.schemas.composition import Box, TemplateSpaceContract
from app.schemas.scene import ScenePrimitive, SceneSpec


def _contract():
    return TemplateSpaceContract(
        page_width=13.33,
        page_height=7.5,
        safe_zone=Box(x=0.7, y=1.4, width=11.93, height=5.5),
    )


def test_scene_primitives_are_restricted_to_approved_types():
    with pytest.raises(ValidationError):
        ScenePrimitive(
            id="p1",
            type="image",
            content_id="bullet:0",
            box=Box(x=1, y=2, width=3, height=2),
        )


def test_scene_rejects_unknown_locked_content_reference():
    locked = {"bullet:0": "核心事实"}
    scene = SceneSpec(
        page=3,
        content_hash=canonical_content_hash(locked),
        primitives=[
            ScenePrimitive(
                id="p1",
                type="text",
                content_id="bullet:9",
                text="核心事实",
                box=Box(x=1, y=2, width=3, height=1),
            )
        ],
    )

    with pytest.raises(ValueError, match="unknown content id"):
        validate_scene(scene, locked, _contract())


def test_scene_text_must_equal_frozen_content_value():
    locked = {"bullet:0": "核心事实"}
    scene = SceneSpec(
        page=3,
        content_hash=canonical_content_hash(locked),
        primitives=[
            ScenePrimitive(
                id="p1",
                type="text",
                content_id="bullet:0",
                text="被改写的事实",
                box=Box(x=1, y=2, width=3, height=1),
            )
        ],
    )

    with pytest.raises(ValueError, match="frozen text"):
        validate_scene(scene, locked, _contract())


def test_scene_rejects_invalid_content_hash():
    scene = SceneSpec(page=3, content_hash="0" * 64, primitives=[])

    with pytest.raises(ValueError, match="content hash"):
        validate_scene(scene, {"bullet:0": "核心事实"}, _contract())


def test_valid_scene_keeps_content_inside_safe_zone():
    locked = {"bullet:0": "核心事实"}
    scene = SceneSpec(
        page=3,
        content_hash=canonical_content_hash(locked),
        primitives=[
            ScenePrimitive(
                id="p1",
                type="text",
                content_id="bullet:0",
                text="核心事实",
                box=Box(x=1.0, y=2.0, width=4.0, height=1.0),
                style_token="primary",
                font_token="font_body",
            )
        ],
    )

    assert validate_scene(scene, locked, _contract()) == scene
