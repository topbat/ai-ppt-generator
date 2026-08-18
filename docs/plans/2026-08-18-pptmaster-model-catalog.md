# PPT-MASTER 独立模型目录 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 PPT-MASTER 页面和提交接口只允许 `deepseek-v4-pro`、`qwen3.7-plus`、`qwen3.8-max`，同时不影响新建生成的四模型目录。

**Architecture:** 在全局 Settings 中增加 PPT-MASTER 专用模型目录与默认值，通过专用解析/校验函数同时驱动 `/pptmaster/options` 和任务创建接口。前端继续完全消费 options 返回的 model-id，不添加硬编码过滤；PPT-MASTER 美化默认回落到 `qwen3.7-plus`。

**Tech Stack:** FastAPI, Pydantic Settings, React/TypeScript, pytest, Vitest, Docker Compose.

---

### Task 1: 写模型目录回归测试

**Files:**
- Modify: `backend/tests/test_model_selection.py`
- Modify: `backend/tests/test_pptmaster.py`

**Steps:**
1. 新增测试证明普通生成仍返回四模型。
2. 新增测试要求 PPT-MASTER options 只返回三个 model-id，默认与美化默认均为 `qwen3.7-plus`。
3. 新增测试要求 PPT-MASTER 提交 `kimi-k3` 时被拒绝。
4. 运行定向测试并确认因专用目录尚未实现而失败。

### Task 2: 实现后端独立目录与环境配置

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/pptmaster_api.py`
- Modify: `backend/.env.example`
- Modify: `deploy/.env.example`
- Modify: `README.md`

**Steps:**
1. 增加 `PPTMASTER_SELECTABLE_MODELS`、`PPTMASTER_DEFAULT_MODEL` 及解析/校验函数。
2. 修改 PPT-MASTER options 和 create API 使用专用函数。
3. 更新环境示例和 README。
4. 运行定向测试确认通过。

### Task 3: 验证、提交、合并和部署

**Files:**
- Modify ignored runtime env: `backend/.env`
- Modify ignored runtime env: `deploy/.env`

**Steps:**
1. 运行后端完整测试、前端测试和生产构建。
2. 提交功能分支并快进合并到本地 `main`。
3. 更新两个运行时 `.env` 的 PPT-MASTER 专用目录。
4. 使用 Docker Compose 强制重建 API、Worker、PPT-MASTER Worker 和 Frontend 镜像及容器。
5. 验证 API options、容器健康状态和运行日志。
