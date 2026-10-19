/**
 * Story 12.6 - Request a replacement venue for an affected booking
 *
 * Happy path
 * 1. On an approved booking marked "Venue unavailable – alternative needed" (9.4), the assigned
 *     coordinator selects "Find a replacement venue" on the event page. The catalogue opens
 *     pre-filled from that booking's venue requirement (8.4), or, for an additional venue, from
 *     the event's own period and attendance, with the unavailable venue excluded. The banner
 *     names the booking being replaced, and stays while the coordinator changes or clears the
 *     filters.
 * 2. "Request this venue" raises a new booking request linked to the original booking as its
 *     replacement, carrying the original's setup and teardown (still editable on the request
 *     step). The event's details, status and other venue bookings are not changed.
 * 3. When Venue Staff approve the replacement (13.2), the original booking is released
 *     (Cancelled) in the same step. The event's booking list shows the original as "Replaced by
 *     <venue>", closed at the time of the release, and the replacement as "Replaces <venue>".
 *     Before approving, Venue Staff see "Replaces <venue>" and "Approving this releases
 *     <venue>". The coordinator's approval notice says the original was released and Venue Staff
 *     are told of the release; the organiser is not notified.
 *
 * Boundary
 * 4. Until a replacement is approved, the original booking stays approved and on record. The
 *     banner (12.5) shows its requirement as "Venue unavailable: <venue>", or "Replacement
 *     requested: <venue>" while one is pending. The event page does not show "All required
 *     venues booked" while a requirement's only booking is marked, and Find a venue skips marked
 *     requirements.
 *
 * Edge
 * 5. If the replacement is rejected or withdrawn, the original booking stays marked and another
 *     replacement can be requested.
 * 6. If the unavailability ends before a replacement is approved (9.4 AC6), the mark clears and
 *     "Find a replacement venue" disappears; the coordinator can withdraw the pending
 *     replacement and keep the original booking. If Venue Staff approve it anyway, it still
 *     replaces the original.
 * 7. A replacement caused by venue unavailability does not need an organiser change request
 *     (19.1), including when its suitability is overridden with a justification (11.1).
 * 8. No replacement can be requested on a cancelled event (6.2). A replacement that was never
 *     approved is never shown as having replaced the original.
 *
 * Permission
 * 9. Only the event's assigned coordinator can request a replacement venue. Only an approved
 *     marked booking can be replaced. A marked pending booking for a requirement offers "Find
 *     another venue", which leads to "Switch to this venue" (12.5); a marked pending additional
 *     venue is withdrawn and requested again.
 *
 * Conflict
 * 10. Only one pending replacement request is allowed per original booking: while one is
 *     pending, "Find a replacement venue" is not offered, a second request is refused naming the
 *     venue already requested, and the pending replacement cannot be switched (withdraw it
 *     first). A replacement at the original booking's own venue is refused. If two replacements
 *     are sent at once, only the first succeeds.
 *
 * Coordinator event list
 * 11. The assigned coordinator's Events inbox has a "Venue unavailable" tab listing only their
 *     events with a booking marked "Venue unavailable – alternative needed", with the number of
 *     such events on the tab (0 when none). An event with a pending replacement stays listed and
 *     shows "Replacement requested: <venue>". Opening an event shows the marked booking. An
 *     event leaves the tab once no booking on it is marked.
 *
 * Safety review and confirmation
 * 12. While any booking on an event is marked "Venue unavailable – alternative needed" (9.4), or
 *     has a pending replacement, the coordinator cannot send the event for safety review (21.2)
 *     or confirm it. The refusal names each such venue together with any other missing
 *     arrangement. Once the replacement is approved or withdrawn, or the unavailability ends
 *     with no replacement pending, the event can be sent and confirmed as usual.
 *
 * This file is what a person clicks, through the pages of AC1-AC12. The rules - the refusals, the
 * one pending replacement, the release, the race, the notices, the list's count and paging, the
 * safety review's and Confirm's refusals - are backend cases: backend/tests/bookings/
 * test_request_replacement.py, test_replacement_approval.py, test_replacement_schema.py,
 * test_replacement_for_venue_staff.py, test_replacement_with_change_request.py (19.2),
 * backend/tests/safety/test_blocked_while_venue_unavailable.py, backend/tests/events/
 * test_assigned_events_venue_unavailable.py and backend/tests/venues/
 * test_venue_search_exclude_venue.py.
 *
 * Seed (backend/db/seed/020_sample_data.sql, "Story 12.6"): events of February 2029, each with a
 * booking at Exhibition Foyer marked by the closure of its day, and Grand Hall free for every
 * one. Each flow that changes something has an event of its own (see the seed's note), so specs
 * running in parallel never share one; the ones that read are never changed. The pages that need
 * a state the seed cannot reach answer one call of their own (a marked pending replacement, a
 * failed read, Venue Staff's queue cut down to one event's requests, which under All is
 * otherwise anywhere in every spec's requests: the queue has no search or filter to find it by).
 */
import { expect, test, type Browser, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, corsHeaders, signIn, venueCard } from './support'

const FOYER = 'Exhibition Foyer'
const GRAND_HALL = 'Grand Hall'
const MAIN_HALL = 'Main hall'
const BREAKOUT_ROOM = 'Breakout room'
const HARBOUR = 'Harbour Pavilion'
const MAIN_HALL_OF_LANTERN = 'cccccccc-0000-0000-0126-000000006201'

const FIND_REPLACEMENT = 'Find a replacement venue'
// How the seed stamps the awards evening's original, as the event page writes it.
const ORIGINAL_APPROVED_AT = 'Sat, 10 Oct 2026, 09:00'
const FIND_ANOTHER = 'Find another venue'
const FIND_A_VENUE = 'Find a venue'
const ALL_BOOKED = 'All required venues booked'
const REQUEST_THIS_VENUE = 'Request this venue'
const SWITCH_TO = 'Switch to this venue'
const UNAVAILABLE_LABEL = 'Venue unavailable – alternative needed'

const DESKTOP = { width: 1280, height: 720 }
const PHONE = { width: 390, height: 844 }

const LANTERN = {
  id: EVENTS.lanternShowcase,
  name: 'Lantern Festival Showcase',
}
const MAKER_FAIRE = { id: EVENTS.makerFaire, name: 'Maker Faire Weekend' }
const SPRING_EXPO = { id: EVENTS.springExpo, name: 'Spring Expo Preview' }
const AWARDS = { id: EVENTS.awardsEvening, name: 'Regional Awards Evening' }
const PITCH_NIGHT = { id: EVENTS.pitchNight, name: 'Startup Pitch Night' }
const SUMMIT = { id: EVENTS.neighbourhoodSummit, name: 'Neighbourhood Summit' }
const HERITAGE = { id: EVENTS.heritageWalk, name: 'Heritage Walk Launch' }
const SHOWCASE = { id: EVENTS.productShowcase, name: 'Product Showcase Day' }
const ROBOTICS = { id: EVENTS.roboticsOpenHouse, name: 'Robotics Open House' }
const WELLNESS = { id: EVENTS.wellnessExpo, name: 'Wellness Expo Weekend' }
const CRAFT_MARKET = { id: EVENTS.craftMarket, name: 'Craft Market Weekend' }
const HARVEST_FAIR = { id: EVENTS.harvestFair, name: 'Harvest Fair Weekend' }
const OPEN_STUDIOS = { id: EVENTS.openStudios, name: 'Open Studios Day' }
const NIGHT_BAZAAR = { id: EVENTS.nightBazaar, name: 'Night Bazaar Weekend' }
const SPRING_FAIR = { id: EVENTS.springFair, name: 'Spring Fair Preview' }
const GARDEN_FAIR = { id: EVENTS.gardenFair, name: 'Garden Fair Day' }
const GRAND_HALL_ID = '22222222-0000-0000-0000-000000000001'
const GARDEN_FAIR_REQUIREMENT = 'cccccccc-0000-0000-0126-000000008501'
const GARDEN_FAIR_PENDING = '44444444-0000-0000-0000-000000012642'
const GARDEN_FAIR_WITHDRAWN = '44444444-0000-0000-0000-000000012643'

type SeededEvent = { id: string; name: string }

// The seeded booking's approval, a hold that lasts until the day before the event.
const HOLD_EXPIRES = (day: string) => `2029-02-${day}T09:00`

test.use({ timezoneId: 'Asia/Singapore' })

function bookingList(page: Page) {
  return page.getByRole('region', { name: 'Venue booking' })
}

function catalogueBanner(page: Page, event: SeededEvent) {
  return page.getByRole('region', {
    name: `Finding a venue for ${event.name}`,
  })
}

function filters(page: Page) {
  return page.getByRole('complementary', { name: 'Filters' })
}

async function openEvent(page: Page, event: SeededEvent) {
  await page.goto(`/events/${event.id}`)
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
  await expect(bookingList(page)).toBeVisible()
}

/** The catalogue as the assigned coordinator reaches it: Find a replacement venue on the page. */
async function findReplacementFor(page: Page, event: SeededEvent) {
  await openEvent(page, event)
  await page.getByRole('link', { name: FIND_REPLACEMENT }).click()
  await expect(catalogueBanner(page, event)).toBeVisible()
}

/** Request Grand Hall as the replacement and send it; the event's page opens. */
async function requestGrandHall(page: Page, event: SeededEvent) {
  await venueCard(page, GRAND_HALL).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${GRAND_HALL}`, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
}

/** A page signed in as `email` in a context of its own; close it with `page.context().close()`. */
async function signedInPage(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await signIn(page, email)
  return page
}

/**
 * Venue Staff's card for the replacement of `event`'s booking, by the event and the venue. The
 * queue pages by ten and the database is shared, so the card may be on a later page: press Next
 * until it shows.
 */
async function queueCard(page: Page, event: SeededEvent, tab?: string) {
  await page.goto('/venue-staff/booking-requests')
  if (tab !== undefined) {
    const chosen = page.getByRole('tab', { name: new RegExp(`^${tab}`) })
    await chosen.click()
    // Wait for that tab's own list: the card is looked for page by page below, and must not be
    // taken from the list of the tab the page opened on.
    await expect(chosen).toHaveAttribute('aria-selected', 'true')
    await page.waitForLoadState('networkidle')
  }
  const card = page
    .getByRole('listitem')
    .filter({ hasText: event.name })
    .filter({ hasText: GRAND_HALL })
  const pager = page.getByRole('navigation', { name: 'Pages' })
  await expect(page.getByRole('heading', { name: 'Booking Requests' })).toBeVisible()
  await expect(page.getByRole('listitem').first()).toBeVisible()
  for (let turned = 0; turned < 20; turned += 1) {
    if ((await card.count()) > 0) break
    const next = pager.getByRole('button', { name: 'Next' })
    if ((await pager.count()) === 0 || (await next.isDisabled())) break
    await next.click()
    await page.waitForLoadState('networkidle')
  }
  return card
}

/**
 * Show Venue Staff's queue as `event`'s own requests only. The queue is every request every spec
 * raised, in the order of their dates, and under All the card can be anywhere in it. It has no
 * search or filter to find the card by, and walking its pages for it did not hold up in a full
 * run (tests/STYLE.md allows a stub for a state the seed cannot reach, and a crowd it cannot
 * promise is one): the real answer is read in full, page by page, and cut down to the event's, so
 * the page under test is the page that really renders them.
 */
async function showOnlyRequestsOf(page: Page, event: SeededEvent) {
  const QUEUE_PAGE = 100
  await page.route(
    (url) => url.pathname === '/bookings',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const asked = new URL(request.url())
      const read = async (offset: number) => {
        asked.searchParams.set('offset', String(offset))
        asked.searchParams.set('limit', String(QUEUE_PAGE))
        const response = await route.fetch({ url: asked.toString() })
        return { response, body: await response.json() }
      }
      const first = await read(0)
      const entries = [...first.body.items]
      for (let offset = QUEUE_PAGE; offset < first.body.total; offset += QUEUE_PAGE) {
        entries.push(...(await read(offset)).body.items)
      }
      const own = entries.filter((entry) => entry.event_name === event.name)
      return route.fulfill({
        response: first.response,
        json: { ...first.body, items: own, total: own.length },
      })
    },
  )
}

/** Assert nothing runs off the side of the page, and `target` sits inside it. */
async function expectFitsPage(page: Page, target: Locator) {
  await expect(target).toBeVisible()
  const box = await target.boundingBox()
  const viewport = page.viewportSize()
  if (box === null || viewport === null) throw new Error('nothing to measure')
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

// --- AC1 ----------------------------------------------------------------------------------------
test("12.6 AC1: Find a replacement venue opens the catalogue pre-filled from the booking's requirement", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, LANTERN)
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)

  await page.getByRole('link', { name: FIND_REPLACEMENT }).click()

  const banner = catalogueBanner(page, LANTERN)
  await expect(banner).toContainText(`Replacing ${FOYER}`)
  await expect(banner.getByRole('button', { name: MAIN_HALL, exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(filters(page).getByLabel('Capacity from')).toHaveValue('100')
  await expect(filters(page).getByLabel('From', { exact: true })).toHaveValue('2029-02-05T10:00')
  await expect(filters(page).getByLabel('To', { exact: true })).toHaveValue('2029-02-05T16:00')
  await expect(filters(page).getByLabel('Layout')).toHaveValue('STANDING')
  // Grand Hall is free and fits; the venue being replaced is not offered.
  await expect(venueCard(page, GRAND_HALL)).toBeVisible()
  await expect(venueCard(page, FOYER)).toHaveCount(0)
})

test("12.6 AC1: an additional venue is replaced from the event's own period and attendance", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, MAKER_FAIRE)

  const banner = catalogueBanner(page, MAKER_FAIRE)
  await expect(banner).toContainText(`Replacing ${FOYER}`)
  await expect(banner).toContainText('additional venue')
  await expect(filters(page).getByLabel('Capacity from')).toHaveValue('100')
  await expect(filters(page).getByLabel('From', { exact: true })).toHaveValue('2029-02-07T10:00')
  await expect(filters(page).getByLabel('To', { exact: true })).toHaveValue('2029-02-07T20:00')
  expect(new URL(page.url()).searchParams.has('requirement')).toBe(false)
  await expect(venueCard(page, FOYER)).toHaveCount(0)
})

test('12.6 AC1/AC7: replacement mode survives a filter change, Clear all and the requirement again', async ({
  page,
}) => {
  const BOARDROOM = 'Boardroom 3.4'
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, LANTERN)
  const banner = catalogueBanner(page, LANTERN)

  /** Still replacing the Foyer: the banner says so, the address keeps it, the closed venue stays
   *  out, `venue` still offers Request this venue, and the booked panel offers no second search. */
  async function expectStillReplacing(venue: string) {
    await expect(banner).toContainText(`Replacing ${FOYER}`)
    await expect(
      venueCard(page, venue).getByRole('link', { name: REQUEST_THIS_VENUE }),
    ).toBeVisible()
    expect(new URL(page.url()).searchParams.has('replacing')).toBe(true)
    await expect(venueCard(page, FOYER)).toHaveCount(0)
    await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
  }

  // A filter changed by hand.
  await filters(page).getByLabel('Capacity from').fill('')
  // The panel waits for a pause in typing before it changes the address.
  await expect(page).not.toHaveURL(/capacity=/)
  await expectStillReplacing(GRAND_HALL)

  // Selecting the same requirement again restores its own filters, and keeps replacing.
  await banner.getByRole('button', { name: MAIN_HALL, exact: true }).click()
  await expect(filters(page).getByLabel('Capacity from')).toHaveValue('100')
  await expectStillReplacing(GRAND_HALL)

  // Clear all drops every filter, so the boardroom is listed; the Foyer is still out.
  await page.getByRole('button', { name: 'Clear all filters' }).click()
  await expect(filters(page).getByLabel('Capacity from')).toHaveValue('')
  await expectStillReplacing(BOARDROOM)

  // AC7 from there: the boardroom does not suit 100 people, so its request asks for a justification.
  await venueCard(page, BOARDROOM).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${BOARDROOM}`, level: 1 })).toBeVisible()
  await expect(page.getByText(`Replaces ${FOYER}`)).toBeVisible()
  await expect(page.getByLabel('Justification')).toBeVisible()
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('heading', { name: `Request ${BOARDROOM}`, level: 1 })).toBeVisible()
})

for (const [size, viewport] of [
  ['1280x720', DESKTOP],
  ['390x844', PHONE],
] as const) {
  test(`12.6 AC1: Find a replacement venue is usable at ${size}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await signIn(page, ACCOUNTS.coordinator)
    await openEvent(page, LANTERN)

    const link = page.getByRole('link', { name: FIND_REPLACEMENT })
    await expectFitsPage(page, link)
    await link.click()
    await expect(catalogueBanner(page, LANTERN)).toBeVisible()
    await expect(venueCard(page, GRAND_HALL)).toBeVisible()
  })
}

// --- AC2 ----------------------------------------------------------------------------------------
test('12.6 AC2: Request this venue raises a pending replacement shown on the event page', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, SPRING_EXPO)

  await venueCard(page, GRAND_HALL).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${GRAND_HALL}`, level: 1 })).toBeVisible()
  await expect(page.getByText(`Replaces ${FOYER}`)).toBeVisible()
  // The original's setup and teardown are the step's, and can be changed.
  const turnaround = page.getByRole('region', { name: 'Setup and teardown' })
  await expect(turnaround).toContainText(
    'Copied from the booking it replaces; change them if needed.',
  )
  await expect(turnaround).not.toContainText('Both stay 0 unless you enter more.')
  const setupMinutes = turnaround
    .getByRole('group', { name: 'Setup', exact: true })
    .getByLabel('Minutes')
  for (const part of ['Setup', 'Teardown']) {
    await expect(
      turnaround.getByRole('group', { name: part, exact: true }).getByLabel('Minutes'),
    ).toHaveValue('30')
  }
  // Both changed from the copied 30: what the coordinator typed is what is requested.
  await setupMinutes.fill('15')
  await turnaround
    .getByRole('group', { name: 'Teardown', exact: true })
    .getByLabel('Minutes')
    .fill('45')
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(page.getByRole('heading', { name: SPRING_EXPO.name, level: 1 })).toBeVisible()
  const bookings = bookingList(page)
  await expect(bookings).toContainText(`Replaces ${FOYER}`)
  await expect(bookings).toContainText(`Replacement requested: ${GRAND_HALL}`)
  await expect(bookings).toContainText('Setup: 15 min')
  await expect(bookings).toContainText('Teardown: 45 min')
})

// --- AC3: one event, three steps in order ---------------------------------------------------
test.describe('12.6 AC3 on the awards evening', () => {
  test.describe.configure({ mode: 'serial' })

  test('12.6 AC3: Venue Staff are told what the replacement replaces and what approving releases', async ({
    page,
    browser,
  }) => {
    await signIn(page, ACCOUNTS.coordinator)
    await findReplacementFor(page, AWARDS)
    await requestGrandHall(page, AWARDS)

    const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
    const card = await queueCard(staff, AWARDS)
    await expect(card).toContainText(`Replaces ${FOYER}`)
    await expect(card).toContainText(`Approving this releases ${FOYER}`)
    await card.getByRole('link').first().click()
    // react-router changes the address before the new page renders, and the queue's cards carry
    // the same text, so wait until the queue itself has gone.
    await expect(staff).toHaveURL(/\/venue-staff\/booking-requests\/[0-9a-f-]{36}$/)
    await expect(staff.getByRole('heading', { name: 'Booking Requests', exact: true })).toHaveCount(
      0,
    )
    await expect(staff.getByText(`Replaces ${FOYER}`)).toBeVisible()
    await expect(staff.getByText(`Approving this releases ${FOYER}`)).toBeVisible()
    await staff.context().close()
  })

  test('12.6 AC3: Venue Staff approve the replacement and the event page shows Replaced by and Replaces', async ({
    page,
    browser,
  }) => {
    const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
    await showOnlyRequestsOf(staff, AWARDS)
    const card = await queueCard(staff, AWARDS, 'All')
    await card.getByRole('button', { name: 'Approve' }).click()
    const dialog = staff.getByRole('dialog', { name: 'Approve this booking?' })
    await dialog.getByLabel('Hold expires').fill(HOLD_EXPIRES('08'))
    await dialog.getByRole('button', { name: 'Approve' }).click()
    await expect(dialog).not.toBeVisible()
    // The All tab is read again, since the approval released the original: its card moves to
    // Cancelled, and the replacement's no longer says what approving it will release.
    const queue = staff.getByRole('listitem').filter({ hasText: AWARDS.name })
    await expect(queue.filter({ hasText: `Replaced by ${GRAND_HALL}` })).toContainText('Cancelled')
    await expect(queue.filter({ hasText: `Replaces ${FOYER}` })).not.toContainText(
      `Approving this releases ${FOYER}`,
    )
    await staff.context().close()

    await signIn(page, ACCOUNTS.coordinator)
    await openEvent(page, AWARDS)
    const bookings = bookingList(page)
    await expect(bookings).toContainText(`Replaced by ${GRAND_HALL}`)
    await expect(bookings).toContainText(`Replaces ${FOYER}`)
    await expect(bookings).toContainText('Cancelled')
    await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
    // The released original closed when its replacement was approved, not when it was approved
    // itself (the seed approves it at 09:00 on 10 Oct 2026).
    await expect(bookings).toContainText('Closed at')
    await expect(bookings).not.toContainText(ORIGINAL_APPROVED_AT)
  })

  for (const [size, viewport] of [
    ['1280x720', DESKTOP],
    ['390x844', PHONE],
  ] as const) {
    test(`12.6 AC3: the Replaced by and Replaces entries are usable at ${size}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport)
      await signIn(page, ACCOUNTS.coordinator)
      await openEvent(page, AWARDS)

      const bookings = bookingList(page)
      await expectFitsPage(page, bookings)
      await expect(bookings.getByText(`Replaced by ${GRAND_HALL}`)).toBeVisible()
      await expect(bookings.getByText(`Replaces ${FOYER}`)).toBeVisible()
    })
  }
})

// --- AC4, AC5, AC10: the pitch night's replacement, withdrawn and asked for again -------------------
test('12.6 AC4/AC5/AC10: the banner follows the replacement, and a withdrawn one can be asked for again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, PITCH_NIGHT)
  await requestGrandHall(page, PITCH_NIGHT)

  // Back to the catalogue the request was made from: it is no longer replacing anything, since
  // a replacement is pending, so it offers no second one - not even with every filter cleared.
  await page.goBack()
  await expect(catalogueBanner(page, PITCH_NIGHT)).toBeVisible()
  await expect(catalogueBanner(page, PITCH_NIGHT)).not.toContainText(`Replacing ${FOYER}`)
  await expect(catalogueBanner(page, PITCH_NIGHT)).toContainText(
    `Replacement requested: ${GRAND_HALL}`,
  )
  await page.getByRole('button', { name: 'Clear all filters' }).click()
  await expect(filters(page).getByLabel('Capacity from')).toHaveValue('')
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)

  // AC4: while it is pending the requirement says so in the banner, and neither Switch nor a
  // second request is offered for it (AC10: a pending replacement is withdrawn, not switched).
  await page.goto(
    `/venues?event=${PITCH_NIGHT.id}&requirement=cccccccc-0000-0000-0126-000000006601`,
  )
  const banner = catalogueBanner(page, PITCH_NIGHT)
  await expect(banner).toContainText(`Replacement requested: ${GRAND_HALL}`)
  await expect(page.getByRole('link', { name: SWITCH_TO })).toHaveCount(0)
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
  // AC4/AC10: the booked panel keeps saying what was asked for, and offers no second search.
  const booked = page.getByRole('region', { name: `Booked for ${MAIN_HALL}` })
  await expect(booked).toContainText(UNAVAILABLE_LABEL)
  await expect(booked.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)

  // AC5: withdrawn from the event's page, the original stays marked and a new one can be asked for.
  await openEvent(page, PITCH_NIGHT)
  await expect(bookingList(page)).toContainText(`Replacement requested: ${GRAND_HALL}`)
  await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
  await page.getByRole('button', { name: `Withdraw ${GRAND_HALL} for ${MAIN_HALL}` }).click()
  const dialog = page.getByRole('dialog', {
    name: 'Withdraw this booking request?',
  })
  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)
  await page.getByRole('link', { name: FIND_REPLACEMENT }).click()
  await expect(catalogueBanner(page, PITCH_NIGHT)).toContainText(`Venue unavailable: ${FOYER}`)
  await requestGrandHall(page, PITCH_NIGHT)
  await expect(bookingList(page)).toContainText(`Replacement requested: ${GRAND_HALL}`)
})

test('12.6 AC5/AC10: Back after replacing an additional venue offers no second request and says why', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, HARVEST_FAIR)
  await expect(catalogueBanner(page, HARVEST_FAIR)).toContainText(`Replacing ${FOYER}`)
  await requestGrandHall(page, HARVEST_FAIR)

  // The address still names the booking being replaced, but a replacement is pending on it now and
  // an additional venue has no requirement to fall back on: nothing is offered, and the banner says
  // why.
  await page.goBack()
  await expect(catalogueBanner(page, HARVEST_FAIR)).toBeVisible()
  await expect(catalogueBanner(page, HARVEST_FAIR)).not.toContainText(`Replacing ${FOYER}`)
  await expect(catalogueBanner(page, HARVEST_FAIR)).toContainText(
    `Replacement requested: ${GRAND_HALL}`,
  )
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear all filters' }).click()
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
})

test('12.6 AC4: the banner says Venue unavailable and Find a venue skips the marked requirement', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, LANTERN)

  await page.getByRole('link', { name: FIND_A_VENUE }).click()

  // The Lantern Festival's Breakout room needs a venue and its Main hall has a marked one, so
  // Find a venue opens on the Breakout room.
  const banner = catalogueBanner(page, LANTERN)
  await expect(banner.getByRole('button', { name: BREAKOUT_ROOM, exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(banner.getByRole('button', { name: MAIN_HALL, exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
  await expect(banner.getByRole('button', { name: MAIN_HALL, exact: true })).toContainText(
    `Venue unavailable: ${FOYER}`,
  )
  await expect(banner.getByRole('button', { name: BREAKOUT_ROOM, exact: true })).toContainText(
    'Needs a venue',
  )
})

test('12.6 AC4: selecting the marked requirement shows its booking with Find a replacement venue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/venues?event=${LANTERN.id}&requirement=${MAIN_HALL_OF_LANTERN}`)
  const banner = catalogueBanner(page, LANTERN)
  await expect(banner).toBeVisible()

  await banner.getByRole('button', { name: MAIN_HALL, exact: true }).click()

  const marked = page.getByRole('region', { name: `Booked for ${MAIN_HALL}` })
  await expect(marked).toContainText(FOYER)
  await expect(marked).toContainText(UNAVAILABLE_LABEL)
  await expect(marked.getByRole('link', { name: FIND_REPLACEMENT })).toBeVisible()
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
})

test('12.6 AC4: the event page does not read All required venues booked while its only booking is marked', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${ROBOTICS.id}`)
  await expect(page.getByRole('heading', { name: ROBOTICS.name, level: 1 })).toBeVisible()
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)

  await expect(page.getByRole('link', { name: ALL_BOOKED })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /^Find a (replacement )?venue$/ })).toBeVisible()
})

// --- AC6 ----------------------------------------------------------------------------------------
test('12.6 AC6: when the closure is removed the button goes and the pending replacement can be withdrawn', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, SUMMIT)
  await requestGrandHall(page, SUMMIT)
  await expect(bookingList(page)).toContainText(`Replacement requested: ${GRAND_HALL}`)

  // Venue Staff remove the closure of the 13th from the foyer's calendar. The browser's clock is
  // pinned to the month before, as the 9.4 spec does for its venues, so the grid opens on February.
  const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
  await staff.clock.setFixedTime(new Date('2029-02-01T10:00:00+08:00'))
  await staff.goto('/venues')
  await staff.getByRole('link', { name: FOYER }).click()
  const availability = staff.getByRole('region', { name: 'Availability', exact: true })
  await expect(availability).toBeVisible()
  await availability.getByRole('button', { name: /^13 February 2029/ }).click()
  const closure = staff.getByRole('listitem').filter({ hasText: 'Floor resurfacing' })
  await closure.getByRole('button', { name: 'Remove' }).click()
  await staff.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
  await expect(closure).toHaveCount(0)
  await staff.context().close()

  // The mark has cleared: no more Find a replacement venue, but the replacement is still there to
  // withdraw, and the original is kept.
  await openEvent(page, SUMMIT)
  await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
  await expect(bookingList(page)).not.toContainText(UNAVAILABLE_LABEL)
  await page.getByRole('button', { name: `Withdraw ${GRAND_HALL} for ${MAIN_HALL}` }).click()
  const dialog = page.getByRole('dialog', {
    name: 'Withdraw this booking request?',
  })
  await dialog.getByRole('button', { name: 'Withdraw' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(bookingList(page)).toContainText(FOYER)
  await expect(bookingList(page)).toContainText('Approved')
  // AC12: the pending replacement was the last thing stopping the review, and the page says so
  // without a reload.
  await expect(page.getByRole('button', { name: 'Request safety review' })).toBeVisible()
})

// --- AC8 ----------------------------------------------------------------------------------------
test('12.6 AC8: a cancelled event offers no Find a replacement venue', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  // The same coordinator is offered it on an event that is going ahead, so its absence below is the
  // cancellation's doing.
  await openEvent(page, LANTERN)
  await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toBeVisible()
  await page.goto(`/events/${HERITAGE.id}`)
  await expect(page.getByRole('heading', { name: HERITAGE.name, level: 1 })).toBeVisible()
  await expect(bookingList(page)).toContainText(FOYER)

  await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
})

// --- AC9 ----------------------------------------------------------------------------------------
test('12.6 AC9: only the assigned coordinator is offered Find a replacement venue', async ({
  browser,
}) => {
  // The assigned coordinator is offered it on the same event, so the others' absence is theirs.
  const owner = await signedInPage(browser, ACCOUNTS.coordinator)
  await openEvent(owner, LANTERN)
  await expect(owner.getByRole('link', { name: FIND_REPLACEMENT })).toBeVisible()
  await owner.context().close()

  for (const account of [
    ACCOUNTS.coordinator2,
    ACCOUNTS.lead,
    ACCOUNTS.venueStaff,
    ACCOUNTS.organiser2,
  ]) {
    const page = await signedInPage(browser, account)
    await page.goto(`/events/${LANTERN.id}`)
    await expect(page.getByRole('heading', { name: LANTERN.name, level: 1 })).toBeVisible()
    await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)
    await page.context().close()
  }
})

test('12.6 AC9: a marked pending booking offers Find another venue, which leads to Switch to this venue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, SHOWCASE)
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)
  await expect(page.getByRole('link', { name: FIND_REPLACEMENT })).toHaveCount(0)

  await page.getByRole('link', { name: FIND_ANOTHER }).click()

  await expect(catalogueBanner(page, SHOWCASE)).toBeVisible()
  await expect(venueCard(page, GRAND_HALL).getByRole('link', { name: SWITCH_TO })).toBeVisible()
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
})

// --- AC11 ---------------------------------------------------------------------------------------
const INBOX = '/events/inbox'

test('12.6 AC11: the Venue unavailable tab lists only marked events and shows its count', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(INBOX)

  // Carl's two marked events, and no others; every other tab's count is the page's own.
  const tab = page.getByRole('tab', { name: 'Venue unavailable (2)' })
  await expect(tab).toBeVisible()
  await tab.click()
  await expect(page.getByRole('link', { name: new RegExp(ROBOTICS.name) })).toBeVisible()
  await expect(page.getByRole('link', { name: new RegExp(WELLNESS.name) })).toBeVisible()
  await expect(page.getByRole('link', { name: /Harbour Lights Concert/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /Marina Food Festival/ })).toHaveCount(0)
})

test('12.6 AC11: the tab shows 0 and stays visible when no event is marked', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator2)
  // The seed cannot give a coordinator none marked, so the one list call is stubbed.
  await page.route(
    (url) => url.pathname === '/events/assigned-to-me',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [],
          total: 0,
          venue_unavailable_count: 0,
        }),
        headers: corsHeaders(request),
      })
    },
  )

  await page.goto(INBOX)

  const tab = page.getByRole('tab', { name: 'Venue unavailable (0)' })
  await expect(tab).toBeVisible()
  await tab.click()
  await expect(page.getByRole('link', { name: new RegExp(ROBOTICS.name) })).toHaveCount(0)
})

test('12.6 AC11: an event with a pending replacement shows Replacement requested and opens to the marked booking', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(INBOX)
  await page.getByRole('tab', { name: /^Venue unavailable/ }).click()
  await page.getByRole('link', { name: new RegExp(WELLNESS.name) }).click()

  // Opening the event shows the marked booking and the way to replace it.
  await expect(page.getByRole('heading', { name: WELLNESS.name, level: 1 })).toBeVisible()
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)
  await page.getByRole('link', { name: FIND_REPLACEMENT }).click()
  await expect(catalogueBanner(page, WELLNESS)).toBeVisible()
  await requestGrandHall(page, WELLNESS)

  // Still in the tab, now naming the venue asked for; the tab's count has not changed.
  await page.goto(INBOX)
  await expect(page.getByRole('tab', { name: 'Venue unavailable (2)' })).toBeVisible()
  await page.getByRole('tab', { name: /^Venue unavailable/ }).click()
  // The card is a list item holding its title link and its details, so the chip is read from it.
  await expect(page.getByRole('listitem').filter({ hasText: WELLNESS.name })).toContainText(
    `Replacement requested: ${GRAND_HALL}`,
  )
})

// --- AC12 ---------------------------------------------------------------------------------------
test('12.6 AC12: the event page says a marked booking stops the safety review', async ({
  page,
}) => {
  // The robotics open house is secured - its one requirement has an approved booking - but that
  // booking is marked, so Request safety review is not offered: the page names the venue instead.
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${ROBOTICS.id}`)
  await expect(page.getByRole('heading', { name: ROBOTICS.name, level: 1 })).toBeVisible()

  await expect(
    page.getByText(
      `${FOYER} is unavailable for part of its booked period: replace it, or wait for it to reopen.`,
    ),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Request safety review' })).toHaveCount(0)
})

// --- review of #123 ------------------------------------------------------------------------------
/** Venue Staff remove the foyer's closure of `day` from its details page, as 9.4 AC6 allows while
 *  it has not started; the browser's clock is pinned to the month before, so the grid opens on it. */
async function removeFoyerClosure(browser: Browser, day: RegExp) {
  const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
  await staff.clock.setFixedTime(new Date('2029-02-01T10:00:00+08:00'))
  await staff.goto('/venues')
  await staff.getByRole('link', { name: FOYER }).click()
  const availability = staff.getByRole('region', { name: 'Availability', exact: true })
  await expect(availability).toBeVisible()
  await availability.getByRole('button', { name: day }).click()
  const closure = staff.getByRole('listitem').filter({ hasText: 'Floor resurfacing' })
  await closure.getByRole('button', { name: 'Remove' }).click()
  await staff.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
  await expect(closure).toHaveCount(0)
  await staff.context().close()
}

/** Answer the event's booking list with its real answer, the first booking changed by `patch`. */
async function patchFirstBooking(page: Page, event: SeededEvent, patch: Record<string, unknown>) {
  await page.route(
    (url) => url.pathname === `/bookings/for-event/${event.id}`,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      const bookings = (await response.json()) as Record<string, unknown>[]
      return route.fulfill({ response, json: [{ ...bookings[0], ...patch }, ...bookings.slice(1)] })
    },
  )
}

test('12.6 AC2/AC6: a replacement asked for after the closure was removed is refused, not sent as a plain request', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, CRAFT_MARKET)
  await page.getByRole('link', { name: FIND_REPLACEMENT }).click()
  await expect(catalogueBanner(page, CRAFT_MARKET)).toContainText(`Replacing ${FOYER}`)

  // Venue Staff remove the closure of the 20th while the catalogue is open.
  await removeFoyerClosure(browser, /^20 February 2029/)

  await venueCard(page, GRAND_HALL).getByRole('link', { name: REQUEST_THIS_VENUE }).click()
  await expect(page.getByRole('heading', { name: `Request ${GRAND_HALL}`, level: 1 })).toBeVisible()
  await expect(page.getByText(`Replaces ${FOYER}`)).toHaveCount(0)
  await page.getByRole('button', { name: 'Send request' }).click()

  // The server's reason, and nothing was requested - the request is not taken as an additional venue.
  await expect(page.getByRole('alert')).toContainText('no longer marked')
  await openEvent(page, CRAFT_MARKET)
  await expect(bookingList(page)).not.toContainText(GRAND_HALL)
})

test('12.6 AC2: when the event bookings cannot be read the step says so and cannot send', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, LANTERN)
  let isFailing = false
  await page.route(
    (url) => url.pathname === `/bookings/for-event/${LANTERN.id}`,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || !isFailing) return route.fallback()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'The bookings could not be read.' }),
        headers: corsHeaders(request),
      })
    },
  )

  isFailing = true
  await venueCard(page, GRAND_HALL).getByRole('link', { name: REQUEST_THIS_VENUE }).click()

  await expect(page.getByRole('heading', { name: `Request ${GRAND_HALL}`, level: 1 })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText(
    "the event's other bookings could not be read",
  )
  await expect(page.getByRole('button', { name: 'Send request' })).toBeDisabled()
})

test("12.6 AC1/AC10: the closed venue's own page offers no Request this venue while replacing it", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, LANTERN)

  await page
    .getByRole('region', { name: `Booked for ${MAIN_HALL}` })
    .getByRole('link', { name: FOYER })
    .click()

  await expect(page.getByRole('heading', { name: FOYER, level: 1 })).toBeVisible()
  // The event and its bookings load beside the venue; wait for them, so the absence below is the
  // page's rule and not a page still loading.
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('link', { name: REQUEST_THIS_VENUE })).toHaveCount(0)
})

test('12.6 AC10: a pending replacement whose own venue is closed offers no way to another venue, only Withdraw', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  // The open studios' pending replacement at the foyer, which its own closure marks too: its way
  // out is Withdraw, since a pending replacement is withdrawn, not switched.
  await openEvent(page, OPEN_STUDIOS)

  await expect(bookingList(page)).toContainText(`Replaces ${HARBOUR}`)
  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)
  await expect(page.getByRole('link', { name: FIND_ANOTHER })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Withdraw / })).toBeVisible()
})

test('12.6 AC9: a marked pending additional venue offers Withdraw, not a catalogue that adds a second venue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page, NIGHT_BAZAAR)

  await expect(bookingList(page)).toContainText(UNAVAILABLE_LABEL)
  await expect(page.getByRole('link', { name: FIND_ANOTHER })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Withdraw / })).toBeVisible()
})

test('12.6 AC9: a withdrawn marked booking no longer offers Find another venue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  // The withdrawal itself is answered here: the seeded booking is every other test's to read.
  await page.route(
    (url) => /^\/bookings\/[0-9a-f-]{36}\/withdraw$/.test(url.pathname),
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: new URL(request.url()).pathname.split('/')[2],
          status: 'WITHDRAWN',
          decided_at: new Date().toISOString(),
          decision_reason: null,
        }),
        headers: corsHeaders(request),
      })
    },
  )
  await openEvent(page, SHOWCASE)
  await expect(page.getByRole('link', { name: FIND_ANOTHER })).toBeVisible()

  await page.getByRole('button', { name: /^Withdraw / }).click()
  await page
    .getByRole('dialog', { name: 'Withdraw this booking request?' })
    .getByRole('button', { name: 'Withdraw' })
    .click()

  await expect(bookingList(page)).toContainText('Withdrawn')
  // A closed booking holds nothing, so nothing marks it any more (9.4 AC3).
  await expect(bookingList(page)).not.toContainText(UNAVAILABLE_LABEL)
  await expect(page.getByRole('link', { name: FIND_ANOTHER })).toHaveCount(0)
})

test('12.6 AC11: reopening the Venue unavailable tab after a failed load shows the list, not the old error', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  let isFailing = true
  await page.route(
    (url) =>
      url.pathname === '/events/assigned-to-me' &&
      url.searchParams.get('venue_unavailable') === 'true',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || !isFailing) return route.fallback()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'The events could not be read.' }),
        headers: corsHeaders(request),
      })
    },
  )
  await page.goto(INBOX)
  await page.getByRole('tab', { name: /^Venue unavailable/ }).click()
  await expect(page.getByRole('alert')).toBeVisible()

  isFailing = false
  await page.getByRole('tab', { name: /^All/ }).click()
  await page.getByRole('tab', { name: /^Venue unavailable/ }).click()

  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('link', { name: new RegExp(ROBOTICS.name) })).toBeVisible()
})

test('12.6 AC11: the Venue unavailable tab shows loading, not the last tab, while its list loads', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  let releaseList: () => void = () => {}
  const isHeld = new Promise<void>((resolve) => {
    releaseList = resolve
  })
  await page.route(
    (url) =>
      url.pathname === '/events/assigned-to-me' &&
      url.searchParams.get('venue_unavailable') === 'true',
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      await isHeld
      return route.fallback()
    },
  )
  await page.goto(INBOX)
  await page.getByRole('tab', { name: /^Venue unavailable/ }).click()

  await expect(page.getByText('Loading')).toBeVisible()
  await expect(page.getByRole('link', { name: /Harbour Lights Concert/ })).toHaveCount(0)
  releaseList()
  await expect(page.getByRole('link', { name: new RegExp(ROBOTICS.name) })).toBeVisible()
})

// --- a replacement rejected, read under the All tab ---------------------------------------------
test('12.6 AC5: a rejected replacement under All no longer says what approving it releases', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findReplacementFor(page, SPRING_FAIR)
  await requestGrandHall(page, SPRING_FAIR)

  const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
  await showOnlyRequestsOf(staff, SPRING_FAIR)
  const card = await queueCard(staff, SPRING_FAIR, 'All')
  await expect(card).toContainText(`Approving this releases ${FOYER}`)
  await card.getByRole('button', { name: 'Reject' }).click()
  const dialog = staff.getByRole('dialog', { name: 'Reject this booking?' })
  await dialog.getByLabel('Reason for rejecting').fill('The hall is held for another event.')
  await dialog.getByRole('button', { name: 'Reject' }).click()
  await expect(dialog).not.toBeVisible()

  const rejected = staff
    .getByRole('listitem')
    .filter({ hasText: SPRING_FAIR.name })
    .filter({ hasText: 'Rejected' })
  await expect(rejected).toContainText('Rejected')
  await expect(rejected).toContainText(`Replaces ${FOYER}`)
  await expect(rejected).not.toContainText('Approving this releases')
  await staff.context().close()
})

// --- an address that names a booking which no longer takes a replacement -------------------------
test('12.6 AC10: a stale replacing address cannot turn Switch to this venue into a replacement', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  // The garden fair's requirement is covered by a plain pending request, which a switch replaces.
  // The address also names its older, withdrawn request as `replacing`, as a link kept from before
  // would: that booking takes no replacement, so the send is the switch it was opened for.
  await page.goto(
    `/events/${GARDEN_FAIR.id}/request-venue/${GRAND_HALL_ID}` +
      `?requirement=${GARDEN_FAIR_REQUIREMENT}&replaces=${GARDEN_FAIR_PENDING}` +
      `&replacing=${GARDEN_FAIR_WITHDRAWN}`,
  )
  await expect(page.getByRole('heading', { name: `Request ${GRAND_HALL}`, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Switch request' }).click()

  await expect(page.getByRole('heading', { name: GARDEN_FAIR.name, level: 1 })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  // The pending request was switched to Grand Hall, and nothing was asked of the withdrawn one.
  await expect(bookingList(page)).toContainText(GRAND_HALL)
  await expect(bookingList(page)).not.toContainText('Replaces')
})
