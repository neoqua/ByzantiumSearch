import logging
from abc import ABC, abstractmethod
import httpx

from app.config import settings as cfg
from app.schemas import LLMSettings

logger = logging.getLogger(__name__)


def _chat_completions_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str:
        ...


class LocalOpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model

    async def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 256,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = _chat_completions_url(self.endpoint)
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


class GenericOpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str, api_key: str):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key

    async def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 256,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = _chat_completions_url(self.endpoint)
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


class YandexCloudProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str, api_key: str, folder_id: str, version: str):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.folder_id = folder_id
        self.version = version

    async def complete(self, prompt: str) -> str:
        payload = {
            "modelUri": f"gpt://{self.folder_id}/{self.model}/{self.version}",
            "completionOptions": {"temperature": 0.1, "maxTokens": 256},
            "messages": [{"role": "user", "text": prompt}],
        }
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["result"]["alternatives"][0]["message"]["text"]


def get_provider(llm_settings: LLMSettings) -> LLMProvider:
    provider = llm_settings.provider
    if provider == "local":
        return LocalOpenAIProvider(
            endpoint=llm_settings.endpoint or cfg.lm_studio_base_url,
            model=llm_settings.model or cfg.lm_studio_model,
        )
    if provider == "openai":
        if not llm_settings.api_key:
            raise ValueError("API-ключ обязателен для OpenAI-совместимого API")
        if not llm_settings.endpoint:
            raise ValueError("Эндпоинт обязателен для OpenAI-совместимого API")
        if not llm_settings.model:
            raise ValueError("Модель обязательна для OpenAI-совместимого API")
        return GenericOpenAIProvider(
            endpoint=llm_settings.endpoint,
            model=llm_settings.model,
            api_key=llm_settings.api_key,
        )
    if provider == "yandex":
        if not llm_settings.api_key:
            raise ValueError("API-ключ обязателен для Yandex Cloud")
        if not llm_settings.folder_id:
            raise ValueError("Folder ID обязателен для Yandex Cloud")
        return YandexCloudProvider(
            endpoint=llm_settings.endpoint
            or "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            model=llm_settings.model or "yandexgpt-lite",
            api_key=llm_settings.api_key,
            folder_id=llm_settings.folder_id,
            version=llm_settings.version or "latest",
        )
    raise ValueError(f"Неизвестный провайдер: {provider}")
