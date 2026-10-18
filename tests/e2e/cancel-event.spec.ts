/**
 * Story 6.2 - cancel an event and release held resources.
 *
 * AC1  the organiser cancels their own event from its details page with a reason; the page then
 *      shows it Cancelled, with who cancelled it and why (AC5), and it stays in their events (AC9).
 * AC6  a cancelled event offers no Cancel event button.
 * AC7  the dialog will not send a blank reason (the client-side half), and closing it leaves the
 *      event as it was.
 * AC11 a coordinator is not offered Cancel event.
 *
 * What is released or closed (AC2-AC4), who is told (AC5), every status rule (AC6), the server's
 * refusals (AC7, AC11), and the transaction and race cases (AC10, AC12, AC13) are backend cases:
 * backend/tests/cancellations/test_cancel_event.py.
 *
 * Each cancelling test raises and submits a fresh request of its own, since a cancellation cannot
 * be undone; the cancelled and planning events it reads are seeded and never changed.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, createAndSubmitRequest, EVENTS, signIn, uniqueName } from './support'

const REASON = 'Our sponsor withdrew the budget.'
// The seeded cancellation of the Summer Rooftop Mixer (backend/db/seed/020_sample_data.sql).
const SEEDED_REASON = 'The rooftop terrace is closed for repairs that week.'

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
  await expect(cancellation).toContainText('Cancelled by Olivia Organiser')
  await expect(cancellation).toContainText(REASON)
  await expect(page.getByText('Cancelled', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)

  await page.goto('/events/mine')
  await expect(page.getByText(name)).toBeVisible()
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
  await expect(cancellation).toContainText('Cancelled by Omar Organiser')
  await expect(cancellation).toContainText(SEEDED_REASON)
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)
})

test('6.2 AC11: a coordinator is not offered Cancel event', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.planning}`)

  await expect(page.getByRole('heading', { name: 'Regional Sales Summit' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0)
})
