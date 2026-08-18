"""ppt-master 能力目录：把 ppt-master（hugohe3/ppt-master v4.8）支持的入参枚举收敛为单一事实来源。

数据来源：ppt-master 仓库 skills/ppt-master/references/{canvas-formats.md, visual-styles/, modes/}
与 workflows/{routing.md, profiles/}。前端 GET /pptmaster/options 直接下发本目录。
"""

INPUT_MODES = [
    {"key": "files", "label": "上传源文件", "desc": "PDF / DOCX / PPTX / XLSX / MD / TXT / HTML / EPUB / 图片，可多个"},
    {"key": "topic", "label": "仅给主题", "desc": "只写题目，Agent 自行检索补充事实（topic-research）"},
    {"key": "text", "label": "粘贴文本", "desc": "把材料内容直接粘贴进来"},
    {"key": "url", "label": "网页链接", "desc": "网页 / 微信文章 URL 作为材料"},
]

ROUTES = [
    {"key": "generate", "label": "生成新 PPT（自由设计）",
     "desc": "ppt-master 主流程：理解材料 → 规划 → 逐页 SVG → 编译为原生 DrawingML PPTX"},
    {"key": "template_fill", "label": "套用我的 PPTX 模板生成", "needs_template": True,
     "desc": "template-fill-pptx：克隆模板页并原位填充文字/表格/图表，保留模板设计"},
    {"key": "beautify", "label": "美化现有 PPTX（页数/顺序/措辞 1:1）", "needs_pptx": True,
     "desc": "beautify-pptx profile：提取原稿事实，只重做版式与层级"},
    {"key": "enhance", "label": "为现有 PPTX 增加备注 / 旁白 / 转场", "needs_pptx": True,
     "desc": "native-enhance-pptx：直接补丁 OOXML，不重做设计"},
    {"key": "image_to_pptx", "label": "页面图片还原为可编辑 PPTX（仅 Codex）", "needs_pptx": False,
     "agents": ["codex"], "desc": "image-to-pptx profile：每张页面图还原为一页原生可编辑幻灯片"},
    {"key": "create_template", "label": "从参考物蒸馏可复用模板",
     "desc": "create-template：从 PPTX/图片/文档/品牌资产提炼 Brand / Style / Layout / Deck 模板工作区"},
]

PROFILES = [
    {"key": "quick", "label": "快速生成（推荐）", "desc": "跳过策略确认，Agent 自决，一次跑完（无人值守场景首选）"},
    {"key": "default", "label": "完整流程（自动决策，不确认）", "desc": "Strategist 规划 + 首页质检门 + 逐页 SVG + 终检；耗时更长、质量更稳"},
]

CANVAS_FORMATS = [
    {"key": "ppt169", "label": "PPT 16:9", "size": "1280×720", "ratio": "16:9", "desc": "商务汇报、会议"},
    {"key": "ppt43", "label": "PPT 4:3", "size": "1024×768", "ratio": "4:3", "desc": "传统投影、学术报告"},
    {"key": "xiaohongshu", "label": "小红书 3:4", "size": "1242×1660", "ratio": "3:4", "desc": "图文分享、知识帖"},
    {"key": "moments", "label": "朋友圈 / IG 1:1", "size": "1080×1080", "ratio": "1:1", "desc": "方形海报"},
    {"key": "story", "label": "竖版 Story 9:16", "size": "1080×1920", "ratio": "9:16", "desc": "竖屏故事、短视频封面"},
    {"key": "wechat", "label": "公众号头图 2.35:1", "size": "900×383", "ratio": "2.35:1", "desc": "公众号封面"},
    {"key": "banner", "label": "横幅 Banner 16:9", "size": "1920×1080", "ratio": "16:9", "desc": "网页横幅、大屏"},
    {"key": "a4", "label": "A4 打印", "size": "1240×1754", "ratio": "1:√2", "desc": "海报、传单"},
]

STYLES = [
    {"key": "auto", "label": "自动（由 Agent 依据材料选择）"},
    {"key": "template", "label": "由上传的 PPTX 模板决定", "desc": "模板填充路线专用，不可修改"},
    {"key": "swiss-minimal", "label": "swiss-minimal · 瑞士极简网格"},
    {"key": "editorial", "label": "editorial · 杂志编辑风"},
    {"key": "photo-editorial", "label": "photo-editorial · 摄影编辑风"},
    {"key": "data-journalism", "label": "data-journalism · 数据新闻（深色仪表盘）"},
    {"key": "dark-tech", "label": "dark-tech · 深色科技"},
    {"key": "glassmorphism", "label": "glassmorphism · 玻璃拟态"},
    {"key": "soft-rounded", "label": "soft-rounded · 柔和圆角"},
    {"key": "blueprint", "label": "blueprint · 蓝图工程"},
    {"key": "brutalist", "label": "brutalist · 粗野主义"},
    {"key": "memphis", "label": "memphis · 孟菲斯波普"},
    {"key": "zine", "label": "zine · 独立小志 / Risograph"},
    {"key": "vintage-poster", "label": "vintage-poster · 复古海报"},
    {"key": "paper-cut", "label": "paper-cut · 剪纸"},
    {"key": "ink-wash", "label": "ink-wash · 水墨"},
    {"key": "ink-notes", "label": "ink-notes · 手写笔记"},
    {"key": "sketch-notes", "label": "sketch-notes · 速写笔记"},
    {"key": "chalkboard", "label": "chalkboard · 黑板"},
    {"key": "pixel-art", "label": "pixel-art · 像素风"},
    {"key": "custom", "label": "自定义（在附加要求里描述风格）"},
]

NARRATIVE_MODES = [
    {"key": "auto", "label": "自动"},
    {"key": "pyramid", "label": "pyramid · 金字塔（结论先行的说服）"},
    {"key": "narrative", "label": "narrative · 叙事（讲故事）"},
    {"key": "instructional", "label": "instructional · 教学（讲清楚）"},
    {"key": "showcase", "label": "showcase · 展示（打动人）"},
    {"key": "briefing", "label": "briefing · 简报（中立信息）"},
]

READING_MODES = [
    {"key": "auto", "label": "自动"},
    {"key": "text", "label": "text · 阅读型（正文 18~21）"},
    {"key": "balanced", "label": "balanced · 平衡（正文 22~25）"},
    {"key": "presentation", "label": "presentation · 演示型（正文 28~32）"},
]

LANGUAGES = [
    {"key": "auto", "label": "自动（跟随材料）"},
    {"key": "zh", "label": "中文"},
    {"key": "en", "label": "English"},
]

IMAGE_SOURCES = [
    {"key": "auto", "label": "由 Agent 决定"},
    {"key": "none", "label": "不使用图片素材"},
    {"key": "search", "label": "网络图库搜索（Openverse / Wikimedia，配 PEXELS/PIXABAY Key 更佳）"},
    {"key": "ai", "label": "AI 生图（需在 ppt-master/.env 配置 IMAGE_BACKEND 与 Key）"},
]

ACCEPT_EXTENSIONS = [".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".csv", ".md", ".txt",
                     ".html", ".htm", ".epub", ".png", ".jpg", ".jpeg", ".webp"]

OUTPUT_KIND_LABELS = {
    "pptx": "PPTX（默认原生形状）",
    "pptx_native": "PPTX（原生图表/表格变体）",
    "pptx_narrated": "PPTX（含语音旁白）",
    "pdf": "PDF 预览",
    "log": "执行日志",
    "stream": "原始事件流（JSONL）",
    "report": "质检/交付报告",
}


def _keys(items):
    return {i["key"] for i in items}


VALID = {
    "input_mode": _keys(INPUT_MODES),
    "route": _keys(ROUTES),
    "profile": _keys(PROFILES),
    "canvas": _keys(CANVAS_FORMATS),
    "style": _keys(STYLES),
    "narrative_mode": _keys(NARRATIVE_MODES),
    "reading_mode": _keys(READING_MODES),
    "language": _keys(LANGUAGES),
    "image_source": _keys(IMAGE_SOURCES),
}

ROUTE_BY_KEY = {r["key"]: r for r in ROUTES}
