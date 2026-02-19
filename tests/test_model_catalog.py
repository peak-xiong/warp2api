from warp2api.domain.models.model_catalog import (
    ALL_KNOWN_MODELS,
    get_all_unique_models,
    get_model_config,
)


def test_model_catalog_contains_expected_models():
    expected = {
        "auto",
        "claude-4-sonnet",
        "claude-4.1-opus",
        "claude-4.5-haiku",
        "claude-4.5-opus",
        "claude-4.5-sonnet",
        "claude-4.6-opus",
        "claude-4.6-sonnet",
        "gemini-2.5-pro",
        "gemini-3-pro",
        "glm-4.7-us-hosted",
        "gpt-5",
        "gpt-5.1",
        "gpt-5.1-codex",
        "gpt-5.1-codex-max",
        "gpt-5.2",
        "gpt-5.2-codex",
        "gpt-5.3-codex",
    }
    assert expected.issubset(ALL_KNOWN_MODELS)


def test_model_config_rejects_unknown_model():
    try:
        get_model_config("not-a-real-model")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Unsupported model" in str(e)


def test_all_unique_models_is_not_empty_and_unique():
    models = get_all_unique_models()
    assert len(models) > 0
    ids = [m["id"] for m in models]
    assert len(ids) == len(set(ids))
