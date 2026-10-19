/**
 * Story 18.3 - fe/be: the registration list for my event.
 * AC1 The list shows each attendee's name, email, registration time and status, and the active
 *     count against the event's capacity: the organiser reads the count on the event's page and
 *     who registered on the registrations report it links to; the assigned coordinator reads the
 *     count on the event page too, and reaches the report from the navigation. An event that does
 *     not take registrations offers neither.
 * AC3 An event with no registrations shows an empty list; an event whose count reaches capacity
 *     shows it is full.
 * Every other case (AC2, AC4-AC7: the server's count, withdrawn rows, paging, the 404s and 401) is
 * a backend case: backend/tests/registrations/test_registration_list_integration.py.
 *
 * Every event is seeded and only read (EVENTS.portfolioReview, wineAppreciation, confirmed): a
 * full event and a closed one, so no other spec can register for either, and one not taking
 * registrations.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

function registrations(page: Page) {
  return page.getByRole('region', { name: 'Registered attendees', exact: true })
}

function registrationCard(page: Page) {
  return page.getByRole('region', { name: 'Registration', exact: true })
}

test('18.3 AC1/AC3: the organiser sees who registered, with the count against capacity and Full', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.portfolioReview}`)

  // The event page shows only the count; the list is on the registrations report.
  const summary = registrationCard(page)
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
  await expect(list).toContainText('1 / 1')
  await expect(list.getByText('Full', { exact: true })).toBeVisible()
})

test('18.3 AC1: an event that does not take registrations offers no count or link', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  // The card asks for the count either way; once it has answered, nothing is shown.
  const answered = page.waitForResponse((response) =>
    response.url().includes(`/events/${EVENTS.confirmed}/registrations`),
  )
  await page.goto(`/events/${EVENTS.confirmed}`)
  await answered

  const summary = registrationCard(page)
  await expect(summary).toContainText('No')
  await expect(summary.getByRole('link', { name: 'View registrations' })).toHaveCount(0)
  await expect(summary.getByText('Registered', { exact: true })).toHaveCount(0)
})

test('18.3 AC1/AC3: the assigned coordinator reads the count, then that no one has registered yet', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.wineAppreciation}`)

  const summary = registrationCard(page)
  await expect(summary).toContainText('0 / 40')
  await expect(summary.getByText('Full', { exact: true })).toHaveCount(0)
  await summary.getByRole('link', { name: 'View registrations' }).click()

  const list = registrations(page)
  await expect(list).toContainText('No one has registered yet.')
  await expect(list).toContainText('0 / 40')
  await expect(list.getByText('Full', { exact: true })).toHaveCount(0)

  // The report is in the navigation too, with no event picked until one is chosen.
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Registrations', exact: true })
    .click()
  await expect(page).toHaveURL(/\/registrations\/report$/)
  await expect(registrations(page)).toHaveCount(0)
  await page.getByLabel('Event').selectOption(EVENTS.wineAppreciation)
  await expect(registrations(page)).toContainText('No one has registered yet.')
})
