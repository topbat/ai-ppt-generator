# Langfuse 真实部署与验收方案

用户已将范围从模拟验收扩展为容器化部署和真实后端联通。本方案接续已完成的指标采集、数据库、API 和中文展示功能。

## 方案

按用户最新要求，所有服务统一归入 `ppt-generator`：新增 Langfuse 4 Web/Worker、ClickHouse 25.12 和一次性初始化服务。共享现有 PostgreSQL 16、Redis 7、MinIO 容器；分别使用专用数据库/账号、Redis DB 4 和 langfuse 桶隔离数据。ClickHouse 单独持久化。业务 API 和 Worker 经同组默认网络访问 langfuse-web:3000，无需额外网络或第二个长期运行的容器组。已有业务环境连接保持原设置，避免切换数据库影响历史任务。

初始化脚本创建随机密钥、管理员、项目及访问令牌，写入忽略提交的环境文件；再次执行保留密钥。业务配置默认不采集模型输入和输出正文。当前 Docker 约 8 GiB 内存且有其他项目运行，因此本地业务 Worker 并发设为 1，ClickHouse 限制线程和内存；这属于本机验收配置，生产容量需单独规划。

## 任务与验收

1. 编写 Compose、初始化脚本、业务网络覆盖配置，启动并验证所有依赖健康。
2. 重建 API、两类 Worker 与前端，把已有实现运行在真实容器里。
3. 使用已配置模型凭据进行受控真实请求，验证标准 Gateway 和 Claude CLI 运行器均形成真实用量；不使用模拟模型数据作为上报证据。
4. 对照业务 PostgreSQL 记录、Langfuse 观测、ClickHouse 数据和远端 Metrics API，修复协议及字段差异。
5. 运行回归测试、生产构建、鉴权及筛选验证；浏览器检查真实指标页、Langfuse 观测详情并截图。
6. 输出中文测试报告、截图和可复用启停命令；明确调用级/运行级统计区别与未覆盖的业务流程。

验收以真实调用和真实观测闭环为准。PPT 内容质量、全部模型能力和高并发压测不属于这次指标功能验收。

## 参考

- https://langfuse.com/self-hosting/deployment/docker-compose
- https://langfuse.com/self-hosting/administration/headless-initialization
- https://langfuse.com/docs/api-and-data-platform/features/public-api

## 执行结果

上述 6 项任务已完成。Web、Worker、ClickHouse 均健康；实际调用和本地/远端对账通过。完整结果、统计边界及截图见[测试报告](../../deliverables/langfuse-live-2026-09-10/report.md)。
