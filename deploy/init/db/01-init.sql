-- 预装 pgvector 扩展（V1 用 JSON 存 embedding，规模化后切换 vector 类型时无需再迁移）
CREATE EXTENSION IF NOT EXISTS vector;
