/**
 * Story 12.1 - fe/be: raise venue booking request.
 *
 * AC1 A request can be raised only from an approved event and against one venue.
 * AC2 The request carries the event's date, start and end times, expected attendance, required
 *     layout, and required facilities.
 * AC3 On submission the request appears in the Venue Staff pending queue with a pending status.
 * AC4 Only the assigned coordinator for that event can raise the request.
 *
 * What is proven here is the flow a coordinator clicks through. The rules themselves - every
 * refused event status, the 403 for a coordinator who is not the assigned one, the 404s, the
 * fields copied onto the row - are `backend/tests/bookings/test_raise_booking_request.py` and
 * `test_bookable_events.py`, which are faster and deterministic, and are not repeated here.
 *
 * AC3 stops where this story's UI stops: the request is shown as pending once sent. The pending
 * *queue* is story 13.1, which depends on this story and has no page yet, and a booking record
 * page is story 13.x - so there is nothing further to click to. That Venue Staff can read the
 * row is proven at the API in `test_raise_booking_request.py`.
 *
 * Seed data this leans on (backend/db/seed/020_sample_data.sql): Chloe Coordinator is assigned
 * five events but only one of them, Nimbus Developer Conference, is APPROVED. Carl Coordinator is
 * assigned only a REJECTED one, which is what makes the empty state reachable without fixtures.
 */

import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

const REQUEST_PATH = '/bookings/new'
const APPROVED_EVENT = 'Nimbus Developer Conference'
const VENUE = 'Seminar Room 2.1'

/** The sidebar. Its links share their names with the home page's tiles, which are built from
 * the same list, so nav assertions scope to it - as `rbac.spec.ts` does. */
function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

/** Open the request form the way a coordinator does: from the sidebar. */
async function openRequestForm(page: Page) {
  await page.goto('/')
  await mainNav(page).getByRole('link', { name: 'Request a venue', exact: true }).click()
  await expect(page).toHaveURL(REQUEST_PATH)
}

test('12.1 AC1/AC2/AC3: a coordinator raises a venue booking request for their approved event', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestForm(page)

  await page.getByLabel('Event').selectOption({ label: APPROVED_EVENT })
  await page.getByLabel('Venue').selectOption({ label: VENUE })

  // AC2: the form states what it will carry over from the event, so the coordinator can see the
  // period, attendance, layout and facilities are the event's and not theirs to choose.
  const summary = page.getByRole('region', {
    name: 'What this request will carry',
  })
  await expect(summary).toContainText('350')
  await expect(summary).toContainText('Theatre')
  await expect(summary).toContainText('Projector & screen')

  await page.getByRole('button', { name: 'Send request' }).click()

  // AC3: the outcome names the venue and shows the request waiting for Venue Staff.
  const outcome = page.getByRole('region', { name: 'Request sent' })
  await expect(outcome).toBeVisible()
  await expect(outcome).toContainText(VENUE)
  await expect(outcome).toContainText('Pending')
})

test('12.1 AC1: the form offers only events that may raise a booking', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestForm(page)

  const picker = page.getByLabel('Event')

  // The positive assertion goes first on purpose: it is the one that waits for the pick-list to
  // arrive, so the absences below cannot pass against a picker that is simply still empty.
  await expect(picker).toContainText(APPROVED_EVENT)
  // All three are assigned to this same coordinator but still awaiting a decision, so AC1 keeps
  // them out - the picker cannot offer a choice `POST /bookings` would refuse.
  await expect(picker).not.toContainText('Data Literacy Workshop')
  await expect(picker).not.toContainText('Nimbus Leadership Offsite')
  await expect(picker).not.toContainText('Diversity & Inclusion Forum')
})

test('12.1 AC4: a coordinator with no approved events has nothing to request for', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await openRequestForm(page)

  await expect(page.getByText('No approved events are assigned to you yet.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send request' })).toBeHidden()
})

test('12.1 AC4: Venue Staff are not offered a way to raise a request', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/')

  await expect(
    mainNav(page).getByRole('link', { name: 'Request a venue', exact: true }),
  ).toHaveCount(0)
})
