from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.composition import Box


PrimitiveType = Literal["text", "shape", "chart", "table", "connector"]
StyleToken = Literal["primary", "secondary", "accent", "text", "muted", "surface"]
FontToken = Literal["font_title", "font_body"]


class ScenePrimitive(BaseModel):
    id: str
    type: PrimitiveType
    content_id: str
    box: Box
    z_index: int = Field(default=0, ge=0, le=100)
    text: str | None = None
    style_token: StyleToken = "text"
    font_token: FontToken = "font_body"
    font_role: Literal["page_title", "conclusion", "body", "chart_label", "source"] = "body"


class SceneSpec(BaseModel):
    page: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)
    primitives: list[ScenePrimitive] = Field(min_length=1, max_length=40)
