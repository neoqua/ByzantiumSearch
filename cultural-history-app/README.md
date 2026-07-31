# Cultural History Analysis App

FastAPI web service: searches travel blogs for mentions of cultural/historical
objects via SearXNG, analyzes relevance with Llama 3.1-8B (LM Studio), generates
reports.

## Requirements

- Docker Desktop (Windows/Mac) — for SearXNG and the app container
- LM Studio running on the host, port 1234, model `meta-llama-3.1-8b-instruct`
  (set `LM_STUDIO_MODEL` if different)

## Docker mode (recommended)

1. Start LM Studio and load the model (`http://localhost:1234/v1/models` should respond).
2. From `cultural-history-app/`:

   `docker compose up -d --build`

3. Open `http://localhost:8000` in a browser.
4. SearXNG is also exposed at `http://localhost:8888` (optional).

Stopping: `docker compose down`. SQLite data persists in `./data/`.

Notes:
- The app container reaches LM Studio on the host via `host.docker.internal:1234`.
- Rebuild after Python-code changes: `docker compose up -d --build`.
- No `.env` needed — configuration comes from `docker-compose.yml`
  `environment:` (see `.env.example`).

## Host mode (debugging, no container for the app)

Requires Python 3.13 + the venv already set up, SearXNG up via Docker:

`docker compose up -d searxng`

then, from `cultural-history-app/`:

```
.\venv\Scripts\python.exe -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

`config.py` defaults already point to `localhost:8888` (SearXNG) and
`localhost:1234` (LM Studio); create a `.env` only to override (see `.env.example`).
Open `http://localhost:8000`.

## Tests

Test logic is verified manually via `python -c` scripts — `pytest` hangs on
Windows/Python 3.13 (see AGENTS.md Known issues).
