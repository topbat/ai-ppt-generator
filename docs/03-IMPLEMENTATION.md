# AI PPT 自动生成系统 — 整体实现方案

> 版本：V1.1
> 日期：2026-08-17（按当前代码同步）
> 内容：总体架构 / 模块设计 / 三模式流水线 / 流程设计 / 状态设计 / 当前 ORM 表 / API / 存储与预览 / 容器化部署 / 已知边界
> 关联文档：[01-PRD.md](01-PRD.md)、[02-UI-DESIGN.md](02-UI-DESIGN.md)

> 本文同时保留部分 V1 设计目标。标注“规划/后续”的内容尚未在当前代码中实现；当前运行入口和服务清单以仓库根目录 `README.md`、`deploy/docker-compose.yml` 以及 `backend/app` 为准。

---

## 1. 总体架构

### 1.1 架构图（容器视图）

```text
                        ┌─────────────────────┐
                        │  Frontend (React)    │  nginx 容器
                        │  静态资源 + 反向代理   │
                        └──────────┬──────────┘
                                   │ /api  (REST + SSE)
                        ┌──────────▼──────────┐
                        │  API Service         │  FastAPI 容器 ×N
                        │  上传/任务/查询/SSE    │
                        └───┬──────────┬───────┘
                            │          │
              投递任务(队列) │          │ 读写元数据
                ┌───────────▼──┐   ┌───▼────────────┐
                │  Redis        │   │  PostgreSQL     │
                │  broker/cache │   │  (+pgvector)    │
                │  /progress    │   └───┬────────────┘
                └───────┬──────┘        │
                        │ 消费           │
          ┌─────────────▼─────────────┐ │
          │  Worker (Celery) 容器 ×N   │◀┘
          │  ┌───────────────────────┐│
          │  │ Pipeline Orchestrator ││        ┌──────────────┐
          │  │  Parser / Knowledge   ││ HTTPS  │ LLM Gateway   │
          │  │  Outline / Planner    │├───────▶│  Qwen(百炼)   │
          │  │  Content / Matcher    ││        │  DeepSeek     │
          │  │  Renderer / Guards    ││        │  (进程内模块)  │
          │  │  QA / Repair          ││        └──────────────┘
          │  └───────────┬───────────┘│
          └──────────────┼────────────┘
             ┌───────────┼───────────────┐
             ▼           ▼               ▼
      ┌───────────┐ ┌────────────────────┐ ┌─────────────────┐
      │  MinIO/OSS │ │ Worker 内置          │ │ Prometheus/     │
      │  文件/产物  │ │ LibreOffice         │ │ Grafana         │
      └───────────┘ │ PPTX→PDF→PNG       │ │ （后续能力）    │
                    └────────────────────┘ └─────────────────┘
```

要点：

- **API 与 Worker 分离**：API 只做轻量请求（<500ms），所有生成工作在 Worker 内异步执行；
- **LLM Gateway 是进程内模块**（非独立服务），统一封装 Qwen/DeepSeek 的路由、重试、熔断、计量；V2 可拆独立服务；
- **LibreOffice 内置在 `worker`/`pptmaster-worker` 镜像**，默认由 Worker 启动独立 `soffice` 子进程转换；只有显式配置 `CONVERT_BACKEND=unoserver` 才会访问外部 unoserver，当前 Compose 未定义该服务；
- 进度通过 Redis Pub/Sub 流转：Worker 发布 → API 订阅 → SSE 推送前端。

### 1.2 技术选型

| 模块 | 选型 | 说明 |
|---|---|---|
| 前端 | React 18 + Ant Design 5 + Vite + TS | 构建产物由 nginx 容器托管 |
| API | Python 3.11 + FastAPI + Uvicorn | Pydantic v2 做全部 Schema 校验 |
| 任务队列 | Celery 5 + Redis | 成熟、支持优先级队列/重试/可见性 |
| PPT 渲染 | python-pptx | 唯一 PPTX 写入方 |
| PDF 解析 | PyMuPDF (fitz) | 文本/表格/图片提取 |
| DOCX 解析 | python-docx | 标题层级/表格/图片 |
| OCR | 当前未实现；无有效文本时返回 E2003 | OCR 配置字段保留，后续接入 |
| 图片处理 | Pillow | 裁剪/质量检查/文本测量 |
| 图表 | python-pptx 原生 Chart；复杂图 matplotlib→PNG 兜底 | 保证可编辑优先 |
| LLM | Qwen（DashScope OpenAI 兼容口）+ DeepSeek | openai sdk 统一接入 |
| Embedding | 当前未生成/检索 embedding；`DocChunk` 为模型骨架 | 后续接入专业模式 RAG |
| 数据库 | PostgreSQL 16（镜像含 pgvector） | 当前主要存元数据与 JSON，未接完整向量检索 |
| 对象存储 | MinIO（S3 协议），可切阿里云 OSS | boto3/s3 抽象层 |
| 文档转换 | Worker 镜像内 LibreOffice + 可选 unoserver | PPTX→PDF；PDF→PNG 用 PyMuPDF |
| 部署 | Docker Compose（V1）→ K8s（V2） | 全容器化 |
| 监控 | 结构化日志、任务/阶段/LLM 调用落库 | Prometheus/Grafana 尚未接入 Compose |

---

## 2. 工程目录

```text
ppt-generator/
├── frontend/                        # React 前端
│   ├── src/{pages,components,api,hooks,stores}/
│   ├── Dockerfile                   # 多阶段: node build → nginx
│   └── nginx.conf                   # 静态资源 + /api 反代 + SSE 配置
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── api/                     # 路由层（薄）
│   │   │   ├── templates.py  documents.py  jobs.py  events.py  admin.py
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings，全部环境变量
│   │   │   ├── logging.py           # 结构化日志(job_id/stage 贯穿)
│   │   │   ├── errors.py            # 错误码枚举 + 异常体系
│   │   │   └── metrics.py           # 规划：Prometheus 指标（当前未实现）
│   │   ├── models/                  # SQLAlchemy ORM（§8 表设计）
│   │   ├── schemas/                 # Pydantic：API DTO + Presentation JSON
│   │   ├── services/                # 业务服务（API 侧）
│   │   │   ├── job_service.py  upload_service.py  storage.py  progress.py
│   │   ├── pipeline/                # ★ 生成流水线（Worker 侧）
│   │   │   ├── orchestrator.py      # 状态机驱动 + 断点续跑
│   │   │   ├── stages/              # 每个阶段一个模块，统一 Stage 接口
│   │   │   │   ├── s01_validate.py  s02_parse_doc.py  s03_parse_template.py
│   │   │   │   ├── s04_knowledge.py s05_outline.py    s06_plan.py
│   │   │   │   ├── s07_content.py   s08_match.py      s09_render.py
│   │   │   │   ├── s10_qa.py        s11_repair.py     s12_publish.py
│   │   │   ├── modes/               # ★ 三模式流水线定义
│   │   │   │   ├── base.py  fast.py  standard.py  premium.py
│   │   │   ├── guards/              # Guard 层
│   │   │   │   ├── input_guard.py  template_guard.py  fact_guard.py
│   │   │   │   ├── outline_guard.py page_guard.py     content_guard.py
│   │   │   │   ├── layout_guard.py  render_guard.py
│   │   │   └── checkpoint.py        # 阶段产物存取（断点重试）
│   │   ├── parser/                  # pdf/docx/pptx/ocr 解析器
│   │   ├── ai/                      # LLM Gateway + Agents + prompts
│   │   │   ├── gateway.py           # 路由/重试/熔断/计量/JSON修复
│   │   │   ├── providers/           # qwen.py deepseek.py（openai兼容）
│   │   │   ├── agents/              # outline/content/planner/reviewer/repair
│   │   │   └── prompts/             # jinja2 模板，版本化
│   │   ├── ppt/                     # 渲染引擎
│   │   │   ├── renderer.py          # Presentation JSON → PPTX 总控
│   │   │   ├── layouts/             # 20 种版式 renderer
│   │   │   ├── text_engine.py       # 文本测量/自动缩排/溢出计算
│   │   │   ├── chart_builder.py  table_builder.py  shape_builder.py
│   │   │   ├── image_engine.py      # crop/contain/cover
│   │   │   └── fonts.py             # Font Resolver
│   │   ├── rag/                     # chunk/embedding/retrieve（专业模式）
│   │   └── worker.py                # Celery app + 任务定义
│   ├── alembic/                     # 数据库迁移
│   ├── tests/
│   ├── Dockerfile                   # api 与 worker 共用镜像，入口不同
│   └── requirements.txt
├── deploy/
│   ├── docker-compose.yml
│   ├── docker-compose.monitoring.yml # 规划文件，当前仓库未提供
│   ├── .env.example
│   └── init/                        # DB init、MinIO bucket 初始化、字体
├── templates/                       # 系统默认模板 + 系统标准版式库
└── docs/
```

---

## 3. 模块设计

### 3.1 模块清单与职责

| 模块 | 职责 | 关键约束 |
|---|---|---|
| Upload Service | 文件接收、类型嗅探、落 MinIO、触发预解析 | 白名单校验；解析失败即报错，禁止带病进入生成 |
| Document Parser | PDF/DOCX → 统一 Document IR（页/章节/段落/表格/图片） | 无有效文本时返回 E2003；扫描件 OCR 尚未接入 |
| Template Parser | 模板 .pptx → 版式清单（type+confidence）+ Design Token | 只读模板；置信度低于阈值走近似匹配/系统版式 |
| Knowledge Builder | Document IR → Knowledge Model（章节树/事实/数字/图表数据） | 关键数字全部进 Fact Registry |
| Fact Registry | 事实登记/等级/冲突检测 | 冲突不得自动取舍（专业模式弹交互） |
| Outline Agent | 知识模型 → 章节大纲 + 各章页数 | 输出过 OutlineGuard + Page Budget |
| Page Budget Engine | 目标页数 → 固定页/章节页/正文页预算；冲突检测 | 硬约束：总页数；预算不足触发用户决策 |
| Slide Planner | 大纲 → 页面级规划（每页 type/key_message/素材需求） | 一页一个核心观点 |
| Template Matcher | 页面规划 → 模板版式绑定 | 评分制（类型40/元素20/长度15/图片10/均衡15） |
| Content Agent | 每页规划 → 页面内容 JSON（标题/要点/图表数据/来源） | 输出过 ContentGuard（长度/字段/事实校验） |
| Layout Engine | 内容 → 元素几何布局；文本实测；溢出/重叠预判 | 只在版式定义的容器内摆放 |
| PPT Renderer | Presentation JSON → PPTX（python-pptx） | 确定性、无 LLM；单页失败不中断整册 |
| Convert Service | PPTX → PDF（本机 soffice/可选 unoserver）→ PNG（PyMuPDF） | 失败仅降级预览，不影响 PPTX 交付 |
| QA Service | 规则 QA（几何/密度/字数）+ Vision QA（专业模式） | 产出 Validation Report + 质量分 |
| Repair Agent | 按 QA issue 定向修复（改文案/换版式/调布局） | 每轮全程留痕；最多 3 轮 |
| Publisher | 产物上传、对象键登记、版本登记、清理临时文件 | 当前下载 API 主要走后端代理；自动留存清理未实现 |
| Progress Service | 阶段/页级进度发布（Redis Pub/Sub → SSE） | 事件幂等，带序号 |
| LLM Gateway | 路由/超时/重试/熔断/JSON 修复/token 计量 | 见 §3.3 |

### 3.2 Stage 统一接口（流水线可编排的基础）

```python
class StageResult(BaseModel):
    status: Literal["success", "warning", "failed"]
    output_key: str | None      # checkpoint 存储键（MinIO）
    warnings: list[Issue] = []
    metrics: dict = {}          # 阶段自定义指标

class Stage(Protocol):
    code: str                   # 如 "PARSE_DOC"
    def run(self, ctx: JobContext) -> StageResult: ...
```

- 每个 Stage：**幂等**（同输入重跑结果一致）、**可 checkpoint**（输出写 MinIO，键记录在 job_stages.output_key）、**自报耗时**（orchestrator 统一计时落库）；
- 三种模式 = 三份 Stage 编排定义（DAG），Orchestrator 只认 DAG，不认模式细节。

### 3.3 LLM Gateway 设计

```text
调用方(Agent) ──▶ Gateway.chat(task_type, messages, schema=None)
                    │
                    ├─ 1. 路由: task_type + mode → (provider, model)   # 配置化
                    ├─ 2. 限流: provider 级并发信号量 + RPM 令牌桶
                    ├─ 3. 调用: openai 兼容 SDK, 超时(默认60s, 长文120s)
                    ├─ 4. 校验: schema 非空时 → json.loads → Pydantic
                    │       失败 → JSON修复器(裁剪markdown围栏/尾逗号/单引号)
                    │       再失败 → 重试(最多2次, 第2次切换备用provider)
                    ├─ 5. 熔断: provider 连续5次失败 → OPEN 60s, 半开探测
                    └─ 6. 计量: llm_calls 落库(provider/model/tokens/耗时/结果)
```

路由表（配置文件，可热更）：

```yaml
routes:
  doc_summary:    { fast: qwen-flash,  standard: qwen-plus, premium: qwen-max,  fallback: deepseek-chat }
  outline:        { fast: qwen-plus,   standard: deepseek-chat, premium: deepseek-reasoner, fallback: qwen-plus }
  page_content:   { fast: qwen-flash,  standard: qwen-plus, premium: qwen-max,  fallback: deepseek-chat }
  json_strict:    { all: qwen-plus(json_mode), fallback: deepseek-chat }
  vision_qa:      { premium: qwen-vl-max, fallback: qwen-vl-plus }
  repair:         { standard: qwen-plus, premium: deepseek-reasoner, fallback: qwen-plus }
  embedding:      { all: text-embedding-v3, fallback: bge-m3(local) }
```

### 3.4 Presentation JSON（核心中间层 Schema 摘要）

AI 只产出/修改该 JSON；Renderer 只消费该 JSON。完整 Schema 用 Pydantic 定义并版本化（`schema_version`）。

```jsonc
{
  "schema_version": "1.0",
  "presentation": { "title": "...", "page_size": "16:9", "total_pages": 16, "mode": "fast", "density": "medium" },
  "theme": { "primary": "#1B3A6B", "font_title": "Microsoft YaHei", "font_body": "Microsoft YaHei", "tokens": {} },
  "slides": [
    {
      "page": 4,
      "chapter_id": "ch01",
      "type": "two_column",              // 只能取 20 种受控版式枚举
      "template_slide_id": 7,            // 绑定的模板版式; null=系统版式
      "title": "项目背景",               // ContentGuard 校验长度
      "subtitle": null,
      "key_message": "数字化转型势在必行",
      "elements": [
        { "type": "bullet_group", "items": ["...", "..."] },
        { "type": "chart", "chart_type": "bar", "title": "近三年项目数量",
          "unit": "个", "data": [{"label": "2024", "value": 82}, {"label": "2025", "value": 116}] },
        { "type": "image", "asset_id": "img_012", "fit": "cover" }
      ],
      "sources": [{ "document_id": "doc_001", "pages": [8, 9] }],
      "notes": "演讲者备注(可选, 附来源说明)"
    }
  ]
}
```

受控版式枚举（20 种）：`cover, toc, section, title_content, two_column, three_column, three_cards, four_cards, key_number, quote, timeline, process, architecture, comparison, table, bar_chart, line_chart, pie_chart, image_text, summary`。AI 输出枚举外类型直接拒绝（ContentGuard）。

---

## 4. 三模式流水线设计（核心）

### 4.0 企业模板视觉构图层（当前实现）

标准与专业模式的正文链路为：

```text
PLAN
  → ART_DIRECTION（继承模板字体/品牌色，生成整册艺术方向）
  → STORYBOARD（逐页 thesis / importance / focal / capacity）
  → CONTENT（按分镜容量收口，溢出支持材料进入 speaker_notes）
  → MATCH
  → COMPOSE（布局语法投影、安全区校验、整册重复度重平衡）
  → LAYOUT（写入 visual_plan / layout_recipe / speaker_notes）
  → [专业] KEY_SLIDE_DESIGN（受约束 SceneSpec，失败逐页回退）
  → RENDER
```

`PARSE_TPL` 的 `layout_meta.space_contract` 以英寸描述页面大小、正文安全区、12列网格、logo/页脚保护区。正文区域的所有 Box 必须分别通过 top/right/bottom/left 检查；文本按语义角色检查字号，正文最小 16pt，来源文字才允许 10–13pt。

构图选择不是随机模板轮换。候选按内容兼容 40、近期家族差异 25、模板空间适配 20、节奏贡献 15 评分，并以 `sha256(job_id:page:recipe_id)` 稳定打破平局。整册二次平衡限制单一家族占比不超过 30%（存在替代方案时），禁止相邻构图指纹重复及连续三页同焦点。

专业关键页数量为正文页的 `ceil(18%)`，最多 5 页；少于 8 个正文页时最多 1 页，同时满足一章一页、关键页不相邻。Agent 只接收冻结可见内容、内容哈希、模板 Token、空间契约及相邻指纹；SceneSpec 仅允许 text/shape/chart/table/connector。内容哈希、逐字文本、Token 或空间校验任一失败即重试，连续两次失败保留 COMPOSE 普通布局。

各模式差异：极速模式不进入上述新增阶段；标准模式启用 ART_DIRECTION/STORYBOARD/COMPOSE；专业模式再启用 KEY_SLIDE_DESIGN。因而极速调用量不变，标准/专业固定增加两次结构化调用，专业按关键页额外增加最多两次场景调用。

三种模式是**三个不同的 DAG 编排 + 不同的 Agent 策略 + 不同的 QA 深度**，共用同一批 Stage 实现与 Guard 层。

### 4.1 ⚡ 极速模式（fast，默认）

设计目标：**最少 LLM 调用次数 + 最大并行度**，10 页 20～40s。事实底线不降（关键数字规则校验仍在）。

```text
VALIDATE ─┬─ PARSE_DOC ──┐
          └─ PARSE_TPL ──┤            ← 文档与模板解析并行
                         ▼
              KNOWLEDGE_LITE          ← 规则抽取章节树+关键数字, 无深度建模
                         ▼
              OUTLINE_PLAN_COMBO      ← ★1次LLM调用同时产出: 大纲+页数分配+逐页规划
                         ▼            (PageGuard 校验预算, 不合法自动修正一次)
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         CONTENT(ch1) CONTENT(ch2) CONTENT(ch3)   ← ★章节级批量生成:
              │          │          │               1章1次LLM调用产出整章N页JSON,
              └──────────┼──────────┘               章节间并行(Celery group)
                         ▼
              MATCH_RULE              ← 规则直配版式(类型查表), 无打分
                         ▼
              RENDER                  ← python-pptx, 单进程整册渲染
                         ▼
              QA_RULE                 ← 仅确定性检查: 字数预算/溢出估算/几何重叠
                         ▼            超限 → 确定性修复(截断改写规则/换高容量版式), 0轮LLM
              PUBLISH ── 缩略图异步   ← PPTX先交付, PDF/PNG转换异步补齐
```

LLM 调用预算（10 页 / 3 章）：摘要 0（规则）+ 大纲规划 1 + 章节内容 3 + JSON 修复预留 ≈ **4～5 次**。

关键取舍：

- 不做 Fact Registry 全量建模，但保留"数字回查"：Content 输出中的数字用正则回查原文，查不到即从该页移除并降级为定性表述（Info 记录）；
- 数据冲突默认策略"取最新来源"，不弹交互；
- Vision QA 关闭；PDF/PNG 转换移出主链路（异步），PPTX 就绪即标记成功。

### 4.2 🚀 标准模式（standard）

设计目标：质量与速度平衡，10 页 40～90s。

```text
VALIDATE ─┬─ PARSE_DOC ──┐
          └─ PARSE_TPL ──┤
                         ▼
              KNOWLEDGE               ← 1次LLM结构化建模(章节摘要+要点+图表数据)
                         ▼              + 关键事实抽取比对
              OUTLINE                 ← 独立 Outline Agent + OutlineGuard
                         ▼
              PAGE_BUDGET → PLAN      ← 预算引擎 + Slide Planner(1次LLM)
                         ▼
         ┌────┬────┬────┬────┐
         ▼    ▼    ▼    ▼    ▼
       CONTENT(p1..pN 页级并行)        ← ★页级并行, 并发信号量(默认8),
         └────┴────┴────┴────┘          单页失败重试1次后降级要点页
                         ▼
              MATCH_SCORE             ← 打分匹配(类型40/元素20/长度15/图片10/均衡15)
                         ▼
              LAYOUT                  ← Pillow 实测文本尺寸, 预判溢出/重叠
                         ▼
              RENDER → BEAUTIFY       ← 视觉优化闭环≤2轮(九维评分→Fix Ops→重渲染, 见04文档)
                         ▼
              CONVERT                 ← PPTX→PDF→PNG 进主链路(预览完整)
                         ▼
              QA_RULE+MEASURE         ← 规则+度量QA, 产出 issue 列表
                         ▼
              REPAIR(≤1轮)            ← 仅对 issue 页定向重生成/换版式
                         ▼
              PUBLISH + REPORT
```

LLM 调用预算（10 页）：建模 1 + 大纲 1 + 规划 1 + 页内容 10 + 修复 ≤2 ≈ **13～15 次**（页级并行，墙钟时间≈最慢单页）。

### 4.3 💎 专业模式（premium）

设计目标：可对外交付质量，10 页 1～3min，事实全链路管控。

```text
VALIDATE ─┬─ PARSE_DOC（扫描件当前直接返回 E2003） ──┐
          └─ PARSE_TPL ────────┤
                               ▼
              KNOWLEDGE_DEEP            ← 深度建模 + Fact Registry(等级A~D)
                               ▼          + Chunk/Embedding（规划；当前仅模型骨架）
              FACT_CONFLICT_CHECK       ← 冲突 → 发布 decision_required 事件,
                               ▼          job → WAITING_USER (超时按默认策略)
              OUTLINE(+可选用户确认)     ← deepseek-reasoner; 可配置暂停供用户改大纲
                               ▼
              PAGE_BUDGET → PLAN        ← 含叙事线检查(问题→方案→架构→实施→效果)
                               ▼
         ┌────┬────┬────┬────┐
         ▼    ▼    ▼    ▼    ▼
       CONTENT(页级并行 + RAG逐页取证)   ← 规划能力；当前实现按已解析 IR/事实生成，
         └────┴────┴────┴────┘            尚未执行向量 TopK 检索
                               ▼
              FACT_GUARD                ← 页面数字逐一回查 Fact Registry,
                               ▼          等级C标注/等级D剔除
              MATCH_SCORE + LAYOUT      ← 同标准模式, 增加密度自适应换版
                               ▼
              RENDER → BEAUTIFY         ← 规则闭环≤2轮 + Vision Critic 1轮(见04文档)
                               ▼
              CONVERT(PDF/PNG)
                               ▼
              QA_FULL                   ← 规则+度量+Vision QA(qwen-vl-max,
                               ▼          整册截图批量审: 溢出/拥挤/空洞/风格一致性)
              REPAIR LOOP(≤3轮)         ← issue→定向修复→重渲染→复检,
                               ▼          每轮质量分须上升, 否则提前终止取最优版本
              PUBLISH + REPORT + 来源清单
```

LLM 调用预算（10 页）：建模 2 + 大纲 1 + 规划 1 + 页内容 10 + Vision 2～3 + 修复 3～9 + 检索嵌入若干 ≈ **25～35 次**。

### 4.3.1 相邻页连续性检查（标准/专业）

QA 阶段追加：标题重复、核心观点重复、数据重复检测；专业模式额外校验故事线完整性（问题→原因→方案→架构→实施→效果）。

### 4.4 模式对比落地摘要

| 决策点 | fast | standard | premium |
|---|---|---|---|
| 内容生成粒度 | 章节批量（1 章 1 调用） | 页级并行 | 页级并行 + RAG |
| PDF/PNG 转换 | 异步（不阻塞成功） | 主链路 | 主链路 |
| 修复轮次 | 0（仅确定性修复） | ≤1 | ≤3 |
| 事实冲突 | 默认策略+留痕 | 默认策略+报告提示 | 用户决策交互 |
| 用户中断点 | 无 | 无 | 冲突/大纲确认（可配） |
| 成功判定 | PPTX 就绪 | PPTX+预览+报告 | PPTX+预览+报告+来源清单 |

---

## 5. 流程设计

### 5.1 任务全流程时序

```text
用户            前端              API             Redis          Worker（内置 LibreOffice） MinIO
 │  上传模板/文档  │                │                                │
 │───────────────▶│──POST files──▶│──────────────────────────────────────────────────────────▶ 存原始文件
 │                │               │  (预解析任务入队) ──▶ 预解析(轻量) ─▶ 解析摘要落库
 │  提交生成       │               │
 │───────────────▶│──POST jobs──▶ │ 建Job(pending) ─▶ LPUSH 任务
 │                │◀─ job_id ─────│
 │                │──GET events(SSE)──▶ 订阅 progress:{job_id}
 │                │               │                │◀─ BRPOP ──────│
 │                │               │                │   执行DAG(见§4) ── 各阶段产物/checkpoint ──▶ 存中间产物
 │                │◀═ stage_update/page_done 事件流(经Redis Pub/Sub→SSE) ═══│
 │                │               │                │               │──PPTX──▶ 转PDF ──▶ PNG
 │                │◀═ thumbnail_ready ═════════════════════════════│                    ──▶ 存产物
 │                │◀═ job_done(quality_score) ═════════════════════│
 │  预览/下载      │──GET output──▶│ 后端代理读取对象 ────────────────────────────────▶ 返回文件流
```

### 5.2 断点重试流程

```text
Job失败(failed, failed_stage=RENDER)
 │  用户点击[断点重试]
 ▼
POST /jobs/{id}/retry {strategy:"resume"}
 │
 ▼
Orchestrator:
  1. 读 job_stages, 找到全部 success 阶段及其 output_key
  2. 校验 checkpoint 完整性(MinIO 对象存在 + schema_version 兼容)
     └ 不完整 → 自动降级为最近可用阶段重跑
  3. 从 failed_stage 起重建 DAG 子图执行
  4. retry_count+1, 每次尝试的 stage 记录 attempt 序号(历史保留)
```

策略枚举：`resume`（断点，默认）/ `restart`（从头，新 Job + parent_job_id 版本链）/ `restart_with_input`（更换输入后从头）。

### 5.3 并行拓扑与汇聚规则

- 章节/页面并行用 Celery `group + chord`：chord 回调做汇聚校验（数量齐全、页码连续、无重复）；
- 单分支失败：重试 1 次 → 仍失败则产出"降级页"（大纲要点版式）并打 Warning，**不阻塞 chord 汇聚**；
- 并发上限：全局 LLM 并发信号量（默认 8/provider），防止把 Provider 限流打爆反而变慢；
- 超时控制：单页内容 90s、章节批量 180s、整任务硬超时（fast 5min / standard 15min / premium 30min），超时按失败处理并可断点重试。

---

## 6. 状态设计

### 6.1 Job 状态机

```text
                    ┌────────────────────────────────────────┐
                    ▼                                        │
 PENDING ──▶ RUNNING ──▶ SUCCEEDED                           │
   │            │  ▲                                         │
   │            │  └──────── WAITING_USER ◀──(决策事件)───────┤
   │            │                │  (用户选择/超时默认策略)     │
   │            ├────────────────┘                           │
   │            ├──▶ FAILED ──(retry:resume)─────────────────┘
   │            │       │
   │            │       └──(retry:restart)──▶ 新Job(parent_job_id=本Job)
   │            └──▶ CANCELED
   └──▶ CANCELED (排队中取消)
```

| 状态 | 含义 | 允许迁出 |
|---|---|---|
| PENDING | 已入队未执行 | RUNNING / CANCELED |
| RUNNING | 执行中（current_stage 标识细分阶段） | WAITING_USER / SUCCEEDED / FAILED / CANCELED |
| WAITING_USER | 等待用户决策（冲突/预算/内容不足） | RUNNING（决策后）/ FAILED（超时且无默认策略）/ CANCELED |
| SUCCEEDED | 成功（产物齐备） | 终态（可派生新 Job） |
| FAILED | 失败（error_code 必填） | RUNNING（断点重试）/ 终态 |
| CANCELED | 用户取消 | 终态 |

### 6.2 Stage 状态与编码

Stage 状态：`pending → running → success | warning | failed | skipped`。

| stage_code | 名称 | fast | standard | premium |
|---|---|:-:|:-:|:-:|
| VALIDATE | 输入校验 | ✓ | ✓ | ✓ |
| PARSE_DOC | 文档解析（OCR 未接入；无有效文本返回 E2003） | ✓ | ✓ | ✓ |
| PARSE_TPL | 模板解析 | ✓ | ✓ | ✓ |
| KNOWLEDGE | 内容理解/知识建模 | 轻量 | ✓ | 深度+RAG |
| FACT_CHECK | 事实登记与冲突检测 | 规则 | ✓ | ✓(交互) |
| OUTLINE | 大纲生成 | 合并 | ✓ | ✓ |
| PLAN | 页面规划（含 Page Budget） | 合并 | ✓ | ✓ |
| CONTENT | 页面内容生成 | 章节并行 | 页并行 | 页并行+RAG |
| MATCH | 模板匹配 | 规则 | 打分 | 打分+自适应 |
| LAYOUT | 布局计算 | 简化 | ✓ | ✓ |
| RENDER | PPTX 渲染 | ✓ | ✓ | ✓ |
| BEAUTIFY | 视觉优化闭环（[04 文档](04-VISUAL-OPTIMIZATION.md)） | skipped（QA 一次性出分） | ≤2 轮 | ≤2 轮 + Vision Critic |
| CONVERT | PDF/PNG 转换 | 异步 | ✓ | ✓ |
| QA | 质量检查 | 规则 | 规则+度量 | +Vision |
| REPAIR | 自动修复 | skipped | ≤1轮 | ≤3轮 |
| PUBLISH | 上传归档 | ✓ | ✓ | ✓ |

### 6.3 错误码体系

格式：`E{类别1位}{序号3位}`；Job 失败必带一个 Blocker 级错误码。

| 段 | 类别 | 示例 |
|---|---|---|
| E1xxx | 输入类 | E1001 文件类型不支持；E1002 文件超限；E1003 文件损坏/加密；E1004 页数超出 5~100 |
| E2xxx | 解析类 | E2001 PDF 解析失败；E2002 DOCX 解析失败；E2003 无有效文本且 OCR 失败；E2004 模板解析失败；E2005 模板无可用版式 |
| E3xxx | AI 类 | E3001 所有 Provider 不可用；E3002 JSON 反复非法；E3003 大纲不满足页数硬约束；E3004 内容生成整体失败；E3005 触发 Provider 内容安全拦截 |
| E4xxx | 渲染类 | E4001 PPTX 渲染失败；E4002 字体解析失败；E4003 图表构建失败(整册级) |
| E5xxx | 质检修复类 | E5001 修复后仍存在 Blocker 级布局错误 |
| E6xxx | 存储类 | E6001 对象存储不可用；E6002 上传失败；E6003 转换服务不可用(仅Warning级降级) |
| E7xxx | 系统类 | E7001 任务超时；E7002 Worker 异常退出；E7003 队列/依赖服务故障；E7004 用户决策超时且无默认策略 |

每个错误码在 `errors.py` 登记：`{code, blocker|warning|info, user_message 模板, suggestion 模板, retryable: resume|restart_with_input|no}` —— 前端据 `retryable` 决定主按钮形态。

### 6.4 进度事件协议（Redis Pub/Sub → SSE）

```jsonc
// channel: progress:{job_id}   事件均带自增 seq, 前端按 seq 去重排序
{ "seq": 12, "event": "stage_update", "stage": "CONTENT", "status": "running",
  "progress": {"done": 6, "total": 16}, "elapsed_ms": 12480, "ts": "..." }
{ "seq": 13, "event": "page_done", "page": 7, "content_card": { "title": "...", "bullets": ["..."] } }
{ "seq": 21, "event": "thumbnail_ready", "page": 7, "url": "/api/v1/jobs/{id}/pages/7/thumb" }
{ "seq": 30, "event": "decision_required", "decision_id": "dc_01", "kind": "fact_conflict",
  "payload": {...}, "deadline_ts": "...", "default_choice": "latest" }
{ "seq": 40, "event": "job_done", "quality_score": 88 }
{ "seq": 40, "event": "job_failed", "error_code": "E2003", "failed_stage": "PARSE_DOC" }
```

---

## 7. API 设计

Base：`/api/v1`；当前无登录鉴权（CORS 全开放，`user_id` 仅预留）；所有业务响应 `{code, message, data}` 包裹。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /templates | 上传模板（multipart），返回 template_id，异步解析 |
| GET | /templates | 模板列表（含解析状态/版式摘要） |
| GET | /templates/{id} | 模板详情（版式清单/Design Token/缩略图） |
| DELETE | /templates/{id} | 删除模板 |
| POST | /documents | 上传主文档，返回 document_id，异步预解析 |
| GET | /documents/{id} | 解析摘要（字数/章节/建议页数/是否扫描件） |
| POST | /jobs | 创建生成任务 `{template_id, document_id, pages, mode, density, options?}` → `{job_id}` |
| GET | /jobs | 任务列表（分页/筛选：status, mode, date） |
| GET | /jobs/{id} | 任务详情：状态、阶段列表（含起止/耗时/attempt）、错误信息、质量分 |
| GET | /jobs/{id}/events | SSE 进度流（支持 Last-Event-ID 续传） |
| POST | /jobs/{id}/cancel | 取消任务 |
| POST | /jobs/{id}/retry | `{strategy: resume|restart|restart_with_input, document_id?, template_id?}` |
| POST | /jobs/{id}/beautify | 历史任务一键美化：fork 子版本 Job 复用内容成果，只重跑 RENDER→BEAUTIFY→CONVERT→QA→PUBLISH |
| POST | /jobs/{id}/decisions/{decision_id} | 提交用户决策（冲突选择/预算方案/内容不足选项） |
| GET | /jobs/{id}/slides | 页面清单（内容卡片+缩略图 URL+来源） |
| GET | /jobs/{id}/output | 产物下载地址（指向后端代理 `/download/{kind}`） |
| GET | /jobs/{id}/pages/{n}/image | 单页大图（后端代理读取 PNG） |
| GET | /jobs/{id}/report | 质检报告 JSON |
| GET | /jobs/{id}/versions | 版本链（parent/child Job 列表） |
| POST | /beautify | 独立 PPTX 美化：同步评分、确定性微调并保存结果 |
| GET | /beautify | 独立美化记录列表 |
| GET | /beautify/{id}/download | 独立美化产物下载（后端代理） |
| GET | /pptmaster/options | ppt-master 入参、Agent 探测和仓库状态 |
| POST/GET | /pptmaster/jobs | ppt-master 异步提交与列表 |
| GET/POST/DELETE | /pptmaster/jobs/{id}/* | 详情、取消、删除、产物/预览/日志 |
| GET | /admin/stats | 后端聚合统计接口（当前无管理端页面） |
| GET | /healthz, /readyz | 健康检查（DB/Redis/MinIO；转换状态可能为 `degraded`） |

---

## 8. 表设计（PostgreSQL 16）

以下 SQL 是字段语义设计稿；运行时以 `backend/app/models/models.py` 为准，应用启动通过 SQLAlchemy `create_all` 幂等建表，并用 `ADD COLUMN IF NOT EXISTS` 补充视觉字段，当前未接 Alembic。当前 ORM 共 15 张表：`templates`、`template_slides`、`documents`、`generation_jobs`、`job_stages`、`job_slides`、`facts`、`fact_conflicts`、`job_decisions`、`llm_calls`、`validation_reports`、`job_events`、`doc_chunks`、`beautify_records`、`pptmaster_jobs`。

约定：主键 `id BIGSERIAL`；对外暴露 `biz_id`（如 `ppt_20260813_00128`）；时间一律 `TIMESTAMPTZ`；软删 `deleted_at`；主要业务表含 `created_at/updated_at`。

### 8.1 templates — 模板

```sql
CREATE TABLE templates (
  id            BIGSERIAL PRIMARY KEY,
  biz_id        VARCHAR(32) UNIQUE NOT NULL,
  user_id       BIGINT,                          -- V1 可空(单租户), 预留
  name          VARCHAR(128) NOT NULL,
  file_key      VARCHAR(512) NOT NULL,           -- MinIO 对象键
  file_size     BIGINT NOT NULL,
  status        VARCHAR(16) NOT NULL DEFAULT 'parsing',  -- parsing|ready|failed
  is_system     BOOLEAN NOT NULL DEFAULT FALSE,
  slide_count   INT,
  design_tokens JSONB,                           -- 主色/字体/字号/间距
  parse_error   VARCHAR(64),                     -- 错误码
  thumbnail_key VARCHAR(512),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ
);
CREATE INDEX idx_templates_status ON templates(status) WHERE deleted_at IS NULL;
```

### 8.2 template_slides — 模板版式页

```sql
CREATE TABLE template_slides (
  id           BIGSERIAL PRIMARY KEY,
  template_id  BIGINT NOT NULL REFERENCES templates(id),
  slide_index  INT NOT NULL,                     -- 模板内页序(0基)
  slide_type   VARCHAR(32) NOT NULL,             -- 20种受控枚举 | unknown
  confidence   NUMERIC(4,3) NOT NULL,            -- 识别置信度 0~1
  layout_meta  JSONB NOT NULL,                   -- 容器几何/占位符/max_chars
  capacity     JSONB,                            -- 文字容量/元素容量估算
  thumbnail_key VARCHAR(512),
  UNIQUE(template_id, slide_index)
);
CREATE INDEX idx_tpl_slides_type ON template_slides(template_id, slide_type);
```

### 8.3 documents — 主说明文档

```sql
CREATE TABLE documents (
  id            BIGSERIAL PRIMARY KEY,
  biz_id        VARCHAR(32) UNIQUE NOT NULL,
  user_id       BIGINT,
  name          VARCHAR(256) NOT NULL,
  file_key      VARCHAR(512) NOT NULL,
  file_type     VARCHAR(8) NOT NULL,             -- pdf|docx
  file_size     BIGINT NOT NULL,
  page_count    INT,
  char_count    INT,
  table_count   INT,
  image_count   INT,
  is_scanned    BOOLEAN DEFAULT FALSE,           -- 扫描件标记（当前不自动 OCR）
  parse_status  VARCHAR(16) NOT NULL DEFAULT 'parsing', -- parsing|ready|failed
  parse_error   VARCHAR(64),
  ir_key        VARCHAR(512),                    -- Document IR 在 MinIO 的键
  suggest_pages INT4RANGE,                       -- 建议页数区间
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at    TIMESTAMPTZ
);
```

### 8.4 generation_jobs — 生成任务（核心表）

```sql
CREATE TABLE generation_jobs (
  id             BIGSERIAL PRIMARY KEY,
  biz_id         VARCHAR(32) UNIQUE NOT NULL,    -- ppt_YYYYMMDD_NNNNN
  user_id        BIGINT,
  template_id    BIGINT NOT NULL REFERENCES templates(id),
  document_id    BIGINT NOT NULL REFERENCES documents(id),
  target_pages   INT NOT NULL CHECK (target_pages BETWEEN 5 AND 100),
  mode           VARCHAR(16) NOT NULL DEFAULT 'fast',    -- fast|standard|premium
  density        VARCHAR(16) NOT NULL DEFAULT 'medium',  -- low|medium|high
  options        JSONB NOT NULL DEFAULT '{}',    -- 高级选项(汇报对象/风格要求等)
  status         VARCHAR(16) NOT NULL DEFAULT 'pending',
                 -- pending|running|waiting_user|succeeded|failed|canceled
  current_stage  VARCHAR(24),                    -- 冗余最新阶段, 便于列表查询
  progress       SMALLINT NOT NULL DEFAULT 0,    -- 0~100
  -- 失败信息
  error_code     VARCHAR(8),
  error_message  TEXT,
  failed_stage   VARCHAR(24),
  retry_count    SMALLINT NOT NULL DEFAULT 0,
  parent_job_id  BIGINT REFERENCES generation_jobs(id),  -- restart 版本链
  version_no     SMALLINT NOT NULL DEFAULT 1,
  -- 产物
  pptx_key       VARCHAR(512),
  pdf_key        VARCHAR(512),
  report_key     VARCHAR(512),
  pjson_key      VARCHAR(512),                   -- 最终 Presentation JSON
  actual_pages   INT,
  quality_score  SMALLINT,                       -- 0~100（生成质量分：对不对）
  visual_score   SMALLINT,                       -- 0~100（视觉分：好不好看，九维规则引擎）
  -- 全链路时间(FR-9)
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 提交时间
  started_at     TIMESTAMPTZ,                    -- Worker 开始执行
  finished_at    TIMESTAMPTZ,
  queue_ms       INT,                            -- started-created
  duration_ms    INT,                            -- finished-started
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at     TIMESTAMPTZ
);
CREATE INDEX idx_jobs_status_created ON generation_jobs(status, created_at DESC);
CREATE INDEX idx_jobs_user ON generation_jobs(user_id, created_at DESC);
```

### 8.5 job_stages — 阶段执行记录（FR-9 核心）

```sql
CREATE TABLE job_stages (
  id           BIGSERIAL PRIMARY KEY,
  job_id       BIGINT NOT NULL REFERENCES generation_jobs(id),
  stage_code   VARCHAR(24) NOT NULL,             -- §6.2 枚举
  seq          SMALLINT NOT NULL,                -- DAG 内顺序号
  attempt      SMALLINT NOT NULL DEFAULT 1,      -- 第几次尝试(断点重试递增)
  status       VARCHAR(12) NOT NULL,             -- pending|running|success|warning|failed|skipped
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ,
  duration_ms  INT,
  error_code   VARCHAR(8),
  error_message TEXT,
  output_key   VARCHAR(512),                     -- checkpoint 对象键(断点重试用)
  meta         JSONB NOT NULL DEFAULT '{}',      -- 阶段指标: 并行分支耗时/token/兜底记录
  UNIQUE(job_id, stage_code, attempt)
);
CREATE INDEX idx_stages_job ON job_stages(job_id, seq, attempt);
```

> 并行阶段（CONTENT）的分支耗时写入 `meta.branches: [{key:"ch1", pages:[3,4,5], duration_ms:12100, status:"success"}]`，阶段本身的 duration 为汇聚墙钟时间。

### 8.6 job_slides — 页面级数据

```sql
CREATE TABLE job_slides (
  id                BIGSERIAL PRIMARY KEY,
  job_id            BIGINT NOT NULL REFERENCES generation_jobs(id),
  page_no           INT NOT NULL,
  chapter_id        VARCHAR(16),
  slide_type        VARCHAR(32) NOT NULL,
  template_slide_id BIGINT REFERENCES template_slides(id),  -- null=系统版式
  plan              JSONB,                       -- 规划(key_message/素材需求)
  content           JSONB,                       -- 页面内容 JSON
  sources           JSONB,                       -- [{document_id, pages:[..]}]
  status            VARCHAR(16) NOT NULL DEFAULT 'pending',
                    -- pending|generated|rendered|degraded|failed
  degrade_reason    VARCHAR(64),                 -- 降级原因(要点页/占位页)
  qa_issues         JSONB,                       -- 该页 QA 问题与修复记录
  visual_score      SMALLINT,                    -- 页级视觉分
  image_key         VARCHAR(512),                -- 大图 PNG
  thumb_key         VARCHAR(512),                -- 缩略图
  gen_duration_ms   INT,
  UNIQUE(job_id, page_no)
);
```

### 8.7 facts / fact_conflicts — 事实与冲突

```sql
CREATE TABLE facts (
  id           BIGSERIAL PRIMARY KEY,
  document_id  BIGINT NOT NULL REFERENCES documents(id),
  job_id       BIGINT REFERENCES generation_jobs(id),   -- 冗余, 便于按任务查
  fact_key     VARCHAR(128) NOT NULL,            -- 归一键: 如 "项目投资金额"
  content      TEXT NOT NULL,                    -- "1.2亿元"
  value_norm   NUMERIC,                          -- 归一化数值(单位统一后)
  unit         VARCHAR(16),
  source_page  INT NOT NULL,
  grade        CHAR(1) NOT NULL CHECK (grade IN ('A','B','C','D')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_facts_doc_key ON facts(document_id, fact_key);

CREATE TABLE fact_conflicts (
  id           BIGSERIAL PRIMARY KEY,
  job_id       BIGINT NOT NULL REFERENCES generation_jobs(id),
  fact_key     VARCHAR(128) NOT NULL,
  candidates   JSONB NOT NULL,                   -- [{fact_id, content, page}]
  status       VARCHAR(16) NOT NULL DEFAULT 'open',  -- open|resolved|expired
  resolution   VARCHAR(16),                      -- user_choice|default_latest|discard
  chosen_fact_id BIGINT REFERENCES facts(id),
  resolved_by  VARCHAR(16),                      -- user|system
  resolved_at  TIMESTAMPTZ
);
```

### 8.8 job_decisions — 用户决策（冲突/预算/内容不足）

```sql
CREATE TABLE job_decisions (
  id           BIGSERIAL PRIMARY KEY,
  job_id       BIGINT NOT NULL REFERENCES generation_jobs(id),
  decision_id  VARCHAR(32) NOT NULL,
  kind         VARCHAR(24) NOT NULL,   -- fact_conflict|page_budget|content_shortage
  payload      JSONB NOT NULL,         -- 选项与上下文
  default_choice VARCHAR(64),
  deadline_at  TIMESTAMPTZ NOT NULL,
  status       VARCHAR(16) NOT NULL DEFAULT 'open', -- open|answered|defaulted
  answer       JSONB,
  answered_at  TIMESTAMPTZ,
  UNIQUE(job_id, decision_id)
);
```

### 8.9 llm_calls — LLM 调用计量

```sql
CREATE TABLE llm_calls (
  id           BIGSERIAL PRIMARY KEY,
  job_id       BIGINT REFERENCES generation_jobs(id),
  stage_code   VARCHAR(24),
  task_type    VARCHAR(24) NOT NULL,             -- outline|page_content|vision_qa...
  provider     VARCHAR(16) NOT NULL,             -- qwen|deepseek
  model        VARCHAR(48) NOT NULL,
  prompt_tokens INT, completion_tokens INT,
  duration_ms  INT NOT NULL,
  status       VARCHAR(12) NOT NULL,             -- success|failed|fallback
  error_type   VARCHAR(32),                      -- timeout|rate_limit|bad_json|...
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_job ON llm_calls(job_id);
CREATE INDEX idx_llm_stat ON llm_calls(provider, model, created_at);
```

### 8.10 validation_reports / job_events / doc_chunks

```sql
CREATE TABLE validation_reports (
  id         BIGSERIAL PRIMARY KEY,
  job_id     BIGINT NOT NULL REFERENCES generation_jobs(id),
  round      SMALLINT NOT NULL DEFAULT 1,        -- 修复轮次(每轮一份)
  status     VARCHAR(12) NOT NULL,               -- pass|warning|fail
  score      SMALLINT,
  errors     SMALLINT NOT NULL DEFAULT 0,
  warnings   SMALLINT NOT NULL DEFAULT 0,
  report     JSONB NOT NULL,                     -- 分项检查明细(§10)
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(job_id, round)
);

CREATE TABLE job_events (                        -- 追加型事件流水(审计/回放)
  id        BIGSERIAL PRIMARY KEY,
  job_id    BIGINT NOT NULL REFERENCES generation_jobs(id),
  seq       INT NOT NULL,
  event     VARCHAR(24) NOT NULL,
  payload   JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(job_id, seq)
);

CREATE TABLE doc_chunks (                        -- RAG 数据骨架，当前未接 pgvector
  id          BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES documents(id),
  chunk_index INT NOT NULL,
  content     TEXT NOT NULL,
  source_pages INT[] NOT NULL,
  embedding   JSONB,                             -- 当前以 JSON 数组保存，Python 内检索
  UNIQUE(document_id, chunk_index)
);
```

`beautify_records` 保存独立 PPTX 美化的源文件、产物和九维报告；`pptmaster_jobs` 保存 ppt-master 的输入快照、运行日志、产物数组、预览列表和 Agent 用量。二者均已在 ORM 中实现，设计稿 SQL 略去重复字段。

### 8.11 ER 关系摘要

```text
templates 1──n template_slides
documents 1──n doc_chunks, 1──n facts
generation_jobs n──1 templates, n──1 documents, 1──n job_stages,
                1──n job_slides, 1──n llm_calls, 1──n validation_reports,
                1──n job_decisions, 1──n job_events, 1──n fact_conflicts,
                自关联 parent_job_id (版本链)
job_slides n──1 template_slides
```

---

## 9. 存储与预览设计

### 9.1 MinIO Bucket 结构

```text
ppt-gen/
├── uploads/{yyyymm}/{doc_biz_id}.pdf|docx          # 原始文档
├── templates/{tpl_biz_id}/source.pptx              # 模板与版式缩略图
│   └── slides/{index}.png
├── parsed/{doc_biz_id}/ir.json                     # Document IR / chunks
├── jobs/{job_biz_id}/
│   ├── checkpoints/{stage_code}.{attempt}.json     # 阶段产物(断点重试)
│   ├── presentation.json                           # 最终中间层
│   ├── final.pptx                                  # ★ 交付物
│   ├── preview.pdf
│   ├── pages/page-{n}.png                          # 大图(1600×900)
│   ├── thumbs/page-{n}.png                         # 缩略图(320×180)
│   └── report.json                                 # 质检报告
```

### 9.2 存储抽象与 OSS 切换

```python
class ObjectStorage(Protocol):
    def put(self, key, data, content_type): ...
    def presign_get(self, key, expires=3600) -> str: ...  # 保留能力，当前下载主要不走它
    def exists(self, key) -> bool: ...
# 实现: MinIOStorage / AliyunOSSStorage(S3兼容, 仅endpoint/签名差异)
# 通过 STORAGE_BACKEND=minio|oss 环境变量切换, 业务代码零改动
```

### 9.3 在线预览

- 预览走**逐页 PNG/SVG**：主流水线由 Worker 内置 LibreOffice 转 PDF，再由 PyMuPDF 输出页面图；ppt-master 优先使用 SVG 页面，若镜像内可转换则补充 PNG；
- 下载和预览当前由 API 读取 MinIO 后端代理返回，`S3_PUBLIC_ENDPOINT` 主要用于兼容预签名/外部部署场景，不应在文档中假定浏览器直连 MinIO；
- 转换链：`final.pptx → soffice（Worker 内进程）→ preview.pdf → PyMuPDF → pages/thumbs`；`CONVERT_BACKEND=none` 时保留 PPTX 但预览降级；
- fast 模式仍按主流水线实现决定是否异步补齐预览，具体以任务事件和 `pdf_key` 是否存在为准。

---

## 10. 质量检查与自动修复

### 10.1 规则 QA（全模式）

| 检查项 | 方法 | 超限动作 |
|---|---|---|
| 页数硬约束 | actual == target | Blocker（重平衡后仍不符则失败） |
| 文本溢出 | text_engine 按字体实测（Pillow.ImageFont.getbbox） | 压缩→换版式→拆页 |
| 元素重叠 | 矩形碰撞检测（title/body/image/chart/footer） | 调位置→换版式 |
| 页面密度 | Density Score = f(文字面积, 元素数, 字号, 图表数)，0~100 | <30 过空提示换版式；>85 严重拥挤必须处理 |
| 字号下限 | 正文 ≥12pt，标题 ≥18pt | 禁止继续缩字，改走拆页 |
| 数字回查 | 页面数字 ↔ facts/原文正则回查 | 查不到→移除该数字并降级定性表述（Info） |
| 图表数据 | null/空数组/单位混用/分母0/极端值 | 清洗→降级表格→降级要点 |
| 相邻页重复 | 标题/要点/数据 simhash 相似度 | 触发该页重生成（标准+） |

### 10.2 Vision QA（专业模式）

- 整册 PNG 分批（每批 ≤6 页）送 qwen-vl-max，检查：标题突出性、拥挤/空洞、图表清晰度、视觉层级、模板风格一致性、明显遮挡错位；
- 输出结构化 issue：`{page, issue_type, severity, suggestion}`，与规则 QA 合并去重后进入修复；
- Vision 不可用时自动降级为"规则+度量 QA"并打 Warning（E6003 同类降级思路）。

### 10.3 修复闭环

```text
issues → 分派: 布局类→Layout Engine(确定性) / 文案类→Repair Agent(LLM定向改写)
      → 仅重渲染受影响页 → 复检该页 → 质量分重算
终止条件: 无 Blocker issue | 达到轮次上限(标准1/专业3) | 质量分不再上升(取历史最优版本)
```

### 10.4 质量分

| 维度 | 权重 | 来源 |
|---|---:|---|
| 内容准确性 | 25 | FactGuard 通过率 |
| 内容简洁性 | 15 | 文案预算达标率 |
| 视觉平衡 | 15 | Density Score 分布 |
| 模板一致性 | 15 | 模板版式命中率/兜底率 |
| 信息层级 | 15 | 规则+Vision 层级检查 |
| 数据表达 | 10 | 图表构建成功率/清洗记录 |
| 可读性 | 5 | 字号/行数达标率 |

---

## 11. 容器化部署

### 11.1 当前 `deploy/docker-compose.yml`

```yaml
name: ppt-generator
services:
  frontend:
    build: ../frontend
    ports: ["8081:80"]
    depends_on: {api: {condition: service_healthy}}

  api:
    build: {context: ../backend, target: api}
    ports: ["8000:8000"]
    env_file: .env
    environment: {PPTMASTER_EXECUTION_SCOPE: worker}
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      minio: {condition: service_healthy}
    healthcheck: {test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"], interval: 10s, timeout: 5s, retries: 6, start_period: 20s}

  worker:
    build: {context: ../backend, target: worker}
    env_file: .env
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      minio: {condition: service_healthy}

  pptmaster-worker:
    build: {context: ../backend, target: pptmaster-worker}
    profiles: [pptmaster]
    env_file: .env
    environment: {PPTMASTER_REPO_DIR: /opt/ppt-master, PPTMASTER_EXECUTION_SCOPE: worker}
    volumes: [pptmaster-projects:/opt/ppt-master/projects]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
      minio: {condition: service_healthy}

  postgres:
    image: pgvector/pgvector:pg16
    environment: {POSTGRES_USER: ppt, POSTGRES_PASSWORD: ppt, POSTGRES_DB: ppt}
    ports: ["127.0.0.1:15432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data, ./init/db:/docker-entrypoint-initdb.d:ro]
    healthcheck: {test: ["CMD-SHELL", "pg_isready -U ppt"], interval: 5s, timeout: 3s, retries: 10}

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    ports: ["127.0.0.1:6379:6379"]
    volumes: [redisdata:/data]
    healthcheck: {test: ["CMD", "redis-cli", "ping"], interval: 5s, timeout: 3s, retries: 10}

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment: {MINIO_ROOT_USER: pptadmin, MINIO_ROOT_PASSWORD: pptadmin123}
    ports: ["9000:9000", "9001:9001"]
    volumes: [miniodata:/data]
    healthcheck: {test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"], interval: 10s, timeout: 5s, retries: 6}

  minio-init:
    image: minio/mc:latest
    depends_on: {minio: {condition: service_healthy}}
    entrypoint: /bin/sh -c "mc alias set local http://minio:9000 pptadmin pptadmin123 && (mc mb -p local/ppt-gen || true)"

volumes: {pgdata: {}, redisdata: {}, miniodata: {}, pptmaster-projects: {}}
```

默认启动 7 个服务容器；启用 `pptmaster` profile 后增加 `pptmaster-worker`。`minio-init` 是一次性初始化容器，执行成功后 `Exited (0)` 属于正常状态。没有独立 `soffice` 容器，LibreOffice 已安装在 `worker` 与 `pptmaster-worker` 镜像中。

### 11.2 镜像与环境要点

| 镜像 | 要点 |
|---|---|
| frontend | 多阶段构建（node:20 build → nginx:alpine）；nginx 对 `/api/v1/jobs/*/events` 关闭缓冲（SSE） |
| backend（api/worker 共用） | python:3.11-slim；内置 Noto Sans CJK / Source Han Sans 字体（渲染度量一致性）；`--max-tasks-per-child` 防内存泄漏 |
| pptmaster-worker | 以 UID/GID 10001 非 root 用户在独立队列执行 Agent；镜像内置 Node、Claude Code、Codex CLI、ppt-master v4.8.0、LibreOffice 与其 Python 依赖 |

关键环境变量（.env.example）：

```bash
# LLM
QWEN_API_KEY=...            QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_API_KEY=...        DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_MAX_CONCURRENCY_PER_PROVIDER=8
# 存储
STORAGE_BACKEND=minio                       # minio | oss
S3_ENDPOINT=http://minio:9000  S3_BUCKET=ppt-gen  S3_ACCESS_KEY=...  S3_SECRET_KEY=...
S3_PUBLIC_ENDPOINT=http://localhost:9000
# 任务
JOB_TIMEOUT_FAST=300  JOB_TIMEOUT_STANDARD=900  JOB_TIMEOUT_PREMIUM=1800
VISION_QA_ENABLED=false  OCR_ENABLED=false
# ppt-master（百炼 Claude Code 示例）
PPTMASTER_EXECUTION_SCOPE=worker  PPTMASTER_DEFAULT_AGENT=auto
PPTMASTER_CLAUDE_MODEL=qwen3.7-plus
ANTHROPIC_AUTH_TOKEN=...  ANTHROPIC_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic
```

Worker 执行域下 API 不依赖本地仓库/CLI：提交时只校验 Agent 枚举，`pptmaster-worker` 领取任务后重新探测并解析实际 Agent。`/options` 的 `repo.ready=false`、`repo.delegated=true` 组合是正常状态。

### 11.3 扩容与高可用

- **扩容点**：普通 `worker` 可按队列吞吐扩容；`pptmaster-worker` 默认并发 1，按 Agent 费用和资源谨慎扩容；API 可加副本但当前 Compose 未配置副本数；
- 当前文档保留 Celery 重派/断点幂等作为设计目标，不能据此推断所有阶段已实现完整断点恢复；
- 产物清理、僵尸任务扫描和 Celery beat 尚未接入，相关留存配置目前只是配置项。

---

## 12. 可观测性

| 层 | 内容 |
|---|---|
| 当前日志/记录 | 应用结构化日志、`job_events`/`job_stages`、LLM 调用记录和 ppt-master 的可读日志/原始事件流；Docker 默认使用容器日志驱动 |
| 当前健康检查 | `/healthz` 只检查进程存活；`/readyz` 检查 DB、Redis、MinIO，转换能力异常时标记 `convert: degraded` |
| Prometheus/Grafana | 尚未接入 Compose；指标名、看板和告警仍是后续规划，不应作为本地启动依赖 |
| 追踪 | 当前以任务事件和阶段记录回放；OpenTelemetry 为后续规划 |

---

## 13. 关键实现细节与风险对策

| 风险 | 对策 |
|---|---|
| LLM 输出 JSON 不稳定 | JSON mode + Pydantic 严校验 + 修复器 + 换 Provider 重试；页面级失败降级要点页，绝不让坏 JSON 进 Renderer |
| 模板千奇百怪解析不准 | confidence 阈值 + 近似匹配 + 系统版式兜底；模板上传即解析并前置暴露"缺失版式"预警（不等到生成时才发现） |
| 中文测宽不准导致溢出 | 容器内统一字体 + Pillow 实测 + 10% 安全边距；QA 阶段二次校验 |
| LibreOffice 转换慢/不稳 | unoserver 常驻 + 独立容器隔离崩溃 + 失败仅降级预览不影响交付 |
| Provider 限流 | 网关级令牌桶 + 并发信号量 + 熔断切换；fast 模式章节批量调用天然减少调用数 |
| 大文档解析内存 | 流式分页解析，IR 落 MinIO 不驻留内存；Worker max-tasks-per-child 回收 |
| 并行分支部分失败 | chord 汇聚容忍降级页；只有"全部正文页失败"才判任务失败（E3004） |
| 时钟与耗时准确性 | 所有时间戳由后端统一产生；并行阶段耗时=汇聚墙钟时间，分支耗时入 meta |

---

## 14. 前端预计耗时估算公式（供 UI 使用）

```text
est_seconds = base(mode) + pages × per_page(mode, density) + doc_factor
  base:      fast 15s | standard 30s | premium 60s
  per_page:  fast 1.5s | standard 4s | premium 8s   (density=high 时 ×1.2)
  doc_factor: 文档每 50 页 +5s; 扫描件 +30s
展示时取区间 [est×0.7, est×1.5]
```

---

## 15. 实施顺序（与 PRD 里程碑对应）

```text
M1 (最小闭环, 仅fast):
  1 存储抽象+上传   2 PDF/DOCX解析   3 模板解析(11版式)   4 LLM Gateway(qwen+deepseek)
  5 OUTLINE_PLAN_COMBO   6 章节并行CONTENT   7 Renderer(11版式)   8 规则QA
  9 PUBLISH+后端代理下载   10 SSE进度   11 错误码+整任务重试   12 docker compose 全量部署
M2 (三模式+质量):
  13 标准模式DAG(页级并行+打分匹配+度量QA+1轮修复)   14 断点重试(checkpoint)
  15 Fact Registry+冲突交互   16 premium DAG(Vision QA+3轮修复)   17 耗时看板
M3 (产品化):
  18 RAG   19 版本链/内容不足交互/预算冲突交互   20 质量分报告页
  21 管理端统计   22 OSS切换验证   23 压测调优达标(§PRD 3.1)
```
