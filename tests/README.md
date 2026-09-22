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
| `e2e/venue-calendar.spec.ts` | 9.1 venue availability calendar: bookings and maintenance periods shown as unavailable, month navigation |
| `e2e/event-request.spec.ts` | 2.1 raise an event request: details, dates (2-year and 14-day limits) and numbers checked live in the browser, what is still needed to submit, equipment availability and the hold made on submit, venue requirements with facility quantities, "No venue requirements" and "No accessibility needs" (vs left empty), equipment, edit/remove, submit from the new page or a draft and read-only, what is missing named, organiser-only |
| `e2e/review-queue.spec.ts` | 4.1 coordinator review queue: own vs all requests, ordering, hidden drafts/decided, search, not permitted; 6.1 the shared All-plus-seven-visible-statuses tab strip, backed by every event assigned to the coordinator in any status |
| `e2e/my-event-requests.spec.ts` | 2.6 an organiser's own list of requests: name, proposed date and status, a just-raised draft, "Not set" and "end not set" for a draft with no or half a date, opening a submitted request (read-only) or a draft (editable) from anywhere on the card, the back link following where you came from, no other organiser's requests, organiser-only, the New event request action, a long list loaded a page at a time, a card that can be selected from and holds its own buttons; a draft opens the editor and every other status opens 7.1's event details page; the empty, loading, error and paging states are reached by stubbing the list call; 6.1 the status tab strip, grouping a transitory status with the visible stage it leads into |
| `e2e/booking-requests.spec.ts` | 12.1 raise a venue booking request: only approved events assigned to the coordinator are offered, what the request carries over from the event, the pending outcome, the empty state, and no entry point for Venue Staff |
| `e2e/events.spec.ts` | 7.1 event details page: core details, venue/accessibility/equipment requirements, back link follows origin, empty states for an incomplete draft, blocked direct URL to another organiser's event |
| `e2e/decision-history.spec.ts` | 4.6 the decision status sentence (pending, awaiting-clarification hint, approved with no reason, rejected with reason) and the clarification thread (oldest first, author/kind/timestamp) on the event details page |

`e2e/support.ts` has the seed accounts, a `signIn` helper and a `venueRow` locator. Specs share
one throwaway database and run in parallel, so use unique names for anything you create.
