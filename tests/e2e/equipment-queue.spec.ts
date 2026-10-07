/**
 * Story 15.2 - fe/be: view equipment requests.
 * AC1 the queue lists equipment requests with event name, event dates, item type, quantity,
 *     technical notes and requesting coordinator. Soonest event first is a backend case.
 * AC2 each request shows the quantity available for the event's period and any shortfall. The
 *     calculation itself (other holds, units out of service, the request's own hold) is a backend
 *     case; here the seeded Regional Partner Roadshow's lapel microphones, every one held and then
 *     four put out of service, show that a shortfall reaches the card.
 * AC3 Pending, Accepted and Declined tabs, and an All tab (a team request beyond the AC) that
 *     shows the three together. Which statuses each tab returns, and the counts, are backend
 *     cases.
 * Each card's View details opens its event, and the event page's back link returns to the queue
 * (story 7.1's back link), as Venue Staff's booking cards do.
 * AC5 an empty queue shows a message. No seeded tab is empty, so the list call is stubbed. That a
 *     removed item or a cancelled event's item leaves the queue is a backend case.
 * AC6 other roles cannot reach the queue page. The API's 401/403 refusals are backend cases, and
 *     the sidebar is rbac.spec.ts's.
 * AC4 (boundaries) and AC7 (figures as they stand at each load) are backend cases:
 * backend/tests/equipment/test_view_equipment_requests.py.
 *
 * The roadshow (EVENTS.equipmentRoadshow) and the five events after it in QUEUE_EVENTS are
 * dedicated to this spec and only read here. Other specs send equipment to Technical Support
 * while this one runs, so cards are found by event name, never by how many a tab holds.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, corsHeaders, EVENTS, signIn } from './support'

const QUEUE_PATH = '/equipment/requests'
const ROADSHOW = 'Regional Partner Roadshow'
/** The seeded events with pending requests, soonest first (backend/db/seed/020_sample_data.sql). */
const PENDING_EVENTS_IN_ORDER = [
  ROADSHOW,
  'Fintech Leaders Breakfast',
  'Customer Success Forum',
  'Annual Sales Kickoff',
  'Graduate Recruitment Fair',
]

function roadshowCard(page: Page) {
  return page.getByRole('listitem').filter({ hasText: ROADSHOW })
}

test('15.2 AC1/AC2: Technical Support open the queue and see a request with its figures', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Equipment requests', exact: true })
    .click()

  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}$`))
  await expect(page.getByRole('heading', { name: 'Equipment Requests', level: 1 })).toBeVisible()
  await expect(page.getByRole('tab', { name: /^Pending/ })).toHaveAttribute('aria-selected', 'true')

  const card = roadshowCard(page)
  await expect(card.getByRole('heading', { name: ROADSHOW })).toBeVisible()
  await expect(card).toContainText('16 Jun 2027')
  await expect(card).toContainText('Lapel microphone')
  await expect(card).toContainText('One per panel speaker')
  await expect(card).toContainText('Chloe Coordinator')
  await expect(card.getByText('Requested', { exact: true })).toBeVisible()
  await expect(card.getByText('Available for this event', { exact: true })).toBeVisible()
  await expect(card.getByText('Short by 4')).toBeVisible()
})

test('15.2 AC1: the seeded requests are listed across their events, soonest event first', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await expect(roadshowCard(page)).toContainText('Lapel microphone')

  const titles = await page.getByRole('listitem').getByRole('heading', { level: 3 }).allInnerTexts()
  const seeded = titles.filter((title) => PENDING_EVENTS_IN_ORDER.includes(title))
  const firstSeen = seeded.filter((title, index) => seeded.indexOf(title) === index)

  expect(firstSeen).toEqual(PENDING_EVENTS_IN_ORDER)
  // Each event's requests sit together, since the queue is ordered by event.
  expect(seeded).toEqual(
    [...seeded].sort(
      (a, b) => PENDING_EVENTS_IN_ORDER.indexOf(a) - PENDING_EVENTS_IN_ORDER.indexOf(b),
    ),
  )
})

test('15.2 AC3: the Accepted and Declined tabs show decided requests', async ({ page }) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await expect(roadshowCard(page)).toContainText('Lapel microphone')

  await page.getByRole('tab', { name: /^Accepted/ }).click()
  await expect(roadshowCard(page)).toContainText('Wireless microphone')
  await expect(roadshowCard(page)).not.toContainText('Lapel microphone')

  await page.getByRole('tab', { name: /^Declined/ }).click()
  await expect(roadshowCard(page)).toContainText('Portable projector')
  await expect(roadshowCard(page)).not.toContainText('Wireless microphone')
})

test('15.2 AC3: the All tab shows pending, accepted and declined requests together', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)
  await expect(roadshowCard(page)).toHaveCount(1)

  await page.getByRole('tab', { name: /^All/ }).click()

  await expect(page.getByRole('tab', { name: /^All/ })).toHaveAttribute('aria-selected', 'true')
  await expect(roadshowCard(page)).toHaveCount(3)
  await expect(roadshowCard(page).filter({ hasText: 'Lapel microphone' })).toContainText('Pending')
  await expect(roadshowCard(page).filter({ hasText: 'Wireless microphone' })).toContainText(
    'Accepted',
  )
  await expect(roadshowCard(page).filter({ hasText: 'Portable projector' })).toContainText(
    'Declined',
  )
})

test('15.2 AC1: View details opens the event, and its back link returns to the queue', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  await roadshowCard(page).getByRole('link', { name: 'View details' }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${EVENTS.equipmentRoadshow}$`))
  await expect(page.getByRole('heading', { name: ROADSHOW, level: 1 })).toBeVisible()
  await expect(page.getByText('One per panel speaker')).toBeVisible()

  await page.getByRole('link', { name: '← Equipment Requests' }).click()
  await expect(page).toHaveURL(new RegExp(`${QUEUE_PATH}$`))
  await expect(page.getByRole('heading', { name: 'Equipment Requests', level: 1 })).toBeVisible()
})

test('15.2 AC5: an empty queue shows a message', async ({ page }) => {
  await page.route(
    (url) => url.pathname === '/equipment-requests',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], counts: { pending: 0, accepted: 0, declined: 0 } }),
        headers: corsHeaders(request),
      })
    },
  )
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(QUEUE_PATH)

  await expect(page.getByText('No equipment requests waiting. You are up to date.')).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Pending (0)' })).toBeVisible()
})

test('15.2 AC6: another role is refused the queue page', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(QUEUE_PATH)

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Equipment Requests' })).toHaveCount(0)
})
