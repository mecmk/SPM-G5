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
 * What is proven here is the flow a coordinator clicks through. The rules themselves - every
 * refused event status, the 403 for a coordinator who is not the assigned one, the 404s, the
 * fields copied onto the row - are `backend/tests/bookings/test_raise_booking_request.py` and
 * `test_bookable_events.py`, which are faster and deterministic, and are not repeated here.
 * f12.1.1 changed no backend rule, so it has no backend test of its own.
 *
 * AC15's address is the contract with story 8.1's filter panel, which reads what Find a venue
 * writes (`VENUE_SEARCH_PARAMS` in frontend/src/routes.ts). These cases pin its names and values;
 * that the panel fills itself in from them is 8.1 AC3's to prove. The flows here open Grand Hall
 * (400 seats), the room that fits Nimbus's 350, but send nothing for Nimbus: Grand Hall is already
 * booked for Nimbus that day, and story 13.1's queue tests find the seeded Nimbus request by its
 * event name. The one request really sent is Regional Sales Summit's, to Grand Hall, which is free
 * on 15-16 Dec. The pending queue itself is story 13.1's (`bookings.spec.ts`), so AC3 stops at
 * the pending outcome shown here.
 *
 * Seed data this leans on (backend/db/seed/020_sample_data.sql): Chloe Coordinator is assigned
 * Nimbus Developer Conference (Planning: Theatre, three facilities, two accessibility needs, 350
 * people, 25 Nov 2026 09:00-18:00), Regional Sales Summit (Planning: Theatre only, 220 people,
 * 15-16 Dec 2026) and Data Literacy Workshop (Under Review, so it cannot take a booking yet).
 * Carl is the other coordinator, and Omar organises Nimbus. No seeded event records "No venue
 * requirements", so that case sets the flag on Nimbus's real response with `page.route`.
 */

import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const NIMBUS = { id: EVENTS.approved, name: 'Nimbus Developer Conference' }
const SUMMIT = { id: EVENTS.planning, name: 'Regional Sales Summit' }
const WORKSHOP = { id: EVENTS.submitted, name: 'Data Literacy Workshop' }
const VENUE = 'Grand Hall'
const VENUE_ID = '22222222-0000-0000-0000-000000000001' // Grand Hall in the seed
const FIND_A_VENUE = 'Find a venue'
const REQUEST_THIS_VENUE = 'Request this venue'
const WITHDRAWN_VENUE_MESSAGE =
  'This venue has been withdrawn from the catalogue and can no longer be booked.'
const NOT_REQUESTABLE_MESSAGE =
  "Only the event's assigned coordinator can request a venue for it, while the event is in " +
  'Planning or Confirmed.'

/** The address Find a venue writes for Nimbus, as 8.1's panel reads it (AC15). */
const NIMBUS_SEARCH = {
  event: NIMBUS.id,
  capacity: '350',
  from: '2026-11-25T09:00',
  to: '2026-11-25T18:00',
  layout: 'THEATRE',
  facility: ['PROJECTOR', 'SOUND_SYSTEM', 'STAGE'],
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
  const href = await page.getByRole('link', { name: FIND_A_VENUE }).getAttribute('href')
  expect(href).not.toBeNull()
  return searchOf(new URL(href ?? '', 'http://address.invalid'))
}

function searchOf(address: URL) {
  const params = address.searchParams
  return {
    path: address.pathname,
    names: [...new Set(params.keys())].sort(),
    event: params.get('event'),
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

/** From the catalogue for Nimbus to the request step for one venue. */
async function openRequestStep(page: Page) {
  await findVenueFor(page, NIMBUS)
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
}

test('12.1 AC15: a coordinator finds a venue from the event and opens its request', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')
  await page.getByRole('link', { name: NIMBUS.name, exact: true }).click()
  await expect(page.getByRole('heading', { name: NIMBUS.name, level: 1 })).toBeVisible()

  await page.getByRole('link', { name: FIND_A_VENUE }).click()

  // The address is exactly the contract: every recorded requirement, and nothing else.
  await expect(page).toHaveURL(/\/venues\?/)
  expect(searchOf(new URL(page.url()))).toEqual({
    path: '/venues',
    names: ['accessibility', 'capacity', 'event', 'facility', 'from', 'layout', 'to'],
    ...NIMBUS_SEARCH,
  })

  const banner = catalogueBanner(page, NIMBUS.name)
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('350')
  await expect(banner.getByRole('link', { name: 'Back to the event' })).toHaveAttribute(
    'href',
    `/events/${NIMBUS.id}`,
  )

  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${NIMBUS.id}/request-venue/[^/]+$`))
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
  await expect(page.getByText(`For ${NIMBUS.name}`)).toBeVisible()
})

test('12.1 AC2: the request step shows what it carries over from the event', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page)

  // The step states what it will carry over from the event, so the coordinator can see the
  // period, attendance, layout and facilities are the event's and not theirs to choose.
  const summary = page.getByRole('region', { name: 'What this request will carry' })
  await expect(summary).toContainText('350')
  await expect(summary).toContainText('Theatre')
  await expect(summary).toContainText('Projector & screen')
})

test('12.1 AC1/AC3: a coordinator raises a venue booking request for their approved event', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)

  // The one request really sent is Summit's, to Grand Hall, which is free on 15-16 Dec. Not
  // Nimbus's: story 13.1's queue tests find the seeded Nimbus request by its event name, and a
  // second Nimbus request in the queue would sit right beside it.
  await venueCard(page, VENUE).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${VENUE}`, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()

  // AC3: the outcome names the venue and shows the request waiting for Venue Staff.
  const outcome = page.getByRole('region', { name: 'Request sent' })
  await expect(outcome).toBeVisible()
  await expect(outcome).toContainText(VENUE)
  await expect(outcome).toContainText('Pending')

  // AC15: the outcome leads back to the event the request was raised for.
  await outcome.getByRole('link', { name: 'Back to the event' }).click()
  await expect(page.getByRole('heading', { name: SUMMIT.name, level: 1 })).toBeVisible()
})

test('12.1 AC15: a venue can be requested from its record in event context', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, NIMBUS)

  await venueCard(page, VENUE).getByRole('link', { name: VENUE }).click()
  await expect(page.getByRole('heading', { name: VENUE, level: 1 })).toBeVisible()

  // Back to the list and in again: the event is still in context. The page's own back link, not
  // the sidebar's "Venue catalogue", which opens the catalogue afresh.
  await page.getByRole('link', { name: '← Venue catalogue' }).click()
  await expect(catalogueBanner(page, NIMBUS.name)).toBeVisible()
  await venueCard(page, VENUE).getByRole('link', { name: VENUE }).click()
  await expect(page.getByRole('heading', { name: VENUE, level: 1 })).toBeVisible()

  await page.getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${NIMBUS.id}/request-venue/[^/]+$`))
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
    names: ['capacity', 'event', 'from', 'layout', 'to'],
    event: SUMMIT.id,
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
        required_layout_code: null,
        required_layout_name: null,
        required_facilities: [],
        venue_requirement_notes: null,
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
  await findVenueFor(page, NIMBUS)

  // Hold the request step's own event lookup in flight so the state before it answers can be
  // asserted at all - the same trick auth.spec.ts uses for b1.1.1. Review of PR #42: the button
  // used to be clickable here, and clicking it did nothing, because the request is built from
  // these details.
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

test('12.1 AC15: a refused request shows why and is not marked sent', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page)

  // As if the venue were withdrawn after the catalogue loaded: the backend refuses with 409.
  await page.route('**/bookings', async (route) => {
    const request = route.request()
    if (request.resourceType() !== 'fetch' || request.method() !== 'POST') return route.fallback()
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ detail: WITHDRAWN_VENUE_MESSAGE }),
      headers: {
        'access-control-allow-origin': request.headers()['origin'] ?? '*',
        'access-control-allow-credentials': 'true',
      },
    })
  })
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(page.getByRole('alert')).toHaveText(WITHDRAWN_VENUE_MESSAGE)
  await expect(page.getByRole('region', { name: 'Request sent' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()
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

    // Wait for the event itself, so the banner's absence is not read before it could appear.
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith(`/events/${NIMBUS.id}`)),
      page.goto(`/venues?${search}`),
    ])
    await expect(venueCard(page, VENUE)).toBeVisible()

    await expect(catalogueBanner(page, NIMBUS.name)).toHaveCount(0)
    await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
  })
}

/** Who can open the request step's address (an old link, an edited one) but must not be offered
 * a request there, and for which event (AC15 permission, review of PR #67). */
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
