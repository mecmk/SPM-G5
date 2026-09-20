/**
 * Story 8.2: display a venue's full characteristics.
 * AC1 the record shows location, capacity, facilities, accessibility features, supported room
 *     layouts, and operating information.
 * AC2 where a characteristic is not recorded, this is shown as unknown ("Not recorded") rather
 *     than as absent.
 * AC3 the record is readable by Event Coordinators and Venue Staff. Technical Support Staff
 * keeps read access too (confirmed 20 Sep 2026), via the shared VENUES_READ permission rather
 * than a venues-specific one (see permissions.py).
 * AC3's permission boundary (Attendee/Organiser refused) is a backend case:
 * backend/tests/auth/test_rbac.py::test_venue_actions_are_allowed_only_for_permitted_roles.
 * Venue Staff has no link to this page from their own UI today (they have a separate
 * manage/edit view) - this only checks direct navigation works, per AC3's wording.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

/** The <section class="card"> whose eyebrow label matches exactly - avoids matching the
 *  similarly-named row inside the "Quick facts" aside (e.g. its own "Facilities" count row). */
function cardSection(page: Page, label: string) {
  return page.locator('section.card').filter({ has: page.getByText(label, { exact: true }) })
}

/** A specific <li> row inside a check-list, by its label - anchored to the start of the row's
 *  text so a sibling row whose value happens to contain the same word (e.g. "Notes" containing
 *  "...hours...") is never mistaken for the labelled row itself. */
function checkListRow(scope: ReturnType<Page['locator']>, label: string) {
  return scope.locator('li').filter({ hasText: new RegExp(`^${label}`) })
}

test('8.2 AC1: a fully-populated venue shows every characteristic', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Tower A, Level 1')).toBeVisible()

  const facilities = cardSection(page, 'Facilities')
  for (const facility of [
    'Catering area',
    'Projector & screen',
    'Sound system',
    'Stage',
    'Wi-Fi',
  ]) {
    await expect(facilities).toContainText(facility)
  }
  const accessibility = cardSection(page, 'Accessibility')
  for (const feature of [
    'Accessible toilet nearby',
    'Hearing loop',
    'Step-free route from entrance',
    'Wheelchair access',
  ]) {
    await expect(accessibility).toContainText(feature)
  }
  const capacity = cardSection(page, 'Capacity')
  await expect(capacity).toContainText('Banquet')
  await expect(capacity).toContainText('Theatre')

  const operating = cardSection(page, 'Operating information')
  await expect(checkListRow(operating, 'Hours')).toContainText('08:00–22:00')
  await expect(checkListRow(operating, 'Notes')).toContainText('Loading bay access from Carpark B.')
  await expect(checkListRow(operating, 'Floor area')).toContainText('520.00 m²')

  const quickFacts = page
    .locator('aside.card')
    .filter({ has: page.getByText('Quick facts', { exact: true }) })
  await expect(checkListRow(quickFacts, 'Max capacity')).toContainText('400')
  await expect(checkListRow(quickFacts, 'Area')).toContainText('520.00 m²')
})

test('8.2 AC2: a partially-recorded venue shows "Not recorded" only for the unset field', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Exhibition Foyer' }).click()

  const operating = cardSection(page, 'Operating information')
  await expect(checkListRow(operating, 'Hours')).toContainText('Not recorded')
  await expect(checkListRow(operating, 'Notes')).toContainText('Operating hours not yet confirmed.')
  await expect(checkListRow(operating, 'Floor area')).toContainText('380.00 m²')
})

test('8.2 AC2: a venue with no facilities, layouts or accessibility features shows "Not recorded" for each', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/manage')
  await page.getByRole('checkbox', { name: 'Show withdrawn venues' }).check()
  await page
    .getByRole('row', { name: /Old Annex Room/ })
    .getByRole('link', { name: 'Edit' })
    .click()
  const venueId = page.url().match(/\/venues\/([^/]+)\/edit/)?.[1]
  expect(venueId).toBeTruthy()

  await page.goto(`/venues/${venueId}`)

  await expect(page.getByRole('heading', { name: 'Old Annex Room' })).toBeVisible()
  await expect(page.getByText('Withdrawn', { exact: true })).toBeVisible()

  await expect(cardSection(page, 'Capacity')).toContainText('Not recorded')
  await expect(cardSection(page, 'Facilities')).toContainText('Not recorded')
  await expect(cardSection(page, 'Accessibility')).toContainText('Not recorded')
})

test('8.2 AC3: a venue staff member can open a venue record directly', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/manage')
  await page
    .getByRole('row', { name: /Grand Hall/ })
    .getByRole('link', { name: 'Edit' })
    .click()
  const venueId = page.url().match(/\/venues\/([^/]+)\/edit/)?.[1]
  expect(venueId).toBeTruthy()

  await page.goto(`/venues/${venueId}`)

  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Tower A, Level 1')).toBeVisible()
})
