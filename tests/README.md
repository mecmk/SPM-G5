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

One spec per story area. Each test title starts with its story and AC (`'1.1 AC2: …'`).

| Spec | Stories and ACs | Covers |
| --- | --- | --- |
| `e2e/health.spec.ts` | smoke | the sign-in page loads and the backend answers |
| `e2e/auth.spec.ts` | 1.1 AC1, AC2, AC4–AC6 | sign in and out, the sign-in lock |
| `e2e/rbac.spec.ts` | 1.2 AC1–AC4 | each role's sidebar and main page, blocked addresses |
| `e2e/event-request.spec.ts` | 2.1 AC1–AC11, AC13–AC17, AC19, AC20 | raising and submitting an event request |
| `e2e/venue-requirements.spec.ts` | 2.7 AC1–AC6, AC8–AC11 | listing several venue requirements, each with its own times |
| `e2e/my-event-requests.spec.ts` | 2.6 AC1–AC5, AC7–AC9, AC11, AC12 | an organiser's own list of requests |
| `e2e/review-queue.spec.ts` | 4.1 AC1–AC4; 6.1 | the coordinator's review queue and status tabs |
| `e2e/request-clarification.spec.ts` | 4.2 AC1, AC3, AC4, AC7 | asking the organiser for clarification, and a follow-up while awaiting a response |
| `e2e/respond-to-clarification.spec.ts` | 4.3 AC1, AC2, AC4, AC6 | the organiser answering a clarification request, more than once |
| `e2e/decision-history.spec.ts` | 4.6 AC1, AC2 | the decision and the clarification thread |
| `e2e/coordinator-reassignment.spec.ts` | 5.2 AC3 | handing an event to another coordinator |
| `e2e/events.spec.ts` | 2.1 AC8, AC19; 7.1 AC1, AC2 | the event details page |
| `e2e/event-routine-edit.spec.ts` | 7.2 AC1–AC3 | editing an event's internal notes through Edit event |
| `e2e/event-correction.spec.ts` | 7.2 AC4–AC9 | the assigned coordinator correcting a request under review or awaiting clarification: the save, replacing the cover picture, adding a venue requirement, a required field that cannot be emptied, equipment marked unavailable for new dates, a stale save and an approval landing mid-edit, details greyed out after approval with notes still saving, and who is offered the edit |
| `e2e/change-requests.spec.ts` | 19.1 AC1, AC2, AC4, AC5, AC9 | an organiser asking for a change to a planning event, the coordinator seeing it pending, updating the point of contact directly, and withdrawing a request |
| `e2e/venue-catalogue.spec.ts` | 8.1 AC1–AC6, AC8, AC9, AC11 | browsing and filtering the venue catalogue |
| `e2e/venue-detail.spec.ts` | 8.2 AC1–AC3 | a venue's record |
| `e2e/venues.spec.ts` | 8.1 AC12; 8.3 AC1–AC8, AC10 | creating, editing and deleting venues, and their pictures |
| `e2e/venue-calendar.spec.ts` | 9.1 AC1–AC3, AC5, AC7–AC10, AC12, AC13 | a venue's availability calendar |
| `e2e/booking-requests.spec.ts` | 12.1 AC1–AC4, AC14, AC15; 12.2 AC1, AC2, AC4 | requesting a venue for an event, and withdrawing the request |
| `e2e/bookings.spec.ts` | 13.1 AC1–AC3; 13.1.2 AC1, AC3, AC4; 13.1.3 AC1–AC4; 13.2 AC1; 13.2.1 AC2–AC4; 13.2.2 AC1 | Venue Staff's queue, Pending / All / Approved / Rejected tabs, cancellation timing, pagination, the requested venue's calendar on the request detail page, approving and rejecting, and when a decision was made |
| `e2e/equipment-requests.spec.ts` | 15.1 AC1–AC4, AC6, AC9 | recording an event's equipment and submitting it to Technical Support |
| `e2e/equipment-queue.spec.ts` | 15.2 AC1–AC3, AC5, AC6 | Technical Support's equipment request queue, its figures, its All / Pending / Accepted / Declined tabs, and View details to the event and back |
| `e2e/equipment-decisions.spec.ts` | 16.1 AC1, AC2, AC4, AC6, AC9 | Technical Support accepting and declining equipment requests from the queue and from each request's own page, a blank decline reason blocked in the browser, a short request's Accept suggesting a decline, a double-click deciding once, and the coordinator seeing each outcome and when it was decided on the event page |

Every case, by story and AC, without starting anything:

```bash
npx playwright test --list
```

`e2e/support.ts` has the seed accounts and events and the helpers more than one spec needs. Specs
share one throwaway database and run in parallel, so use unique names for anything you create.
