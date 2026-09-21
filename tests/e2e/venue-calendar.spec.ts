/**
 * Story 9.1: venue availability calendar.
 * AC1 a calendar view shows availability for one venue across a selectable range of dates.
 * AC2 each period is shown as available or unavailable.
 * AC3 the view is restricted to authorised internal users - fully covered as a backend case:
 * backend/tests/venues/test_venue_calendar.py::test_calendar_is_restricted_to_internal_roles.
 * The calendar opens on the current month (September 2026), so these navigate forward to
 * November 2026, where the seed data's booking and maintenance period live.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

/** The "Availability" card - a region via its `aria-labelledby`, same pattern as
 *  venue-detail.spec.ts's cardSection(). */
function availabilitySection(page: Page) {
  return page.getByRole('region', { name: 'Availability', exact: true })
}

async function goToNovember2026(page: Page) {
  const section = availabilitySection(page)
  for (let i = 0; i < 2; i += 1) {
    await section.getByRole('button', { name: 'Next →' }).click()
  }
  await expect(page.getByText('November 2026')).toBeVisible()
}

test('9.1 AC1/AC2: an approved booking shows as unavailable, with the event as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).toBeVisible()
})

test('9.1 AC1/AC2: a maintenance period shows as unavailable, with its notes as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Annual air-con servicing').first()).toBeVisible()
})

test('9.1 AC1: a venue with nothing booked shows no unavailable days', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Boardroom 3.4' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).not.toBeVisible()
  await expect(page.getByText('Annual air-con servicing')).not.toBeVisible()
})

test('9.1 AC1: navigating back a month leaves the current month', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()
  await section.getByRole('button', { name: '← Prev' }).click()
  await expect(page.getByText('August 2026')).toBeVisible()
})
