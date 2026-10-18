/**
 * Story 18.3 - fe/be: the registration list for my event.
 * AC1 the organiser reads the active count against capacity on the event's page, and each
 *     attendee's name, email, registration time and status on the registrations report it links to.
 * AC3 the assigned coordinator picks an event no one registered for on the registrations report
 *     and reads "No one has registered yet."; an event whose count reaches capacity says "Full".
 * Every other case (AC2, AC4-AC7: the server's count, withdrawn rows, the 404s and 401) is a
 * backend case: backend/tests/registrations/test_registration_list_integration.py.
 *
 * Both events are seeded and only read (EVENTS.portfolioReview, wineAppreciation): a full event
 * and a closed one, so no other spec can register for either.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

function registrations(page: Page) {
  return page.getByRole('region', { name: 'Registered attendees', exact: true })
}

test('18.3 AC1: the organiser sees who registered, with the count against capacity', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.portfolioReview}`)

  // The event page shows only the count; the list is on the registrations report.
  const summary = page.getByRole('region', { name: 'Registration', exact: true })
  await expect(summary).toContainText('1 / 1')
  await expect(summary.getByText('Full', { exact: true })).toBeVisible()
  await expect(registrations(page)).toHaveCount(0)
  await summary.getByRole('link', { name: 'View registrations' }).click()
  await expect(page).toHaveURL(/\/registrations\/report\?event=/)

  const list = registrations(page)
  const row = list.getByRole('row', { name: /Bella Attendee/ })
  await expect(row).toContainText('attendee2@example.com')
  await expect(row).toContainText('Registered')
  await expect(row).toContainText('11 Oct 2026')
  await expect(list).toContainText('1 / 1 registered')
  await expect(list.getByText('Full', { exact: true })).toBeVisible()
})

test('18.3 AC3: the assigned coordinator sees an empty list said so', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto('/registrations/report')
  await page.getByLabel('Event').selectOption(EVENTS.wineAppreciation)

  const list = registrations(page)
  await expect(list).toContainText('No one has registered yet.')
  await expect(list).toContainText('0 / ')
  await expect(list.getByText('Full', { exact: true })).toHaveCount(0)
})
