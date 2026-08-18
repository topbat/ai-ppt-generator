"""全局配置：全部通过环境变量注入，禁止在业务代码中散落魔法值。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础 ----
    app_name: str = "ppt-generator"
    env: str = "dev"
    log_level: str = "INFO"

    # ---- 数据库 / Redis ----
    database_url: str = "postgresql+psycopg2://ppt:ppt@postgres:5432/ppt"
    redis_url: str = "redis://redis:6379/0"

    # ---- 对象存储 (S3 协议, MinIO / 阿里云 OSS 通用) ----
    storage_backend: str = "minio"          # minio | oss
    s3_endpoint: str = "http://minio:9000"  # 容器内部访问地址
    s3_public_endpoint: str = "http://localhost:9000"  # 浏览器可达地址(预签名URL用)
    s3_bucket: str = "ppt-gen"
    s3_access_key: str = "pptadmin"
    s3_secret_key: str = "pptadmin123"
    s3_region: str = "us-east-1"
    presign_expires: int = 3600

    # ---- LLM: 国内模型优先 (Qwen + DeepSeek + Kimi) ----
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    llm_max_concurrency_per_provider: int = 8   # Provider 级并发信号量(多任务共享)
    llm_timeout_seconds: int = 90
    llm_max_retries: int = 2                    # 单次调用重试上限(含切换备用 Provider)
    llm_mock: bool = False                      # 无 API Key 时可开启, 用于本地联调

    # ---- 具体模型选择（deepseek* / kimi* 按前缀路由，其余 → Qwen）----
    llm_model_fast: str = "qwen-flash"          # 极速模式主力（页面文案/摘要）
    llm_model_standard: str = "qwen-plus"       # 标准模式主力
    llm_model_premium: str = "qwen-max"         # 专业模式主力
    llm_model_reasoner: str = "deepseek-reasoner"  # 复杂推理（专业模式大纲/修复）
    llm_model_fallback: str = "deepseek-chat"   # 备用通道（主通道失败自动切换）
    llm_model_vision: str = "qwen-vl-max"       # Vision QA（专业模式视觉审查）
    llm_selectable_models: str = "deepseek-v4-pro,kimi-k3,qwen3.7-plus,qwen3.8-max"
    llm_default_selectable_model: str = "qwen3.7-plus"
    llm_beautify_model: str = "kimi-k3"

    # ---- 任务控制 ----
    job_timeout_fast: int = 300
    job_timeout_standard: int = 900
    job_timeout_premium: int = 1800
    user_max_concurrent_jobs: int = 3
    decision_timeout_seconds: int = 600         # 用户决策超时(超时按默认策略)
    content_parallelism: int = 8                # 页/章并行线程数(受 LLM 信号量二次约束)

    # ---- 文档转换 (PPTX -> PDF -> PNG) ----
    # soffice: Worker 容器内置 LibreOffice（默认，中文字体保真）
    # unoserver: 远程 soffice 常驻容器；none: 关闭预览转换
    convert_backend: str = "soffice"
    unoserver_host: str = "soffice"
    unoserver_port: int = 2003
    soffice_bin: str = "soffice"
    preview_dpi: int = 110                      # 大图分辨率
    thumb_width: int = 320

    # ---- 字体 (容器内置 Noto CJK, 用于文本测量) ----
    font_path: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

    # ---- 可选能力开关 ----
    vision_qa_enabled: bool = False             # 专业模式 Vision QA(需 qwen-vl 可用)
    ocr_enabled: bool = False                   # 扫描件 OCR(V1 默认关闭, 明确报错)

    # ---- 清理策略 ----
    artifact_retention_days: int = 30
    checkpoint_retention_days: int = 7

    # ---- ppt-master 生成（独立能力：以子进程驱动 Claude Code / Codex 在 ppt-master 仓库内跑工作流）----
    pptmaster_execution_scope: str = "local"       # local | worker；容器部署由独立 Worker 解析 Agent
    pptmaster_repo_dir: str = "../ppt-master"        # ppt-master 仓库目录（含 skills/ppt-master）；相对路径按 backend/ 解析，容器内为 /opt/ppt-master
    pptmaster_projects_dir: str = ""                 # 项目工作区（默认 <repo>/projects）
    pptmaster_default_agent: str = "auto"            # auto | claude | codex | mock
    pptmaster_claude_bin: str = ""                   # 为空则在 PATH 与常见安装位置自动探测
    pptmaster_codex_bin: str = ""
    pptmaster_python_bin: str = ""                   # Agent 调用 python3 时使用的解释器（默认当前解释器）
    pptmaster_timeout_minutes: int = 40              # 单任务默认超时
    pptmaster_timeout_max_minutes: int = 120
    pptmaster_max_concurrent_jobs: int = 3           # 单个部署最多同时运行的 ppt-master 任务
    pptmaster_max_upload_mb: int = 200
    pptmaster_max_files: int = 10
    pptmaster_selectable_models: str = "deepseek-v4-pro,qwen3.7-plus,qwen3.8-max"
    pptmaster_default_model: str = "qwen3.7-plus"
    pptmaster_claude_model: str = ""                 # 为空用 CLI 默认模型
    pptmaster_codex_model: str = ""
    pptmaster_claude_max_budget_usd: float = 0       # >0 时给 claude -p 加 --max-budget-usd 费用上限（0=不限）


@lru_cache
def get_settings() -> Settings:
    return Settings()


def selectable_models(settings: Settings | None = None) -> list[str]:
    """Return the ordered, unique user-selectable model catalog from the environment."""
    raw = (settings or get_settings()).llm_selectable_models
    models: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        model = item.strip()
        if model and model not in seen:
            models.append(model)
            seen.add(model)
    if not models:
        raise ValueError("LLM_SELECTABLE_MODELS 未配置可选模型")
    return models


def default_selectable_model(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    default = current.llm_default_selectable_model.strip()
    if default not in selectable_models(current):
        raise ValueError(f"默认模型 {default or '<empty>'} 不在 LLM_SELECTABLE_MODELS 中")
    return default


def beautify_selectable_model(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    model = current.llm_beautify_model.strip()
    if model not in selectable_models(current):
        raise ValueError(f"美化模型 {model or '<empty>'} 不在 LLM_SELECTABLE_MODELS 中")
    return model


def validate_selectable_model(model: str | None, settings: Settings | None = None) -> str:
    selected = (model or "").strip()
    if not selected:
        raise ValueError("请选择模型")
    if selected not in selectable_models(settings):
        raise ValueError(f"模型 {selected} 不在可选模型列表中")
    return selected


def pptmaster_selectable_models(settings: Settings | None = None) -> list[str]:
    """Return the model catalog exposed by the independent PPT-MASTER workflow."""
    raw = (settings or get_settings()).pptmaster_selectable_models
    models: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        model = item.strip()
        if model and model not in seen:
            models.append(model)
            seen.add(model)
    if not models:
        raise ValueError("PPTMASTER_SELECTABLE_MODELS 未配置可选模型")
    return models


def default_pptmaster_model(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    default = current.pptmaster_default_model.strip()
    if default not in pptmaster_selectable_models(current):
        raise ValueError(
            f"PPT-MASTER 默认模型 {default or '<empty>'} 不在 PPTMASTER_SELECTABLE_MODELS 中"
        )
    return default


def validate_pptmaster_model(model: str | None, settings: Settings | None = None) -> str:
    selected = (model or "").strip()
    if not selected:
        raise ValueError("请选择模型")
    if selected not in pptmaster_selectable_models(settings):
        raise ValueError(f"模型 {selected} 不在 PPT-MASTER 可选模型列表中")
    return selected
