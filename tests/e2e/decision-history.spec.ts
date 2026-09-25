/**
 * Story 4.6 - fe: display the decision and clarification history on the event details page.
 * AC1 the decision status (badge, decided-by, decided-on, and the reason when rejected) renders
 *     as one sentence above the clarification thread; a pending decision shows placeholder copy,
 *     with an extra hint when the coordinator has asked for clarification.
 * AC2 the clarification conversation renders oldest first, with each entry's author, kind and
 *     timestamp.
 * Permission boundaries (403 for an unrelated internal role, 404 for another organiser's
 * request), ordering edge cases and immutability are backend cases:
 * backend/tests/events/test_decision_history.py.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

function clarificationsSection(page: Page): Locator {
  return page.getByRole('region', { name: 'Clarifications', exact: true })
}

test('4.6 AC1: a request awaiting decision shows the decision has not been made yet', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.submitted}`)

  const section = clarificationsSection(page)
  await expect(section.getByText('A decision has not been made yet.')).toBeVisible()
  await expect(
    section.getByText('No clarification has been requested on this request.'),
  ).toBeVisible()
})

test('4.6 AC1: a request sent back for clarification points to the messages below', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.clarificationRequested}`)

  const section = clarificationsSection(page)
  await expect(
    section.getByText(
      'A decision has not been made yet. The coordinator has asked for clarification - see the messages below.',
    ),
  ).toBeVisible()
})

test('4.6 AC1: an approved request shows who decided it and when, with no reason shown', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.approved}`)

  const section = clarificationsSection(page)
  await expect(section.getByText('Planning', { exact: true })).toBeVisible()
  await expect(section.getByText('Decided by Chloe Coordinator on Thu, 3 Sept 2026')).toBeVisible()
})

test('4.6 AC1: a rejected request shows who decided it, when, and the reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.rejected}`)

  const section = clarificationsSection(page)
  await expect(section.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(
    section.getByText(
      'Decided by Carl Coordinator on Mon, 7 Sept 2026 — "No outdoor venues are available after 22:00."',
    ),
  ).toBeVisible()
})

test('4.6 AC2: the clarification thread renders oldest first with author, kind and timestamp', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.clarificationRequested}`)

  const messages = clarificationsSection(page).getByRole('listitem')
  await expect(messages).toHaveCount(2)

  await expect(messages.nth(0)).toContainText('Chloe Coordinator')
  await expect(messages.nth(0)).toContainText('Clarification requested')
  await expect(messages.nth(0)).toContainText('Fri, 4 Sept 2026, 10:00')
  await expect(messages.nth(0)).toContainText('Please add expected headcount by department.')

  await expect(messages.nth(1)).toContainText('Olivia Organiser')
  await expect(messages.nth(1)).toContainText('Response')
  await expect(messages.nth(1)).toContainText('Sat, 5 Sept 2026, 14:30')
  await expect(messages.nth(1)).toContainText(
    'About 60 from Engineering, 50 from Sales and 40 from Operations.',
  )
})
