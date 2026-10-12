/**
 * Story 12.7 - expire tentative venue holds, as the customer has them (constitution s12.7, the
 * rework of 12 Oct 2026): the hold is an approved booking waiting for its event to be confirmed,
 * and Venue Staff set its expiry as they approve. A pending request has none.
 *
 * AC1  Venue Staff give the hold its expiry in the Approve dialog; it is on the request's own
 *      page, its day in the calendar, Venue Staff's queue card and the event's booking list. A
 *      pending request shows no expiry.
 * AC3  An expired booking is under its own Expired tab, with when it expired.
 * AC5  The Approve dialog refuses no expiry, a time in the past, or one after the booked period
 *      starts, before anything is sent; the Change expiry dialog refuses a blank reason (Q29).
 * AC6  An expired booking covers no venue requirement: Find a venue is not greyed, and the
 *      catalogue's banner says the requirement needs a venue.
 * AC7  Venue Staff change the expiry, with a reason (Q27); the request's page and the
 *      coordinator's event page show the new expiry, who changed it and why. An expired hold is
 *      not revived: the coordinator requests the venue again.
 * AC8  The expired booking stays in the event's booking list.
 * AC11 The venue the expired booking held is found again for the same period.
 *
 * The rules - the expiry's bounds, the warnings and the expiry itself, the event's confirmation
 * completing a hold, who may change an expiry, the server's refusals and the confirmation racing
 * the expiry - are backend cases: backend/tests/bookings/test_hold_expiry.py. So is AC7's notice
 * to the coordinator, since no page lists the server's notifications until story 20.2.
 *
 * Seed (backend/db/seed/020_sample_data.sql), Chloe's and only used here: Community Craft Fair,
 * 12 Jul 2028 10:00-16:00, 120 people. Its one requirement, Craft hall (120, Exhibition, Wi-Fi),
 * had Exhibition Foyer approved on 29 Sep 2026 with a hold until 5 Oct 2026 at 10:00; the event
 * was not confirmed by then, so the hold expired. Its one test requests the foyer again, so it
 * runs once, on its own. The other tests only read the seed, or open a dialog and cancel it.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const CRAFT_FAIR = { id: EVENTS.craftFair, name: 'Community Craft Fair' }
const CRAFT_HALL = 'Craft hall'
const CRAFT_HALL_ID = 'cccccccc-0000-0000-0034-000000000001'
const FOYER = 'Exhibition Foyer'
// The seeded booking's approval and expiry, as the pages write them (en-SG, Singapore time).
const APPROVED_AT = 'Tue, 29 Sept 2026, 10:00'
const EXPIRED_AT = 'Mon, 5 Oct 2026, 10:00'
// The hold Venue Staff give the Craft Fair's new request, then the one they change it to, with
// why (Q27), shown with who changed it (Q30).
const HOLD_UNTIL = { input: '2028-06-30T17:00', shown: 'Fri, 30 Jun 2028, 17:00' }
const CHANGED_TO = { input: '2028-07-01T09:00', shown: 'Sat, 1 Jul 2028, 09:00' }
const CHANGE_REASON = 'The makers confirm their stalls at the end of June.'
// Coastal Resilience Workshop's Seminar Room 2.1 booking (4444..09), approved in the seed with a
// hold until its booked start, 6 Jun 2028 at 09:00. Read and never changed here.
const WORKSHOP = { name: 'Coastal Resilience Workshop', heldUntil: 'Tue, 6 Jun 2028, 09:00' }
const WORKSHOP_BOOKING_ID = '44444444-0000-0000-0000-000000000009'
// Product Roadmap Townhall's Grand Hall request (4444..04), pending, read and never changed here:
// 15 Jan 2027, 10:00-12:00 with an hour of setup, so its booked period starts at 09:00.
const TOWNHALL_REQUEST_ID = '44444444-0000-0000-0000-000000000004'

function bookingList(page: Page) {
  return page.getByRole('region', { name: 'Venue booking' })
}

function holdBlock(page: Page) {
  return page.getByRole('region', { name: 'Hold expires' })
}

function approveDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Approve this booking?' })
}

function changeExpiryDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Change when this hold expires' })
}

async function signInAgain(page: Page, email: string) {
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, email)
}

async function openEvent(page: Page) {
  await page.goto(`/events/${CRAFT_FAIR.id}`)
  await expect(page.getByRole('heading', { name: CRAFT_FAIR.name, level: 1 })).toBeVisible()
}

test('12.7 AC8/AC6/AC11/AC1/AC7: an expired booking stays as history, and the venue is requested, approved and held again', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page)

  // AC8: the expired booking is in the event's history, with when it was approved and expired.
  const bookings = bookingList(page)
  await expect(bookings).toContainText(FOYER)
  await expect(bookings).toContainText(
    "This booking's hold expired before the event was confirmed, so the venue was released.",
  )
  await expect(bookings.getByText('Approved at', { exact: true })).toBeVisible()
  await expect(bookings).toContainText(APPROVED_AT)
  await expect(bookings.getByText('Expired at', { exact: true })).toBeVisible()
  await expect(bookings).toContainText(EXPIRED_AT)

  // AC6: it covers nothing, so Find a venue keeps its normal look and selects the Craft hall,
  // the event's one requirement, which the banner shows on its own as needing a venue.
  await expect(page.getByText('All required venues booked')).toHaveCount(0)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(page).toHaveURL(new RegExp(`[?&]requirement=${CRAFT_HALL_ID}(&|$)`))
  const craftHall = page
    .getByRole('region', { name: `Finding a venue for ${CRAFT_FAIR.name}` })
    .getByRole('listitem')
    .filter({ hasText: CRAFT_HALL })
  await expect(craftHall).toContainText('Needs a venue')

  // AC11: the foyer it held is free again for the same period, so it can be requested again.
  await venueCard(page, FOYER).getByRole('link', { name: 'Request this venue' }).click()
  await expect(page.getByRole('heading', { name: `Request ${FOYER}`, level: 1 })).toBeVisible()
  const sent = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === '/bookings',
  )
  await page.getByRole('button', { name: 'Send request' }).click()
  const request = await (await sent).json()

  // AC1: one requirement, so the event's page opens: the new request is pending, with no hold
  // yet, and the expired booking is still listed beneath it (AC8).
  await expect(page.getByRole('heading', { name: CRAFT_FAIR.name, level: 1 })).toBeVisible()
  await expect(bookings.getByText('Pending', { exact: true })).toBeVisible()
  await expect(bookings.getByText('Expired', { exact: true })).toBeVisible()
  await expect(bookings.getByText('Hold expires', { exact: true })).toHaveCount(0)

  // AC1: Venue Staff approve it, giving the hold its expiry, and see it on the request's page
  // and on its day in the calendar.
  await signInAgain(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${request.id}`)
  await expect(page.getByRole('heading', { name: CRAFT_FAIR.name, level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()
  await approveDialog(page).getByLabel('Hold expires').fill(HOLD_UNTIL.input)
  await approveDialog(page).getByRole('button', { name: 'Approve' }).click()
  await expect(approveDialog(page)).toHaveCount(0)
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
  await expect(holdBlock(page)).toContainText(HOLD_UNTIL.shown)
  await expect(page.getByRole('region', { name: 'Wed, 12 Jul 2028' })).toContainText(
    `Hold expires ${HOLD_UNTIL.shown}`,
  )

  // AC7: they change it, with a reason, and the page shows the new expiry, who changed it and
  // why (Q27, Q30).
  await holdBlock(page).getByRole('button', { name: 'Change expiry' }).click()
  await changeExpiryDialog(page).getByLabel('New expiry').fill(CHANGED_TO.input)
  await changeExpiryDialog(page).getByLabel('Reason').fill(CHANGE_REASON)
  await changeExpiryDialog(page).getByRole('button', { name: 'Save expiry' }).click()
  await expect(changeExpiryDialog(page)).toHaveCount(0)
  await expect(holdBlock(page)).toContainText(CHANGED_TO.shown)
  await expect(holdBlock(page)).toContainText('Changed by Vera Venue')
  await expect(holdBlock(page)).toContainText(CHANGE_REASON)
  await expect(page.getByRole('region', { name: 'Wed, 12 Jul 2028' })).toContainText(
    `Hold expires ${CHANGED_TO.shown}`,
  )

  // AC1/AC7: the coordinator's page shows the booking's hold, who changed it and why.
  await signInAgain(page, ACCOUNTS.coordinator)
  await openEvent(page)
  await expect(bookings.getByText('Hold expires', { exact: true })).toBeVisible()
  await expect(bookings).toContainText(CHANGED_TO.shown)
  await expect(bookings).toContainText('Changed by Vera Venue')
  await expect(bookings).toContainText(CHANGE_REASON)
})

test('12.7 AC3: an expired booking is under Expired, saying when it expired, with nothing to decide', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('tab', { name: /^Expired/ }).click()

  const card = page.getByRole('listitem').filter({ hasText: CRAFT_FAIR.name })
  await expect(card).toContainText(FOYER)
  await expect(card).toContainText('Expired')
  await expect(card.getByText('Expired at', { exact: true })).toBeVisible()
  await expect(card).toContainText(EXPIRED_AT)
  await expect(card.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Reject' })).toHaveCount(0)
})

test('12.7 AC1: an approved booking’s queue card shows when its hold expires', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('tab', { name: /^Approved/ }).click()

  const card = page.getByRole('listitem').filter({ hasText: WORKSHOP.name })
  await expect(card.getByText('Hold expires', { exact: true })).toBeVisible()
  await expect(card).toContainText(WORKSHOP.heldUntil)
})

test('12.7 AC5/AC7: no expiry, one in the past or after the booked period starts, or a blank reason, is refused before it is sent', async ({
  page,
}) => {
  const sent: string[] = []
  page.on('request', (request) => {
    const isWrite = request.method() === 'POST' || request.method() === 'PATCH'
    if (isWrite && new URL(request.url()).pathname.startsWith('/bookings/')) {
      sent.push(`${request.method()} ${request.url()}`)
    }
  })
  await signIn(page, ACCOUNTS.venueStaff)

  // AC1/AC5: the Approve dialog asks for the expiry, with no default.
  await page.goto(`/venue-staff/booking-requests/${TOWNHALL_REQUEST_ID}`)
  await page.getByRole('button', { name: 'Approve' }).click()
  const approving = approveDialog(page)
  const holdExpires = approving.getByLabel('Hold expires')
  const approve = approving.getByRole('button', { name: 'Approve' })
  await expect(holdExpires).toHaveValue('')

  await approve.click()
  await expect(approving.getByRole('alert')).toHaveText('Choose when the hold should expire.')

  await holdExpires.fill('2025-01-01T09:00')
  await approve.click()
  await expect(approving.getByRole('alert')).toHaveText('The hold must expire in the future.')

  // The booked period starts at 09:00, an hour of setup before the 10:00 townhall.
  await holdExpires.fill('2027-01-15T09:01')
  await approve.click()
  await expect(approving.getByRole('alert')).toHaveText(
    'The hold must expire by the start of the booked period.',
  )
  await approving.getByRole('button', { name: 'Cancel' }).click()

  // AC7, Q29: a new expiry needs a reason, and spaces are no reason.
  await page.goto(`/venue-staff/booking-requests/${WORKSHOP_BOOKING_ID}`)
  await holdBlock(page).getByRole('button', { name: 'Change expiry' }).click()
  const changing = changeExpiryDialog(page)
  await changing.getByLabel('New expiry').fill('2028-06-01T09:00')
  await changing.getByLabel('Reason').fill('   ')
  await changing.getByRole('button', { name: 'Save expiry' }).click()
  await expect(changing.getByRole('alert')).toHaveText('Give a reason for the new expiry.')
  await changing.getByRole('button', { name: 'Cancel' }).click()

  expect(sent).toEqual([])
})
