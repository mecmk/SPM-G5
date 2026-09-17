# E2E Tests

Playwright end-to-end tests that exercise the frontend and backend together. See the
[root README](../README.md) for full setup docs and
[docs/testing/README.md](../docs/testing/README.md) for conventions.

## Install

```bash
npm install
npx playwright install --with-deps chromium
```

## Run

Make sure the database, backend (`http://localhost:8000`) and frontend (`http://localhost:5173`)
are running - `npm run db:ready` then `npm run dev` from the repo root - then:

```bash
npm test
```

## Specs

| File | Story |
| --- | --- |
| `e2e/health.spec.ts` | smoke: sign-in page loads, backend reachable |
| `e2e/auth.spec.ts` | 1.1 sign in, sign out, redirects, generic failure message |

`e2e/support.ts` has the seed accounts and a `signIn` helper. Specs run against your local
development database, so use unique names for anything you create.
