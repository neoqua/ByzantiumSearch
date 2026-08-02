# Remote LLM Providers (YandexGPT + Generic OpenAI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user switch between the local LLM (LM Studio) and remote LLMs (YandexGPT via Yandex Cloud, or any OpenAI-compatible API) from the start page, with connection settings kept in the browser and a connection test button.

**Architecture:** Browser stores LLM connection settings in `localStorage` and sends them with each `/api/search` request as an `llm_settings` object. The backend has a provider abstraction (`app/llm_providers.py`): an `LLMProvider` ABC with `LocalOpenAIProvider`, `GenericOpenAIProvider`, and `YandexCloudProvider`, plus a `get_provider()` factory. `llm.py` keeps its prompt/parse/coerce logic; it calls `provider.complete(prompt)` for raw text and then parses as today. A `POST /api/llm/test` endpoint validates settings with a minimal call.

**Tech Stack:** FastAPI, Pydantic v2, httpx (async), Python 3.13, vanilla JS + localStorage on the frontend.

## Global Constraints

- **Do NOT run `python -m pytest`** — it hangs on this machine. All pytest files below are written "for the record"; actual verification uses venv python throwaway scripts in `C:\Temp\opencode`. Scripts that mock `httpx.AsyncClient` follow the pattern in `C:\Temp\opencode\manual_test_search.py`.
- venv python path: `cultural-history-app\venv\Scripts\python.exe` (run commands from `cultural-history-app` workdir).
- When a throwaway script needs the app importable, add `sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")` at the top, and set `os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///C:/Temp/opencode/<name>.db"` BEFORE importing `app.*`.
- Do not import `aiohttp` in throwaway scripts (it can hang on import). `httpx` is fine.
- Commit message for each task's final step is given verbatim; stage only the files listed for that task.
- Style: Python 3.13, black-ish formatting, double quotes, 4-space indent. No type hints in `config.py` (dataclass pattern) — but new modules (`llm_providers.py`) use standard type hints like the rest of `app/`.
- `.env.example` / docker-compose env vars stay unchanged (remote settings are runtime, not env).
- `LLMSettings.api_key`, `folder_id`, `endpoint`, `model`, `version` are never written to the DB or logs (no logging of settings payloads).
- Exact spec file: `docs/superpowers/specs/2026-08-02-remote-llm-providers-design.md`.

---

### Task 1: Schema `LLMSettings` + provider classes + factory

**Files:**
- Modify: `cultural-history-app/app/schemas.py`
- Create: `cultural-history-app/app/llm_providers.py`
- Test: `cultural-history-app/tests/test_llm_providers.py`

**Interfaces:**
- Consumes: `app.config.settings` (for `lm_studio_base_url`, `lm_studio_model` defaults).
- Produces:
  - `app.schemas.LLMSettings` — fields `provider: Literal["local","yandex","openai"] = "local"`, `endpoint: Optional[str] = None`, `model: Optional[str] = None`, `api_key: Optional[str] = None`, `folder_id: Optional[str] = None`, `version: Optional[str] = "latest"`.
  - `app.llm_providers.LLMProvider` (ABC), `LocalOpenAIProvider`, `GenericOpenAIProvider`, `YandexCloudProvider`, and `get_provider(settings: LLMSettings) -> LLMProvider`.
  - Each provider implements `async complete(prompt: str) -> str` returning the raw completion text.

- [ ] **Step 1: Add `LLMSettings` to `app/schemas.py`**

Add to imports: `from typing import Optional, List, Literal`. Add the class after `SearchRequest`:

```python
class LLMSettings(BaseModel):
    provider: Literal["local", "yandex", "openai"] = "local"
    endpoint: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    folder_id: Optional[str] = None
    version: Optional[str] = "latest"
```

Verify import:
Run: `.\venv\Scripts\python.exe -c "from app.schemas import LLMSettings; s=LLMSettings(); assert s.provider=='local'; assert s.version=='latest'; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 2: Write the failing test (for the record)**

Create `cultural-history-app/tests/test_llm_providers.py`:

```python
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
```

- [ ] **Step 3: Write the implementation**

Create `cultural-history-app/app/llm_providers.py`:

```python
import logging
from abc import ABC, abstractmethod
import httpx

from app.config import settings as cfg
from app.schemas import LLMSettings

logger = logging.getLogger(__name__)


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
            url = f"{self.endpoint.rstrip('/')}/v1/chat/completions"
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
            url = f"{self.endpoint.rstrip('/')}/v1/chat/completions"
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
```

The factory parameter is `llm_settings` and the config singleton is imported as `cfg` so the two `settings` names never collide. Yandex endpoint is used as-is (it is already the full completion URL); local/openai get `/v1/chat/completions` appended.

- [ ] **Step 4: Verify with a throwaway mock script**

Create `C:\Temp\opencode\manual_test_llm_providers.py`:

```python
import asyncio
import sys
import os

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

import httpx

from app.schemas import LLMSettings
from app.llm_providers import get_provider, LocalOpenAIProvider, GenericOpenAIProvider, YandexCloudProvider

captured = {}


class FakeResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", "x"), response=None)
        return None

    def json(self):
        return self._json


class FakeAsyncClient:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        if "yandex" in url or "foundationModels" in url:
            return FakeResponse({"result": {"alternatives": [{"message": {"text": '{"mentions_object": true}'}}]}})
        return FakeResponse({"choices": [{"message": {"content": '{"mentions_object": true}'}}]})


async def main():
    httpx.AsyncClient = FakeAsyncClient

    local = get_provider(LLMSettings(provider="local"))
    assert isinstance(local, LocalOpenAIProvider)
    await local.complete("hi")
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["headers"] is None
    assert "content" in captured["json"]["messages"][0]

    openai = get_provider(LLMSettings(provider="openai", api_key="k", endpoint="https://api.example.com/v1", model="m"))
    assert isinstance(openai, GenericOpenAIProvider)
    await openai.complete("hi")
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["json"]["model"] == "m"

    yandex = get_provider(LLMSettings(provider="yandex", api_key="k", folder_id="f"))
    assert isinstance(yandex, YandexCloudProvider)
    await yandex.complete("hi")
    assert captured["headers"]["Authorization"] == "Api-Key k"
    assert captured["json"]["modelUri"] == "gpt://f/yandexgpt-lite/latest"
    assert captured["json"]["messages"][0]["text"] == "hi"
    assert "content" not in captured["json"]["messages"][0]

    try:
        get_provider(LLMSettings(provider="openai", endpoint="https://x/v1", model="m"))
        assert False, "should raise"
    except ValueError:
        pass

    try:
        get_provider(LLMSettings(provider="yandex", api_key="k"))
        assert False, "should raise"
    except ValueError:
        pass

    print("LLM_PROVIDERS: PASS")


asyncio.run(main())
```

Run: `.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_llm_providers.py`
Expected: prints `LLM_PROVIDERS: PASS`.

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/schemas.py cultural-history-app/app/llm_providers.py cultural-history-app/tests/test_llm_providers.py
git commit -m "feat: LLM provider classes and factory for local/OpenAI/Yandex"
```

---

### Task 2: Wire `llm_settings` through `llm.py`

**Files:**
- Modify: `cultural-history-app/app/llm.py`
- Test: `cultural-history-app/tests/test_llm.py`

**Interfaces:**
- Consumes: `app.llm_providers.get_provider`, `app.schemas.LLMSettings` (from Task 1).
- Produces:
  - `analyze_text(object_name, keywords, title, text, llm_settings: Optional[LLMSettings] = None) -> dict`
  - `analyze_text_with_retry(object_name, keywords, title, text, max_retries=2, llm_settings: Optional[LLMSettings] = None) -> dict`
  - When `llm_settings is None`, behavior is identical to today (local provider from config).

- [ ] **Step 1: Write the failing test (for the record)**

Add to `cultural-history-app/tests/test_llm.py`:

```python
from app.schemas import LLMSettings
from app.llm_providers import get_provider
from app import llm


def test_analyze_text_accepts_llm_settings():
    async def run():
        provider = get_provider(LLMSettings(provider="local"))
        assert provider is not None
        # analyze_text signature accepts the optional arg without error when not called over the wire
        import inspect
        sig = inspect.signature(llm.analyze_text)
        assert "llm_settings" in sig.parameters
    import asyncio
    asyncio.run(run())
```

- [ ] **Step 2: Write the implementation**

In `app/llm.py`:

- Add imports:

```python
from app.llm_providers import get_provider
from app.schemas import LLMSettings
```

- Replace `analyze_text` (keep `_build_prompt` and everything below unchanged):

```python
async def analyze_text(
    object_name: str,
    keywords: list[str],
    title: str,
    text: str,
    llm_settings: Optional[LLMSettings] = None,
) -> dict:
    prompt = _build_prompt(object_name, keywords, title, text)
    provider = get_provider(llm_settings or LLMSettings(provider="local"))
    content = await provider.complete(prompt)
    return _parse_response(content)
```

- Replace the `analyze_text_with_retry` signature and its `analyze_text(...)` call:

```python
async def analyze_text_with_retry(
    object_name: str,
    keywords: list[str],
    title: str,
    text: str,
    max_retries: int = 2,
    llm_settings: Optional[LLMSettings] = None,
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            result = await analyze_text(
                object_name, keywords, title, text, llm_settings=llm_settings
            )
            return _coerce_result(result)
        except Exception as e:
            logger.warning("LLM analysis attempt %d failed: %s", attempt + 1, e)
            if attempt == max_retries:
                return _coerce_result({
                    "mentions_object": False,
                    "has_keyword": False,
                    "keyword_found": None,
                    "date_mentioned": None,
                    "publication_date": None,
                    "author_location": None,
                    "relevance_score": 0.0,
                    "source_type": "other",
                })
```

- [ ] **Step 3: Verify**

Run: `.\venv\Scripts\python.exe -c "from app.llm import analyze_text, analyze_text_with_retry; import inspect; print('OK' if 'llm_settings' in str(inspect.signature(analyze_text_with_retry)) else 'FAIL')"`
Expected: prints `OK`.

Also verify the fallback behavior with a mocked failure via a one-liner throwaway at `C:\Temp\opencode\manual_test_llm_retry.py`:

```python
import asyncio
import sys
import os

sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

from app import llm


async def main():
    orig = llm.analyze_text

    async def boom(*args, **kwargs):
        raise RuntimeError("network down")

    llm.analyze_text = boom
    try:
        result = await llm.analyze_text_with_retry("Obj", ["kw"], "T", "text", max_retries=0)
        assert result["mentions_object"] is False
        assert result["source_type"] == "other"
    finally:
        llm.analyze_text = orig
    print("LLM_RETRY: PASS")


asyncio.run(main())
```

Run: `.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_llm_retry.py`
Expected: prints `LLM_RETRY: PASS`.

- [ ] **Step 4: Commit**

```bash
git add cultural-history-app/app/llm.py cultural-history-app/tests/test_llm.py
git commit -m "feat: thread llm_settings through analysis calls"
```

---

### Task 3: Call chain (scraper/analyzer/main) + `/api/llm/test`

**Files:**
- Modify: `cultural-history-app/app/scraper.py`, `cultural-history-app/app/analyzer.py`, `cultural-history-app/app/main.py`
- Test: `cultural-history-app/tests/test_api.py`

**Interfaces:**
- Consumes: `LLMSettings`, `analyze_text_with_retry(..., llm_settings=...)` (Task 2), `get_provider` (Task 1).
- Produces:
  - `fetch_and_analyze(url, object_name, keywords, title, llm_settings: Optional[LLMSettings] = None) -> dict`
  - `run_analysis(task_id, object_name, keywords_raw, manual_urls_raw=None, llm_settings: Optional[LLMSettings] = None)`
  - `POST /api/llm/test` accepting `LLMSettings` → `{"ok": True}` or `{"ok": False, "error": "..."}`; 400 for invalid settings.

- [ ] **Step 1: Write the failing test (for the record)**

Add to `cultural-history-app/tests/test_api.py`:

```python
@pytest.mark.asyncio
async def test_llm_test_endpoint_ok(monkeypatch):
    from app import llm_providers

    class FakeProvider:
        async def complete(self, prompt):
            return "OK"

    async def fake_get_provider(settings):
        return FakeProvider()

    monkeypatch.setattr(llm_providers, "get_provider", fake_get_provider)
    from app.main import app as main_app
    transport = ASGITransport(app=main_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/llm/test", json={
            "provider": "yandex", "api_key": "k", "folder_id": "f",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_llm_test_endpoint_invalid(api_client):
    resp = await api_client.post("/api/llm/test", json={
        "provider": "openai", "endpoint": "https://x/v1", "model": "m",
    })
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
```

- [ ] **Step 2: Write the implementation**

`app/scraper.py` — change `fetch_and_analyze` signature and its `analyze_text_with_retry` call:

```python
async def fetch_and_analyze(
    url: str, object_name: str, keywords: list[str], title: str,
    llm_settings: Optional[LLMSettings] = None,
) -> dict:
    ...
    llm_result = await analyze_text_with_retry(
        object_name, keywords, title, text, llm_settings=llm_settings
    )
    ...
```

Add import: `from app.schemas import LLMSettings`.

`app/analyzer.py` — change `run_analysis` signature, pass to `fetch_and_analyze`:

```python
async def run_analysis(
    task_id: str,
    object_name: str,
    keywords_raw: str,
    manual_urls_raw: Optional[str] = None,
    llm_settings: Optional[LLMSettings] = None,
):
```

and inside the cache-miss branch:

```python
                    llm_data = await fetch_and_analyze(
                        url, object_name, keywords, title, llm_settings=llm_settings
                    )
```

Add import: `from app.schemas import LLMSettings`.

`app/main.py` — in `api_search`, pass `body.llm_settings` to the background task:

```python
    background_tasks.add_task(
        run_analysis,
        task.id,
        body.object_name,
        body.keywords,
        body.manual_urls,
        body.llm_settings,
    )
```

Add the test endpoint after `api_search`:

```python
@app.post("/api/llm/test")
async def test_llm_connection(body: LLMSettings):
    try:
        provider = get_provider(body)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    try:
        await provider.complete("Say OK")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

Add imports in `app/main.py`:

```python
from app.schemas import SearchRequest, LLMSettings
from app.llm_providers import get_provider
```

- [ ] **Step 3: Verify**

Run: `.\venv\Scripts\python.exe -c "from app.main import app; from app.schemas import LLMSettings; print('OK')"`
Expected: prints `OK` (import check; if aiohttp hangs on this import, retry once — it imports fine on fresh runs).

Then create `C:\Temp\opencode\manual_test_llm_endpoint.py`:

```python
import asyncio
import sys
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///C:/Temp/opencode/llm_endpoint_test.db"
sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

import httpx

from app import llm_providers
from app.database import init_db


class FakeProvider:
    async def complete(self, prompt):
        return '{"mentions_object": false}'


async def main():
    await init_db()
    llm_providers.get_provider = lambda settings: FakeProvider()
    from app.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/llm/test", json={"provider": "yandex", "api_key": "k", "folder_id": "f"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["ok"] is True, ok.text

        bad = await client.post("/api/llm/test", json={"provider": "openai", "endpoint": "https://x/v1", "model": "m"})
        assert bad.status_code == 400, bad.text
        assert bad.json()["ok"] is False, bad.text

        search = await client.post("/api/search", json={
            "object_name": "Obj", "keywords": "kw",
            "llm_settings": {"provider": "local"},
        })
        assert search.status_code == 200, search.text
        assert "task_id" in search.json(), search.text
    print("LLM_ENDPOINT: PASS")


asyncio.run(main())
```

Run: `.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_llm_endpoint.py`
Expected: prints `LLM_ENDPOINT: PASS`.

- [ ] **Step 4: Commit**

```bash
git add cultural-history-app/app/scraper.py cultural-history-app/app/analyzer.py cultural-history-app/app/main.py cultural-history-app/tests/test_api.py
git commit -m "feat: llm connection test endpoint and llm_settings pass-through"
```

---

### Task 4: Frontend settings panel

**Files:**
- Modify: `cultural-history-app/app/templates/index.html`

**Interfaces:**
- Consumes: `POST /api/llm/test` (Task 3), `POST /api/search` with `llm_settings` in the body (Task 3).
- Produces: settings UI; `localStorage["llm_settings"]`; `llm_settings` object included in search POST body.

- [ ] **Step 1: Write the template changes**

Add the settings panel between the `manual_urls` textarea and the submit button in `index.html`:

```html
    <details id="llm-settings">
        <summary>Настройки подключения LLM</summary>
        <label>Провайдер
            <select id="llm-provider">
                <option value="local">Локальный (LM Studio)</option>
                <option value="yandex">YandexGPT (Yandex Cloud)</option>
                <option value="openai">OpenAI-совместимый API</option>
            </select>
        </label>

        <div id="fields-local">
            <label>Эндпоинт</label>
            <input type="text" id="llm-local-endpoint" value="http://localhost:1234">
            <label>Модель</label>
            <input type="text" id="llm-local-model" placeholder="meta-llama-3.1-8b-instruct">
        </div>

        <div id="fields-yandex" style="display:none;">
            <label>API-ключ</label>
            <input type="password" id="llm-yandex-api-key">
            <label>Эндпоинт</label>
            <input type="text" id="llm-yandex-endpoint" value="https://llm.api.cloud.yandex.net/foundationModels/v1/completion">
            <label>Folder ID</label>
            <input type="text" id="llm-yandex-folder-id">
            <label>Модель</label>
            <select id="llm-yandex-model">
                <option value="yandexgpt-lite">yandexgpt-lite</option>
                <option value="yandexgpt">yandexgpt</option>
            </select>
        </div>

        <div id="fields-openai" style="display:none;">
            <label>API-ключ</label>
            <input type="password" id="llm-openai-api-key">
            <label>Эндпоинт</label>
            <input type="text" id="llm-openai-endpoint" placeholder="https://api.openai.com/v1">
            <label>Модель</label>
            <input type="text" id="llm-openai-model">
        </div>

        <button type="button" id="llm-test-btn">Проверить подключение</button>
        <span id="llm-test-result"></span>
    </details>
```

Add JS after `const data = {...}` block in the submit handler (or as a separate `<script>` function block before the form handler — either works as long as it runs before submit). Recommended: add a standalone helper block at the start of the existing `<script>`:

```js
const LLM_STORAGE_KEY = 'llm_settings';

function llmShowFields(provider) {
    document.getElementById('fields-local').style.display = provider === 'local' ? 'block' : 'none';
    document.getElementById('fields-yandex').style.display = provider === 'yandex' ? 'block' : 'none';
    document.getElementById('fields-openai').style.display = provider === 'openai' ? 'block' : 'none';
}

function llmLoadSettings() {
    const saved = JSON.parse(localStorage.getItem(LLM_STORAGE_KEY) || 'null');
    if (!saved) { llmShowFields('local'); return; }
    document.getElementById('llm-provider').value = saved.provider || 'local';
    if (saved.local) {
        document.getElementById('llm-local-endpoint').value = saved.local.endpoint || '';
        document.getElementById('llm-local-model').value = saved.local.model || '';
    }
    if (saved.yandex) {
        document.getElementById('llm-yandex-api-key').value = saved.yandex.api_key || '';
        document.getElementById('llm-yandex-endpoint').value = saved.yandex.endpoint || '';
        document.getElementById('llm-yandex-folder-id').value = saved.yandex.folder_id || '';
        document.getElementById('llm-yandex-model').value = saved.yandex.model || 'yandexgpt-lite';
    }
    if (saved.openai) {
        document.getElementById('llm-openai-api-key').value = saved.openai.api_key || '';
        document.getElementById('llm-openai-endpoint').value = saved.openai.endpoint || '';
        document.getElementById('llm-openai-model').value = saved.openai.model || '';
    }
    llmShowFields(saved.provider || 'local');
}

function llmCollectSettings() {
    const provider = document.getElementById('llm-provider').value;
    const local = {
        endpoint: document.getElementById('llm-local-endpoint').value,
        model: document.getElementById('llm-local-model').value,
    };
    const yandex = {
        api_key: document.getElementById('llm-yandex-api-key').value,
        endpoint: document.getElementById('llm-yandex-endpoint').value,
        folder_id: document.getElementById('llm-yandex-folder-id').value,
        model: document.getElementById('llm-yandex-model').value,
    };
    const openai = {
        api_key: document.getElementById('llm-openai-api-key').value,
        endpoint: document.getElementById('llm-openai-endpoint').value,
        model: document.getElementById('llm-openai-model').value,
    };
    const stored = { provider: provider, local: local, yandex: yandex, openai: openai };
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(stored));
    const active = provider === 'local' ? local : provider === 'yandex' ? yandex : openai;
    return Object.assign({ provider: provider }, active);
}
```

Add to the submit handler, before `const resp = await fetch('/api/search'...`:

```js
    data.llm_settings = llmCollectSettings();
```

Add initialization on page load (at the end of the existing `<script>`):

```js
document.getElementById('llm-provider').addEventListener('change', function() {
    llmShowFields(this.value);
});
document.getElementById('llm-test-btn').addEventListener('click', async function() {
    const btn = this;
    const resultEl = document.getElementById('llm-test-result');
    resultEl.textContent = 'Проверка...';
    btn.disabled = true;
    try {
        const resp = await fetch('/api/llm/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(llmCollectSettings()),
        });
        const body = await resp.json();
        if (body.ok) {
            resultEl.textContent = 'Подключение работает';
            resultEl.style.color = 'green';
        } else {
            resultEl.textContent = body.error || 'Ошибка подключения';
            resultEl.style.color = 'red';
        }
    } catch (e) {
        resultEl.textContent = 'Ошибка запроса';
        resultEl.style.color = 'red';
    } finally {
        btn.disabled = false;
    }
});
llmLoadSettings();
```

- [ ] **Step 2: Verify**

Render the template via Jinja2 without starting the app:

```powershell
.\venv\Scripts\python.exe -c @"
import sys
sys.path.insert(0, r'F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app')
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader(r'F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app\app\templates'))
tpl = env.get_template('index.html')
html = tpl.render()
assert 'llm-provider' in html
assert 'llm-yandex-api-key' in html
assert 'llm-test-btn' in html
assert 'llmCollectSettings' in html
assert 'localStorage' in html
print('TEMPLATE: PASS')
"@
```

Expected: prints `TEMPLATE: PASS`.

- [ ] **Step 3: Commit**

```bash
git add cultural-history-app/app/templates/index.html
git commit -m "feat: LLM connection settings panel on start page"
```

---

### Task 5: End-to-end verification

**Files:**
- Create: `C:\Temp\opencode\manual_test_llm_e2e.py` (throwaway, not committed)

**Interfaces:**
- Consumes: full app.

- [ ] **Step 1: Write the e2e script**

`C:\Temp\opencode\manual_test_llm_e2e.py`:

```python
import asyncio
import sys
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///C:/Temp/opencode/llm_e2e_test.db"
sys.path.insert(0, r"F:\VisuallStudioProjects\ByzantiumSearch\cultural-history-app")

import httpx

from app import llm_providers
from app.database import init_db


class FakeProvider:
    def __init__(self, settings):
        self.settings = settings

    async def complete(self, prompt):
        assert "Analyze the text below" in prompt
        return '{"mentions_object": true, "has_keyword": true, "keyword_found": "kw", "relevance_score": 0.9, "source_type": "blog"}'


async def main():
    await init_db()
    llm_providers.get_provider = lambda settings: FakeProvider(settings)

    import app.main as main_mod
    import app.analyzer as analyzer_mod

    # keep real run_analysis but stub search to a single fake URL to avoid network
    original_search_urls = analyzer_mod.search_urls

    async def fake_search_urls(object_name, keywords):
        return [{"url": "https://example.com/post1", "title": "Fake post"}]

    analyzer_mod.search_urls = fake_search_urls
    try:
        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/search", json={
                "object_name": "Test",
                "keywords": "kw",
                "llm_settings": {"provider": "yandex", "api_key": "k", "folder_id": "f"},
            })
            assert resp.status_code == 200, resp.text
            task_id = resp.json()["task_id"]

            for _ in range(30):
                prog = await client.get(f"/api/tasks/{task_id}/progress")
                if "event: done" in prog.text:
                    break
                await asyncio.sleep(0.2)

            results = await client.get(f"/api/tasks/{task_id}/results")
            data = results.json()
            assert data["status"] == "completed", data
            assert len(data["results"]) == 1, data
            r = data["results"][0]
            assert r["source_type"] == "blog", r
            assert r["mentions_object"] is True, r

            page = await client.get(f"/results/{task_id}")
            assert "<td>blog</td>" in page.text, page.text[:300]
    finally:
        analyzer_mod.search_urls = original_search_urls

    print("LLM_E2E: PASS")


asyncio.run(main())
```

Note: the real `run_analysis` will call `fetch_and_analyze` → `fetch_page_text` via aiohttp on `https://example.com/post1`. If aiohttp import hangs in this process, fall back to monkeypatching `analyzer_mod.fetch_and_analyze` with an async fake returning a canned dict (replace the `fake_search_urls` approach). Prefer the full path first; use the fallback only if aiohttp stalls.

- [ ] **Step 2: Run it**

Run: `.\venv\Scripts\python.exe C:\Temp\opencode\manual_test_llm_e2e.py`
Expected: prints `LLM_E2E: PASS`.

- [ ] **Step 3: Confirm all commits**

```bash
git log --oneline -7
```

Expected: the five new feature commits (Tasks 1-4) on top of the previous work; `git status` clean except `.superpowers/`, `docs/superpowers/plans/2026-08-02-ugc-priority-search-stop.md`, `описание.txt`.

- [ ] **Step 4: (Optional) Update AGENTS.md**

Add a line under Architecture notes: the app supports local (LM Studio) and remote LLM providers (Yandex Cloud YandexGPT, OpenAI-compatible) selectable on the start page; connection settings live in browser `localStorage` and are sent per-request; `POST /api/llm/test` validates a connection.

Commit only if added:
```bash
git add AGENTS.md
git commit -m "docs: note remote LLM provider support"
```

---

## Self-Review Notes

- **Spec coverage:** provider layer (Task 1) ✓; `llm.py` wiring (Task 2) ✓; call chain + test endpoint (Task 3) ✓; frontend panel + localStorage (Task 4) ✓; e2e (Task 5) ✓. All spec sections map to tasks.
- **Defaults:** local endpoint/model from config (Task 1 factory); Yandex endpoint/model/version defaults in factory (Task 1); OpenAI requires key+endpoint+model → ValueError → 400 (Task 3).
- **Error semantics:** remote failures flow through `analyze_text_with_retry` → fallback data (`mentions_object=False`), task continues (spec decision).
- **No server-side key storage:** `llm_settings` only travels in request bodies and in-memory; never logged (constraint).
- **Type consistency:** `LLMSettings` fields used identically in schema, factory, and frontend `llmCollectSettings` (`provider`, `endpoint`, `model`, `api_key`, `folder_id`, `version`). `version` is sent from the frontend Yandex object only; for local/openai the frontend active object carries only the relevant fields — the schema defaults fill the rest.
