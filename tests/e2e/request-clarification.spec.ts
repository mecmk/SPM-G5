/**
 * Story 4.2 - fe/be: the assigned coordinator asks the organiser for clarification.
 *
 * 4.2 AC1 writing a message and sending it records it with author and time, and the event's
 *         status sentence shows it is awaiting the organiser.
 * 4.2 AC3 the message appears immediately, without reloading the page.
 * 4.2 AC5 the coordinator can still send a follow-up question once the request already awaits
 *         a response to an earlier one - this branch implements only story 4.2, so nothing else
 *         would ever move the event back to Under Review to unlock a second round.
 *
 * Boundary, permission and conflict detail are backend cases, covered by
 * backend/tests/events/test_request_clarification.py. This spec covers the round trip a
 * coordinator actually clicks through.
 *
 * The event used here is a fresh one created and submitted through the UI, not an existing seed
 * row: story 5.1's round robin means a submission can land on either seeded coordinator, and this
 * action moves the event to CLARIFICATION_REQUESTED - reusing EVENTS.clarificationRequested (whose
 * fixed two-message thread e2e/decision-history.spec.ts asserts exactly) or one of
 * review-queue.spec.ts's shared UNDER_REVIEW events would leave it permanently changed for the
 * rest of this parallel run (see tests/CLAUDE.md on why specs must not mutate shared seed state).
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

function clarificationsSection(page: Page) {
  return page.getByRole('region', { name: 'Clarifications', exact: true })
}

/** The name of whoever the event page currently shows as the assigned coordinator. */
async function readAssignedCoordinatorName(page: Page): Promise<string> {
  const stat = page.locator('.stat').filter({ has: page.getByText('Assigned coordinator') })
  const name = await stat.locator('.stat-value').textContent()
  if (!name) throw new Error('no assigned coordinator shown on the event page')
  return name.trim()
}

test('4.2: the coordinator asks, and can still ask a follow-up question', async ({ page }) => {
  // Two full sign-in cycles (organiser, then the auto-assigned coordinator) genuinely take
  // longer than the default per-test budget - see coordinator-reassignment.spec.ts for the same
  // reasoning with two.
  test.setTimeout(90_000)

  const name = uniqueName('Clarify')
  await signIn(page, ACCOUNTS.organiser)
  const eventId = await createAndSubmitRequest(page, name)

  await page.goto(`/events/${eventId}`)
  const coordinatorName = await readAssignedCoordinatorName(page)
  const coordinatorAccount = COORDINATOR_ACCOUNT_BY_NAME[coordinatorName]
  if (!coordinatorAccount) {
    throw new Error(`unrecognised auto-assigned coordinator: ${coordinatorName}`)
  }

  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinatorAccount)
  await page.goto(`/events/${eventId}`)

  await page.getByLabel('Message').fill('Could you confirm the expected headcount?')
  await page.getByRole('button', { name: 'Send clarification request' }).click()

  await expect(page.getByText('Could you confirm the expected headcount?')).toBeVisible()
  await expect(
    page.getByText(
      'A decision has not been made yet. The coordinator has asked for clarification - see the messages below.',
    ),
  ).toBeVisible()

  // 4.2 AC5: several rounds are allowed. Nothing on this branch moves the event back to Under
  // Review, so the coordinator has to be able to ask again directly from CLARIFICATION_REQUESTED.
  await expect(page.getByRole('button', { name: 'Send clarification request' })).toBeVisible()
  await page.getByLabel('Message').fill('And which room layout do you need?')
  await page.getByRole('button', { name: 'Send clarification request' }).click()

  const followUp = clarificationsSection(page).getByRole('listitem').last()
  await expect(followUp).toContainText(coordinatorName)
  await expect(followUp).toContainText('And which room layout do you need?')
})
