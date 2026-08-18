# AI PPT 自动生成系统（Template-driven AI Presentation Generator）

输入 **PPT 模板 + 主说明文档(PDF/DOCX) + 页数 + 模式 + 内容密度** 5 项信息，分钟级产出可编辑、可预览、可追溯、可重试的 PPTX。全容器化，一键部署。

内置**视觉优化**能力（第二阶段）：九维视觉评分（布局/对齐/字体/间距/色彩/层级/密度/图片/一致性）+ BEAUTIFY 确定性美化闭环 + 历史任务"一键美化"，质量分与视觉分并列展示。

另提供 **ppt-master 生成**（第三阶段，可选）：把开源 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master) 作为工具，用 FastAPI 包装成"异步提交 → 轮询状态"的 API，后端以子进程驱动 Claude Code / Codex CLI 在 ppt-master 工作区内无人值守跑完整工作流，产出原生可编辑 PPTX 并上传对象存储；前端独立菜单「ppt-master生成」。与既有生成流水线完全隔离，见 [ppt-master 生成](#ppt-master-生成可选独立能力)。

设计文档见 [docs/](docs/)：[PRD](docs/01-PRD.md) · [UI 设计](docs/02-UI-DESIGN.md) · [实现方案](docs/03-IMPLEMENTATION.md) · [视觉优化](docs/04-VISUAL-OPTIMIZATION.md) · [ppt-master 集成](docs/05-PPTMASTER-INTEGRATION.md)

> **实现状态说明（2026-08-17）**：主生成流水线、模板页 XML 克隆、九维视觉评分、任务一键美化、独立 PPTX 美化 API 与 ppt-master 的 API/Worker/前端代码均已存在；Compose 分离容器中的真实 Claude Code + `qwen3.7-plus` 链路已完成端到端验证。当前 ORM 实际定义 15 张表，数据库仍使用 `create_all + ADD COLUMN IF NOT EXISTS`，未接 Alembic。OCR、真正的 RAG 检索、Prometheus/Grafana、产物自动清理、用户并发配额和认证/多租户仍未落地；具体边界见本文末尾。

## 快速开始

前置：Docker 20+ / Docker Compose v2。

```bash
cd deploy
cp .env.example .env
# 编辑 .env：至少填入 QWEN_API_KEY 或 DEEPSEEK_API_KEY
# （没有 Key 想先跑通链路：把 LLM_MOCK=true）
# 部署到服务器时：S3_PUBLIC_ENDPOINT 改为 http://<服务器IP>:9000

docker compose up -d --build
```

启动后：

| 入口 | 地址 |
|---|---|
| Web 界面 | http://localhost:8081（compose 端口映射 8081→80） |
| API（Swagger） | http://localhost:8000/docs |
| 就绪检查 | http://localhost:8000/readyz |
| MinIO 控制台 | http://localhost:9001（pptadmin / pptadmin123） |

首次启动会自动：建表 → 创建存储桶 `ppt-gen` → 注册"系统默认模板"。

使用流程：**模板库上传公司模板（可选）→ 新建生成 → 上传 PDF/DOCX → 选模型/页数/模式/密度 → 开始生成 → 实时进度（边生成边看）→ 在线预览 / 下载 PPTX**。

## 本地容器运行

以下命令以 Windows PowerShell 为例。首次运行先准备配置：

```powershell
Set-Location deploy
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

至少检查 `deploy/.env` 中的数据库、Redis、MinIO 与 LLM 配置。没有 Qwen/DeepSeek Key 时可先设置 `LLM_MOCK=true` 验证主链路。

### 只启动主生成链路

```powershell
docker compose up -d --build
docker compose ps -a
```

启动后共创建 7 个容器：`frontend`、`api`、`worker`、`postgres`、`redis`、`minio`、`minio-init`。其中 `minio-init` 创建存储桶后以 `Exited (0)` 正常退出，其余 6 个常驻运行。LibreOffice 已内置在 `worker` 镜像中，没有独立 `soffice` 容器。

### 连同 ppt-master 一起启动

先在 `deploy/.env` 选择执行 Agent：

```dotenv
# 真实 Claude Code + 阿里云百炼（推荐示例）
LLM_SELECTABLE_MODELS=deepseek-v4,qwen3.7-plus,qwen3.8-max
LLM_DEFAULT_SELECTABLE_MODEL=qwen3.7-plus
PPTMASTER_DEFAULT_AGENT=auto
PPTMASTER_CLAUDE_MODEL=qwen3.7-plus
PPTMASTER_MAX_CONCURRENT_JOBS=3
ANTHROPIC_AUTH_TOKEN=<百炼 API Key>
ANTHROPIC_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic
PPTMASTER_CLAUDE_MAX_BUDGET_USD=12

# 没有 Agent 凭据时，仅验证异步/存储/预览链路
# PPTMASTER_DEFAULT_AGENT=mock
```

百炼地址必须包含 `/apps/anthropic`，且不要再追加 `/v1`；API Key 与地域/Workspace 必须匹配。也可使用 `ANTHROPIC_API_KEY`，完整接入说明见[阿里云 Claude Code 文档](https://help.aliyun.com/zh/model-studio/claude-code)。Codex 路线则配置 `OPENAI_API_KEY`、`PPTMASTER_CODEX_MODEL` 和兼容 Responses API 的 Provider。

然后启动 `pptmaster` profile：

```powershell
docker compose --profile pptmaster up -d --build
docker compose --profile pptmaster ps -a
docker compose logs -f pptmaster-worker
```

此时共创建 8 个容器：

| 容器/服务 | 运行方式 | 职责 |
|---|---|---|
| `frontend` | 常驻 | Nginx 托管 React 页面并反向代理 API |
| `api` | 常驻、健康检查 | FastAPI：上传、任务、查询、下载；ppt-master 采用 Worker 执行域 |
| `worker` | 常驻 | 主生成链路的 `generate,convert` Celery 队列 |
| `pptmaster-worker` | 常驻、profile `pptmaster` | 独立消费 `pptmaster` 队列；内置非 root 用户、Claude/Codex、ppt-master v4.8.0、LibreOffice |
| `postgres` | 常驻、健康检查 | 任务、模板、事件与统计元数据 |
| `redis` | 常驻、健康检查 | Celery broker/result backend 与进度消息 |
| `minio` | 常驻、健康检查 | 源材料、PPTX、PDF、预览、报告、日志对象存储 |
| `minio-init` | 一次性 | 创建 `ppt-gen` 存储桶，成功后 `Exited (0)` |

API 在 `PPTMASTER_EXECUTION_SCOPE=worker` 下只根据凭据展示能力并接受 `auto|claude|codex|mock`；真正的 CLI、仓库和 Agent 可用性由 `pptmaster-worker` 领取任务后重新探测并回填实际 Agent。因而 `/options` 中 API 本地 `repo.ready=false` 与 `repo.delegated=true` 同时出现是正常状态，不会再把真实任务错误降级为 Mock。

### 启动后检查

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
Invoke-RestMethod http://localhost:8000/api/v1/pptmaster/options
docker compose exec -T pptmaster-worker sh -lc 'id && claude --version && codex --version && soffice --version'
docker compose exec -T pptmaster-worker test -f /opt/ppt-master/skills/ppt-master/SKILL.md
docker compose --profile pptmaster logs --tail 100 api worker pptmaster-worker
```

本机入口：Web `http://localhost:8081`、Swagger `http://localhost:8000/docs`、MinIO 控制台 `http://localhost:9001`。部署到其他机器时，如启用预签名或需要浏览器直连对象存储，再把 `S3_PUBLIC_ENDPOINT` 改成可访问的服务器地址；当前默认下载走 API 后端代理。

## 三种模式

| | ⚡ 极速（默认） | 🚀 标准 | 💎 专业 |
|---|---|---|---|
| 定位 | 内部草稿、快速汇报 | 日常正式汇报 | 对外方案、领导汇报 |
| 内容生成 | 章节批量+并行（4~5 次 LLM/10页） | 页级并行 | 页级并行+事实提示注入 |
| 视觉构图 | 原有确定性版式，调用量不变 | 整册艺术指导 + 视觉分镜 + 布局语法 + 重复度控制 | 同标准，并将约 18% 关键页交给受约束自由设计 Agent（最多5页） |
| 视觉优化 | Token 化渲染+一次性出分 | BEAUTIFY 规则闭环 ≤2 轮 | BEAUTIFY 闭环 + Vision Critic(可选) |
| 质检 | 规则 QA | 规则+度量 QA + 1 轮修复 | +事实冲突交互 + Vision QA(可选) + ≤3 轮修复 |
| 预览 | PPTX 秒交付，PDF/PNG 异步补齐 | 主链路内完成 | 主链路内完成 + 质检报告 |
| 10 页目标 | 20~40s | 40~90s | 1~3min |

成功页可对历史任务**一键美化**（`POST /jobs/{id}/beautify`）：以原任务为父创建新版本，复用全部内容成果，只重跑 渲染→视觉优化→转换→质检→归档，秒级完成。

### 企业模板视觉构图升级

标准/专业模式在 `PLAN` 与 `CONTENT` 之间增加整册艺术指导和逐页视觉分镜，在 `MATCH` 与 `LAYOUT` 之间增加确定性构图层：

- 模板解析生成 `space_contract`，正文只能进入安全区，logo、页脚等品牌区域作为保护区；
- 14 套布局语法覆盖单焦点、分栏、卡片、流程、结构、数据和编辑式构图；同一任务用 SHA-256 稳定选型；
- 所有内容容器逐边检查上/右/下/左边距，正文语义字号不低于 16pt；
- 相邻构图指纹不得重复，单一布局家族在有可选方案时不超过正文页的 30%，连续三页不保持同一焦点位置；
- 超量支持材料不会缩成小字，而是转入可编辑的 PowerPoint 演讲者备注；核验数字和专有名称必须保持；
- 专业模式关键页 Agent 只能重排冻结内容并使用批准 Token；单页最多尝试两次，失败自动保留普通构图，不会中断整册；
- 质检报告新增构图节奏分、边距/字体违规、重复率和关键页应用/回退明细。

成本变化：标准/专业模式固定增加艺术指导与视觉分镜两次结构化调用；专业模式再按关键页数量增加最多两次/页的场景调用。极速模式阶段与调用量保持不变。

## 架构与目录

```text
frontend/   React 18 + AntD 5（nginx 容器，SSE 实时进度）
backend/    FastAPI(api) + Celery(worker) 共用代码
  app/pipeline/   三模式流水线：Orchestrator + 16 个 Stage（含 BEAUTIFY）+ Guard 层 + Checkpoint
  app/ai/         LLM Gateway（Qwen/DeepSeek 路由、熔断、JSON 修复、调用计量）
  app/ppt/        python-pptx 渲染引擎（20 种版式、文本测量、原生图表）
    design_tokens.py  视觉规范单一事实来源（字号/间距/网格/锚线）
    visual_score.py   九维视觉评分规则引擎（逐页+整册，零 LLM 成本）
    visual_ops.py     Fix Ops 受控 DSL + 确定性调整器 + PPTX 几何微调
  app/parser/     PDF(PyMuPDF) / DOCX / PPTX 模板解析
  app/pptmaster/  ppt-master 集成（独立能力）：能力目录 / 提示词编译 / Agent 运行器(claude|codex|mock) / 任务服务
deploy/     docker-compose + .env + 初始化脚本
docs/       PRD / UI 设计 / 实现方案 / 视觉优化设计 / ppt-master 集成设计
ppt-master/ （不入库）hugohe3/ppt-master 稀疏克隆，与 backend 同级；仅本地开发的 pptmaster Worker 使用，容器镜像自带一份
```

七个容器：frontend / api / worker / postgres(pgvector) / redis / minio / minio-init；可选第八个 `pptmaster-worker`（profile `pptmaster`）。

## ppt-master 生成（可选独立能力）

**是什么**：[ppt-master](https://github.com/hugohe3/ppt-master)（MIT，47k★）是运行在 coding agent 里的 PPT 设计工作流：LLM 逐页手写受控 SVG → 脚本编译为原生 DrawingML PPTX，视觉自由度与原生深度远高于版式引擎。本项目把它**当工具**接入：

```text
前端 /pptmaster ── POST /api/v1/pptmaster/jobs（multipart）──▶ API 落库 + 材料上 MinIO ──▶ Celery 队列 pptmaster
        ▲ 每 3s 轮询 GET /jobs、GET /jobs/{id}                                     │
        │                                                                          ▼
   列表/进度/详情/预览/下载  ◀── 产物(PPTX/预览/日志/报告)上 MinIO ◀── pptmaster-worker：project_manager.py init 建工作区
                                                                     → 放材料 → 子进程 `claude -p …` / `codex exec …`
                                                                     （或 mock）无人值守跑完 → 收集 exports/*.pptx
```

- **入参**（覆盖 ppt-master 支持的方式）：输入方式 上传源文件(PDF/DOCX/PPTX/XLSX/MD/HTML/EPUB/图片，多文件) / 仅主题(topic-research) / 粘贴文本 / 网页链接；路线 生成新 PPT / 套用我的 PPTX 模板(template-fill) / 美化现有 PPTX(1:1) / 为 PPTX 加备注·旁白·转场(native-enhance) / 页面图片还原(image-to-pptx，仅 Codex) / 蒸馏模板(create-template)；档位 quick / default(自动决策不确认)；模型由环境目录三选一；页数、8 种画布、视觉风格、叙事模式、阅读模式、语言、图片素材策略、增强开关和附加要求。模板填充路线的视觉风格固定为上传模板，不可修改。
- **状态与产物**：`pending → running(progress/stage 启发式：事件流 + 工作区文件) → succeeded|failed|canceled`；列表独立展示模型，运行中悬浮展示 `stage1 --> stage2 --> stage3` 完整轨迹；最多同时生成 3 个，更多任务保持 pending 排队；产物 PPTX、逐页预览、日志与报告均支持下载。
- **成本**：每个任务的 Claude 费用/轮次记录在详情 `run` 字段；2026-08-17 容器实测 `qwen3.7-plus`、topic/quick/1 页为 375 秒、40 轮、约 $2.05。实际成本随主题、页数、模型和质检修复轮次变化；`PPTMASTER_CLAUDE_MAX_BUDGET_USD` 可设单任务费用上限。
- **完全隔离**：独立表 `pptmaster_jobs`、独立路由 `/api/v1/pptmaster/*`、独立 Celery 队列 `pptmaster` 与 Worker，不触碰生成流水线代码。

**单独启动 ppt-master Worker（主服务已经运行时）**：

```bash
# .env 追加 Agent 凭据与模型；百炼 Base URL 必须以 /apps/anthropic 结尾
cd deploy && docker compose --profile pptmaster up -d --build pptmaster-worker
# 镜像 = worker 镜像 + Node20 + @anthropic-ai/claude-code + @openai/codex + ppt-master(v4.8.0 稀疏克隆) + 其 pip 依赖
```

**本地开发**：把 ppt-master 稀疏克隆到项目根目录下的 `ppt-master/`（与 `backend/` 同级，已在 `.gitignore` 中排除），安装其依赖到后端 venv，然后单独起一个只消费 `pptmaster` 队列的 Worker：

```bash
# 在 main-ppt 项目根目录执行
git clone --filter=blob:none --sparse --depth 1 --branch v4.8.0 https://github.com/hugohe3/ppt-master.git ppt-master
git -C ppt-master sparse-checkout set --no-cone '/*' '!/examples' '!/docs/assets'   # 剔除 800MB 示例（Windows Git Bash 前置 MSYS_NO_PATHCONV=1）
pip install -r ppt-master/skills/ppt-master/requirements.txt
# backend/.env：PPTMASTER_REPO_DIR=../ppt-master  PPTMASTER_DEFAULT_AGENT=auto  PPTMASTER_MAX_CONCURRENT_JOBS=3
cd backend && celery -A app.worker worker -Q pptmaster -c 3 -P threads
```

没有任何 Agent CLI 时选 `mock` 仍可跑通"提交 → 轮询 → 上传 → 预览 → 下载"全链路（产出占位 PPTX）。冒烟脚本按直接执行方式编写：`python tests/test_pptmaster.py`；当前本机 Python 环境需先安装 `backend/requirements.txt`，否则会在导入 `boto3` 等依赖时中止。

## 关键运维

```bash
# Worker 扩容（吞吐扩容点；同时按需调大 .env 的 LLM_MAX_CONCURRENCY_PER_PROVIDER）
docker compose up -d --scale worker=4

# 看生成日志（中文结构化日志，含 job_id/stage）
docker compose logs -f worker

# 切换阿里云 OSS：改 .env 后重启
#   STORAGE_BACKEND=oss
#   S3_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com  S3_PUBLIC_ENDPOINT=同左
#   S3_ACCESS_KEY/S3_SECRET_KEY=OSS 的 AK/SK  S3_BUCKET=你的桶
```

## 故障排查

| 现象 | 处理 |
|---|---|
| 任务失败显示 E3001 | 检查 .env 的 LLM Key 与网络；`docker compose logs worker | grep LLM` |
| 预览图不出（PPTX 可下载） | E6003 降级：检查 worker 容器内 `soffice --version`；本机跑 Worker 时多半是 `CONVERT_BACKEND=none`（无 LibreOffice），见"本地开发"一节的两种补齐方式；不影响交付 |
| 下载/预览失败 | 先检查 API 能否访问 MinIO：`docker compose logs api`；后端代理下载不要求浏览器直连 `minio` 服务名，外部预签名场景才需正确设置 `S3_PUBLIC_ENDPOINT` |
| 中文显示为方块 | worker 镜像需含 fonts-noto-cjk（默认已装）；重新 build |
| 任务卡 pending | worker 未起或队列积压：`docker compose ps`、`logs worker` |

## 本地开发（不使用 Docker 跑后端）

支持直连本地 PostgreSQL（`localhost:5432`）：`ppt` 数据库不存在时**启动自动创建**，无需手工建库。

```bash
# 1) 后端环境配置
cd backend
cp .env.example .env        # 按需改 DATABASE_URL 密码、填 LLM Key
                            # Windows 无 LibreOffice 时保持 CONVERT_BACKEND=none（见下方说明）

# 2) Redis / MinIO 只起依赖容器（compose 已把端口映射到本机回环地址）
cd ../deploy && docker compose up -d redis minio minio-init

# 3) 启动后端（Python 3.11+）
cd ../backend && pip install -r requirements.txt
uvicorn app.main:app --reload             # API → http://localhost:8000
celery -A app.worker worker -Q generate,convert -c 4 -P threads   # Worker（Windows 用 -P threads）

# 4) 前端
cd ../frontend && npm install && npm run dev -- --port 5800
# → http://localhost:5800（代理到 :8000）
# 注意：Vite 默认端口 5173 可能落在 Windows 保留端口段（netsh interface ipv4 show
# excludedportrange protocol=tcp 查看），报 EACCES 时换 5800 等空闲端口
```

> 容器部署与本地开发互不干扰：compose 内的 PostgreSQL 映射到本机 `127.0.0.1:15432`，不与本地 5432 实例冲突。

**本机跑 Worker 时的预览转换说明**：PPTX→PDF→PNG 预览链路依赖 LibreOffice。本机没有装时
（`CONVERT_BACKEND=none`）任务照常成功、PPTX 可下载，但成功页没有预览图。两种补齐方式：

1. **推荐：Worker 用容器跑**（镜像内置 LibreOffice + Noto CJK 字体），本机只跑 API 与前端：
   ```bash
   cd deploy && docker compose build worker && docker compose up -d --no-deps worker
   # 同时停掉本机 celery，避免两个 worker 抢任务；容器 worker 经 deploy/.env 连宿主机数据库
   ```
2. 本机安装 LibreOffice，然后 backend/.env 设 `CONVERT_BACKEND=soffice`、
   `SOFFICE_BIN=C:/Program Files/LibreOffice/program/soffice.com` 并重启 Worker。

## 当前版本边界（V1）

- 模板页 XML 克隆已实现：封面/目录/章节/尾页整页克隆，正文以内容框架页为底版；匹配或克隆失败时降级到系统版式；
- `OCR_ENABLED` 目前只有配置字段，没有 OCR 执行实现；扫描件 PDF/DOCX 会明确报错 E2003，需要先转成可复制文本的 PDF/DOCX；
- Vision QA 默认关闭（`VISION_QA_ENABLED=true` 且配置 qwen-vl 后启用）；
- `DocChunk`/embedding 只有数据模型骨架，专业模式尚未执行真正的向量 RAG 检索；
- 单页/单章重新生成、主流水线图片素材管线仍在 V2 路线图；
- 当前无登录鉴权和租户隔离，CORS 全开放；`user_id` 只是预留字段；
- `USER_MAX_CONCURRENT_JOBS`、产物/Checkpoint 留存天数目前仅有配置项，没有调度与清理任务；
- Prometheus/Grafana、Kubernetes、Alembic 迁移和自动压测尚未实现；
- ppt-master 的图片搜索、AI 生图、TTS 和部分模型 Provider 仍依赖各自外部 Key；未配置时只能选择不使用这些资源或按工作流降级。
