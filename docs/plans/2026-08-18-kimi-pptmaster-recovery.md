# Kimi 接入与 PPT-MASTER 产物恢复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在新建生成与 PPT-MASTER 中接入 `kimi-k3`，让美化任务默认使用它，并把已有完整 SVG 却无 PPTX 的 PPT-MASTER 任务安全恢复为可下载成功记录。

**Architecture:** 模型目录继续由环境变量统一驱动，普通生成通过 OpenAI 兼容的 Kimi Provider 调用，PPT-MASTER 将所选 model-id 传给 Claude Code 并原样落库展示。PPT-MASTER Worker 在 Agent 未导出 PPTX、但 SVG 页数完整且退出码为 0 时，运行官方 finalize/converter 脚本做显式诊断降级导出；结果标记质量门禁绕过，不隐藏质量风险。历史失败任务复用同一恢复入口，避免一次性 SQL 与线上逻辑分叉。

**Tech Stack:** FastAPI, SQLAlchemy, Celery, OpenAI Python SDK, React/TypeScript, Vitest, pytest, Docker Compose, ppt-master scripts.

---

### Task 1: Kimi 配置与 Provider 路由

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/ai/gateway.py`
- Modify: `backend/.env.example`
- Modify: `deploy/.env.example`
- Modify: `README.md`
- Test: `backend/tests/test_model_selection.py`

**Steps:**
1. 写失败测试，要求默认目录包含 `kimi-k3`、`provider_of('kimi-k3') == 'kimi'`，并验证 Kimi 客户端使用独立 key/base URL。
2. 运行 `python -m pytest backend/tests/test_model_selection.py -q`，确认 RED。
3. 增加 `KIMI_API_KEY`、`KIMI_BASE_URL`、Kimi semaphore/breaker/client 路由；仅 Qwen 注入 `enable_thinking`。
4. 更新示例环境与 README 模型目录。
5. 重跑测试确认 GREEN。

### Task 2: 美化默认 Kimi 与前端路由联动

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/beautify_service.py`
- Modify: `backend/app/api/jobs_api.py`
- Modify: `backend/app/api/pptmaster_api.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/utils/modelOptions.ts`
- Modify: `frontend/src/utils/modelOptions.test.ts`
- Modify: `frontend/src/pages/PptMaster.tsx`
- Test: `backend/tests/test_model_selection.py`
- Test: `backend/tests/test_pptmaster.py`

**Steps:**
1. 写失败测试：`LLM_BEAUTIFY_MODEL=kimi-k3` 必须属于目录；一键美化子任务固定使用该模型；PPT-MASTER options 返回 `beautify_model`。
2. 写前端失败测试：选择 `beautify` 路线时解析为 `kimi-k3`，其他路线使用普通默认值。
3. 运行后端和前端定向测试确认 RED。
4. 实现配置校验、子任务模型覆盖、options 字段和表单路线联动。
5. 重跑定向测试确认 GREEN。

### Task 3: PPT-MASTER 完整 SVG 自动恢复导出

**Files:**
- Modify: `backend/app/pptmaster/service.py`
- Test: `backend/tests/test_pptmaster.py`

**Steps:**
1. 写失败测试：退出码 0、完整 `svg_output`、无 PPTX 时调用 finalize 与 `svg_to_pptx.py -s final`，生成有效 PPTX；页数不足时不得绕过门禁。
2. 运行 `python -m pytest backend/tests/test_pptmaster.py -q` 确认 RED。
3. 实现 `_recover_pptx_from_svgs`：校验源 SVG 数量、运行脚本、验证 PPTX 可打开且页数合理、追加恢复日志并返回审计元数据。
4. 在主流程收集产物前触发恢复；成功状态显示“SVG 降级导出，质量门禁未通过”，并把恢复详情写入 `_run`。
5. 提供 `recover_failed_pptmaster_job(job_pk)`，只允许恢复“failed + 无主 PPTX + 可用工作区”的历史任务，复用相同上传与状态更新逻辑。
6. 重跑定向测试确认 GREEN。

### Task 4: 模型列与历史数据回填

**Files:**
- Modify: `backend/app/pptmaster/service.py`
- Test: `backend/tests/test_pptmaster.py`

**Steps:**
1. 写测试确认任务 DTO 原样返回所选 model-id，前端模型列继续直接显示 `job.model`。
2. 增加受限维护函数：仅把历史 `model IS NULL` 记录回填为旧部署实际默认 `qwen3.7-plus`。
3. 验证新任务存储/展示 `kimi-k3` 等精确 model-id。

### Task 5: 全量验证、部署与历史任务修复

**Files:**
- Modify ignored runtime env: `deploy/.env`（不提交凭据）

**Steps:**
1. 运行后端完整 pytest、前端 Vitest 与 production build。
2. 检查 git diff，确保没有凭据和无关改动。
3. 合并本地分支到 `main`，重建 API、Worker、PPT-MASTER Worker、Frontend 容器。
4. 调用维护入口回填历史空模型，并恢复截图中的任务 12、14、15；保留真正失败的任务不变。
5. 验证三条记录为成功、模型列为 model-id、PPTX 页数分别匹配完整 SVG 数量，下载对象存在。
6. 检查容器健康状态和相关日志。
