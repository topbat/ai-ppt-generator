"""字体工具：统一设置中西文字体（python-pptx 的 font.name 只作用于拉丁字符，
中文需要显式写入 a:ea 东亚字体节点，否则容器内渲染会退回默认字体）。"""
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Pt


def set_run_font(run, name: str, size_pt: float, color_hex: str, bold: bool = False) -> None:
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.name = name
    run.font.color.rgb = RGBColor.from_string(color_hex)
    # 关键：补写东亚(a:ea)与复杂文种(a:cs)字体，保证中文命中目标字体
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
        el = rPr.makeelement(qn(tag), {"typeface": name})
        rPr.append(el)
