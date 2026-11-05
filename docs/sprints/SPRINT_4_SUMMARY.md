# Sprint 4 - summary

> **Historical record.** This describes Sprint 4 as it stood on 5 Nov 2026 and is not kept up to
> date. For how things work today, see [AGENTS.md](../../AGENTS.md),
> [ARCHITECTURE.md](../ARCHITECTURE.md) and [C4_MODEL.md](../C4_MODEL.md).

Written on 2026-11-05 from the product backlog (the Sprint 4 tab, the Change Log and the Backlog
Dashboard) and the history of `main`.

## Goal

> Finish the end-to-end planning workflow for release: safety follow-up, attendee needs,
> equipment release and correct event statuses.

## Team and dates

| Role | Who |
| --- | --- |
| Product Owner | Joshua |
| Scrum Master | Matthew |
| Developers | Amanda, Cassia, Joshua, Matthew, Warren, Yu Bing |

Planned at the Sprint Planning Meeting on 23 Oct (CL-161 to CL-163). Its pull requests merged into
`main` from 27 Oct, the first being 18.4's, #129.

## Points

| Committed | Done | Stories done |
| --- | --- | --- |
| 42 | 42 | 14 of 14 |

| Developer | Done of assigned |
| --- | --- |
| Amanda | 5 of 5 |
| Cassia | 6 of 6 |
| Joshua | 6 of 6 |
| Matthew | 12 of 12 |
| Warren | 8 of 8 |
| Yu Bing | 5 of 5 |

## Stories delivered

| Story | Title | Owner | Pull request |
| --- | --- | --- | --- |
| 7.4 | display event change history | Cassia | #131 |
| 8.6 | manage the room layouts venues can offer | Joshua | #134 |
| 9.5 | end the bookings a venue closure covers | Warren | #159 |
| 12.8 | cancel an approved venue booking | Yu Bing | #145 |
| 13.3 | search and sort the Venue Staff and Technical Support queues | Joshua | #133 |
| 16.2 | mark equipment out of service | Matthew | #141 |
| 17.2 | withdraw booked equipment | Yu Bing | #143 |
| 17.3 | view the equipment holds schedule as Technical Support | Matthew | #157 |
| 18.1 | browse and register for an event (carried from Sprint 3, as f18.1.2) | Matthew | #139 |
| 18.2 | view and withdraw my registrations (carried from Sprint 3, as f18.2.1) | Matthew | #140 |
| 18.4 | autofill attendee profile details | Amanda | #129 |
| 18.5 | register with guests | Amanda | #138 |
| 19.4 | view my change requests across all my events as an organiser | Cassia | #152 |
| 21.3 | release venue bookings named in a safety finding | Warren | #136 |

s15.2.1, an explanation of each tab in the equipment and booking queues, was delivered with them
by Yu Bing (#146).

## Fixes

| ID | What | Owner | Pull request |
| --- | --- | --- | --- |
| f2.1.6 | a picture removal is no longer lost while a save uploads | Joshua | #162 |
| f2.7.5 | ask how many only of countable facilities | Joshua | #185 |
| f4.5.1 | release equipment reservations when an event is rejected | Yu Bing | #132 |
| f7.1.2 | Event Organisers see their venue bookings | Yu Bing | #137 |
| f7.1.3 | organisers see bookings released by a safety finding or cancelled by a closure or the coordinator | Yu Bing | #164 |
| f7.2.5 | remove the Equipment section from the coordinator's Edit form (CL-221) | Warren | #184 |
| f8.3.4 | require a venue's opening hours, setup and teardown | Joshua | #188 |
| f8.3.5 | follow up the review of the venue's operating information | Joshua | #196 |
| f8.6.1 | open room layouts to organisers and take venue access from Technical Support | Cassia | #178 |
| f12.1.3 | pre-fill a booking request's setup and teardown from the venue's defaults | Joshua | #174 |
| f12.1.4 | check a multi-day booking against opening hours on its first start and last end | Joshua | #183 |
| f13.1.5 | name both dates of a multi-day booking in the Venue Staff views | Warren | #173 |
| f13.2.1.1 | show the venue's capacity on the event page's booking cards | Joshua | #186 |
| f15.1.1 | keep a declined item out of a correction | Joshua | #150 |
| f15.1.2 | request equipment only once the event is approved | Cassia | #176 |
| f16.1.1 | tell the coordinator when equipment is accepted or declined | Joshua | #158 |
| f16.2.1 | show scheduled out-of-service periods on the equipment catalogue | Yu Bing | #180 |
| f16.2.2 | mark a short equipment hold on the event and the holds schedule | Joshua | #187 |
| f16.2.3 | show a short item's advice only to whoever can act on it | Joshua | #189 |
| f16.2.4 | close an equipment item left with none of its units | Joshua | #190 |
| f16.2.5 | refresh the out-of-service figures as a scheduled record starts or ends | Yu Bing | #192 |
| f16.2.6 | keep a number box's value as typed when the page is scrolled over it | Yu Bing | #193 |
| f17.3.1 | say how long equipment stays held | Joshua | #182 |
| f17.3.2 | leave items not yet sent off the equipment holds schedule | Yu Bing | #191 |
| f19.1.2 | show the minimum allowed attendance in change requests | Yu Bing | #135 |
| f19.2.1 | an attendance increase no longer cancels venues that still fit | Yu Bing | #130 |
| f19.3.1 | flag oversized venues in a change request's impact | Yu Bing | #142 |
| f19.3.2 | keep the impact panel's unaffected rows inside their card | Yu Bing | #144 |
| f21.2.1 | flag only the bookings the safety review was about | Amanda | #181 |
| f21.2.2 | mark a Confirmed event Completed once it has ended (Q57) | Joshua | #195 |
| f21.3.1 | name both dates on a multi-day booking's card | Warren | #169 |

## Chores, tests and docs

| ID | What | Owner | Pull request |
| --- | --- | --- | --- |
| c3.1 | centre every page and line up the safety check cards | Yu Bing | #153 |
| c8 | review the seeded Confirmed events without venue bookings | Cassia | #149 |
| c9 | remove sidebar sections no story delivers | Joshua | #147, #155 |
| c10 | reset closed items when the seed re-runs | Joshua | #160 |
| c11 | venue catalogue cards: no link colour, open from anywhere on the card | Yu Bing | #154 |
| c13 | seed sample pictures for events | Matthew | #163 |
| c14 | seed sample change requests | Yu Bing | #156 |
| c15.1, c15.2 | refactor the UI components, sizing and positioning | Amanda | #165, #168 |
| c15.3 | scroll the picture previews into view in the 8.3 drag test | Amanda | #166 |
| c15.4 | drop the Open chip from the home page tiles | Joshua | #175 |
| c15.5 | show errors as toasts and block bad input | Joshua | #179 |
| c16 | take the developer tools off the sign-in page | Amanda | #167 |
| c17 | clean up comments | Joshua | #171 |
| c18 | signing out clears location state | Cassia | #170 |
| c19 | seed sample pictures for venues | Yu Bing | #172 |
| c20 | keep the clarification reply box under the conversation | Amanda | #177 |
| - | cover the cancellation's lock and both dates' refusals in 16.2's tests | Matthew | #148 |
| - | stop tests depending on today's date or a tied timestamp | Joshua | #161 |
| - | redraw the C4 diagrams as Mermaid flowcharts and add upload storage | Matthew | #194 |

## Not done

- c12, restyle the attendee's Upcoming Events like the venue catalogue: not started.

## Decisions worth knowing

- New stories agreed on 23 Oct: 21.3 releases only the bookings a safety finding names (CL-160,
  rewritten from the PO's answers in CL-175), and 18.4 keeps an attendee's phone number and
  dietary requirements on a profile (CL-161 to CL-163). Registering with guests was split out
  of 18.4 as 18.5 (CL-168, CL-173).
- 8.6's criteria were rewritten before the build (CL-178), and 16.2's firmed up before it and
  refined from its review (CL-188, CL-195).
- 12.8 began as a fix to 12.2 and became its own story (CL-192).
- 9.5 was added on 1 Nov: a venue closure ends the bookings it covers once Venue Staff confirm
  them (CL-193, CL-194, CL-209).
- 18.1 and 18.2 came over from Sprint 3 and finished as f18.1.2 and f18.2.1 (CL-200).
- Q57 was answered: an ended Confirmed event becomes Completed, on the API's own timer
  (f21.2.2, #195).

## Evidence

Every automated test is tagged with the story and acceptance criterion it proves. Run
`npm run test:trace` on `main` for the current traceability matrix (see
[testing/README.md](../testing/README.md)).
