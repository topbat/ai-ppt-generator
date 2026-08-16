# AI PPT 自动生成系统 — 文档索引

> 产品定位：Template-driven AI Presentation Generator（模板驱动的 AI PPT 生成引擎）
> 版本：V1.0（2026-08-13）

## 文档清单

| 文档 | 内容 |
|---|---|
| [01-PRD.md](01-PRD.md) | 产品需求文档：背景与定位、5 项核心输入、三模式产品定义、事实保障、兜底要求、失败与重试、存储与预览、耗时记录、非功能需求、验收标准、里程碑 |
| [02-UI-DESIGN.md](02-UI-DESIGN.md) | UI 规划与原型：信息架构、核心流程、8 个页面 ASCII 原型（列表/三步向导/进度页/成功预览/失败页/模板库）、状态-UI 映射、SSE 协议约定、视觉规范 |
| [03-IMPLEMENTATION.md](03-IMPLEMENTATION.md) | 整体实现方案：容器化架构、技术选型、工程目录、模块设计、三模式流水线 DAG、流程设计（时序/断点重试/并行拓扑）、状态机与错误码、16 张表 DDL、API 设计、存储与预览、QA 与修复闭环、docker-compose 部署、可观测性、风险对策、实施顺序 |
| [04-VISUAL-OPTIMIZATION.md](04-VISUAL-OPTIMIZATION.md) | 视觉优化（第二阶段，已落地）：Design Token 体系、12 列网格与锚线、九维视觉评分模型、Fix Ops 受控 DSL、BEAUTIFY 优化闭环、Vision Critic、历史任务一键美化、实现状态与验收记录 |

## 一句话摘要

用户提供 **PPT 模板 + 主说明文档(PDF/DOCX) + 页数 + 模式(极速/标准/专业，默认极速) + 内容密度** 5 项输入；系统通过 **解析 → 知识建模 → 大纲 → 页面规划 → 并行内容生成 → 模板匹配 → python-pptx 渲染 → 质检修复 → MinIO/OSS 归档** 的异步流水线，在分钟级产出可编辑、可预览、可追溯、可重试的 PPTX。

## 核心设计决策（速览）

1. **AI 与渲染解耦**：AI 只产出受控的 Presentation JSON 中间层，python-pptx 做确定性渲染；
2. **三模式 = 三条 DAG**：极速（章节批量+规则QA，4~5 次 LLM 调用/10页）、标准（页级并行+度量QA+1轮修复）、专业（RAG取证+Vision QA+3轮修复+冲突交互）；
3. **Guard 层独立**：Input/Template/Fact/Outline/Page/Content/Layout/Render 八类校验集中管理，配 Fallback Matrix，单点异常不失败整体；
4. **异步 Job + 阶段 checkpoint**：秒回 job_id，SSE 推送阶段与页级进度（边生成边看），失败断点重试；
5. **全链路计时**：Job 级 + Stage 级（含并行分支）+ LLM 调用级三层耗时全落库；
6. **国内模型优先**：Qwen + DeepSeek 双 Provider，网关级路由/熔断/自动切换；
7. **全容器化**：frontend / api / worker(内置 LibreOffice) / postgres(pgvector) / redis / minio / minio-init 七个服务，docker compose 一键部署，Worker 副本数即扩容点；
8. **视觉优化第二阶段**（[04 文档](04-VISUAL-OPTIMIZATION.md)）：九维视觉评分规则引擎 + BEAUTIFY 确定性美化闭环 + 一键美化，质量分管"对不对"、视觉分管"好不好看"。
