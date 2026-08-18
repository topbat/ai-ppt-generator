import hashlib
import json

from app.ppt.layout_guard import check_page_box
from app.schemas.composition import TemplateSpaceContract
from app.schemas.scene import SceneSpec


_SYSTEM = """你是企业演示文稿关键页的受约束视觉设计师。
只能重排给定的冻结内容，不得研究、补充、删除、改写任何事实或措辞。
每个图元必须引用已有 content_id，文本必须逐字等于 frozen value。
只能使用批准的颜色/字体 Token，并且所有图元必须位于安全区、避开品牌保护区。
只返回 SceneSpec JSON。"""


def canonical_content_hash(locked_content: dict) -> str:
    canonical = json.dumps(
        locked_content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_slide_content(slide) -> dict:
    locked = {}
    if slide.title:
        locked["title"] = slide.title
    if slide.subtitle:
        locked["subtitle"] = slide.subtitle
    if slide.key_message:
        locked["key_message"] = slide.key_message
    bullet_index = 0
    for index, element in enumerate(slide.elements):
        locked[f"element:{index}"] = element
        if element.get("type") == "bullet_group":
            for item in element.get("items") or []:
                locked[f"bullet:{bullet_index}"] = str(item)
                bullet_index += 1
        elif element.get("type") == "cards":
            for item_index, item in enumerate(element.get("items") or []):
                if item.get("title"):
                    locked[f"card:{item_index}:title"] = str(item["title"])
                if item.get("desc"):
                    locked[f"card:{item_index}:desc"] = str(item["desc"])
    return locked


def request_scene(
    gateway,
    page: int,
    locked_content: dict,
    approved_tokens: dict,
    contract: TemplateSpaceContract,
    adjacent_fingerprints: list[str],
    job_id: int,
) -> dict:
    payload = {
        "page": page,
        "content_hash": canonical_content_hash(locked_content),
        "locked_content": locked_content,
        "approved_tokens": approved_tokens,
        "space_contract": contract.model_dump(),
        "adjacent_fingerprints": adjacent_fingerprints,
        "allowed_primitives": ["text", "shape", "chart", "table", "connector"],
    }
    return gateway.chat_json(
        "page_content",
        "premium",
        _SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        job_id=job_id,
        temperature=0.2,
        max_tokens=3500,
    )


def validate_scene(
    scene: SceneSpec,
    locked_content: dict,
    contract: TemplateSpaceContract,
) -> SceneSpec:
    expected_hash = canonical_content_hash(locked_content)
    if scene.content_hash != expected_hash:
        raise ValueError("content hash does not match frozen content")
    for primitive in scene.primitives:
        if primitive.content_id not in locked_content:
            raise ValueError(f"unknown content id: {primitive.content_id}")
        frozen = locked_content[primitive.content_id]
        if primitive.type == "text" and primitive.text != str(frozen):
            raise ValueError(f"text differs from frozen text: {primitive.content_id}")
        issues = check_page_box(primitive.box, contract)
        if any(issue.severity == "error" for issue in issues):
            raise ValueError(f"scene primitive outside safe contract: {primitive.id}")
    return scene
