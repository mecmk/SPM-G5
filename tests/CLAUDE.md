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
npm test                                      # playwright test
npm test -- e2e/health.spec.ts                # one spec
npm test -- --headed --debug                  # watch it run
```

Both dev servers **and** a seeded database must already be running — `npm run poc` from the repo
root does all three. Nothing here starts them: `playwright.config.ts` sets no `webServer`, so
against a stopped stack every spec fails on navigation rather than reporting anything useful.

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
| `e2e/support.ts` *(path since deleted)* | Held `ACCOUNTS`, `PASSWORD`, `signIn(page, email)` and `expectSignedIn(page)`; restore it from commit `6db5a5b` when a spec needs to sign in |

**These specs run against your development database, not an isolated one.** Unlike
`backend/tests/`, there is no per-test transaction and no rollback — anything a spec creates is
still there afterwards, and `fullyParallel: true` means specs share that database concurrently.
So give every created record a unique name (`E2E Room ${Date.now()}`, as
`e2e/venues.spec.ts:9` did *(path since deleted)*) and run `npm run db:reset` from the root to clear leftovers.

Accounts a spec signs in with (formerly `e2e/support.ts` *(path since deleted)*) are rows in
`backend/db/seed/020_sample_data.sql`, which is also
mirrored in `backend/tests/support/seed.py`. A seed change means editing all three.

Traceability here is by **test title**, not by a marker: titles begin with the story and AC
(`'1.1 AC2: unknown email shows exactly the same message'`, from a spec since deleted). Only backend tests feed
`docs/testing/TRACEABILITY.md`, via `@pytest.mark.story`.

## Do not

- Do not put detailed rule or validation checks here. E2E covers flows a user clicks through;
  boundary values, 401/403 refusals and conflict cases belong in `backend/tests/`, where they
  are faster and deterministic.
- Do not create records with fixed names — parallel specs and reruns will collide.
- Do not reach into the database or call the API directly to set up a test; drive the UI, or add
  the coverage as a backend test instead.
- Do not add a `webServer` block to `playwright.config.ts` — the team starts the stack with
  `npm run poc`.
- Do not add browsers beyond chromium, or a visual-regression/screenshot dependency, without asking.
- Do not select elements by CSS class or test id — every existing spec uses accessible roles and
  labels (`getByRole`, `getByLabel`), which is also what makes them double as an a11y check.

## Feature dev workflow

1. `e2e/<feature>.spec.ts` — docblock naming the story and its ACs, mirroring the existing specs.
2. Title each test `'<story> AC<n>: <behaviour>'`.
3. Sign in with `signIn(page, ACCOUNTS.<role>)` (restore `e2e/support.ts` from `6db5a5b` first)
   rather than filling the login form, unless the login flow itself is what is under test.
4. Add the spec to the table in [README.md](README.md).

## Git and PR workflow

No e2e-specific rules — see [AGENTS.md](../AGENTS.md).
