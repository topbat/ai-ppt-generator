import pytest
from pydantic import ValidationError

from app.ai.gateway import LLMGateway
from app.api import jobs_api
from app.core.config import Settings, default_selectable_model, selectable_models, validate_selectable_model
from app.core.database import _INCREMENTAL_COLUMNS
from app.models.models import GenerationJob
from app.schemas.dto import JobCreateReq


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_selectable_models_are_environment_ordered_and_deduplicated():
    settings = _settings(
        llm_selectable_models=" deepseek-v4, qwen3.7-plus,deepseek-v4,qwen3.8-max ",
        llm_default_selectable_model="qwen3.7-plus",
    )

    assert selectable_models(settings) == ["deepseek-v4", "qwen3.7-plus", "qwen3.8-max"]
    assert default_selectable_model(settings) == "qwen3.7-plus"


def test_default_model_must_be_in_environment_catalog():
    settings = _settings(
        llm_selectable_models="deepseek-v4,qwen3.7-plus",
        llm_default_selectable_model="qwen3.8-max",
    )

    with pytest.raises(ValueError, match="默认模型"):
        default_selectable_model(settings)


def test_submitted_model_must_match_environment_catalog():
    settings = _settings(
        llm_selectable_models="deepseek-v4,qwen3.7-plus,qwen3.8-max",
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
        llm_selectable_models="deepseek-v4,qwen3.7-plus,qwen3.8-max",
        llm_default_selectable_model="qwen3.7-plus",
    )
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)

    result = jobs_api.get_options()

    assert result["data"] == {
        "models": ["deepseek-v4", "qwen3.7-plus", "qwen3.8-max"],
        "default_model": "qwen3.7-plus",
    }


def test_gateway_model_override_retries_only_selected_model():
    gateway = LLMGateway()

    assert gateway._route("outline", "premium", "deepseek-v4") == [
        ("deepseek", "deepseek-v4"),
        ("deepseek", "deepseek-v4"),
    ]
    assert gateway._route("page_content", "fast", "qwen3.8-max") == [
        ("qwen", "qwen3.8-max"),
        ("qwen", "qwen3.8-max"),
    ]
