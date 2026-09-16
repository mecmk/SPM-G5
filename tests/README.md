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
| `e2e/health.spec.ts` | smoke: placeholder page loads, backend reachable |

Login, role-gated navigation and venue specs are being added alongside the pages. Specs run
against your local development database, so use unique names for anything you create.
