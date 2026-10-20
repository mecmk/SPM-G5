/**
 * Story 6.2 - cancel an event and release held resources.
 *
 * AC1  The Event Organiser can cancel their own event from the Event Details page by selecting
 *      Cancel Event, entering a cancellation reason and confirming the action. The event's status
 *      changes to Cancelled.
 * AC4  All pending venue booking requests, open equipment requests, pending event change requests
 *      and attendee registrations are closed. Their records remain available for reference.
 * AC6  Cancellation is permitted while an event is Under Review, Clarification Requested,
 *      Planning, Awaiting Safety Check or Confirmed. Draft, Completed, Cancelled and Rejected
 *      events cannot be cancelled.
 * AC7  A cancellation reason is mandatory. An empty or whitespace-only reason is refused. Closing
 *      the confirmation dialog leaves the event unchanged.
 * AC11 Only the Event Organiser who owns the event can cancel it. Other users, including Event
 *      Coordinators, cannot cancel the event. Unauthorised API requests are refused.
 * AC14 Venue Staff see the cancelled event's venue bookings under a read-only Cancelled tab in
 *      their booking queue, and under All. No Approve or Reject is offered.
 * AC15 Technical Support see the cancelled event's equipment requests that had been sent to them
 *      under a read-only Cancelled tab in their equipment queue, and under All. Requests never
 *      sent to them are not shown. No Accept or Decline is offered. This replaces 15.2 AC5 for
 *      cancelled events; equipment on rejected events still leaves the queue.
 * AC16 A cancelled venue booking or equipment request shows when it was cancelled, alongside (not
 *      instead of) when it was approved. On the event page, the coordinator sees "This booking
 *      was cancelled with its event."
 *
 * This spec covers the parts of those a user clicks through: the dialog and the cancelled page
 * (AC1, AC4's change request, AC5's display, AC6, AC7, AC11's button), and what each role then
 * sees (AC14-AC16).
 *
 * What is released or closed (AC2-AC4), who is told (AC5), every status rule (AC6), the server's
 * refusals (AC7, AC11), the transaction and race cases (AC10, AC12, AC13), what each queue lists
 * and counts (AC14, AC15) and the time recorded (AC16) are backend cases:
 * backend/tests/cancellations/test_cancel_event.py.
 *
 * Each cancelling test raises and submits a fresh request of its own, since a cancellation cannot
 * be undone; the cancelled and planning events it reads are seeded and never changed. The AC14-AC16
 * test cancels the seeded Lakeside Charity Run, which holds a booking and an equipment request.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  approvedEvent,
  changeRequests,
  createAndSubmitRequest,
  EVENTS,
  signIn,
  uniqueName,
} from './support'

const REASON = 'Our sponsor withdrew the budget.'
// The seeded cancellation of the Summer Rooftop Mixer (backend/db/seed/020_sample_data.sql).
const SEEDED_REASON = 'The rooftop terrace is closed for repairs that week.'

const CHARITY_RUN = 'Lakeside Charity Run'
// The charity run's approved Sunrise Studio booking and its wireless microphones
// (backend/db/seed/020_sample_data.sql), cancelled with it; and its Harbour Pavilion booking, which
// an earlier change cancelled.
const CHARITY_RUN_STUDIO_BOOKING = '44444444-0000-0000-0000-000000000062'
const CHARITY_RUN_MICROPHONES = '66666666-0000-0000-0000-000000000062'

function cancelDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Cancel this event?' })
}

test('6.2 AC1: the organiser cancels their own event with a reason', async ({ page }) => {
  const name = uniqueName('Cancelled social')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)
  await page.goto(`/events/${eventId}`)

  await page.getByRole('button', { name: 'Cancel event' }).click()
  await cancelDialog(page).getByLabel('Reason for cancelling').fill(REASON)
  await cancelDialog(page).getByRole('button', { name: 'Cancel event' }).click()

  await expect(cancelDialog(page)).toHaveCount(0)
  const cancellation = page.getByRole('region', { name: 'Cancellation' })
  await expect(cancellation.getByText('Cancelled by', { exact: true })).toBeVisible()
  await expect(cancellation).toContainText('Olivia Organiser')
  await expect(cancellation).toContainText(REASON)
  await expect(page.getByText('Cancelled', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)

  await page.goto('/events/mine')
  await expect(page.getByText(name)).toBeVisible()
})

test('6.2 AC4: a pending change request reads Cancelled once its event is cancelled', async ({
  page,
}) => {
  await approvedEvent(page, 'Cancelled with a change')
  await changeRequests(page).getByRole('button', { name: 'Request a change' }).click()
  await changeRequests(page)
    .getByLabel('What to change')
    .selectOption({ label: 'Expected attendance' })
  await changeRequests(page).getByLabel('New expected attendance').fill('150')
  await changeRequests(page).getByLabel('Reason for the change').fill('More guests confirmed.')
  await changeRequests(page).getByRole('button', { name: 'Send change request' }).click()
  const raised = changeRequests(page)
    .getByRole('listitem')
    .filter({ hasText: 'Expected attendance' })
  await expect(raised).toContainText('Pending')

  await page.getByRole('button', { name: 'Cancel event' }).click()
  await cancelDialog(page).getByLabel('Reason for cancelling').fill(REASON)
  await cancelDialog(page).getByRole('button', { name: 'Cancel event' }).click()
  await expect(page.getByRole('region', { name: 'Cancellation' })).toBeVisible()

  await expect(raised).toContainText('Cancelled')
  await expect(raised.getByRole('button', { name: 'Withdraw request' })).toHaveCount(0)
})

test('6.2 AC7: a blank reason is not sent, and closing the dialog keeps the event', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, uniqueName('Kept social'))
  await page.goto(`/events/${eventId}`)
  let cancelCalls = 0
  page.on('request', (request) => {
    if (request.url().endsWith(`/events/${eventId}/cancel`)) cancelCalls += 1
  })

  await page.getByRole('button', { name: 'Cancel event' }).click()
  await cancelDialog(page).getByLabel('Reason for cancelling').fill('   ')
  await cancelDialog(page).getByRole('button', { name: 'Cancel event' }).click()
  await expect(cancelDialog(page).getByRole('alert')).toHaveText(
    'Enter a reason for cancelling this event.',
  )

  await cancelDialog(page).getByRole('button', { name: 'Keep event' }).click()
  await expect(cancelDialog(page)).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Cancellation' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Cancel event' })).toBeVisible()
  expect(cancelCalls).toBe(0)
})

test('6.2 AC6: a cancelled event shows why, and offers no Cancel event', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.cancelled}`)

  const cancellation = page.getByRole('region', { name: 'Cancellation' })
  await expect(cancellation.getByText('Cancelled by', { exact: true })).toBeVisible()
  await expect(cancellation).toContainText('Omar Organiser')
  await expect(cancellation).toContainText(SEEDED_REASON)
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)
})

test('6.2 AC11: a coordinator is not offered Cancel event', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.planning}`)

  await expect(page.getByRole('heading', { name: 'Regional Sales Summit' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)
})

test('6.2 AC14/AC15/AC16: Venue Staff and Technical Support find what was released under Cancelled', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.charityRun}`)
  await page.getByRole('button', { name: 'Cancel event' }).click()
  await cancelDialog(page).getByLabel('Reason for cancelling').fill(REASON)
  await cancelDialog(page).getByRole('button', { name: 'Cancel event' }).click()
  await expect(page.getByRole('region', { name: 'Cancellation' })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()

  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('tab', { name: /^Cancelled/ }).click()
  const booking = page
    .getByRole('listitem')
    .filter({ hasText: CHARITY_RUN })
    .filter({ hasText: 'Sunrise Studio' })
  await expect(booking.getByRole('heading', { name: CHARITY_RUN })).toBeVisible()
  await expect(booking.getByText('Approved at', { exact: true })).toBeVisible()
  await expect(booking.getByText('Cancelled at', { exact: true })).toBeVisible()
  await expect(booking.getByRole('button')).toHaveCount(0)
  await page.goto(`/venue-staff/booking-requests/${CHARITY_RUN_STUDIO_BOOKING}`)
  await expect(page.getByText('Approved at', { exact: true })).toBeVisible()
  await expect(page.getByText('Cancelled at', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Sign out' }).click()

  await signIn(page, ACCOUNTS.techSupport)
  await page.goto('/equipment/requests')
  await page.getByRole('tab', { name: /^Cancelled/ }).click()
  const item = page.getByRole('listitem').filter({ hasText: CHARITY_RUN })
  await expect(item.getByRole('heading', { name: CHARITY_RUN })).toBeVisible()
  await expect(item).toContainText('Wireless microphone')
  await expect(item.getByText('Cancelled at', { exact: true })).toBeVisible()
  await expect(item.getByText('Available', { exact: true })).toHaveCount(0)
  await expect(item.getByRole('button')).toHaveCount(0)
  await page.goto(`/equipment/requests/${CHARITY_RUN_MICROPHONES}`)
  await expect(page.getByText('Cancelled at', { exact: true })).toBeVisible()
  await expect(page.getByText('Available', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Accept' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Sign out' }).click()

  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.charityRun}`)
  const bookingSection = page.getByRole('region', { name: 'Venue booking' })
  // Only the Sunrise Studio booking went with the event; an earlier change cancelled the other.
  await expect(bookingSection.getByText('This booking was cancelled with its event.')).toHaveCount(
    1,
  )
  await expect(bookingSection.getByText('Cancelled at', { exact: true })).toHaveCount(2)
  // 4.6's decision reads as the approval it was, not the Cancelled the page states above it.
  const clarifications = page.getByRole('region', { name: 'Clarifications' })
  await expect(clarifications.getByText('Approved', { exact: true })).toBeVisible()
})
