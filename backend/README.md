# Backend

FastAPI service for ConnectSphere. See the [root README](../README.md) for full setup and
workflow docs — this file is just a quick reference for when you're already `cd`'d in here.

## Quick reference

```bash
uv sync                              # install dependencies
uv run uvicorn app.main:app --reload --port 8000   # run the dev server
uv run pytest                        # run tests
uv run ruff check .                  # lint
uv run ruff format --check .         # format check
```

API docs (Swagger UI) are available at `http://localhost:8000/docs` while the server is running.

New to `uv`, or need to activate the virtual environment manually / add a new dependency? See
[docs/UV_GUIDE.md](../docs/UV_GUIDE.md).
