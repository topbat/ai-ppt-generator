# AI PPT 自动生成系统（Template-driven AI Presentation Generator）

输入 **PPT 模板 + 主说明文档(PDF/DOCX) + 页数 + 模式 + 内容密度** 5 项信息，分钟级产出可编辑、可预览、可追溯、可重试的 PPTX。全容器化，一键部署。

内置**视觉优化**能力（第二阶段）：九维视觉评分（布局/对齐/字体/间距/色彩/层级/密度/图片/一致性）+ BEAUTIFY 确定性美化闭环 + 历史任务"一键美化"，质量分与视觉分并列展示。

设计文档见 [docs/](docs/)：[PRD](docs/01-PRD.md) · [UI 设计](docs/02-UI-DESIGN.md) · [实现方案](docs/03-IMPLEMENTATION.md) · [视觉优化](docs/04-VISUAL-OPTIMIZATION.md)

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

使用流程：**模板库上传公司模板（可选）→ 新建生成 → 上传 PDF/DOCX → 选页数/模式/密度 → 开始生成 → 实时进度（边生成边看）→ 在线预览 / 下载 PPTX**。

## 三种模式

| | ⚡ 极速（默认） | 🚀 标准 | 💎 专业 |
|---|---|---|---|
| 定位 | 内部草稿、快速汇报 | 日常正式汇报 | 对外方案、领导汇报 |
| 内容生成 | 章节批量+并行（4~5 次 LLM/10页） | 页级并行 | 页级并行+事实提示注入 |
| 视觉优化 | Token 化渲染+一次性出分 | BEAUTIFY 规则闭环 ≤2 轮 | BEAUTIFY 闭环 + Vision Critic(可选) |
| 质检 | 规则 QA | 规则+度量 QA + 1 轮修复 | +事实冲突交互 + Vision QA(可选) + ≤3 轮修复 |
| 预览 | PPTX 秒交付，PDF/PNG 异步补齐 | 主链路内完成 | 主链路内完成 + 质检报告 |
| 10 页目标 | 20~40s | 40~90s | 1~3min |

成功页可对历史任务**一键美化**（`POST /jobs/{id}/beautify`）：以原任务为父创建新版本，复用全部内容成果，只重跑 渲染→视觉优化→转换→质检→归档，秒级完成。

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
deploy/     docker-compose + .env + 初始化脚本
docs/       PRD / UI 设计 / 实现方案 / 视觉优化设计
```

七个容器：frontend / api / worker / postgres(pgvector) / redis / minio / minio-init。

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
| 下载链接打不开 | `S3_PUBLIC_ENDPOINT` 必须是浏览器可达地址（服务器 IP，非 minio 服务名） |
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

- 模板贡献视觉语言（配色/字体/版式识别绑定），模板页 XML 直接克隆为 V2 能力；
- 扫描件 PDF 需开启 OCR（`OCR_ENABLED`，V1 默认关闭并明确报错 E2003）；
- Vision QA 默认关闭（`VISION_QA_ENABLED=true` 且配置 qwen-vl 后启用）；
- 单页/单章重新生成、图片素材管线在 V2 路线图（见 docs/01-PRD.md §7/§9）。
