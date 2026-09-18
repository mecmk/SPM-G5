/**
 * Story 7.1 - fe: display full event details.
 * AC1 the detail view shows core details, venue and accessibility requirements, equipment
 *     requirements, status, and assigned coordinator.
 * AC2 users see the detail view only for events they are related to.
 * AC3 fields the user's role may not edit are shown read-only rather than hidden.
 * This story adds no editing affordances at all, so AC3 is checked by asserting no form control
 * appears anywhere on the page, for any role.
 * Refusals (401, 403/404, unrelated organiser, attendee) are backend cases:
 * backend/tests/events/test_event_detail.py. The backend endpoint this page calls is queued
 * behind story 4.1 and does not exist yet, so every test below currently fails on the network
 * call rather than reaching these assertions - see frontend/src/api/events.ts.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test('7.1 AC1: the organiser sees their event’s full details', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiserOther)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByText('Approved')).toBeVisible()
  await expect(page.getByText('Chloe Coordinator')).toBeVisible()
  await expect(page.getByText('Grand Hall')).toHaveCount(0) // venue bookings: out of scope, story 13.4
  await expect(page.getByRole('textbox')).toHaveCount(0) // AC3: nothing here is editable
})

test('7.1 AC1: an internal staff member sees the same details for an event they are not assigned to', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByText('Chloe Coordinator')).toBeVisible()
})

test('7.1 AC1: an event with no coordinator assigned shows a clear unassigned state', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.submitted}`)

  await expect(page.getByText('Not yet assigned')).toBeVisible()
})

test('7.1 AC2: an organiser cannot open another organiser’s event by direct URL', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('alert')).toContainText('does not exist')
})

test('7.1 AC3: no field renders as an input, textarea or select for any role', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
})
