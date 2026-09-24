# Backend

FastAPI service for ConnectSphere. See the [root README](../README.md) for full setup and
workflow docs — this file is just a quick reference for when you're already `cd`'d in here.

## Quick reference

```bash
uv sync                              # install dependencies
uv run python -m app.dbtool ready    # start-of-day: migrate + seed + verify the database
uv run uvicorn app.main:app --reload --port 8000   # run the dev server
uv run pytest                        # run tests (needs PostgreSQL running)
uv run pytest --traceability=../docs/testing/TRACEABILITY.md   # + story/AC matrix
uv run ruff check .                  # lint
uv run ruff format --check .         # format check
```

API docs (Swagger UI) are available at `http://localhost:8000/docs` while the server is running.

## Layout

```text
app/
  main.py          FastAPI app; include each feature's router here
  config.py        settings (DATABASE_URL, session cookie, ...) read from .env
  db.py            SQLAlchemy engine/session + Base + shared mixins
  auth/            story 1.1 login/logout, 1.2 permissions (models, service, deps, router)
  venues/          story 8.x venue catalogue
  common/          cross-cutting helpers (audit log)
  dbtool/          migrate / seed / reset / ready / docs  (python -m app.dbtool --help)
db/
  migrations/      schema DDL, applied once in order (source of truth)
  seed/            idempotent reference + sample data
tests/             mirrors app/ by feature; see ../docs/testing/README.md
```

New to `uv`, or need to activate the virtual environment manually / add a new dependency? See
[docs/UV_GUIDE.md](../docs/UV_GUIDE.md). Database workflow: [docs/database/README.md](../docs/database/README.md).
