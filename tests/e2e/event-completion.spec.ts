/**
 * Fix f21.2.2 (story 21.2, Q57) - a Confirmed event becomes Completed once it has ended.
 * AC28 an ended Confirmed event becomes Completed with no one acting.
 *
 * The API completes ended events on a timer whose first pass runs as it starts, so the seeded
 * Autumn Book Swap - Confirmed, Carl's, and over since 3 Oct 2026 - is Completed before any spec
 * runs. When the move happens to the second, who is told, the statuses left alone (AC29, AC30)
 * and an event another action holds (AC31) are backend cases:
 * backend/tests/events/test_complete_ended_events.py.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const BOOK_SWAP = 'Autumn Book Swap'

function queueCard(page: Page, name: string) {
  return page.getByRole('main').getByRole('listitem').filter({ hasText: name })
}

test('21.2 AC28: an ended Confirmed event shows as Completed to its coordinator', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto('/events/inbox')

  await page.getByRole('tab', { name: /^Confirmed/ }).click()
  await expect(queueCard(page, BOOK_SWAP)).toHaveCount(0)

  await page.getByRole('tab', { name: /^Completed/ }).click()
  await expect(queueCard(page, BOOK_SWAP)).toContainText('Completed')

  await page.goto(`/events/${EVENTS.bookSwap}`)
  await expect(page.getByRole('heading', { level: 1, name: BOOK_SWAP })).toBeVisible()
  // The event status comes first; the Clarifications record repeats it further down.
  await expect(page.getByRole('main').getByText('Completed', { exact: true }).first()).toBeVisible()
})
