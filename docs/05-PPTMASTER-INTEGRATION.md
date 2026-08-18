# AI PPT 生成系统 — ppt-master 集成设计（第三阶段，可选独立能力）

> 版本：V1.2
> 日期：2026-08-18（按当前实现同步）
> 定位：把开源 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master)（v4.8.0，MIT）作为**工具**接入，用 FastAPI 包装成"异步提交 → 轮询状态"的 API 供前端使用；与既有生成流水线（[03 文档](03-IMPLEMENTATION.md)）完全隔离。
> 关联：[README §启用 PPT-MASTER](../README.md#启用-ppt-master)

---

## 1. 为什么是"子进程驱动 Agent"

ppt-master 不是库，而是运行在 coding agent（Claude Code / Codex / Cursor…）里的 **skill 工作流**：由 LLM 主代理读取 `skills/ppt-master/SKILL.md` 完成路由，逐页手写受控 SVG，再调用其 Python 脚本（`svg_quality_checker.py`、`svg_to_pptx.py` 等）编译为原生 DrawingML PPTX。因此"包装成 API"的本质是**无人值守地运行一个 agent 会话**：

| 方案 | 结论 |
|---|---|
| 直接 import 其脚本重写流水线 | 丢失其全部提示词/工作流资产，等于重写一个 ppt-master，放弃 |
| Claude Agent SDK 内嵌 | 可行，但与 CLI 等价且多一层依赖；后续可作为第四种 Runner |
| **子进程 `claude -p` / `codex exec`（采用）** | 官方 headless 模式，stream-json 事件流可解析进度与用量；Runner 可插拔（claude / codex / mock） |

## 2. 架构

```text
前端 /pptmaster ──POST multipart──▶ pptmaster_api.create_job ──▶ 校验/上传材料到 MinIO/落库(pending) ──▶ Celery 队列 pptmaster
   ▲ 3s 轮询 list/detail                                                                              │
   │                                                                                                  ▼
 列表/进度/详情抽屉/预览/下载  ◀── 产物上 MinIO ◀── service.run_pptmaster_job（pptmaster-worker，独立进程/容器）
                                                     1 project_manager.py init <biz> --format <canvas> [--quick-generate]
                                                     2 材料下载到 <project>/sources/（粘贴文本 → pasted_material.md）
                                                     3 build_prompt() 生成中文提示词（真实工作区路径）
                                                     4 Runner.run()：子进程 + 事件流 → 可读日志 agent.log / 原始 agent.log.stream.jsonl
                                                       ├ _ProgressMonitor：事件(tool_use/命令) + 工作区文件(svg_output/exports) → progress/stage，3s 节流写库
                                                       ├ should_cancel：每 2s 查库 cancel_requested → 杀进程树
                                                       └ 超时：timeout_minutes（≤ PPTMASTER_TIMEOUT_MAX_MINUTES）
                                                     5 收集 exports/*.pptx（每变体最新）+ validation/*.report.json + 日志/事件流 → 上传
                                                     6 预览：PPTX→PDF→PNG（有 soffice）否则 svg_final/ | svg_output/ 页面 SVG
                                                     7 落库 succeeded / failed / canceled（含 cost_usd / num_turns）
```

> 容器部署使用 `PPTMASTER_EXECUTION_SCOPE=worker`：API 只校验 Agent 枚举、根据已注入凭据展示 Claude/Codex 能力并投递任务；`pptmaster-worker` 领取任务后强制刷新 CLI 探测、解析 `auto`，再把实际 Agent 回填任务。API 镜像不含 ppt-master 仓库，因此 `/options` 同时返回 `repo.ready=false` 与 `repo.delegated=true` 属于预期状态。

代码位置：`backend/app/pptmaster/{catalog,prompt,runner,service}.py`、`backend/app/api/pptmaster_api.py`、`app.worker.pptmaster_generate`（队列 `pptmaster`）、模型 `PptMasterJob`（表 `pptmaster_jobs`）、前端 `frontend/src/pages/PptMaster.tsx`。

## 3. 入参目录（`GET /api/v1/pptmaster/options`，`catalog.py`）

| 维度 | 取值 | 对应 ppt-master |
|---|---|---|
| input_mode | files / topic / text / url | 源文件（`import-sources`）/ topic-research / 粘贴文本落为 md / `source_to_md.py` 抓网页 |
| route | generate / template_fill / beautify / enhance / image_to_pptx(仅 codex) / create_template | Generate PPTX / Fill Native PPTX / beautify-pptx profile / Enhance Native PPTX / image-to-pptx profile / Create Template |
| profile | quick / default | quick-generate profile / 默认 Strategist→Executor（提示词要求自动锁定规格不确认） |
| canvas | ppt169 ppt43 xiaohongshu moments story wechat banner a4 | `canvas-formats.md` |
| style | auto + template（分析上传模板后推导）+ 18 内置 + custom；所有路线均允许修改 | `references/visual-styles/` |
| narrative_mode | auto pyramid narrative instructional showcase briefing | `references/modes/` |
| reading_mode | auto text balanced presentation | 正文字号档 |
| language / image_source | auto zh en / auto none search ai | — / `image_search.py` `image_gen.py` |
| 开关 | native_charts speaker_notes narration transitions animations | `--native-charts-and-tables` / notes / `notes_to_audio` / transitions / animations |
| 执行 | agent(auto claude codex mock) model timeout_minutes | Runner 选择；model 来自环境模型目录 |

当前前端模型目录固定来自 `PPTMASTER_SELECTABLE_MODELS`，只展示 `deepseek-v4-pro`、`qwen3.7-plus`、`qwen3.8-max`，默认 `qwen3.7-plus`。任务创建时必须提交合法 model-id，后端写入 `pptmaster_jobs.model`，列表“模型”列展示该持久化值。

## 4. 提示词契约（`prompt.py`）

- 无人值守：不提问、不等待确认、不启动 confirm_ui / live preview；未指定项由 Agent 自决；
- 显式即遵循：每个用户参数转成一句明确指令（页数"正好 N 页"、风格、叙事、图片策略、导出开关…）；
- 工作区已 init：明确目录 `projects/<biz>_<canvas>_<YYYYMMDD>/`，禁止再次 init 或另建目录；
- 交付：PPTX 必须在 `<project>/exports/`；最后一行 `DONE: <path>` 或 `FAILED: <原因>`（Worker 据此判定并提取失败原因）。
- 模板路线：选择“由上传的 PPTX 模板决定”时，Agent 根据模板内容、结构、字体、色彩与版式语言推导风格；它只是 `style=template` 的选项，前端不会锁定视觉风格，用户始终可改选其他风格。

## 5. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /pptmaster/options | 入参目录、执行域、Agent 能力、仓库状态与限制；Worker 执行域按凭据展示能力并标记 `repo.delegated` |
| POST | /pptmaster/jobs | multipart：字段见 §3 + `files[]` + `template`；校验枚举/大小/路线依赖（模板/pptx/图片）；返回 `job_id` |
| GET | /pptmaster/jobs?status&page&page_size | 列表（含 progress/stage/outputs/preview_urls/run） |
| GET | /pptmaster/jobs/{id} | 详情 + prompt + log_tail + log_url |
| POST | /pptmaster/jobs/{id}/cancel | pending 直接 canceled；running 置 cancel_requested（Worker 杀进程树），API 同机时顺带 taskkill |
| DELETE | /pptmaster/jobs/{id} | 软删（运行中 409） |
| GET | /pptmaster/jobs/{id}/download/{kind} | pptx / pptx_native / pptx_narrated / pdf / report / log / stream（后端代理输出） |
| GET | /pptmaster/jobs/{id}/pages/{n}/image | 逐页预览 png/svg |
| GET | /pptmaster/jobs/{id}/log | 完整可读日志 |

任务 DTO 还返回去重后的 `stage_history`。前端对进行中状态使用悬浮提示，将已经历阶段按 `准备工作区 --> 启动 Agent --> ...` 完整展示；阶段历史最多保留最近 60 项，不把内部 `_stage_history` 暴露在普通 `params` 中。

### 5.1 完成判定与误失败恢复

完成判定以“是否存在可打开的 PPTX”优先，不只看 Agent 退出码：

1. 先收集 `exports/*.pptx`；只要存在产物，即使 Agent 最终回复异常或返回非零，也上传产物并以 `succeeded` 结束，同时在阶段文案中标注 Agent 异常；
2. Agent 正常结束但没有导出 PPTX 时，如果 `svg_output/` 已有完整页集，Worker 会执行 SVG finalize、质量检查和 `svg_to_pptx.py` 转换；
3. 恢复产物必须能被 `python-pptx` 打开，并与期望页数一致；失败则保留为 `failed`，审计原因写入 `run.recovery`；
4. 对历史失败记录，`recover_failed_pptmaster_job()` 只处理 Agent 当时正常退出的任务，重新收集已有导出或从完整 SVG 恢复，避免把不完整页集误判为成功；
5. 美化路线的期望页数从上传 PPTX 读取，其他路线优先使用显式页数或设计规格。

## 6. 部署与安全

- 目录约定：ppt-master 仓库放在项目根目录 `ppt-master/`（与 `backend/` 同级，`.gitignore` 排除，独立 git 仓库，按 README 稀疏克隆）；`PPTMASTER_REPO_DIR` 默认 `../ppt-master`（相对 `backend/` 解析），容器内为 `/opt/ppt-master`。
- 容器：`backend/Dockerfile` 目标 `pptmaster-worker` = worker-base + git + Node 20（二进制）+ `@anthropic-ai/claude-code` + `@openai/codex` + ppt-master 稀疏克隆 + 其 pip 依赖；compose 服务 `pptmaster-worker`（profile `pptmaster`，工作区卷 `pptmaster-projects`）。镜像最终切换到 UID/GID 10001 的 `pptmaster` 用户，因为 Claude Code 禁止 root 搭配 `--dangerously-skip-permissions`。
- 凭据：Claude 使用 `ANTHROPIC_API_KEY`，或 `ANTHROPIC_AUTH_TOKEN` + 绝对 `ANTHROPIC_BASE_URL`；阿里云百炼 Workspace 地址必须写成 `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic`（不要追加 `/v1`）。Codex 使用 `OPENAI_API_KEY` 和支持 Responses API 的 Provider。图片搜索、AI 生图、TTS 等额外能力的 Key 必须通过 Worker 环境传入。
- 费用护栏：`PPTMASTER_CLAUDE_MAX_BUDGET_USD`（`--max-budget-usd`）；每任务 `run.cost_usd / num_turns` 落库并在详情展示。
- 并发与排队：`PPTMASTER_MAX_CONCURRENT_JOBS=3` 控制单个部署最多同时运行三个 Agent；Celery 预取为 1，更多任务继续接受并保留 `pending / 排队中`，待执行槽释放后自动运行。不要横向扩容 `pptmaster-worker` 绕过该部署级上限。
- **注意**：Agent 以 `--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox` 运行（无人值守必需），生产环境应只在独立容器中运行 pptmaster-worker，不与业务 Worker 混跑。

### 6.1 本地容器启动

在项目根目录执行（Windows PowerShell）：

```powershell
Set-Location .\deploy
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 编辑 .env：主链路配置 QWEN/DEEPSEEK/KIMI；真实 ppt-master 配置 Agent Key、模型与兼容端点
# PPT-MASTER 模型目录：PPTMASTER_SELECTABLE_MODELS=deepseek-v4-pro,qwen3.7-plus,qwen3.8-max
# PPT-MASTER 默认模型：PPTMASTER_DEFAULT_MODEL=qwen3.7-plus
# 并发上限：PPTMASTER_MAX_CONCURRENT_JOBS=3
# 百炼示例：PPTMASTER_CLAUDE_MODEL=qwen3.7-plus
#           ANTHROPIC_AUTH_TOKEN=<API Key>
#           ANTHROPIC_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic
docker compose --profile pptmaster up -d --build
docker compose --profile pptmaster ps -a
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/readyz
Invoke-RestMethod http://localhost:8000/api/v1/pptmaster/options
docker compose exec -T pptmaster-worker sh -lc 'id && claude --version && codex --version && soffice --version'
```

默认服务是 `frontend`、`api`、`worker`、`postgres`、`redis`、`minio`、`minio-init`；启用 profile 后增加 `pptmaster-worker`。`minio-init` 完成建桶后显示 `Exited (0)` 是正常状态。访问前端 `http://localhost:8081`，API 文档 `http://localhost:8000/docs`，MinIO 控制台 `http://localhost:9001`。下载和预览由 API 后端代理 MinIO 对象，不要求浏览器直接访问 `minio` 服务名。

## 7. 验收记录（2026-08-17，本机 Windows）

- 冒烟 `backend/tests/test_pptmaster.py`：目录、提示词、Runner、Worker 侧 Agent 解析、API 延迟校验、Worker 能力展示、Base URL 规范化、非 root 镜像、Mock 端到端和进度启发式全部通过；
- API 端到端（mock）：提交 → 轮询 → 成功 → 下载/预览/日志/列表/取消/删除/参数校验 全部通过；
- **真实 Agent（Compose 分离容器）**：任务 `pm_20260817_xsyr61` 使用 Claude Code 2.1.197 + `qwen3.7-plus` 完成 topic/quick/1 页验证。API 入队、Worker 侧 Agent 解析、topic research、SVG 生成、错误修正后质检通过、PPTX 导出、MinIO 上传、PDF/PNG 预览、日志/事件流/报告下载全部成功；耗时 375 秒、40 轮、约 $2.05。下载 PPTX 为 15,743 字节，`python-pptx` 可打开且含 1 页、13 个形状、4 个文本形状；预览 PNG 为 126,298 字节。

## 8. 已知边界与后续

- 进度是启发式（事件 + 文件），不是精确百分比；
- 同一任务重试未实现（可重新提交，Agent 会话本身不可续跑，与 ppt-master Quick 契约一致）；
- URL 在 API 层只做 `http/https` 格式校验，网页抓取由 Agent 调用 ppt-master 转换器；应用层固定最多三次抓取的护栏尚未独立实现；
- 图片搜索/AI 生图、TTS 旁白依赖 ppt-master 侧的 Key 配置，未配置时 Agent 会按提示词退化并在最终回复说明；
- `ANTHROPIC_BASE_URL` 必须是绝对 `http://` 或 `https://` URL；百炼 Workspace 端点必须包含 `/apps/anthropic`，只填主机名或 OpenAI 兼容路径会得到 404；
- Worker 执行域下 API 只能从凭据判断“可能可用”，最终 CLI/仓库/模型可用性以 Worker 运行时二次校验及 Agent 日志为准；
- 后续可加：Claude Agent SDK Runner、跨多 Worker 的分布式并发租约、产物清理策略、工作区磁盘配额。
