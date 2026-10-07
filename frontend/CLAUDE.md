# frontend/CLAUDE.md

React 19 + TypeScript SPA built with Vite. Setup, branching and the merge checklist are in
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
Pydantic schema, so `backend/app/` is the reference, for example:

- `CurrentUser` (`src/api/auth.ts`) mirrors `UserOut`, and carries `permissions: string[]`.
- `Venue` / `VenueSummary` (`src/api/venues.ts`) mirror the venue schemas.

When a page is gated on a permission, the code is compared as a plain string against
`backend/app/auth/permissions.py`, so a renamed code fails **silently** — no type error, the nav
link simply stops appearing. Grep both sides when changing one.

## Architecture

| Path                     | Holds                                                                                                                                                                                                                                                  | May import                                                                                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/api/<feature>.ts`   | Types mirroring backend schemas, and one function per endpoint                                                                                                                                                                                         | `./client` only                                                                                                                                               |
| `src/api/client.ts`      | The single `fetch` wrapper: `api<T>()`, `ApiError`, `formatApiError`                                                                                                                                                                                   | `../errors/registry` only                                                                                                                                     |
| `src/errors/registry.ts` | The error registry: every error code, title and fallback message                                                                                                                                                                                       | nothing                                                                                                                                                       |
| `src/routes.ts`          | Route paths used by more than one file                                                                                                                                                                                                                 | nothing                                                                                                                                                       |
| `src/components/`        | Presentational pieces used by more than one page. Props only: no API calls, no auth                                                                                                                                                                    | `../api/<feature>` types; `../api/venues`'s calendar reason constants, for `venueCalendarDays.ts` only; `../routes`, `../shared/*`                            |
| `src/shared/`            | Helpers used by more than one page: formatting, the load-on-arrival hook `useLoaded`, the month-by-month venue calendar hook `useVenueCalendar`, and the status helpers `eventStatus.ts` / `bookingStatus.ts` and permission rules several pages apply | `../api/<feature>` types; `../api/client`, for `useLoaded` and `useVenueCalendar` only; `../auth/permissions`, for `venueRequest.ts` only                     |
| `src/<feature>/`         | The pages of one feature area                                                                                                                                                                                                                          | `../api/*`, `../auth/authContext`, `../auth/permissions`, `../components/*`, `../errors/registry`, `../layout/LoadingState`, `../routes`, `../shared/*`       |
| `src/auth/`              | Sign-in and the session: `AuthProvider` / `useAuth`, the route guards, the sign-in page, `permissions.ts`                                                                                                                                              | `../api/auth`, `../api/client`, `../api/health`, `../errors/registry`, `../layout/LoadingState`, `../pages/NotPermittedPage`, `../routes`, `../shared/format` |
| `src/layout/`            | The signed-in frame (sidebar, phone bar and drawer, notification bell), `navigation.ts` (every section and the permission it needs), `LoadingState`                                                                                                    | `../auth/authContext`, `../auth/permissions`, `../components/*`, `../notifications/*`, `../routes`                                                            |
| `src/notifications/`     | The notification centre: its provider, the bell's list and the toasts                                                                                                                                                                                  | `../api/client`, `../components/*`                                                                                                                            |
| `src/pages/`             | Pages belonging to no feature area, including the component gallery at `/dev/components`, routed in development builds only                                                                                                                            | anything above                                                                                                                                                |
| `src/App.tsx`            | The route map                                                                                                                                                                                                                                          | everything                                                                                                                                                    |
| `public/images/events/`  | Pictures seed events point at (`/images/events/<file>`); Vite serves `public/` as-is. Uploaded pictures are stored and served by the backend, under `/uploads/events/`                                                                                 | —                                                                                                                                                             |

Routing is **react-router v7**, imported from the `react-router` package — _not_
`react-router-dom`. Paths used in more than one file are constants in `src/routes.ts`, and links
are router `Link` / `NavLink`, never a bare `<a href>` to an in-app path.

State is plain React: `useState` + `useEffect`, with a `cancelled` flag in the cleanup so a slow
response cannot set state after unmount (`AuthProvider` in `src/auth/AuthProvider.tsx` is the
pattern). A page that only loads data when it opens uses `useLoaded` (`src/shared/useLoaded.ts`),
which holds that pattern once and returns `{ data, error, isLoading, setData }`; give it a
module-level function or a `useCallback`, never an inline arrow. The shared state is auth, held in
`AuthProvider` and read through `useAuth()`, and the notification centre, held in
`NotificationProvider` and read through `useNotifications()`.
There is no Redux, Zustand, TanStack Query or SWR, and adding one is a team decision.

Styling is plain global CSS: colour and font tokens as custom properties in `src/index.css`
(`--text`, `--accent`, `--border`, …), component classes in `src/App.css`. No CSS modules, no
Tailwind, no styled-components. Build pages from the story c3 classes (`button.secondary`,
`.card`, `.badge-<status>`, `label > input`, `.table-wrap`, …) and components before adding
new ones.

### Errors

Every failure a user can see is named in `src/errors/registry.ts`. `api<T>()` turns any failed
request into an `ApiError` with a registry `code`; an endpoint that gives a status a specific
meaning passes `errorCodes` (for example `{ 401: 'INVALID_CREDENTIALS' }` in `src/api/auth.ts`).
The message shown is the backend's own `detail` sentence when there is one, otherwise the
registry's fallback, so pages render `formatApiError(error)` and branch on `error.code`, never on
message text.

### Notifications

Every POST, PUT, PATCH and DELETE lands in the notification centre (team decision, 17 Sep 2026):
`api<T>()` reports the outcome, and `NotificationProvider` lists it under the bell beside the
sidebar wordmark and shows it briefly as a toast. Pass `notify: { title, message }` so the entry
says what changed; failures take their title from the error registry and are always marked
important. Only sign-in and sign-out pass `notify: false`. The list is per session and clears on
sign-out.

### Permission checks here are UX, not security

`RequirePermission` and `visibleNavSections` exist so a role does not see doors it cannot open
(story 1.2 AC2/AC4). The backend independently rejects every unpermitted call. Never treat a
frontend check as the thing that protects data.

Permission codes are constants in `src/auth/permissions.ts`, mirrored from
`backend/app/auth/permissions.py`. Every section of the app is one `NavItem` in
`src/layout/navigation.ts`, with the permission it needs, and both the sidebar and the main page
are built from that list (team decision, 17 Sep 2026: a role sees everything it can use there).
An item whose page is not built yet has `isAvailable: false`, and `App.tsx` routes it to
`ComingSoonPage`, which names the story that delivers it.

## Do not

- Do not import from `react-router-dom`.
- Do not call `fetch` directly — go through `api<T>()` in `src/api/client.ts`, which sends the
  session cookie (`credentials: 'include'`) and raises `ApiError`. A bare `fetch` silently drops
  the session. The scaffold's `src/api/health.ts` needs no session, so it is the exception.
- Do not read `import.meta.env.VITE_API_BASE_URL` outside `src/api/client.ts`.
- Do not write a user-facing error string in a page. Add it to `src/errors/registry.ts`, or let
  the backend's `detail` sentence through `formatApiError`.
- Do not add a state-management or data-fetching library, a component library, or a CSS framework.
- Do not add a unit test runner without team agreement.
- Do not use default exports for components — `App.tsx` is the single exception.
- Do not add barrel `index.ts` files.
- Do not gate anything on `role_code`; gate on a permission string, as `can()` does.

## Feature dev workflow

Adding `<feature>` end to end, after the backend endpoints exist:

1. `src/api/<feature>.ts` — interfaces mirroring the backend schemas, plus one function per
   endpoint calling `api<T>()`. Head each interface with a docblock naming the backend schema
   it mirrors, the way `CurrentUser` in `src/api/auth.ts` does.
2. `src/<feature>/<Name>Page.tsx` — named export. Loading, empty, and error states all rendered;
   errors through `formatApiError` into `<p role="alert" className="error">`.
3. `src/App.tsx` — add the route inside `<RequireAuth>` / `<AppLayout>`, behind
   `<RequirePermission>` when the feature is role-restricted.
4. `src/layout/navigation.ts` — set the section's `isAvailable` to `true` (or add a `NavItem`
   if the section is new). The sidebar and main page pick it up for every role holding its
   permission.
5. `src/auth/homeFor.ts` — only if a role should land on this page after login.
6. `src/App.css` — any new class names, following the existing flat naming.
7. `tests/e2e/<feature>.spec.ts` — in the `tests/` subsystem, since nothing here runs tests.

## Git and PR workflow

No frontend-specific rules — see [AGENTS.md](../AGENTS.md).
