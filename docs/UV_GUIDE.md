# New to uv?

[uv](https://docs.astral.sh/uv/) replaces `pip` + `venv` for the backend — one tool manages both
the virtual environment and the dependency list. You don't need this doc to get the app
running (`npm run setup` already does everything below for you) — it's here for when you're
curious what happened, or need to do one of these things manually.

## What `npm run setup` already did

It ran `uv sync`, which read `backend/pyproject.toml` and `backend/uv.lock` and created
`backend/.venv` — an isolated Python install containing exactly this project's dependencies,
separate from your system Python. You don't need to touch this again unless `pyproject.toml` or
`uv.lock` change (e.g. after pulling commits, or a teammate adds a dependency — then just run
`uv sync` again from `backend/`).

## You do not need to activate anything

Every command that starts with `uv run` (e.g. `uv run uvicorn ...`, `uv run pytest`)
automatically uses `backend/.venv` for that one command. That's the whole point of the prefix —
most people never need anything below this point.

## Activating the venv manually (optional)

If you'd rather have a normal activated shell for a while — so you can type `pytest`, `python`,
`ruff` directly, without the `uv run` prefix each time:

| Shell | Activate (run once, from inside `backend/`) | Deactivate |
| --- | --- | --- |
| Windows PowerShell | `.venv\Scripts\activate.ps1` | `deactivate` |
| Windows Command Prompt (cmd.exe) | `.venv\Scripts\activate.bat` | `deactivate` |
| macOS / Linux (bash/zsh) | `source .venv/bin/activate` | `deactivate` |

You'll know it worked because your terminal prompt gains a `(backend)` prefix:

```powershell
cd backend
.venv\Scripts\activate.ps1        # Windows PowerShell — see table above for your shell
(backend) PS> pytest              # no "uv run" needed now
(backend) PS> deactivate          # leave the virtual environment when done
```

> If PowerShell blocks the script with a "running scripts is disabled" error, that's Windows'
> execution policy — use `cmd.exe`'s `activate.bat` instead, or ask a teammate/instructor before
> changing execution policy settings.

## Adding a new dependency

Don't `pip install` it — that won't be recorded anywhere and the rest of the team won't get it:

```powershell
cd backend
uv add <package-name>          # a dependency the app needs to run
uv add --dev <package-name>    # a dev-only tool (testing, linting)
```

Either command installs the package **and** records it in `pyproject.toml` and `uv.lock` in one
step — commit both files so the rest of the team gets it next time they run `uv sync`.
