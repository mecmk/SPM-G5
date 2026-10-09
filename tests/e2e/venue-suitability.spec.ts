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

// --- The request step: the warning, the justification and the confirmation (AC2, AC3, AC6, AC7) -
// Seeded venue ids. Exhibition Foyer is the one venue E5 really requests for Briefing; E7's real
// send goes to Boardroom 3.4 instead, so E5's hold on Foyer can never turn it into a 409.
const FOYER = { id: '22222222-0000-0000-0000-000000000004', name: 'Exhibition Foyer' }
const SEMINAR_ROOM = { id: '22222222-0000-0000-0000-000000000002', name: 'Seminar Room 2.1' }
const BOARDROOM = { id: '22222222-0000-0000-0000-000000000003', name: 'Boardroom 3.4' }
const SUITABILITY_PATH = (venueId: string) => `/venues/${venueId}/suitability`
const BOOKINGS_PATH = '/bookings'
// As errors/registry.ts words BOOKING_JUSTIFICATION_REQUIRED (the request is never sent).
const JUSTIFICATION_REQUIRED =
  'Give a justification for requesting a venue that does not suit the event.'

/** Briefing's one venue requirement in the seed. Story 12.5: the step's address names the
 * requirement a request is for; without it the request is for an additional venue. */
const BRIEFING_MAIN_VENUE = 'cccccccc-0000-0000-0000-000000000018'

async function openRequestStep(page: Page, venue: { id: string; name: string }) {
  await page.goto(
    `/events/${BRIEFING.id}/request-venue/${venue.id}?requirement=${BRIEFING_MAIN_VENUE}`,
  )
  await expect(page.getByRole('heading', { name: `Request ${venue.name}`, level: 1 })).toBeVisible()
}

function suitabilityRegion(page: Page) {
  return page.getByRole('region', { name: 'Suitability' })
}

/** Every POST /bookings the page sends, from now on. */
function recordBookingSends(page: Page): Request[] {
  const sends: Request[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === BOOKINGS_PATH) {
      sends.push(request)
    }
  })
  return sends
}

test('11.1 AC2/AC3/AC6: an unsuitable venue is requested with a justification, which Venue Staff and the coordinator then read', async ({
  page,
}) => {
  const justification = `E2E ${Date.now()}: the only free room that day with space for booths.`
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, FOYER)

  // AC2: the warning lists every failure, and asks for a justification.
  const suitability = suitabilityRegion(page)
  await expect(suitability.getByText('Unsuitable', { exact: true })).toBeVisible()
  await expect(suitability.getByText('Layout Classroom not offered', { exact: true })).toBeVisible()
  await expect(
    suitability.getByText('Projector & screen not offered', { exact: true }),
  ).toBeVisible()
  await page.getByRole('textbox', { name: 'Justification' }).fill(justification)

  // AC2: sending asks for confirmation first.
  await page.getByRole('button', { name: 'Send request' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(FOYER.name)
  await dialog.getByRole('button', { name: 'Send request' }).click()

  // AC6: the coordinator reads it on the event's bookings - story 12.5 AC6 opens the event's
  // page once its one requirement has a request.
  await expect(page.getByRole('heading', { name: BRIEFING.name, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Venue booking' })).toContainText(justification)

  // AC3: Venue Staff read it on the request.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  const card = page
    .getByRole('listitem')
    .filter({ hasText: BRIEFING.name })
    .filter({ hasText: FOYER.name })
  await card.getByRole('link', { name: 'View details' }).click()
  await expect(page.getByRole('region', { name: 'Why this venue was requested' })).toContainText(
    justification,
  )
})

test('11.1 AC7: the request cannot be sent with an empty justification', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  const sends = recordBookingSends(page)
  await openRequestStep(page, FOYER)
  await expect(suitabilityRegion(page).getByText('Unsuitable', { exact: true })).toBeVisible()

  for (const blank of ['', '   ']) {
    await page.getByRole('textbox', { name: 'Justification' }).fill(blank)
    await page.getByRole('button', { name: 'Send request' }).click()
    await expect(page.getByRole('alert')).toContainText(JUSTIFICATION_REQUIRED)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  expect(sends).toHaveLength(0)
})

test('11.1 AC7: a send refused for a missing justification shows the warning again', async ({
  page,
}) => {
  // The step's first read is the real answer with its values changed to "suits" - as if the
  // requirement had changed after the page loaded. The real send is then refused (422), and the
  // step reads again: this time the real answer, which does not suit.
  let reads = 0
  await page.route(
    (url) => url.pathname === SUITABILITY_PATH(BOARDROOM.id),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      reads += 1
      if (reads > 1) return route.fallback()
      const response = await route.fetch()
      const real = await response.json()
      return route.fulfill({ response, json: { ...real, is_suitable: true, failures: [] } })
    },
  )
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, BOARDROOM)
  await expect(suitabilityRegion(page).getByText('Suitable', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(page.getByRole('alert')).toContainText('justification')
  await expect(suitabilityRegion(page).getByText('Unsuitable', { exact: true })).toBeVisible()
  await expect(
    suitabilityRegion(page).getByText('Capacity 16 < 60 people', { exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Justification' })).toBeVisible()
  expect(reads).toBe(2)
})

test('11.1 AC2: a venue that suits is requested with no warning', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, SEMINAR_ROOM)

  await expect(suitabilityRegion(page).getByText('Suitable', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Justification' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()
})

test('11.1 AC2: while the check loads the step says so and cannot send yet', async ({ page }) => {
  // The real answer, held back until the test lets it through.
  let release: () => void = () => {}
  const released = new Promise<void>((resolve) => (release = resolve))
  await page.route(
    (url) => url.pathname === SUITABILITY_PATH(FOYER.id),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      await released
      return route.fallback()
    },
  )
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, FOYER)

  await expect(page.getByText('Checking whether this venue suits the event…')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send request' })).toBeDisabled()

  release()
  await expect(suitabilityRegion(page).getByText('Unsuitable', { exact: true })).toBeVisible()
  await expect(page.getByText('Checking whether this venue suits the event…')).toHaveCount(0)
})

test('11.1 AC2: if the check cannot be loaded the step says so and can still send', async ({
  page,
}) => {
  // The real answer, its status changed to a server error.
  await page.route(
    (url) => url.pathname === SUITABILITY_PATH(FOYER.id),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, status: 500, json: { detail: 'Internal Server Error' } })
    },
  )
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, FOYER)

  await expect(suitabilityRegion(page).getByRole('alert')).toBeVisible()
  await expect(page.getByText('Checking whether this venue suits the event…')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()
})

/** The suitability read answers with a server error while `state.failing` is set. */
async function failSuitabilityReadsWhile(
  page: Page,
  venue: { id: string },
  state: { failing: boolean },
) {
  await page.route(
    (url) => url.pathname === SUITABILITY_PATH(venue.id),
    async (route) => {
      if (route.request().resourceType() !== 'fetch' || !state.failing) return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, status: 500, json: { detail: 'Internal Server Error' } })
    },
  )
}

test('11.1 AC7: a send refused for a missing justification replaces an earlier failed check', async ({
  page,
}) => {
  // The step's first read fails, so it cannot say Boardroom does not suit. Send is pressed anyway,
  // the real send is refused (422), and the read that follows is the real answer.
  const state = { failing: true }
  await failSuitabilityReadsWhile(page, BOARDROOM, state)
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, BOARDROOM)
  await expect(suitabilityRegion(page).getByRole('alert')).toBeVisible()

  state.failing = false
  await page.getByRole('button', { name: 'Send request' }).click()

  await expect(suitabilityRegion(page).getByText('Unsuitable', { exact: true })).toBeVisible()
  await expect(
    suitabilityRegion(page).getByText('Capacity 16 < 60 people', { exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Justification' })).toBeVisible()
  // The answer that failed to load is no longer on screen beside the one that did.
  await expect(suitabilityRegion(page).getByRole('alert')).toHaveCount(0)
})

test('11.1 AC7: with the check down, a send refused for a missing justification still asks for one', async ({
  page,
}) => {
  // Every read of the venue's suitability fails, so the page only learns from the refused send
  // that a justification is needed. It must still let the coordinator give one.
  const state = { failing: true }
  await failSuitabilityReadsWhile(page, BOARDROOM, state)
  await signIn(page, ACCOUNTS.coordinator)
  const sends = recordBookingSends(page)
  await openRequestStep(page, BOARDROOM)
  await expect(suitabilityRegion(page).getByRole('alert')).toBeVisible()

  await page.getByRole('button', { name: 'Send request' }).click()

  const justification = page.getByRole('textbox', { name: 'Justification' })
  await expect(justification).toBeVisible()
  // The read that followed the refusal failed too, and the step still says the check failed.
  await expect(suitabilityRegion(page).getByRole('alert')).toBeVisible()
  await justification.fill('The only room free that morning.')
  await page.getByRole('button', { name: 'Send request' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(BOARDROOM.name)
  // Stopped here: the real send with a justification is proven by the AC2/AC3/AC6 test above,
  // and a request left pending would crowd the first page of Venue Staff's queue.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  expect(sends).toHaveLength(1) // only the refused first send
})

test('11.1 AC7: a read after a refused send that says the venue suits asks for no justification', async ({
  page,
}) => {
  // Both of the step's reads are the real answer changed to "suits", as if the requirement had
  // changed back: the real send is still refused (422), but the latest read decides what to ask.
  let reads = 0
  await page.route(
    (url) => url.pathname === SUITABILITY_PATH(BOARDROOM.id),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      reads += 1
      const response = await route.fetch()
      const real = await response.json()
      return route.fulfill({ response, json: { ...real, is_suitable: true, failures: [] } })
    },
  )
  await signIn(page, ACCOUNTS.coordinator)
  await openRequestStep(page, BOARDROOM)
  await expect(suitabilityRegion(page).getByText('Suitable', { exact: true })).toBeVisible()
  const readsOnArrival = reads

  await page.getByRole('button', { name: 'Send request' }).click()

  await expect.poll(() => reads).toBeGreaterThan(readsOnArrival)
  await expect(page.getByRole('button', { name: 'Send request' })).toBeEnabled()
  await expect(suitabilityRegion(page).getByText('Suitable', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Justification' })).toHaveCount(0)
})
