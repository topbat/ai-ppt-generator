# LLM 指标与 Langfuse 使用说明

本功能覆盖标准 PPT 流水线与 PPT-MASTER。项目内页面使用本地新增观测表，Langfuse 区域单独查询远端聚合。二者不相加。

## 0. 容器化自托管（同一 ppt-generator 容器组）

Langfuse Web、Langfuse Worker 和 ClickHouse 加入现有 `ppt-generator` Compose 项目。共享现有 Redis、MinIO、PostgreSQL 容器：Langfuse 使用 Redis DB 4、`langfuse` 存储桶、`langfuse` 数据库及独立 `ppt_langfuse` 账号。一次性 `langfuse-init` 服务幂等创建数据库和桶。原有业务环境文件的数据库/队列/存储连接保持原设置。

在项目根目录执行（先确保 `deploy/.env` 已配置真实模型）：

```powershell
python deploy/langfuse/init.py
# 先构建本项目镜像，初始化服务复用 API 镜像中的数据库和 S3 客户端。
docker compose -f deploy/docker-compose.yml --profile pptmaster build
# 必须合并两个文件，并加载 Langfuse 凭据；项目名仍为 ppt-generator。
docker compose --env-file deploy/langfuse/.env -f deploy/docker-compose.yml -f deploy/docker-compose.langfuse.yml --profile pptmaster up -d --no-build
```

Langfuse 地址 `http://localhost:3000`，账户 `admin@ppt.local`。密码是 `deploy/langfuse/.env` 的 `ADMIN_PASSWORD`，指标页令牌是同文件的 `METRICS_ACCESS_TOKEN`。项目 ID 为 `ppt-local-project`。脚本自动更新业务环境中的连接参数，再次执行保留现有随机凭据。环境文件被 Git 忽略，不应上传到工单、截图或版本库。

业务上报使用内部地址 `http://langfuse-web:3000`，浏览器追踪链接使用 `http://localhost:3000`。MinIO 沿用现有 9000/9001 端口，ClickHouse 不发布主机端口。若修改了原 Compose 的 MinIO 根凭据，在 Langfuse 环境文件同步设置 `LF_S3_ACCESS_KEY_ID`、`LF_S3_SECRET_ACCESS_KEY`。Langfuse 与业务共享 Redis 进程，因此停机和内存压力会共同影响两者；DB 4 用于键隔离，不代表资源隔离。

```powershell
# 查看健康状态，不公开包含凭据的完整 config 输出。
docker compose --env-file deploy/langfuse/.env -f deploy/docker-compose.yml -f deploy/docker-compose.langfuse.yml --profile pptmaster ps
# 单独停止观测服务，保留共享依赖及所有数据卷。
docker compose --env-file deploy/langfuse/.env -f deploy/docker-compose.yml -f deploy/docker-compose.langfuse.yml stop langfuse-web langfuse-worker clickhouse
```

如果本机已有本项目旧运行镜像，且系统软件源下载不稳定，可选择增量构建：复用原有系统工具，重新安装当前 `requirements.txt` 并复制当前 `app`。不适用于空白机器或升级系统工具。

```powershell
# 仅首次升级前保存基底，不要在每次重建时覆盖。
docker image tag ppt-generator-api:latest ppt-generator-api:pre-langfuse
docker image tag ppt-generator-worker:latest ppt-generator-worker:pre-langfuse
docker image tag ppt-generator-pptmaster-worker:latest ppt-generator-pptmaster-worker:pre-langfuse
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.incremental.yml build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple api worker pptmaster-worker frontend
# 然后按上面的两个 Compose 文件启动即可。
```

本机验收将两个业务 Worker 并发设为 1；生产应按请求量调整资源、访问控制与备份策略。方案见 [真实部署计划](plans/2026-09-10-langfuse-live.md)。

## 1. 本地指标启用

在实际使用的 `backend/.env`（直接运行）或 `deploy/.env`（Compose）中设置足够长的随机令牌：

```dotenv
METRICS_ACCESS_TOKEN=替换为独立随机令牌
LANGFUSE_ENABLED=false
LANGFUSE_CAPTURE_CONTENT=false
```

更新依赖后重启 API 与执行生成的 Worker。启动初始化会通过 `create_all` 新建 `llm_observations`，不会修改或删除旧 `llm_calls`，也不会把旧记录回填成虚构调用链。Compose 的 API、worker、pptmaster-worker 已共用 `deploy/.env`，不需要额外改动 Compose 环境传递。

进入顶部 **LLM 用量** 菜单（`/metrics`），输入指标访问令牌。标准任务详情和 PPT-MASTER 详情也有 **模型消耗** 面板。前端只在当前页面内存保存令牌，刷新或退出后清除；不要把 Langfuse 的 Secret Key 当作页面访问令牌。

未配置访问令牌时新指标接口返回 503，错误令牌返回 401。这是独立的指标访问控制，不是多租户身份认证；项目现有业务接口的权限模型没有因此改变。若部署到公网，按现有系统要求使用 HTTPS 和上游访问控制。

## 2. 连接 Langfuse

准备一个独立 Langfuse Cloud 或自托管项目，把配置写入同一个后端环境文件：

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=填写项目公钥
LANGFUSE_SECRET_KEY=填写项目私钥
LANGFUSE_PROJECT_ID=填写项目ID
LANGFUSE_UI_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_CONTENT=false
ENV=production
```

`BASE_URL` 是服务端和 Worker 可访问的地址；`UI_URL` 是浏览器可访问的地址，留空则沿用前者；`PROJECT_ID` 用于构造追踪链接。所有生成服务的 `ENV` 应一致，不同部署环境使用不同值，远端查询会固定过滤当前环境。

本次接入采用显式 Langfuse generation/span API；依赖固定为已验证的 SDK 4.15.2，Metrics 使用 `/api/public/v2/metrics`。应配合支持 Metrics v2 的服务端。较旧自托管版本如不支持 v2，远端区域会显示兼容性错误，本地页面仍可用。

SDK 批量异步上报，API/Worker 退出时进行刷新。上报/本地计量写入失败只记录通用警告，不替换业务异常；最佳努力模式不保证进程被强杀时的最后一批事件必达，也不提供离线补传队列。

调用链按引擎、环境和任务主键生成稳定 Trace ID。标准流水线包含阶段 span，阶段内部实际请求记录为 generation；并行阶段和页面内容线程显式传播上下文。PPT-MASTER 一次 CLI 运行是一条 `agent_run`，续跑使用新的运行记录但仍在同一任务 Trace 中。

## 3. 指标解释

| 指标 | 口径 |
|---|---|
| 请求尝试 | 标准模型实际 SDK 请求次数，含失败、重试、参数兼容重试 |
| Agent 运行 | CLI 启动运行次数，不等于 Agent 内部 LLM 请求次数 |
| 成功率 | 当前记录粒度的成功比例，不代表最终 PPT 交付成功率 |
| 重试 / 续跑 | 同一逻辑调用首个请求之后的实际请求，或任务第二次 CLI 运行 |
| 输入 Token | 包含已知缓存读取/写入的输入总量 |
| 未知用量 | 上游未返回输入或输出 Token；不按 0 计 |
| 部分用量 | 中断运行仅能从已收到事件恢复部分消耗；详情明确标记 |
| 请求耗时 | SDK 调用时间，不包含并发队列等待、观测写库时间 |
| 排队耗时 | 网关并发信号量等待；不等于 Celery 任务排队时间 |
| P50/P95 | 所选本地记录耗时的离散分位数，单位毫秒 |
| 已知费用 | 有数据记录的费用之和；有未知记录时不代表完整总费用 |

Claude 优先使用最终 result 的 usage；无 result 时，按 assistant message ID 去重汇总已知快照，并标记部分用量。Codex 累加 `turn.completed` 的用量；中断且已有用量时标记部分用量。缓存字段支持 OpenAI/Qwen 的 `prompt_tokens_details.cached_tokens`、DeepSeek 的 `prompt_cache_hit_tokens`、Codex 的 `cached_input_tokens` 和 Anthropic 缓存读写字段。

默认不采集提示词、正文或图片；本地账本始终只保存指标。开启 `LANGFUSE_CAPTURE_CONTENT` 后标准请求的 messages 和响应正文会发送给 Langfuse，可能包含业务材料与图片。PPT-MASTER 汇总不上传 CLI 全部日志或提示词。

## 4. 可选费用估算

本地费用优先使用 CLI 明确报告的 USD 成本。标准调用可以配置模型单价，单位是 **美元 / 一百万 Token**：

```dotenv
LLM_PRICES_JSON='{"your-model":{"input":2,"output":8,"cached":0.2,"cache_creation":3}}'
```

这里只是格式示例，不是实际模型报价。`input`、`output` 必填；发生缓存命中/写入时需要对应价格，缺失则费用仍未知。没有匹配模型、usage 不完整或只拿到中断部分用量时，不冒充完整估算。前端明细对估算费用加标签。

Langfuse 也有自己的模型价格配置，远端费用可能与本地估算不同；它也可能对没有用量的记录返回聚合 0，因此本地的未知数量仍应作为完整性依据。

## 5. API

所有请求携带 `Authorization: Bearer <METRICS_ACCESS_TOKEN>`。

- `GET /api/v1/metrics/summary`：本地总览、按模型/阶段/UTC 日期汇总、P50/P95。
- `GET /api/v1/metrics/observations`：分页明细和可选 Langfuse Trace 链接。
- `GET /api/v1/metrics/remote`：Langfuse Metrics v2 聚合，固定引擎/环境过滤，5 秒请求超时、30 秒有界进程内缓存。

公共参数：`days=1..90`、`engine=pipeline|pptmaster`、`model=模型完整名称`、`job=任务业务ID`。明细支持 `page=1..10000`、`page_size=1..100`。远端任务过滤会解析业务 ID 为对应的 Trace ID，不接受任意远端 URL 或任意 query。返回包裹格式与现有 API 一致。

## 6. 复现页面验收

以下使用独立内存数据库，不读取生产环境文件或调用模型：

```powershell
# 后端测试环境中安装 requirements.txt 和 pytest 后
python backend/tests/metrics_preview.py

# 另一个终端
$env:VITE_API_TARGET='http://127.0.0.1:8017'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5177
```

访问 `http://127.0.0.1:5177/metrics`，输入演示令牌 `preview-only`。示例数据的模型名带 `demo`，不能作为真实用量证据；该服务只用于本地页面验收，不可作为部署入口。

上面的演示页面只用于开发。真实验收应使用容器化实例、真实模型调用和实际 PostgreSQL/ClickHouse 数据；执行脚本 `backend/tests/live_observability_probe.py` 会消耗真实模型 Token，不会创建虚构 PPT 任务。标准路径按请求记录，Claude 路径按一次 CLI 运行记录，不能将该探针测试解释为完整 PPT 生成质量验收。

## 7. 已完成的真实部署验收

2026-09-10 已在 `ppt-generator` 内完成 Langfuse Web/Worker 与 ClickHouse 部署，共享 PostgreSQL、Redis 和 MinIO。后端 120 项、前端 11 项测试通过，真实 Gateway 与 Claude CLI 的本地/远端 Token 对账通过。详见[中文测试报告与实际截图](../deliverables/langfuse-live-2026-09-10/report.md)。
