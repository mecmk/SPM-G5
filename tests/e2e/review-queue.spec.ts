/**
 * Story 4.1 - fe/be: display the coordinator review queue.
 * AC1 the queue lists requests awaiting a decision, assigned to the signed-in coordinator.
 * AC2 each entry shows the event name, organiser, proposed date and submission date.
 * AC3 the queue can be ordered by submission date or proposed event date.
 * AC4 drafts and already-decided requests never appear.
 * Ordering across several rows, the coordinator filter, malformed input, and 401/403/422
 * refusals are backend cases: backend/tests/events/test_review_queue.py.
 * The page also shows a Planning/Confirmed/Completed tab strip (the coordinator dashboard
 * shape from the finalised prototype); only Under Review is wired to real data so far.
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
  await expect(page.getByRole('tab', { name: 'Under Review (4)' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
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

  await expect(page.getByText('Nothing is waiting for your decision.')).toBeVisible()
  await expect(queueCard(page, 'Data Literacy Workshop')).toHaveCount(0)
})

test('4.1 AC3: the queue can be ordered by submission date or proposed event date', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  const titles = () =>
    page.getByRole('main').getByRole('heading', { level: 3 }).allTextContents()

  // Default: submission date, earliest first.
  await expect.poll(titles).toEqual([
    'Diversity & Inclusion Forum',
    'Data Literacy Workshop',
    'Nimbus Leadership Offsite',
    'Wellness Week Kickoff',
  ])

  await page.getByLabel('Order by').selectOption({ label: 'Proposed event date' })

  await expect.poll(titles).toEqual([
    'Wellness Week Kickoff',
    'Diversity & Inclusion Forum',
    'Data Literacy Workshop',
    'Nimbus Leadership Offsite',
  ])
})

test('4.1 AC4: drafts and decided requests are not listed', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await expect(queueCard(page, 'Q1 Sales Kick-off')).toHaveCount(0)
  await expect(queueCard(page, 'Nimbus Developer Conference')).toHaveCount(0)
  await expect(queueCard(page, 'Rooftop Networking Night')).toHaveCount(0)
})

test('4.1: the queue can be searched by event or organiser', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

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

test('4.1: the Planning, Confirmed and Completed tabs are placeholders until their stories land', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await page.getByRole('tab', { name: 'Planning' }).click()
  await expect(page.getByText('Events in planning will appear here in a later story.')).toBeVisible()
  await expect(page.getByLabel('Search requests')).toHaveCount(0)
  await expect(queueCard(page, 'Data Literacy Workshop')).toHaveCount(0)

  await page.getByRole('tab', { name: 'Confirmed' }).click()
  await expect(
    page.getByText('Confirmed events will appear here in a later story.'),
  ).toBeVisible()

  await page.getByRole('tab', { name: 'Completed' }).click()
  await expect(
    page.getByText('Completed events will appear here in a later story.'),
  ).toBeVisible()

  await page.getByRole('tab', { name: 'Under Review (4)' }).click()
  await expect(queueCard(page, 'Data Literacy Workshop')).toBeVisible()
  await expect(page.getByLabel('Search requests')).toBeVisible()
})
