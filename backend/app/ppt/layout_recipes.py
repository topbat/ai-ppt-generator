from app.schemas.composition import (
    Box,
    Insets,
    LayoutRecipe,
    LayoutRegion,
    TemplateSpaceContract,
)


_ALL_TEXT = ["bullet_group", "paragraph", "quote"]
_ALL_DATA = ["chart", "table", "key_number"]


def _region(
    region_id: str,
    role: str,
    x: float,
    y: float,
    width: float,
    height: float,
    importance: str = "secondary",
) -> LayoutRegion:
    return LayoutRegion(
        id=region_id,
        role=role,
        importance=importance,
        box=Box(x=x, y=y, width=width, height=height),
    )


def _recipe(recipe_id, family, allowed, regions, mirrored=False):
    return LayoutRecipe(
        id=recipe_id,
        family=family,
        allowed_elements=allowed,
        regions=regions,
        mirrored=mirrored,
    )


RECIPE_CATALOG = [
    _recipe("focus_statement", "single_focus", _ALL_TEXT + ["key_number"], [
        _region("focus", "primary", 0.08, 0.10, 0.84, 0.80, "primary"),
    ]),
    _recipe("focus_metric", "single_focus", ["key_number", "chart"], [
        _region("metric", "data", 0.16, 0.08, 0.68, 0.84, "primary"),
    ]),
    _recipe("split_left", "split", _ALL_TEXT + _ALL_DATA + ["cards", "comparison"], [
        _region("primary", "primary", 0.00, 0.00, 0.58, 1.00, "primary"),
        _region("support", "supporting", 0.62, 0.00, 0.38, 1.00),
    ]),
    _recipe("split_right", "split", _ALL_TEXT + _ALL_DATA + ["cards", "comparison"], [
        _region("support", "supporting", 0.00, 0.00, 0.38, 1.00),
        _region("primary", "primary", 0.42, 0.00, 0.58, 1.00, "primary"),
    ], mirrored=True),
    _recipe("cards_three", "cards_grid", ["cards", "key_number", "bullet_group"], [
        _region("card_1", "card", 0.00, 0.05, 0.31, 0.90, "primary"),
        _region("card_2", "card", 0.345, 0.05, 0.31, 0.90),
        _region("card_3", "card", 0.69, 0.05, 0.31, 0.90),
    ]),
    _recipe("cards_four", "cards_grid", ["cards", "key_number", "bullet_group"], [
        _region("card_1", "card", 0.00, 0.00, 0.48, 0.47, "primary"),
        _region("card_2", "card", 0.52, 0.00, 0.48, 0.47),
        _region("card_3", "card", 0.00, 0.53, 0.48, 0.47),
        _region("card_4", "card", 0.52, 0.53, 0.48, 0.47),
    ]),
    _recipe("flow_horizontal", "flow", ["timeline", "process", "architecture"], [
        _region("flow", "flow", 0.00, 0.18, 1.00, 0.64, "primary"),
    ]),
    _recipe("flow_vertical", "flow", ["timeline", "process", "architecture"], [
        _region("flow", "flow", 0.10, 0.00, 0.80, 1.00, "primary"),
    ]),
    _recipe("structure_layers", "structure", ["architecture", "process", "comparison"], [
        _region("structure", "structure", 0.06, 0.00, 0.88, 1.00, "primary"),
    ]),
    _recipe("structure_compare", "structure", ["comparison", "architecture", "bullet_group"], [
        _region("left", "primary", 0.00, 0.08, 0.47, 0.84, "primary"),
        _region("right", "primary", 0.53, 0.08, 0.47, 0.84, "primary"),
    ]),
    _recipe("data_hero", "data_focus", _ALL_DATA + ["bullet_group"], [
        _region("data", "data", 0.00, 0.00, 0.72, 1.00, "primary"),
        _region("insight", "supporting", 0.76, 0.08, 0.24, 0.84),
    ]),
    _recipe("data_full", "data_focus", ["chart", "table", "key_number"], [
        _region("data", "data", 0.03, 0.00, 0.94, 1.00, "primary"),
    ]),
    _recipe("editorial_aside", "editorial", _ALL_TEXT + ["key_number", "chart"], [
        _region("thesis", "primary", 0.00, 0.00, 0.66, 1.00, "primary"),
        _region("aside", "supporting", 0.72, 0.18, 0.28, 0.64),
    ]),
    _recipe("editorial_band", "editorial", _ALL_TEXT + ["key_number", "chart"], [
        _region("thesis", "primary", 0.04, 0.00, 0.92, 0.60, "primary"),
        _region("evidence", "supporting", 0.18, 0.68, 0.64, 0.32),
    ]),
]


def project_recipe(
    recipe: LayoutRecipe,
    contract: TemplateSpaceContract,
) -> LayoutRecipe:
    """把 0..1 语法坐标投影到模板正文安全区。"""
    base_x, base_y, base_w, base_h = contract.safe_zone.content_rect()
    regions = []
    for region in recipe.regions:
        normalized = region.box
        text_bearing = region.role != "media"
        padding = Insets(top=0.18, right=0.22, bottom=0.18, left=0.22) if text_bearing else Insets()
        regions.append(
            LayoutRegion(
                id=region.id,
                role=region.role,
                importance=region.importance,
                box=Box(
                    x=base_x + normalized.x * base_w,
                    y=base_y + normalized.y * base_h,
                    width=normalized.width * base_w,
                    height=normalized.height * base_h,
                    padding=padding,
                ),
            )
        )
    return recipe.model_copy(update={"regions": regions})
