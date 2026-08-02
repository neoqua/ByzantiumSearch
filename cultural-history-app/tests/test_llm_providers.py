import pytest
from app.schemas import LLMSettings
from app.llm_providers import (
    get_provider,
    LocalOpenAIProvider,
    GenericOpenAIProvider,
    YandexCloudProvider,
)


def test_get_provider_local_defaults_to_config():
    provider = get_provider(LLMSettings(provider="local"))
    assert isinstance(provider, LocalOpenAIProvider)


def test_get_provider_openai():
    provider = get_provider(LLMSettings(provider="openai", api_key="k", endpoint="https://x/v1", model="m"))
    assert isinstance(provider, GenericOpenAIProvider)


def test_get_provider_yandex():
    provider = get_provider(LLMSettings(provider="yandex", api_key="k", folder_id="f"))
    assert isinstance(provider, YandexCloudProvider)


def test_get_provider_openai_missing_key_raises():
    with pytest.raises(ValueError):
        get_provider(LLMSettings(provider="openai", endpoint="https://x/v1", model="m"))


def test_get_provider_yandex_missing_folder_raises():
    with pytest.raises(ValueError):
        get_provider(LLMSettings(provider="yandex", api_key="k"))
