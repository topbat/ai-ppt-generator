# 模型选择、模板风格锁定与 PPT-MASTER 队列设计

## 目标

“新建生成”和“PPT-MASTER 生成”均从后端环境配置读取可选模型，并要求用户在实际 model_id `deepseek-v4-pro`、`qwen3.7-plus`、`qwen3.8-max` 中选择一个。前端原样显示 model_id。PPT-MASTER 的模板填充路线由上传的 PPTX 决定视觉风格；任务列表展示模型与完整阶段轨迹；生成任务最多同时运行三个，其余任务继续接受并排队。

## 配置与模型数据流

新增 `LLM_SELECTABLE_MODELS` 和 `LLM_DEFAULT_SELECTABLE_MODEL`。后端将逗号分隔配置解析成唯一、有序的模型目录，并同时提供给 `/jobs/options` 与 `/pptmaster/options`。前端只渲染接口返回的数据，不保存模型常量。两个创建接口都要求模型非空并进行白名单校验。

普通生成在 `generation_jobs.model` 中持久化选择，通过 `JobContext.model` 显式传入每次 Gateway 调用。模型覆盖模式只重试用户所选模型，不自动切换到其他模型，保证任务记录与实际调用一致。DeepSeek 前缀走 DeepSeek Provider，其余两个 Qwen 模型走 Qwen Provider。

## PPT-MASTER 行为

模板填充路线将 `style` 强制改为 `template`。前端显示“由上传的 PPTX 模板决定”并禁用控件，后端也执行同样的覆盖，防止绕过界面。提示词明确要求保留模板配色、字体、版式与视觉语言。

任务阶段沿用 `params` JSON 存储 `_stage_history`，所有阶段更新通过同一入口追加，连续重复项去重。DTO 提供独立 `stage_history`，列表状态单元格用 ` --> ` 拼接为悬浮提示；模型使用独立列展示。

## 并发与排队

`PPTMASTER_MAX_CONCURRENT_JOBS` 默认值为 3，并用于 PPT-MASTER Celery Worker 的并发参数。Worker 预取仍为 1，因此最多三个任务进入运行状态，其余消息留在 Redis 队列，对应数据库任务保持 `pending / 排队中`。当前部署保持单个 PPT-MASTER Worker，不通过横向扩容突破全局上限。

## 兼容与验证

数据库初始化使用幂等 `ADD COLUMN IF NOT EXISTS` 增加普通生成模型列。历史任务允许模型为空，但新建任务必须选择。验证覆盖配置解析、白名单校验、任务级 Gateway 路由、模板风格锁定、阶段历史去重、Docker 并发参数、前端纯逻辑测试、后端完整回归和前端生产构建。
