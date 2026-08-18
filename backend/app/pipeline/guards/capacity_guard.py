import copy
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapacityResult:
    visible: dict
    notes: dict
    fact_numbers: set[str]


def _all_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _all_text(child)]
    if isinstance(value, (list, tuple, set)):
        return [text for child in value for text in _all_text(child)]
    return []


def extract_numbers(value: Any) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", " ".join(_all_text(value))))


def fit_page_capacity(
    content: dict,
    max_points: int,
    max_chars: int,
    source_numbers: set[str],
    source_names: set[str] | None = None,
) -> CapacityResult:
    """按顺序保留主要信息，把超量支持材料移入结构化演讲者备注。"""
    visible = copy.deepcopy(content)
    input_text = " ".join(_all_text(content))
    input_numbers = extract_numbers(content)
    expected_numbers = {str(number) for number in source_numbers}
    if not expected_numbers.issubset(input_numbers):
        raise ValueError(
            f"verified numbers changed: expected {sorted(expected_numbers)}, got {sorted(input_numbers)}"
        )
    protected_names = set(source_names or set())
    missing_names = {name for name in protected_names if name not in input_text}
    if missing_names:
        raise ValueError(f"protected names missing: {sorted(missing_names)}")

    used_chars = sum(
        len(str(visible.get(key) or ""))
        for key in ("title", "subtitle", "key_message")
    )
    visible_points = 0
    moved = []
    for element in visible.get("elements", []):
        if element.get("type") != "bullet_group":
            continue
        kept = []
        for item in [str(item) for item in element.get("items", []) if str(item).strip()]:
            fits_points = visible_points < max_points
            fits_chars = used_chars + len(item) <= max_chars
            if visible_points == 0 or (fits_points and fits_chars):
                kept.append(item)
                visible_points += 1
                used_chars += len(item)
            else:
                moved.append(item)
        element["items"] = kept

    notes = {
        "details": moved,
        "sources": copy.deepcopy(content.get("sources") or []),
        "moved_count": len(moved),
    }
    output_numbers = extract_numbers({"visible": visible, "notes": notes})
    if output_numbers != input_numbers:
        raise ValueError("verified numbers changed while fitting page capacity")
    output_text = " ".join(_all_text({"visible": visible, "notes": notes}))
    if any(name not in output_text for name in protected_names):
        raise ValueError("protected names changed while fitting page capacity")
    return CapacityResult(visible=visible, notes=notes, fact_numbers=expected_numbers)
