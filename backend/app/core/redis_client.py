"""Redis 客户端：同步实例给 Worker/服务层，异步实例给 SSE 推流。"""
import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

_sync: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _sync
    if _sync is None:
        _sync = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _sync


def new_async_redis() -> aioredis.Redis:
    """SSE 每个连接独立创建（pubsub 独占连接），由调用方负责关闭。"""
    return aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)
