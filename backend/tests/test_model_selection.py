from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai import gateway as gateway_module
from app.ai.gateway import LLMGateway, provider_of
from app.api import jobs_api
from app.core.config import (Settings, beautify_selectable_model, default_selectable_model,
                             selectable_models, validate_selectable_model)
from app.core.database import _INCREMENTAL_COLUMNS
from app.models.models import GenerationJob
from app.schemas.dto import JobCreateReq


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_default_catalog_uses_actual_model_ids():
    settings = _settings()

    assert selectable_models(settings) == ["deepseek-v4-pro", "kimi-k3", "qwen3.7-plus", "qwen3.8-max"]
    assert default_selectable_model(settings) == "qwen3.7-plus"
    assert beautify_selectable_model(settings) == "kimi-k3"


def test_example_env_files_publish_actual_model_ids():
    root = Path(__file__).resolve().parents[2]

    for env_example in (root / "backend" / ".env.example", root / "deploy" / ".env.example"):
        content = env_example.read_text(encoding="utf-8")
        assert "LLM_SELECTABLE_MODELS=deepseek-v4-pro,kimi-k3,qwen3.7-plus,qwen3.8-max" in content
        assert "LLM_BEAUTIFY_MODEL=kimi-k3" in content
        assert "KIMI_API_KEY=" in content
        assert "KIMI_BASE_URL=" in content


def test_selectable_models_are_environment_ordered_and_deduplicated():
    settings = _settings(
        llm_selectable_models=" deepseek-v4-pro,kimi-k3, qwen3.7-plus,deepseek-v4-pro,qwen3.8-max ",
        llm_default_selectable_model="qwen3.7-plus",
    )

    assert selectable_models(settings) == ["deepseek-v4-pro", "kimi-k3", "qwen3.7-plus", "qwen3.8-max"]
    assert default_selectable_model(settings) == "qwen3.7-plus"


def test_default_model_must_be_in_environment_catalog():
    settings = _settings(
        llm_selectable_models="deepseek-v4-pro,qwen3.7-plus",
        llm_default_selectable_model="qwen3.8-max",
    )

    with pytest.raises(ValueError, match="默认模型"):
        default_selectable_model(settings)


def test_submitted_model_must_match_environment_catalog():
    settings = _settings(
        llm_selectable_models="deepseek-v4-pro,qwen3.7-plus,qwen3.8-max",
        llm_default_selectable_model="qwen3.7-plus",
    )

    assert validate_selectable_model(" qwen3.8-max ", settings) == "qwen3.8-max"
    with pytest.raises(ValueError, match="可选模型"):
        validate_selectable_model("qwen-max", settings)
    with pytest.raises(ValueError, match="请选择模型"):
        validate_selectable_model("", settings)


def test_normal_job_request_requires_a_model():
    common = {
        "template_id": "tpl_1",
        "document_id": "doc_1",
        "pages": 12,
        "mode": "standard",
        "density": "medium",
    }

    with pytest.raises(ValidationError):
        JobCreateReq(**common)
    assert JobCreateReq(**common, model="qwen3.7-plus").model == "qwen3.7-plus"


def test_normal_job_model_is_persisted_and_migrated():
    assert "model" in GenerationJob.__table__.c
    assert ("generation_jobs", "model", "VARCHAR(64)") in _INCREMENTAL_COLUMNS


def test_normal_job_options_come_from_environment(monkeypatch):
    settings = _settings(
        llm_selectable_models="deepseek-v4-pro,kimi-k3,qwen3.7-plus,qwen3.8-max",
        llm_default_selectable_model="qwen3.7-plus",
        llm_beautify_model="kimi-k3",
    )
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)

    result = jobs_api.get_options()

    assert result["data"] == {
        "models": ["deepseek-v4-pro", "kimi-k3", "qwen3.7-plus", "qwen3.8-max"],
        "default_model": "qwen3.7-plus",
        "beautify_model": "kimi-k3",
    }


def test_gateway_model_override_retries_only_selected_model():
    gateway = LLMGateway()

    assert gateway._route("outline", "premium", "deepseek-v4-pro") == [
        ("deepseek", "deepseek-v4-pro"),
        ("deepseek", "deepseek-v4-pro"),
    ]
    assert gateway._route("page_content", "fast", "qwen3.8-max") == [
        ("qwen", "qwen3.8-max"),
        ("qwen", "qwen3.8-max"),
    ]
    assert gateway._route("page_content", "standard", "kimi-k3") == [
        ("kimi", "kimi-k3"),
        ("kimi", "kimi-k3"),
    ]


def test_kimi_uses_dedicated_openai_compatible_provider(monkeypatch):
    settings = _settings(kimi_api_key="kimi-secret", kimi_base_url="https://kimi.example/v1")
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(gateway_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    gateway = LLMGateway()

    assert provider_of("kimi-k3") == "kimi"
    gateway._client("kimi")
    assert created == [{
        "api_key": "kimi-secret",
        "base_url": "https://kimi.example/v1",
        "timeout": settings.llm_timeout_seconds,
    }]


def test_beautify_model_must_belong_to_catalog():
    settings = _settings(
        llm_selectable_models="deepseek-v4-pro,qwen3.7-plus",
        llm_beautify_model="kimi-k3",
    )

    with pytest.raises(ValueError, match="美化模型"):
        beautify_selectable_model(settings)
