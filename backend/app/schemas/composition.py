from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Insets(BaseModel):
    top: float = Field(default=0.0, ge=0)
    right: float = Field(default=0.0, ge=0)
    bottom: float = Field(default=0.0, ge=0)
    left: float = Field(default=0.0, ge=0)


class Box(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    padding: Insets = Field(default_factory=Insets)

    @model_validator(mode="after")
    def validate_content_area(self):
        if self.padding.left + self.padding.right >= self.width:
            raise ValueError("horizontal padding consumes container")
        if self.padding.top + self.padding.bottom >= self.height:
            raise ValueError("vertical padding consumes container")
        return self

    def content_rect(self) -> tuple[float, float, float, float]:
        p = self.padding
        return (
            self.x + p.left,
            self.y + p.top,
            self.width - p.left - p.right,
            self.height - p.top - p.bottom,
        )


class ProtectedZone(BaseModel):
    role: str
    box: Box


class TemplateSpaceContract(BaseModel):
    page_width: float = Field(gt=0)
    page_height: float = Field(gt=0)
    safe_zone: Box
    protected_zones: list[ProtectedZone] = Field(default_factory=list)
    grid_columns: int = Field(default=12, ge=1, le=24)
    gutter: float = Field(default=0.24, ge=0)

    @model_validator(mode="after")
    def validate_page_bounds(self):
        boxes = [self.safe_zone] + [zone.box for zone in self.protected_zones]
        for box in boxes:
            if box.x + box.width > self.page_width + 1e-6:
                raise ValueError("box exceeds page width")
            if box.y + box.height > self.page_height + 1e-6:
                raise ValueError("box exceeds page height")
        return self


Importance = Literal["primary", "secondary", "supporting"]


class LayoutRegion(BaseModel):
    id: str
    box: Box
    role: str
    importance: Importance = "secondary"


class LayoutRecipe(BaseModel):
    id: str
    family: str
    allowed_elements: list[str]
    regions: list[LayoutRegion]
    mirrored: bool = False
    background: Literal["inherit", "light", "dark"] = "inherit"


class DeckArtDirection(BaseModel):
    concept: str
    visual_motif: str
    composition: str
    palette: list[str]
    font_title: str
    font_body: str
    reading_mode: Literal["text", "balanced", "presentation"] = "balanced"
    rhythm: list[str] = Field(default_factory=list)


class SlideVisualPlan(BaseModel):
    page: int = Field(ge=1)
    narrative_role: str
    importance: Importance
    thesis: str
    layout_family: str
    focal_element: str
    focal_position: Literal["left", "center", "right", "full"]
    background: Literal["inherit", "light", "dark"] = "inherit"
    max_points: int = Field(default=5, ge=1, le=8)
    max_chars: int = Field(default=180, ge=40, le=320)
    key_slide_candidate: bool = False
