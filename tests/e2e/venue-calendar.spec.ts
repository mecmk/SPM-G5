/**
 * Story 9.1: venue availability calendar.
 * AC1 a calendar view shows availability for one venue across a selectable range of dates.
 * AC2 each period is shown as available or unavailable.
 * AC3 the view is restricted to authorised internal users - fully covered as a backend case:
 * backend/tests/venues/test_venue_calendar.py::test_calendar_is_restricted_to_internal_roles.
 * The calendar opens on the current month (September 2026), so these navigate forward to
 * November 2026, where the seed data's booking and maintenance period live.
 *
 * Bug f9.1.1: two regression tests below stub the calendar fetch (tests/CLAUDE.md's slow/failing
 * request exception) to cover the Previous/Next transition itself, not just the end state.
 */
import { expect, test, type Page, type Route } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

/** The "Availability" card - a region via its `aria-labelledby`, same pattern as
 *  venue-detail.spec.ts's cardSection(). */
function availabilitySection(page: Page) {
  return page.getByRole('region', { name: 'Availability', exact: true })
}

async function goToNovember2026(page: Page) {
  const section = availabilitySection(page)
  for (let i = 0; i < 2; i += 1) {
    await section.getByRole('button', { name: 'Next →' }).click()
  }
  await expect(page.getByText('November 2026')).toBeVisible()
}

test('9.1 AC1/AC2: an approved booking shows as unavailable, with the event as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).toBeVisible()
})

test('9.1 AC1/AC2: a maintenance period shows as unavailable, with its notes as the label', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Seminar Room 2.1' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Annual air-con servicing').first()).toBeVisible()
})

test('9.1 AC1: a venue with nothing booked shows no unavailable days', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Boardroom 3.4' }).click()

  await goToNovember2026(page)

  await expect(page.getByText('Nimbus Developer Conference')).not.toBeVisible()
  await expect(page.getByText('Annual air-con servicing')).not.toBeVisible()
})

test('9.1 AC1: navigating back a month leaves the current month', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()
  await section.getByRole('button', { name: '← Prev' }).click()
  await expect(page.getByText('August 2026')).toBeVisible()
})

/**
 * Intercepts exactly the next matching `/calendar` fetch (falling back to the real network for
 * every other request, including ones before and after it), so a test can control one month's
 * response without disturbing the rest of the page. CORS headers are required since the app and
 * API are on different ports (tests/CLAUDE.md).
 */
async function interceptNextCalendarFetch(page: Page, fulfill: (route: Route) => Promise<void>) {
  let handled = false
  await page.route(
    (url) => /\/venues\/[^/]+\/calendar$/.test(url.pathname),
    async (route) => {
      if (handled || route.request().resourceType() !== 'fetch') return route.fallback()
      handled = true
      await fulfill(route)
    },
  )
}

function corsHeaders(route: Route) {
  return {
    'access-control-allow-origin': route.request().headers()['origin'] ?? '*',
    'access-control-allow-credentials': 'true',
  }
}

/**
 * Regression test for bug f9.1.1: clicking Next/Previous used to unmount the whole calendar
 * (including its own Prev/Next buttons) the instant the new range's fetch started, replacing it
 * with a bare loading message until the fetch resolved - and never brought it back at all if the
 * fetch failed, stranding the user with no way to navigate elsewhere. The regression guard is
 * that the calendar's own controls stay on screen throughout, not just that the data is right.
 */
test('9.1: the calendar and its controls stay visible while the next range is slow to load', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()

  await interceptNextCalendarFetch(page, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
      headers: corsHeaders(route),
    })
  })

  await section.getByRole('button', { name: 'Next →' }).click()

  await expect(page.getByText('October 2026')).toBeVisible()
  await expect(section.getByRole('button', { name: '← Prev' })).toBeVisible()
  await expect(section.getByRole('button', { name: 'Next →' })).toBeVisible()
  await expect(page.getByText('Loading availability…')).toBeVisible()

  await expect(page.getByText('Loading availability…')).not.toBeVisible()
})

test('9.1: a failed re-fetch falls back to an available calendar instead of a dead end', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await page.getByRole('link', { name: 'Grand Hall' }).click()

  const section = availabilitySection(page)
  await expect(page.getByText('September 2026')).toBeVisible()

  await interceptNextCalendarFetch(page, async (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: null }),
      headers: corsHeaders(route),
    }),
  )

  await section.getByRole('button', { name: 'Next →' }).click()

  await expect(page.getByText('October 2026')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('The server hit a problem')
  await expect(section.getByRole('button', { name: '← Prev' })).toBeVisible()

  // Recovers on the next navigation (unstubbed, real network) instead of staying stuck.
  await section.getByRole('button', { name: '← Prev' }).click()
  await expect(page.getByText('September 2026')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})
