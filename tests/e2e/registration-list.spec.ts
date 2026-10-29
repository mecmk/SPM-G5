/**
 * Story 18.3 - fe/be: the registration list for my event.
 * AC1 Shows attendee name, email, registration time and status, plus the active count against
 *     capacity: the organiser reads the count on the event's page and who registered on the
 *     registrations report it links to; the assigned coordinator reads the count on the event page
 *     too, and reaches the report from the navigation. An event that does not take registrations
 *     offers neither.
 * AC3 No registrations shows an empty message. When the count reaches capacity, the list shows
 *     "Full".
 * AC4 Withdrawn registrations are marked as such and not counted: a withdrawn row shows when.
 * AC7 The count always matches the list as loaded: Load more adds the next page and its counts,
 *     and never to another event's list.
 * Every other case (AC2, AC4-AC7: the server's count, which rows count, paging bounds, the 404s
 * and 401) is a backend case: backend/tests/registrations/test_registration_list_integration.py.
 *
 * Every event is seeded and only read (EVENTS.portfolioReview, wineAppreciation, confirmed,
 * heritageTrail): a full event and a closed one, so no other spec can register for either, one
 * not taking registrations, and one Aiden withdrew from. The paging tests stub the list call.
 */
import { expect, test, type Page, type Request, type Route } from '@playwright/test'
import { ACCOUNTS, EVENTS, corsHeaders, signIn } from './support'

function registrations(page: Page) {
  return page.getByRole('region', {
    name: 'Registered attendees',
    exact: true,
  })
}

function registrationCard(page: Page) {
  return page.getByRole('region', { name: 'Registration', exact: true })
}

test('18.3 AC1/AC3: the organiser sees who registered, with the count against capacity and Full', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.portfolioReview}`)

  // The event page shows only the count; the list is on the registrations report.
  const summary = registrationCard(page)
  await expect(summary).toContainText('1 / 1')
  await expect(summary.getByText('Full', { exact: true })).toBeVisible()
  await expect(registrations(page)).toHaveCount(0)
  await summary.getByRole('link', { name: 'View registrations' }).click()
  await expect(page).toHaveURL(/\/registrations\/report\?event=/)

  const list = registrations(page)
  const row = list.getByRole('row', { name: /Bella Attendee/ })
  await expect(row).toContainText('attendee2@example.com')
  await expect(row).toContainText('Registered')
  await expect(row).toContainText('11 Oct 2026')
  await expect(list).toContainText('1 / 1')
  await expect(list.getByText('Full', { exact: true })).toBeVisible()
})

test('18.3 AC1: an event that does not take registrations offers no count or link', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  // The card asks for the count either way; once it has answered, nothing is shown.
  const answered = page.waitForResponse((response) =>
    response.url().includes(`/events/${EVENTS.confirmed}/registrations`),
  )
  await page.goto(`/events/${EVENTS.confirmed}`)
  await answered

  const summary = registrationCard(page)
  await expect(summary).toContainText('No')
  await expect(summary.getByRole('link', { name: 'View registrations' })).toHaveCount(0)
  await expect(summary.getByText('Registered', { exact: true })).toHaveCount(0)
})

test('18.3 AC1/AC3: the assigned coordinator reads the count, then that no one has registered yet', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto(`/events/${EVENTS.wineAppreciation}`)

  const summary = registrationCard(page)
  await expect(summary).toContainText('0 / 40')
  await expect(summary.getByText('Full', { exact: true })).toHaveCount(0)
  await summary.getByRole('link', { name: 'View registrations' }).click()

  const list = registrations(page)
  await expect(list).toContainText('No one has registered yet.')
  await expect(list).toContainText('0 / 40')
  await expect(list.getByText('Full', { exact: true })).toHaveCount(0)

  // The report is in the navigation too, with no event picked until one is chosen.
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Registrations', exact: true })
    .click()
  await expect(page).toHaveURL(/\/registrations\/report$/)
  await expect(registrations(page)).toHaveCount(0)
  await page.getByLabel('Event').selectOption(EVENTS.wineAppreciation)
  await expect(registrations(page)).toContainText('No one has registered yet.')
})

test('18.3 AC4: a withdrawn registration is marked Withdrawn, with when', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/registrations/report?event=${EVENTS.heritageTrail}`)

  const row = registrations(page).getByRole('row', { name: /Aiden Attendee/ })
  await expect(row.getByText('Withdrawn', { exact: true })).toBeVisible()
  await expect(row).toContainText('Thu, 8 Oct 2026, 20:45')
})

/** One registration row as the API sends it. */
function listedRegistration(n: number) {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
    attendee_name: `E2E Attendee ${n}`,
    attendee_email: `e2e${n}@example.com`,
    registered_at: '2026-10-01T01:00:00Z',
    status: 'REGISTERED',
    withdrawn_at: null,
    guest: null,
  }
}

/** Answer `eventId`'s list call with `answer(offset)` instead of the API; the CORS headers
 *  go with it, since the app and the API run on different ports. */
async function stubListCall(
  page: Page,
  eventId: string,
  answer: (offset: number) => Promise<unknown> | unknown,
) {
  await page.route(
    (url) => url.pathname === `/events/${eventId}/registrations`,
    async (route: Route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const offset = Number(new URL(request.url()).searchParams.get('offset') ?? 0)
      const body = await answer(offset)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify(body),
      })
    },
  )
}

test('18.3 AC7: Load more adds the next page and its counts', async ({ page }) => {
  await stubListCall(page, EVENTS.portfolioReview, (offset) => ({
    items: [listedRegistration(offset + 1)],
    total: 2,
    active_count: 2,
    capacity: 100,
    is_full: false,
  }))
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/registrations/report?event=${EVENTS.portfolioReview}`)

  const list = registrations(page)
  await expect(list).toContainText('Showing 1 of 2 registrations')
  await list.getByRole('button', { name: 'Load more' }).click()

  await expect(list.getByRole('row', { name: /E2E Attendee 2/ })).toBeVisible()
  await expect(list.getByRole('row', { name: /E2E Attendee 1/ })).toBeVisible()
  await expect(list).toContainText('2 / 100')
  await expect(list.getByRole('button', { name: 'Load more' })).toHaveCount(0)
})

test('18.3 AC7: a page that arrives after another event is picked stays out of its list', async ({
  page,
}) => {
  let releaseLatePage = () => {}
  const latePageHeld = new Promise<void>((resolve) => (releaseLatePage = resolve))
  await stubListCall(page, EVENTS.portfolioReview, async (offset) => {
    if (offset > 0) await latePageHeld
    return {
      items: [listedRegistration(offset + 1)],
      total: 51,
      active_count: 51,
      capacity: 100,
      is_full: false,
    }
  })
  await stubListCall(page, EVENTS.wineAppreciation, () => ({
    items: [listedRegistration(900)],
    total: 1,
    active_count: 1,
    capacity: 7,
    is_full: false,
  }))
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/registrations/report?event=${EVENTS.portfolioReview}`)

  const list = registrations(page)
  await list.getByRole('button', { name: 'Load more' }).click()
  await page.getByLabel('Event').selectOption(EVENTS.wineAppreciation)
  await expect(list.getByRole('row', { name: /E2E Attendee 900/ })).toBeVisible()

  const latePage = page.waitForResponse((response) =>
    response.url().includes(`/events/${EVENTS.portfolioReview}/registrations?offset=1`),
  )
  releaseLatePage()
  await (await latePage).finished()
  // Two frames: whatever the late page would set has rendered by then.
  await page.evaluate(() => new Promise(requestAnimationFrame))
  await page.evaluate(() => new Promise(requestAnimationFrame))

  await expect(list).toContainText('1 / 7')
  await expect(list.getByRole('row')).toHaveCount(2) // the header and the one attendee
  await expect(list.getByText(/Showing/)).toHaveCount(0)
})
