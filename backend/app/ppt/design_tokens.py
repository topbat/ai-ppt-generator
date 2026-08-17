"""PPT Design Token —— 视觉规范的单一事实来源（docs/04-VISUAL-OPTIMIZATION.md §2）。

原则：
- 排版常量全部收敛于此，绘制代码不允许出现散落的魔法数；
- 字号服务演示媒介：正文 16pt 起（密度高时），常规 18pt，拒绝 Word 化的 12/14pt 正文；
- 间距吸附 8pt spacing scale；正文不用纯黑；线条纤细。
"""

# ---- 画布与安全区（英寸） ----
CANVAS_W, CANVAS_H = 13.333, 7.5
MARGIN_X = 0.7           # 全局对齐锚线（思想文档：对齐比颜色更重要）
MARGIN_TOP = 0.45
MARGIN_BOTTOM = 0.45
GRID_COLS = 12
GRID_GUTTER = 0.25

# ---- 字号 Token（pt） ----
TYPO = {
    "title":    {"size": 28, "min": 20, "weight": 700, "line": 1.2},   # 页标题（系统路径）
    "subtitle": {"size": 14, "min": 11, "weight": 400, "line": 1.35},
    "heading":  {"size": 17, "min": 13, "weight": 600, "line": 1.3},   # 卡片标题/小标题
    "body":     {"size": 18, "min": 13, "weight": 400, "line": 1.5},   # 正文
    "caption":  {"size": 13, "min": 10, "weight": 400, "line": 1.4},   # 注释/来源/时间
    "number":   {"size": 54, "min": 28, "weight": 700, "line": 1.1},   # 关键数字=视觉主体
    "section_no": {"size": 88, "min": 48, "weight": 700, "line": 1.0},
}

# 语义角色字号范围。新构图层按角色校验，旧版式在逐步迁移前保持兼容。
TYPO_ROLES = {
    "cover_title": (32, 48),
    "section_title": (28, 40),
    "page_title": (24, 32),
    "conclusion": (22, 30),
    "body": (16, 22),
    "chart_label": (12, 16),
    "source": (10, 13),
}

# 密度 → 正文基准字号（不低于 16，演示可读性）
BODY_SIZE_BY_DENSITY = {"low": 20, "medium": 18, "high": 16}
MIN_BODY_SIZE = 13

# ---- 间距 scale（pt → 英寸换算：/72） ----
SPACING = {"xs": 8 / 72, "sm": 16 / 72, "md": 24 / 72, "lg": 32 / 72,
           "xl": 48 / 72, "xxl": 64 / 72}
TITLE_TO_BODY = SPACING["lg"]     # 标题 → 正文 32pt
CARD_GAP = SPACING["sm"] + 0.08   # 卡片间距 ~22pt（含视觉缓冲）
BLOCK_GAP = SPACING["lg"]

# ---- 中性色（浅底） ----
TEXT_COLOR = "1F2937"      # 正文不用纯黑
MUTED_COLOR = "64748B"
BORDER_COLOR = "E2E8F0"
SURFACE_COLOR = "FAFBFD"   # 卡片底

# ---- 中性色（深底自适应） ----
DARK_TEXT_COLOR = "F1F5F9"
DARK_MUTED_COLOR = "C3CCDA"
DARK_BORDER_COLOR = "56607A"

# ---- 圆角 / 线条（pt） ----
RADIUS = {"sm": 8, "md": 12, "lg": 16}
LINE = {"thin": 0.5, "normal": 1.0, "strong": 1.5}

# ---- 全局对齐锚线（英寸）：所有正文元素左缘的视觉锚点 ----
ANCHOR_X = MARGIN_X

# ---- 8pt spacing scale（pt），间距取值必须命中该序列 ----
SPACING_SCALE_PT = (8, 16, 24, 32, 48, 64)

# ---- 视觉评分支撑：Token 允许的字号全集（含各档 min~size 区间由评分器判定） ----
TOKEN_FONT_SIZES = sorted({v["size"] for v in TYPO.values()} | {v["min"] for v in TYPO.values()})


def snap8(inches: float) -> float:
    """把英寸值吸附到最近的 8pt 倍数（8pt Grid，工业化一致性）。"""
    pt = inches * 72
    return round(pt / 8) * 8 / 72


def col(i: int, span: int, x: float | None = None, w: float | None = None) -> tuple[float, float]:
    """12 列网格取位：返回第 i 列（0 基）跨 span 列的 (x, width)（英寸）。

    x/w 为内容区起点与总宽（默认整页安全区）；两栏=col(0,6)+col(6,6)、
    三卡=col(0,4)/col(4,4)/col(8,4)、图文=col(0,5)+col(5,7)。"""
    x = MARGIN_X if x is None else x
    w = (CANVAS_W - 2 * MARGIN_X) if w is None else w
    cw = (w - GRID_GUTTER * (GRID_COLS - 1)) / GRID_COLS
    left = x + i * (cw + GRID_GUTTER)
    width = cw * span + GRID_GUTTER * (span - 1)
    return left, width
