"""文本测量引擎：估算文字在给定容器内的占用，用于自动选字号与溢出预判。

测量优先级：
1. 容器内置 Noto CJK 字体文件（PIL 实测，误差小）；
2. 启发式估算（中文全角 ≈ 1.0×字号，ASCII ≈ 0.55×字号）——无字体文件时兜底。
所有尺寸单位为磅（pt），1 英寸 = 72 pt。
"""
import math
import os
from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_SAFETY = 1.10  # 10% 安全边距：真实渲染器与测量间的偏差缓冲


@lru_cache(maxsize=64)
def _pil_font(size: int):
    """按字号缓存 PIL 字体对象；文件不存在返回 None（走启发式）。"""
    path = get_settings().font_path
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import ImageFont
        return ImageFont.truetype(path, size=size)
    except Exception as e:
        logger.warning("字体文件加载失败，改用启发式测宽: %s", e)
        return None


def text_width_pt(text: str, size_pt: float) -> float:
    font = _pil_font(int(size_pt))
    if font is not None:
        try:
            return font.getlength(text) * _SAFETY
        except Exception:
            pass
    # 启发式：中文/全角按 1.0 倍字号，半角按 0.55 倍
    width = sum(size_pt if ord(c) > 0x2E80 else size_pt * 0.55 for c in text)
    return width * _SAFETY


def wrap_line_count(text: str, box_w_pt: float, size_pt: float) -> int:
    """估算文本在指定宽度内的折行数。"""
    if not text:
        return 0
    total = 0
    for seg in text.split("\n"):
        total += max(1, math.ceil(text_width_pt(seg, size_pt) / max(box_w_pt, 1)))
    return total


def fits(text: str, box_w_pt: float, box_h_pt: float, size_pt: float,
         line_spacing: float = 1.35) -> bool:
    lines = wrap_line_count(text, box_w_pt, size_pt)
    return lines * size_pt * line_spacing <= box_h_pt


def fit_size(text: str, box_w_pt: float, box_h_pt: float,
             max_size: float, min_size: float, line_spacing: float = 1.35) -> tuple[float, bool]:
    """从 max_size 逐级下调找到能放下的字号。

    返回 (选定字号, 是否仍溢出)。字号绝不低于 min_size（可读性铁律），
    到达 min_size 仍放不下时返回 overflow=True，由 QA/修复链路处理。
    """
    size = max_size
    while size >= min_size:
        if fits(text, box_w_pt, box_h_pt, size, line_spacing):
            return size, False
        size -= 1
    return min_size, True


def truncate_to_fit(text: str, box_w_pt: float, box_h_pt: float, size_pt: float,
                    line_spacing: float = 1.35) -> str:
    """确定性截断（最后手段）：截到能放下为止，结尾加省略号。"""
    if fits(text, box_w_pt, box_h_pt, size_pt, line_spacing):
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(text[:mid] + "…", box_w_pt, box_h_pt, size_pt, line_spacing):
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + "…") if lo > 0 else text[:1]
