"""FastAPI 应用入口。

启动时：建表（幂等）→ 确保存储桶 → 注册系统默认模板。
任一依赖未就绪不阻塞启动（记录错误，/readyz 反映真实状态）。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.errors import PPTError
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 各初始化步骤相互独立，失败只记日志不阻塞启动
    try:
        from app.core.database import init_db
        init_db()
    except Exception as e:
        logger.error("数据库初始化失败（/readyz 将反映）：%s", e)
    try:
        from app.services.storage import get_storage
        get_storage().ensure_bucket()
    except Exception as e:
        logger.error("对象存储初始化失败（/readyz 将反映）：%s", e)
    try:
        _ensure_ai_seed_templates()
    except Exception as e:
        logger.error("AI 模板初始化播种失败（可通过 AI 生成入口补建）：%s", e)
    logger.info("API 服务启动完成")
    yield


def _ensure_ai_seed_templates():
    """模板库为空时初始化播种 10 套 AI 模板（八维参数化生成器）。

    仅在"无任何可用模板"时播种：用户删除部分模板不会被重建，
    清空全部模板后重启即恢复出厂 10 套。会话级咨询锁防多 worker 重复注册。
    """
    from sqlalchemy import func, select, text

    from app.core.database import db_session, get_engine
    from app.models.models import Template
    from app.ppt.template_gallery import SEED_PRESETS, build_ai_template, template_name
    from app.services.template_service import register_template_bytes

    with get_engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(778900)"))
        try:
            with db_session() as db:
                active = db.execute(select(func.count()).select_from(Template).where(
                    Template.deleted_at.is_(None))).scalar_one()
            if active:
                return
            logger.info("模板库为空，开始初始化播种 %d 套 AI 模板", len(SEED_PRESETS))
            done = 0
            for preset in SEED_PRESETS:
                try:
                    data = build_ai_template(preset)
                    register_template_bytes(template_name(preset), data, is_system=False)
                    done += 1
                except Exception as e:
                    logger.warning("AI 模板播种失败（跳过）%s：%s", template_name(preset), e)
            logger.info("AI 模板初始化播种完成：%d/%d 套", done, len(SEED_PRESETS))
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(778900)"))
            conn.commit()


app = FastAPI(title="AI PPT Generator", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---- 统一异常收口：全部包为 {code, message, data} 信封 ----
@app.exception_handler(PPTError)
async def ppt_error_handler(_req: Request, exc: PPTError):
    logger.warning("业务异常：%s %s", exc.code, exc.user_message)
    return JSONResponse(status_code=200, content={
        "code": int(exc.code[1:]) if exc.code[1:].isdigit() else 9999,
        "message": exc.user_message, "data": {"error_code": exc.code,
                                              "suggestion": exc.definition.suggestion}})


@app.exception_handler(RequestValidationError)
async def validation_handler(_req: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "code": 422, "message": "请求参数不合法", "data": exc.errors()})


@app.exception_handler(Exception)
async def unknown_handler(_req: Request, exc: Exception):
    logger.exception("未捕获异常")
    return JSONResponse(status_code=500, content={
        "code": 500, "message": "服务内部错误，请稍后重试", "data": None})


# ---- 路由注册 ----
from app.api.admin_api import router as admin_router          # noqa: E402
from app.api.beautify_api import router as beautify_router    # noqa: E402
from app.api.documents_api import router as documents_router  # noqa: E402
from app.api.events_api import router as events_router        # noqa: E402
from app.api.health_api import router as health_router        # noqa: E402
from app.api.jobs_api import router as jobs_router            # noqa: E402
from app.api.templates_api import router as templates_router  # noqa: E402

API_PREFIX = "/api/v1"
app.include_router(templates_router, prefix=API_PREFIX)
app.include_router(beautify_router, prefix=API_PREFIX)
app.include_router(documents_router, prefix=API_PREFIX)
app.include_router(events_router, prefix=API_PREFIX)   # 先注册：/jobs/{id}/events 需优先匹配
app.include_router(jobs_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(health_router)  # /healthz /readyz 挂根路径
