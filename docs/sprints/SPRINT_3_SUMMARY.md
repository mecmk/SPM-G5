# Sprint 3 - summary

> **Historical record.** This describes Sprint 3 as it stood when it closed and is not kept up to
> date. For how things work today, see [AGENTS.md](../../AGENTS.md),
> [ARCHITECTURE.md](../ARCHITECTURE.md) and [C4_MODEL.md](../C4_MODEL.md).

Written on 2026-11-05 from the product backlog (the Sprint 3 tab, the Change Log and the Backlog
Dashboard) and the history of `main`.

## Goal

> Finish Release 1's core workflow: the Event Coordinator Lead assigns and oversees events,
> coordinators book a venue for each requirement with holds that expire and replacements when a
> venue goes out of use, the Safety Officer clears an event before it is Confirmed, attendees
> register for confirmed events, change requests are assessed and decided, a cancelled event
> releases what it held, and everyone sees their notifications in the app.

## Team and dates

| Role | Who |
| --- | --- |
| Product Owner | Warren |
| Scrum Master | Yu Bing |
| Developers | Amanda, Cassia, Joshua, Matthew, Warren, Yu Bing |

Planned on 7 Oct (CL-108), with the roles agreed on 9 Oct (CL-113). Its pull requests merged into
`main` between 12 Oct and 21 Oct; the last was 20.2's, #128. The sprint was closed in the backlog
on 1 Nov (CL-200).

## Points

| Committed | Done | Stories done |
| --- | --- | --- |
| 51 | 45 | 16 of 18 |

8.4, carried from Sprint 2, was built here but not counted (CL-108).

| Developer | Done of assigned |
| --- | --- |
| Amanda | 8 of 8 |
| Cassia | 8 of 8 |
| Joshua | 9 of 9 |
| Matthew | 2 of 8 |
| Warren | 9 of 9 |
| Yu Bing | 9 of 9 |

Matthew's 18.1 and 18.2 merged in this sprint but were reopened: an attendee could not open an
event's full details before registering or withdrawing (f18.1.2, f18.2.1). Both were carried to
Sprint 4 (CL-200).

## Stories delivered

| Story | Title | Owner | Pull request |
| --- | --- | --- | --- |
| 5.4 | view unassigned event queue and assign a coordinator | Amanda | #107 |
| 5.5 | oversee coordinator assignments and active events | Amanda | #113 |
| 5.6 | reassign events between coordinators as the Lead | Amanda | #124 |
| 6.2 | cancel event and release held resources | Yu Bing | #122 |
| 8.4 | find a venue for each of an event's venue requirements (carried from Sprint 2) | Joshua | #98 |
| 9.4 | mark venue temporarily unavailable and flag affected bookings | Warren | #111 |
| 12.5 | request a venue for each venue requirement and see when all are covered | Joshua | #101 |
| 12.6 | request a replacement venue for an affected booking | Warren | #123 |
| 12.7 | expire tentative venue holds | Joshua | #103 |
| 17.1 | display equipment reserved for my event | Matthew | #120 |
| 18.3 | display registration list for my event | Cassia | #119 |
| 19.2 | review and decide change request | Yu Bing | #116 |
| 19.3 | assess change request impact | Yu Bing | #127 |
| 20.2 | view and act on notifications | Warren | #128 |
| 21.1 | view events awaiting operational safety check | Cassia | #104 |
| 21.2 | record operational safety check decision | Cassia | #115 |

Merged but reopened, and carried to Sprint 4:

| Story | Title | Owner | Pull request |
| --- | --- | --- | --- |
| 18.1 | browse and register for an event | Matthew | #110 |
| 18.2 | view and withdraw my registrations | Matthew | #118 |

## Fixes and chores

| ID | What | Owner | Pull request |
| --- | --- | --- | --- |
| f2.1.5 | refuse a number above 100,000 with a message that fits | Joshua | #117 |
| f2.7.4 | every event request needs at least one venue requirement (CL-117) | Joshua | #108 |
| f7.2.4 | the coordinator edits event details until the event is Confirmed (CL-123) | Yu Bing | #106 |
| f9.4.1 | Venue Staff manage closures from the Edit venue page | Warren | #126 |
| f11.1.1 | judge each venue against the selected venue requirement | Joshua | #102 |
| f12.1.2 | check opening hours against the event's own times, not setup and teardown (CL-125) | Joshua | #109 |
| f18.1.1 | show each upcoming event's cover picture | Matthew | #121 |
| f19.1.1 | allow change requests on Confirmed events (CL-122) | Amanda | #125 |

## Not done

- 18.1 and 18.2: reopened and carried to Sprint 4 (CL-200).
- c7, CI change detection that skips a suite when a pull request only adds files: not started.

## Decisions worth knowing

- The Week 7 customer changes were built here: venue closures (9.4) and replacement venues
  (12.6), hold expiry (12.7), the Event Coordinator Lead's queue, overview and reassignment (5.4
  to 5.6), and the Safety Officer's queue and decision (21.1, 21.2).
- 12.7 was reworked to the customer's hold before it merged: Venue Staff set each expiry when they
  approve, and confirming the event completes the hold (CL-124, Q53).
- 5.4 switched off 5.1's automatic assignment: only the Lead assigns an unassigned event (CL-128).
- 21.2 was rewritten for the build: the coordinator requests the safety review and confirms the
  event, and Approve and Request changes are the only outcomes (CL-140). The automatic moves its
  earlier wording described were not built, so an ended event stayed Confirmed (Q57) until
  f21.2.2 in Sprint 4.
- Change requests close 24 hours before an event's set-up time (CL-150).

## Evidence

Every automated test is tagged with the story and acceptance criterion it proves. To see the
traceability matrix as it stood, check out `1d642d0`, the last merge of the sprint, and run
`npm run test:trace` (see [testing/README.md](../testing/README.md)).
