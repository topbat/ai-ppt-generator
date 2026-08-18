# Documentation and Open-Source Release Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 以当前代码和运行环境为唯一事实来源，同步全部现行文档，补齐 README 的开发、部署、截图与许可信息，并以 MIT 许可证开放项目代码。

**Architecture:** 保留 `docs/plans/` 作为历史决策记录，不追改已经完成的历史方案；更新 `docs/01` 至 `docs/05` 与 `docs/README.md` 作为现行产品、UI、实现、视觉优化和 PPT-MASTER 集成说明。README 作为项目入口，只保留读者首次使用需要的概要，并链接到详细文档。功能截图从本地实际运行系统采集，保存到 `docs/images/`，不使用示意图。

**Tech Stack:** Markdown、React 18 / TypeScript / Vite、FastAPI / Celery / PostgreSQL / Redis / MinIO、Docker Compose、agent-browser、MIT License

---

## Task 1: 建立代码事实清单

**Files:**
- Inspect: `frontend/src/App.tsx`
- Inspect: `backend/app/main.py`
- Inspect: `backend/app/core/config.py`
- Inspect: `backend/app/worker.py`
- Inspect: `deploy/docker-compose.yml`

1. 汇总页面路由、API 路由、模型目录、任务状态、Worker 队列、容器服务与配置入口。
2. 对照现有文档，标记过期、缺失或与代码冲突的描述。
3. 所有密钥只记录变量名和用途，不读取或写入真实值。

## Task 2: 同步现行 docs 文档

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/01-PRD.md`
- Modify: `docs/02-UI-DESIGN.md`
- Modify: `docs/03-IMPLEMENTATION.md`
- Modify: `docs/04-VISUAL-OPTIMIZATION.md`
- Modify: `docs/05-PPTMASTER-INTEGRATION.md`

1. 补齐双生成入口、独立美化、模板库、任务历史与预览下载能力。
2. 记录普通生成与 PPT-MASTER 的模型目录、真实路由方式和密钥来源。
3. 记录 PPT-MASTER 三并发排队、阶段历史、产物恢复、URL 重试和视觉风格可编辑语义。
4. 在文档索引中明确现行文档与历史计划的边界。

## Task 3: 加入开源许可

**Files:**
- Create: `LICENSE`
- Modify: `frontend/package.json`
- Modify: `README.md`

1. 使用 OSI 发布的标准 MIT License 文本。
2. 将前端包元数据标记为 `MIT`。
3. 说明第三方依赖和内置/拉取的 ppt-master 仍遵循各自许可证。

## Task 4: 采集实际功能截图

**Files:**
- Create: `docs/images/*.png`

1. 从 `http://localhost:8081` 采集任务、新建生成、模板库、PPT 美化和 PPT-MASTER 页面。
2. 避免截图中出现 API Key、访问令牌或不必要的私有材料。
3. 逐张检查清晰度、裁切和页面状态。

## Task 5: 重构项目 README

**Files:**
- Modify: `README.md`

1. 增加项目定位、两种生成路线、功能矩阵与截图说明。
2. 增加 Docker 快速启动、本地开发、生产部署、模型配置、运维和测试说明。
3. 增加许可证与第三方组件声明，并链接详细文档。

## Task 6: 验证

1. 运行 Markdown 相对链接检查与 `git diff --check`。
2. 运行后端测试、前端测试和前端构建。
3. 校验 Docker Compose 配置并确认本地服务健康。
4. 审阅最终差异，确保没有真实密钥、占位内容或与代码冲突的描述。
