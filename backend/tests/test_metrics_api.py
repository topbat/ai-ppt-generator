from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def metrics_client(monkeypatch):
    from app.api import metrics_api as api
    from app.core.config import Settings
    from app.core.database import Base, get_db
    from app.models.models import LLMObservation
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[LLMObservation.__table__])
    def db():
        with Session(engine) as session:
            yield session
    monkeypatch.setattr(api, 'get_settings', lambda: Settings(_env_file=None, metrics_access_token='test-token'))
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1')
    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        yield client, engine


def test_metrics_require_token(metrics_client):
    client, _ = metrics_client
    assert client.get('/api/v1/metrics/summary').status_code == 401
    assert client.get('/api/v1/metrics/summary', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    r = client.get('/api/v1/metrics/summary', headers={'Authorization': 'Bearer test-token'})
    assert r.status_code == 200
    assert r.json()['data']['summary']['count'] == 0


def test_summary_unknown_cost_filter_and_pagination(metrics_client):
    from app.models.models import LLMObservation
    client, engine = metrics_client
    with Session(engine) as db:
        for i in range(3):
            db.add(LLMObservation(id=str(i), trace_id='a'*32, engine='pipeline', kind='request',
                job_id=i, biz_id=f'job-{i}', stage='OUTLINE', task_type='outline', provider='qwen',
                model='model-a' if i < 2 else 'model-b', mode='standard', attempt=i+1, fallback=i == 2,
                input_tokens=None if i == 0 else 10, output_tokens=2, cached_tokens=None,
                cost_usd=None, cost_source='unknown', duration_ms=100*(i+1), queue_ms=4,
                status='failed' if i == 0 else 'success', created_at=datetime.now(timezone.utc)))
        db.commit()
    headers = {'Authorization': 'Bearer test-token'}
    data = client.get('/api/v1/metrics/summary?model=model-a', headers=headers).json()['data']
    assert data['summary']['count'] == 2
    assert data['summary']['cost_usd'] is None
    assert data['summary']['unknown_usage_count'] == 1
    assert data['summary']['success_rate'] == 50
    page = client.get('/api/v1/metrics/observations?page_size=1', headers=headers).json()['data']
    assert page['total'] == 3 and len(page['items']) == 1
    assert client.get('/api/v1/metrics/summary?days=999', headers=headers).status_code == 422


def test_remote_disabled_is_explicit(metrics_client):
    client, _ = metrics_client
    r = client.get('/api/v1/metrics/remote', headers={'Authorization': 'Bearer test-token'})
    assert r.json()['data']['status'] == 'disabled'


def test_remote_query_is_scoped_cached_and_secrets_stay_server_side(metrics_client, monkeypatch):
    from app.api import metrics_api as api
    from app.core.config import Settings
    import httpx
    import json
    client, _ = metrics_client
    api._cache.clear()
    monkeypatch.setattr(api, 'get_settings', lambda: Settings(_env_file=None, metrics_access_token='test-token',
        langfuse_enabled=True, langfuse_public_key='public-test', langfuse_secret_key='never-expose'))
    calls = []
    def remote_get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request('GET', url), json={'data': [
            {'providedModelName': 'm', 'count_count': '3', 'untrusted_extra': 'never-expose'}]})
    monkeypatch.setattr(api.httpx, 'get', remote_get)
    headers = {'Authorization': 'Bearer test-token'}
    first = client.get('/api/v1/metrics/remote?model=m', headers=headers)
    second = client.get('/api/v1/metrics/remote?model=m', headers=headers)
    assert first.json()['data']['status'] == 'ok'
    assert second.json()['data']['cached'] is True
    assert len(calls) == 1
    query = json.loads(calls[0][1]['params']['query'])
    assert query['view'] == 'observations'
    assert any(f.get('key') == 'engine' and f['value'] == 'pipeline' for f in query['filters'])
    assert any(f['column'] == 'environment' and f['value'] == 'dev' for f in query['filters'])
    assert 'never-expose' not in first.text
    api._cache.clear()
    monkeypatch.setattr(api.httpx, 'get', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('never-expose')))
    result = client.get('/api/v1/metrics/remote', headers=headers)
    assert result.json()['data']['status'] == 'error'
    assert 'never-expose' not in result.text
