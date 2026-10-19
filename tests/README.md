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
| `e2e/rbac.spec.ts` | 1.2 AC1–AC4; 21.1 AC1 | each role's sidebar and main page, blocked addresses |
| `e2e/event-request.spec.ts` | 2.1 AC1–AC11, AC13–AC17, AC19–AC22; 2.7 AC15 | raising and submitting an event request, and the largest numbers it accepts (f2.1.5) |
| `e2e/venue-requirements.spec.ts` | 2.7 AC1–AC6, AC8–AC11, AC14, AC16–AC18 | listing several venue requirements, each with its own times; every request keeping at least one (f2.7.4), on the request form, the coordinator's form and the change request form, and a request with none shown as not recorded on its page until it is decided |
| `e2e/my-event-requests.spec.ts` | 2.6 AC1–AC5, AC7–AC9, AC11, AC12 | an organiser's own list of requests |
| `e2e/review-queue.spec.ts` | 4.1 AC1–AC4; 6.1 AC2 | the coordinator's review queue, its status tabs, and each event's dates |
| `e2e/request-clarification.spec.ts` | 4.2 AC1, AC3, AC4, AC7 | asking the organiser for clarification, and a follow-up while awaiting a response |
| `e2e/respond-to-clarification.spec.ts` | 4.3 AC1, AC2, AC4, AC6 | the organiser answering a clarification request, more than once |
| `e2e/decision-history.spec.ts` | 4.6 AC1, AC2 | the decision and the clarification thread |
| `e2e/coordinator-reassignment.spec.ts` | 5.6 AC1, AC3, AC5, AC6; responsive | the Event Coordinator Lead handing an event to another coordinator, from its page and from the overview, offered only on an active event with a coordinator; each overview view saying when its own list could not be refreshed afterwards; the picker not confirmed before its coordinators load, or with none to offer; a coordinator no longer offered Reassign; a stale reassignment's refusal; at phone, tablet and desktop widths |
| `e2e/unassigned-queue.spec.ts` | 5.4 AC1–AC3, AC5–AC9; responsive | the Event Coordinator Lead's unassigned queue, assigning from it, its empty and no-coordinator states, losing a race to another Lead, at phone and desktop widths |
| `e2e/assignment-overview.spec.ts` | 5.5 AC1–AC6; responsive | the Lead's overview of every active event and each coordinator's workload: its filters in the page address, an idle and a deactivated coordinator, opening an event read-only with only Reassign offered, at phone, tablet and desktop widths |
| `e2e/events.spec.ts` | 2.1 AC8, AC19; 7.1 AC1, AC2 | the event details page |
| `e2e/event-routine-edit.spec.ts` | 7.2 AC1–AC3 | editing an event's internal notes through Edit event |
| `e2e/event-correction.spec.ts` | 7.2 AC4, AC7–AC10, AC12, AC15 | the assigned coordinator correcting a request until it is confirmed: the save, replacing the cover picture, adding a venue requirement, a required field that cannot be emptied, equipment marked unavailable for new dates, a stale save and an approval landing mid-edit, correcting an approved event, an event awaiting its safety check still offered for correction, equipment read-only once approved and left out of the save, details greyed out once confirmed with notes still saving, and who is offered the edit |
| `e2e/change-requests.spec.ts` | 19.1 AC1, AC2, AC4, AC5, AC9 | an organiser asking for a change to a planning event, the coordinator seeing it pending, updating the point of contact directly, and withdrawing a request |
| `e2e/change-request-decisions.spec.ts` | 19.2 AC1, AC2, AC3, AC4, AC5, AC8 | the coordinator's queue of pending change requests and its tabs of decided ones, approving an attendance change, rejecting one with a reason the organiser reads, a blank reason not being sent, approving a date change after being told what it may release and seeing the event take the new date, and approving a change on an event awaiting its safety check after being warned it goes back to Planning |
| `e2e/venue-catalogue.spec.ts` | 8.1 AC1–AC6, AC8, AC9, AC11 | browsing and filtering the venue catalogue |
| `e2e/venue-detail.spec.ts` | 8.2 AC1–AC3 | a venue's record |
| `e2e/venues.spec.ts` | 8.1 AC12; 8.3 AC1–AC8, AC10 | creating, editing and deleting venues, and their pictures |
| `e2e/venue-requirement-search.spec.ts` | 8.4 AC1–AC11; 11.1 AC1; 12.5 AC1 | finding a venue for each of an event's venue requirements: the requirements in the catalogue's banner, the filters each one sets, the selection kept in the address, who is offered a request, and each venue judged against the selected requirement |
| `e2e/venue-calendar.spec.ts` | 9.1 AC1–AC3, AC5, AC7–AC10, AC12, AC13 | a venue's availability calendar |
| `e2e/venue-suitability.spec.ts` | 11.1 AC1–AC3, AC5–AC7 | whether each catalogue venue suits the event, and why not; requesting one that does not, with a justification |
| `e2e/booking-requests.spec.ts` | 12.1 AC1–AC5, AC14, AC15, AC17; 12.2 AC1, AC2, AC4; 12.5 AC6 | requesting a venue for an event, with its setup and teardown (refused before sending when negative, fractional or over 14 days, and said on the step and to Venue Staff on the request's card and page when they run outside the venue's opening hours), and withdrawing the request |
| `e2e/venue-requirement-booking.spec.ts` | 12.5 AC1–AC5, AC7–AC9, AC11 | requesting a venue for each of an event's venue requirements: each one's status in the catalogue's banner, the catalogue moving on to the next after a request, the event's page once every one has a request, an additional venue, no second request for a requirement that has one, and withdrawing or switching a requirement's request from the catalogue |
| `e2e/venue-hold-expiry.spec.ts` | 12.7 AC1, AC3, AC5–AC8, AC11 | Venue Staff setting a hold's expiry as they approve a request, and the hold shown on the request's page, its calendar day, the Approved tab's card and the event's page; changing it, with a reason shown beside it; an expired booking kept on the event's page and under its own Expired tab, its requirement needing a venue again and its venue requested again; no expiry, a past one, one after the booked period starts, or a blank reason, refused before it is sent |
| `e2e/venue-unavailability.spec.ts` | 9.4 AC1–AC3, AC5–AC7, AC9 | Venue Staff blocking off time at a venue from the "Block off time" card on its page: a closure added with its reason and description and shown as Unavailable on the calendar, the month grid naming it by its reason (its description for Other), a block off with no description refused in the backend's words, an end not after the start refused in the form before anything is sent, the bookings it would affect listed before Save and Save held back until they are (or blocked when they cannot be had), a flagged booking read on its event's page, on its request's page whatever its status, and held back from approval there and on the queue card, a closure edited then ended from its day with no actions left once ended, editing one removed meanwhile saying so, a refused End now saying why, an edit the server refuses saying why in its form, a failed list checked again, an edit that reaches a booking asking first, a start with seconds edited by the changed field alone, and the controls shown to Venue Staff only |
| `e2e/bookings.spec.ts` | 13.1 AC1–AC3; 13.1.2 AC1, AC3, AC4; 13.1.3 AC1–AC4; 13.2 AC1; 13.2.1 AC2–AC4; 13.2.2 AC1 | Venue Staff's queue, Pending / All / Approved / Rejected tabs, cancellation timing, pagination, the requested venue's calendar on the request detail page, approving (with the hold's expiry, story 12.7) and rejecting, and when a decision was made |
| `e2e/equipment-requests.spec.ts` | 15.1 AC1–AC4, AC6, AC9 | recording an event's equipment and submitting it to Technical Support |
| `e2e/equipment-queue.spec.ts` | 15.2 AC1–AC3, AC5, AC6 | Technical Support's equipment request queue, its figures, its All / Pending / Accepted / Declined tabs, and View details to the event and back |
| `e2e/equipment-decisions.spec.ts` | 16.1 AC1, AC2, AC4, AC6, AC9 | Technical Support accepting and declining equipment requests from the queue and from each request's own page, a blank decline reason blocked in the browser, a short request's Accept suggesting a decline, a double-click deciding once, a decision refused because another page decided first leaving the page showing the current status, a two-day event's period named in full on the card, the Accept dialog and the request's page, and the coordinator seeing each outcome and when it was decided on the event page |
| `e2e/equipment-display.spec.ts` | 17.1 AC1–AC6; responsive | the Equipment requirements section as each viewer reads it: each item's quantity, period and status, Accepted (reserved), Declined with its reason and Released, and which decision was made, by whom; a released item that was held saying it holds nothing, and a declined one keeping its reason; read-only for the organiser and Technical Support; reloading after a decision; each item's notes and period on one line on a phone |
| `e2e/safety-checks.spec.ts` | 21.1 AC2–AC6 | the Safety Officer's queue of events awaiting the safety check, oldest first, its Pending / Accepted / Declined / All tabs, and each event's safety details: its venues with any over capacity flagged, accessibility needs, accepted equipment, what changed since the last review and the previous reviews, with details never recorded shown as such |
| `e2e/safety-decision.spec.ts` | 21.2 AC1, AC2, AC4, AC7, AC10, AC12, AC18 | the coordinator requesting a safety review of a secured event, the Safety Officer reviewing against the seven review factors and requesting changes with findings the coordinator and the organiser then read, the flagged section highlighted on the event page, the organiser offered neither request nor confirm, the form refusing a finding that says nothing without sending it, the warning when a flagged venue is resubmitted unchanged, and approving then confirming an event |
| `e2e/attendee-registration.spec.ts` | 18.1 AC1, AC3–AC6, AC8 | an attendee's Upcoming events: each open event's date, time, venues and places left; each event's cover picture, an uploaded one asked of the API, and the placeholder when there is none or it can't be loaded; registering, with a confirmation and its time kept after a reload; full, closed and not-yet-open events listed with Register disabled; an event that stopped taking registrations saying so; no events, a failed load, Load more, an event repeated on the next page shown once, and a failed next page, no longer reported once the list is loaded again; the list at phone width; other roles refused the page; no Register while a registration is being sent; a double-click sending one registration; the last place taken by another attendee first |
| `e2e/my-registrations.spec.ts` | 18.2 AC1, AC3–AC8 | an attendee's My registrations: each registration with its event's date and time and its status, and when they registered or withdrew; withdrawing after confirming, with the place back on Upcoming events; cancelling the confirmation; the list loading, no registrations, a failed load, and the list on an iPhone 12 Pro, with a card's picture beside its details and an uploaded picture from the API; each event's cover picture; no Withdraw once the event has started, with the card saying why, and a withdrawal refused as it starts saying why, leaving only Close, which keeps the focus; a withdrawal that cannot reach the server, tried again until it goes through, with no failure left on the page and a slower earlier reload changing nothing; registering again after withdrawing; an organiser refused the page; a registration gone mid-visit saying so, and the next Withdraw starting afresh; a double-click withdrawing once; a cancelled event's registration shown as Event cancelled, in a cancelled event's colour |
| `e2e/registration-list.spec.ts` | 18.3 AC1, AC3, AC4, AC7 | the organiser reading the count against capacity and Full on the event page, then following View registrations to the registrations report for each attendee's name, email, registration time and status; no count or View registrations on an event not taking registrations; the assigned coordinator reading the count on the event page, following View registrations to read that no one has registered yet, and reaching the report from the navigation and picking the event there; a withdrawn row marked Withdrawn with when; Load more adding the next page and its counts (stubbed); a page that arrives after another event is picked staying out of its list (stubbed) |

Every case, by story and AC, without starting anything:

```bash
npx playwright test --list
```

`e2e/support.ts` has the seed accounts and events and the helpers more than one spec needs. Specs
share one throwaway database and run in parallel, so use unique names for anything you create.
