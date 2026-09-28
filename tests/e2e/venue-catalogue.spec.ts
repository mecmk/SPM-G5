/**
 * Story 8.1: browse the venue catalogue - with 10.1 merged in for Sprint 2 (built as s8.1): the
 * filter panel, the search on the server, and the filters kept in the page address.
 *
 * AC1  All venues in service are listed with name, location and capacity; selecting one opens
 *      its full record.
 * AC2  Withdrawn venues are not listed.
 * AC3  One filter panel: capacity, start and end, name or location, facilities, accessibility
 *      features and room layout. Only venues matching every criterion and free for the period
 *      are listed: not booked or held, not closed for maintenance, not closed at those hours.
 *      Raising Capacity from or From past the other end takes that end along.
 * AC4  The filters live in the page address, so a search can be bookmarked and reloaded. Opened
 *      from an event's Find a venue (f12.1.1), the panel is filled in from that address and
 *      matching venues show straight away.
 * AC5  Only the event's assigned coordinator is offered Request this venue; Venue Staff and
 *      Technical Support browse and filter too.
 * AC8  A search that cannot be run (a start in the past, an end before the start) says why beside
 *      the panel and leaves the results as they were.
 * AC9  Nothing matches: the page names the filter whose removal would give results; Clear filters
 *      resets the panel.
 * AC11 The filters stay set while a venue is opened, its calendar moved, and the list returned to.
 * AC12 (f8.1.1) Venue Staff manage venues from this catalogue: tests/e2e/venues.spec.ts.
 * A request refused because the venue stopped being available (12.1 AC14) is in
 * booking-requests.spec.ts, beside the request step's other cases.
 *
 * The rules themselves - every filter's boundaries, the availability rules, what each refusal
 * says, the counts behind "Try removing", who may search - are backend cases:
 * backend/tests/venues/test_venue_search.py and backend/tests/bookings/
 * test_request_rechecks_venue.py. Nothing here sends a request, so every case can use the seed:
 * Grand Hall (400, Theatre, booked for Nimbus Developer Conference on 25 Nov 2026), Seminar Room
 * 2.1 (80, closed for maintenance 2-4 Nov 2026), Boardroom 3.4 (16), Exhibition Foyer (250, no
 * opening hours recorded) and the withdrawn Old Annex Room.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const NIMBUS = { id: EVENTS.approved, name: 'Nimbus Developer Conference' }
const SUMMIT = { id: EVENTS.planning, name: 'Regional Sales Summit' }
const IN_SERVICE = ['Grand Hall', 'Seminar Room 2.1', 'Boardroom 3.4', 'Exhibition Foyer']

/** The address Find a venue writes for Regional Sales Summit (f12.1.1's contract). */
const SUMMIT_SEARCH = new URLSearchParams({
  event: SUMMIT.id,
  capacity: '220',
  from: '2026-12-15T09:00',
  to: '2026-12-16T17:00',
  layout: 'THEATRE',
})

function panel(page: Page) {
  return page.getByRole('complementary', { name: 'Filters' })
}

function catalogueBanner(page: Page, eventName: string) {
  return page.getByRole('region', { name: `Finding a venue for ${eventName}` })
}

/** The catalogue as its coordinator reaches it from an event's page (f12.1.1). */
async function findVenueFor(page: Page, event: { id: string; name: string }) {
  await page.goto(`/events/${event.id}`)
  await expect(page.getByRole('heading', { name: event.name, level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(catalogueBanner(page, event.name)).toBeVisible()
}

async function expectListed(page: Page, listed: string[], notListed: string[]) {
  for (const name of listed) await expect(venueCard(page, name)).toBeVisible()
  for (const name of notListed) await expect(venueCard(page, name)).toHaveCount(0)
}

test('8.1 AC1/AC2: the catalogue lists in-service venues with name, location and capacity, excluding withdrawn ones', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await expect(page.getByRole('heading', { name: 'Venue catalogue', level: 1 })).toBeVisible()
  const grandHall = venueCard(page, 'Grand Hall')
  await expect(grandHall).toContainText('Tower A, Level 1')
  await expect(grandHall).toContainText('400')

  await expect(venueCard(page, 'Old Annex Room')).toHaveCount(0)
})

test('8.1 AC1: selecting a venue opens its full record', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await page.getByRole('link', { name: 'Grand Hall' }).click()

  await expect(page).toHaveURL(/\/venues\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Grand Hall' })).toBeVisible()
  await expect(page.getByText('Tower A, Level 1')).toBeVisible()
  await expect(page.getByText('Quick facts')).toBeVisible()
})

test('8.1 AC3: the catalogue can be filtered by a capacity range', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')

  await page.getByLabel('Capacity from').fill('100')
  await page.getByLabel('Capacity to').fill('300')

  await expectListed(page, ['Exhibition Foyer'], ['Grand Hall', 'Boardroom 3.4'])
})

test('8.1 AC3: a name or location of only spaces is no filter', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues?search=%20%20')
  const filters = panel(page)
  const clearFilters = filters.getByRole('button', { name: 'Clear all filters' })
  await expectListed(page, IN_SERVICE, [])
  await expect(clearFilters).toHaveCount(0)

  await filters.getByLabel('Name or location').fill('hall')
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1'])
  await expect(clearFilters).toBeVisible()
  await filters.getByLabel('Name or location').fill('   ')
  await expectListed(page, IN_SERVICE, [])
  await expect(clearFilters).toHaveCount(0)
  await expect(page).not.toHaveURL(/search=/)
})

test('8.1 AC6: a capacity of 0 or below is no limit, typed or in the address', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues?capacity=0&capacity_max=-5')
  const filters = panel(page)
  await expectListed(page, IN_SERVICE, [])
  await expect(filters.getByRole('alert')).toHaveCount(0)

  await filters.getByLabel('Capacity from').fill('300')
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1'])
  await filters.getByLabel('Capacity from').fill('0')
  await expectListed(page, IN_SERVICE, [])

  await filters.getByLabel('Capacity to').fill('20')
  await expectListed(page, ['Boardroom 3.4'], ['Grand Hall'])
  await filters.getByLabel('Capacity to').fill('-5')
  await expectListed(page, IN_SERVICE, [])
  await expect(page).not.toHaveURL(/capacity(_max)?=/)
  await expect(filters.getByRole('alert')).toHaveCount(0)
})

test('8.1 AC3: raising Capacity from past Capacity to takes Capacity to up with it', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  const filters = panel(page)
  await filters.getByLabel('Capacity from').fill('50')
  await filters.getByLabel('Capacity to').fill('60')
  await expect(page).toHaveURL(/capacity_max=60/)

  await filters.getByLabel('Capacity from').fill('80')

  await expect(filters.getByLabel('Capacity to')).toHaveValue('80')
  await expect(page).toHaveURL(/capacity=80&capacity_max=80/)
  await expectListed(page, ['Seminar Room 2.1'], ['Grand Hall', 'Exhibition Foyer'])
  await expect(filters.getByRole('alert')).toHaveCount(0)
})

test('8.1 AC3: moving From past To moves To with it, keeping the period as long', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  const filters = panel(page)
  await filters.getByLabel('From', { exact: true }).fill('2027-03-01T09:00')
  await filters.getByLabel('To', { exact: true }).fill('2027-03-01T12:00')

  await filters.getByLabel('From', { exact: true }).fill('2027-03-02T10:00')

  await expect(filters.getByLabel('To', { exact: true })).toHaveValue('2027-03-02T13:00')
  await expect(page).toHaveURL(/from=2027-03-02T10%3A00&to=2027-03-02T13%3A00/)
  await expectListed(page, IN_SERVICE, [])
  await expect(filters.getByRole('alert')).toHaveCount(0)
})

test('8.1 AC3: each filter narrows the catalogue', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await expectListed(page, IN_SERVICE, [])
  const filters = panel(page)
  const clearFilters = filters.getByRole('button', { name: 'Clear all filters' })

  await filters.getByRole('checkbox', { name: 'Video conferencing', exact: true }).check()
  await expectListed(
    page,
    ['Seminar Room 2.1', 'Boardroom 3.4'],
    ['Grand Hall', 'Exhibition Foyer'],
  )

  await filters.getByRole('checkbox', { name: 'Wheelchair access', exact: true }).check()
  await expectListed(page, ['Seminar Room 2.1'], ['Boardroom 3.4'])

  await clearFilters.click()
  await filters.getByLabel('Layout').selectOption({ label: 'Exhibition' })
  await expectListed(
    page,
    ['Grand Hall', 'Exhibition Foyer'],
    ['Seminar Room 2.1', 'Boardroom 3.4'],
  )

  await clearFilters.click()
  await filters.getByLabel('Name or location').fill('tower b')
  await expectListed(
    page,
    ['Boardroom 3.4', 'Exhibition Foyer'],
    ['Grand Hall', 'Seminar Room 2.1'],
  )
})

test('8.1 AC3: a venue closed for maintenance is hidden for those dates', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  const filters = panel(page)

  // Seminar Room 2.1 is closed for air-con servicing from 2 Nov 00:00 to 4 Nov 00:00.
  await filters.getByLabel('From', { exact: true }).fill('2026-11-03T09:00')
  await filters.getByLabel('To', { exact: true }).fill('2026-11-03T12:00')
  await expectListed(page, ['Grand Hall', 'Exhibition Foyer'], ['Seminar Room 2.1'])
  // Exhibition Foyer has no opening hours recorded, so it stays, saying so.
  await expect(venueCard(page, 'Exhibition Foyer')).toContainText('Opening hours not recorded')
  await expect(venueCard(page, 'Grand Hall')).not.toContainText('Opening hours not recorded')

  await filters.getByLabel('From', { exact: true }).fill('2026-11-04T09:00')
  await filters.getByLabel('To', { exact: true }).fill('2026-11-04T12:00')
  await expectListed(page, ['Seminar Room 2.1', 'Grand Hall'], [])
})

test('8.1 AC4: opened from an event, the panel is filled in and matching venues show', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)
  const filters = panel(page)

  await expect(filters.getByLabel('Capacity from')).toHaveValue('220')
  await expect(filters.getByLabel('From', { exact: true })).toHaveValue('2026-12-15T09:00')
  await expect(filters.getByLabel('To', { exact: true })).toHaveValue('2026-12-16T17:00')
  await expect(filters.getByLabel('Layout')).toHaveValue('THEATRE')
  // Theatre for 220 people over both days: only Grand Hall, straight away.
  await expectListed(
    page,
    ['Grand Hall'],
    ['Seminar Room 2.1', 'Boardroom 3.4', 'Exhibition Foyer'],
  )
})

test.describe('with the browser in New York', () => {
  test.use({ timezoneId: 'America/New_York' })

  test("8.1 AC4: the panel's dates are Singapore time wherever the browser is", async ({
    page,
  }) => {
    await signIn(page, ACCOUNTS.coordinator)
    await findVenueFor(page, SUMMIT)

    // 09:00 in Singapore is 20:00 the day before in New York; the panel must not shift.
    await expect(panel(page).getByLabel('From', { exact: true })).toHaveValue('2026-12-15T09:00')
    await expect(venueCard(page, 'Grand Hall')).toBeVisible()
  })
})

test('8.1 AC4: the filters live in the page address', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  const filters = panel(page)

  await filters.getByLabel('Name or location').fill('hall')
  await filters.getByLabel('Layout').selectOption({ label: 'Theatre' })

  await expect(page).toHaveURL(/[?&]search=hall(&|$)/)
  await expect(page).toHaveURL(/[?&]layout=THEATRE(&|$)/)
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1', 'Exhibition Foyer'])

  await page.reload()

  await expect(filters.getByLabel('Name or location')).toHaveValue('hall')
  await expect(filters.getByLabel('Layout')).toHaveValue('THEATRE')
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1', 'Exhibition Foyer'])
})

test('8.1 AC8: a search that cannot be run says why and keeps the results', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venues')
  await expectListed(page, IN_SERVICE, [])
  const filters = panel(page)

  await filters.getByLabel('From', { exact: true }).fill('2025-01-06T09:00')
  await filters.getByLabel('To', { exact: true }).fill('2025-01-06T12:00')
  await expect(filters.getByRole('alert')).toHaveText('Searches cannot start in the past.')
  await expectListed(page, IN_SERVICE, [])

  await filters.getByLabel('From', { exact: true }).fill('2027-01-06T12:00')
  await filters.getByLabel('To', { exact: true }).fill('2027-01-06T09:00')
  await expect(filters.getByRole('alert')).toHaveText(
    'The end of the range must be after its start.',
  )
  await expectListed(page, IN_SERVICE, [])
})

test('8.1 AC9: when nothing matches, the page says which filter to remove', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  // Only Grand Hall fits Nimbus, and it is booked for Nimbus itself that day.
  await findVenueFor(page, NIMBUS)

  await expect(page.getByText('No venues match these filters.')).toBeVisible()
  await expect(page.getByText('Try removing:')).toBeVisible()
  const removeDates = page.getByRole('button', { name: 'Dates (1 venue)' })
  await expect(removeDates).toBeVisible()

  await removeDates.click()
  await expectListed(page, ['Grand Hall'], ['Seminar Room 2.1'])
  await expect(panel(page).getByLabel('From', { exact: true })).toHaveValue('')

  await panel(page).getByRole('button', { name: 'Clear all filters' }).click()
  await expectListed(page, IN_SERVICE, [])
  await expect(panel(page).getByLabel('Capacity from')).toHaveValue('')
  // The event is not a filter: the page still finds a venue for Nimbus.
  await expect(catalogueBanner(page, NIMBUS.name)).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`[?&]event=${NIMBUS.id}(&|$)`))
})

test('8.1 AC11: the filters stay set while a venue is opened and its calendar moved', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await findVenueFor(page, SUMMIT)
  const address = page.url()

  await venueCard(page, 'Grand Hall').getByRole('link', { name: 'Grand Hall' }).click()
  await expect(page.getByRole('heading', { name: 'Grand Hall', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: /Next/ }).click()
  await page.getByRole('link', { name: '← Venue catalogue' }).click()

  expect(page.url()).toBe(address)
  await expect(panel(page).getByLabel('Capacity from')).toHaveValue('220')
  await expect(panel(page).getByLabel('Layout')).toHaveValue('THEATRE')
  await expectListed(page, ['Grand Hall'], ['Exhibition Foyer'])
})

for (const viewer of [
  { who: 'Venue Staff', email: ACCOUNTS.venueStaff },
  { who: 'Technical Support', email: ACCOUNTS.techSupport },
]) {
  test(`8.1 AC5: ${viewer.who} filter the catalogue but are offered no request`, async ({
    page,
  }) => {
    await signIn(page, viewer.email)
    // The address a coordinator's Find a venue writes, shared with them.
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith(`/events/${SUMMIT.id}`)),
      page.goto(`/venues?${SUMMIT_SEARCH}`),
    ])

    await expect(panel(page).getByLabel('Capacity from')).toHaveValue('220')
    await expectListed(page, ['Grand Hall'], ['Exhibition Foyer'])
    await expect(catalogueBanner(page, SUMMIT.name)).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Request this venue' })).toHaveCount(0)

    await panel(page).getByLabel('Name or location').fill('seminar')
    await expectListed(page, [], ['Grand Hall'])
    await expect(page.getByText('No venues match these filters.')).toBeVisible()
  })
}
