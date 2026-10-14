/**
 * Story 12.1 - fe/be: raise venue booking request, and f12.1.1 (12.1 AC15) - the request starts
 * from the event.
 *
 * AC1 A request can be raised only from an approved event and against one venue.
 * AC2 The request carries the event's date, start and end times, expected attendance, required
 *     layout, and required facilities.
 * AC3 On submission the request appears in the Venue Staff pending queue with a pending status.
 * AC4 Only the assigned coordinator for that event can raise the request.
 * AC15 (f12.1.1) The assigned coordinator of an event that can take a booking opens the venue
 *     catalogue from the event's Venue requirements with Find a venue. The catalogue's address
 *     carries the event's dates and times, expected attendance as minimum capacity, layout,
 *     facilities and accessibility needs, and the page names the event. Each venue then offers
 *     Request this venue, which raises the booking request for that event and venue. There is no
 *     separate Request a venue page, and its old address opens the Events inbox.
 *
 * Story 12.2 - fe: track and withdraw a venue booking request, from the same event page.
 *
 * AC1 Selecting a request shows the full request and any decision reason - already true of the
 *     event page's existing Venue booking card, which this story adds a Withdraw action onto
 *     directly rather than a separate page to click into.
 * AC2/AC4 A pending request can be withdrawn after confirmation, and reads as its own, visually
 *     distinct outcome afterward - proven together in one flow below, since withdrawing is what
 *     produces a Withdrawn card to look at.
 * AC4 (other half) An event with no booking requests shows an empty state linking to the venue
 *     catalogue.
 * The permission, not-pending and conflict rules (AC3, AC5-AC8) are backend cases -
 * `backend/tests/bookings/test_withdraw_booking.py` - not repeated here.
 *
 * What is proven here is the flow a coordinator clicks through. The rules themselves - every
 * refused event status, the 403 for a coordinator who is not the assigned one, the 404s, the
 * fields copied onto the row - are `backend/tests/bookings/test_raise_booking_request.py` and
 * `test_bookable_events.py`, which are faster and deterministic, and are not repeated here.
 * f12.1.1 changed no backend rule, so it has no backend test of its own.
 *
 * AC15's address is the contract with story 8.1's filter panel, which reads what Find a venue
 * writes (`VENUE_SEARCH_PARAMS` in frontend/src/routes.ts). These cases pin its names and values;
 * that the panel fills itself in from them is 8.1 AC4's to prove (`venue-catalogue.spec.ts`).
 *
 * Since 8.1's search leaves out venues that are not free, Nimbus's catalogue lists nothing: Grand
 * Hall, the one room that fits its 350, is already booked for Nimbus that day. So Nimbus's cases
 * pin the address only, or open the request step by its address, and send nothing - story 13.1's
 * queue tests also find the seeded Nimbus request by its event name. The flows through the
 * catalogue use Regional Sales Summit, whose results show Grand Hall, and send nothing either, so
 * Grand Hall stays free for them. The one request really sent is Sales Onboarding Day's, to
 * Seminar Room 2.1: an event no other test uses, so its hold hides nothing another test looks
 * for. The pending queue itself is story 13.1's (`bookings.spec.ts`), so AC3 stops at the pending
 * booking the event's page shows.
 *
 * Story 12.5: a request is for one venue requirement, and both of Nimbus's have one in the seed
 * (its Main venue booked, its Breakout room requested), so its Find a venue reads "All required
 * venues booked" and opens the catalogue for an additional venue: the event's own dates,
 * attendance and accessibility needs. Sending a request
 * for an event whose only requirement then has one opens the event's page (12.5 AC6).
 *
 * AC14 (built with s8.1): a venue that stopped being available since the search is refused, and
 * the step leads back to the same results.
 *
 * f7.1.1: an event over two days keeps both dates, on the catalogue's banner (AC15) and in the
 * request step's Date and time (AC2).
 *
 * f12.1.2: the request step takes a setup and a teardown, under 12.1's ACs as the backlog numbers
 * them now - the AC1-AC4 above are Sprint 1's numbering, which the older cases keep. AC1: each is
 * entered in days, hours and minutes, 0 until changed, and the step shows the booked period they
 * make around the requirement's own times. AC5: a setup may reach into earlier days, and a
 * negative, fractional or over-long one is refused under the fields before anything is sent; the
 * server's own refusals, AC9's setup that would start in the past among them, are
 * `backend/tests/bookings/test_request_setup_and_teardown.py`'s. AC17: a setup or teardown that
 * would run outside the venue's opening hours is said on the step before anything is sent, with
 * the hours, and Venue Staff see it on the request's card in their queue and on its page, with the
 * booked period, so they decide when approving; a venue with no hours recorded says nothing. That
 * such a request is accepted at all, the event's own times being inside the hours, is AC16's,
 * proven with its refusals in `backend/tests/bookings/test_request_opening_hours.py`. These cases
 * use only Supplier Induction Morning (Planning, Chloe's: one Main venue, a Classroom with a
 * projector for 30 people, 3 Feb 2027 09:00-12:00) at Seminar Room 2.1 (open 08:00 to 20:00), and
 * once at Exhibition Foyer (no hours recorded), opening the step by its address. One case sends
 * its request, to Seminar Room 2.1; no other spec uses the event or that day, so nothing done for
 * it holds anything another test looks for, and Venue Staff's Pending tab, soonest first, lists it
 * on its first page. That request stays pending, so `bookings.spec.ts`'s Alumni Homecoming Weekend
 * card (1 Sep 2027) is at worst tenth on that page: one more request dated before it and left
 * pending by any spec would push that card to the second page. A request whose own times are
 * outside the hours is the server's to refuse (AC16), so the step says nothing about its setup
 * and teardown then.
 *
 * Seed data this leans on (backend/db/seed/020_sample_data.sql): Chloe Coordinator is assigned
 * Nimbus Developer Conference (Planning: Theatre, three facilities, two accessibility needs, 350
 * people, 25 Nov 2026 09:00-18:00), Regional Sales Summit (Planning: Theatre only, 220 people,
 * 15-16 Dec 2026), Sales Onboarding Day (Planning: Classroom, a projector, 40 people, 17 May
 * 2028 09:00-17:00) and Data Literacy Workshop (Under Review, so it cannot take a booking yet).
 * Carl is the other coordinator, and Omar organises Nimbus. No seeded event records "No venue
 * requirements", so that case sets the flag on Nimbus's real response with `page.route`.
 */

import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, corsHeaders, EVENTS, signIn, venueCard } from './support'

const NIMBUS = { id: EVENTS.approved, name: 'Nimbus Developer Conference' }
const SUMMIT = { id: EVENTS.planning, name: 'Regional Sales Summit' }
const WORKSHOP = { id: EVENTS.submitted, name: 'Data Literacy Workshop' }
// Story 12.5: a venue requirement takes one request at a time, so 12.1's real send has an event
// of its own (one requirement, no bookings) rather than sharing Briefing's with 11.1's spec.
const ONBOARDING = { id: EVENTS.onboardingDay, name: 'Sales Onboarding Day' }
// Confirmed, Chloe's, Banquet layout, 90 people, 10 Feb 2027 - no other spec sends a request
// for it or searches the catalogue on its date, so raising and withdrawing one here holds
// nothing another test looks for (unlike Summit's own slot, which 8.1's catalogue specs read).
const DINNER = { id: '33333333-0000-0000-0000-000000000013', name: 'Partner Appreciation Dinner' }
// f12.1.2: Planning, Chloe's, one Main venue and no bookings, 3 Feb 2027 09:00-12:00. Only the
// setup and teardown cases use it, at Seminar Room 2.1, which suits it.
const INDUCTION = { id: EVENTS.supplierInduction, name: 'Supplier Induction Morning' }
const VENUE = 'Grand Hall'
const VENUE_ID = '22222222-0000-0000-0000-000000000001' // Grand Hall in the seed
const ONBOARDING_VENUE = 'Seminar Room 2.1'
const SEMINAR_ROOM_ID = '22222222-0000-0000-0000-000000000002' // Seminar Room 2.1 in the seed
// f12.1.2: the seed records no opening hours for it (12.1 AC17).
const FOYER = { id: '22222222-0000-0000-0000-000000000004', name: 'Exhibition Foyer' }
const FIND_A_VENUE = 'Find a venue'
// Story 12.5 AC5: Find a venue's name once every requirement of the event has a request.
const FIND_A_VENUE_EITHER_WAY = /^(Find a venue|All required venues booked)$/
const REQUEST_THIS_VENUE = 'Request this venue'
// As the backend words a venue closed since the search (AC14).
const CLOSED_VENUE_MESSAGE =
  'Grand Hall is closed for maintenance from Tue 15 Dec 2026, 00:00 to Thu 17 Dec 2026, 00:00.'
const NOT_REQUESTABLE_MESSAGE =
  "Only the event's assigned coordinator can request a venue for it, while the event is in " +
  'Planning or Confirmed.'
// f12.1.2 (12.1 AC5): as the step words a setup or teardown it refuses before sending.
const TURNAROUND_INVALID_MESSAGE =
  'Setup and teardown must be whole numbers of days, hours and minutes, zero or more.'
const TURNAROUND_TOO_LONG_MESSAGE = 'Setup and teardown can each be at most 14 days.'
// f12.1.2 (12.1 AC17): as the step and Venue Staff are told what runs outside Seminar Room 2.1's
// opening hours - the step adding who decides, and Venue Staff the booked period.
const OUTSIDE_HOURS = /outside the venue's opening hours/
const SETUP_OUTSIDE = "Setup runs outside the venue's opening hours, 08:00–20:00."
const TEARDOWN_OUTSIDE = "Teardown runs outside the venue's opening hours, 08:00–20:00."
const BOTH_OUTSIDE = "Setup and teardown run outside the venue's opening hours, 08:00–20:00."
const STAFF_DECIDE = 'Venue Staff decide whether to allow it when they approve.'

/** Nimbus's Main venue in the seed, already booked (Grand Hall, approved). */
const NIMBUS_MAIN_VENUE = 'cccccccc-0000-0000-0000-000000000003'
/** Supplier Induction Morning's Main venue in the seed, with the event's own times (f12.1.2). */
const INDUCTION_MAIN_VENUE = 'cccccccc-0000-0000-0000-000000000039'
/** Partner Appreciation Dinner's Main venue in the seed, 18:30-22:00 (f12.1.2). */
const DINNER_MAIN_VENUE = 'cccccccc-0000-0000-0000-000000000013'

/** The address Nimbus's Find a venue writes, as 8.1's panel reads it (AC15). Story 12.5 AC5: both
 * its requirements have a request in the seed, so it selects none - an additional venue - and
 * carries the event's own dates, attendance and accessibility needs. */
const NIMBUS_SEARCH = {
  event: NIMBUS.id,
  requirement: null,
  capacity: '350',
  from: '2026-11-25T09:00',
  to: '2026-11-25T18:00',
  layout: null,
  facility: [],
  accessibility: ['HEARING_LOOP', 'WHEELCHAIR_ACCESS'],
}

/** The sidebar. Its links share their names with the home page's tiles, which are built from
 * the same list, so nav assertions scope to it - as `rbac.spec.ts` does. */
function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

function catalogueBanner(page: Page, eventName: string) {
  return page.getByRole('region', { name: `Finding a venue for ${eventName}` })
}

/** Open an event's page and wait for its Venue requirements card, so an absence is meaningful. */
async function openEvent(page: Page, event: { id: string; name: string }) {
  await page.goto(`/events/${event.id}`)
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Venue requirements' })).toBeVisible()
}

/**
 * The catalogue address Find a venue points at, read from the link rather than followed, for the
 * cases that only pin the contract. Repeated names are sorted, as their order is not part of it.
 */
async function findVenueSearch(page: Page) {
  const href = await page.getByRole('link', { name: FIND_A_VENUE_EITHER_WAY }).getAttribute('href')
  expect(href).not.toBeNull()
  return searchOf(new URL(href ?? '', 'http://address.invalid'))
}

function searchOf(address: URL) {
  const params = address.searchParams
  return {
    path: address.pathname,
    names: [...new Set(params.keys())].sort(),
    event: params.get('event'),
    requirement: params.get('requirement'),
    capacity: params.get('capacity'),
    from: params.get('from'),
    to: params.get('to'),
    layout: params.get('layout'),
    facility: params.getAll('facility').sort(),
    accessibility: params.getAll('accessibility').sort(),
  }
}

/** From the event's page to the catalogue for it, as its coordinator does (AC15). */
async function findVenueFor(page: Page, event: { id: string; name: string }) {
  await openEvent(page, event)
  await page.getByRole('link', { name: FIND_A_VENUE }).click()
  await expect(catalogueBanner(page, event.name)).toBeVisible()
}

/** From the catalogue for Regional Sales Summit to the request step for Grand Hall. */
async function openRequestStep(page: Page) {
  await findVenueFor(page, SUMMIT)
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
}

/** f12.1.2: the request step for Supplier Induction Morning's Main venue at `venue` (Seminar Room
 * 2.1 unless said), opened by its address, and its Setup and teardown section once loaded. */
async function openInductionStep(
  page: Page,
  venue = { id: SEMINAR_ROOM_ID, name: ONBOARDING_VENUE },
) {
  await page.goto(
    `/events/${INDUCTION.id}/request-venue/${venue.id}?requirement=${INDUCTION_MAIN_VENUE}`,
  )
  await expect(page.getByRole('heading', { name: `Request ${venue.name}`, level: 1 })).toBeVisible()
  const turnaround = page.getByRole('region', { name: 'Setup and teardown' })
  await expect(turnaround).toBeVisible()
  return turnaround
}

/** One field of the step's Setup or Teardown (12.1 AC1): its Days, Hours or Minutes. */
function turnaroundField(turnaround: Locator, part: string, unit: string): Locator {
  return turnaround.getByRole('group', { name: part, exact: true }).getByLabel(unit)
}

test('12.1 AC15: a coordinator finds a venue from the event and opens its request', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')
  await page.getByRole('link', { name: NIMBUS.name, exact: true }).click()
  await expect(page.getByRole('heading', { name: NIMBUS.name, level: 1 })).toBeVisible()

  // Story 12.5 AC5: both of Nimbus's requirements have a request, so the link says so and opens
  // the catalogue for an additional venue.
  await page.getByRole('link', { name: 'All required venues booked' }).click()

  // The address is exactly the contract: what the event recorded, and nothing else.
  await expect(page).toHaveURL(/\/venues\?/)
  expect(searchOf(new URL(page.url()))).toEqual({
    path: '/venues',
    names: ['accessibility', 'capacity', 'event', 'from', 'to'],
    ...NIMBUS_SEARCH,
  })

  const banner = catalogueBanner(page, NIMBUS.name)
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('350')
  await expect(banner.getByRole('link', { name: 'Back to the event' })).toHaveAttribute(
    'href',
    `/events/${NIMBUS.id}`,
  )

  // Nimbus's results are empty (Grand Hall is booked for it), so the venue is requested from
  // Summit's, which list Grand Hall.
  await findVenueFor(page, SUMMIT)
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${SUMMIT.id}/request-venue/[^/]+$`))
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
  await expect(page.getByText(`For ${SUMMIT.name}`)).toBeVisible()
})

test('12.1 AC2: the request step shows what it carries over from the event', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  // Nimbus records the most to carry over. Its catalogue lists nothing, so the step is opened by
  // its address; nothing is sent.
  // Story 12.5: the step's address names the requirement the request is for.
  await page.goto(`/events/${NIMBUS.id}/request-venue/${VENUE_ID}?requirement=${NIMBUS_MAIN_VENUE}`)
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()

  // The step states what it will carry over from the event, so the coordinator can see the
  // period, attendance, layout and facilities are the event's and not theirs to choose.
  const summary = page.getByRole('region', { name: 'What this request will carry' })
  await expect(summary).toContainText('350')
  await expect(summary).toContainText('Theatre')
  await expect(summary).toContainText('Projector & screen')
})

test('12.1 AC2/AC15: a two-day event keeps both dates from Find a venue to the request step', async ({
  page,
}) => {
  // Summit and its Main venue both run 15 Dec 09:00 to 16 Dec 17:00. Nothing is sent.
  const period = 'Tue, 15 Dec 2026, 09:00 – Wed, 16 Dec 2026, 17:00'
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)
  await expect(catalogueBanner(page, SUMMIT.name)).toContainText(period)

  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'What this request will carry' })).toContainText(
    period,
  )
})

test('12.1 AC1/AC3: a coordinator raises a venue booking request for their approved event', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, ONBOARDING)

  // The one request really sent is Sales Onboarding Day's, to Seminar Room 2.1, which fits
  // everything it records: an event no other spec uses, so the hold the request leaves on the
  // room hides nothing another test looks for.
  await venueCard(page, ONBOARDING_VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(
    page.getByRole('heading', { name: `Request ${ONBOARDING_VENUE}`, level: 1 }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()

  // AC3 and AC15: the event the request was raised for opens - story 12.5 AC6, since its one
  // requirement now has a request - and lists it as pending, waiting for Venue Staff.
  await expect(page.getByRole('heading', { name: ONBOARDING.name, level: 1 })).toBeVisible()
  const bookings = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookings).toContainText(ONBOARDING_VENUE)
  await expect(bookings).toContainText('Pending')
})

test('12.1 AC15: a venue can be requested from its record in event context', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)

  await venueCard(page, VENUE).getByRole('link', { name: VENUE }).click()
  await expect(page.getByRole('heading', { name: VENUE, level: 1 })).toBeVisible()

  // Back to the list and in again: the event is still in context. The page's own back link, not
  // the sidebar's "Venue catalogue", which opens the catalogue afresh.
  await page.getByRole('link', { name: '← Venue catalogue' }).click()
  await expect(catalogueBanner(page, SUMMIT.name)).toBeVisible()
  await venueCard(page, VENUE).getByRole('link', { name: VENUE }).click()
  await expect(page.getByRole('heading', { name: VENUE, level: 1 })).toBeVisible()

  await page.getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${SUMMIT.id}/request-venue/[^/]+$`))
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
})

test('12.1 AC15: only what the event recorded goes into the catalogue address', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, SUMMIT)

  // No facilities or accessibility needs recorded, and a two-day event keeps both dates.
  expect(await findVenueSearch(page)).toEqual({
    path: '/venues',
    names: ['capacity', 'event', 'from', 'layout', 'requirement', 'to'],
    event: SUMMIT.id,
    requirement: 'cccccccc-0000-0000-0000-000000000012', // Summit's Main venue in the seed
    capacity: '220',
    from: '2026-12-15T09:00',
    to: '2026-12-16T17:00',
    layout: 'THEATRE',
    facility: [],
    accessibility: [],
  })
})

test('12.1 AC15: an event with no venue requirements still finds a venue by date and capacity', async ({
  page,
}) => {
  // No seeded event records "No venue requirements" (story 2.1 AC4), so Nimbus's real record is
  // answered with it set: no layout, no facilities, no other requirements.
  await page.route(`**/events/${NIMBUS.id}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    return route.fulfill({
      response,
      json: {
        ...event,
        venue_none_required: true,
        // Story 2.7: "No venue requirements" lists none.
        venue_requirements: [],
      },
    })
  })
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, NIMBUS)

  // "No venue requirements" means none were stated, not that no venue is needed.
  expect(await findVenueSearch(page)).toEqual({
    path: '/venues',
    names: ['accessibility', 'capacity', 'event', 'from', 'to'],
    event: NIMBUS.id,
    requirement: null,
    capacity: '350',
    from: NIMBUS_SEARCH.from,
    to: NIMBUS_SEARCH.to,
    layout: null,
    facility: [],
    accessibility: NIMBUS_SEARCH.accessibility,
  })
})

test.describe('with the browser in New York', () => {
  test.use({ timezoneId: 'America/New_York' })

  test('12.1 AC15: the dates in the address are Singapore time wherever the browser is', async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.coordinator)
    await openEvent(page, NIMBUS)

    // 09:00 in Singapore is 20:00 the day before in New York; the address must not shift.
    const search = await findVenueSearch(page)
    expect(search.from).toBe(NIMBUS_SEARCH.from)
    expect(search.to).toBe(NIMBUS_SEARCH.to)
  })
})

test('12.1 AC15: the old request a venue address opens the events inbox', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/bookings/new')

  await expect(page).toHaveURL(/\/events\/inbox$/)
  await expect(page.getByRole('heading', { name: 'Events inbox', level: 1 })).toBeVisible()
})

test('12.1 AC2: the request cannot be sent before the event details arrive', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)

  // Hold the request step's own event lookup in flight so the state before it answers can be
  // asserted at all - the same trick auth.spec.ts uses for f1.1.1. The button must stay disabled
  // while the lookup is in flight, because the request is built from these details.
  await page.route('**/events/*', async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page.getByText('Loading the request')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send request' })).toHaveCount(0)

  // Once they arrive, the summary replaces the message and the request can be sent.
  await expect(page.getByRole('region', { name: 'What this request will carry' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()
})

test('12.1 AC14: a venue that stopped being available is refused, and the step leads back to the results', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page)
  const results = page.url().replace(/\/events\/.*\?/, '/venues?')

  // As if Grand Hall were closed for maintenance after the catalogue loaded: the backend re-checks
  // and refuses with 409. Stubbed, since the seed cannot close a venue between two page loads.
  await page.route('**/bookings', async (route) => {
    const request = route.request()
    if (request.resourceType() !== 'fetch' || request.method() !== 'POST') return route.fallback()
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: CLOSED_VENUE_MESSAGE }),
      headers: corsHeaders(request),
    })
  })
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(page.getByRole('alert')).toHaveText(CLOSED_VENUE_MESSAGE)
  await expect(page.getByRole('region', { name: 'Request sent' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()

  // Back to the same search, which runs again - the results refresh.
  await page.getByRole('link', { name: 'Back to the results' }).click()
  expect(page.url()).toBe(results)
  await expect(catalogueBanner(page, SUMMIT.name)).toBeVisible()
  await expect(venueCard(page, VENUE)).toBeVisible()
})

/** Who must not be offered Find a venue, and on which event (AC15 permission). */
const NOT_OFFERED = [
  {
    who: 'the coordinator of an event still under review',
    email: ACCOUNTS.coordinator,
    event: WORKSHOP,
  },
  { who: 'a coordinator not assigned to the event', email: ACCOUNTS.coordinator2, event: NIMBUS },
  { who: "the event's organiser", email: ACCOUNTS.organiser2, event: NIMBUS },
  { who: 'Venue Staff', email: ACCOUNTS.venueStaff, event: NIMBUS },
]

for (const viewer of NOT_OFFERED) {
  test(`12.1 AC15: Find a venue is not offered to ${viewer.who}`, async ({ page }) => {
    await signIn(page, viewer.email)
    await openEvent(page, viewer.event)

    await expect(page.getByRole('link', { name: FIND_A_VENUE })).toHaveCount(0)
  })
}

/** Users who can open the catalogue but must not request for Nimbus from its address. */
const NOT_REQUESTING = [
  { who: 'a coordinator not assigned to the event', email: ACCOUNTS.coordinator2 },
  { who: 'Venue Staff', email: ACCOUNTS.venueStaff },
]

for (const viewer of NOT_REQUESTING) {
  test(`12.1 AC15: the catalogue address for an event offers no request to ${viewer.who}`, async ({
    page,
  }) => {
    await signIn(page, viewer.email)
    const search = new URLSearchParams({ event: NIMBUS.id, capacity: NIMBUS_SEARCH.capacity })

    // Wait for the event itself, so the absence of a request is not read before it could appear.
    // Story 8.4 AC10: the banner itself shows for anyone who may read the event.
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith(`/events/${NIMBUS.id}`)),
      page.goto(`/venues?${search}`),
    ])
    await expect(venueCard(page, VENUE)).toBeVisible()
    await expect(catalogueBanner(page, NIMBUS.name)).toBeVisible()

    await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
  })
}

/** Who can open the request step's address (an old link, an edited one) but must not be offered
 * a request there, and for which event (AC15 permission). */
const NOT_SENDING = [
  { who: 'a coordinator not assigned to the event', email: ACCOUNTS.coordinator2, event: NIMBUS },
  {
    who: 'the coordinator of an event still under review',
    email: ACCOUNTS.coordinator,
    event: WORKSHOP,
  },
]

for (const viewer of NOT_SENDING) {
  test(`12.1 AC15: the request step's address offers no request to ${viewer.who}`, async ({
    page,
  }) => {
    await signIn(page, viewer.email)
    await page.goto(`/events/${viewer.event.id}/request-venue/${VENUE_ID}`)

    // The page says why on arrival, rather than after Send request is refused.
    await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveText(NOT_REQUESTABLE_MESSAGE)
    await expect(page.getByRole('region', { name: 'What this request will carry' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Send request' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: `← ${viewer.event.name}` })).toHaveAttribute(
      'href',
      `/events/${viewer.event.id}`,
    )
  })
}

test('12.1 AC4: Venue Staff are not offered a way to raise a request', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/')

  await expect(
    mainNav(page).getByRole('link', { name: 'Request a venue', exact: true }),
  ).toHaveCount(0)
})

test('12.1 AC1/AC5: setup and teardown start at 0, and the booked period follows them', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const turnaround = await openInductionStep(page)

  // AC1: nothing is added until the coordinator enters it, so the booked period is the Main
  // venue's own times.
  for (const part of ['Setup', 'Teardown']) {
    for (const unit of ['Days', 'Hours', 'Minutes']) {
      await expect(turnaroundField(turnaround, part, unit)).toHaveValue('0')
    }
  }
  await expect(turnaround).toContainText('Booked period')
  await expect(turnaround).toContainText('Wed, 3 Feb 2027 · 09:00–12:00')

  // AC5: a setup may reach into earlier days, so two days of it start the booked period on the
  // Monday; a teardown moves its end. Nothing is sent.
  await turnaroundField(turnaround, 'Setup', 'Days').fill('2')
  await expect(turnaround).toContainText('Mon, 1 Feb 2027, 09:00 – Wed, 3 Feb 2027, 12:00')
  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('30')
  await expect(turnaround).toContainText('Mon, 1 Feb 2027, 09:00 – Wed, 3 Feb 2027, 12:30')
})

test('12.1 AC5: a negative, fractional or over-long setup or teardown is refused before it is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  let sends = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/bookings') sends += 1
  })
  const turnaround = await openInductionStep(page)
  const problem = turnaround.getByRole('alert')
  const sendRequest = page.getByRole('button', { name: 'Send request' })

  // Said under the fields as soon as it is typed, and still said after Send request, which sends
  // nothing while it shows.
  for (const hours of ['-1', '1.5']) {
    await turnaroundField(turnaround, 'Setup', 'Hours').fill(hours)
    await expect(problem).toHaveText(TURNAROUND_INVALID_MESSAGE)
    await sendRequest.click()
    await expect(problem).toHaveText(TURNAROUND_INVALID_MESSAGE)
  }

  // Each is at most 14 days, the longest an event may run.
  await turnaroundField(turnaround, 'Setup', 'Hours').fill('0')
  await turnaroundField(turnaround, 'Teardown', 'Days').fill('15')
  await expect(problem).toHaveText(TURNAROUND_TOO_LONG_MESSAGE)
  await sendRequest.click()
  await expect(problem).toHaveText(TURNAROUND_TOO_LONG_MESSAGE)

  // 14 days is the most, to the minute: a minute more is refused, 14 days itself is not. Every
  // Send request above was made with a problem showing, so nothing has been sent.
  await turnaroundField(turnaround, 'Teardown', 'Days').fill('14')
  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('1')
  await expect(problem).toHaveText(TURNAROUND_TOO_LONG_MESSAGE)
  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('0')
  await expect(problem).toHaveCount(0)
  expect(sends).toBe(0)
})

test('12.1 AC5: text that is not a whole number is refused, not read as 0', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  const turnaround = await openInductionStep(page)
  const hours = turnaroundField(turnaround, 'Setup', 'Hours')

  // Typed key by key, as a person types it, so the field holds exactly what was typed.
  await hours.fill('')
  await hours.pressSequentially('3-')
  await expect(turnaround.getByRole('alert')).toHaveText(TURNAROUND_INVALID_MESSAGE)
  await expect(turnaround).not.toContainText('Booked period')
})

test('12.1 AC17: the step says when setup or teardown would run outside the opening hours', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const turnaround = await openInductionStep(page)
  const notice = turnaround.getByText(OUTSIDE_HOURS)

  // Seminar Room 2.1 opens 08:00 to 20:00 and the Main venue runs 09:00-12:00 inside them, so
  // nothing is said. An hour of setup starts exactly at opening, which is still inside.
  await expect(notice).toHaveCount(0)
  await turnaroundField(turnaround, 'Setup', 'Hours').fill('1')
  await expect(turnaround).toContainText('Wed, 3 Feb 2027 · 08:00–12:00')
  await expect(notice).toHaveCount(0)

  // A minute more starts before the room opens, which the step says before anything is sent.
  await turnaroundField(turnaround, 'Setup', 'Minutes').fill('1')
  await expect(notice).toHaveText(`${SETUP_OUTSIDE} ${STAFF_DECIDE}`)

  // Eight hours of teardown end exactly at closing; a minute more runs past it.
  await turnaroundField(turnaround, 'Teardown', 'Hours').fill('8')
  await expect(notice).toHaveText(`${SETUP_OUTSIDE} ${STAFF_DECIDE}`)
  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('1')
  await expect(notice).toHaveText(`${BOTH_OUTSIDE} ${STAFF_DECIDE}`)

  // Without the setup, only the teardown runs outside.
  await turnaroundField(turnaround, 'Setup', 'Hours').fill('0')
  await turnaroundField(turnaround, 'Setup', 'Minutes').fill('0')
  await expect(notice).toHaveText(`${TEARDOWN_OUTSIDE} ${STAFF_DECIDE}`)

  // A day of setup starts at 09:00 like the event, but the day before, so it runs through the
  // night, when the room is closed.
  await turnaroundField(turnaround, 'Setup', 'Days').fill('1')
  await expect(notice).toHaveText(`${BOTH_OUTSIDE} ${STAFF_DECIDE}`)
})

test("12.1 AC17: the step says nothing about setup or teardown when the event's own times are outside the hours", async ({
  page,
}) => {
  // Partner Appreciation Dinner runs 18:30-22:00, past Seminar Room 2.1's 20:00 closing, so the
  // server refuses it there whatever its teardown (AC16): there is no request for Venue Staff to
  // decide on. Its step is only opened; nothing is sent.
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(
    `/events/${DINNER.id}/request-venue/${SEMINAR_ROOM_ID}?requirement=${DINNER_MAIN_VENUE}`,
  )
  await expect(
    page.getByRole('heading', { name: `Request ${ONBOARDING_VENUE}`, level: 1 }),
  ).toBeVisible()
  const turnaround = page.getByRole('region', { name: 'Setup and teardown' })

  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('15')
  await expect(turnaround).toContainText('Wed, 10 Feb 2027 · 18:30–22:15')
  await expect(turnaround.getByText(OUTSIDE_HOURS)).toHaveCount(0)
})

test('12.1 AC17: a venue with no opening hours recorded says nothing about setup and teardown', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const turnaround = await openInductionStep(page, FOYER)

  // A day of setup and a day of teardown run through two nights, but with no hours recorded
  // nothing can run outside them. The booked period still shows; nothing is sent.
  await turnaroundField(turnaround, 'Setup', 'Days').fill('1')
  await turnaroundField(turnaround, 'Teardown', 'Days').fill('1')
  await expect(turnaround).toContainText('Tue, 2 Feb 2027, 09:00 – Thu, 4 Feb 2027, 12:00')
  await expect(turnaround.getByText(OUTSIDE_HOURS)).toHaveCount(0)
})

test('12.1 AC17: Venue Staff see on the request that its setup runs outside the opening hours', async ({
  page,
}) => {
  const staffNotice = `${SETUP_OUTSIDE} Booked period: Wed, 3 Feb 2027 · 07:30–12:30.`
  await signIn(page, ACCOUNTS.coordinator)
  const turnaround = await openInductionStep(page)

  // An hour and a half of setup starts at 07:30, before Seminar Room 2.1 opens at 08:00; half an
  // hour of teardown ends at 12:30, well inside.
  await turnaroundField(turnaround, 'Setup', 'Hours').fill('1')
  await turnaroundField(turnaround, 'Setup', 'Minutes').fill('30')
  await turnaroundField(turnaround, 'Teardown', 'Minutes').fill('30')
  await expect(turnaround).toContainText('Wed, 3 Feb 2027 · 07:30–12:30')
  await expect(turnaround.getByText(OUTSIDE_HOURS)).toHaveText(`${SETUP_OUTSIDE} ${STAFF_DECIDE}`)

  // It is sent all the same, the Main venue's own 09:00-12:00 being inside the hours (AC16). Its
  // one requirement now has a request, so the event's page opens (12.5 AC6), with the setup and
  // teardown sent.
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('heading', { name: INDUCTION.name, level: 1 })).toBeVisible()
  const bookings = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookings).toContainText('Setup: 1 hr 30 min')
  await expect(bookings).toContainText('Teardown: 30 min')

  // Venue Staff see it, with the booked period, on the request's card in their queue - where it
  // can be approved straight away (13.2 AC1) - and on its page.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  const card = page.getByRole('listitem').filter({ hasText: INDUCTION.name })
  await expect(card).toContainText(staffNotice)
  await card.getByRole('link', { name: INDUCTION.name }).click()
  await expect(page.getByRole('heading', { name: INDUCTION.name, level: 1 })).toBeVisible()
  await expect(page.getByText(staffNotice)).toBeVisible()
})

test('12.2 AC1/AC2/AC4: a coordinator withdraws a pending request from the event page', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, DINNER)
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()

  // Story 12.5 AC6: the event has one venue requirement, so sending opens its page.
  await expect(page.getByRole('heading', { name: DINNER.name, level: 1 })).toBeVisible()

  // AC1: the request's venue and status already read directly off the event page's own Venue
  // booking card - no separate page to select into.
  await expect(page.getByText('Pending', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Withdraw' }).click()

  const dialog = page.getByRole('dialog', { name: 'Withdraw this booking request?' })
  await dialog.getByRole('button', { name: 'Withdraw' }).click()

  // AC4: withdrawn reads as its own, visually distinct outcome once it exists.
  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Withdrawn', { exact: true })).toBeVisible()
  await expect(page.getByText('This booking request was withdrawn.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Withdraw' })).toHaveCount(0)
})

test('12.2 AC4: an event with no booking requests shows an empty state linking to the catalogue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, WORKSHOP)

  await expect(page.getByText('No venue booking requests yet.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Browse the venue catalogue' })).toHaveAttribute(
    'href',
    '/venues',
  )
})
