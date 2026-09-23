/**
 * Story 7.2 - fe: the assigned Event Coordinator edits an event's routine information from the
 * event detail page.
 * AC1 the coordinator assigned to the event opens the edit page and saves its routine fields.
 * AC2 the change takes effect immediately: the event detail page shows it on return.
 * AC3 the edit entry point is not offered once the event is completed, cancelled or rejected.
 * Who may call the PATCH itself, the routine-field allow-list, and the 403/409 refusals are
 * covered by backend/tests/events/test_edit_routine_information.py. This spec covers the flow a
 * coordinator actually clicks through, plus the one purely-frontend concern: whether the edit
 * link is offered at all for an event that is no longer open.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test('7.2 AC1/AC2: the assigned coordinator edits routine information and it is still there on return', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.submitted}`)

  await page.getByRole('link', { name: 'Edit routine information' }).click()
  await expect(
    page.getByRole('heading', { name: 'Edit routine information', level: 1 }),
  ).toBeVisible()

  const stamp = Date.now()
  const description = `E2E updated description ${stamp}`
  const internalNotes = `E2E coordinator note ${stamp}`
  const contactName = `E2E Contact ${stamp}`
  const contactEmail = `e2e-${stamp}@acme.example`
  const contactPhone = '+65 6555 0100'

  await page.getByLabel('Description').fill(description)
  await page.getByLabel('Internal notes').fill(internalNotes)
  await page.getByLabel('Contact name').fill(contactName)
  await page.getByLabel('Contact email').fill(contactEmail)
  await page.getByLabel('Contact phone').fill(contactPhone)

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/routine-information') && response.request().method() === 'PATCH',
    ),
    page.getByRole('button', { name: 'Save changes' }).click(),
  ])

  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await expect(page.getByRole('alert')).toHaveCount(0)

  await page.getByRole('link', { name: /^← / }).click()
  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText(description)).toBeVisible()
  await expect(page.getByText(internalNotes)).toBeVisible()
  await expect(page.getByText(contactName)).toBeVisible()
  await expect(page.getByText(contactEmail)).toBeVisible()
  await expect(page.getByText(contactPhone)).toBeVisible()
})

test('7.2 AC3: a rejected event offers no edit entry point, even to its assigned coordinator', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.rejected}`)

  await expect(
    page.getByRole('heading', { name: 'Rooftop Networking Night', level: 1 }),
  ).toBeVisible()
  await expect(page.getByRole('link', { name: 'Edit routine information' })).toHaveCount(0)
})
