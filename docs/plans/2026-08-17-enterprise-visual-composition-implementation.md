# Enterprise Visual Composition Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the main PPT generation pipeline so enterprise templates keep their brand shell while standard and premium modes gain deck-level art direction, storyboard-driven composition, strict four-edge container checks, typography guards, and deterministic repetition control; premium mode additionally redesigns a small set of key slides through a constrained scene agent with guaranteed fallback.

**Architecture:** Add a typed composition layer between page planning and rendering. Template parsing emits a spatial contract; standard/premium modes create deck art direction and per-slide storyboards, then a recipe selector composes content inside the safe zone and validates it before rendering. Premium mode may replace at most 18% (five maximum) of body slides with a constrained SceneSpec, but facts and ordinary-layout fallbacks remain authoritative.

**Tech Stack:** Python 3.11+, FastAPI, Celery, Pydantic 2, python-pptx, Pillow text metrics, existing Qwen/DeepSeek `LLMGateway`, pytest/project smoke scripts.

**Required skills during execution:** `@test-driven-development`, `@systematic-debugging` for unexpected failures, `@verification-before-completion`, and `@requesting-code-review` before integration.

---

## Delivery order

The tasks are intentionally ordered so deterministic safety exists before any LLM/agent behavior is enabled:

1. typed composition primitives;
2. template spatial contract;
3. geometry and typography guards;
4. layout recipe catalog and selector;
5. deck rhythm and key-slide selection;
6. art direction and storyboard stages;
7. content capacity and speaker notes;
8. composition integration;
9. mode-specific pipeline wiring;
10. constrained premium key-slide agent;
11. QA/report integration;
12. regression, documentation, and final verification.

### Task 1: Add typed composition primitives

**Files:**
- Create: `backend/app/schemas/composition.py`
- Create: `backend/tests/test_composition_models.py`

**Step 1: Write the failing Box Model tests**

Create `backend/tests/test_composition_models.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.composition import Box, Insets, TemplateSpaceContract


def test_box_content_rect_subtracts_all_four_margins():
    box = Box(x=1.0, y=2.0, width=6.0, height=3.0,
              padding=Insets(top=.2, right=.3, bottom=.4, left=.5))
    assert box.content_rect() == pytest.approx((1.5, 2.2, 5.2, 2.4))


def test_box_rejects_padding_that_consumes_container():
    with pytest.raises(ValidationError):
        Box(x=0, y=0, width=1, height=1,
            padding=Insets(top=.6, right=.6, bottom=.6, left=.6))


def test_space_contract_rejects_safe_zone_outside_page():
    with pytest.raises(ValidationError):
        TemplateSpaceContract(page_width=13.33, page_height=7.5,
                              safe_zone=Box(x=12, y=1, width=2, height=3))
```

**Step 2: Run the tests to verify RED**

Run:

```powershell
Set-Location backend
python -m pytest tests/test_composition_models.py -v
```

Expected: collection fails with `ModuleNotFoundError: app.schemas.composition`.

**Step 3: Implement the minimal typed models**

Create `backend/app/schemas/composition.py` with these public types:

```python
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
        return (self.x + p.left, self.y + p.top,
                self.width - p.left - p.right,
                self.height - p.top - p.bottom)


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
        boxes = [self.safe_zone] + [z.box for z in self.protected_zones]
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
```

**Step 4: Run the tests to verify GREEN**

Run: `python -m pytest tests/test_composition_models.py -v`

Expected: 3 passed.

**Step 5: Commit**

```powershell
git add backend/app/schemas/composition.py backend/tests/test_composition_models.py
git commit -m "feat: add typed visual composition models"
```

### Task 2: Extract a template spatial contract

**Files:**
- Modify: `backend/app/parser/template_parser.py:23-73,260-318`
- Modify: `backend/app/pipeline/stages/parse_stages.py:98-140`
- Modify: `backend/app/ppt/renderer.py:105-143`
- Create: `backend/tests/test_template_space_contract.py`

**Step 1: Write failing extraction tests**

The tests build a 16:9 template with a title, top-right logo image, and footer. Assert that `_space_contract` returns inches, keeps the logo/footer as protected zones, and places the safe zone below the title and above the footer.

```python
from pptx import Presentation
from pptx.util import Inches

from app.parser.template_parser import _space_contract


def test_space_contract_reserves_title_logo_and_footer(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Inches(.8), Inches(.4), Inches(8), Inches(.6)).text = "页面标题"
    slide.shapes.add_textbox(Inches(.8), Inches(7.1), Inches(5), Inches(.2)).text = "公司机密"
    contract = _space_contract(slide, prs, {"left": 731520, "top": 365760,
                                             "width": 7315200, "height": 548640})
    assert contract["safe_zone"]["y"] >= 1.28
    assert contract["safe_zone"]["y"] + contract["safe_zone"]["height"] <= 7.0
    assert any(z["role"] == "footer" for z in contract["protected_zones"])
```

**Step 2: Verify RED**

Run: `python -m pytest tests/test_template_space_contract.py -v`

Expected: import failure for `_space_contract`.

**Step 3: Implement `_space_contract`**

Add deterministic helpers to `template_parser.py`:

- convert EMU to inches;
- start from page margins `left/right=.7`, top below the detected title plus `.28`, bottom above `.45`;
- classify small top-band pictures as `logo`;
- classify bottom-band text/shapes as `footer`;
- shrink the safe zone around protected zones only when their overlap exceeds 10%;
- emit `space_contract` in each slide's `layout_meta`;
- increment `PARSER_VERSION` from 5 to 6.

The resulting dict must match `TemplateSpaceContract.model_validate()`.

**Step 4: Reuse the contract in parsing and rendering**

- `ParseTemplateStage` already persists `layout_meta`; no schema migration is needed.
- Return the selected content-frame contract in `PARSE_TPL` output as `space_contract`.
- Replace the nested `content_area()` geometry calculation in `renderer.py` with contract-safe-zone lookup first, then keep the existing title-geometry fallback.

**Step 5: Verify GREEN and regressions**

Run:

```powershell
python -m pytest tests/test_template_space_contract.py -v
$env:PYTHONUTF8='1'; python tests/test_ai_templates.py
$env:PYTHONUTF8='1'; python tests/test_smoke.py
```

Expected: all commands pass.

**Step 6: Commit**

```powershell
git add backend/app/parser/template_parser.py backend/app/pipeline/stages/parse_stages.py backend/app/ppt/renderer.py backend/tests/test_template_space_contract.py
git commit -m "feat: extract enterprise template space contracts"
```

### Task 3: Add geometry and typography guards

**Files:**
- Create: `backend/app/ppt/layout_guard.py`
- Modify: `backend/app/ppt/design_tokens.py:18-61`
- Modify: `backend/app/ppt/layouts.py:63-83`
- Create: `backend/tests/test_layout_guard.py`

**Step 1: Write failing guard tests**

Cover one behavior per test:

```python
from app.ppt.layout_guard import (GuardIssue, check_box, check_typography,
                                  boxes_overlap)
from app.schemas.composition import Box, Insets, TemplateSpaceContract


def test_guard_reports_each_violated_edge_margin():
    parent = Box(x=0, y=0, width=5, height=4,
                 padding=Insets(top=.2, right=.3, bottom=.4, left=.5))
    child = Box(x=.2, y=.1, width=4.6, height=3.7)
    issues = check_box(child, parent)
    assert {i.code for i in issues} == {"margin_top", "margin_left", "margin_bottom"}


def test_typography_rejects_body_below_sixteen_points():
    issues = check_typography(role="body", size_pt=15, levels_on_page=3)
    assert [i.code for i in issues] == ["font_too_small"]


def test_touching_boxes_do_not_overlap():
    assert not boxes_overlap(Box(x=0, y=0, width=1, height=1),
                             Box(x=1, y=0, width=1, height=1))
```

**Step 2: Verify RED**

Run: `python -m pytest tests/test_layout_guard.py -v`

Expected: module import failure.

**Step 3: Implement the guard**

`layout_guard.py` must define immutable `GuardIssue(code, detail, severity="error")` and pure functions:

- `check_box(child, parent)` checks top/right/bottom/left independently against `parent.content_rect()`;
- `check_page_box(box, contract)` checks page and protected-zone collisions;
- `boxes_overlap(a, b, tolerance=.01)`;
- `check_typography(role, size_pt, levels_on_page, emphasis_count=0)` using semantic minimums;
- `guard_regions(recipe, contract)` returning all issues without raising.

Add typography ranges to `design_tokens.py`:

```python
TYPO_ROLES = {
    "cover_title": (32, 48), "section_title": (28, 40),
    "page_title": (24, 32), "conclusion": (22, 30),
    "body": (16, 22), "chart_label": (12, 16), "source": (10, 13),
}
```

Update `_text()` so `role` can be supplied and the role minimum wins over a lower caller-provided minimum. Existing calls without `role` retain current behavior until migrated by later tasks.

**Step 4: Verify GREEN**

Run: `python -m pytest tests/test_layout_guard.py -v`

Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/app/ppt/layout_guard.py backend/app/ppt/design_tokens.py backend/app/ppt/layouts.py backend/tests/test_layout_guard.py
git commit -m "feat: enforce container margins and typography roles"
```

### Task 4: Add layout recipes and deterministic selection

**Files:**
- Create: `backend/app/ppt/layout_recipes.py`
- Create: `backend/app/ppt/recipe_selector.py`
- Create: `backend/tests/test_layout_recipes.py`

**Step 1: Write failing recipe tests**

Test that:

- every recipe validates inside a standard safe zone;
- the selector rejects recipes that cannot accept the page's element types;
- the selector prefers a different family from the preceding slide;
- mirrored variants are deterministic for the same page and job id.

Use the public API:

```python
selection = select_recipe(
    page=7,
    job_seed="ppt_abc",
    requested_family="editorial_split",
    element_types=["bullet_group", "key_number"],
    contract=contract,
    previous_families=["cards_grid"],
)
assert selection.recipe.family == "editorial_split"
```

**Step 2: Verify RED**

Run: `python -m pytest tests/test_layout_recipes.py -v`

Expected: import failure.

**Step 3: Implement the initial catalog**

Create at least 12 recipes across these seven families:

- `single_focus`;
- `split`;
- `cards_grid`;
- `flow`;
- `structure`;
- `data_focus`;
- `editorial`.

All recipe regions must be normalized to a `0..1` coordinate system, then projected into the template safe zone. Use minimum paddings of `.18in` top/bottom and `.22in` left/right for text-bearing regions.

**Step 4: Implement deterministic scoring**

`select_recipe()` scores candidates as:

```text
content compatibility 40
different from recent families 25
contract fit 20
rhythm contribution 15
```

Break ties using `sha256(f"{job_seed}:{page}:{recipe.id}")`, never `random.random()`.

**Step 5: Verify GREEN**

Run: `python -m pytest tests/test_layout_recipes.py -v`

Expected: all tests pass.

**Step 6: Commit**

```powershell
git add backend/app/ppt/layout_recipes.py backend/app/ppt/recipe_selector.py backend/tests/test_layout_recipes.py
git commit -m "feat: add deterministic enterprise layout recipes"
```

### Task 5: Add deck rhythm and key-slide selection

**Files:**
- Create: `backend/app/ppt/deck_rhythm.py`
- Create: `backend/tests/test_deck_rhythm.py`

**Step 1: Write failing rhythm tests**

Cover:

- adjacent fingerprints may not match;
- one layout family may not exceed 30% of body slides when alternatives exist;
- three consecutive slides may not keep the same focal position;
- key-slide count is `min(5, ceil(body_count * .18))`;
- fewer than eight body slides selects at most one;
- at most one key slide per chapter and never adjacent key slides.

**Step 2: Verify RED**

Run: `python -m pytest tests/test_deck_rhythm.py -v`

Expected: import failure.

**Step 3: Implement pure rhythm functions**

Public API:

```python
def layout_fingerprint(plan: SlideVisualPlan, recipe: LayoutRecipe) -> str: ...
def rhythm_issues(plans: list[SlideVisualPlan], recipes: dict[int, LayoutRecipe]) -> list[GuardIssue]: ...
def rebalance_families(plans, candidates_by_page, job_seed) -> dict[int, LayoutRecipe]: ...
def select_key_slides(plans: list[SlideVisualPlan], chapter_by_page: dict[int, str]) -> list[int]: ...
```

Key-slide score weights must be 35/20/20/15/10 for business importance, structural complexity, climax need, ordinary-layout dissatisfaction, and rhythm contribution.

**Step 4: Verify GREEN**

Run: `python -m pytest tests/test_deck_rhythm.py -v`

Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/app/ppt/deck_rhythm.py backend/tests/test_deck_rhythm.py
git commit -m "feat: control deck rhythm and key slide selection"
```

### Task 6: Add soft-failing art direction and storyboard stages

**Files:**
- Create: `backend/app/ai/agents/design_agent.py`
- Create: `backend/app/pipeline/stages/design_stages.py`
- Modify: `backend/app/pipeline/stages/base.py:5-12`
- Create: `backend/tests/test_design_stages.py`

**Step 1: Write failing tests using a tiny fake gateway**

Test:

- standard/premium parse valid LLM JSON into typed models;
- malformed output returns a deterministic default art direction;
- storyboard output missing pages is completed deterministically;
- fast mode uses defaults without calling the gateway;
- every page receives one thesis, importance, focal position, and capacity.

Dependency-inject the gateway into stage constructors for tests; default to `get_gateway()` in production.

**Step 2: Verify RED**

Run: `python -m pytest tests/test_design_stages.py -v`

Expected: import failure.

**Step 3: Implement prompt builders**

`design_agent.py` exports:

```python
def generate_art_direction(gateway, mode, template_tokens, outline, job_id) -> dict: ...
def generate_storyboard(gateway, mode, art_direction, page_plan, job_id) -> dict: ...
```

Prompts must explicitly forbid new facts and request only visual/narrative metadata. Do not include full source text.

**Step 4: Implement stages and defaults**

- `ArtDirectionStage(code="ART_DIRECTION", weight=3)`;
- `StoryboardStage(code="STORYBOARD", weight=4)`;
- default direction inherits template fonts/palette;
- default storyboard maps structural pages to stable families and rotates body-page families/focal positions deterministically;
- all outputs are Pydantic-validated and checkpoint-safe.

**Step 5: Verify GREEN**

Run: `python -m pytest tests/test_design_stages.py -v`

Expected: all tests pass.

**Step 6: Commit**

```powershell
git add backend/app/ai/agents/design_agent.py backend/app/pipeline/stages/design_stages.py backend/app/pipeline/stages/base.py backend/tests/test_design_stages.py
git commit -m "feat: add deck art direction and storyboard stages"
```

### Task 7: Enforce storyboard capacity and preserve details in speaker notes

**Files:**
- Create: `backend/app/pipeline/guards/capacity_guard.py`
- Modify: `backend/app/pipeline/stages/content_stage.py:26-229`
- Modify: `backend/app/schemas/presentation.py:38-87`
- Create: `backend/tests/test_capacity_guard.py`

**Step 1: Write failing capacity tests**

Test the exact policy order at the pure-function level:

```python
result = fit_page_capacity(
    content={"title": "结论", "elements": [{"type": "bullet_group", "items": [
        "核心事实23个系统", "次要解释一", "次要解释二", "次要解释三"]}]},
    max_points=2,
    max_chars=80,
    source_numbers={"23"},
)
assert result.visible["elements"][0]["items"] == ["核心事实23个系统", "次要解释一"]
assert result.notes["details"] == ["次要解释二", "次要解释三"]
assert result.fact_numbers == {"23"}
```

Also test that number changes and proprietary-name deletion are rejected.

**Step 2: Verify RED**

Run: `python -m pytest tests/test_capacity_guard.py -v`

Expected: import failure.

**Step 3: Implement deterministic capacity fitting**

- prefer layout capacity before altering content;
- keep primary items first;
- move overflow supporting items to structured notes;
- never introduce or remove verified numbers;
- expose `details`, `sources`, and `moved_count`;
- do not call an LLM in this first implementation.

Extend `SlideSpec` with backward-compatible fields:

```python
visual_plan: dict[str, Any] | None = None
layout_recipe: str | None = None
speaker_notes: dict[str, Any] | None = None
```

**Step 4: Integrate into ContentStage**

When `STORYBOARD` exists, enforce each page's `max_points`/`max_chars` after `content_guard()`, persist notes in `JobSlide.content`, and publish only visible bullets in SSE previews.

**Step 5: Verify GREEN and content regression**

Run:

```powershell
python -m pytest tests/test_capacity_guard.py -v
$env:PYTHONUTF8='1'; python tests/test_smoke.py
```

Expected: all pass.

**Step 6: Commit**

```powershell
git add backend/app/pipeline/guards/capacity_guard.py backend/app/pipeline/stages/content_stage.py backend/app/schemas/presentation.py backend/tests/test_capacity_guard.py
git commit -m "feat: preserve overflow details in speaker notes"
```

### Task 8: Compose recipes into PresentationSpec and render them

**Files:**
- Create: `backend/app/pipeline/stages/composition_stage.py`
- Create: `backend/app/ppt/recipe_renderer.py`
- Modify: `backend/app/pipeline/stages/assemble_stages.py:52-100`
- Modify: `backend/app/ppt/renderer.py:180-292`
- Create: `backend/tests/test_composition_stage.py`
- Create: `backend/tests/test_recipe_renderer.py`

**Step 1: Write failing composition tests**

Test that CompositionStage:

- projects normalized recipe regions into the template safe zone;
- stores the chosen recipe and visual plan in every body SlideSpec;
- records no four-edge guard violation;
- reselects a recipe when the first candidate fails;
- falls back to `title_content` if all recipes fail.

Test recipe rendering with a real PPTX and reopen it with python-pptx to assert all generated shapes remain inside the content rectangle.

**Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_composition_stage.py tests/test_recipe_renderer.py -v
```

Expected: imports fail.

**Step 3: Implement CompositionStage**

`CompositionStage(code="COMPOSE", weight=4)` reads PLAN, STORYBOARD, CONTENT, MATCH, and PARSE_TPL. It selects recipes, runs `guard_regions`, performs deck rebalancing, and writes a serializable `composition_by_page` checkpoint.

Keep `LayoutStage` as the final PresentationSpec assembler, now consuming COMPOSE when present and retaining existing behavior when absent.

**Step 4: Implement recipe rendering**

`recipe_renderer.py` maps recipe regions to existing `ELEMENT_PAINTERS`. It must not duplicate chart/table logic. For unknown/missing mappings it emits a render note and delegates to the existing BODY_PAINTER.

**Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_composition_stage.py tests/test_recipe_renderer.py -v
$env:PYTHONUTF8='1'; python tests/test_visual.py
```

Expected: all pass.

**Step 6: Commit**

```powershell
git add backend/app/pipeline/stages/composition_stage.py backend/app/ppt/recipe_renderer.py backend/app/pipeline/stages/assemble_stages.py backend/app/ppt/renderer.py backend/tests/test_composition_stage.py backend/tests/test_recipe_renderer.py
git commit -m "feat: compose and render recipe-driven slides"
```

### Task 9: Wire mode-specific pipelines

**Files:**
- Modify: `backend/app/pipeline/modes/pipelines.py:1-82`
- Modify: `backend/app/pipeline/stages/base.py:5-12`
- Modify: `frontend/src/utils/constants.ts:39-58`
- Create: `backend/tests/test_visual_pipeline_modes.py`

**Step 1: Write failing mode tests**

Assert exact stage sequences:

```python
assert "ART_DIRECTION" not in codes("fast")
assert codes("standard").index("ART_DIRECTION") > codes("standard").index("PLAN")
assert codes("standard").index("STORYBOARD") < codes("standard").index("CONTENT")
assert codes("standard").index("COMPOSE") < codes("standard").index("LAYOUT")
assert "KEY_SLIDE_DESIGN" not in codes("standard")
assert "KEY_SLIDE_DESIGN" in codes("premium")
```

For this task, wire `KEY_SLIDE_DESIGN` as a no-op placeholder stage returning `{"selected": [], "applied": []}`; Task 10 replaces it with real behavior.

**Step 2: Verify RED**

Run: `python -m pytest tests/test_visual_pipeline_modes.py -v`

Expected: stage assertions fail.

**Step 3: Wire pipelines**

- fast remains unchanged;
- standard: PLAN → ART_DIRECTION → STORYBOARD → CONTENT → MATCH → COMPOSE → LAYOUT;
- premium: same plus KEY_SLIDE_DESIGN between LAYOUT and RENDER;
- add Chinese names to backend and frontend maps.

**Step 4: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_visual_pipeline_modes.py -v
$env:PYTHONUTF8='1'; python tests/test_smoke.py
Set-Location ..\frontend; npm run build
```

Expected: all pass; the existing AntD chunk-size warning is acceptable.

**Step 5: Commit**

```powershell
git add backend/app/pipeline/modes/pipelines.py backend/app/pipeline/stages/base.py frontend/src/utils/constants.ts backend/tests/test_visual_pipeline_modes.py
git commit -m "feat: enable visual composition by generation mode"
```

### Task 10: Add the constrained premium key-slide agent

**Files:**
- Create: `backend/app/schemas/scene.py`
- Create: `backend/app/ai/agents/key_slide_agent.py`
- Create: `backend/app/pipeline/stages/key_slide_stage.py`
- Create: `backend/app/ppt/scene_renderer.py`
- Modify: `backend/app/pipeline/modes/pipelines.py`
- Create: `backend/tests/test_key_slide_agent.py`
- Create: `backend/tests/test_key_slide_stage.py`

**Step 1: Write failing SceneSpec and selection tests**

Test:

- scene primitives are restricted to text, shape, chart, table, and connector;
- every primitive references an existing locked content id;
- text content must equal the frozen content value;
- invalid/missing content hashes reject the scene;
- selected page count and chapter/adjacency caps match Task 5;
- two failed attempts return the ordinary composition unchanged.

**Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_key_slide_agent.py tests/test_key_slide_stage.py -v
```

Expected: imports fail.

**Step 3: Implement constrained scene types**

`scene.py` defines `ScenePrimitive` and `SceneSpec` with boxes, z-order, content id, style token references, and no arbitrary font/color outside the approved tokens.

**Step 4: Implement agent boundary**

Use the existing `LLMGateway.chat_json("page_content", "premium", ...)` behind an injected interface. The prompt includes only frozen visible content, approved tokens, safe/protected zones, and adjacent-slide fingerprints. It explicitly forbids research and wording changes.

Validate content using canonical JSON + SHA-256 before accepting SceneSpec.

**Step 5: Implement stage and fallback**

`KeySlideDesignStage(code="KEY_SLIDE_DESIGN", weight=5, resumable=False)`:

1. chooses pages with `select_key_slides()`;
2. saves the ordinary composition as fallback;
3. requests at most two scene attempts per selected page;
4. validates layout/typography/content;
5. stores only accepted scenes;
6. never raises for a page-level agent failure.

`scene_renderer.py` reuses existing text/chart/table painters wherever possible and respects the template safe zone.

**Step 6: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_key_slide_agent.py tests/test_key_slide_stage.py -v
$env:PYTHONUTF8='1'; python tests/test_smoke.py
```

Expected: all pass.

**Step 7: Commit**

```powershell
git add backend/app/schemas/scene.py backend/app/ai/agents/key_slide_agent.py backend/app/pipeline/stages/key_slide_stage.py backend/app/ppt/scene_renderer.py backend/app/pipeline/modes/pipelines.py backend/tests/test_key_slide_agent.py backend/tests/test_key_slide_stage.py
git commit -m "feat: add constrained premium key slide agent"
```

### Task 11: Add deck-quality results to QA and reports

**Files:**
- Modify: `backend/app/pipeline/stages/qa_stages.py:22-132`
- Modify: `backend/app/ppt/visual_score.py:341-439`
- Modify: `frontend/src/api/types.ts:118-189`
- Modify: `frontend/src/pages/job-detail/SuccessView.tsx:302-410`
- Create: `backend/tests/test_deck_quality_report.py`

**Step 1: Write failing report tests**

Assert the report contains:

```python
report["composition"] == {
    "margin_violations": 0,
    "typography_violations": 0,
    "adjacent_fingerprint_duplicates": 0,
    "dominant_family_ratio": pytest.approx(...),
    "deck_rhythm_score": ...,
    "key_slides_selected": [...],
    "key_slides_applied": [...],
    "key_slides_fallback": [...],
}
```

**Step 2: Verify RED**

Run: `python -m pytest tests/test_deck_quality_report.py -v`

Expected: missing `composition` field.

**Step 3: Implement report aggregation**

- aggregate LAYOUT_GUARD/COMPOSE/KEY_SLIDE_DESIGN metadata;
- calculate rhythm score from explicit deductions;
- keep quality score and visual score unchanged for backward compatibility;
- expose the new composition block in the existing report modal.

**Step 4: Verify GREEN and frontend build**

Run:

```powershell
python -m pytest tests/test_deck_quality_report.py -v
Set-Location ..\frontend
npm run build
```

Expected: all pass/build succeeds.

**Step 5: Commit**

```powershell
git add backend/app/pipeline/stages/qa_stages.py backend/app/ppt/visual_score.py frontend/src/api/types.ts frontend/src/pages/job-detail/SuccessView.tsx backend/tests/test_deck_quality_report.py
git commit -m "feat: report composition and deck rhythm quality"
```

### Task 12: Full regression, docs, and final verification

**Files:**
- Modify: `README.md:114-145,249-262`
- Modify: `docs/03-IMPLEMENTATION.md`
- Modify: `docs/04-VISUAL-OPTIMIZATION.md`
- Modify: `backend/tests/test_visual.py`
- Create: `backend/tests/test_enterprise_composition_e2e.py`

**Step 1: Add a regression deck**

Create a deterministic enterprise template in the test and generate a 12-page deck with repeated content candidates. Assert:

- zero page/protected-zone/four-edge violations;
- zero body text below 16pt;
- exact target page count;
- no adjacent fingerprint duplicates;
- dominant layout family ratio at or below 30% when catalog alternatives exist;
- all verified numbers remain present in visible content or notes;
- premium agent failure returns a valid ordinary-layout PPTX.

**Step 2: Verify the new test fails before final integration fixes**

Run: `python -m pytest tests/test_enterprise_composition_e2e.py -v`

Expected: fail on any remaining integration gap; fix only production behavior demonstrated by the failing assertion.

**Step 3: Repair the existing pytest collection shape**

Rename chained helpers in `test_visual.py` from `test_ops_dsl(spec, score)` and `test_adjuster_and_loop(...)` to `_check_ops_dsl(...)` / `_check_adjuster_and_loop(...)`, keeping their direct-script execution. Add pytest wrapper tests with local setup so `python -m pytest -q` is clean.

**Step 4: Update documentation**

Document:

- mode behavior;
- template spatial contract;
- composition stages;
- font and margin hard constraints;
- notes overflow policy;
- key-slide selection and fallback;
- configuration/cost implications.

**Step 5: Run complete verification**

Run from `backend`:

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q
python tests/test_smoke.py
python tests/test_visual.py
python tests/test_ai_templates.py
python tests/test_pptmaster.py
```

Run from `frontend`:

```powershell
npm run build
```

Repository checks:

```powershell
git diff --check
git status --short
```

Expected: pytest has zero failures/errors, all four direct smoke scripts pass, frontend build succeeds, and `git diff --check` is clean. The existing Vite large-chunk advisory may remain.

**Step 6: Commit**

```powershell
git add README.md docs/03-IMPLEMENTATION.md docs/04-VISUAL-OPTIMIZATION.md backend/tests/test_visual.py backend/tests/test_enterprise_composition_e2e.py
git commit -m "docs: document enterprise visual composition pipeline"
```

## Final acceptance checklist

- [ ] Fast mode behavior and call count remain unchanged.
- [ ] Standard mode has ART_DIRECTION, STORYBOARD, COMPOSE, and deck rhythm control.
- [ ] Premium mode adds constrained key-slide scenes only.
- [ ] Every generated container passes top/right/bottom/left checks.
- [ ] Body text never drops below 16pt; source text is the only 10–13pt role.
- [ ] One page has at most one primary focal element.
- [ ] Adjacent fingerprints do not duplicate.
- [ ] A family does not dominate more than 30% when alternatives fit.
- [ ] Content compression preserves numbers, names, conclusions, and sources.
- [ ] Supporting details move to structured speaker notes.
- [ ] Key slides use at most 18% of body pages, capped at five, one per chapter, non-adjacent.
- [ ] Agent failure cannot fail the whole PPT job.
- [ ] Exact page count, editable PPTX output, checkpoints, retries, visual score, and quality report remain intact.
