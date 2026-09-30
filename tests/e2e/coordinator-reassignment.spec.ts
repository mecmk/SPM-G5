/**
 * Story 5.2 - fe/be: reassign a coordinator-holding event to a different coordinator.
 *
 * AC3 the event page has a Reassign action with a list of eligible coordinators and a
 *     confirmation step; the assignment change takes effect immediately (the page shows the new
 *     coordinator without a reload).
 *
 * Boundary, permission and conflict detail (AC4, AC6, AC7) are backend cases, covered by
 * backend/tests/coordination/test_reassign_coordinator.py. This spec covers the flow a
 * coordinator actually clicks through.
 *
 * The event used here is a fresh one created and submitted through the UI, not an existing seed
 * row: story 5.1's round robin means a submission can land on either seeded coordinator, and
 * reassigning a *shared* seed event (used by several other specs for its bookings, equipment and
 * accessibility data) would leave it permanently changed for the rest of this parallel run (see
 * tests/CLAUDE.md on why specs must not mutate shared seed state). Whichever coordinator the
 * round robin lands on is discovered from the page itself, the same way a person would look.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

const COORDINATOR_ACCOUNT_BY_NAME: Record<string, string> = {
  'Chloe Coordinator': ACCOUNTS.coordinator,
  'Carl Coordinator': ACCOUNTS.coordinator2,
}

function uniqueName(label: string): string {
  return `E2E ${label} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

function inFuture(days: number, hour = 9): string {
  const day = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
  const date = day.toISOString().slice(0, 10)
  return `${date}T${String(hour).padStart(2, '0')}:00`
}

/** Create and submit a fresh, minimal request as the organiser; returns its id. */
async function createAndSubmitRequest(page: Page, name: string): Promise<string> {
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Purpose').fill('Staff training')
  await page.getByLabel('Description').fill('One-day hands-on workshop.')
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByLabel('Proposed end').fill(inFuture(30, 17))
  await page.getByLabel('Expected attendance').fill('60')
  await page.getByLabel('Contact name').fill('Priya Nair')
  await page.getByLabel('Contact email').fill('priya.nair@example.com')
  await page.getByLabel('Contact phone number').fill('+65 9123 4567')
  await page.getByRole('checkbox', { name: 'No venue requirements' }).check()
  await page.getByRole('checkbox', { name: 'No accessibility needs' }).check()
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(/\/events\/[0-9a-f-]{36}\/edit$/)
  const match = page.url().match(/\/events\/([0-9a-f-]{36})\/edit$/)
  if (!match) throw new Error(`could not read the event id from ${page.url()}`)
  const eventId = match[1]

  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(/\/events\/mine$/)
  return eventId
}

/** The name of whoever the event page currently shows as the assigned coordinator. */
async function readAssignedCoordinatorName(page: Page): Promise<string> {
  const stat = page.locator('.stat').filter({ has: page.getByText('Assigned coordinator') })
  const name = await stat.locator('.stat-value').textContent()
  if (!name) throw new Error('no assigned coordinator shown on the event page')
  return name.trim()
}

test('5.2 AC3: a coordinator reassigns an event to another coordinator', async ({ page }) => {
  // Two full sign-in cycles (organiser, then the auto-assigned coordinator) genuinely take
  // longer than the default per-test budget - see bookings.spec.ts's AC3/AC4 test for the
  // same reasoning.
  test.setTimeout(60_000)

  const name = uniqueName('Reassign')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  await page.goto(`/events/${eventId}`)
  const currentName = await readAssignedCoordinatorName(page)
  const currentAccount = COORDINATOR_ACCOUNT_BY_NAME[currentName]
  if (!currentAccount) throw new Error(`unrecognised auto-assigned coordinator: ${currentName}`)
  const otherName = currentName === 'Chloe Coordinator' ? 'Carl Coordinator' : 'Chloe Coordinator'

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, currentAccount)
  await page.goto(`/events/${eventId}`)

  await page.getByRole('button', { name: 'Reassign' }).click()
  await page.getByLabel('New coordinator').selectOption({ label: otherName })
  await page.getByRole('button', { name: 'Confirm reassignment' }).click()

  await expect(page.getByText(otherName)).toBeVisible()
})
