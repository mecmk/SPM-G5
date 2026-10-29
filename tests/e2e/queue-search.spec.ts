/**
 * Story 13.3 - fe/be: search and order the Venue Staff booking queue (13.1) and the Technical
 * Support equipment queue (15.2).
 * AC1/AC2 each queue has a search box and an Order by list beside its tabs; the list follows the
 *     box as the user types, and the tab counts are the matching requests'. Which fields match,
 *     ignoring capitals, and the counts themselves are backend cases:
 *     backend/tests/bookings/test_queue_search_sort.py, backend/tests/equipment/test_queue_search_sort.py.
 * AC3 choosing an order reorders the cards. Each order's rule, ties included, is a backend case.
 * AC4 a new search or order goes back to page 1, and the pager counts only the matches. That the
 *     server searches the whole tab before paging is a backend case.
 * AC5 the box takes no more than 100 characters (client-side), and ten matches fit one page with
 *     no pager, an eleventh bringing it. The API's limits are backend cases.
 * AC6 a search nothing matches says so and offers Clear search. Wildcards and the request with no
 *     recorded time are backend cases.
 * AC7 the tab, search, order and page live in the page address: switching tabs keeps the search
 *     and order, and View details and back, a refresh, or deciding a request keep the list. An
 *     address the page cannot use falls back to Pending, soonest first, page 1.
 * AC8 is all backend: the pages' own refusals are 13.1's and 15.2's specs.
 * AC9 a page emptied between loads gives way to the last page, under a search too. That each load
 *     reads the requests as they stand is a backend case.
 *
 * The seed holds fewer than eleven matching requests in any tab a pager needs, so the paging tests
 * fake the booking queue's answer, searching and ordering it the way the server does. Deciding from
 * a searched list fakes the decision, as 13.1.3 AC4 does, so the seeded request stays pending for
 * the other specs. Other specs add and decide requests while this one runs, so a list is checked
 * against the answer it was drawn from, or by the names it must hold, never by its length alone.
 */
import { expect, test, type Page, type Response, type Route } from '@playwright/test'
import { ACCOUNTS, corsHeaders, signIn } from './support'

const BOOKING_QUEUE_PATH = '/venue-staff/booking-requests'
const EQUIPMENT_QUEUE_PATH = '/equipment/requests'
const SEARCH_MAX_LENGTH = 100
const QUEUE_PAGE_SIZE = 10
const NIMBUS = 'Nimbus Developer Conference'
const NIMBUS_SEMINAR_REQUEST_ID = '44444444-0000-0000-0000-000000000002'
// Story 12.7: the hold's expiry Venue Staff give as they approve, before the request's booked
// period starts on 25 Nov 2026 (as 13.1.3 AC4 gives it).
const NIMBUS_SEMINAR_HOLD_EXPIRES = '2026-11-20T09:00'
// Story 15.2's dedicated event, only read by the other specs.
const ROADSHOW = 'Regional Partner Roadshow'

function searchBox(page: Page) {
  return page.getByRole('searchbox', { name: 'Search requests' })
}

function orderBy(page: Page) {
  return page.getByLabel('Order by')
}

function cards(page: Page) {
  return page.getByRole('main').getByRole('listitem')
}

function card(page: Page, text: string) {
  return cards(page).filter({ hasText: text })
}

function tab(page: Page, name: string) {
  return page.getByRole('tab', { name: new RegExp(`^${name} \\(`) })
}

function pager(page: Page) {
  return page.getByRole('navigation', { name: 'Pages' })
}

async function cardTitles(page: Page): Promise<string[]> {
  return cards(page).getByRole('heading', { level: 3 }).allTextContents()
}

/** A to Z ignoring capitals, as the server orders names. */
function byName(a: string, b: string): number {
  const [left, right] = [a.toLowerCase(), b.toLowerCase()]
  return left < right ? -1 : left > right ? 1 : 0
}

/** The next answer to the queue's own GET at `path` whose query holds `wanted` (null: absent). */
function queueAnswer(
  page: Page,
  path: string,
  wanted: Record<string, string | null>,
): Promise<Response> {
  return page.waitForResponse((response) => {
    const url = new URL(response.url())
    return (
      url.pathname === path &&
      response.request().method() === 'GET' &&
      Object.entries(wanted).every(([name, value]) => url.searchParams.get(name) === value)
    )
  })
}

/** The address's query, as a page shows it. */
function addressQuery(page: Page): URLSearchParams {
  return new URL(page.url()).searchParams
}

// --- the booking queue's answer, faked where the seed has too few requests -----------------------

/** One fake booking queue entry, its event named `name`. */
function fakeBooking(index: number, name: string) {
  const number = String(index + 1).padStart(3, '0')
  return {
    id: `00000000-0000-0000-0000-000000000${number}`,
    event_id: '33333333-0000-0000-0000-000000000003',
    event_name: name,
    venue_id: '22222222-0000-0000-0000-000000000001',
    venue_name: 'Grand Hall',
    venue_location: 'Tower A',
    starts_at: `2027-03-${String((index % 28) + 1).padStart(2, '0')}T01:00:00Z`,
    ends_at: `2027-03-${String((index % 28) + 1).padStart(2, '0')}T03:00:00Z`,
    expected_attendance: 10,
    required_layout_code: null,
    required_layout_name: null,
    requirement_notes: null,
    requested_by_name: 'Chloe Coordinator',
    status: 'PENDING',
    decision_reason: null,
    created_at: '2026-09-20T01:00:00Z',
    decided_at: null,
    cancelled_at: null,
    hold_expires_at: null,
    hold_completed_at: null,
    held_from: '2027-03-01T01:00:00Z',
    setup_minutes: 0,
    teardown_minutes: 0,
    held_until: '2027-03-01T03:00:00Z',
    venue_operating_hours_start: null,
    venue_operating_hours_end: null,
    venue_unavailable_marked_at: null,
    replaces_venue_name: null,
    approval_releases_venue_name: null,
    original_is_marked: null,
    released_at: null,
  }
}

type FakeBooking = ReturnType<typeof fakeBooking>

/** `count` fake requests, `Paged Request 01` onwards. */
function pagedRequests(count: number): FakeBooking[] {
  return Array.from({ length: count }, (_, index) =>
    fakeBooking(index, `Paged Request ${String(index + 1).padStart(2, '0')}`),
  )
}

/**
 * Answer the booking queue's GETs from `every(params)`: searched, ordered by event name when asked
 * and paged by limit/offset, the way the server answers. `asked` collects each query.
 */
async function fakeBookingQueue(page: Page, every: (params: URLSearchParams) => FakeBooking[]) {
  const asked: URLSearchParams[] = []
  await page.route(
    (url) => url.pathname === '/bookings',
    async (route: Route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const params = new URL(request.url()).searchParams
      asked.push(params)
      const search = (params.get('search') ?? '').trim().toLowerCase()
      const matching = every(params).filter((entry) =>
        entry.event_name.toLowerCase().includes(search),
      )
      if (params.get('order') === 'event_name') {
        matching.sort((a, b) => byName(a.event_name, b.event_name))
      }
      const offset = Number(params.get('offset'))
      const limit = Number(params.get('limit'))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: matching.slice(offset, offset + limit),
          total: matching.length,
          counts: {
            pending: matching.length,
            approved: 0,
            rejected: 0,
            withdrawn: 0,
            cancelled: 0,
            expired: 0,
          },
        }),
        headers: corsHeaders(request),
      })
    },
  )
  return asked
}

// --- AC1/AC2: search as you type ---------------------------------------------------------------
test('13.3 AC1/AC2: Venue Staff search the booking queue as they type, and the tab counts follow', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await expect(card(page, NIMBUS).first()).toBeVisible()
  await expect(orderBy(page)).toHaveValue('date')

  const answered = queueAnswer(page, '/bookings', { status: 'PENDING', search: 'nimbus' })
  await searchBox(page).pressSequentially('nimbus')
  const queue = await (await answered).json()

  await expect(page).toHaveURL(/[?&]search=nimbus(&|$)/)
  await expect(card(page, NIMBUS).first()).toBeVisible()
  await expect(cards(page)).toHaveCount(queue.items.length)
  await expect(cards(page).filter({ hasNotText: /nimbus/i })).toHaveCount(0)
  // The approved Nimbus booking at Grand Hall counts under Approved, not in this Pending list.
  expect(queue.counts.approved).toBeGreaterThan(0)
  await expect(tab(page, 'Pending')).toHaveText(`Pending (${queue.counts.pending})`)
  await expect(tab(page, 'Approved')).toHaveText(`Approved (${queue.counts.approved})`)
})

test('13.3 AC1/AC2: Technical Support search the equipment queue as they type, and the tab counts follow', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(EQUIPMENT_QUEUE_PATH)
  await expect(card(page, ROADSHOW)).toBeVisible()
  await expect(orderBy(page)).toHaveValue('date')

  const answered = queueAnswer(page, '/equipment-requests', {
    status: 'PENDING',
    search: 'microphone',
  })
  await searchBox(page).pressSequentially('microphone')
  const queue = await (await answered).json()

  await expect(page).toHaveURL(/[?&]search=microphone(&|$)/)
  await expect(card(page, 'Lapel microphone').first()).toBeVisible()
  await expect(cards(page)).toHaveCount(queue.items.length)
  await expect(cards(page).filter({ hasNotText: /microphone/i })).toHaveCount(0)
  await expect(tab(page, 'Pending')).toHaveText(`Pending (${queue.counts.pending})`)
  await expect(tab(page, 'Accepted')).toHaveText(`Accepted (${queue.counts.accepted})`)
})

// --- AC3: Order by --------------------------------------------------------------------------------
test('13.3 AC3: ordering the booking queue by event name puts the cards A to Z', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await tab(page, 'All').click()
  await searchBox(page).fill('foyer')
  await expect(page).toHaveURL(/[?&]search=foyer(&|$)/)

  const answered = queueAnswer(page, '/bookings', { search: 'foyer', order: 'event_name' })
  await orderBy(page).selectOption({ label: 'Event name: A to Z' })
  const queue = await (await answered).json()

  await expect(page).toHaveURL(/[?&]order=event_name(&|$)/)
  const names: string[] = queue.items.map((entry: { event_name: string }) => entry.event_name)
  await expect(cards(page).getByRole('heading', { level: 3 })).toHaveText(names)
  expect(names).toEqual([...names].sort(byName))
})

test('13.3 AC3: ordering the equipment queue by equipment type puts the cards A to Z', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(EQUIPMENT_QUEUE_PATH)
  await expect(card(page, ROADSHOW)).toBeVisible()

  const answered = queueAnswer(page, '/equipment-requests', {
    status: 'PENDING',
    order: 'equipment_type',
  })
  await orderBy(page).selectOption({ label: 'Equipment type: A to Z' })
  const queue = await (await answered).json()

  await expect(page).toHaveURL(/[?&]order=equipment_type(&|$)/)
  const types: string[] = queue.items.map(
    (entry: { equipment_type_name: string }) => entry.equipment_type_name,
  )
  expect(types).toEqual([...types].sort(byName))
  await expect(cards(page)).toHaveCount(types.length)
  for (const [index, type] of types.entries()) {
    await expect(cards(page).nth(index)).toContainText(type)
  }
})

// --- AC4: a new search or order starts again at page 1 ------------------------------------------
test('13.3 AC4: a new search or order goes back to page 1, and the pager counts only the matches', async ({
  page,
}) => {
  const every = pagedRequests(25)
  const asked = await fakeBookingQueue(page, () => every)
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await pager(page).getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByText('Showing 11–20 of 25 requests')).toBeVisible()

  // "1" is in Paged Request 01, 10 to 19 and 21: twelve of the twenty-five.
  await searchBox(page).fill('1')
  await expect(page.getByText('Showing 1–10 of 12 requests')).toBeVisible()
  await expect(pager(page).getByRole('button', { name: '1', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  expect(asked.at(-1)?.get('offset')).toBe('0')
  expect(asked.at(-1)?.get('search')).toBe('1')
  expect(addressQuery(page).get('page')).toBeNull()

  await pager(page).getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByText('Showing 11–12 of 12 requests')).toBeVisible()
  await orderBy(page).selectOption({ label: 'Event name: A to Z' })
  await expect(page.getByText('Showing 1–10 of 12 requests')).toBeVisible()
  expect(asked.at(-1)?.get('offset')).toBe('0')
  expect(asked.at(-1)?.get('order')).toBe('event_name')
  expect(addressQuery(page).get('page')).toBeNull()
})

// --- AC5: boundaries --------------------------------------------------------------------------------
test('13.3 AC5: the search box takes no more than 100 characters', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await expect(searchBox(page)).toBeVisible()
  const typed = 'x'.repeat(SEARCH_MAX_LENGTH + 1)

  const answered = queueAnswer(page, '/bookings', { search: typed.slice(0, SEARCH_MAX_LENGTH) })
  await searchBox(page).pressSequentially(typed)

  await expect(searchBox(page)).toHaveValue(typed.slice(0, SEARCH_MAX_LENGTH))
  expect((await answered).status()).toBe(200)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('13.3 AC5: ten matching requests fit one page with no pager, and an eleventh brings page 2', async ({
  page,
}) => {
  await fakeBookingQueue(page, (params) => {
    const search = params.get('search') ?? ''
    if (search === 'ten') return Array.from({ length: 10 }, (_, i) => fakeBooking(i, `Ten ${i}`))
    if (search === 'eleven') {
      return Array.from({ length: 11 }, (_, i) => fakeBooking(i, `Eleven ${i}`))
    }
    return pagedRequests(3)
  })
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await expect(card(page, 'Paged Request 01')).toBeVisible()

  await searchBox(page).fill('ten')
  await expect(cards(page)).toHaveCount(QUEUE_PAGE_SIZE)
  await expect(card(page, 'Ten 9')).toBeVisible()
  await expect(pager(page)).toHaveCount(0)

  await searchBox(page).fill('eleven')
  await expect(page.getByText('Showing 1–10 of 11 requests')).toBeVisible()
  await pager(page).getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByText('Showing 11–11 of 11 requests')).toBeVisible()
  await expect(cards(page)).toHaveCount(1)
  await expect(card(page, 'Eleven 10')).toBeVisible()
})

// --- AC6: nothing matches -----------------------------------------------------------------------
test('13.3 AC6: a booking search nothing matches says so, and Clear search brings the tab back', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await expect(card(page, NIMBUS).first()).toBeVisible()

  await searchBox(page).fill('no request is called this')
  await expect(page.getByText('No requests match your search.')).toBeVisible()
  await expect(cards(page)).toHaveCount(0)

  await page.getByRole('button', { name: 'Clear search' }).click()
  await expect(searchBox(page)).toHaveValue('')
  await expect(card(page, NIMBUS).first()).toBeVisible()
  await expect(page.getByText('No requests match your search.')).toHaveCount(0)
  expect(addressQuery(page).get('search')).toBeNull()
})

test('13.3 AC6: an equipment search nothing matches says so, and Clear search brings the tab back', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(EQUIPMENT_QUEUE_PATH)
  await expect(card(page, ROADSHOW)).toBeVisible()

  await searchBox(page).fill('no request is called this')
  await expect(page.getByText('No equipment requests match your search.')).toBeVisible()
  await expect(cards(page)).toHaveCount(0)

  await page.getByRole('button', { name: 'Clear search' }).click()
  await expect(searchBox(page)).toHaveValue('')
  await expect(card(page, ROADSHOW)).toBeVisible()
  expect(addressQuery(page).get('search')).toBeNull()
})

// --- AC7: the list lives in the page address ------------------------------------------------------
/** The booking queue's controls show the All tab, page 2, searched for Foyer by event name. */
async function expectFoyerPage2(page: Page) {
  await expect(page).toHaveURL(/[?&]status=ALL(&|$)/)
  await expect(page).toHaveURL(/[?&]search=foyer(&|$)/)
  await expect(page).toHaveURL(/[?&]order=event_name(&|$)/)
  await expect(page).toHaveURL(/[?&]page=2(&|$)/)
  await expect(tab(page, 'All')).toHaveAttribute('aria-selected', 'true')
  await expect(searchBox(page)).toHaveValue('foyer')
  await expect(orderBy(page)).toHaveValue('event_name')
  await expect(pager(page).getByRole('button', { name: '2', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(page.getByText(/^Showing 11–20 of \d+ requests$/)).toBeVisible()
}

test('13.3 AC7: the booking queue keeps its tab, search, order and page through View details, a refresh and a tab change', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await tab(page, 'All').click()
  await searchBox(page).fill('foyer')
  await expect(page).toHaveURL(/[?&]search=foyer(&|$)/)
  await orderBy(page).selectOption({ label: 'Event name: A to Z' })
  await expect(page).toHaveURL(/[?&]order=event_name(&|$)/)
  // The seed has over twenty requests at Exhibition Foyer, so the search has a second page.
  await pager(page).getByRole('button', { name: '2', exact: true }).click()
  await expectFoyerPage2(page)

  await cards(page).first().getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(new RegExp(`${BOOKING_QUEUE_PATH}/[^/?]+$`))
  await page.getByRole('link', { name: '← Back to Booking Requests' }).click()
  await expectFoyerPage2(page)

  await page.reload()
  await expectFoyerPage2(page)

  await tab(page, 'Pending').click()
  await expect(tab(page, 'Pending')).toHaveAttribute('aria-selected', 'true')
  await expect(searchBox(page)).toHaveValue('foyer')
  await expect(orderBy(page)).toHaveValue('event_name')
  expect(addressQuery(page).get('search')).toBe('foyer')
  expect(addressQuery(page).get('order')).toBe('event_name')
  expect(addressQuery(page).get('page')).toBeNull()
})

/** The equipment queue's controls show the All tab, searched for the roadshow by type. */
async function expectRoadshowByType(page: Page) {
  await expect(page).toHaveURL(/[?&]status=ALL(&|$)/)
  await expect(page).toHaveURL(/[?&]search=roadshow(&|$)/)
  await expect(page).toHaveURL(/[?&]order=equipment_type(&|$)/)
  await expect(tab(page, 'All')).toHaveAttribute('aria-selected', 'true')
  await expect(searchBox(page)).toHaveValue('roadshow')
  await expect(orderBy(page)).toHaveValue('equipment_type')
  // The roadshow's three requests, one per tab, by type.
  await expect(cards(page).getByRole('heading', { level: 3 })).toHaveText([
    ROADSHOW,
    ROADSHOW,
    ROADSHOW,
  ])
  await expect(cards(page).nth(0)).toContainText('Lapel microphone')
  await expect(cards(page).nth(1)).toContainText('Portable projector')
  await expect(cards(page).nth(2)).toContainText('Wireless microphone')
}

test('13.3 AC7: the equipment queue keeps its tab, search and order through View details, the event, a refresh and a tab change', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(EQUIPMENT_QUEUE_PATH)
  await tab(page, 'All').click()
  await searchBox(page).fill('roadshow')
  await expect(page).toHaveURL(/[?&]search=roadshow(&|$)/)
  await orderBy(page).selectOption({ label: 'Equipment type: A to Z' })
  await expectRoadshowByType(page)

  await cards(page).first().getByRole('link', { name: 'View details' }).click()
  await expect(page).toHaveURL(new RegExp(`${EQUIPMENT_QUEUE_PATH}/[^/?]+$`))
  await page.getByRole('link', { name: '← Equipment Requests' }).click()
  await expectRoadshowByType(page)

  await cards(page).first().getByRole('link', { name: ROADSHOW }).click()
  await expect(page.getByRole('heading', { name: ROADSHOW, level: 1 })).toBeVisible()
  await page.getByRole('link', { name: '← Equipment Requests' }).click()
  await expectRoadshowByType(page)

  await page.reload()
  await expectRoadshowByType(page)

  await tab(page, 'Pending').click()
  await expect(tab(page, 'Pending')).toHaveAttribute('aria-selected', 'true')
  await expect(searchBox(page)).toHaveValue('roadshow')
  await expect(orderBy(page)).toHaveValue('equipment_type')
  expect(addressQuery(page).get('search')).toBe('roadshow')
  expect(addressQuery(page).get('order')).toBe('equipment_type')
})

test('13.3 AC7: approving from a searched booking queue keeps the search and order', async ({
  page,
}) => {
  // The approval is faked, so the seeded request stays pending for the other specs.
  let hasApproved = false
  await page.route(
    (url) => url.pathname === `/bookings/${NIMBUS_SEMINAR_REQUEST_ID}/approve`,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      hasApproved = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: corsHeaders(route.request()),
        body: JSON.stringify({
          id: NIMBUS_SEMINAR_REQUEST_ID,
          status: 'APPROVED',
          replaces_booking_id: null,
          decided_at: '2026-10-28T02:00:00Z',
        }),
      })
    },
  )
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(BOOKING_QUEUE_PATH)
  await searchBox(page).fill('nimbus')
  await expect(page).toHaveURL(/[?&]search=nimbus(&|$)/)
  const ordered = queueAnswer(page, '/bookings', { search: 'nimbus', order: 'venue_name' })
  await orderBy(page).selectOption({ label: 'Venue: A to Z' })
  await ordered
  await expect(page).toHaveURL(/[?&]order=venue_name(&|$)/)
  const address = page.url()

  const nimbusCard = cards(page).filter({ hasText: '#00000002' })
  await nimbusCard.getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await dialog.getByLabel('Hold expires').fill(NIMBUS_SEMINAR_HOLD_EXPIRES)
  const reloaded = queueAnswer(page, '/bookings', {
    status: 'PENDING',
    search: 'nimbus',
    order: 'venue_name',
  })
  await dialog.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).not.toBeVisible()
  await reloaded

  expect(hasApproved).toBe(true)
  expect(page.url()).toBe(address)
  await expect(searchBox(page)).toHaveValue('nimbus')
  await expect(orderBy(page)).toHaveValue('venue_name')
  await expect(card(page, NIMBUS).first()).toBeVisible()
})

test('13.3 AC7: declining from a searched equipment queue keeps the search and order', async ({
  page,
}) => {
  // The decision is faked, so the roadshow's request stays pending for 15.2's spec.
  let decided: object | null = null
  await page.route(
    (url) => /^\/equipment-requests\/[^/]+\/decision$/.test(url.pathname),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        headers: corsHeaders(route.request()),
        body: JSON.stringify(decided),
      })
    },
  )
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(EQUIPMENT_QUEUE_PATH)
  const answered = queueAnswer(page, '/equipment-requests', {
    status: 'PENDING',
    search: 'roadshow',
    order: 'equipment_type',
  })
  await searchBox(page).fill('roadshow')
  await orderBy(page).selectOption({ label: 'Equipment type: A to Z' })
  const queue = await (await answered).json()
  const lapelMics = queue.items.find(
    (entry: { equipment_type_name: string }) => entry.equipment_type_name === 'Lapel microphone',
  )
  decided = {
    ...lapelMics,
    status: 'DECLINED',
    decision_reason: 'Short by four for the panel.',
    decided_by_name: 'Theo Tech',
    decided_at: '2026-10-28T02:00:00Z',
  }
  const address = page.url()

  const lapelCard = card(page, 'Lapel microphone')
  await lapelCard.getByRole('button', { name: 'Decline' }).click()
  const dialog = page.getByRole('dialog', { name: 'Decline this request?' })
  await dialog.getByLabel('Reason for declining').fill('Short by four for the panel.')
  await dialog.getByRole('button', { name: 'Decline' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(lapelCard).toHaveCount(0)
  expect(page.url()).toBe(address)
  await expect(searchBox(page)).toHaveValue('roadshow')
  await expect(orderBy(page)).toHaveValue('equipment_type')
})

test('13.3 AC7: an address the queue cannot use opens on Pending, soonest first, page 1', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  const answered = queueAnswer(page, '/bookings', { status: 'PENDING', offset: '0' })
  const tooLong = 'x'.repeat(SEARCH_MAX_LENGTH + 1)
  await page.goto(`${BOOKING_QUEUE_PATH}?status=DECIDED&order=price&page=two&search=${tooLong}`)
  const asked = new URL((await answered).url()).searchParams

  expect(asked.get('order')).toBe('date')
  expect(asked.get('search')).toBe(tooLong.slice(0, SEARCH_MAX_LENGTH))
  await expect(tab(page, 'Pending')).toHaveAttribute('aria-selected', 'true')
  await expect(orderBy(page)).toHaveValue('date')
  await expect(searchBox(page)).toHaveValue(tooLong.slice(0, SEARCH_MAX_LENGTH))
  await expect(page.getByRole('alert')).toHaveCount(0)
})

// --- AC9: a page emptied between loads ----------------------------------------------------------
test('13.3 AC9: under a search, a page emptied between loads shows the last page instead', async ({
  page,
}) => {
  // Twenty-five match when the queue opens; by the time page 3 is asked for, ten of them were
  // decided elsewhere, so fifteen remain and page 3 is past the end.
  let remaining = 25
  const every = pagedRequests(25)
  await fakeBookingQueue(page, (params) => {
    if (params.get('offset') === String(2 * QUEUE_PAGE_SIZE)) remaining = 15
    return every.slice(0, remaining)
  })
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`${BOOKING_QUEUE_PATH}?search=paged`)
  await expect(page.getByText('Showing 1–10 of 25 requests')).toBeVisible()

  await pager(page).getByRole('button', { name: '3', exact: true }).click()

  await expect(page.getByText('Showing 11–15 of 15 requests')).toBeVisible()
  await expect(pager(page).getByRole('button', { name: '2', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )
  await expect(searchBox(page)).toHaveValue('paged')
  await expect(page.getByText('No requests match your search.')).toHaveCount(0)
})
