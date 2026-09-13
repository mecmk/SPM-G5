# frontend/CLAUDE.md

React 19 + TypeScript SPA built with Vite. Setup, branching and Definition of Done are in
[AGENTS.md](../AGENTS.md). This file holds only what is specific to `frontend/` and not obvious
from reading the code.

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
| `VITE_API_BASE_URL` | `http://localhost:8000` | Consumed once, in `src/api/client.ts` |

## Domain

The frontend owns no domain of its own — every type is a hand-written mirror of a backend
Pydantic schema, so `backend/app/` is the reference. The two that matter:

- `CurrentUser` (`src/api/auth.ts`) mirrors `UserOut`, and carries `permissions: string[]`.
- `Venue` / `VenueSummary` (`src/api/venues.ts`) mirror the venue schemas.

Permission codes are compared as plain strings against
`backend/app/auth/permissions.py`, so a renamed code fails **silently** — no type error, the nav
link simply stops appearing. Grep both sides when changing one.

## Architecture

| Path                       | Holds                                                                | May import                                |
| -------------------------- | -------------------------------------------------------------------- | ----------------------------------------- |
| `src/api/<feature>.ts`     | Types mirroring backend schemas, and one function per endpoint       | `./client` only                           |
| `src/api/client.ts`        | The single `fetch` wrapper: `api<T>()`, `ApiError`, `formatApiError` | nothing                                   |
| `src/<feature>/`           | Pages for one feature area, e.g. `src/venues/`                       | `../api/<feature>`, `../auth/authContext` |
| `src/auth/`                | `AuthProvider`, `authContext`, route guards, `LoginPage`, `homeFor`  | `../api/auth`                             |
| `src/layout/AppLayout.tsx` | Header and the permission-filtered nav                               | `../auth/authContext`                     |
| `src/pages/`               | Pages belonging to no feature area (`HomePage`)                      | anything above                            |
| `src/App.tsx`              | The route map                                                        | everything                                |

Routing is **react-router v7**, imported from the `react-router` package — _not_
`react-router-dom`, which is not installed.

State is plain React: `useState` + `useEffect`, with a `cancelled` flag in the cleanup so a slow
response cannot set state after unmount (`VenueManagePage.tsx:13-25` is the pattern to copy).
Auth is the one piece of shared state, held in `AuthProvider` and read through `useAuth()`.
There is no Redux, Zustand, TanStack Query or SWR, and adding one is a team decision.

Styling is plain global CSS: colour and font tokens as custom properties in `src/index.css`
(`--text`, `--accent`, `--border`, …), component classes in `src/App.css`. No CSS modules, no
Tailwind, no styled-components.

### Permission checks here are UX, not security

`RequirePermission` and the `NAV_ITEMS` filter exist so a role does not see doors it cannot
open (story 1.2 AC2/AC4). The backend independently rejects every unpermitted call. Never treat
a frontend check as the thing that protects data.

## Do not

- Do not import from `react-router-dom`.
- Do not call `fetch` directly — go through `api<T>()` in `src/api/client.ts`, which sends the
  session cookie (`credentials: 'include'`) and raises `ApiError`. A bare `fetch` silently
  drops the session.
- Do not read `import.meta.env.VITE_API_BASE_URL` outside `src/api/client.ts`.
- Do not add a state-management or data-fetching library, a component library, or a CSS framework.
- Do not add a unit test runner without team agreement.
- Do not use default exports for components — `App.tsx` is the single exception.
- Do not add barrel `index.ts` files.
- Do not gate anything on `role_code`; gate on a permission string via `can()`.

## Feature dev workflow

Adding `<feature>` end to end, after the backend endpoints exist:

1. `src/api/<feature>.ts` — interfaces mirroring the backend schemas, plus one function per
   endpoint calling `api<T>()`. Head each interface with a docblock naming the backend schema
   it mirrors, the way `src/api/auth.ts:3` does.
2. `src/<feature>/<Name>Page.tsx` — named export. Loading, empty, and error states all rendered;
   errors through `formatApiError` into `<p role="alert" className="error">`.
3. `src/App.tsx` — add the route inside `<RequireAuth>` / `<AppLayout>`, wrapped in
   `<RequirePermission permission="…" />` when the feature is role-restricted.
4. `src/layout/AppLayout.tsx` — add a `NAV_ITEMS` entry with its permission code.
5. `src/auth/homeFor.ts` — only if a role should land on this page after login.
6. `src/App.css` — any new class names, following the existing flat naming.
7. `tests/e2e/<feature>.spec.ts` — in the `tests/` subsystem, since nothing here runs tests.

## Git and PR workflow

No frontend-specific rules — see [AGENTS.md](../AGENTS.md).
