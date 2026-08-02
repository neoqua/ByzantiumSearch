# Spec: Remote LLM providers (YandexGPT + generic OpenAI)

**Date:** 2026-08-02
**Status:** Approved (user reviewed design sections 1-4)
**Base:** current `master` (`d7504bf`), after UGC-priority search + stop feature

## Problem

The app currently uses only a local LLM (LM Studio, OpenAI-compatible, `http://localhost:1234`,
`meta-llama-3.1-8b-instruct`) configured via `.env`. There is no way to use a remote LLM.

Goal: let the user switch between local and remote LLM from the start page. Remote options:
- **YandexGPT** via Yandex Cloud API (`llm.api.cloud.yandex.net/foundationModels/v1/completion`, non-OpenAI format)
- **generic OpenAI-compatible API** (any provider speaking `chat/completions` with an API key)

## Design decisions (from brainstorming)

| Question | Decision |
|---|---|
| Where are connection settings stored? | Browser `localStorage`; sent with each analysis request; key never stored server-side |
| Remote scope | YandexGPT (Yandex Cloud) + generic OpenAI-compatible |
| Connection test | "Проверить подключение" button on start page before analysis |
| Yandex fields | API key, endpoint, folder ID, model (yandexgpt-lite/yandexgpt), version |
| Local fields | endpoint + model (editable in same panel, default localhost:1234) |
| Remote LLM failure | Same semantics as today: `analyze_text_with_retry` catches, retries, returns fallback data (`mentions_object=False`); task continues. Not a hard `failed` task status. |
| Client architecture | Provider classes: `LLMProvider` ABC + `LocalOpenAIProvider`, `GenericOpenAIProvider`, `YandexCloudProvider`, factory `get_provider` |
| Fallback when no settings sent | Use `config.py` defaults (current behavior), backward compatible |

## LLM provider layer

### New file: `app/llm_providers.py`

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str: ...

class LocalOpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str)
    # POST {endpoint}/v1/chat/completions
    # body: {"model", "messages":[{"role":"user","content":prompt}], "temperature":0.1, "max_tokens":256}
    # response: data["choices"][0]["message"]["content"]

class GenericOpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str, api_key: str)
    # as Local + header Authorization: Bearer {api_key}

class YandexCloudProvider(LLMProvider):
    def __init__(self, endpoint: str, model: str, api_key: str, folder_id: str, version: str)
    # POST {endpoint} (full URL, no /v1/chat/completions appended)
    # headers: Authorization: Api-Key {api_key}
    # body: {"modelUri": f"gpt://{folder_id}/{model}/{version}",
    #        "completionOptions": {"temperature":0.1, "maxTokens":256},
    #        "messages":[{"role":"user","text":prompt}]}
    # response: data["result"]["alternatives"][0]["message"]["text"]

def get_provider(settings: LLMSettings) -> LLMProvider:
    # local  -> LocalOpenAIProvider(endpoint or config default, model or config default)
    # openai -> GenericOpenAIProvider(api_key required, endpoint required, model required)
    # yandex -> YandexCloudProvider(api_key + folder_id required; endpoint/model/version have defaults)
```

- Each provider returns **raw text**; prompt building and JSON parsing stay in `llm.py`.
- HTTP timeouts: 60s (same as today), `httpx.AsyncClient`.
- Providers raise `httpx.HTTPStatusError` / `KeyError` on failure; `analyze_text_with_retry` handles them.

## Schema changes (`app/schemas.py`)

```python
class LLMSettings(BaseModel):
    provider: Literal["local", "yandex", "openai"] = "local"
    endpoint: Optional[str] = None      # local: base URL; yandex: full completion URL; openai: base URL
    model: Optional[str] = None         # local model / yandexgpt-lite / openai model name
    api_key: Optional[str] = None       # yandex, openai only
    folder_id: Optional[str] = None     # yandex only
    version: Optional[str] = "latest"   # yandex only
```

- `SearchRequest` gains `llm_settings: Optional[LLMSettings] = None`.

## Defaults when fields empty

- local: endpoint `http://localhost:1234`, model from `config.lm_studio_model`
- yandex: endpoint `https://llm.api.cloud.yandex.net/foundationModels/v1/completion`, model `yandexgpt-lite`, version `latest`
- openai: endpoint and model required (no defaults)

## LLM changes (`app/llm.py`)

- `analyze_text(object_name, keywords, title, text, llm_settings: Optional[LLMSettings] = None) -> dict`:
  - `provider = get_provider(llm_settings)` (defaults to local when `llm_settings is None`)
  - `text = await provider.complete(prompt)`; then existing `_parse_response`, `_coerce_result`.
- `analyze_text_with_retry(..., llm_settings: Optional[LLMSettings] = None)` passes `llm_settings` to `analyze_text`.
- `_build_prompt`, `_parse_response`, `_coerce_result`, fallback dict unchanged.

## Call chain changes

- `app/scraper.py` — `fetch_and_analyze(..., llm_settings: Optional[LLMSettings] = None)` passes it to `analyze_text_with_retry`.
- `app/analyzer.py` — `run_analysis(task_id, object_name, keywords_raw, manual_urls_raw=None, llm_settings=None)` passes it to `fetch_and_analyze`.
- `app/main.py` — `api_search` passes `body.llm_settings` to `run_analysis`.

## API: connection test endpoint

```python
@app.post("/api/llm/test")
async def test_llm(settings: LLMSettings):
    try:
        provider = get_provider(settings)          # ValueError -> 400
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    try:
        await provider.complete("Say OK")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}      # 200, front shows the message
```

- Invalid settings (empty api_key for yandex/openai, empty endpoint/model for openai) → 400.
- Network/auth errors → 200 `{"ok": false, "error": "..."}`.

## Frontend (`app/templates/index.html`)

Collapsible `details` section "Настройки подключения LLM" between `manual_urls` and the submit button:

- Provider `<select>`: local / yandex / openai.
- Three field groups, only the active one visible:
  - local: endpoint (`http://localhost:1234`), model (`meta-llama-3.1-8b-instruct`)
  - yandex: api_key (password), endpoint (default `.../foundationModels/v1/completion`), folder_id, model select (`yandexgpt-lite` / `yandexgpt`)
  - openai: api_key (password), endpoint, model
- Button "Проверить подключение" → `POST /api/llm/test` → green "Подключение работает" or red error text.
- JS logic:
  - On load: read `localStorage["llm_settings"]`, populate fields, show active provider group.
  - On provider change: switch visible group, persist all three sets + active `provider`.
  - On submit: build `llm_settings` object from active group, include in `POST /api/search` body.

## Files touched

- Modify: `app/schemas.py`, `app/llm.py`, `app/analyzer.py`, `app/scraper.py`, `app/main.py`, `app/templates/index.html`, `tests/test_llm.py`, `tests/test_api.py`
- Create: `app/llm_providers.py`

## Testing / verification

- pytest files written "for the record" (not run; pytest hangs on this machine).
- Manual verification via venv python throwaway script `C:\Temp\opencode\manual_test_llm_providers.py`: mock `httpx.AsyncClient`; assert Yandex request shape (`modelUri`, `text` field, `Api-Key` header), OpenAI shape (Bearer header), local (no key), and `POST /api/llm/test` via ASGI transport.

## Out of scope

- Streaming responses.
- Server-side persistence of settings (keys never stored server-side).
- Auto-fallback from remote to local on failure (decision: stop-with-error semantics, i.e. current fallback data behavior).
- Secret storage beyond `localStorage` (no encryption).
