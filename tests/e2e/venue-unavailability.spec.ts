/**
 * Story 9.4: mark a venue temporarily unavailable, even with events booked there.
 *
 * AC1  Venue Staff add a closure from the venue's page - a start, an end, a reason and a
 *      description, which every reason needs - and the calendar shows it as "Unavailable" with
 *      its reason; a block off with no description is refused in the backend's own words, and
 *      the month grid's chip names the reason, or the description for Other.
 * AC5  An end not after the start is refused in the form, before anything is sent.
 * AC2  Before Save, the bookings the closure would affect are listed; Save still goes through.
 * AC3  A flagged booking reads "Venue unavailable – alternative needed" on its event's page.
 * AC6  A closure is edited, then ended, from the day it falls on; an ended one shows no actions;
 *      editing one that was removed meanwhile says so.
 * AC7  Venue Staff's request page and queue card say a flagged request is unavailable, and
 *      Approve is held back.
 * AC9  Only Venue Staff see the controls; the coordinator and the Safety Officer see the reason
 *      on the calendar but no way to change it.
 *
 * The rules - the reasons and the Other description, what overlaps, the event's return to
 * Planning, who is told, the refusal to approve, the races - are backend cases:
 * backend/tests/venues/test_venue_unavailability.py. This file is the flow a person clicks.
 *
 * Seed (backend/db/seed/020_sample_data.sql), dedicated to this spec so a closure cannot touch
 * any other spec's calendar or approvals: Garden Atrium has no booking; Harbour Pavilion holds the
 * Community Choir Showcase's pending request (14 Oct 2028, 18:00-21:00); Sunrise Studio holds the
 * Neighbourhood Art Market's (21 Oct 2028, 10:00-16:00). The tests that add a closure over a
 * booking leave it flagged, so they run once, each on its own venue.
 *
 * The calendar opens on the current month, and the seeded bookings are in October 2028, so those
 * tests pin the page's own clock to 10 October 2028. Only the browser's Date moves; the server
 * keeps real time, which is why a closure over October 2028 is still "not started" for it. The
 * test that ends a closure needs one already started by the server's clock, so it keeps the real
 * one and works on today.
 */
import { expect, test, type Browser, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, VENUES, inFuture, signIn, uniqueName } from './support'

const PINNED_NOW = new Date('2028-10-10T10:00:00+08:00')

/** The "Availability" card, a region via its `aria-labelledby` (as venue-calendar.spec.ts). */
function availability(page: Page) {
  return page.getByRole('region', { name: 'Availability', exact: true })
}

/** Venue Staff's "Block off time" card, under the calendar: the form, its preview and Save. */
function blockOff(page: Page) {
  return page.getByRole('region', { name: 'Block off time', exact: true })
}

async function openVenue(page: Page, name: string) {
  await page.goto('/venues')
  await page.getByRole('link', { name }).click()
  await expect(availability(page)).toBeVisible()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

/** A day's button in the calendar grid, named "3 October 2028, 1 item". */
function dayButton(page: Page, name: RegExp) {
  return availability(page).getByRole('button', { name })
}

/** The list a day opens, a region named after the day (e.g. "Tue, 3 Oct 2028"). */
function dayList(page: Page, name: RegExp) {
  return page.getByRole('region', { name })
}

const DEFAULT_DESCRIPTION = 'Scheduled work'

interface ClosureForm {
  starts: string
  ends: string
  reason?: string
  /** Left out, the form is given `DEFAULT_DESCRIPTION`. Pass '' to leave it empty. */
  description?: string
}

/** Open the add form on the venue's page and fill it. Nothing is saved. */
async function fillClosure(page: Page, form: ClosureForm) {
  const section = blockOff(page)
  await section.getByRole('button', { name: 'Block off time' }).click()
  await section.getByLabel('Starts').fill(form.starts)
  await section.getByLabel('Ends').fill(form.ends)
  if (form.reason) await section.getByLabel('Reason').selectOption({ label: form.reason })
  // Every block off needs a description, so a case that is not about one gets a plain one.
  await section.getByLabel('Description').fill(form.description ?? DEFAULT_DESCRIPTION)
}

/**
 * A request's card in Venue Staff's queue, by the short id on it. The queue pages by ten and the
 * database is shared with specs that raise requests of their own, so the card may be on a later
 * page: press Next until it shows.
 */
async function queueCard(page: Page, shortId: string) {
  const card = page.getByRole('listitem').filter({ hasText: `#${shortId}` })
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

async function signedInPage(browser: Browser, email: string): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await signIn(page, email)
  return page
}

test('9.4 AC1: Venue Staff add a closure, which the calendar shows as Unavailable with its reason', async ({
  page,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  const description = uniqueName('Atrium floor polishing')

  await fillClosure(page, {
    starts: '2028-10-02T09:00',
    ends: '2028-10-04T18:00',
    reason: 'Maintenance',
    description,
  })
  await expect(blockOff(page).getByText('No bookings are affected.')).toBeVisible()
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()

  await dayButton(page, /^3 October 2028/).click()
  const list = dayList(page, /3 Oct 2028/)
  await expect(list).toContainText(description)
  await expect(list).toContainText('Unavailable – Maintenance')
})

test('9.4 AC2: the bookings a closure would affect are listed before Save, and Save still goes through', async ({
  page,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.harbourPavilion)

  await fillClosure(page, {
    starts: '2028-10-13T08:00',
    ends: '2028-10-15T20:00',
    reason: 'Renovation',
  })

  const affected = blockOff(page).getByRole('region', { name: 'Affected bookings' })
  await expect(affected).toContainText('Community Choir Showcase')
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Community Choir Showcase')
  await dialog.getByRole('button', { name: 'Block off time' }).click()

  await dayButton(page, /^14 October 2028/).click()
  await expect(dayList(page, /14 Oct 2028/)).toContainText('Unavailable – Renovation')
})

test('9.4 AC3 and AC7: a flagged booking reads "alternative needed" on its event, and Venue Staff cannot approve it', async ({
  page,
  browser,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.sunriseStudio)
  await fillClosure(page, {
    starts: '2028-10-21T09:00',
    ends: '2028-10-21T17:00',
    reason: 'Safety concern',
  })
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Block off time' }).click()
  await expect(dayButton(page, /^21 October 2028/)).toBeVisible()

  // AC3: the coordinator's event page flags the booking.
  const coordinator = await signedInPage(browser, ACCOUNTS.coordinator)
  await coordinator.goto(`/events/${EVENTS.artMarket}`)
  await expect(coordinator.getByText('Venue unavailable – alternative needed')).toBeVisible()

  // AC7: Venue Staff's queue card carries the marker and holds Approve back.
  await page.goto('/venue-staff/booking-requests')
  const card = await queueCard(page, '00000014')
  await expect(card).toContainText('Venue unavailable')
  await expect(card.getByRole('button', { name: 'Approve' })).toBeDisabled()

  // ... and so does the request's own page, with a notice saying why.
  await card.getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  // The request page's notice has the status role; the queue's card text does not, so this waits
  // for the page itself and not for the queue it was opened from.
  await expect(
    page.getByRole('status').filter({ hasText: /unavailable for part of this request/ }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toBeDisabled()
})

test('9.4 AC6: a closure in force is edited, then ended, and an ended one shows no actions', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  const description = uniqueName('Atrium lighting')
  // Started yesterday and running three days, so it is in force by the server's clock.
  await fillClosure(page, {
    starts: inFuture(-1, 9),
    ends: inFuture(3, 18),
    reason: 'Equipment failure',
    description,
  })
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()

  const singapore = new Date(Date.now() + 8 * 60 * 60 * 1000)
  const today = new RegExp(
    `^${singapore.getUTCDate()} ${singapore.toLocaleString('en-GB', {
      month: 'long',
      timeZone: 'UTC',
    })} ${singapore.getUTCFullYear()}`,
  )
  await dayButton(page, today).click()
  const item = page.getByRole('listitem').filter({ hasText: description })
  await expect(item).toContainText('Unavailable – Equipment failure')
  await expect(item.getByRole('button', { name: 'Edit' })).toBeVisible()
  await expect(item.getByRole('button', { name: 'End now' })).toBeVisible()
  await expect(item.getByRole('button', { name: 'Remove' })).toHaveCount(0)

  await item.getByRole('button', { name: 'Edit' }).click()
  await blockOff(page).getByLabel('Reason').selectOption({ label: 'Renovation' })
  await blockOff(page).getByRole('button', { name: 'Save changes' }).click()
  await expect(item).toContainText('Unavailable – Renovation')

  await item.getByRole('button', { name: 'End now' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'End now' }).click()
  await expect(item.getByRole('button')).toHaveCount(0)
})

test('9.4 AC9: only Venue Staff see the controls; others read the reason and cannot change it', async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  // The Venue Staff half is what makes this fail before the controls exist: the other two
  // halves cannot fail first, since no role but Venue Staff has ever had a way to add one.
  await expect(blockOff(page).getByRole('button', { name: 'Block off time' })).toBeVisible()

  for (const email of [ACCOUNTS.coordinator, ACCOUNTS.safetyOfficer]) {
    const other = await signedInPage(browser, email)
    await openVenue(other, VENUES.gardenAtrium)
    await expect(availability(other)).toBeVisible()
    await expect(blockOff(other)).toHaveCount(0)
    await expect(other.getByRole('button', { name: 'Block off time' })).toHaveCount(0)
  }
})

test('9.4 AC1: a block off with no description is refused in the backend\'s own words', async ({
  page,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)

  // Other first - the reason that used to be the only one needing a description - then another.
  for (const reason of ['Other', 'Maintenance']) {
    await fillClosure(page, {
      starts: '2028-10-08T09:00',
      ends: '2028-10-08T17:00',
      reason,
      description: '',
    })
    await blockOff(page).getByRole('button', { name: 'Save closure' }).click()
    await expect(blockOff(page).getByRole('alert')).toHaveText(
      'Describe why the venue is blocked off.',
    )
    await blockOff(page).getByRole('button', { name: 'Cancel' }).click()
  }
  await expect(dayButton(page, /^8 October 2028/)).toHaveCount(0)
})

test('9.4 AC5: an end that is not after the start is refused in the form, before anything is sent', async ({
  page,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  const writes: string[] = []
  page.on('request', (request) => {
    if (request.method() !== 'GET') writes.push(`${request.method()} ${request.url()}`)
  })
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  writes.length = 0

  await fillClosure(page, { starts: '2028-10-09T10:00', ends: '2028-10-09T09:00' })

  await expect(blockOff(page).getByRole('alert')).toHaveText('The end must be after the start.')
  await expect(blockOff(page).getByRole('button', { name: 'Save closure' })).toBeDisabled()
  // Equal is not after either.
  await blockOff(page).getByLabel('Ends').fill('2028-10-09T10:00')
  await expect(blockOff(page).getByRole('alert')).toHaveText('The end must be after the start.')
  expect(writes).toEqual([])
})

test('9.4 AC1: the month grid names a closure by its reason, and by its description for Other', async ({
  page,
}) => {
  await page.clock.setFixedTime(new Date('2028-12-10T10:00:00+08:00'))
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  const renovation = uniqueName('Atrium repainting')
  const other = uniqueName('Atrium film shoot')

  await fillClosure(page, {
    starts: '2028-12-05T09:00',
    ends: '2028-12-05T18:00',
    reason: 'Renovation',
    description: renovation,
  })
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()
  await dayButton(page, /^5 December 2028/).waitFor()
  await fillClosure(page, {
    starts: '2028-12-06T09:00',
    ends: '2028-12-06T18:00',
    reason: 'Other',
    description: other,
  })
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()

  const grid = availability(page)
  await expect(dayButton(page, /^5 December 2028/)).toContainText('Renovation')
  await expect(dayButton(page, /^5 December 2028/)).not.toContainText(renovation)
  await expect(dayButton(page, /^6 December 2028/)).toContainText(other)
  // The day list keeps the kind and the description.
  await dayButton(page, /^5 December 2028/).click()
  const list = dayList(page, /5 Dec 2028/)
  await expect(list).toContainText('Unavailable – Renovation')
  await expect(list).toContainText(renovation)
  await expect(grid).toBeVisible()
})

test('9.4 AC6: editing a closure that was removed meanwhile says it is gone, and the calendar catches up', async ({
  page,
  browser,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)
  await openVenue(page, VENUES.gardenAtrium)
  const description = uniqueName('Atrium carpet')
  await fillClosure(page, {
    starts: '2028-10-24T09:00',
    ends: '2028-10-24T18:00',
    description,
  })
  await blockOff(page).getByRole('button', { name: 'Save closure' }).click()
  await dayButton(page, /^24 October 2028/).click()
  const item = page.getByRole('listitem').filter({ hasText: description })
  await expect(item.getByRole('button', { name: 'Edit' })).toBeVisible()

  // Meanwhile another Venue Staff session removes it.
  const other = await signedInPage(browser, ACCOUNTS.venueStaff)
  await other.clock.setFixedTime(PINNED_NOW)
  await openVenue(other, VENUES.gardenAtrium)
  await dayButton(other, /^24 October 2028/).click()
  const removing = other.getByRole('listitem').filter({ hasText: description })
  await removing.getByRole('button', { name: 'Remove' }).click()
  await other.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()
  await expect(dayButton(other, /^24 October 2028/)).toHaveCount(0)

  await item.getByRole('button', { name: 'Edit' }).click()
  await blockOff(page).getByLabel('Description').fill(uniqueName('Atrium carpet again'))
  await blockOff(page).getByRole('button', { name: 'Save changes' }).click()

  await expect(blockOff(page).getByRole('alert')).toHaveText('Unavailability period not found.')
  await expect(dayButton(page, /^24 October 2028/)).toHaveCount(0)
})
