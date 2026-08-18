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
    for m in mirrors.tuna.tsinghua.edu.cn deb.debian.org mirrors.aliyun.com; do \
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


# ---- ppt-master Worker（可选，compose profile: pptmaster）----
# 在 worker-base 之上再装：git + Node.js 20（二进制包，npmmirror 优先/官方回退）+ Claude Code / Codex CLI，
# 并克隆 hugohe3/ppt-master（剔除 800MB 示例）及其 Python 依赖；运行时以子进程驱动 Agent 在 /opt/ppt-master 内执行工作流。
# 需要在 .env 提供 ANTHROPIC_API_KEY（或 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN）与/或 OPENAI_API_KEY 供 CLI 使用。
FROM worker-base AS pptmaster-worker
ARG PIP_INDEX_URL
ARG PPTMASTER_REF=v4.8.0
ARG NODE_VERSION=20.19.0
ARG NODE_DIST_MIRROR=https://npmmirror.com/mirrors/node
ARG NPM_REGISTRY=https://registry.npmmirror.com
# 1) git（apt 抖动重试）
RUN ok=""; \
    for i in 1 2 3; do \
        apt-get update && apt-get install -y --no-install-recommends --fix-missing \
            -o Acquire::Retries=5 git ca-certificates xz-utils && ok=1 && break; \
        sleep 5; \
    done; \
    test -n "$ok" && rm -rf /var/lib/apt/lists/*
# 2) Node.js 二进制（镜像优先，官方回退）
RUN set -e; f="node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    (curl -fsSL "${NODE_DIST_MIRROR}/v${NODE_VERSION}/${f}" -o /tmp/node.tar.xz \
     || curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${f}" -o /tmp/node.tar.xz) \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 && rm /tmp/node.tar.xz \
    && node --version && npm --version
# 3) Agent CLI（构建期即校验可执行）
RUN npm config set registry ${NPM_REGISTRY} \
    && npm install -g @anthropic-ai/claude-code @openai/codex \
    && claude --version && codex --version && npm cache clean --force
# 4) ppt-master 仓库（稀疏克隆，无示例；GitHub 抖动重试 3 次）+ 其 Python 依赖
RUN ok=""; \
    for i in 1 2 3; do \
        rm -rf /opt/ppt-master; \
        git clone --filter=blob:none --sparse --depth 1 --branch ${PPTMASTER_REF} \
            https://github.com/hugohe3/ppt-master.git /opt/ppt-master \
        && git -C /opt/ppt-master sparse-checkout set --no-cone '/*' '!/examples' '!/docs/assets' \
        && test -f /opt/ppt-master/skills/ppt-master/SKILL.md && ok=1 && break; \
        echo "==> 克隆 ppt-master 失败，重试 $i/3"; sleep 5; \
    done; test -n "$ok" \
    && pip install -i ${PIP_INDEX_URL} -r /opt/ppt-master/skills/ppt-master/requirements.txt
# Claude Code 禁止 root 使用 --dangerously-skip-permissions；独立低权限用户同时消除 Celery root 警告。
RUN groupadd --gid 10001 pptmaster \
    && useradd --uid 10001 --gid pptmaster --create-home --home-dir /home/pptmaster \
       --shell /bin/sh pptmaster \
    && mkdir -p /opt/ppt-master/projects \
    && chown -R pptmaster:pptmaster /opt/ppt-master /home/pptmaster
ENV PPTMASTER_REPO_DIR=/opt/ppt-master
ENV HOME=/home/pptmaster
ENV PPTMASTER_MAX_CONCURRENT_JOBS=3
COPY --chown=pptmaster:pptmaster app ./app
USER pptmaster
# 单容器并发最多 3；多出的消息留在 Redis 队列，任务保持 pending，等待空闲执行槽。
CMD ["sh", "-c", "exec celery -A app.worker worker -Q pptmaster -c \"${PPTMASTER_MAX_CONCURRENT_JOBS:-3}\" --max-tasks-per-child 10 --loglevel INFO"]
