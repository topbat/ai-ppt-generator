"""观测契约：真实用量、异常隔离、重试计数和受保护查询。"""
import importlib.util
from types import SimpleNamespace

import pytest


def test_observability_module_exists():
    assert importlib.util.find_spec('app.observability') is not None


def test_usage_unknown_is_not_zero():
    from app.observability import normalize_usage
    assert normalize_usage(None) == {'input_tokens': None, 'output_tokens': None,
                                     'cached_tokens': None, 'cache_creation_tokens': None}
    assert normalize_usage({'prompt_tokens': 0, 'completion_tokens': 0})['input_tokens'] == 0
    result = normalize_usage(SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                           prompt_tokens_details=SimpleNamespace(cached_tokens=40)))
    assert result['cached_tokens'] == 40


def test_trace_stable_but_engines_distinct():
    from app.observability import trace_id_for
    assert trace_id_for('pipeline', 4) == trace_id_for('pipeline', 4)
    assert trace_id_for('pipeline', 4) != trace_id_for('pptmaster', 4)
    assert len(trace_id_for('pipeline', 4)) == 32


def test_cost_requires_complete_usage_and_cache_price():
    from app.observability import estimate_cost
    prices = {'model': {'input': 2, 'output': 8}}
    assert estimate_cost('model', {'input_tokens': 100, 'output_tokens': None}, prices) is None
    assert estimate_cost('model', {'input_tokens': 100, 'output_tokens': 20,
                                  'cached_tokens': 30}, prices) is None
    assert estimate_cost('model', {'input_tokens': 100, 'output_tokens': 20}, prices) == pytest.approx(.00036)


def test_record_survives_broken_export_and_database(monkeypatch):
    from app import observability as obs
    monkeypatch.setattr(obs, '_persist', lambda e: (_ for _ in ()).throw(RuntimeError('db down')))
    monkeypatch.setattr(obs, '_client', lambda: (_ for _ in ()).throw(RuntimeError('export down')))
    with pytest.raises(ValueError, match='business'):
        with obs.capture(engine='pipeline', job_id=1, task_type='outline', model='m'):
            raise ValueError('business')


def test_capture_without_prompt_by_default(monkeypatch):
    from app import observability as obs
    from app.core.config import Settings
    exported, records = [], []
    span = SimpleNamespace(update=lambda **kw: exported.append(kw), end=lambda **kw: None)
    client = SimpleNamespace(start_observation=lambda **kw: (exported.append(kw), span)[1])
    monkeypatch.setattr(obs, 'get_settings', lambda: Settings(_env_file=None))
    monkeypatch.setattr(obs, '_client', lambda: client)
    monkeypatch.setattr(obs, '_persist', records.append)
    with obs.capture(engine='pipeline', job_id=1, task_type='outline', model='m',
                     input_data='private text') as event:
        event['output_data'] = 'private answer'
        event.update(obs.normalize_usage({'prompt_tokens': 12, 'completion_tokens': 5}))
    assert len(records) == 1
    assert records[0]['input_tokens'] == 12
    assert 'private' not in str(exported)
    assert 'input_data' not in records[0] and 'output_data' not in records[0]


def test_cli_usage_accumulates_and_resume_preserves_unknown():
    from app.pptmaster.runner import ClaudeRunner, CodexRunner, RunResult
    from app.pptmaster.service import _merge_resumed_result
    first, second = RunResult(0), RunResult(0)
    CodexRunner(None).extract_final([
        {'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 8, 'output_tokens': 2}},
    ], first)
    assert first.extra['usage']['input_tokens'] == 20
    ClaudeRunner(None).extract_final([{'type': 'result', 'usage': {'input_tokens': 5, 'output_tokens': 2},
                                   'total_cost_usd': .1}], second)
    assert second.extra['usage']['input_tokens'] == 5
    merged = _merge_resumed_result(first, second)
    assert merged.extra['usage']['input_tokens'] == 25
    assert merged.cost_usd is None  # 首次费用未知，总费用不得冒充完整


def test_gateway_counts_parameter_retry_and_content_filter(monkeypatch):
    from app.ai.gateway import LLMGateway
    from app.core.config import Settings
    from app import observability as obs
    import httpx
    from openai import APIStatusError
    monkeypatch.setattr('app.ai.gateway.get_settings', lambda: Settings(_env_file=None))
    records = []
    monkeypatch.setattr(obs, '_persist', records.append)
    gw = LLMGateway()
    monkeypatch.setattr(gw, '_log_call', lambda *args: None)
    calls = []
    def create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise APIStatusError('thinking unsupported', response=httpx.Response(400,
                request=httpx.Request('POST', 'https://example.test')), body=None)
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
                               choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(gw, '_client', lambda p: client)
    assert gw.chat_text('outline', 'standard', 's', 'u', job_id=8) == 'ok'
    assert len(records) == 2
    assert [r['status'] for r in records] == ['failed', 'success']
    assert [r['attempt'] for r in records] == [1, 2]


def test_real_sdk_export_links_threaded_generation_without_content(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from langfuse import Langfuse
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app import observability as obs
    exporter = InMemorySpanExporter()
    client = Langfuse(public_key='pk-lf-unit-observability', secret_key='unit-secret',
                      base_url='http://127.0.0.1:1', span_exporter=exporter)
    monkeypatch.setattr(obs, '_client', lambda: client)
    records = []
    persisted_at = []
    def persist(event):
        import time
        persisted_at.append(time.time_ns())
        records.append(event)
    monkeypatch.setattr(obs, '_persist', persist)
    def call():
        with obs.capture(job_id=9, task_type='outline', model='test-model', input_data='private prompt') as event:
            event.update(obs.normalize_usage({'prompt_tokens': 12, 'completion_tokens': 5,
                                              'prompt_tokens_details': {'cached_tokens': 4}}))
            event['output_data'] = 'private answer'
    with obs.stage_scope(9, 'OUTLINE', 'standard'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(copy_context().run, call).result()
    client.flush()
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    generation = next(s for s in spans if s.name == 'outline')
    stage = next(s for s in spans if s.name == 'OUTLINE')
    assert generation.parent.span_id == stage.context.span_id
    assert format(generation.context.trace_id, '032x') == obs.trace_id_for('pipeline', 9)
    assert 'private' not in str([dict(s.attributes) for s in spans])
    usage = generation.attributes['langfuse.observation.usage_details']
    import json
    assert json.loads(usage) == {'input': 8, 'output': 5, 'input_cached': 4}
    assert records[0]['stage'] == 'OUTLINE'
    assert generation.end_time <= persisted_at[0]
    client.shutdown()


def test_visual_request_is_recorded_and_failures_not_retried_by_sdk(monkeypatch):
    from app.ai.gateway import LLMGateway
    from app import observability as obs
    records = []
    monkeypatch.setattr(obs, '_persist', records.append)
    gw = LLMGateway()
    response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    monkeypatch.setattr(gw, '_client', lambda p: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: response))))
    assert gw.complete('qwen', job_id=3, task_type='vision_qa', model='vision', messages=[]) is response
    assert records[0]['task_type'] == 'vision_qa'
    assert records[0]['input_tokens'] is None


def test_deepseek_cache_and_invalid_cache_totals():
    from app.observability import normalize_usage, estimate_cost
    u = normalize_usage({'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_cache_hit_tokens': 60})
    assert u['cached_tokens'] == 60
    assert estimate_cost('m', u, {'m': {'input': 2, 'output': 8, 'cached': .2}}) == pytest.approx(.000252)
    assert estimate_cost('m', {'input_tokens': 10, 'output_tokens': 2, 'cached_tokens': 8,
                              'cache_creation_tokens': 5}, {'m': {'input': 2, 'output': 8,
                                                                 'cached': .2, 'cache_creation': 3}}) is None


def test_claude_interrupted_usage_deduplicates_message_snapshots():
    from app.pptmaster.runner import ClaudeRunner, RunResult
    result = RunResult(1, timed_out=True)
    ClaudeRunner(None).extract_final([
        {'type': 'assistant', 'message': {'id': 'm1', 'usage': {'input_tokens': 10, 'output_tokens': 2}}},
        {'type': 'assistant', 'message': {'id': 'm1', 'usage': {'input_tokens': 10, 'output_tokens': 5}}},
        {'type': 'assistant', 'message': {'id': 'm2', 'usage': {'input_tokens': 20, 'output_tokens': 3}}},
    ], result)
    assert result.extra['usage']['input_tokens'] == 30
    assert result.extra['usage']['output_tokens'] == 8
    assert result.extra['usage_source'] == 'partial'


def test_circuit_breaker_fallback_is_still_marked(monkeypatch):
    import time
    from app.ai.gateway import LLMGateway
    from app import observability as obs
    records = []
    monkeypatch.setattr(obs, '_persist', records.append)
    gw = LLMGateway()
    gw._breakers['qwen'].open_until = time.monotonic() + 60
    monkeypatch.setattr(gw, '_log_call', lambda *a: None)
    response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))])
    monkeypatch.setattr(gw, '_client', lambda p: SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: response))))
    assert gw.chat_text('outline', 'standard', 's', 'u', job_id=8) == 'ok'
    assert records[0]['provider'] == 'deepseek'
    assert records[0]['fallback'] is True


def test_capture_persists_real_sql_row_without_content(monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app import observability as obs
    from app.models.models import LLMObservation
    engine = create_engine('sqlite://')
    LLMObservation.__table__.create(engine)
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
            db.commit()
    monkeypatch.setattr('app.core.database.db_session', session)
    with obs.capture(task_type='test_sql', model='model', input_data='private') as event:
        event.update(obs.normalize_usage({'prompt_tokens': 10, 'completion_tokens': 4}))
    with Session(engine) as db:
        row = db.scalars(select(LLMObservation)).one()
        assert row.input_tokens == 10 and row.output_tokens == 4
        assert row.usage_source == 'reported'
        assert row.cost_usd is None
