# AI PPT 自动生成系统 — 文档中心

> 当前文档版本：V1.2（2026-08-18）
> 产品定位：企业模板优先、双生成引擎、可编辑交付的 AI 演示文稿平台

## 现行文档

| 文档 | 说明 |
|---|---|
| [01-PRD.md](01-PRD.md) | 产品定位、用户场景、双生成入口、三模式、模型选择、任务和验收边界 |
| [02-UI-DESIGN.md](02-UI-DESIGN.md) | 页面路由、交互流程、模型选择、任务状态、阶段提示、预览和下载 |
| [03-IMPLEMENTATION.md](03-IMPLEMENTATION.md) | 系统架构、主流水线、数据模型、API、对象存储、容器与实现边界 |
| [04-VISUAL-OPTIMIZATION.md](04-VISUAL-OPTIMIZATION.md) | 整册艺术指导、视觉分镜、布局语法、重复度控制、四边距检查、评分与美化闭环 |
| [05-PPTMASTER-INTEGRATION.md](05-PPTMASTER-INTEGRATION.md) | PPT-MASTER Agent/SVG 流水线、模型目录、模板风格语义、三并发排队与产物恢复 |
| [06-DEVELOPMENT-DEPLOYMENT.md](06-DEVELOPMENT-DEPLOYMENT.md) | 环境变量、模型 Key 来源、本地开发、Docker/生产部署、测试和运维 |

`plans/` 保存已经执行过的设计与实施计划，用于追踪决策来源，不代表当前配置；发生冲突时，以上现行文档和代码优先。

## 当前能力总览

系统提供两条互补的生成链路：

| 入口 | 实现方式 | 优势 | 典型场景 |
|---|---|---|---|
| 新建生成 | LLM 输出受控 Presentation JSON，python-pptx 确定性渲染企业模板 | 稳定、可追溯、版式和事实可控、原生元素可编辑 | 企业周报、项目汇报、批量标准化生产 |
| PPT-MASTER 生成 | Claude Code/Codex 驱动 ppt-master skill，逐页生成 SVG 后编译 DrawingML PPTX | 视觉自由度高、路线和画布丰富、关键页表现力强 | 高质量提案、自由设计、模板填充、美化和图片还原 |

此外提供模板库、AI 模板生成、任务历史/版本、在线预览、PPTX/PDF/报告下载、失败重试、历史任务一键美化和独立 PPTX 九维视觉美化。

## 模型目录

- 新建生成：`deepseek-v4-pro`、`kimi-k3`、`qwen3.7-plus`、`qwen3.8-max`；默认 `qwen3.7-plus`；一键美化子任务默认 `kimi-k3`。
- PPT-MASTER：`deepseek-v4-pro`、`qwen3.7-plus`、`qwen3.8-max`；默认 `qwen3.7-plus`。
- 所有选项来自 `.env`，前端展示并提交实际 model-id；任务列表持久化展示提交时的 model-id。

## 关键实现事实

1. 主链路三模式是三条不同 DAG：极速、标准、专业；
2. 企业模板生成已加入整册艺术指导、视觉分镜、布局语法、重复度控制和少量关键页自由设计；
3. 所有内容容器执行四边距安全区、字体、层级、密度和连续性检查；
4. PPT-MASTER 的“由上传模板决定”是可选风格，不是锁定控件；用户始终可以改选视觉风格；
5. PPT-MASTER 单部署最多三个任务同时运行，更多任务保持 `pending / 排队中`；
6. PPT-MASTER 会保存阶段历史，进行中状态可查看完整阶段链；
7. Agent 非零退出或超时时，只要工作区已有完整可打开的 PPTX，Worker 会恢复产物并按成功交付；用户主动取消仍保持 `canceled`；
8. 默认 Compose 有七个服务项（其中 `minio-init` 为一次性容器），启用 `pptmaster` profile 后增加独立 Worker。

## 截图

| 页面 | 说明 |
|---|---|
| ![新建生成](images/new-generation.png) | 企业模板选择、预览与三步生成入口 |
| ![PPT-MASTER](images/pptmaster-generation.png) | 多输入、多路线、模型、画布与视觉风格配置 |
| ![PPT 美化](images/ppt-beautify.png) | 上传 PPTX、九维评分、确定性修复与历史下载 |
| ![模板库](images/template-library.png) | 个人模板、AI 模板、预览、下载和批量管理 |

## 快速入口

```powershell
Set-Location .\deploy
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose --profile pptmaster up -d --build
```

Web：<http://localhost:8081>；Swagger：<http://localhost:8000/docs>。完整配置和上线注意事项见 [开发、配置与部署](06-DEVELOPMENT-DEPLOYMENT.md)。
