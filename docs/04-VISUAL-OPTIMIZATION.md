# AI PPT 生成系统 — 视觉优化（Visual Optimization）设计文档

> 版本：V1.0
> 日期：2026-08-14
> 定位：在现有"快速生成"能力之上叠加的第二阶段能力
> 思想来源：tmp/AI 辅助美化.md（12 维排版认知 / Design Token / 视觉评分模型 / 两阶段架构）
> 关联文档：[03-IMPLEMENTATION.md](03-IMPLEMENTATION.md)（快速生成架构）

> 当前实现边界：规则九维评分和确定性美化已落地；`VISION_QA_ENABLED` 默认是 `false`，只有显式开启并提供可用视觉模型配置时，专业模式才调用 Vision Critic。独立 `POST /api/v1/beautify` 是同步接口，直接返回报告和后端代理下载地址，不进入 Celery 主生成队列。

---

## 1. 定位：两阶段架构

```text
第一阶段：快速生成（已实现）                第二阶段：视觉优化（本设计）
内容 → Layout → 模板克隆 → PPTX            PPTX → 截图 → 视觉评分 → 问题清单
                                            → 确定性调整 → 重渲染 → 复评（≤3轮）
30页 目标 1~2 分钟                          追加 2~5 分钟
```

核心原则（来自思想文档，作为本设计的公理）：

1. **布局 > 信息层级 > 字体 > 间距 > 色彩 > 装饰** —— 优化优先级按此排序，不把力气花在配色装饰上；
2. **排版工作交给 Design Token + Layout Engine + 确定性调整器，LLM 只做理解与建议** —— 保证速度、风格统一、可控；
3. **对齐比颜色更重要** —— 全局对齐锚线是最便宜也最有效的高级感来源；
4. **超过文字量预算就拆页/精简，绝不缩字号到不可读**（已有铁律，延续）；
5. **模板一致性仍是最高前提** —— 视觉优化只动我们绘制的内容层，绝不动模板克隆的装饰层。

---

## 2. Design Token 体系（规范落地）

新增 `app/ppt/design_tokens.py`，所有绘制常量从散落代码收敛为 Token（单一事实来源）：

```yaml
canvas:  { width: 13.333, height: 7.5 }          # 16:9
margin:  { left: 0.7, right: 0.7, top: 0.45, bottom: 0.45 }
grid:    { columns: 12, gutter: 0.25 }           # 12 列网格
anchor_x: 0.7                                     # 全局对齐锚线

typography:            # 字号 Token（pt）；演示媒介，正文不低于 18
  title:    { size: 32, weight: 700, line: 1.2 }   # 页标题（系统路径）
  subtitle: { size: 20, weight: 500, line: 1.3 }
  heading:  { size: 22, weight: 600, line: 1.25 }  # 卡片标题/小标题
  body:     { size: 18, weight: 400, line: 1.5 }   # 正文（原 14~17 → 18 起）
  caption:  { size: 14, weight: 400, line: 1.4 }   # 注释/来源/单位
  number:   { size: 60, weight: 700, line: 1.1 }   # 关键数字（视觉主体）

spacing: [8, 16, 24, 32, 48, 64]   # 8pt spacing scale，所有间距取值于此
  title_to_body: 32
  card_gap: 16
  block_gap: 32

radius:  { sm: 8, md: 12, lg: 16 }               # 圆角（pt），拒绝全圆角
shadow:  { opacity: 0.10, blur: 18, offset: 4 }  # 轻阴影
line:    { thin: 0.5, normal: 1.0, strong: 1.5 } # 线宽（pt）

color_roles:           # 色彩角色（从模板采收后映射，每页 主色1+辅色≤2+中性2~4）
  primary / secondary / accent / background / surface / text / muted / border
  text: "1F2937"       # 正文不用纯黑
  muted: "64748B"
  border: "E2E8F0"
```

落地方式：

- `layouts.py` 的 BODY_SIZE/GRAY_TEXT/LIGHT_BORDER/间距魔法数 全部改从 Token 取值；
- 深色背景自适应保留：Token 提供 light/dark 两套 text/muted/border 取值；
- 模板路径下 `title` Token 不生效（标题样式来自模板占位符），其余 Token 生效。

## 3. 12 列网格与布局升级（Layout Engine）

- 内容区按 12 列网格划分：`col(i, span)` 返回精确 x/w，两栏=6+6、三卡=4+4+4、图文=5+7、2×2=6+6×2；
- **对齐锚线**：所有正文元素左缘统一 `anchor_x`（标题/正文/卡片/图表同一锚线，形成视觉锚点）；
- **8pt 网格吸附**：所有 y 坐标与间距吸附到 8pt 倍数（inch 值 ×72 后取最近 8 的倍数）；
- **视觉重量平衡**：两栏内容量差 >2.5 倍时自动改 5/7 或 4/8 分栏；
- **纯文字页视觉化**（思想文档 §28-29 的五种高级表达）：
  - 密度低（≤2 信息点）的 title_content 自动升格为"大标题页"（40pt 居中）或"大数字页"；
  - 要点含明显时序词 → 建议 timeline；含层级词 → 建议 architecture（PLAN 阶段提示词强化）。

## 4. 视觉评分模型（PPT Visual Score，独立于生成质量分）

九维 100 分制（思想文档 §36），逐页评分 + 整册汇总：

| 维度 | 分值 | 评分方式 | 可确定性计算 |
|---|---:|---|:-:|
| Layout 布局 | 20 | 元素在网格列上的落位率、内容区外溢检测 | ✅ |
| Alignment 对齐 | 15 | 各元素左缘与锚线/网格线的偏差统计 | ✅ |
| Typography 字体 | 15 | 字号是否取自 Token、层级字号是否单调递减、Bold 占比 | ✅ |
| Spacing 间距 | 10 | 间距值对 spacing scale 的命中率、标题-正文距 | ✅ |
| Color 色彩 | 10 | 每页色相数（主1+辅2+中性4 内）、正文纯黑检测、对比度 | ✅ |
| Hierarchy 层级 | 10 | L1-L5 视觉强度递减检验（字号×字重×颜色深度） | ✅ |
| Density 密度 | 10 | 信息点数 vs 版式预算（普通3~5/卡片3~4/架构5~9） | ✅ |
| Image 图片 | 5 | 图片占比区间、变形检测、图上文字对比度 | 部分 |
| Consistency 一致性 | 5 | 跨页 Token 一致性（字体/主色/锚线/页码） | ✅ |

- **规则引擎优先**：9 维中 8 维可从 Presentation JSON + 渲染几何确定性计算（毫秒级、零成本）；
- **Vision 增强（专业模式可选）**：qwen-vl 对规则难以判断的（图片构图、整体协调）打分并产出问题描述；
- 数据落点：`job_slides.visual_score`（页级）+ `generation_jobs.visual_score`（册级=页均分）；与现有 `quality_score`（生成质量分：完成度/事实/无越界）**并列展示，不互相替代**。

## 5. 视觉优化闭环（BEAUTIFY 阶段）

```text
RENDER 产物
   ↓
VISUAL_SCORE（规则9维评分，逐页）
   ↓
问题清单 → Fix Ops（结构化修复指令，确定性执行）
   │         op 示例：
   │         {op:"snap_align",  page:5, detail:"左缘吸附锚线"}
   │         {op:"apply_spacing",page:5, detail:"标题-正文距 24→32"}
   │         {op:"font_token",  page:7, detail:"正文 14→18，标题降权重"}
   │         {op:"reduce_palette",page:8, detail:"辅色 4→2"}
   │         {op:"upgrade_layout",page:9, detail:"低密度页升格大字报"}
   │         {op:"rebalance",   page:11,detail:"两栏改 5/7"}
   ↓
确定性调整器（Adjuster）应用 Ops → 更新 Presentation JSON → 重渲染
   ↓
复评（分数必须上升，≤3 轮，取历史最优）
   ↓
（专业模式追加）Vision Critic：截图 → qwen-vl → 补充 Ops → 再执行 1 轮
```

关键设计决策：

1. **Fix Ops 是受控 DSL**：LLM/Vision 只能建议枚举内的 op，执行永远是确定性代码——不会“越修越乱”；
2. **一次性正确优先**：Token 化后大部分维度在渲染期就已达标，BEAUTIFY 主要处理动态内容导致的偏差（内容长短、AI 选型不佳）；
3. 模板装饰层（克隆的形状）只读，Ops 只作用于我们绘制的内容元素。

## 6. 流程/接口/存储变更

### 6.1 流水线

| 模式 | 视觉优化行为 |
|---|---|
| ⚡ 极速 | 仅 Token 化渲染（一次性正确），不跑 BEAUTIFY 闭环 |
| 🚀 标准 | BEAUTIFY 规则闭环 ≤2 轮 |
| 💎 专业 | BEAUTIFY 规则闭环 ≤2 轮 +（开启 `VISION_QA_ENABLED` 时）Vision Critic 1 轮 |

新增 stage：`BEAUTIFY`（位于 RENDER 之后、CONVERT 之前；与 REPAIR 独立——REPAIR 管"对不对"，BEAUTIFY 管"好不好看"）。

### 6.2 历史任务一键美化

`POST /api/v1/jobs/{id}/beautify` → 以原任务为父创建新版本 Job，流水线从 LAYOUT 断点恢复（复用内容），只跑 LAYOUT→RENDER→BEAUTIFY→CONVERT→QA→PUBLISH。前端成功页新增"一键美化"按钮。

### 6.3 数据与报告

- `job_slides.visual_score SMALLINT`、`generation_jobs.visual_score SMALLINT`（建表已幂等，新列自动创建）；
- `validation_reports.report.visual` 新增九维明细：`{layout: 18, alignment: 14, ..., pages: [{page, score, deductions: [...]}]}`；
- 前端质检报告抽屉：九维条形图 + 逐页评分列表；预览页每页角标显示页级分。

## 7. SLA 目标（两阶段合计）

| 页数 | 极速（Token化渲染） | 标准（+规则闭环） | 专业（+Vision） |
|---:|---|---|---|
| 10 | <1 分钟 | 1~3 分钟 | 2~4 分钟 |
| 20 | <2 分钟 | 2~5 分钟 | 3~7 分钟 |
| 30 | <3 分钟 | 3~8 分钟 | 5~10 分钟 |

## 8. 实施计划

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **V-M1 Token 化** | design_tokens.py；layouts.py 全量接 Token（字号↑18 起/8pt 吸附/锚线对齐/轻阴影圆角规范）；正文不纯黑 | 全量批测分数不降，目测层级/留白明显改善 |
| **V-M2 评分引擎** | visual_score.py 规则九维逐页评分；报告九维明细 + 前端展示 | 20 模板批测出分，人工抽检评分与观感一致 |
| **V-M3 优化闭环** | Fix Ops DSL + Adjuster + BEAUTIFY 阶段（标准/专业）；历史任务一键美化 API+按钮 | 闭环后 visual_score 平均提升 ≥8 分 |
| **V-M4 Vision Critic** | qwen-vl 审查产出受控 Ops；专业模式接入 | 专业模式 visual_score ≥ 90 |

实施顺序即上表；V-M1/V-M2 先行（一次性正确 + 可度量），闭环与 Vision 在其上叠加。

---

## 9. 实现状态（2026-08-14，V-M1~V-M4 全部落地）

### 9.1 文件清单

| 模块 | 文件 | 说明 |
|---|---|---|
| Design Token | `backend/app/ppt/design_tokens.py` | 字号/间距/圆角/中性色 + `col(i,span)` 12列网格 + `ANCHOR_X` 锚线 + `snap8` |
| 评分引擎 | `backend/app/ppt/visual_score.py` | 九维规则引擎：输入 Presentation JSON + 渲染产物 PPTX 真实几何，逐页评分+整册汇总+中文扣分明细 |
| Fix Ops | `backend/app/ppt/visual_ops.py` | 受控 DSL（6 个枚举 op）+ 确定性调整器（spec 级）+ `polish_pptx` 几何微调（pptx 级） |
| BEAUTIFY 阶段 | `backend/app/pipeline/stages/beautify_stage.py` | 闭环 ≤2 轮/分数必须上升/取历史最优/≥90 提前收束；专业模式按开关调用 Vision Critic；`compute_visual_once` 供极速模式 QA 一次性出分 |
| 一键美化 | `backend/app/services/beautify_service.py` + `jobs_api.py` | fork 子任务：复制 checkpoint 到子命名空间（不污染父产物）→ resume 只跑 RENDER 之后 |
| 前端 | `SuccessView.tsx` / `JobDetail.tsx` / `types.ts` / `endpoints.ts` | 一键美化按钮、视觉分标签、报告抽屉九维条形图+逐页评分 |
| 对外美化 API | `backend/app/ppt/beautify_external.py` + `api/beautify_api.py` | `POST /api/v1/beautify`：上传任意 PPTX → 伪 Spec 构建（解析器逐页定型）→ 九维评分 → 确定性美化（锚线/8pt 吸附 + 纯黑正文替换，复评不升则回退）→ 报告 + 产物下载；模板库"PPT 美化演示"入口即调用本 API |
| 测试 | `backend/tests/test_visual.py` | 评分/DSL/调整器/闭环/稳定性 五项冒烟（不依赖 DB/LLM，按脚本直接运行） |

### 9.2 与设计的差异说明

1. **几何吸附前移到渲染期**（原设计属 BEAUTIFY）：`render_and_upload` 渲染后即执行
   `polish_pptx`（左缘聚类吸附 ≤8pt、8pt 网格吸附 ≤3pt，仅动带文字形状），全模式生效——
   即"一次性正确优先"原则的落地；BEAUTIFY 闭环只处理 spec 级问题（升格/配平/精简）；
2. **极速模式仍出视觉分**：不跑闭环，但 QA 阶段调用 `compute_visual_once` 规则出分并落库
   （毫秒级），保证三种模式的 visual_score 数据完整；
3. **reduce_palette 仅登记留痕**：色彩来源于模板主题与 Token，规则层无可改字段，
   该 op 留给 Vision/人工决策；
4. **数据落点**：`generation_jobs.visual_score` / `job_slides.visual_score`（init_db 幂等
   `ADD COLUMN IF NOT EXISTS` 自动升级老库）；报告 `report.visual = {score, dimensions,
   score_before, rounds, ops_applied, pages[]}`。

### 9.3 验收记录

- 冒烟：刻意缺陷册闭环 96→97 分，Ops 全部正确推导与应用；常规册 93 分无升格误报；
- 端到端（本地真实任务，标准模式 8 页）：35s 成功，质量分 96 / 视觉分 98，
  BEAUTIFY 阶段 94ms（98 分达标提前收束）；一键美化 fork 任务前 10 阶段全部断点复用，6s 完成。
