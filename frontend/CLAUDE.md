# frontend/CLAUDE.md

React 19 + TypeScript SPA built with Vite. Setup, branching and Definition of Done are in
[AGENTS.md](../AGENTS.md). This file holds only what is specific to `frontend/` and not obvious
from reading the code.

**Removed paths.** Sprint 1 is backend-only, so the whole Sprint 1 UI (stories 1.1, 1.2 and 8.3)
was removed and `src/` is back to the scaffold placeholder, an `App.tsx` that calls
`src/api/health.ts`. Gone _(paths since deleted)_: `src/auth/`, `src/layout/`, `src/pages/`,
`src/venues/`, `src/api/auth.ts`, `src/api/client.ts`, `src/api/venues.ts`, the Sprint 1
`App.tsx` / `App.css`, and the `react-router` dependency. Everything below that points at them is
a dead anchor, kept as the convention to rebuild on; read the code at commit `6db5a5b`, for
example `git show 6db5a5b:frontend/src/auth/LoginPage.tsx`.

**Before writing or reviewing code in `frontend/`, read [STYLE.md](STYLE.md)** — the graded
coding rules for this subsystem, with the sites in this repo each one is anchored to.

@STYLE.md

## Setup and commands

```bash
npm install
npm run dev            # Vite dev server on :5173
npm run lint           # oxlint
npm run format         # prettier --write .
npm run format:check   # prettier --check .
npm run build          # tsc -b && vite build — the only type check there is
```

**There is no unit test runner here.** No vitest, no jest, no React Testing Library. The root's
`npm run test:frontend` is `lint && build`, so a component's behaviour is only ever verified by
the Playwright specs in `tests/` or by exercising it in the browser. Do not write a `*.test.tsx`
expecting it to run, and do not add a test runner without asking the team.

`oxlint` is configured with exactly two rules (`react/rules-of-hooks`,
`react/only-export-components`) plus plugin defaults, and prettier owns formatting
(no semicolons, single quotes, trailing commas, 100 columns). Everything else is review-enforced.

## Environment variables

Read from `frontend/.env` (copy `frontend/.env.sample`). Vite only exposes names prefixed
`VITE_`.

**Required: none.**

| Optional            | Default                 | Note                                  |
| ------------------- | ----------------------- | ------------------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Consumed once, in `src/api/health.ts` |

## Domain

The frontend owns no domain of its own — every type is a hand-written mirror of a backend
Pydantic schema, so `backend/app/` is the reference. The two Sprint 1 examples:

- `CurrentUser` (`src/api/auth.ts` _(path since deleted)_) mirrored `UserOut`, and carried
  `permissions: string[]`.
- `Venue` / `VenueSummary` (`src/api/venues.ts` _(path since deleted)_) mirrored the venue
  schemas.

When a page is gated on a permission again, the code is compared as a plain string against
`backend/app/auth/permissions.py`, so a renamed code fails **silently** — no type error, the nav
link simply stops appearing. Grep both sides when changing one.

## Architecture

| Path                       | Holds                                                                | May import                                |
| -------------------------- | -------------------------------------------------------------------- | ----------------------------------------- |
| `src/api/<feature>.ts`     | Types mirroring backend schemas, and one function per endpoint       | `./client` only                           |
| `src/api/client.ts`        | The single `fetch` wrapper: `api<T>()`, `ApiError`, `formatApiError` | nothing                                   |
| `src/<feature>/`           | Pages for one feature area, e.g. `src/venues/` _(since deleted)_     | `../api/<feature>`, `../auth/authContext` |
| `src/auth/`                | `AuthProvider`, `authContext`, `RequireAuth`, `LoginPage`, `homeFor` | `../api/auth`                             |
| `src/layout/AppLayout.tsx` | Header and nav                                                       | `../auth/authContext`                     |
| `src/pages/`               | Pages belonging to no feature area (`HomePage`)                      | anything above                            |
| `src/App.tsx`              | The route map                                                        | everything                                |

Routing was **react-router v7** _(removed with the Sprint 1 UI)_, imported from the
`react-router` package — _not_ `react-router-dom`. Neither is installed now.

State is plain React: `useState` + `useEffect`, with a `cancelled` flag in the cleanup so a slow
response cannot set state after unmount (`src/auth/AuthProvider.tsx:10-25` _(path since deleted)_
was the pattern). Auth was the one piece of shared state, held in `AuthProvider` and read through
`useAuth()`.
There is no Redux, Zustand, TanStack Query or SWR, and adding one is a team decision.

Styling is plain global CSS: colour and font tokens as custom properties in `src/index.css`
(`--text`, `--accent`, `--border`, …), component classes in `src/App.css`. No CSS modules, no
Tailwind, no styled-components.

### Permission checks here are UX, not security

`RequirePermission` and the `NAV_ITEMS` filter _(since deleted)_ existed so a role did not see
doors it could not open (story 1.2 AC2/AC4). The backend independently rejects every unpermitted
call. Never treat a frontend check as the thing that protects data.

## Do not

- Do not import from `react-router-dom`.
- Do not call `fetch` directly once pages call the API — go through `api<T>()` in
  `src/api/client.ts` _(path since deleted; restore it first)_, which sends the session cookie
  (`credentials: 'include'`) and raises `ApiError`. A bare `fetch` silently drops the session.
  The scaffold's `src/api/health.ts` needs no session, so it is the exception.
- Do not read `import.meta.env.VITE_API_BASE_URL` outside the one API module
  (`src/api/health.ts` today).
- Do not add a state-management or data-fetching library, a component library, or a CSS framework.
- Do not add a unit test runner without team agreement.
- Do not use default exports for components — `App.tsx` is the single exception.
- Do not add barrel `index.ts` files.
- Do not gate anything on `role_code`; gate on a permission string, as `can()` _(since deleted)_
  did.

## Feature dev workflow

Adding `<feature>` end to end, after the backend endpoints exist:

1. `src/api/<feature>.ts` — interfaces mirroring the backend schemas, plus one function per
   endpoint calling `api<T>()`. Head each interface with a docblock naming the backend schema
   it mirrors, the way `src/api/auth.ts:3` does.
2. `src/<feature>/<Name>Page.tsx` — named export. Loading, empty, and error states all rendered;
   errors through `formatApiError` into `<p role="alert" className="error">`.
3. `src/App.tsx` — add the route inside `<RequireAuth>` / `<AppLayout>`, behind a permission
   guard when the feature is role-restricted (`RequirePermission` _(since deleted)_ was the model).
4. `src/layout/AppLayout.tsx` — add a `NAV_ITEMS` entry, hidden from roles without its permission.
5. `src/auth/homeFor.ts` — only if a role should land on this page after login.
6. `src/App.css` — any new class names, following the existing flat naming.
7. `tests/e2e/<feature>.spec.ts` — in the `tests/` subsystem, since nothing here runs tests.

## Git and PR workflow

No frontend-specific rules — see [AGENTS.md](../AGENTS.md).
