# 后端镜像：api 与 worker 共用代码，分层原则——重依赖(apt/pip)在前、代码 COPY 在最后，
# 保证日常改代码只重建最后一层，绝不重复下载 LibreOffice/字体。
ARG PIP_INDEX_URL=https://pypi.org/simple

# ---- 系统依赖 + Python 依赖（变更频率最低） ----
FROM python:3.11-slim AS base
ARG PIP_INDEX_URL
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Shanghai
# 国内镜像优先，失败回退官方源
RUN (sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && (apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk curl) \
    || (sed -i 's|mirrors.tuna.tsinghua.edu.cn|deb.debian.org|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
        apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk curl) \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install -i ${PIP_INDEX_URL} -r requirements.txt

# ---- Worker 系统层：LibreOffice（仅此层重，代码变更不触发） ----
# 抗网络/代理抖动：镜像源逐个尝试；单源内 --fix-missing 断点续传式重试
# （apt 已下载的 .deb 会保留在缓存中，重试只补拉失败的包）
FROM base AS worker-base
RUN ok=""; \
    for m in mirrors.aliyun.com mirrors.tuna.tsinghua.edu.cn deb.debian.org; do \
        sed -i -E "s|https?://[^/ ]+/debian|http://$m/debian|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
        echo "==> 使用镜像源 $m"; \
        apt-get update || continue; \
        for i in 1 2 3 4 5; do \
            echo "==> 安装尝试 $i/5（--fix-missing 续传）"; \
            if apt-get install -y --no-install-recommends --fix-missing \
                 -o Acquire::Retries=5 libreoffice-impress; then ok=1; break; fi; \
            sleep 3; \
        done; \
        [ -n "$ok" ] && break; \
    done; \
    test -n "$ok" && rm -rf /var/lib/apt/lists/*

# ---- API 服务（代码层在最后） ----
FROM base AS api
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ---- Worker（代码层在最后） ----
FROM worker-base AS worker
COPY app ./app
CMD ["celery", "-A", "app.worker", "worker", "-Q", "generate,convert", \
     "-c", "4", "--max-tasks-per-child", "50", "--loglevel", "INFO"]
