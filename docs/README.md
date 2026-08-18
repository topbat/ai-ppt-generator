# AI PPT 自动生成系统 — 文档索引

> 产品定位：Template-driven AI Presentation Generator（模板驱动的 AI PPT 生成引擎）
> 版本：V1.1（2026-08-17，按当前代码同步）

## 文档清单

| 文档 | 内容 |
|---|---|
| [01-PRD.md](01-PRD.md) | 产品需求文档：背景与定位、5 项核心输入、三模式产品定义、事实保障、兜底要求、失败与重试、存储与预览、耗时记录、非功能需求、验收标准、里程碑 |
| [02-UI-DESIGN.md](02-UI-DESIGN.md) | UI 信息架构与当前页面：任务列表、三步生成、任务详情、模板库、PPT 美化、ppt-master 生成、状态映射与 SSE 约定 |
| [03-IMPLEMENTATION.md](03-IMPLEMENTATION.md) | 整体实现方案与实现边界：容器化架构、三模式流水线、状态/错误码、当前 15 张 ORM 表、API、对象存储、QA/美化、Compose 运行方式与未落地的运维能力 |
| [04-VISUAL-OPTIMIZATION.md](04-VISUAL-OPTIMIZATION.md) | 视觉优化（第二阶段，已落地）：Design Token 体系、12 列网格与锚线、九维视觉评分模型、Fix Ops 受控 DSL、BEAUTIFY 优化闭环、Vision Critic、历史任务一键美化、实现状态与验收记录 |
| [05-PPTMASTER-INTEGRATION.md](05-PPTMASTER-INTEGRATION.md) | ppt-master 独立集成：API/Worker/队列/Agent/产物链路、容器资源、运行配置与真实 Agent 验收 |

## 一句话摘要

用户提供 **PPT 模板 + 主说明文档(PDF/DOCX) + 页数 + 模式(极速/标准/专业，默认极速) + 内容密度** 5 项输入；系统通过 **解析 → 知识建模 → 大纲 → 页面规划 → 并行内容生成 → 模板匹配/模板页克隆 → python-pptx 渲染 → 质检修复 → MinIO/OSS 归档** 的异步流水线，在分钟级产出可编辑、可预览、可追溯、可重试的 PPTX。

## 核心设计决策（速览）

1. **AI 与渲染解耦**：AI 只产出受控的 Presentation JSON 中间层，python-pptx 做确定性渲染；
2. **三模式 = 三条 DAG**：极速（章节批量+规则QA）、标准（页级并行+视觉闭环+度量QA+修复）、专业（事实冲突交互+可选 Vision QA+视觉闭环+修复）；专业模式的 `DocChunk`/embedding 目前是模型骨架，尚未执行完整向量 RAG；
3. **Guard 层独立**：Input/Template/Fact/Outline/Page/Content/Layout/Render 八类校验集中管理，配 Fallback Matrix，单点异常不失败整体；
4. **异步 Job + 阶段 checkpoint**：秒回 job_id，SSE 推送阶段与页级进度（边生成边看），失败断点重试；
5. **全链路计时**：Job 级 + Stage 级（含并行分支）+ LLM 调用级三层耗时全落库；
6. **国内模型优先**：Qwen + DeepSeek 双 Provider，网关级路由/熔断/自动切换；
7. **全容器化**：默认 7 个服务（frontend / api / worker / postgres / redis / minio / minio-init），启用 `pptmaster` profile 后增加独立 `pptmaster-worker`；`minio-init` 是一次性初始化容器，LibreOffice 内置在 Worker 镜像中；
8. **视觉优化第二阶段**（[04 文档](04-VISUAL-OPTIMIZATION.md)）：九维视觉评分规则引擎 + BEAUTIFY 确定性美化闭环 + 一键美化，质量分管"对不对"、视觉分管"好不好看"。

## 当前实现边界

- 当前 ORM 实际定义 15 张表，数据库使用 `create_all` 与少量幂等增量列，不是文档最初规划的 16 张 DDL/Alembic 方案；
- 模板页 XML 克隆已经实现，README 中“V2 才支持模板 XML 克隆”的旧描述已废弃；
- 扫描件 OCR、真正的向量 RAG、Prometheus/Grafana、自动清理、用户并发配额、认证/多租户尚未实现；
- ppt-master 已采用 Worker 执行域：API 接受任务并按凭据展示能力，`pptmaster-worker` 领取任务后重新探测 CLI/仓库并解析 `auto`；真实 Claude Code + `qwen3.7-plus` 的 Compose 端到端链路已验证。

## 本地容器入口

```powershell
Set-Location deploy
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d --build
docker compose --profile pptmaster up -d --build
docker compose --profile pptmaster ps -a
```

主链路入口为 `http://localhost:8081`，Swagger 为 `http://localhost:8000/docs`，MinIO 控制台为 `http://localhost:9001`。完整配置项、健康检查和真实 Agent 前提见 [README.md](../README.md) 与 [05-PPTMASTER-INTEGRATION.md](05-PPTMASTER-INTEGRATION.md)。
