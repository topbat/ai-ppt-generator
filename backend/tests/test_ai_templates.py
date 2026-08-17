"""AI 模板生成器冒烟测试（不依赖 DB/LLM）：
1. 八维参数生成 + 结构硬性要求（封面/目录/5~8内容页/尾页）；
2. 名称一律以 AI 为前缀；
3. 模板解析器角色识别（cover/toc/content_frame/ending 齐备，可直接用于生成）；
4. 非法参数回退默认，生成器永不炸。
运行：python tests/test_ai_templates.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.template_parser import parse_template  # noqa: E402
from app.ppt.template_gallery import (SEED_PRESETS, ai_options, build_ai_template,  # noqa: E402
                                      normalize_params, template_name)

_STRUCT = {"cover", "toc", "section", "ending"}


def _parse(data: bytes) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="aitpl_") as tmp:
        path = os.path.join(tmp, "t.pptx")
        with open(path, "wb") as f:
            f.write(data)
        parsed = parse_template(path)
    return [s["slide_type"] for s in parsed["slides"]]


def test_options():
    opts = ai_options()
    assert len(opts["industries"]) == 10 and len(opts["styles"]) == 5
    assert set(opts) == {"industries", "audiences", "styles", "data_contents",
                        "countries", "seasons"}
    print(f"✓ 八维选项通过（行业{len(opts['industries'])} 风格{len(opts['styles'])} "
          f"数据{len(opts['data_contents'])} 国家{len(opts['countries'])} 季节{len(opts['seasons'])}）")


def test_seed_presets():
    assert len(SEED_PRESETS) == 10, "初始化播种必须是 10 套"
    for preset in SEED_PRESETS:
        name = template_name(preset)
        assert name.startswith("AI"), f"名称未以 AI 为前缀: {name}"
        roles = _parse(build_ai_template(preset))
        content = [r for r in roles if r not in _STRUCT]
        assert roles[0] == "cover", f"{name} 首页应为封面: {roles}"
        assert "toc" in roles and "ending" in roles, f"{name} 缺目录/尾页: {roles}"
        assert 5 <= len(content) <= 8, f"{name} 内容页应为 5~8 个，实际 {len(content)}: {roles}"
        assert "content_frame" in roles, f"{name} 缺内容框架页（克隆底版）: {roles}"
    print(f"✓ 10 套播种预设通过（页结构均满足 封面+目录+5~8内容页+尾页）")


def test_full_params_and_fallback():
    # 全参数生成
    p = {"industry": "文旅消费", "audience": "公众演讲", "style": "活力明快",
         "data_content": "图文展示型", "theme": "城市文旅推介", "keywords": "山水·人文·美食",
         "country": "中国", "season": "秋"}
    name = template_name(p)
    assert name == "AI·城市文旅推介·活力明快", name
    roles = _parse(build_ai_template(p))
    assert 5 <= len([r for r in roles if r not in _STRUCT]) <= 8
    # 非法参数回退默认，不炸
    junk = normalize_params({"industry": "外星采矿", "style": "赛博蒸汽波", "season": "梅雨",
                             "theme": "x" * 100})
    assert junk["industry"] == "通用" and junk["style"] == "商务稳重" and junk["season"] == "不限"
    assert len(junk["theme"]) <= 20
    roles2 = _parse(build_ai_template({"industry": "外星采矿"}))
    assert roles2[0] == "cover" and "ending" in roles2
    print(f"✓ 全参数生成与非法参数回退通过（示例：{name}，{len(roles)} 页 → {roles}）")


if __name__ == "__main__":
    test_options()
    test_seed_presets()
    test_full_params_and_fallback()
    print("\nAI 模板生成器全部冒烟测试通过 ✅")
