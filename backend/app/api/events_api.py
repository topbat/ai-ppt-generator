"""SSE 进度推流：Worker(Redis Pub/Sub) → API → 前端。

- 支持 Last-Event-ID 断线续传（历史事件从 job_events 回放）；
- 15 秒无事件发心跳注释行保活；
- 收到终态事件（job_done/job_failed）后自然结束流。
"""
import asyncio
import json

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.database import db_session
from app.core.logging import get_logger
from app.core.redis_client import new_async_redis
from app.models.models import GenerationJob, JobEvent
from app.services.progress import TERMINAL_EVENTS, channel_of

router = APIRouter(prefix="/jobs", tags=["events"])
logger = get_logger(__name__)

_HEARTBEAT_SECONDS = 15


def _load_job_and_events(biz_id: str, after_seq: int):
    with db_session() as db:
        job = db.execute(select(GenerationJob).where(
            GenerationJob.biz_id == biz_id)).scalar_one_or_none()
        if job is None:
            return None, []
        events = db.execute(select(JobEvent).where(JobEvent.job_id == job.id,
                                                   JobEvent.seq > after_seq)
                            .order_by(JobEvent.seq)).scalars().all()
        return job.status, [(e.seq, e.event, e.payload) for e in events]


def _sse_frame(seq: int, event: str, payload: dict) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/{biz_id}/events")
async def job_events(biz_id: str, request: Request,
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    after_seq = int(last_event_id) if (last_event_id or "").isdigit() else 0

    async def stream():
        status, history = await run_in_threadpool(_load_job_and_events, biz_id, after_seq)
        if status is None:
            yield _sse_frame(0, "error", {"message": "任务不存在"})
            return
        terminal_sent = False
        for seq, event, payload in history:  # 回放历史（断线续传）
            yield _sse_frame(seq, event, payload)
            if event in TERMINAL_EVENTS:
                terminal_sent = True
        if terminal_sent or status in ("succeeded", "failed", "canceled"):
            # 任务已结束：极速模式的缩略图可能仍在异步补齐，继续挂 60s 收尾事件
            if status != "succeeded":
                return

        redis = new_async_redis()
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(channel_of(biz_id))
            idle, max_idle_after_done = 0.0, 60.0
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    idle += 1.0
                    if idle >= _HEARTBEAT_SECONDS:
                        yield ": heartbeat\n\n"  # SSE 注释行保活
                        idle = 0.0
                    if terminal_sent:
                        max_idle_after_done -= 1.0
                        if max_idle_after_done <= 0:
                            break
                    continue
                idle = 0.0
                try:
                    body = json.loads(msg["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if body.get("seq", 0) <= after_seq:
                    continue  # 与回放重叠的事件去重
                yield _sse_frame(body["seq"], body["event"], body)
                if body["event"] in TERMINAL_EVENTS:
                    terminal_sent = True  # 终态后再等 60s 收异步缩略图事件
        finally:
            try:
                await pubsub.unsubscribe(channel_of(biz_id))
                await redis.aclose()
            except Exception:
                pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
