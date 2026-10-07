/**
 * Story 11.1 - venue suitability with reasons and override: what the coordinator sees.
 *
 * AC1  In event context each catalogue result shows Suitable or Unsuitable for the event's venue
 *      requirement, and an unsuitable one lists each failed criterion with the requirement's value
 *      and the venue's ("Capacity 16 < 60 people"). The requirement is named only when the event
 *      has several; where a layout's own capacity was compared, the layout is named.
 * AC5  A characteristic the venue has not recorded reads "Unknown". No indicator appears outside
 *      event context.
 * AC6  Only the event's assigned coordinator sees indicators. The catalogue asks for them only
 *      once the event in its address has resolved to one the user may request a venue for, so a
 *      fake or someone else's event is searched without it, and arriving sends one search, not a
 *      search without the event followed by one with it.
 *
 * The runner serves the development build, where React's StrictMode runs each effect twice, so one
 * search can go out twice, identically (useLoaded keeps only the second answer). The tests count
 * distinct queries: two different ones on arrival would be the double fetch that shows as flicker.
 *
 * Seed: Quarterly Partner Briefing (Chloe's; 60 people, Classroom, a projector) judged against
 * Seminar Room 2.1 (suits), Boardroom 3.4 (16 seats, no Classroom, no projector) and Grand Hall (no
 * Classroom). Every verdict and its rules are backend tests (backend/tests/venues/
 * test_venue_suitability.py); these prove the page shows them. No seeded pair has an Unknown
 * characteristic or an event with several requirements, so E3/E4 take the real search answer and
 * change only its values.
 */
import { expect, test, type Page, type Request } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn, venueCard } from './support'

const BRIEFING = { id: EVENTS.partnerBriefing, name: 'Quarterly Partner Briefing' }
const SEARCH_PATH = '/venues/search'
const EVENT_PARAM = 'event'

/** Every catalogue search the page sends, from now on. */
function recordSearches(page: Page): URL[] {
  const searches: URL[] = []
  page.on('request', (request: Request) => {
    const url = new URL(request.url())
    if (request.resourceType() === 'fetch' && url.pathname === SEARCH_PATH) searches.push(url)
  })
  return searches
}

/** The distinct queries among `searches`: the same search sent twice by StrictMode counts once. */
function distinctQueries(searches: URL[]): string[] {
  return [...new Set(searches.map((url) => url.search))]
}

/** The catalogue as the coordinator reaches it from the event's page: filtered to the event. */
async function openBriefingCatalogue(page: Page) {
  await page.goto(`/events/${BRIEFING.id}`)
  await expect(page.getByRole('heading', { name: BRIEFING.name, level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(
    page.getByRole('region', { name: `Finding a venue for ${BRIEFING.name}` }),
  ).toBeVisible()
}

/** Every filter cleared, so venues that do not suit are listed too (the event stays). */
async function clearFilters(page: Page) {
  await page
    .getByRole('complementary', { name: 'Filters' })
    .getByRole('button', { name: 'Clear all filters' })
    .click()
  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
}

async function briefingCatalogueUnfiltered(page: Page) {
  await openBriefingCatalogue(page)
  await clearFilters(page)
}

function tag(page: Page, venue: string, label: string) {
  return venueCard(page, venue).getByText(label, { exact: true })
}

test("11.1 AC1: in an event's catalogue each venue shows Suitable or Unsuitable, and why", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const searches = recordSearches(page)

  const arrived = page.waitForResponse(
    (response) => new URL(response.url()).pathname === SEARCH_PATH,
  )
  await openBriefingCatalogue(page)
  // Arriving sent one search, carrying the event - none without it first. Checked when the first
  // answer comes, whatever it lists: filtered to Briefing's day, a venue another spec has just
  // requested for that day (booking-requests.spec.ts holds Seminar Room) is not listed.
  await arrived
  const arrival = distinctQueries(searches)
  expect(arrival).toHaveLength(1)
  expect(new URLSearchParams(arrival[0]).get(EVENT_PARAM)).toBe(BRIEFING.id)

  await clearFilters(page)

  await expect(tag(page, 'Seminar Room 2.1', 'Suitable')).toBeVisible()
  const boardroom = venueCard(page, 'Boardroom 3.4')
  await expect(tag(page, 'Boardroom 3.4', 'Unsuitable')).toBeVisible()
  await expect(boardroom.getByText('Capacity 16 < 60 people', { exact: true })).toBeVisible()
  await expect(boardroom.getByText('Layout Classroom not offered', { exact: true })).toBeVisible()
  await expect(boardroom.getByText('Projector & screen not offered', { exact: true })).toBeVisible()
  await expect(tag(page, 'Grand Hall', 'Unsuitable')).toBeVisible()
  await expect(
    venueCard(page, 'Grand Hall').getByText('Layout Classroom not offered'),
  ).toBeVisible()
  // Briefing has one venue requirement, so it is not named.
  await expect(page.getByText(/Unsuitable for|Suitable for/)).toHaveCount(0)
  // Clearing the filters searched again, still with the event.
  expect(searches.every((url) => url.searchParams.get(EVENT_PARAM) === BRIEFING.id)).toBe(true)
})

test('11.1 AC5: the catalogue outside an event shows no indicator', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  const searches = recordSearches(page)

  await page.goto('/venues')

  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
  await expect(page.getByText(/^(Suitable|Unsuitable)/)).toHaveCount(0)
  expect(searches.every((url) => !url.searchParams.has(EVENT_PARAM))).toBe(true)
})

test('11.1 AC6: an event in the address that does not exist is not sent with the search', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  const searches = recordSearches(page)

  await page.goto(`/venues?event=${crypto.randomUUID()}`)

  // The event has resolved (to "not found") once its alert shows.
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
  await expect(page.getByText(/^(Suitable|Unsuitable)/)).toHaveCount(0)
  const queries = distinctQueries(searches)
  expect(queries).toHaveLength(1)
  expect(new URLSearchParams(queries[0]).has(EVENT_PARAM)).toBe(false)
})

test("11.1 AC6: Venue Staff in an event's catalogue see no indicator and send no event", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  const searches = recordSearches(page)
  const eventLoaded = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith(`/events/${BRIEFING.id}`),
  )

  await page.goto(`/venues?event=${BRIEFING.id}`)

  await eventLoaded
  await expect(venueCard(page, 'Boardroom 3.4')).toBeVisible()
  await expect(page.getByText(/^(Suitable|Unsuitable)/)).toHaveCount(0)
  const queries = distinctQueries(searches)
  expect(queries).toHaveLength(1)
  expect(new URLSearchParams(queries[0]).has(EVENT_PARAM)).toBe(false)
})

/** Hits from the real search answer, by venue name, for a stub to change. */
interface Hit {
  name: string
  suitability: { failures: Record<string, unknown>[] } | null
}

/**
 * Answers the event's catalogue searches with the real answer, changed by `change` - so the shape
 * is the server's own and only the values differ. Only a search whose answer lists every venue
 * the change edits is changed: the catalogue's first search is still filtered to the event, and
 * lists Seminar Room alone. Only the API's `fetch` is stubbed, never the page's navigation.
 */
async function changeSearchAnswer(
  page: Page,
  venues: readonly string[],
  change: (hits: Map<string, Hit>) => void,
) {
  await page.route(
    (url) => url.pathname === SEARCH_PATH && url.searchParams.get(EVENT_PARAM) === BRIEFING.id,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      const body = await response.json()
      const hits = new Map((body.venues as Hit[]).map((hit) => [hit.name, hit]))
      if (venues.every((name) => hits.has(name))) change(hits)
      return route.fulfill({ response, json: body })
    },
  )
}

/** The real failure of `criterion` on `hit`, to change the values of. */
function realFailure(hit: Hit | undefined, criterion: string) {
  const failure = hit?.suitability?.failures.find((each) => each.criterion === criterion)
  if (failure === undefined) throw new Error(`the real answer has no ${criterion} failure`)
  return failure
}

test('11.1 AC1: with several requirements the tag names the one judged, and says which layout was compared', async ({
  page,
}) => {
  // The event answered with a second requirement, copied from its real first one.
  await page.route(`**/events/${BRIEFING.id}`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.fallback()
    const response = await route.fetch()
    const event = await response.json()
    const [first] = event.venue_requirements
    const breakout = { ...first, id: crypto.randomUUID(), position: 1, name: 'Breakout' }
    return route.fulfill({
      response,
      json: { ...event, venue_requirements: [first, breakout] },
    })
  })
  await changeSearchAnswer(page, ['Boardroom 3.4'], (hits) => {
    // Boardroom's real capacity failure, as if its Classroom layout seated 12.
    Object.assign(realFailure(hits.get('Boardroom 3.4'), 'CAPACITY'), {
      code: 'CLASSROOM',
      name: 'Classroom',
      venue_value: 12,
    })
    // Its real projector failure, as if it had 2 of the 3 needed.
    Object.assign(realFailure(hits.get('Boardroom 3.4'), 'FACILITY'), {
      criterion: 'FACILITY_QUANTITY',
      required: 3,
      venue_value: 2,
    })
  })
  await signIn(page, ACCOUNTS.coordinator)

  await briefingCatalogueUnfiltered(page)

  const boardroom = venueCard(page, 'Boardroom 3.4')
  await expect(boardroom.getByText('Unsuitable for Main venue', { exact: true })).toBeVisible()
  await expect(
    boardroom.getByText('Capacity in Classroom 12 < 60 people', { exact: true }),
  ).toBeVisible()
  await expect(
    boardroom.getByText('Projector & screen: 2 available, 3 needed', { exact: true }),
  ).toBeVisible()
  await expect(
    venueCard(page, 'Seminar Room 2.1').getByText('Suitable for Main venue', { exact: true }),
  ).toBeVisible()
})

test('11.1 AC5: a characteristic the venue has not recorded reads Unknown', async ({ page }) => {
  await changeSearchAnswer(page, ['Boardroom 3.4', 'Grand Hall'], (hits) => {
    const boardroom = hits.get('Boardroom 3.4')
    // Boardroom's real failures, each as if the venue had recorded nothing of that kind.
    Object.assign(realFailure(boardroom, 'LAYOUT'), { outcome: 'UNKNOWN' })
    Object.assign(realFailure(boardroom, 'FACILITY'), { outcome: 'UNKNOWN' })
    // Two more failures on Grand Hall, each a copy of its real layout failure with only the
    // values changed: an accessibility need and a quantity it did not record.
    const grandHall = hits.get('Grand Hall')
    const layout = realFailure(grandHall, 'LAYOUT')
    grandHall?.suitability?.failures.push(
      {
        ...layout,
        criterion: 'ACCESSIBILITY',
        code: 'HEARING_LOOP',
        name: 'Hearing loop',
        outcome: 'UNKNOWN',
      },
      {
        ...layout,
        criterion: 'FACILITY_QUANTITY',
        code: 'PROJECTOR',
        name: 'Projector & screen',
        outcome: 'UNKNOWN',
        required: 3,
        venue_value: null,
      },
    )
  })
  await signIn(page, ACCOUNTS.coordinator)

  await briefingCatalogueUnfiltered(page)

  const boardroom = venueCard(page, 'Boardroom 3.4')
  await expect(boardroom.getByText('Layout Classroom: Unknown', { exact: true })).toBeVisible()
  await expect(boardroom.getByText('Projector & screen: Unknown', { exact: true })).toBeVisible()
  const grandHall = venueCard(page, 'Grand Hall')
  await expect(grandHall.getByText('Hearing loop: Unknown', { exact: true })).toBeVisible()
  await expect(grandHall.getByText('Projector & screen ×3: Unknown', { exact: true })).toBeVisible()
})
