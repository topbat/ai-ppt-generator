"""把任务参数编译为发给 Agent（Claude Code / Codex）的提示词。

原则：
- 无人值守：明确告诉 Agent 不要向用户提问、需要决策时自行选择并继续；
- 显式即遵循：ppt-master 的 Quick 契约是"用户明说的必须遵守，没说的 Agent 自决"，
  因此每个用户填写的参数都转成一句明确指令；
- 产物位置固定：projects/<biz_id>/exports/，Worker 据此收集并上传；
- 提示词全部为中文（前端展示给用户看），Agent 会自行读取 ppt-master 的 SKILL.md 路由。
"""
from app.pptmaster.catalog import (CANVAS_FORMATS, NARRATIVE_MODES, READING_MODES, ROUTE_BY_KEY,
                                   STYLES)

_LABEL = {
    "canvas": {i["key"]: i["label"] for i in CANVAS_FORMATS},
    "style": {i["key"]: i["label"].split(" · ")[0] for i in STYLES},
    "narrative_mode": {i["key"]: i["label"].split(" · ")[0] for i in NARRATIVE_MODES},
    "reading_mode": {i["key"]: i["label"].split(" · ")[0] for i in READING_MODES},
}


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def build_prompt(biz_id: str, params: dict, source_rel_paths: list[str],
                 template_rel_path: str | None, project_rel: str | None = None) -> str:
    """params 为 API 层已校验的参数字典；source_rel_paths / project_rel 为相对 ppt-master 仓库根的路径。

    project_rel 为空时按 projects/{biz_id} 预估（API 侧预览用）；Worker 侧用 project_manager.py init
    的真实目录（形如 projects/{biz_id}_{canvas}_{YYYYMMDD}）重建提示词。
    """
    route = params.get("route", "generate")
    profile = params.get("profile", "quick")
    input_mode = params.get("input_mode", "files")
    project = project_rel or f"projects/{biz_id}"
    lines: list[str] = []

    # ---- 1. 角色与总要求 ----
    lines.append("请严格按本仓库的 ppt-master 工作流（先读 skills/ppt-master/SKILL.md 完成路由）执行下面这项任务。")
    lines.append("本次为无人值守自动执行：全程不要向我提问或等待确认；凡我未明确指定的选择，请你按专业判断"
                 "直接决定并继续；不要启动 confirm_ui / live preview 等需要人工交互的服务。")
    lines.append(f"项目工作区已经用 `project_manager.py init` 初始化完毕，目录为 `{project}/`（项目名 `{biz_id}`）："
                 "请直接在该目录内工作，不要再次 init、不要另建带日期后缀的新目录。")

    # ---- 2. 路线 ----
    if route == "generate":
        if profile == "quick":
            lines.append("路线：Generate PPTX，使用【快速生成 quick-generate】模式：跳过 Strategist 策略确认与 design_spec，"
                         "直接完成材料理解 → 页面决策 → 逐页 SVG → 终检 → 导出。")
        else:
            lines.append("路线：Generate PPTX，走完整默认流程（Strategist → Executor → 质检 → 导出）；"
                         "但 Stage 1/Stage 2 的设计规格确认由你根据下述参数自行锁定，不要等待我确认。")
    elif route == "template_fill":
        lines.append("路线：Fill Native PPTX（template-fill-pptx）：把材料内容填入我提供的 PPTX 模板，"
                     "保留模板设计，导出填充后的可编辑 PPTX。")
    elif route == "beautify":
        lines.append("路线：Generate PPTX 的 beautify-pptx profile：对我提供的 PPTX 做美化，"
                     "页数 / 顺序 / 措辞必须 1:1 保持，只优化版式与视觉层级。"
                     + ("使用 Quick 运行时。" if profile == "quick" else "使用默认运行时（自动决策不确认）。"))
    elif route == "enhance":
        lines.append("路线：Enhance Native PPTX（native-enhance-pptx）：对我提供的 PPTX 直接补丁 OOXML，"
                     "不改动版面与内容。")
    elif route == "image_to_pptx":
        lines.append("路线：Generate PPTX 的 image-to-pptx profile：把我提供的页面图片逐张还原为可编辑的原生幻灯片"
                     "（一图一页，文字原生还原，禁止整页截图皮肤）。")
    elif route == "create_template":
        lines.append("路线：Create Template：从我提供的参考物蒸馏可复用的 Brand / Style / Layout / Deck 模板工作区；"
                     "若该子流程可导出 review PPTX，请一并导出。")

    # ---- 3. 材料 ----
    if source_rel_paths:
        lines.append("材料文件（已放在项目 sources 目录，直接使用，不要询问是否存在）：")
        for p in source_rel_paths:
            lines.append(f"  - {p}")
    if template_rel_path:
        lines.append(f"我的 PPTX 模板：{template_rel_path}")
    if input_mode == "topic" and params.get("topic"):
        lines.append(f"主题：{params['topic']}（没有材料文件，请按 topic-research 自行补充事实并标注来源）")
    if input_mode == "url" and params.get("url"):
        lines.append(f"材料网址：{params['url']}（请先用 source_to_md.py 抓取转换）")
    if input_mode == "text" and params.get("text"):
        lines.append("材料文本如下（以 <<<MATERIAL>>> 与 <<<END>>> 包裹，请完整使用）：")
        lines.append("<<<MATERIAL>>>")
        lines.append(str(params["text"]).strip())
        lines.append("<<<END>>>")

    # ---- 4. 参数 ----
    reqs: list[str] = []
    canvas = params.get("canvas") or "ppt169"
    reqs.append(f"画布格式：{canvas}（{_LABEL['canvas'].get(canvas, canvas)}）")
    pages = params.get("pages")
    if pages:
        reqs.append(f"页数：正好 {pages} 页（含封面/结尾页）")
    else:
        reqs.append("页数：由你根据材料量决定")
    style = params.get("style") or "auto"
    if style == "custom":
        reqs.append("视觉风格：自定义，见下方附加要求")
    elif style != "auto":
        reqs.append(f"视觉风格：{style}（内置风格）")
    nm = params.get("narrative_mode") or "auto"
    if nm != "auto":
        reqs.append(f"叙事模式：{nm}（{_LABEL['narrative_mode'].get(nm, nm)}）")
    rm = params.get("reading_mode") or "auto"
    if rm != "auto":
        reqs.append(f"阅读模式：{rm}")
    lang = params.get("language") or "auto"
    if lang == "zh":
        reqs.append("输出语言：中文")
    elif lang == "en":
        reqs.append("输出语言：English")
    img = params.get("image_source") or "auto"
    if img == "none":
        reqs.append("图片素材：不使用外部图片（不生图、不搜图），用原生形状/图标/图表表达")
    elif img == "search":
        reqs.append("图片素材：优先网络图库搜索（image_search.py），必要时加署名；不做 AI 生图")
    elif img == "ai":
        reqs.append("图片素材：可使用 AI 生图（image_gen.py，需 .env 已配置 IMAGE_BACKEND；不可用则退回图库搜索）")
    if _truthy(params.get("native_charts")):
        reqs.append("图表/表格：导出为 PowerPoint 原生数据图表与表格对象（svg_to_pptx.py 加 --native-charts-and-tables）")
    if _truthy(params.get("speaker_notes")):
        reqs.append("讲者备注：为每页生成讲者备注（notes/）并写入 PPTX")
    if _truthy(params.get("narration")):
        reqs.append("语音旁白：基于讲者备注生成语音旁白并嵌入 PPTX（若 TTS 未配置则跳过并在最终回复中说明）")
    if _truthy(params.get("transitions")):
        reqs.append("转场：为幻灯片添加合适的原生切换效果")
    if _truthy(params.get("animations")):
        reqs.append("对象动画：为关键元素添加克制的进入/强调动画")
    if route == "enhance" and not any(_truthy(params.get(k)) for k in
                                      ("speaker_notes", "narration", "transitions", "animations")):
        reqs.append("增强项：未勾选具体项时，请添加讲者备注与转场")
    lines.append("参数要求：")
    lines.extend(f"  - {r}" for r in reqs)
    extra = (params.get("extra_instructions") or "").strip()
    if extra:
        lines.append("附加要求（优先级最高，须遵守）：")
        lines.append(extra)

    # ---- 5. 交付契约 ----
    lines.append("交付要求：")
    lines.append(f"  - 最终 PPTX 必须导出到 `{project}/exports/` 目录（使用工作流默认命名即可）；")
    lines.append(f"  - 过程中的 SVG、报告等中间产物保留在 `{project}/` 下，不要写到其他项目目录；")
    lines.append("  - 全部完成后，最后一条回复只写一行：`DONE: <相对仓库根的 pptx 路径>`；"
                 "若失败无法产出 PPTX，最后一条回复只写一行：`FAILED: <一句话原因>`。")
    return "\n".join(lines)


def route_label(route: str) -> str:
    r = ROUTE_BY_KEY.get(route)
    return r["label"] if r else route
