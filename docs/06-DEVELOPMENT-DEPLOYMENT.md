# 开发、配置与部署

> 版本：V1.2  
> 更新：2026-08-18  
> 事实来源：`backend/app/core/config.py`、`backend/Dockerfile`、`deploy/docker-compose.yml`、两份 `.env.example`

本文说明当前代码可直接使用的开发、测试、部署和运维方式。真实密钥只应写入未纳入版本控制的 `deploy/.env` 或 `backend/.env`，不要提交到仓库。

## 1. 运行结构

| 服务 | 作用 | 默认端口/状态 |
|---|---|---|
| `frontend` | React/Vite 构建产物，由 Nginx 托管并反代 `/api` | `8081` |
| `api` | FastAPI，同步校验、查询、下载和任务入队 | `8000` |
| `worker` | Celery 主生成和预览转换 | 无公开端口 |
| `pptmaster-worker` | 可选的 Claude Code/Codex + ppt-master 执行域 | profile `pptmaster` |
| `postgres` | 15 张业务表，镜像含 pgvector | 本机回环 `15432` |
| `redis` | Celery broker/backend、进度事件 | 本机回环 `6379` |
| `minio` | 默认 S3 兼容对象存储 | `9000` / 控制台 `9001` |
| `minio-init` | 一次性创建 `ppt-gen` 桶 | 完成后 `Exited (0)` 正常 |

主 Worker 消费 `generate`、`convert` 队列；PPT-MASTER Worker 只消费 `pptmaster` 队列。LibreOffice 已内置在后端 Worker 镜像中，不需要独立 soffice 服务。

## 2. 环境要求

- Docker Desktop / Docker Engine，支持 Compose v2；
- 本地开发：Python 3.11+、Node.js 20+、npm；
- Windows 推荐 PowerShell 7；Linux/macOS 可将示例命令换成对应 shell；
- 真实生成至少配置一个主链路模型 Key；无 Key 时可用 `LLM_MOCK=true` 验证基础链路；
- 真实 PPT-MASTER 需要 Agent 凭据和兼容的模型端点。

## 3. Docker Compose 快速启动

```powershell
Set-Location .\deploy
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env，填入需要的模型凭据
docker compose up -d --build
```

同时启动 PPT-MASTER：

```powershell
docker compose --profile pptmaster up -d --build
docker compose --profile pptmaster ps -a
```

启动后访问：

- Web：<http://localhost:8081>
- Swagger：<http://localhost:8000/docs>
- MinIO Console：<http://localhost:9001>
- 健康检查：`GET http://localhost:8000/healthz`
- 就绪检查：`GET http://localhost:8000/readyz`

## 4. 模型配置

### 4.1 新建生成

前端模型目录来自环境变量，不在页面写死：

```dotenv
LLM_SELECTABLE_MODELS=deepseek-v4-pro,kimi-k3,qwen3.7-plus,qwen3.8-max
LLM_DEFAULT_SELECTABLE_MODEL=qwen3.7-plus
LLM_BEAUTIFY_MODEL=kimi-k3
```

Gateway 按 model-id 前缀选 Provider：

| model-id | Provider | Key | Base URL |
|---|---|---|---|
| `deepseek-v4-pro` | DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` |
| `kimi-k3` | Kimi/Moonshot | `KIMI_API_KEY` | `KIMI_BASE_URL` |
| `qwen3.7-plus` / `qwen3.8-max` | Qwen/DashScope | `QWEN_API_KEY` | `QWEN_BASE_URL` |

`LLM_BEAUTIFY_MODEL=kimi-k3` 用于主生成成功后的“一键美化”子任务。独立“PPT 美化”上传页目前执行确定性九维评分与几何修复，本身不调用 LLM。

### 4.2 PPT-MASTER

PPT-MASTER 的前端目录独立配置，当前只保留三个 model-id：

```dotenv
PPTMASTER_SELECTABLE_MODELS=deepseek-v4-pro,qwen3.7-plus,qwen3.8-max
PPTMASTER_DEFAULT_MODEL=qwen3.7-plus
PPTMASTER_MAX_CONCURRENT_JOBS=3
```

这里的模型不是由主链路 `QWEN_API_KEY` / `DEEPSEEK_API_KEY` 直接调用，而是作为 `--model` 参数传给执行 Agent。默认 Claude Code 路线从以下变量取凭据：

```dotenv
ANTHROPIC_API_KEY=
# 或兼容服务：
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic
```

Codex 路线使用 `OPENAI_API_KEY` 和兼容 Responses API 的端点。API 只根据凭据判断 Agent“可能可用”，Worker 会在任务开始时重新检查 CLI、仓库与凭据。

## 5. 其他关键配置

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` / `REDIS_URL` | PostgreSQL 与 Redis 连接 |
| `STORAGE_BACKEND` | `minio` 或 S3 兼容 `oss` |
| `S3_ENDPOINT` | 服务端访问对象存储的地址 |
| `S3_PUBLIC_ENDPOINT` | 浏览器可达地址；服务器部署不能保留 `localhost` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | 对象存储凭据与桶 |
| `LLM_MAX_CONCURRENCY_PER_PROVIDER` | 主链路每 Provider 并发信号量 |
| `CONTENT_PARALLELISM` | 页/章并行线程数 |
| `JOB_TIMEOUT_FAST/STANDARD/PREMIUM` | 三模式任务超时 |
| `VISION_QA_ENABLED` | 专业模式 Vision Critic 开关 |
| `PPTMASTER_TIMEOUT_MINUTES` | PPT-MASTER 默认单任务超时 |
| `PPTMASTER_TIMEOUT_MAX_MINUTES` | 用户可选超时上限 |

完整默认值以 [`deploy/.env.example`](../deploy/.env.example) 为准。

## 6. 本地开发

先启动依赖服务：

```powershell
Set-Location .\deploy
docker compose up -d postgres redis minio minio-init
```

后端：

```powershell
Set-Location ..\backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

另开终端启动主 Worker：

```powershell
Set-Location .\backend
.\.venv\Scripts\Activate.ps1
celery -A app.worker worker -Q generate,convert --loglevel INFO --pool=solo
```

前端：

```powershell
Set-Location .\frontend
npm ci
npm run dev -- --host 0.0.0.0 --port 5800
```

Vite 会把 `/api` 代理到本机 `8000`。若 Windows 报端口 `EACCES`，请使用 `netsh interface ipv4 show excludedportrange protocol=tcp` 检查保留端口后换一个端口。

## 7. 测试与静态验证

```powershell
python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
docker compose --profile pptmaster -f deploy/docker-compose.yml config --quiet
```

后端测试覆盖 API、模型选择、主流水线、视觉引擎和 PPT-MASTER 任务恢复；前端使用 Vitest，构建同时执行 TypeScript 检查。

## 8. 生产部署建议

1. 复制 `.env.example` 为 `.env`，使用强随机数据库和对象存储密码；
2. 将 `S3_PUBLIC_ENDPOINT` 改为用户浏览器可访问的 HTTPS 域名；
3. 不直接暴露 PostgreSQL、Redis 和 MinIO API 到公网；
4. 在 Nginx/Ingress 前增加 TLS、鉴权、请求大小限制和访问日志；当前应用本身没有登录/多租户；
5. PPT-MASTER Agent 带无人值守执行权限，只应运行在独立非 root 容器中；
6. 对 `pgdata`、`miniodata` 和 `pptmaster-projects` 做持久化备份；
7. 为 API/Worker 配置 CPU、内存限制和日志轮转；
8. 扩容主 Worker 可提升主链路吞吐，但不要通过扩容 `pptmaster-worker` 绕过部署级三并发上限。

更新镜像：

```powershell
Set-Location .\deploy
docker compose --profile pptmaster build --pull
docker compose --profile pptmaster up -d --force-recreate
docker compose --profile pptmaster ps -a
```

## 9. 常用运维命令

```powershell
# 全部日志
docker compose --profile pptmaster logs -f --tail=200

# 单服务日志
docker compose logs -f api worker
docker compose --profile pptmaster logs -f pptmaster-worker

# 健康与模型目录
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
Invoke-RestMethod http://localhost:8000/api/v1/pptmaster/options

# 停止服务但保留卷
docker compose --profile pptmaster down
```

不要在没有备份且未明确需要清空数据时使用 `down -v`。

## 10. 当前边界

- 无内建用户认证、权限和多租户隔离；
- 扫描 PDF OCR 默认关闭；
- 完整 embedding/RAG、Prometheus/Grafana 和自动产物清理尚未落地；
- PPT-MASTER 进度由 Agent 事件和工作区文件推断，是阶段性估计值；
- 单个 PPT-MASTER 任务不可从 Agent 会话断点续跑，但如果 Agent 已生成可用产物，Worker 会优先恢复并交付产物，避免误标失败。
