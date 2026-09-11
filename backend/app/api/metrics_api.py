"""指标查询：本地账本与远端聚合分别返回，所有路由先校验访问令牌。"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import threading
import time
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.models import LLMObservation as O
from app.observability import trace_id_for
from app.schemas.dto import ok


def require_access(authorization: str = Header(default='')):
    expected = get_settings().metrics_access_token
    if not expected:
        raise HTTPException(503, '指标访问未配置')
    provided = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(401, '指标访问令牌无效')


router = APIRouter(prefix='/metrics', tags=['metrics'], dependencies=[Depends(require_access)])


def filters(days: int = Query(7, ge=1, le=90), engine: Literal['pipeline', 'pptmaster'] = 'pipeline',
            model: str = Query('', max_length=128), job: str = Query('', max_length=64)):
    now = datetime.now(timezone.utc)
    conditions = [O.created_at >= now - timedelta(days=days), O.created_at <= now, O.engine == engine]
    if model:
        conditions.append(O.model == model)
    if job:
        conditions.append(O.biz_id == job)
    return {'days': days, 'engine': engine, 'model': model, 'job': job, 'conditions': conditions}


def aggregate_columns():
    return [func.count().label('count'),
            func.sum(case((O.status == 'success', 1), else_=0)).label('success_count'),
            func.sum(case((O.attempt > 1, 1), else_=0)).label('retries'),
            func.sum(case((O.fallback.is_(True), 1), else_=0)).label('fallbacks'),
            func.sum(O.input_tokens).label('input_tokens'), func.sum(O.output_tokens).label('output_tokens'),
            func.sum(O.cost_usd).label('cost_usd'), func.avg(O.duration_ms).label('avg_duration_ms'),
            func.sum(case((or_(O.input_tokens.is_(None), O.output_tokens.is_(None)), 1), else_=0)).label('unknown_usage_count'),
            func.sum(case((O.cost_usd.is_(None), 1), else_=0)).label('unknown_cost_count'),
            func.sum(case((O.cost_source == 'estimated', 1), else_=0)).label('estimated_cost_count'),
            func.sum(case((O.usage_source == 'partial', 1), else_=0)).label('partial_usage_count')]


def summary_row(row):
    d = dict(row)
    count = d['count'] or 0
    for k in ('retries', 'fallbacks', 'unknown_usage_count', 'unknown_cost_count', 'estimated_cost_count', 'partial_usage_count'):
        d[k] = int(d[k] or 0)
    d['success_rate'] = round(100 * (d.pop('success_count') or 0) / count, 2) if count else None
    for k in ('cost_usd', 'avg_duration_ms'):
        d[k] = float(d[k]) if d[k] is not None else None
    return d


def percentile(histogram, q):
    total = sum(n for _, n in histogram)
    target = max(1, math.ceil(total * q))
    cumulative = 0
    for value, n in histogram:
        cumulative += n
        if cumulative >= target:
            return value
    return None


@router.get('/summary')
def summary(f: dict = Depends(filters), db: Session = Depends(get_db)):
    base = select(*aggregate_columns()).select_from(O).where(*f['conditions'])
    result = summary_row(db.execute(base).mappings().one())
    histogram = db.execute(select(O.duration_ms, func.count()).where(*f['conditions'])
                           .group_by(O.duration_ms).order_by(O.duration_ms)).all()
    result.update(p50_ms=percentile(histogram, .5), p95_ms=percentile(histogram, .95))
    def grouped(column, label):
        query = select(column.label(label), *aggregate_columns()).where(*f['conditions']).group_by(column).order_by(column)
        return [summary_row(r) for r in db.execute(query).mappings()]
    date_column = func.date(func.timezone('UTC', O.created_at)) if db.get_bind().dialect.name == 'postgresql' else func.date(O.created_at)
    return ok({'source': 'local_observations', 'engine': f['engine'], 'summary': result,
               'by_model': grouped(O.model, 'model'), 'by_stage': grouped(O.stage, 'stage'),
               'daily': grouped(date_column, 'date'),
               'langfuse_enabled': get_settings().langfuse_enabled})


def trace_url(trace_id):
    s = get_settings()
    url = (s.langfuse_ui_url or s.langfuse_base_url).rstrip('/')
    parsed = urlsplit(url)
    if not s.langfuse_enabled or not s.langfuse_project_id or parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username:
        return None
    return f'{url}/project/{quote(s.langfuse_project_id, safe="")}/traces/{quote(trace_id, safe="")}'


@router.get('/observations')
def observations(f: dict = Depends(filters), page: int = Query(1, ge=1, le=10000),
                 page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(O).where(*f['conditions']))
    rows = db.scalars(select(O).where(*f['conditions']).order_by(O.created_at.desc(), O.id.desc())
                      .offset((page-1)*page_size).limit(page_size)).all()
    items = []
    for row in rows:
        d = {c.name: getattr(row, c.name) for c in O.__table__.columns}
        d['cost_usd'] = float(d['cost_usd']) if d['cost_usd'] is not None else None
        d['trace_url'] = trace_url(row.trace_id)
        # SQLite 验证库可能返回 naive 时间；生产 PostgreSQL 为 TIMESTAMPTZ。
        if d['created_at'].tzinfo is None:
            d['created_at'] = d['created_at'].replace(tzinfo=timezone.utc)
        items.append(d)
    return ok({'items': items, 'total': total, 'page': page, 'page_size': page_size})


_cache = {}
_cache_lock = threading.Lock()


@router.get('/remote')
def remote(f: dict = Depends(filters), db: Session = Depends(get_db)):
    s = get_settings()
    if not s.langfuse_enabled or not s.langfuse_public_key or not s.langfuse_secret_key:
        return ok({'status': 'disabled', 'message': 'Langfuse 尚未启用或未配置项目凭据，本地指标仍可使用。'})
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # 使用固定观测名称限制应用数据，显式排除 stage span。
    remote_filters = [
        {'column': 'type', 'operator': '=', 'value': 'GENERATION', 'type': 'string'},
        {'column': 'environment', 'operator': '=', 'value': s.env, 'type': 'string'},
        {'column': 'metadata', 'key': 'engine', 'operator': '=', 'value': f['engine'], 'type': 'stringObject'},
    ]
    if f['model']:
        remote_filters.append({'column': 'providedModelName', 'operator': '=', 'value': f['model'], 'type': 'string'})
    if f['job']:
        from app.models.models import GenerationJob, PptMasterJob
        model = PptMasterJob if f['engine'] == 'pptmaster' else GenerationJob
        job_id = db.scalar(select(model.id).where(model.biz_id == f['job']))
        if job_id is None:
            return ok({'status': 'ok', 'data': [], 'cached': False})
        remote_filters.append({'column': 'traceId', 'operator': '=',
                               'value': trace_id_for(f['engine'], job_id), 'type': 'string'})
    query = {'view': 'observations', 'metrics': [
        {'measure': 'count', 'aggregation': 'count'}, {'measure': 'totalTokens', 'aggregation': 'sum'},
        {'measure': 'totalCost', 'aggregation': 'sum'}, {'measure': 'latency', 'aggregation': 'p95'}],
        'dimensions': [{'field': 'providedModelName'}], 'filters': remote_filters,
        'fromTimestamp': (now-timedelta(days=f['days'])).isoformat(), 'toTimestamp': now.isoformat(),
        'config': {'row_limit': 1000}}
    payload = json.dumps(query, sort_keys=True)
    key = hashlib.sha256((s.langfuse_base_url+s.langfuse_public_key+s.langfuse_secret_key+payload).encode()).hexdigest()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic()-cached[0] < 30:
            return ok({**cached[1], 'cached': True})
    try:
        response = httpx.get(s.langfuse_base_url.rstrip('/')+'/api/public/v2/metrics',
                             params={'query': payload}, auth=(s.langfuse_public_key, s.langfuse_secret_key),
                             timeout=5, follow_redirects=False)
        response.raise_for_status()
        data = response.json().get('data')
        if not isinstance(data, list):
            raise ValueError('invalid metrics payload')
        # 只允许预期聚合列，不把任意远端响应直接传到前端。
        fields = ('providedModelName', 'count_count', 'sum_totalTokens', 'sum_totalCost', 'p95_latency')
        result = {'status': 'ok', 'data': [{k: r.get(k) for k in fields} for r in data if isinstance(r, dict)], 'cached': False}
        with _cache_lock:
            if len(_cache) >= 128:
                _cache.clear()
            _cache[key] = (time.monotonic(), result)
        return ok(result)
    except Exception:
        return ok({'status': 'error', 'message': 'Langfuse 聚合暂不可用，请检查连接、项目凭据和 Metrics v2 兼容性。本地指标不受影响。'})
