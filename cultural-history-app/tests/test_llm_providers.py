import pytest
from app.config import settings
from app.schemas import LLMSettings
from app.llm_providers import (
    get_provider,
    LocalOpenAIProvider,
    GenericOpenAIProvider,
    YandexCloudProvider,
    normalize_yandex_api_key,
)


def test_get_provider_local_defaults_to_config():
    provider = get_provider(LLMSettings(provider="local"))
    assert isinstance(provider, LocalOpenAIProvider)


def test_get_provider_openai():
    provider = get_provider(LLMSettings(provider="openai", api_key="k", endpoint="https://x/v1", model="m"))
    assert isinstance(provider, GenericOpenAIProvider)


def test_get_provider_yandex(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "fromenv")
    provider = get_provider(LLMSettings(provider="yandex", folder_id="f"))
    assert isinstance(provider, YandexCloudProvider)
    assert provider.api_key == "fromenv"


def test_get_provider_openai_missing_key_raises():
    with pytest.raises(ValueError):
        get_provider(LLMSettings(provider="openai", endpoint="https://x/v1", model="m"))


def test_normalize_yandex_api_key_strips_prefix():
    assert normalize_yandex_api_key("  Api-Key secret  ") == "secret"
    assert normalize_yandex_api_key("Bearer secret") == "secret"
    assert normalize_yandex_api_key('"secret"') == "secret"


def test_get_provider_yandex_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "")
    with pytest.raises(ValueError, match="YANDEX_API_KEY"):
        get_provider(LLMSettings(provider="yandex", folder_id="f"))


def test_get_provider_yandex_ignores_client_key(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "fromenv")
    provider = get_provider(LLMSettings(provider="yandex", api_key="from-browser", folder_id="f"))
    assert provider.api_key == "fromenv"


def test_get_provider_yandex_missing_folder_raises(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "k")
    monkeypatch.setattr(settings, "yandex_folder_id", "")
    with pytest.raises(ValueError, match="Folder ID"):
        get_provider(LLMSettings(provider="yandex"))


def test_get_provider_yandex_folder_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(settings, "yandex_folder_id", "b1gfromenv")
    monkeypatch.setattr(settings, "yandex_api_key", "k")
    provider = get_provider(LLMSettings(provider="yandex", folder_id=""))
    assert isinstance(provider, YandexCloudProvider)
    assert provider.folder_id == "b1gfromenv"


def test_get_provider_yandex_strips_folder(monkeypatch):
    monkeypatch.setattr(settings, "yandex_api_key", "k")
    monkeypatch.setattr(settings, "yandex_folder_id", "")
    provider = get_provider(LLMSettings(provider="yandex", folder_id="  f  "))
    assert provider.folder_id == "f"
