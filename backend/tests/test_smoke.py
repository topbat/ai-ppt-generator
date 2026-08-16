"""本地冒烟测试（不依赖 DB/Redis/MinIO/LLM）：
1. PageGuard 页数硬约束；2. ContentGuard 截断与数字回查；3. 全版式渲染出真实 PPTX。
运行：python tests/test_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pipeline.guards.guards import build_page_plan, content_guard  # noqa: E402
from app.ppt.renderer import render_presentation  # noqa: E402
from app.schemas.presentation import PresentationSpec, SlideSpec, ThemeSpec  # noqa: E402


def test_page_guard():
    outline = [{"chapter": "项目背景", "pages": 2, "summary": "背景"},
               {"chapter": "建设方案", "pages": 4, "summary": "方案"},
               {"chapter": "实施计划", "pages": 2, "summary": "计划"}]
    ai_slides = [{"page": 4, "chapter_idx": 1, "type": "title_content", "title": "行业趋势"},
                 {"page": 5, "chapter_idx": 2, "type": "architecture", "title": "总体架构"},
                 {"page": 6, "chapter_idx": 2, "type": "bar_chart", "title": "投资分布"}]
    plan, warnings = build_page_plan(outline, ai_slides, 12, "测试文档")
    assert len(plan) == 12, f"页数硬约束失败: {len(plan)}"
    assert plan[0]["type"] == "cover" and plan[1]["type"] == "toc" and plan[-1]["type"] == "summary"
    # 章节数超预算的自动合并
    many = [{"chapter": f"章{i}", "pages": 1, "summary": ""} for i in range(8)]
    plan2, w2 = build_page_plan(many, [], 10, "测试")
    assert len(plan2) == 10, f"预算冲突降级失败: {len(plan2)}"
    print(f"✓ PageGuard 通过（12页计划 {len(warnings)} 处修正；8章→10页自动合并 {len(w2)} 处）")


def test_content_guard():
    raw = {"page": 4, "type": "title_content", "title": "这是一个特别特别特别特别长的超限标题需要截断",
           "elements": [
               {"type": "bullet_group", "items": ["项目覆盖23个业务系统", "投资金额高达99亿元", "a" * 100]},
               {"type": "super_tech", "items": ["非法元素"]},
           ]}
    plan = {"page": 4, "type": "title_content", "title": "备用", "key_message": "核心观点"}
    source = "本项目覆盖23个业务系统，总投资1.2亿元。"
    fixed, issues = content_guard(raw, plan, "medium", source, "premium")
    assert len(fixed["title"]) <= 18
    assert all(el["type"] != "super_tech" for el in fixed["elements"])
    texts = str(fixed["elements"])
    assert "99亿元" not in texts, "专业模式未剔除无法验证的数字"
    assert "23" in texts, "已验证数字被误删"
    print(f"✓ ContentGuard 通过（{len(issues)} 个问题被拦截/修正）")


def test_render_all_layouts():
    slides = [
        SlideSpec(page=1, type="cover", title="企业数字化转型建设方案", subtitle="2026年度汇报"),
        SlideSpec(page=2, type="toc", title="目录", elements=[
            {"type": "bullet_group", "items": ["项目背景", "建设方案", "技术架构", "实施计划"]}]),
        SlideSpec(page=3, type="section", title="项目背景", section_no=1, key_message="数字化势在必行"),
        SlideSpec(page=4, type="title_content", title="行业趋势", elements=[
            {"type": "bullet_group", "items": ["政策驱动数字化提速", "行业竞争加剧", "客户体验要求提升"]}]),
        SlideSpec(page=5, type="two_column", title="现状与挑战", elements=[
            {"type": "bullet_group", "items": ["系统烟囱林立", "数据孤岛严重", "响应速度慢", "运维成本高"]}]),
        SlideSpec(page=6, type="three_cards", title="三大目标", elements=[
            {"type": "cards", "items": [{"title": "降本", "desc": "统一平台减少重复建设"},
                                        {"title": "增效", "desc": "流程自动化提升效率"},
                                        {"title": "创新", "desc": "数据驱动业务创新"}]}]),
        SlideSpec(page=7, type="key_number", title="核心指标", elements=[
            {"type": "key_number", "items": [{"value": "23个", "label": "业务系统"},
                                             {"value": "1.2亿", "label": "总投资"},
                                             {"value": "3年", "label": "建设周期"}]}]),
        SlideSpec(page=8, type="bar_chart", title="近三年项目数量", elements=[
            {"type": "chart", "chart_type": "bar", "title": "项目数量", "unit": "个",
             "data": [{"label": "2024", "value": 82}, {"label": "2025", "value": 116},
                      {"label": "2026", "value": 158}]}]),
        SlideSpec(page=9, type="pie_chart", title="投资构成", elements=[
            {"type": "chart", "chart_type": "pie", "title": "投资构成", "unit": "%",
             "data": [{"label": "平台", "value": 45}, {"label": "应用", "value": 35},
                      {"label": "安全", "value": 20}]}]),
        SlideSpec(page=10, type="table", title="里程碑计划", elements=[
            {"type": "table", "headers": ["阶段", "时间", "目标"],
             "rows": [["一期", "2026Q3", "平台搭建"], ["二期", "2027Q1", "应用迁移"],
                      ["三期", "2027Q4", "全面上线"]]}]),
        SlideSpec(page=11, type="timeline", title="实施路线", elements=[
            {"type": "timeline", "items": [{"time": "2026Q3", "title": "启动", "desc": "平台选型"},
                                           {"time": "2027Q1", "title": "建设", "desc": "核心开发"},
                                           {"time": "2027Q4", "title": "上线", "desc": "全面推广"}]}]),
        SlideSpec(page=12, type="process", title="推进流程", elements=[
            {"type": "process", "steps": ["调研", "设计", "开发", "测试", "上线"]}]),
        SlideSpec(page=13, type="architecture", title="总体技术架构", elements=[
            {"type": "architecture", "layers": [
                {"title": "用户层", "items": ["PC端", "移动端", "驾驶舱"]},
                {"title": "应用层", "items": ["门户", "OA", "CRM"]},
                {"title": "平台层", "items": ["数据中台", "业务中台"]},
                {"title": "基础层", "items": ["云资源", "网络", "安全"]}]}]),
        SlideSpec(page=14, type="comparison", title="建设前后对比", elements=[
            {"type": "comparison", "left": {"title": "现状", "items": ["人工处理", "数据分散"]},
             "right": {"title": "目标", "items": ["自动流转", "统一中台"]}}]),
        SlideSpec(page=15, type="quote", title="愿景", elements=[
            {"type": "quote", "text": "让数据驱动每一个决策", "author": "项目组"}]),
        SlideSpec(page=16, type="summary", title="总结", elements=[
            {"type": "bullet_group", "items": ["统一数字底座", "三年三步走", "价值可量化"]}]),
    ]
    spec = PresentationSpec(title="冒烟测试演示文稿", total_pages=len(slides),
                            theme=ThemeSpec(), slides=slides)
    out = os.path.join(os.path.dirname(__file__), "smoke_output.pptx")
    result = render_presentation(spec, out)
    assert os.path.exists(out) and os.path.getsize(out) > 20000
    assert not result["degraded_pages"], f"存在降级页: {result['degraded_pages']}"
    # 用 python-pptx 重新打开验证文件完整性
    from pptx import Presentation
    prs = Presentation(out)
    assert len(prs.slides.__iter__.__self__._sldIdLst) == len(slides)
    print(f"✓ 渲染通过：{len(slides)} 页全版式 PPTX（{os.path.getsize(out) // 1024}KB，"
          f"渲染备注 {len(result['notes'])} 条）→ {out}")


def test_json_repair():
    from app.ai.gateway import repair_json
    assert repair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert repair_json('前缀{"a": [1, 2,], }后缀') == {"a": [1, 2]}
    assert repair_json("不是json") is None
    print("✓ JSON 修复器通过")


if __name__ == "__main__":
    test_page_guard()
    test_content_guard()
    test_json_repair()
    test_render_all_layouts()
    print("\n全部冒烟测试通过 ✅")
