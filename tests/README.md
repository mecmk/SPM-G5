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

From the repo root, with PostgreSQL up (`npm run db:up`):

```bash
npm run test:e2e                          # every spec
npm run test:e2e -- e2e/venues.spec.ts    # one spec
```

This rebuilds a throwaway `connectsphere_e2e` database, starts its own API (`:8001`) and app
(`:5174`) on it, runs the specs and cleans up. It never touches your development database, and a
bare `npm test` in this folder is refused (see `global-setup.ts`).

## Specs

| File | Story |
| --- | --- |
| `e2e/health.spec.ts` | smoke: sign-in page loads, backend reachable |
| `e2e/auth.spec.ts` | 1.1 sign in, sign out, redirects, generic failure message |
| `e2e/rbac.spec.ts` | 1.2 role-specific sidebar and main page, blocked direct URLs, collapse and phone drawer |
| `e2e/venue-catalogue.spec.ts` | 8.1 browse venues, capacity filter, withdrawn venues excluded |
| `e2e/venue-detail.spec.ts` | 8.2 venue characteristics, "Not recorded" for unset fields, Venue Staff read access |
| `e2e/venues.spec.ts` | 8.3 create, edit, delete, search and filter venues; capacity check; notifications |
| `e2e/event-request.spec.ts` | 2.1 raise an event request: details, dates (2-year and 14-day limits) and numbers checked live in the browser, what is still needed to submit, equipment availability and the hold made on submit, venue requirements with facility quantities, "No venue requirements" and "No accessibility needs" (vs left empty), equipment, edit/remove, submit from the new page or a draft and read-only, what is missing named, organiser-only |
| `e2e/review-queue.spec.ts` | 4.1 coordinator review queue: stage tabs (Under Review wired, others placeholders), own vs all requests, ordering, hidden drafts/decided, search, not permitted |
| `e2e/booking-requests.spec.ts` | 12.1 raise a venue booking request: only approved events assigned to the coordinator are offered, what the request carries over from the event, the pending outcome, the empty state, and no entry point for Venue Staff |

`e2e/support.ts` has the seed accounts, a `signIn` helper and a `venueRow` locator. Specs share
one throwaway database and run in parallel, so use unique names for anything you create.
