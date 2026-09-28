/**
 * Story 8.3 - fe/be: create and update venue records.
 * AC1 a venue can be created with at least a name, location and capacity.
 * AC2 existing venue characteristics can be edited and saved.
 * AC3 capacity accepts positive whole numbers only (checked in the browser before sending).
 * AC4 only Venue Staff can create or edit venue records.
 * The team meeting of 17 Sep 2026 added delete (full CRUD), search and a capacity filter, and
 * asked for every save to appear in the notification centre.
 *
 * Story 8.1 AC12 (f8.1.1, Sprint 1 review): Venue Staff manage venues from the venue catalogue,
 * the page coordinators browse - New venue, Edit and Delete on each venue, and Show withdrawn
 * venues, for venues:manage holders only. The separate Manage venues page is gone and its old
 * address opens the catalogue. The manage page's name search and capacity filter live on in the
 * catalogue's "Name or location" box and capacity range.
 * Refusals and conflicts (401, 403, 409 in use, 422) are backend cases:
 * backend/tests/venues/test_venue_records.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn, venueCard } from './support'

const CATALOGUE_PATH = /\/venues$/

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' })
}

async function createVenue(page: Page, name: string, capacity = '45') {
  await page.goto('/venues')
  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill(capacity)
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
}

test('8.3 AC1/AC2: venue staff create a venue, then edit it', async ({ page }) => {
  const name = `E2E Room ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')

  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill('45')
  await page.getByRole('checkbox', { name: 'Wi-Fi', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Theatre', exact: true }).check()
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(venueCard(page, name)).toContainText('45')

  await venueCard(page, name).getByRole('link', { name: 'Edit' }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Wi-Fi', exact: true })).toBeChecked()
  await page.getByLabel('Maximum capacity').fill('60')
  await page.getByRole('button', { name: 'Save changes' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(venueCard(page, name)).toContainText('60')
})

test('8.3 AC3: capacity must be a positive whole number before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  let createCalls = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/venues')) createCalls += 1
  })
  await page.getByLabel('Venue name').fill('Capacity check room')
  await page.getByLabel('Location').fill('Nowhere')

  for (const value of ['0', '-3', '12.5']) {
    await page.getByLabel('Maximum capacity').fill(value)
    await page.getByRole('button', { name: 'Create venue' }).click()
    await expect(page.getByRole('alert')).toContainText('positive whole number')
  }
  expect(createCalls).toBe(0)
})

test('8.3 AC1: a duplicate venue name is refused with the reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/new')
  await page.getByLabel('Venue name').fill('Grand Hall')
  await page.getByLabel('Location').fill('Anywhere')
  await page.getByLabel('Maximum capacity').fill('10')
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page.getByRole('main').getByRole('alert')).toContainText('already exists')
  await expect(page).toHaveURL(/\/venues\/new$/)
})

test('8.3: every save appears in the notification centre', async ({ page }) => {
  const name = `E2E Notify ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)

  await createVenue(page, name)

  await expect(page.getByRole('status').filter({ hasText: 'Venue created' })).toBeVisible()
  await page.getByRole('button', { name: /^Notifications/ }).click()
  const panel = page.getByRole('region', { name: 'Notifications' })
  await expect(panel.getByText(`${name} was added to the catalogue.`)).toBeVisible()
})

test('8.3 AC4: an event coordinator cannot open venue management', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto('/venues/new')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByLabel('Venue name')).toHaveCount(0)

  // The old Manage venues address is still behind venues:manage, so it does not redirect them.
  await page.goto('/venues/manage')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page).toHaveURL(/\/venues\/manage$/)
})

test('8.3: a link to the new-venue form survives signing in', async ({ page }) => {
  await page.goto('/venues/new')
  await expect(page).toHaveURL(/\/login$/)

  await signIn(page, ACCOUNTS.venueStaff)

  await expect(page).toHaveURL(/\/venues\/new$/)
  await expect(page.getByRole('heading', { name: 'New venue' })).toBeVisible()
})

test('8.1 AC12: Venue Staff add and edit venues from the catalogue', async ({ page }) => {
  const name = `E2E Catalogue ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)

  await expect(mainNav(page).getByRole('link', { name: 'Manage venues' })).toHaveCount(0)
  await mainNav(page).getByRole('link', { name: 'Venue catalogue', exact: true }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  await expect(page.getByText('Keep the venue records accurate.', { exact: false })).toBeVisible()

  await page.getByRole('link', { name: 'New venue' }).click()
  await expect(page.getByRole('heading', { name: 'New venue', level: 1 })).toBeVisible()
  // Backing out of the form returns to the catalogue.
  await page.getByRole('link', { name: '← Venue catalogue' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 3')
  await page.getByLabel('Maximum capacity').fill('30')
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  const card = venueCard(page, name)
  await expect(card).toContainText('Tower E, Level 3')
  await expect(card).toContainText('30')

  await card.getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await page.getByRole('link', { name: 'Cancel' }).click()
  await expect(page).toHaveURL(CATALOGUE_PATH)

  await card.getByRole('link', { name: 'Edit', exact: true }).click()
  // Wait for the form: until it opens, "Location" also matches the catalogue's search box.
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await page.getByLabel('Location').fill('Tower F, Level 5')
  await page.getByRole('button', { name: 'Save changes' }).click()

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(card).toContainText('Tower F, Level 5')
})

test('8.1 AC12: Venue Staff delete a venue from the catalogue', async ({ page }) => {
  const name = `E2E Delete ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await createVenue(page, name)

  await venueCard(page, name).getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog).toHaveCount(0)
  await expect(venueCard(page, name)).toHaveCount(0)
  await expect(page).toHaveURL(CATALOGUE_PATH)
})

test('8.1 AC12: a venue with bookings is not deleted, and the dialog says why', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')

  await venueCard(page, 'Grand Hall').getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete Grand Hall?' })
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog.getByRole('alert')).toContainText('cannot delete a venue that has bookings')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

test('8.1 AC12: withdrawn venues can be shown, marked', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')
  const showWithdrawn = page.getByRole('checkbox', { name: 'Show withdrawn venues' })
  await expect(showWithdrawn).not.toBeChecked()
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
  await expect(venueCard(page, 'Old Annex Room')).toHaveCount(0)

  await showWithdrawn.check()

  await expect(
    venueCard(page, 'Old Annex Room').getByText('Withdrawn', { exact: true }),
  ).toBeVisible()
  await expect(venueCard(page, 'Grand Hall').getByText('Withdrawn', { exact: true })).toHaveCount(0)

  await showWithdrawn.uncheck()

  await expect(venueCard(page, 'Old Annex Room')).toHaveCount(0)
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

test('8.1 AC12: the catalogue keeps the manage page’s name search and capacity range', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues')
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()

  // Name or location, ignoring case: "seminar" is a name, "tOWER b" a location.
  await page.getByLabel('Name or location').fill('seminar')
  await expect(venueCard(page, 'Seminar Room 2.1')).toBeVisible()
  await expect(venueCard(page, 'Grand Hall')).toHaveCount(0)

  await page.getByLabel('Name or location').fill('tOWER b')
  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(venueCard(page, 'Seminar Room 2.1')).toHaveCount(0)

  // The capacity range includes both ends: Exhibition Foyer holds exactly 250.
  await page.getByLabel('Name or location').fill('')
  await page.getByLabel('Capacity from').fill('250')
  await page.getByLabel('Capacity to').fill('250')
  await expect(venueCard(page, 'Exhibition Foyer')).toBeVisible()
  await expect(venueCard(page, 'Grand Hall')).toHaveCount(0)
  await expect(venueCard(page, 'Boardroom 3.4')).toHaveCount(0)
})

test('8.1 AC12: the old Manage venues address opens the catalogue', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)

  await page.goto('/venues/manage')

  await expect(page).toHaveURL(CATALOGUE_PATH)
  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'New venue' })).toBeVisible()
})

test('8.1 AC12: a venue deleted elsewhere cannot be deleted again, and the list reloads', async ({
  page,
}) => {
  const name = `E2E Gone ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await createVenue(page, name)
  await expect(venueCard(page, name)).toBeVisible()

  // A second tab in the same session deletes it first; tests/CLAUDE.md forbids calling the API.
  const otherTab = await page.context().newPage()
  await otherTab.goto('/venues')
  await venueCard(otherTab, name).getByRole('button', { name: 'Delete', exact: true }).click()
  await otherTab.getByRole('button', { name: 'Delete venue' }).click()
  await expect(venueCard(otherTab, name)).toHaveCount(0)
  await otherTab.close()

  await venueCard(page, name).getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog.getByRole('alert')).toContainText('Venue not found.')
  await expect(venueCard(page, name)).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(venueCard(page, 'Grand Hall')).toBeVisible()
})

for (const { role, email } of [
  { role: 'a coordinator', email: ACCOUNTS.coordinator },
  { role: 'Technical Support', email: ACCOUNTS.techSupport },
]) {
  test(`8.1 AC12: ${role} browses the catalogue without the manage controls`, async ({ page }) => {
    await signIn(page, email)
    await page.goto('/venues')
    const grandHall = venueCard(page, 'Grand Hall')
    await expect(grandHall).toBeVisible()

    await expect(page.getByText('Venues currently in service.', { exact: false })).toBeVisible()
    await expect(page.getByRole('link', { name: 'New venue' })).toHaveCount(0)
    await expect(page.getByRole('checkbox', { name: 'Show withdrawn venues' })).toHaveCount(0)
    await expect(grandHall.getByRole('link', { name: 'Edit', exact: true })).toHaveCount(0)
    await expect(grandHall.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)
  })
}
