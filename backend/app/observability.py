"""模型观测边界：显式上下文、真实 usage、最佳努力写入与异步导出。"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import threading
import time
import uuid

from app.core.config import get_settings
from app.core.logging import ctx_stage, get_logger

logger = get_logger(__name__)
_context = ContextVar('llm_observation_context', default={})
_sdk = None
_sdk_pid = None
_sdk_lock = threading.Lock()


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def _dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    return vars(value) if hasattr(value, '__dict__') else {}


def normalize_usage(usage):
    u = _dict(usage)
    details = _dict(u.get('prompt_tokens_details') or u.get('input_tokens_details'))
    return {
        'input_tokens': _number(u.get('prompt_tokens', u.get('input_tokens'))),
        'output_tokens': _number(u.get('completion_tokens', u.get('output_tokens'))),
        'cached_tokens': _number(u.get('cached_tokens', u.get('cached_input_tokens',
                                  u.get('cache_read_input_tokens', u.get('prompt_cache_hit_tokens', details.get('cached_tokens')))))),
        'cache_creation_tokens': _number(u.get('cache_creation_tokens', u.get('cache_creation_input_tokens'))),
    }


def sum_usage(usages):
    """汇总同口径增量；某次缺失的字段，其总量也保持未知。"""
    rows = [normalize_usage(u) for u in usages]
    return {k: sum(r[k] for r in rows) if rows and all(r[k] is not None for r in rows) else None
            for k in normalize_usage(None)}


def trace_id_for(engine, job_id):
    namespace = get_settings().env
    return hashlib.sha256(f'ppt:{namespace}:{engine}:{job_id}'.encode()).hexdigest()[:32]


def estimate_cost(model, usage, prices):
    rate = prices.get(model)
    if not isinstance(rate, dict):
        return None
    inp, out = usage.get('input_tokens'), usage.get('output_tokens')
    if inp is None or out is None or _number(rate.get('input')) is None or _number(rate.get('output')) is None:
        return None
    cached, created = usage.get('cached_tokens') or 0, usage.get('cache_creation_tokens') or 0
    if cached + created > inp or (cached and _number(rate.get('cached')) is None) or (created and _number(rate.get('cache_creation')) is None):
        return None
    return ((inp - cached - created) * rate['input'] + out * rate['output'] +
            cached * rate.get('cached', 0) + created * rate.get('cache_creation', 0)) / 1_000_000


def _client():
    global _sdk, _sdk_pid
    s = get_settings()
    if not s.langfuse_enabled or not s.langfuse_public_key or not s.langfuse_secret_key:
        return None
    with _sdk_lock:
        if _sdk_pid != os.getpid():
            from langfuse import Langfuse
            _sdk = Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key,
                            base_url=s.langfuse_base_url, environment=s.env, timeout=3)
            _sdk_pid = os.getpid()
        return _sdk


def flush():
    # 不为未使用的进程创建客户端，子进程不使用父进程的导出器。
    try:
        if _sdk is not None and _sdk_pid == os.getpid():
            _sdk.flush()
    except Exception:
        logger.warning('观测刷新失败，忽略')


def _start(event, input_data=None, as_type='generation'):
    try:
        client = _client()
        if client is None:
            return None
        trace = {'trace_id': event['trace_id']}
        parent = _context.get().get('span_id')
        if parent:
            trace['parent_span_id'] = parent
        kwargs = dict(name=event['task_type'], as_type=as_type, trace_context=trace,
                      metadata={k: event.get(k) for k in ('engine', 'job_id', 'stage', 'mode', 'attempt', 'fallback', 'kind')})
        if as_type == 'generation':
            kwargs['model'] = event.get('model')
        if get_settings().langfuse_capture_content and input_data is not None:
            kwargs['input'] = input_data
        return client.start_observation(**kwargs)
    except Exception:
        logger.warning('观测初始化失败，忽略')
        return None


def _finish(span, event, output_data=None, end_time=None):
    if span is None:
        return
    try:
        usage = {k: event[k] for k in ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_creation_tokens')
                 if event.get(k) is not None}
        # input/output 为非缓存部分，其余类型独立计量，避免 Langfuse total 重复。
        mapped = {}
        if 'input_tokens' in usage:
            mapped['input'] = max(0, usage['input_tokens'] - usage.get('cached_tokens', 0) - usage.get('cache_creation_tokens', 0))
        if 'output_tokens' in usage:
            mapped['output'] = usage['output_tokens']
        if 'cached_tokens' in usage:
            mapped['input_cached'] = usage['cached_tokens']
        if 'cache_creation_tokens' in usage:
            mapped['input_cache_creation'] = usage['cache_creation_tokens']
        data = {'level': 'ERROR' if event['status'] != 'success' else 'DEFAULT',
                'status_message': event.get('error_type'),
                'metadata': {k: event.get(k) for k in ('engine', 'job_id', 'biz_id', 'kind', 'stage', 'mode',
                            'attempt', 'fallback', 'duration_ms', 'queue_ms', 'cost_source', 'usage_source')}}
        if event.get('kind') in ('request', 'agent_run'):
            data['usage_details'] = mapped
            if event.get('cost_usd') is not None:
                data['cost_details'] = {'total': float(event['cost_usd'])}
        if get_settings().langfuse_capture_content and output_data is not None:
            data['output'] = output_data
        span.update(**data)
    except Exception:
        logger.warning('观测导出失败，忽略')
    finally:
        try:
            span.end(end_time=end_time)
        except Exception:
            logger.warning('观测结束失败，忽略')


def _persist(event):
    from app.core.database import db_session
    from app.models.models import GenerationJob, LLMObservation, PptMasterJob
    with db_session() as db:
        if event.get('job_id') is not None:
            job = db.get(PptMasterJob if event['engine'] == 'pptmaster' else GenerationJob, event['job_id'])
            if job:
                event['biz_id'] = job.biz_id
        db.add(LLMObservation(**event))


@contextmanager
def capture(*, engine='pipeline', job_id=None, task_type, model='', provider='', mode='',
            attempt=1, fallback=False, queue_ms=0, kind='request', input_data=None):
    context = _context.get()
    job_id = job_id if job_id is not None else context.get('job_id')
    event = dict(id=uuid.uuid4().hex, trace_id=trace_id_for(engine, job_id if job_id is not None else uuid.uuid4().hex),
                 engine=engine, kind=kind, job_id=job_id, biz_id=None,
                 stage=(task_type if engine == 'pptmaster' else context.get('stage') or ctx_stage.get()), task_type=task_type, model=model,
                 provider=provider, mode=mode or context.get('mode', ''), attempt=attempt,
                 fallback=fallback, queue_ms=queue_ms, status='success', error_type=None,
                 cost_usd=None, cost_source='unknown', usage_source='unknown', created_at=datetime.now(timezone.utc),
                 **normalize_usage(None))
    span = _start(event, input_data)
    started = time.monotonic()
    try:
        yield event
    except BaseException as exc:
        event['status'] = 'failed'
        event['error_type'] = type(exc).__name__[:64]
        raise
    finally:
        end_time = time.time_ns()
        event['duration_ms'] = max(0, int((time.monotonic() - started) * 1000))
        output = event.pop('output_data', None)
        if event['usage_source'] == 'unknown' and event['input_tokens'] is not None and event['output_tokens'] is not None:
            event['usage_source'] = 'reported'
        if event['cost_usd'] is None and event['usage_source'] != 'partial':
            try:
                event['cost_usd'] = estimate_cost(model, event, json.loads(get_settings().llm_prices_json))
                if event['cost_usd'] is not None:
                    event['cost_source'] = 'estimated'
            except (TypeError, ValueError, AttributeError):
                pass
        try:
            _persist(event)
        except Exception:
            logger.warning('观测记录写入失败，忽略')
        _finish(span, event, output, end_time=end_time)


@contextmanager
def stage_scope(job_id, stage, mode):
    event = dict(trace_id=trace_id_for('pipeline', job_id), engine='pipeline', job_id=job_id,
                 task_type=stage, stage=stage, mode=mode, kind='stage', status='success')
    span = _start(event, as_type='span')
    token = _context.set({'job_id': job_id, 'stage': stage, 'mode': mode,
                          'span_id': getattr(span, 'id', None)})
    try:
        yield
    except BaseException as exc:
        event.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        _context.reset(token)
        _finish(span, event)
