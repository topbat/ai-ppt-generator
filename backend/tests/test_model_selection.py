import pytest

from app.core.config import Settings, default_selectable_model, selectable_models, validate_selectable_model


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
