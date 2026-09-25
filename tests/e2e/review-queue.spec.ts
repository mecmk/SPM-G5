/**
 * Story 4.1 - fe/be: display the coordinator review queue.
 * AC1 the queue lists requests awaiting a decision, assigned to the signed-in coordinator.
 * AC2 each entry shows the event name, organiser, proposed date and submission date.
 * AC3 the queue can be ordered by submission date or proposed event date.
 * AC4 drafts and already-decided requests never appear.
 * Ordering across several rows, the coordinator filter, malformed input, and 401/403/422
 * refusals are backend cases: backend/tests/events/test_review_queue.py.
 *
 * Story 6.1 replaced the old four-tab, review-only page with the shared All-plus-seven tab set
 * (tests/e2e/my-event-requests.spec.ts's sibling for the coordinator side), backed by
 * `/events/assigned-to-me`. AC1-AC4 above still hold true within the "Under Review" tab, which
 * carries the same awaiting-decision rows the old page's single view showed.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

function queueCard(page: Page, name: string) {
  return page.getByRole('main').getByRole('listitem').filter({ hasText: name })
}

test('4.1 AC1/AC2: a coordinator sees the requests assigned to them with name, organiser and dates', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await expect(page.getByRole('heading', { name: 'Events inbox' })).toBeVisible()
  await page.getByRole('tab', { name: /^Under Review/ }).click()

  const card = queueCard(page, 'Data Literacy Workshop')
  await expect(card).toContainText('Olivia Organiser')
  await expect(card).toContainText('18 Nov 2026')
  await expect(card).toContainText('8 Sept 2026')
})

test('4.1 AC1: an event assigned to another coordinator does not appear in this queue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto('/events/inbox')

  await expect(queueCard(page, 'Data Literacy Workshop')).toHaveCount(0)
  await expect(queueCard(page, 'Rooftop Networking Night')).toBeVisible()
})

test('4.1 AC3: the "Under Review" tab can be ordered by submission date or proposed event date', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')
  await page.getByRole('tab', { name: /^Under Review/ }).click()

  // Story 5.1 auto-assigns a coordinator round robin on submission, so another spec's request
  // can land in this same "Under Review" tab too; filter to these three seeded ones and check
  // their relative order, rather than asserting the tab holds only them (tests/CLAUDE.md).
  const seeded = ['Data Literacy Workshop', 'Nimbus Leadership Offsite', 'Wellness Week Kickoff']
  const titles = async () => {
    const all = await page.getByRole('main').getByRole('heading', { level: 3 }).allTextContents()
    return all.filter((title) => seeded.includes(title))
  }

  // Default: submission date, earliest first.
  await expect
    .poll(titles)
    .toEqual(['Data Literacy Workshop', 'Nimbus Leadership Offsite', 'Wellness Week Kickoff'])

  await page.getByLabel('Order by').selectOption({ label: 'Proposed event date' })

  await expect
    .poll(titles)
    .toEqual(['Wellness Week Kickoff', 'Data Literacy Workshop', 'Nimbus Leadership Offsite'])
})

test('4.1 AC4: drafts and decided requests are not listed', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await expect(queueCard(page, 'Q1 Sales Kick-off')).toHaveCount(0)
})

test('4.1: the queue can be searched by event or organiser', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')
  await page.getByRole('tab', { name: /^Under Review/ }).click()

  await page.getByLabel('Search requests').fill('olivia')
  await expect(queueCard(page, 'Data Literacy Workshop')).toBeVisible()

  await page.getByLabel('Search requests').fill('zzz-no-match')
  await expect(page.getByText('No requests match your search.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear search' }).click()

  await expect(queueCard(page, 'Data Literacy Workshop')).toBeVisible()
})

test('4.1: an organiser cannot open the events inbox', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto('/events/inbox')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})

test("6.1: every tab shows the coordinator's events in that status, and each card names its status", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await expect(page.getByRole('tab', { name: 'All', exact: false })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(queueCard(page, 'Data Literacy Workshop')).toContainText('Submitted')

  await page.getByRole('tab', { name: /^Planning/ }).click()
  await expect(queueCard(page, 'Nimbus Developer Conference')).toContainText('Approved')
  await expect(queueCard(page, 'Regional Sales Summit')).toContainText('Planning')
  await expect(queueCard(page, 'Partner Appreciation Dinner')).toContainText('Confirmed')

  await page.getByRole('tab', { name: /^Completed/ }).click()
  await expect(queueCard(page, 'New Year Town Hall')).toContainText('Completed')

  await page.getByRole('tab', { name: /^Cancelled/ }).click()
  await expect(queueCard(page, 'Summer Rooftop Mixer')).toContainText('Cancelled')
})
