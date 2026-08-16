"""数据库会话管理。V1 使用 create_all 建表（生产迁移接入 Alembic 时替换）。"""
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        # pool_pre_ping: 防止长任务期间连接被数据库回收导致报错
        _engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入用。"""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Worker / 服务层用的短会话上下文：出错回滚，用完即还。"""
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_database_exists() -> None:
    """目标数据库不存在时自动创建（本地环境友好）。

    典型场景：本地 PostgreSQL（localhost:5432，postgres/postgres）没有预建 ppt 库，
    此时先连同实例的 postgres 系统库执行 CREATE DATABASE，再继续建表。
    """
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    url = make_url(get_settings().database_url)
    probe = create_engine(url, pool_pre_ping=True)
    try:
        with probe.connect():
            return  # 数据库已存在
    except OperationalError as e:
        # 仅处理"库不存在"，认证失败/连不上实例等原样抛出
        msg = str(e)
        if "does not exist" not in msg and "不存在" not in msg:
            raise
        logger.info("数据库 %s 不存在，自动创建（本地环境首次启动）", url.database)
    except UnicodeDecodeError:
        # 中文 Windows 本地 PostgreSQL：启动阶段错误消息为 GBK 编码，psycopg2 解码失败，
        # 无法区分"库不存在"与"认证失败"。下面尝试连 postgres 系统库来区分：
        # 能连上 → 只是目标库不存在，继续自动建库；连不上 → 大概率认证失败，给出明确指引。
        logger.warning("本地 PostgreSQL 返回非 UTF-8 错误消息（中文 Windows 常见），尝试自动区分原因")
    finally:
        probe.dispose()

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        logger.info("数据库 %s 创建完成", url.database)
    except UnicodeDecodeError as e:
        raise RuntimeError(
            f"本地 PostgreSQL 认证失败（服务端以 GBK 返回错误消息，SQLSTATE 大概率为 28P01 口令错误）。"
            f"请核对 DATABASE_URL 中的用户名/密码是否与本机实例一致：{url.render_as_string(hide_password=True)}"
        ) from e
    except OperationalError as e:
        msg = str(e)
        if "password" in msg.lower() or "认证" in msg or "authentication" in msg.lower():
            raise RuntimeError(
                f"本地 PostgreSQL 认证失败，请核对 DATABASE_URL 的用户名/密码："
                f"{url.render_as_string(hide_password=True)}"
            ) from e
        raise
    except Exception as e:
        # 并发启动时可能已被其他进程创建，二次探测通过即视为成功
        with create_engine(url).connect():
            logger.info("数据库 %s 已由其他进程创建：%s", url.database, e)
    finally:
        admin.dispose()


# 增量新列登记：create_all 不会给已存在的表加列，此处幂等补齐（表名, 列名, 列定义）
_INCREMENTAL_COLUMNS = [
    ("generation_jobs", "visual_score", "SMALLINT"),   # 视觉分（册级）
    ("job_slides", "visual_score", "SMALLINT"),        # 视觉分（页级）
]


def _ensure_incremental_columns() -> None:
    """老库升级：ADD COLUMN IF NOT EXISTS 幂等加列（PostgreSQL）。失败仅告警不阻塞。"""
    from sqlalchemy import text

    with get_engine().begin() as conn:
        for table, column, ddl in _INCREMENTAL_COLUMNS:
            try:
                conn.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}'))
            except Exception as e:
                logger.warning("增量加列跳过 %s.%s：%s", table, column, e)


def init_db() -> None:
    """建库（如缺失）+ 建表（幂等）+ 增量加列。注意需先 import models 让 Base 感知全部表。"""
    from app.models import models  # noqa: F401  确保表定义已注册

    _ensure_database_exists()
    Base.metadata.create_all(bind=get_engine())
    _ensure_incremental_columns()
    logger.info("数据库初始化完成（create_all + 增量列 幂等执行）")
