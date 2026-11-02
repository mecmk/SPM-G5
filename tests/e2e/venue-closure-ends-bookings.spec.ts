/**
 * Story 9.5 - end the bookings a venue closure covers. The backlog's ACs, as the flow shows them:
 *
 * AC1 Before saving a closure (9.4 AC1), Venue Staff see every pending request and approved
 *     booking it covers, each with its event and status, and are told that saving rejects each
 *     pending request and cancels each approved booking. Closing the confirmation saves nothing.
 * AC2 Saving rejects each pending request and cancels each approved booking, with the closure's
 *     reason and description. A cancelled booking shows on the event's booking list and in the
 *     Venue Staff queue's Cancelled tab as cancelled because the venue closed, with the reason; a
 *     rejected request shows in the Rejected tab with the same reason.
 * AC3 Each venue requirement that lost its booking shows "Needs a venue" again (12.5). An event
 *     that was Confirmed goes back to Planning.
 * AC7 Nothing is marked "Venue unavailable – alternative needed" any more: no Find a replacement
 *     venue, no Venue unavailable tab in the coordinator's Events inbox. A booking already
 *     replaced keeps showing "Replaced by <venue>".
 *
 * AC4-AC6 and AC8-AC10 (who is told, what a closure touches, what is never restored, the
 * migration, permissions, races) are backend cases: backend/tests/venues/test_closure_ends_bookings.py.
 *
 * Seed (backend/db/seed/020_sample_data.sql, the story's 0095NN block), dedicated to this spec:
 * Seminar Room 2.1 on 12 June 2029 holds the Alumni Networking Brunch's approved booking
 * (09:00-12:00, a Confirmed event) and the Partner Workshop Afternoon's pending request
 * (14:00-17:00, a Planning event). The Product Forum's original booking at Grand Hall was
 * released when its replacement at Seminar Room 2.1 was approved. The tests run in order on that
 * state and the first one ends the two bookings for good: a retry would only fail on the closure
 * it already saved and hide the first trace, so the group is serial with no retries.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, VENUES, signIn, uniqueName, venueCard } from './support'

test.describe.configure({ mode: 'serial', retries: 0 })
test.use({ timezoneId: 'Asia/Singapore' })

const PINNED_NOW = new Date('2029-06-01T10:00:00+08:00')
const PHONE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 720 }

const CONFIRMED_EVENT = 'Alumni Networking Brunch'
const PLANNING_EVENT = 'Partner Workshop Afternoon'
const REPLACED_EVENT = 'Product Forum'
const DESCRIPTION = uniqueName('Hall floor repair')

const DIALOG_TEXT =
  'Saving this closure rejects each pending request and cancels each approved booking listed.'
const CANCELLED_LINE = 'Cancelled: the venue closed'
const REASON_LINE = 'Reason: Maintenance'
const REJECTED_REASON = 'Venue closed: Maintenance'

function blockOff(page: Page) {
  const name = /^(Block off time|Edit blocked-off time)$/
  return page.getByRole('region', { name }).or(page.getByRole('group', { name }))
}

/** The "Availability" card: a fieldset, which is a group, on the Edit venue page. */
function availability(page: Page) {
  return page
    .getByRole('region', { name: 'Availability', exact: true })
    .or(page.getByRole('group', { name: 'Availability', exact: true }))
}

/** The "Block off time" card, as it is when closed, holding the button that opens the add form. */
function blockOffCard(page: Page) {
  return page
    .getByRole('region', { name: 'Block off time', exact: true })
    .or(page.getByRole('group', { name: 'Block off time', exact: true }))
}

/** Venue Staff's way to the controls: the venue's Edit venue page, from its card. */
async function openVenue(page: Page) {
  await page.goto('/venues')
  await venueCard(page, VENUES.seminarRoom).getByRole('link', { name: 'Edit' }).click()
  await expect(availability(page)).toBeVisible()
  await expect(page.getByText('Loading availability…')).toHaveCount(0)
}

/** Open the add form and fill a closure over the whole of 12 June, then wait for its list. */
async function fillClosure(page: Page) {
  const card = blockOffCard(page)
  await card.getByRole('button', { name: 'Block off time' }).click()
  await card.getByLabel('Starts').fill('2029-06-12T08:00')
  await card.getByLabel('Ends').fill('2029-06-12T18:00')
  await card.getByLabel('Reason').selectOption({ label: 'Maintenance' })
  await card.getByLabel('Description').fill(DESCRIPTION)
  await expect(blockOff(page).getByRole('region', { name: 'Affected bookings' })).toContainText(
    PLANNING_EVENT,
  )
}

async function openConfirmation(page: Page) {
  const save = blockOff(page).getByRole('button', { name: 'Save closure' })
  await expect(save).toBeEnabled()
  await save.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(DIALOG_TEXT)
  return dialog
}

function section(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true })
}

/** Venue Staff's queue on a tab, found with the search box rather than by paging. */
async function queueTab(page: Page, tab: RegExp, search: string) {
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('tab', { name: tab }).click()
  await page.getByRole('searchbox', { name: 'Search requests' }).fill(search)
  return page.getByRole('main').getByRole('listitem').filter({ hasText: search })
}

test('9.5 AC1: the confirmation lists what the closure ends, Go back saves nothing, and confirming saves', async ({
  page,
}) => {
  await page.clock.setFixedTime(PINNED_NOW)
  await signIn(page, ACCOUNTS.venueStaff)

  // At the phone's size: the list, in the dialog, and Go back.
  await page.setViewportSize(PHONE)
  await openVenue(page)
  await fillClosure(page)
  let dialog = await openConfirmation(page)
  const approved = dialog.getByRole('listitem').filter({ hasText: CONFIRMED_EVENT })
  const pending = dialog.getByRole('listitem').filter({ hasText: PLANNING_EVENT })
  await expect(approved).toContainText('Approved')
  await expect(pending).toContainText('Pending')
  await dialog.getByRole('button', { name: 'Go back' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: /^12 June 2029/ }).click()
  await expect(page.getByRole('region', { name: /12 Jun 2029/ })).not.toContainText('Unavailable')

  // At the desktop's: confirming saves, and the calendar shows the closure.
  await page.setViewportSize(DESKTOP)
  dialog = await openConfirmation(page)
  const landed = page.waitForResponse(
    (response) =>
      /\/unavailability$/.test(new URL(response.url()).pathname) &&
      response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: 'Save and end these bookings' }).click()
  expect((await landed).ok()).toBe(true)
  await page.getByRole('button', { name: /^12 June 2029/ }).click()
  await expect(page.getByRole('region', { name: /12 Jun 2029/ })).toContainText(
    'Unavailable – Maintenance',
  )
})

test("9.5 AC2: the Cancelled tab, the Rejected tab and the coordinator's event page show how each booking ended", async ({
  page,
  browser,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)

  const cancelled = await queueTab(page, /^Cancelled/, CONFIRMED_EVENT)
  await expect(cancelled).toContainText(CANCELLED_LINE)
  await expect(cancelled).toContainText(REASON_LINE)
  await expect(cancelled).toContainText(DESCRIPTION)

  const rejected = await queueTab(page, /^Rejected/, PLANNING_EVENT)
  await expect(rejected).toContainText(REJECTED_REASON)

  const context = await browser.newContext()
  const coordinator = await context.newPage()
  await signIn(coordinator, ACCOUNTS.coordinator)
  await coordinator.goto(`/events/${EVENTS.closureConfirmed}`)
  const booking = section(coordinator, 'Venue booking')
  await expect(booking.getByText(CANCELLED_LINE, { exact: true })).toBeVisible()
  await expect(booking.getByText(REASON_LINE, { exact: true })).toBeVisible()
  await expect(booking).toContainText(DESCRIPTION)
  await coordinator.goto(`/events/${EVENTS.closurePlanning}`)
  const request = section(coordinator, 'Venue booking')
  await expect(request).toContainText('Rejected')
  await expect(request).toContainText(REJECTED_REASON)
  await context.close()
})

test('9.5 AC3: the Confirmed event is back in Planning, and its requirement needs a venue again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.closureConfirmed}`)

  await expect(page.getByRole('heading', { level: 1, name: CONFIRMED_EVENT })).toBeVisible()
  await expect(page.getByText('Planning', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Confirmed', { exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  const main = page
    .getByRole('region', { name: `Finding a venue for ${CONFIRMED_EVENT}` })
    .getByRole('listitem')
    .filter({ hasText: 'Main hall' })
  await expect(main).toContainText('Needs a venue')
})

test('9.5 AC7: no replacement is offered, the inbox has no Venue unavailable tab, and a replaced booking still says so', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto(`/events/${EVENTS.closureConfirmed}`)
  await expect(page.getByRole('heading', { level: 1, name: CONFIRMED_EVENT })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Find a replacement venue' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Find a replacement venue' })).toHaveCount(0)

  await page.goto('/events/inbox')
  await expect(page.getByRole('heading', { name: 'Events inbox' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /^Under Review/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /^Venue unavailable/ })).toHaveCount(0)

  await page.goto(`/events/${EVENTS.closureReplaced}`)
  await expect(page.getByRole('heading', { level: 1, name: REPLACED_EVENT })).toBeVisible()
  const bookings = section(page, 'Venue booking')
  await expect(bookings).toContainText(`Replaced by ${VENUES.seminarRoom}`)
  await expect(bookings).toContainText(`Replaces ${VENUES.grandHall}`)
})
