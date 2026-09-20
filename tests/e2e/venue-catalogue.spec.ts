/**
 * Story 8.1: browse the venue catalogue.
 * AC1 all venues in service are listed, showing name, location and capacity.
 * AC2 selecting a venue opens its full record.
 * AC3 venues withdrawn from service are excluded.
 * Team decision, 17 Sep 2026 (frontend design prototype): coordinators can also filter the list
 * by a capacity range ("Capacity from" / "Capacity to"), applied client-side like story 8.3's
 * Venue Staff list.
 * Permission refusal (403) and the underlying data shape are backend cases:
 * backend/tests/venues/test_venue_records.py.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

test('8.1 AC1/AC3: the catalogue lists in-service venues with name, location and capacity, excluding withdrawn ones', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await expect(page.getByRole('heading', { name: 'Venue catalogue' })).toBeVisible()
  const grandHallCard = page.locator('.item-card', { hasText: 'Grand Hall' })
  await expect(grandHallCard).toContainText('Tower A, Level 1')
  await expect(grandHallCard).toContainText('400')

  await expect(page.locator('.item-card', { hasText: 'Old Annex Room' })).toHaveCount(0)
})

test('8.1 AC2: selecting a venue opens its full record', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await expect(page).toHaveURL(/\/venues\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Tower A, Level 1')).toBeVisible()
  await expect(page.getByText('Quick facts')).toBeVisible()
})

test('8.1: the catalogue can be filtered by a capacity range', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await page.getByLabel('Capacity from').fill('100')
  await page.getByLabel('Capacity to').fill('300')

  await expect(page.locator('.item-card', { hasText: 'Exhibition Foyer' })).toBeVisible()
  await expect(page.locator('.item-card', { hasText: 'Grand Hall' })).toHaveCount(0)
  await expect(page.locator('.item-card', { hasText: 'Boardroom 3.4' })).toHaveCount(0)
})

test('8.1: a venue staff member does not see the coordinator catalogue link', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await expect(page.getByRole('link', { name: 'Venue catalogue' })).toHaveCount(0)
})
