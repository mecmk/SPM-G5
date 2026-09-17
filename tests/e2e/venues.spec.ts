/**
 * Story 8.3 - fe/be: create and update venue records.
 * AC1 a venue can be created with at least a name, location and capacity.
 * AC2 existing venue characteristics can be edited and saved.
 * AC3 capacity accepts positive whole numbers only (checked in the browser before sending).
 * AC4 only Venue Staff can create or edit venue records.
 * The team meeting of 17 Sep 2026 added delete (full CRUD), search and a capacity filter, and
 * asked for every save to appear in the notification centre.
 * Refusals and conflicts (401, 403, 409 in use, 422) are backend cases:
 * backend/tests/venues/test_venue_records.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

const MANAGE_PATH = /\/venues\/manage$/

async function createVenue(page: Page, name: string, capacity = '45') {
  await page.goto('/venues/manage')
  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill(capacity)
  await page.getByRole('button', { name: 'Create venue' }).click()
  await expect(page).toHaveURL(MANAGE_PATH)
}

function venueRow(page: Page, name: string) {
  return page.getByRole('row', { name: new RegExp(name) })
}

test('8.3 AC1/AC2: venue staff create a venue, then edit it', async ({ page }) => {
  const name = `E2E Room ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/manage')

  await page.getByRole('link', { name: 'New venue' }).click()
  await page.getByLabel('Venue name').fill(name)
  await page.getByLabel('Location').fill('Tower E, Level 2')
  await page.getByLabel('Maximum capacity').fill('45')
  await page.getByRole('checkbox', { name: 'Wi-Fi', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Theatre', exact: true }).check()
  await page.getByRole('button', { name: 'Create venue' }).click()

  await expect(page).toHaveURL(MANAGE_PATH)
  await expect(venueRow(page, name)).toContainText('45')

  await venueRow(page, name).getByRole('link', { name: 'Edit' }).click()
  await expect(page.getByRole('heading', { name: `Edit ${name}` })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Wi-Fi', exact: true })).toBeChecked()
  await page.getByLabel('Maximum capacity').fill('60')
  await page.getByRole('button', { name: 'Save changes' }).click()

  await expect(page).toHaveURL(MANAGE_PATH)
  await expect(venueRow(page, name)).toContainText('60')
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

test('8.3: venue staff delete a venue they no longer need', async ({ page }) => {
  const name = `E2E Delete ${Date.now()}`
  await signIn(page, ACCOUNTS.venueStaff)
  await createVenue(page, name)

  await venueRow(page, name).getByRole('button', { name: 'Delete' }).click()
  const dialog = page.getByRole('dialog', { name: `Delete ${name}?` })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete venue' }).click()

  await expect(dialog).toHaveCount(0)
  await expect(venueRow(page, name)).toHaveCount(0)
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

test('8.3: the list can be searched by name and filtered by capacity', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venues/manage')
  await expect(venueRow(page, 'Grand Hall')).toBeVisible()

  await page.getByLabel('Search venues').fill('seminar')
  await expect(venueRow(page, 'Seminar Room 2.1')).toBeVisible()
  await expect(venueRow(page, 'Grand Hall')).toHaveCount(0)

  await page.getByLabel('Search venues').fill('')
  await page.getByLabel('Minimum capacity').fill('300')
  await expect(venueRow(page, 'Grand Hall')).toBeVisible()
  await expect(venueRow(page, 'Boardroom 3.4')).toHaveCount(0)
})

test('8.3 AC4: an event coordinator cannot open venue management', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)

  await page.goto('/venues/new')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByLabel('Venue name')).toHaveCount(0)
})

test('8.3: a link to the new-venue form survives signing in', async ({ page }) => {
  await page.goto('/venues/new')
  await expect(page).toHaveURL(/\/login$/)

  await signIn(page, ACCOUNTS.venueStaff)

  await expect(page).toHaveURL(/\/venues\/new$/)
  await expect(page.getByRole('heading', { name: 'New venue' })).toBeVisible()
})
