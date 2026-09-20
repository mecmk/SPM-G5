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
 * manage/edit view); AC3 only requires it be readable, so this checks direct navigation to
 * /venues, which they can reach because they hold VENUES_READ even without a nav link.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, venueRow } from './support'

/** The region whose heading matches exactly - relies on the card's `aria-labelledby`, so this
 *  also doubles as an a11y check the way every other spec's role-based selectors do. */
function cardSection(page: Page, label: string): Locator {
  return page.getByRole('region', { name: label, exact: true })
}

function quickFacts(page: Page): Locator {
  return page.getByRole('complementary', { name: 'Quick facts', exact: true })
}

/** A specific row inside a check-list, by its label. `role="listitem"` gets no accessible name
 *  from its content (unlike region/complementary above, which have an explicit aria-labelledby),
 *  so this finds the label text itself and steps up to its row - still a text-based, no
 *  CSS-class or test-id lookup, matching the label's own exact text so a sibling row whose value
 *  happens to contain the same word (e.g. "Notes" containing "...hours...") is never confused
 *  with the row actually labelled "Hours". */
function checkListRow(scope: Locator, label: string): Locator {
  return scope.getByText(label, { exact: true }).locator('..')
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
  await expect(checkListRow(operating, 'Setup')).toContainText('60 min')
  await expect(checkListRow(operating, 'Teardown')).toContainText('60 min')
  await expect(checkListRow(operating, 'Floor area')).toContainText('520.00 m²')
  await expect(checkListRow(operating, 'Notes')).toContainText('Loading bay access from Carpark B.')

  const facts = quickFacts(page)
  await expect(checkListRow(facts, 'Max capacity')).toContainText('400')
  await expect(checkListRow(facts, 'Area')).toContainText('520.00 m²')
})

test('8.2 AC2: a partially-recorded venue shows "Not recorded" only for the unset field', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Exhibition Foyer' }).click()

  await expect(page.getByRole('heading', { name: 'Exhibition Foyer' })).toBeVisible()

  const operating = cardSection(page, 'Operating information')
  await expect(checkListRow(operating, 'Hours')).toContainText('Not recorded')
  await expect(checkListRow(operating, 'Notes')).toContainText('Operating hours not yet confirmed.')
  await expect(checkListRow(operating, 'Floor area')).toContainText('380.00 m²')
})

test('8.2 AC2: a venue with nothing recorded shows "Not recorded" for every field, not a blank or vanished section', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/manage')
  await page.getByRole('checkbox', { name: 'Show withdrawn venues' }).check()
  await venueRow(page, 'Old Annex Room').getByRole('link', { name: 'Edit' }).click()
  await page.waitForURL(/\/venues\/[^/]+\/edit$/)
  const venueId = page.url().match(/\/venues\/([^/]+)\/edit/)?.[1]
  expect(venueId).toBeTruthy()

  await page.goto(`/venues/${venueId}`)

  await expect(page.getByRole('heading', { name: 'Old Annex Room' })).toBeVisible()
  await expect(page.getByText('Withdrawn', { exact: true })).toBeVisible()

  await expect(cardSection(page, 'Capacity')).toContainText('Not recorded')
  await expect(cardSection(page, 'Facilities')).toContainText('Not recorded')
  await expect(cardSection(page, 'Accessibility')).toContainText('Not recorded')

  const operating = cardSection(page, 'Operating information')
  await expect(checkListRow(operating, 'Hours')).toContainText('Not recorded')
  await expect(checkListRow(operating, 'Floor area')).toContainText('Not recorded')
  await expect(checkListRow(operating, 'Notes')).toContainText('Not recorded')
})

test('8.2 AC3: a venue staff member can open a venue record', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await expect(page).toHaveURL(/\/venues\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Tower A, Level 1')).toBeVisible()
})
