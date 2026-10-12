/**
 * Story 12.7 - expire tentative venue holds.
 *
 * AC1  A pending request's hold expiry is on the event's booking list, Venue Staff's queue card,
 *      the request's own page and its calendar day, and Venue Staff can change it there.
 * AC3  An expired request leaves the Pending tab for its own Expired tab, with when it expired.
 * AC5  The Change expiry dialog refuses a time in the past, or one after the booked period
 *      starts, before anything is sent - and a blank reason (decided 12 Oct 2026, Q29).
 * AC6  An expired request covers no venue requirement: Find a venue is not greyed, and the
 *      catalogue's banner says the requirement needs a venue.
 * AC7  Venue Staff extend a hold, with a reason (decided 12 Oct 2026, Q27); the request's page
 *      and the coordinator's event page show the new expiry, who changed it and why. An expired
 *      hold is not revived: the coordinator requests the venue again.
 * AC8  The expired request stays in the event's booking list.
 * AC11 The venue the expired request held is found again for the same period.
 *
 * The rules - the default and its bounds, the warnings and the expiry itself, who may change an
 * expiry, the server's refusals and the approval racing the expiry - are backend cases:
 * backend/tests/bookings/test_hold_expiry.py. So is AC7's notice to the coordinator, since no page
 * lists the server's notifications until story 20.2.
 *
 * Seed (backend/db/seed/020_sample_data.sql), Chloe's and only used here: Community Craft Fair,
 * 12 Jul 2028 10:00-16:00, 120 people. Its one requirement, Craft hall (120, Exhibition, Wi-Fi),
 * had Exhibition Foyer requested on 28 Sep 2026; Venue Staff did not approve it, and it expired on
 * 5 Oct 2026 at 10:00. Its one test requests the foyer again, so it runs once, on its own.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const CRAFT_FAIR = { id: EVENTS.craftFair, name: 'Community Craft Fair' }
const CRAFT_HALL = 'Craft hall'
const CRAFT_HALL_ID = 'cccccccc-0000-0000-0034-000000000001'
const FOYER = 'Exhibition Foyer'
// The seeded request's expiry, as the pages write it (en-SG, Singapore time).
const EXPIRED_AT = 'Mon, 5 Oct 2026, 10:00'
// Why Venue Staff extend the Craft Fair's new hold (Q27), shown with who changed it (Q30).
const CHANGE_REASON = 'The makers confirm their stalls at the end of June.'
// Nimbus Developer Conference's breakout request (4444..02), pending, as its queue card shows it.
const NIMBUS_BREAKOUT_SHORT_ID = '00000002'
// Product Roadmap Townhall's Grand Hall request (4444..04), pending, read and never changed here:
// 15 Jan 2027, 10:00-12:00 with an hour of setup, so its booked period starts at 09:00.
const TOWNHALL_REQUEST_ID = '44444444-0000-0000-0000-000000000004'

function bookingList(page: Page) {
  return page.getByRole('region', { name: 'Venue booking' })
}

function holdBlock(page: Page) {
  return page.getByRole('region', { name: 'Hold expires' })
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

test('12.7 AC8/AC6/AC11/AC1/AC7: an expired request stays as history, and the venue is requested and held again', async ({
  page,
}) => {
  test.setTimeout(120_000)
  await signIn(page, ACCOUNTS.coordinator)
  await openEvent(page)

  // AC8: the expired request is in the event's history, saying when it expired.
  const bookings = bookingList(page)
  await expect(bookings).toContainText(FOYER)
  await expect(bookings).toContainText('Expired')
  await expect(bookings).toContainText(
    "This request's hold expired before Venue Staff approved it, so the venue was released.",
  )
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

  // AC1: one requirement, so the event's page opens: the new request shows when its hold
  // expires, and the expired one is still listed beneath it (AC8).
  await expect(page.getByRole('heading', { name: CRAFT_FAIR.name, level: 1 })).toBeVisible()
  await expect(bookings.getByText('Hold expires', { exact: true })).toBeVisible()
  await expect(bookings.getByText('Pending', { exact: true })).toBeVisible()
  await expect(bookings.getByText('Expired', { exact: true })).toBeVisible()

  // AC1: Venue Staff see the expiry on the request's page and on its day in the calendar.
  await signInAgain(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${request.id}`)
  await expect(holdBlock(page)).toBeVisible()
  await expect(page.getByRole('region', { name: 'Wed, 12 Jul 2028' })).toContainText('Hold expires')

  // AC7: they extend it, with a reason, and the page shows the new expiry, who changed it and
  // why (Q27, Q30).
  await holdBlock(page).getByRole('button', { name: 'Change expiry' }).click()
  await changeExpiryDialog(page).getByLabel('New expiry').fill('2028-07-01T09:00')
  await changeExpiryDialog(page).getByLabel('Reason').fill(CHANGE_REASON)
  await changeExpiryDialog(page).getByRole('button', { name: 'Save expiry' }).click()
  await expect(changeExpiryDialog(page)).toHaveCount(0)
  await expect(holdBlock(page)).toContainText('Sat, 1 Jul 2028, 09:00')
  await expect(holdBlock(page)).toContainText('Changed by Vera Venue')
  await expect(holdBlock(page)).toContainText(CHANGE_REASON)
  await expect(page.getByRole('region', { name: 'Wed, 12 Jul 2028' })).toContainText(
    'Hold expires Sat, 1 Jul 2028, 09:00',
  )

  // AC7: the coordinator's page shows the new expiry, who changed it and why, too.
  await signInAgain(page, ACCOUNTS.coordinator)
  await openEvent(page)
  await expect(bookings).toContainText('Sat, 1 Jul 2028, 09:00')
  await expect(bookings).toContainText('Changed by Vera Venue')
  await expect(bookings).toContainText(CHANGE_REASON)
})

test('12.7 AC3: an expired request is under Expired, saying when it expired, with nothing to decide', async ({
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

test('12.7 AC1: a pending request’s queue card shows when its hold expires', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: `#${NIMBUS_BREAKOUT_SHORT_ID}` })
  await expect(card.getByText('Hold expires', { exact: true })).toBeVisible()
})

test('12.7 AC5: an expiry in the past, or after the booked period starts, or a blank reason, is refused before it is sent', async ({
  page,
}) => {
  const sentChanges: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PATCH') sentChanges.push(request.url())
  })
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${TOWNHALL_REQUEST_ID}`)
  await holdBlock(page).getByRole('button', { name: 'Change expiry' }).click()
  const dialog = changeExpiryDialog(page)
  const newExpiry = dialog.getByLabel('New expiry')
  const save = dialog.getByRole('button', { name: 'Save expiry' })

  await newExpiry.fill('')
  await save.click()
  await expect(dialog.getByRole('alert')).toHaveText('Choose when the hold should expire.')

  await newExpiry.fill('2025-01-01T09:00')
  await save.click()
  await expect(dialog.getByRole('alert')).toHaveText('The hold must expire in the future.')

  // The booked period starts at 09:00, an hour of setup before the 10:00 townhall.
  await newExpiry.fill('2027-01-15T09:01')
  await save.click()
  await expect(dialog.getByRole('alert')).toHaveText(
    'The hold must expire by the start of the booked period.',
  )

  // Q29: a sound expiry still needs a reason, and spaces are no reason.
  await newExpiry.fill('2027-01-14T09:00')
  await dialog.getByLabel('Reason').fill('   ')
  await save.click()
  await expect(dialog.getByRole('alert')).toHaveText('Give a reason for the new expiry.')

  expect(sentChanges).toEqual([])
})
