/**
 * Story 12.6 - request a replacement venue for an affected booking: what a coordinator clicks
 * through when Venue Staff have closed a venue over a booking of theirs.
 *
 * AC1  On an approved booking marked "Venue unavailable – alternative needed" the event's page
 *      offers Find a replacement venue, which opens the catalogue pre-filled from the booking's
 *      requirement - or, for an additional venue, from the event's own period and attendance -
 *      with the banner naming the booking being replaced. Usable at 1280x720 and 390x844.
 * AC2  Request this venue raises a pending replacement; the request step says what it replaces
 *      and carries the original's setup and teardown, editable; the event page lists both.
 * AC3  Venue Staff's queue card and request page say what the replacement replaces and what
 *      approving it releases; once approved the event's list reads "Replaced by <venue>" on the
 *      original and "Replaces <venue>" on the replacement, at both sizes.
 * AC4  Until it is approved the requirement reads "Venue unavailable: <venue>" in the banner, then
 *      "Replacement requested: <venue>"; the event page does not read "All required venues
 *      booked" while its only live booking is marked; Find a venue skips a marked requirement;
 *      selecting one in the banner shows its booking with Find a replacement venue, never
 *      Request this venue.
 * AC5  A withdrawn replacement leaves the original marked, and another can be requested.
 * AC6  Once the closure is removed Find a replacement venue goes, and the pending replacement can
 *      still be withdrawn with the original kept.
 * AC8  A cancelled event's marked booking offers no replacement.
 * AC9  Only the event's assigned coordinator is offered Find a replacement venue; a marked
 *      pending booking offers Find another venue, which leads to Switch to this venue.
 * AC10 Switch to this venue is not offered on a pending replacement.
 * AC13 While a booking is marked the event cannot go for a safety review or be confirmed, and its
 *      page says why - naming the venue - in place of the button.
 * AC11 The coordinator's Events inbox has a "Venue unavailable" tab with the server's count, its
 *      empty state, and the pending replacement named on its cards.
 *
 * The rules - the refusals, the one pending replacement, the release, the race, the notices, the
 * list's count and paging - are backend cases: backend/tests/bookings/test_request_replacement.py,
 * test_replacement_approval.py, test_replacement_schema.py, test_replacement_for_venue_staff.py,
 * backend/tests/events/test_assigned_events_venue_unavailable.py and
 * backend/tests/venues/test_venue_search_exclude_venue.py. This file is the flow a person clicks.
 *
 * Seed (backend/db/seed/020_sample_data.sql, "Story 12.6"): ten events of February 2029, each with
 * a booking at Exhibition Foyer marked by the closure of its day, and Grand Hall free for every
 * one. Each flow that changes something has an event of its own (see the seed's note), so specs
 * running in parallel never share one; the ones that read are never changed. The 2 s the DoD asks
 * of the pre-filled catalogue is checked by hand, not here.
 */
import { expect, test, type Browser, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, corsHeaders, signIn, venueCard } from './support'

const FOYER = 'Exhibition Foyer'
const GRAND_HALL = 'Grand Hall'
const MAIN_HALL = 'Main hall'
const BREAKOUT_ROOM = 'Breakout room'
const MAIN_HALL_OF_LANTERN = 'cccccccc-0000-0000-0062-000000000001'

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
async function queueCard(page: Page, event: SeededEvent) {
  await page.goto('/venue-staff/booking-requests')
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

test('12.6 AC1/AC10/AC7: replacement mode survives a filter change, Clear all and the requirement again', async ({
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
  for (const part of ['Setup', 'Teardown']) {
    await expect(
      turnaround.getByRole('group', { name: part, exact: true }).getByLabel('Minutes'),
    ).toHaveValue('30')
  }
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(page.getByRole('heading', { name: SPRING_EXPO.name, level: 1 })).toBeVisible()
  const bookings = bookingList(page)
  await expect(bookings).toContainText(`Replaces ${FOYER}`)
  await expect(bookings).toContainText(`Replacement requested: ${GRAND_HALL}`)
  await expect(bookings).toContainText('Setup: 30 min')
  await expect(bookings).toContainText('Teardown: 30 min')
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
    const card = await queueCard(staff, AWARDS)
    await card.getByRole('button', { name: 'Approve' }).click()
    const dialog = staff.getByRole('dialog', { name: 'Approve this booking?' })
    await dialog.getByLabel('Hold expires').fill(HOLD_EXPIRES('08'))
    await dialog.getByRole('button', { name: 'Approve' }).click()
    await expect(dialog).not.toBeVisible()
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

  // AC4: while it is pending the requirement says so in the banner, and neither Switch nor a
  // second request is offered for it (AC10: a pending replacement is withdrawn, not switched).
  await page.goto(
    `/venues?event=${PITCH_NIGHT.id}&requirement=cccccccc-0000-0000-0066-000000000001`,
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

  // Venue Staff remove the closure of the 13th from the foyer's calendar, on its Edit venue page. The browser's clock is
  // pinned to the month before, as the 9.4 spec does for its venues, so the grid opens on February.
  const staff = await signedInPage(browser, ACCOUNTS.venueStaff)
  await staff.clock.setFixedTime(new Date('2029-02-01T10:00:00+08:00'))
  await staff.goto('/venues')
  // Story 12.6 AC12: the controls are on the Edit venue page.
  await venueCard(staff, FOYER).getByRole('link', { name: 'Edit' }).click()
  const availability = staff.getByRole('region', {
    name: 'Availability',
    exact: true,
  })
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

// --- AC13 ---------------------------------------------------------------------------------------
test('12.6 AC13: the event page says a marked booking stops the safety review', async ({
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
