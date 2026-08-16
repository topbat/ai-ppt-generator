"""进度事件发布：Worker → Redis Pub/Sub → API(SSE) → 前端。

事件同时落库 job_events，用于 SSE 断线重连回放（Last-Event-ID）与审计。
事件协议见文档 §6.4，所有事件带自增 seq，前端按 seq 去重。
"""
import json
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.models.models import JobEvent

logger = get_logger(__name__)

# 事件名常量
EV_STAGE = "stage_update"
EV_PAGE_DONE = "page_done"
EV_THUMB = "thumbnail_ready"
EV_DECISION = "decision_required"
EV_DONE = "job_done"
EV_FAILED = "job_failed"

TERMINAL_EVENTS = {EV_DONE, EV_FAILED}


def channel_of(job_biz_id: str) -> str:
    return f"progress:{job_biz_id}"


class ProgressPublisher:
    """每个 Job 一个实例，由 Orchestrator 持有。"""

    def __init__(self, job_pk: int, job_biz_id: str, session_factory):
        self.job_pk = job_pk
        self.biz_id = job_biz_id
        self.session_factory = session_factory
        self.redis = get_redis()
        self._seq_key = f"progress_seq:{job_biz_id}"

    def publish(self, event: str, payload: dict) -> int:
        """发布事件并落库。发布失败不阻断主流程（仅记日志）。"""
        seq = int(self.redis.incr(self._seq_key))
        body = {"seq": seq, "event": event, "ts": datetime.now(timezone.utc).isoformat(), **payload}
        try:
            self.redis.publish(channel_of(self.biz_id), json.dumps(body, ensure_ascii=False))
        except Exception as e:  # Redis 抖动不应导致任务失败
            logger.warning("进度事件发布失败(忽略) event=%s: %s", event, e)
        try:
            with self.session_factory() as db:
                db.add(JobEvent(job_id=self.job_pk, seq=seq, event=event, payload=body))
                db.commit()
        except Exception as e:
            logger.warning("进度事件落库失败(忽略) event=%s: %s", event, e)
        return seq

    # ---- 便捷方法 ----
    def stage_update(self, stage: str, status: str, elapsed_ms: int | None = None,
                     progress: dict | None = None):
        self.publish(EV_STAGE, {"stage": stage, "status": status,
                                "elapsed_ms": elapsed_ms, "progress": progress})

    def page_done(self, page: int, content_card: dict):
        self.publish(EV_PAGE_DONE, {"page": page, "content_card": content_card})

    def thumbnail_ready(self, page: int, url: str):
        self.publish(EV_THUMB, {"page": page, "url": url})

    def decision_required(self, decision_id: str, kind: str, payload: dict,
                          deadline_ts: str, default_choice: str | None):
        self.publish(EV_DECISION, {"decision_id": decision_id, "kind": kind, "payload": payload,
                                   "deadline_ts": deadline_ts, "default_choice": default_choice})

    def job_done(self, quality_score: int | None):
        self.publish(EV_DONE, {"quality_score": quality_score})

    def job_failed(self, error_code: str, error_message: str, failed_stage: str | None):
        self.publish(EV_FAILED, {"error_code": error_code, "error_message": error_message,
                                 "failed_stage": failed_stage})
