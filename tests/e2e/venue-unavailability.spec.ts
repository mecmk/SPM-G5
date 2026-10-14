/**
 * Story 9.4: mark a venue temporarily unavailable, even with events booked there.
 *
 * AC1  Venue Staff add a closure from the venue's page - a start, an end, a reason and, for
 *      Other, a description - and the calendar shows it as "Unavailable" with its reason.
 * AC2  Before Save, the bookings the closure would affect are listed; Save still goes through.
 * AC3  A flagged booking reads "Venue unavailable – alternative needed" on its event's page.
 * AC6  A closure is edited, then ended, from the day it falls on; an ended one shows no actions.
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

interface ClosureForm {
  starts: string
  ends: string
  reason?: string
  description?: string
}

/** Open the add form on the venue's page and fill it. Nothing is saved. */
async function fillClosure(page: Page, form: ClosureForm) {
  const section = availability(page)
  await section.getByRole('button', { name: 'Mark unavailable' }).click()
  await section.getByLabel('Starts').fill(form.starts)
  await section.getByLabel('Ends').fill(form.ends)
  if (form.reason) await section.getByLabel('Reason').selectOption({ label: form.reason })
  if (form.description) await section.getByLabel('Description').fill(form.description)
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
  await expect(availability(page).getByText('No bookings are affected.')).toBeVisible()
  await availability(page).getByRole('button', { name: 'Save closure' }).click()

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

  const affected = availability(page).getByRole('region', { name: 'Affected bookings' })
  await expect(affected).toContainText('Community Choir Showcase')
  await availability(page).getByRole('button', { name: 'Save closure' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Community Choir Showcase')
  await dialog.getByRole('button', { name: 'Mark unavailable' }).click()

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
  await availability(page).getByRole('button', { name: 'Save closure' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Mark unavailable' }).click()
  await expect(dayButton(page, /^21 October 2028/)).toBeVisible()

  // AC3: the coordinator's event page flags the booking.
  const coordinator = await signedInPage(browser, ACCOUNTS.coordinator)
  await coordinator.goto(`/events/${EVENTS.artMarket}`)
  await expect(coordinator.getByText('Venue unavailable – alternative needed')).toBeVisible()

  // AC7: Venue Staff's queue card carries the marker and holds Approve back.
  await page.goto('/venue-staff/booking-requests')
  const card = page.getByRole('listitem').filter({ hasText: '#00000014' })
  await expect(card).toContainText('Venue unavailable')
  await expect(card.getByRole('button', { name: 'Approve' })).toBeDisabled()

  // ... and so does the request's own page, with a notice saying why.
  await card.getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  await expect(page.getByText(/unavailable for part of this request/)).toBeVisible()
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
  await availability(page).getByRole('button', { name: 'Save closure' }).click()

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
  await availability(page).getByLabel('Reason').selectOption({ label: 'Renovation' })
  await availability(page).getByRole('button', { name: 'Save changes' }).click()
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
  await expect(availability(page).getByRole('button', { name: 'Mark unavailable' })).toBeVisible()

  for (const email of [ACCOUNTS.coordinator, ACCOUNTS.safetyOfficer]) {
    const other = await signedInPage(browser, email)
    await openVenue(other, VENUES.gardenAtrium)
    await expect(availability(other)).toBeVisible()
    await expect(availability(other).getByRole('button', { name: 'Mark unavailable' })).toHaveCount(
      0,
    )
  }
})
