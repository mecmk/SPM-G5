# tests/CLAUDE.md

Playwright end-to-end specs, a separate npm package from `frontend/`. Conventions for all three
test layers live in [docs/testing/README.md](../docs/testing/README.md) — read that first. This
file holds only what is specific to `tests/` and not obvious from reading the specs.

**Before writing or reviewing specs in `tests/`, read [STYLE.md](STYLE.md)** — the graded
conventions for this subsystem, and the note that nothing here is linted or formatted.

@STYLE.md

## Setup and commands

```bash
npm install
npx playwright install --with-deps chromium   # chromium only; no other browser is configured
```

Run the specs from the **repo root**, never with a bare `npm test` here:

```bash
npm run test:e2e                          # every spec
npm run test:e2e -- e2e/health.spec.ts    # one spec
npm run test:e2e -- --headed --debug      # watch it run
```

`scripts/e2e.mjs` rebuilds a throwaway `connectsphere_e2e` database, starts its own API (`:8001`)
and Vite server (`:5174`) on it, runs Playwright, then stops the servers and empties the database.
It only needs PostgreSQL up (`npm run db:up`); a dev stack on `:8000` / `:5173` can stay running.
`playwright.config.ts` sets no `webServer`, and `global-setup.ts` refuses to start unless
`E2E_ISOLATED_DB=1` is set (the runner and CI set it), so specs cannot be pointed at a dev database
by accident.

## Environment variables

**Required: none.**

| Optional | Default | Note |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:5173` | Playwright's `baseURL`; specs navigate with relative paths like `page.goto('/login')` |
| `CI` | unset | When set, retries once instead of zero |

## Architecture

| Path | Holds |
| --- | --- |
| `e2e/<feature>.spec.ts` | One spec per story area, headed by a docblock naming the story and the ACs it covers |
| `e2e/support.ts` | Holds `ACCOUNTS`, `PASSWORD`, `signIn(page, email)` and `expectSignedIn(page)` for specs that need to sign in |

**These specs run against a throwaway database, never your development one.** Unlike
`backend/tests/`, there is no per-test transaction and no rollback: within a run, anything a spec
creates stays until the run ends, and `fullyParallel: true` means specs share that database
concurrently. So give every created record a unique name (`E2E Room ${Date.now()}`, as
`e2e/venues.spec.ts:9` does). Nothing survives the run, so there is no leftover to clear.

Accounts a spec signs in with (`e2e/support.ts`) are rows in `backend/db/seed/020_sample_data.sql`,
which is also mirrored in `backend/tests/support/seed.py`. A seed change means editing all three.

Traceability here is by **test title**, not by a marker: titles begin with the story and AC
(`'1.1 AC2: unknown email shows exactly the same message'`). Only backend tests feed
`docs/testing/TRACEABILITY.md`, via `@pytest.mark.story`.

## Do not

- Do not put detailed rule or validation checks here. E2E covers flows a user clicks through;
  boundary values, 401/403 refusals and conflict cases belong in `backend/tests/`, where they
  are faster and deterministic. **Exception:** a boundary case that is purely client-side (blocks
  submit before any request fires — a required-field message, a zod schema check) has no backend
  call to assert against and no other runner (frontend has none, see
  [frontend/CLAUDE.md](../frontend/CLAUDE.md)), so it belongs here instead, as its own titled
  case.
- Do not create records with fixed names — parallel specs and reruns will collide.
- Do not reach into the database or call the API directly to set up a test; drive the UI, or add
  the coverage as a backend test instead.
- Do not add a `webServer` block to `playwright.config.ts` — `scripts/e2e.mjs` starts the stack on
  the throwaway database, and a `webServer` would start it on whatever `DATABASE_URL` says.
- Do not run, or document running, the specs against the development database, or set
  `E2E_ISOLATED_DB=1` for a stack whose database is not disposable.
- Do not add browsers beyond chromium, or a visual-regression/screenshot dependency, without asking.
- Do not select elements by CSS class or test id — every existing spec uses accessible roles and
  labels (`getByRole`, `getByLabel`), which is also what makes them double as an a11y check.

## Feature dev workflow

1. `e2e/<feature>.spec.ts` — docblock naming the story and its ACs, mirroring the existing specs.
2. Title each test `'<story> AC<n>: <behaviour>'`.
3. Sign in with `signIn(page, ACCOUNTS.<role>)` from `e2e/support.ts` rather than filling the
   login form, unless the login flow itself is what is under test.
4. Add the spec to the table in [README.md](README.md).

## Git and PR workflow

No e2e-specific rules — see [AGENTS.md](../AGENTS.md).
