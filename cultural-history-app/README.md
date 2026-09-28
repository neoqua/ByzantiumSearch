# Cultural History Analysis App

FastAPI web service: searches travel blogs for mentions of cultural/historical
objects via SearXNG, analyzes relevance with Llama 3.1-8B (LM Studio), generates
reports.

## Requirements

- Docker Desktop (Windows/Mac) — for SearXNG and the app container
- LM Studio running on the host, port 1234, model `meta-llama-3.1-8b-instruct`
  (set `LM_STUDIO_MODEL` if different)

## Quick start / stop (scripts)

`scripts/` contains start/stop wrappers for both platforms. They check that
Docker is running, warn if LM Studio is not answering on :1234, start the
containers, wait for health checks and print the URLs.

| | Linux / macOS | Windows |
|---|---|---|
| Start (Docker mode) | `scripts/start.sh` | `scripts\start.cmd` or `.\scripts\start.ps1` |
| Start without rebuilding the app image | `scripts/start.sh --no-build` | `scripts\start.cmd -NoBuild` |
| Start in host mode (app via uvicorn, engines in Docker) | `scripts/start.sh --host` | `scripts\start.cmd -HostMode` |
| Stop (keeps `./data`) | `scripts/stop.sh` | `scripts\stop.cmd` or `.\scripts\stop.ps1` |
| Stop and drop the SearXNG volume | `scripts/stop.sh --volumes` | `scripts\stop.cmd -Volumes` |

The `.cmd` wrappers run PowerShell with `-ExecutionPolicy Bypass`, so no policy
change is needed; they can be double-clicked. In host mode the scripts create
`./venv` and install requirements if no venv exists, then run uvicorn in the
foreground (Ctrl+C stops the app, `stop` stops the containers). LM Studio is not
managed by the scripts.

## Docker mode (recommended)

1. Start LM Studio and load the model (`http://localhost:1234/v1/models` should respond).
2. From `cultural-history-app/`:

   `docker compose up -d --build`  (or `scripts/start.sh` / `scripts\start.cmd`)

3. Open `http://localhost:8000` in a browser.
4. SearXNG is also exposed at `http://localhost:8888`, OpenSERP at `http://localhost:7000` (optional).

Stopping: `docker compose down` (or `scripts/stop.sh` / `scripts\stop.cmd`). SQLite data persists in `./data/`.

Notes:
- The app container reaches LM Studio on the host via `host.docker.internal:1234`.
- Rebuild after Python-code changes: `docker compose up -d --build`.
- No `.env` needed — configuration comes from `docker-compose.yml`
  `environment:` (see `.env.example`).

## Host mode (debugging, no container for the app)

Requires Python 3.13, SearXNG up via Docker:

`docker compose up -d searxng`

then, from `cultural-history-app/`:

```
python -m venv venv
```

Activate the venv and install dependencies (Windows: `.\venv\Scripts\Activate.ps1`,
Mac: `source venv/bin/activate`), then run:

```
pip install -r requirements.txt
uvicorn app.main:app --reload
```

(Alternatively, skip activation and call the interpreter directly:
Windows `.\venv\Scripts\python.exe -m pip install -r requirements.txt`,
Mac `venv/bin/python -m pip install -r requirements.txt`.)

`config.py` defaults already point to `localhost:8888` (SearXNG) and
`localhost:1234` (LM Studio); create a `.env` only to override (see `.env.example`).
Open `http://localhost:8000`.

## Tests

From `cultural-history-app/` with the venv active (Linux/Mac):

```
python -m pytest -q
```

All tests are offline (HTTP is mocked with `pytest-httpx`).

On the Windows dev machine `pytest` was observed to hang at collection
(Python 3.13). `pytest.ini` now disables the unused `anyio` plugin and sets
`faulthandler_timeout = 60`, so a stalled run prints the stack of every thread
after a minute instead of hanging silently — include that output when
reporting the problem. Until the cause is confirmed, run the suite inside the
Linux app image instead (Docker Desktop, from `cultural-history-app/`):

```powershell
docker compose build app
docker run --rm -v "${PWD}:/app" -w /app cultural-history-app-app python -m pytest -q
```

See AGENTS.md Known issues for the diagnostic steps and the `python -c` fallback.
