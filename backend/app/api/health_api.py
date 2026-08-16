"""健康检查：/healthz 轻量存活，/readyz 依赖探测（DB/Redis/存储/转换）。"""
from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import get_engine
from app.core.redis_client import get_redis
from app.services.convert import convert_healthy
from app.services.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    checks = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    checks["storage"] = "ok" if get_storage().healthy() else "error"
    checks["convert"] = "ok" if convert_healthy() else "degraded"
    ready = all(v == "ok" for k, v in checks.items() if k != "convert")
    return {"status": "ok" if ready else "degraded", "checks": checks}
