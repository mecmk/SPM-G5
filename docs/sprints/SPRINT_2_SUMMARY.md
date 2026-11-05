# Sprint 2 - summary

> **Historical record.** This describes Sprint 2 as it stood when it closed on 7 Oct 2026 and is
> not kept up to date. For how things work today, see [AGENTS.md](../../AGENTS.md),
> [ARCHITECTURE.md](../ARCHITECTURE.md) and [C4_MODEL.md](../C4_MODEL.md).

Written on 2026-11-05 from the product backlog (the Sprint 2 tab, the Change Log and the Backlog
Dashboard) and the history of `main`.

## Goal

> Take a submitted event from review through venue and equipment planning. Coordinators clarify
> requests with organisers, find a suitable venue and hold it, and reserve equipment that
> Technical Support tracks, and the people involved are notified at each step.

## Team and dates

| Role | Who |
| --- | --- |
| Product Owner | Amanda |
| Scrum Master | Joshua |
| Developers | Amanda, Cassia, Joshua, Matthew, Warren, Yu Bing |

Planned on 26 Sep (CL-052, CL-053) and reviewed on 7 Oct (CL-107). Its pull requests merged into
`main` between 26 Sep and 8 Oct; the last was 11.1's, #97.

## Points

| Committed | Done | Stories done |
| --- | --- | --- |
| 77 | 74 | 19 of 20 |

8.4 (3 points) was set to Sprint 2 at the Sprint 1 review (CL-017) and never started, so it was
carried to Sprint 3 (CL-107). Every developer finished what they were assigned:

| Developer | Done of assigned |
| --- | --- |
| Amanda | 15 of 15 |
| Cassia | 9 of 9 |
| Joshua | 15 of 15 |
| Matthew | 15 of 15 |
| Warren | 10 of 10 |
| Yu Bing | 10 of 10 |

## Stories delivered

New in Sprint 2:

| Story | Title | Owner | Pull requests |
| --- | --- | --- | --- |
| 2.7 | record several venue requirements, each with its own times | Amanda | #84 |
| 4.2 | request clarification from organiser | Cassia | #82 |
| 4.3 | respond to a clarification request | Cassia | #88 |
| 5.2 | reassign event to another coordinator | Amanda | #80 |
| 11.1 | show venue suitability with reasons and allow override | Warren | #97 |
| 12.2 | track and withdraw my booking requests | Amanda | #79 |
| 15.1 | submit equipment requests for an event | Matthew | #89 |
| 15.2 | view equipment requests | Yu Bing | #92 |
| 16.1 | accept or decline equipment requests | Yu Bing | #96 |
| 19.1 | raise event change request | Amanda | #94 |
| 20.1 | generate and route notifications | Joshua | #93 |

Carried over from Sprint 1 and finished:

| Story | Title | Owner | Pull requests |
| --- | --- | --- | --- |
| 2.1 | capture event details, requirements and equipment on a request | Matthew | #60, #66, #76 |
| 2.6 | list my event requests | Matthew | #68 |
| 4.4 | approve event request | Cassia | #65 |
| 4.5 | reject event request with reason | Cassia | #65 |
| 7.2 | edit event details during review and internal notes | Yu Bing | #85 |
| 8.1 | browse, search and filter venue catalogue | Joshua | #73, #74 |
| 9.1 | display venue availability calendar with bookings and holds | Warren | #70, #75 |
| 12.1 | submit venue booking request with setup/teardown and soft lock | Joshua | #67, #69, #74 |

Parts of 13.1 and 13.2 delivered as their own pull requests, all by Yu Bing: s13.1.2, booking
status tabs and decision timing on the Venue Staff queue (#71); s13.1.3, the venue's schedule
beside the booking requests (#90); s13.2.1, rejecting a booking request (#64); s13.2.2, when Venue
Staff decided a booking, on the event page (#72).

## Fixes and chores

| ID | What | Owner | Pull request |
| --- | --- | --- | --- |
| f1.1.2 | a temporary lock after repeated failed sign-ins | Joshua | #63 |
| f1.2.3 | remove the All Events tab for Technical Support Staff | Yu Bing | #59 |
| f2.1.2 | remove recording equipment from the equipment types | Matthew | #76 |
| f2.6.1 | remove the organiser's New event request tab | Yu Bing | #61 |
| f2.7.1 to f2.7.3 | 2.7's manual-testing and review follow-ups | Amanda | in #84 |
| f5.2.1, f5.2.2 | 5.2's seed backfill and the router's 409 tests | Amanda | in #80 |
| f7.1.1 | a multi-day event names both of its dates | Joshua | #95 |
| f8.1.1 | Venue Staff manage venues from the catalogue page | Joshua | #73 |
| f8.3.2, f8.3.3 | venue pictures on create and edit, and their follow-ups | Joshua | #86, #91 |
| f9.1.1 | the calendar keeps its venue on previous and next | Warren | #70 |
| f12.1.1 | the venue request moves into the coordinator's event page | Joshua | #67 |
| f12.2.1 | bring `main` into 12.2's branch | Amanda | in #79 |
| f13.2.1 | two flaky 13.2 e2e tests wait for the detail page | Yu Bing | in #72 |
| d7.2.3 | regenerate the data dictionary for 7.2 | Yu Bing | #62 |
| d0.01 | the merge checklist, the reviewer sign-off and a docs refresh | Matthew | #81 |
| c6 | clean up comments and duplicated code | Cassia | #83 |

Sprint 1's review raised bug rows that merged on 25 Sep, before this sprint's planning, and are
recorded on the Sprint 1 tab: #55 (f7.2.2), #56 (f6.1.1), #57 (f5.1.1), #58 (f1.2.2) and #60
(f2.1.1). `sprint/1` merged into `main` on 24 Sep (#54), and the team has worked trunk-based on
`main` since.

## Not done

- 8.4, find a venue for each of an event's venue requirements: carried to Sprint 3 (CL-107).
- f2.1.3, name each equipment card's Remove button for screen readers: not started; stays on the
  product backlog.
- c4, a CI step that fails when the generated database docs are out of date: not started.

## Decisions worth knowing

- 20.1's notification writer covers every action built so far; a story built later adds its own
  notices (CL-071).
- Reassignment by the Event Coordinator Lead moved to a new story, 5.6 (CL-081).
- 15.1 was rewritten to ten acceptance criteria during the build (CL-102), and 16.1's decision
  notified nobody yet (Q24, fixed in Sprint 4 by f16.1.1).
- 11.1's AC8, judging every requirement at once, moved to 12.5 (CL-112).
- The Week 7 customer changes arrived during this sprint (CL-060 to CL-067): venue closures,
  replacement venues, hold expiry, the Event Coordinator Lead's queue and the Safety Officer's
  check. They were planned into Sprint 3.

## Evidence

Every automated test is tagged with the story and acceptance criterion it proves. To see the
traceability matrix as it stood, check out `17d17c4`, the last merge of the sprint, and run
`npm run test:trace` (see [testing/README.md](../testing/README.md)).
