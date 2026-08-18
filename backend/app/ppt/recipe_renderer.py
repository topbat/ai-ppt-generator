from app.ppt.layouts import BODY_PAINTERS, ELEMENT_PAINTERS, _header
from app.schemas.composition import Box


def _region_boxes(data: dict) -> list[Box]:
    visual = data.get("visual_plan") or {}
    boxes = []
    for raw in visual.get("regions") or []:
        try:
            boxes.append(Box.model_validate(raw.get("box") or raw))
        except Exception:
            return []
    return boxes


def paint_recipe(rc, slide, data: dict) -> bool:
    boxes = _region_boxes(data)
    elements = [element for element in data.get("elements", []) if element.get("type")]
    if not boxes or not elements:
        return False
    if any(element.get("type") not in ELEMENT_PAINTERS for element in elements):
        rc.note(data.get("page"), "recipe_mapping_missing", "未知元素已按普通布局降级")
        BODY_PAINTERS.get(data.get("type"), BODY_PAINTERS["title_content"])(
            rc, slide, data, *_union_rect(boxes)
        )
        return True

    if len(elements) == 1 and elements[0]["type"] in {"cards", "key_number"} and len(boxes) > 1:
        items = elements[0].get("items") or []
        for box, item in zip(boxes, items):
            x, y, width, height = box.content_rect()
            ELEMENT_PAINTERS[elements[0]["type"]](
                rc,
                slide,
                {**elements[0], "items": [item]},
                x,
                y,
                width,
                height,
                data.get("page"),
            )
        return True

    for index, box in enumerate(boxes):
        assigned = elements[index:index + 1] if index < len(boxes) - 1 else elements[index:]
        if not assigned:
            continue
        x, y, width, height = box.content_rect()
        if len(assigned) == 1:
            element = assigned[0]
            ELEMENT_PAINTERS[element["type"]](
                rc, slide, element, x, y, width, height, data.get("page")
            )
        else:
            BODY_PAINTERS["title_content"](
                rc, slide, {**data, "elements": assigned}, x, y, width, height
            )
    return True


def paint_recipe_page(rc, slide, data: dict) -> bool:
    if not _region_boxes(data):
        return False
    _header(rc, slide, data)
    return paint_recipe(rc, slide, data)


def _union_rect(boxes: list[Box]) -> tuple[float, float, float, float]:
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.x + box.width for box in boxes)
    bottom = max(box.y + box.height for box in boxes)
    return left, top, right - left, bottom - top
