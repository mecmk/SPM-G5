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
| `e2e/rbac.spec.ts` | 1.2 role-specific sidebar and main page, blocked direct URLs, collapse and phone drawer |
| `e2e/venue-catalogue.spec.ts` | 8.1 browse venues, capacity filter, withdrawn venues excluded |
| `e2e/venue-detail.spec.ts` | 8.2 venue characteristics, "Not recorded" for unset fields, Venue Staff read access |
| `e2e/venues.spec.ts` | 8.3 create, edit, delete, search and filter venues; capacity check; notifications |
| `e2e/review-queue.spec.ts` | 4.1 coordinator review queue: stage tabs (Under Review wired, others placeholders), own vs all requests, ordering, hidden drafts/decided, search, not permitted |

`e2e/support.ts` has the seed accounts, a `signIn` helper and a `venueRow` locator. Specs run
against your local development database, so use unique names for anything you create.
