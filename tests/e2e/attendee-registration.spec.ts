import { expect, test, type Locator, type Page, type Request } from '@playwright/test'
import {
  ACCOUNTS,
  CONFIRM_AND_REGISTER,
  EVENTS,
  MIN_TOUCH_TARGET,
  confirmDetailsDialog,
  confirmRegistration,
  corsHeaders,
  expectNoSidewaysScroll,
  openEventPage,
  registerButton,
  registrationSection,
  signIn,
} from './support'

/**
 * Story 18.1 - browse and register for an event. END-TO-END tests: what an attendee clicks.
 *
 * Level: e2e. Each test drives the real app and API in a browser. The rules behind what it shows -
 * the last place, the closing and opening times, which events are listed or have a page, who may
 * register, the races - are proven in backend/tests/registrations/ (unit and integration), not
 * repeated here.
 *
 * AC1 Confirmed, Public events with registration enabled that have not started are listed
 *     soonest first, a page at a time. Each card shows the event's cover picture, name, date and
 *     time, each booked venue's name and location, the places left, where registration stands,
 *     and when registration closes - or opens, while it has not, or when the attendee registered,
 *     once they have. The attendee registers from the event's page (AC9) - Register, then
 *     confirming their details (story 18.4) - which shows a confirmation with its time; the event
 *     then shows as Registered on its page and its card, also after a reload.
 * AC3 Full, closed and not-yet-open events stay listed, and their page shows Register disabled.
 * AC5 Only attendees can open Upcoming events or an event's page (the API's 401/403 are backend
 *     cases).
 * AC6 A second registration is refused, also when both arrive at once; of two attendees competing
 *     for the last place, one succeeds and the other is told the event is full. A double-click on
 *     Confirm and register (story 18.4) sends one.
 * AC8 (fix f18.1.1) Each event shows its cover picture (2.1 AC14), on its card and its page, or
 *     the placeholder when it has none or its picture can't be loaded. An uploaded picture is
 *     loaded from the API. What the list sends is a backend case.
 * AC9 (fix f18.1.2) Clicking anywhere on an event's card opens its page: its cover picture, name,
 *     description, date and time, each booked venue, the places left, where registration stands
 *     and when it opens and closes. Register is only on this page. A back link returns to
 *     Upcoming events.
 * AC10 (fix f18.1.2) An event that is not listed, and that the attendee never registered for, has
 *     no page: its address says the event is not open for registration. Which events those are is
 *     a backend case.
 * AC11 (fix f18.1.2) A registration refused because the event filled up, closed or stopped being
 *     listed while its page was open says why, and the page then shows where the event stands.
 *
 * Every test is independent: each case that registers has a seeded event of its own
 * (backend/db/seed/020_sample_data.sql, 3333..39-45), so tests running in parallel never share a
 * place, and every other case only reads. Those three never retry: a retry could only fail on
 * what the first attempt changed, and would hide that attempt's trace. States the seed cannot
 * reach - no events at all, a failed load, a second page, an event closed mid-visit, an uploaded
 * picture, a reload that fails, a long link in a description - stub the calls with `page.route`,
 * answering as the server would.
 */

const UPCOMING_EVENTS_PATH = '/browse'
const EVENTS_API_PATH = '/registrations/events'
// AC8: a picture is decorative - no alt text, hidden from assistive technology - so it has no role
// or name, and is found by its tag. The jazz evening has the seeded one; an uploaded one is served
// by the API (mediaUrl).
const JAZZ_PICTURE = '/images/events/cat.jpg'
const UPLOADED_PICTURE_PATH = '/uploads/events/e2e-pictured-gala.png'
const REGISTER_API_PATH = '/registrations'
const NOT_OPEN_MESSAGE = 'This event is not open for registration.'
const BACK_TO_LIST = '← Upcoming events'
const EVENT_FULL_MESSAGE = 'This event is full.'
const UNREACHABLE_MESSAGE = 'The server could not be reached. Check your connection and try again.'
const PHONE = { width: 390, height: 844 }
// AC9: one unbroken word - a link pasted into the description - that must wrap on a phone.
const LONG_LINK =
  'https://www.connectsphere.example/events/harbourfrontjazzevening/foodstallsforthewholeevening'

// AC1: each state's badge has a colour of its own, which its class names (App.css `.badge-*`).
const OPEN_BADGE = /\bbadge-success\b/
const REGISTERED_BADGE = /\bbadge-registered\b/
const FULL_BADGE = /\bbadge-warning\b/
const CLOSED_BADGE = /\bbadge-neutral\b/
const NOT_YET_OPEN_BADGE = /\bbadge-info\b/
// AC9: Register is the brand colour, so it stands out.
const BRAND_BUTTON = /\bbrand\b/

const JAZZ_EVENING = 'Harbourfront Jazz Evening' // open, two venues booked, a picture; only read
const DESIGN_MASTERCLASS = 'Design Thinking Masterclass' // open; registered for once
const FOUNDERS_FIRESIDE = 'Startup Founders Fireside' // open; double-clicked once
const MENTORING_SLOT = 'Career Mentoring Slot' // one place; raced for once
const PORTFOLIO_REVIEW = 'Portfolio Review Slot' // one place, already taken: Full
const WINE_APPRECIATION = 'Autumn Wine Appreciation' // registration closed on 1 Oct 2026
const LUNAR_NEW_YEAR_MARKET = 'Lunar New Year Market' // registration opens on 10 Jan 2028

/** An event's card on Upcoming events, found by its name. */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

async function openUpcomingEvents(page: Page, account: string = ACCOUNTS.attendee) {
  await signIn(page, account)
  await page.goto(UPCOMING_EVENTS_PATH)
  await expect(page.getByRole('heading', { level: 1, name: 'Upcoming events' })).toBeVisible()
}

/** AC1: where registration stands shows as `label`, in that state's own colour. */
async function expectBadge(within: Locator, label: string, colour: RegExp) {
  const badge = within.getByText(label, { exact: true })
  await expect(badge).toBeVisible()
  await expect(badge).toHaveClass(colour)
}

/** The width the main column scrolls sideways by: the app scrolls inside it, so the document's
 *  own width (expectNoSidewaysScroll) never shows a page that is too wide. */
async function mainOverflow(page: Page): Promise<number> {
  return page.getByRole('main').evaluate((main) => main.scrollWidth - main.clientWidth)
}

/** Answer the page's call for an event with what the server sends, changed by `change`. */
async function changeEventCall(page: Page, change: (event: Record<string, unknown>) => object) {
  await page.route(
    (url) => url.pathname.startsWith(`${EVENTS_API_PATH}/`),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, json: change(await response.json()) })
    },
  )
}

/** Today's date as the app writes it, on Singapore's clock. */
function todayInSingapore(): string {
  return new Date().toLocaleDateString('en-SG', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Singapore',
  })
}

function escapeForRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** "You registered on <today>, HH:MM", allowing for midnight passing while the test runs. */
function registeredToday(before: string, after: string): RegExp {
  const days = [...new Set([before, after])].map(escapeForRegExp).join('|')
  return new RegExp(`You registered on (${days}), \\d{2}:\\d{2}`)
}

/** A listed event as the API sends it, for a stubbed list or page. */
function listedEvent(name: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `00000000-0000-4000-8000-${String(Math.floor(Math.random() * 1e12)).padStart(12, '0')}`,
    name,
    description: `${name}, described.`,
    starts_at: '2029-03-01T01:00:00Z',
    ends_at: '2029-03-01T04:00:00Z',
    venues: [{ name: 'Grand Hall', location: 'Tower A, Level 1' }],
    registration_opens_at: null,
    registration_closes_at: '2029-02-27T10:00:00Z',
    places_left: 10,
    state: 'OPEN',
    registered_at: null,
    cover_image_url: null,
    ...overrides,
  }
}

/** AC9: an event's page as the API sends it for a listed event the attendee never registered for:
 *  the event, what its card shows, and no registration of theirs (18.2's fix f18.2.1). */
function eventPage(listed: ReturnType<typeof listedEvent>) {
  const { id, name, description, cover_image_url, starts_at, ends_at, venues } = listed
  return {
    id,
    name,
    description,
    cover_image_url,
    starts_at,
    ends_at,
    venues,
    listing: listed,
    registration: null,
  }
}

/**
 * Answer the page's list call with `answer(offset)` instead of the API. Only the `fetch` is
 * stubbed; the CORS headers go with it, since the app and the API run on different ports.
 */
async function stubEventsCall(
  page: Page,
  answer: (offset: number) => { status: number; body: unknown },
) {
  await page.route(
    (url) => url.pathname === EVENTS_API_PATH,
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const offset = Number(new URL(request.url()).searchParams.get('offset') ?? 0)
      const { status, body } = answer(offset)
      return route.fulfill({
        status,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify(body),
      })
    },
  )
}

// --- AC1: the list -----------------------------------------------------------------------------
test('18.1 AC1: an attendee finds an open event under Upcoming events, with its date, time, venues, places left and when registration closes', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Upcoming events' })
    .click()

  await expect(page).toHaveURL(new RegExp(`${UPCOMING_EVENTS_PATH}$`))
  const card = eventCard(page, JAZZ_EVENING)
  await expect(card).toContainText('Sat, 7 Oct 2028 · 19:00–22:00')
  await expect(card).toContainText('Grand Hall, Tower A, Level 1')
  await expect(card).toContainText('Exhibition Foyer, Tower B, Level 1')
  await expect(card).toContainText('120 places left')
  await expect(card).toContainText('Registration closes Thu, 5 Oct 2028, 18:00')
  await expectBadge(card, 'Open', OPEN_BADGE)
  // AC9: Register is on the event's page, not its card.
  await expect(card.getByRole('button')).toHaveCount(0)
})

// --- AC9: an event's page ----------------------------------------------------------------------
test("18.1 AC9: clicking anywhere on an event's card opens its page, with its description, date, venues, places left and Register, and the back link returns to the list", async ({
  page,
}) => {
  await openUpcomingEvents(page)

  // Not the title, which is the card's link: anywhere else on the card opens the event too.
  await eventCard(page, JAZZ_EVENING).getByText('120 places left').click()

  await expect(page).toHaveURL(new RegExp(`${UPCOMING_EVENTS_PATH}/[0-9a-f-]{36}$`))
  await expect(page.getByRole('heading', { level: 1, name: JAZZ_EVENING })).toBeVisible()
  const main = page.getByRole('main')
  await expect(main).toContainText('Live jazz on the waterfront, with food stalls in the foyer.')
  await expect(main).toContainText('Sat, 7 Oct 2028 · 19:00–22:00')
  await expect(main).toContainText('Grand Hall, Tower A, Level 1')
  await expect(main).toContainText('Exhibition Foyer, Tower B, Level 1')
  const box = registrationSection(page)
  await expectBadge(box, 'Open', OPEN_BADGE)
  await expect(box).toContainText('120 places left')
  await expect(box).toContainText('Registration closes Thu, 5 Oct 2028, 18:00')
  await expect(registerButton(page, JAZZ_EVENING)).toBeEnabled()
  await expect(registerButton(page, JAZZ_EVENING)).toHaveClass(BRAND_BUTTON)

  await page.getByRole('link', { name: BACK_TO_LIST }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'Upcoming events' })).toBeVisible()
  await expect(eventCard(page, JAZZ_EVENING)).toBeVisible()
})

test.describe('registers for a seeded event once', () => {
  test.describe.configure({ retries: 0 })

  test('18.1 AC1: registering on the event page shows a confirmation with its time at once, and the event stays Registered on its page and its card after a reload', async ({
    page,
  }) => {
    await openUpcomingEvents(page)
    await expect(eventCard(page, DESIGN_MASTERCLASS)).toContainText('60 places left')
    await openEventPage(page, DESIGN_MASTERCLASS)

    // The page loaded again after registering is held back until it has been checked, so what it
    // shows comes from the registration's own answer, as soon as it arrives.
    let hasRegistered = false
    let releaseReload: () => void = () => {}
    const reloadHeld = new Promise<void>((resolve) => {
      releaseReload = resolve
    })
    await page.route(
      (url) => url.pathname === REGISTER_API_PATH || url.pathname.startsWith(`${EVENTS_API_PATH}/`),
      async (route) => {
        const request: Request = route.request()
        if (request.resourceType() !== 'fetch') return route.fallback()
        if (request.method() === 'POST') {
          const response = await route.fetch()
          hasRegistered = true
          return route.fulfill({ response })
        }
        if (hasRegistered) await reloadHeld
        return route.fallback()
      },
    )

    await registerButton(page, DESIGN_MASTERCLASS).click()
    const before = todayInSingapore()
    await confirmRegistration(page)
    const after = todayInSingapore()

    const confirmation = page
      .getByRole('status')
      .filter({ hasText: `You are registered for ${DESIGN_MASTERCLASS}.` })
    await expect(confirmation).toContainText('Registered')
    const box = registrationSection(page)
    await expectBadge(box, 'Registered', REGISTERED_BADGE)
    await expect(box).toContainText(registeredToday(before, after))
    await expect(box).toContainText('59 places left')
    // No second Register; the page offers Withdraw instead (story 18.2 AC9, fix f18.2.1).
    await expect(registerButton(page, DESIGN_MASTERCLASS)).toHaveCount(0)
    await expect(
      box.getByRole('button', { name: `Withdraw from ${DESIGN_MASTERCLASS}` }),
    ).toBeEnabled()
    releaseReload()

    await page.reload()
    await expectBadge(box, 'Registered', REGISTERED_BADGE)
    await expect(box).toContainText(registeredToday(before, after))
    await expect(box).toContainText('59 places left')

    await page.getByRole('link', { name: BACK_TO_LIST }).click()
    const card = eventCard(page, DESIGN_MASTERCLASS)
    await expectBadge(card, 'Registered', REGISTERED_BADGE)
    await expect(card).toContainText(registeredToday(before, after))
    await expect(card).toContainText('59 places left')
  })
})

test('18.1 AC1: a registration taken stays on the page, Registered with its time, when the event cannot be read again after it', async ({
  page,
}) => {
  // The registration is stubbed as taken, and the server cannot be reached for the event after
  // it, so nothing is written: the jazz evening stays read-only.
  let hasRegistered = false
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH || url.pathname.startsWith(`${EVENTS_API_PATH}/`),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST') {
        hasRegistered = true
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({
            id: '00000000-0000-4000-8000-000000018101',
            event_id: request.postDataJSON().event_id,
            status: 'REGISTERED',
            registered_at: new Date().toISOString(),
            guests: [],
          }),
        })
      }
      if (hasRegistered) return route.abort('internetdisconnected')
      return route.fallback()
    },
  )
  await signIn(page, ACCOUNTS.attendee)
  await openEventPage(page, JAZZ_EVENING)

  await registerButton(page, JAZZ_EVENING).click()
  const before = todayInSingapore()
  await confirmRegistration(page)
  const after = todayInSingapore()

  // Once the event could not be read again, the page still says the attendee has their place.
  await expect(page.getByRole('main').getByRole('alert')).toHaveText(UNREACHABLE_MESSAGE)
  await expect(page.getByRole('heading', { level: 1, name: JAZZ_EVENING })).toBeVisible()
  const box = registrationSection(page)
  await expectBadge(box, 'Registered', REGISTERED_BADGE)
  await expect(box).toContainText(registeredToday(before, after))
  await expect(box).toContainText('119 places left')
  // No second Register; the page offers Withdraw instead (story 18.2 AC9, fix f18.2.1).
  await expect(registerButton(page, JAZZ_EVENING)).toHaveCount(0)
  await expect(box.getByRole('button', { name: `Withdraw from ${JAZZ_EVENING}` })).toBeEnabled()
})

// --- AC8: cover pictures -----------------------------------------------------------------------
test('18.1 AC8: an event with a cover picture shows it on its card and on its page', async ({
  page,
}) => {
  await openUpcomingEvents(page)

  const onCard = eventCard(page, JAZZ_EVENING).locator('img')
  await expect(onCard).toHaveAttribute('src', JAZZ_PICTURE)
  // Loaded, not only asked for: a picture that fails to load gives way to the placeholder.
  await expect
    .poll(() => onCard.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)

  await openEventPage(page, JAZZ_EVENING)
  const onPage = page.getByRole('main').locator('img')
  await expect(onPage).toHaveAttribute('src', JAZZ_PICTURE)
  await expect
    .poll(() => onPage.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0)
})

test('18.1 AC8: an uploaded picture is asked of the API, one that cannot be loaded gives way to the placeholder, and so does none', async ({
  page,
}) => {
  // No seeded event has an uploaded picture, so the list call alone is stubbed. The picture itself
  // is not: the browser asks the API for it, which has no such file, so the card then shows the
  // placeholder - AC8's picture that can't be loaded.
  const listRequest = page.waitForRequest(
    (request) =>
      request.resourceType() === 'fetch' && new URL(request.url()).pathname === EVENTS_API_PATH,
  )
  const pictureRequest = page.waitForRequest(
    (request) =>
      request.resourceType() === 'image' &&
      new URL(request.url()).pathname === UPLOADED_PICTURE_PATH,
  )
  const pictured = listedEvent('E2E Pictured Gala', { cover_image_url: UPLOADED_PICTURE_PATH })
  const plain = listedEvent('E2E Plain Gala')
  await stubEventsCall(page, () => ({ status: 200, body: { items: [pictured, plain], total: 2 } }))

  await openUpcomingEvents(page)

  const apiOrigin = new URL((await listRequest).url()).origin
  expect(new URL((await pictureRequest).url()).origin).toBe(apiOrigin)
  await expect(eventCard(page, pictured.name)).toBeVisible()
  await expect(eventCard(page, pictured.name).locator('img')).toHaveCount(0)
  await expect(eventCard(page, plain.name)).toBeVisible()
  await expect(eventCard(page, plain.name).locator('img')).toHaveCount(0)
})

test("18.1 AC8: on an event's page, an uploaded picture is asked of the API, one that cannot be loaded gives way to the placeholder, and so does none", async ({
  page,
}) => {
  // As on the card: only the page's call for the event is stubbed, and the picture is asked of the
  // API, which has no such file.
  const pictured = listedEvent('E2E Pictured Page Gala', { cover_image_url: UPLOADED_PICTURE_PATH })
  const plain = listedEvent('E2E Plain Page Gala')
  await page.route(
    (url) => url.pathname.startsWith(`${EVENTS_API_PATH}/`),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      const id = new URL(request.url()).pathname.split('/').pop()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify(eventPage(id === pictured.id ? pictured : plain)),
      })
    },
  )
  await signIn(page, ACCOUNTS.attendee)
  const eventRequest = page.waitForRequest(
    (request) =>
      request.resourceType() === 'fetch' &&
      new URL(request.url()).pathname === `${EVENTS_API_PATH}/${pictured.id}`,
  )
  const pictureRequest = page.waitForRequest(
    (request) =>
      request.resourceType() === 'image' &&
      new URL(request.url()).pathname === UPLOADED_PICTURE_PATH,
  )

  await page.goto(`${UPCOMING_EVENTS_PATH}/${pictured.id}`)

  const apiOrigin = new URL((await eventRequest).url()).origin
  expect(new URL((await pictureRequest).url()).origin).toBe(apiOrigin)
  await expect(page.getByRole('heading', { level: 1, name: pictured.name })).toBeVisible()
  await expect(page.getByRole('main').locator('img')).toHaveCount(0)

  await page.goto(`${UPCOMING_EVENTS_PATH}/${plain.id}`)
  await expect(page.getByRole('heading', { level: 1, name: plain.name })).toBeVisible()
  await expect(page.getByRole('main').locator('img')).toHaveCount(0)
})

// --- AC1: the list's other states ----------------------------------------------------------------
test('18.1 AC1: with no events open for registration, the page says so', async ({ page }) => {
  await stubEventsCall(page, () => ({ status: 200, body: { items: [], total: 0 } }))

  await openUpcomingEvents(page)

  await expect(page.getByText('No events are open for registration right now.')).toBeVisible()
  await expect(page.getByRole('heading', { level: 3 })).toHaveCount(0)
})

test('18.1 AC1: a list that fails to load says why', async ({ page }) => {
  await stubEventsCall(page, () => ({ status: 500, body: {} }))

  await openUpcomingEvents(page)

  await expect(page.getByRole('alert')).toHaveText(
    'The server hit a problem. Try again in a moment.',
  )
})

test('18.1 AC1: Load more adds the next page of events', async ({ page }) => {
  // Opened on 1 Jan 2029, so it is open and shows when it closes, not when it opened.
  const first = listedEvent('E2E First Page Talk', {
    places_left: 1,
    registration_opens_at: '2029-01-01T01:00:00Z',
  })
  // Closed, so its closing time has passed.
  const second = listedEvent('E2E Second Page Fair', {
    description: null,
    venues: [],
    state: 'CLOSED',
    registration_closes_at: '2026-10-01T10:00:00Z',
    places_left: 4,
  })
  await stubEventsCall(page, (offset) => ({
    status: 200,
    body: { items: offset === 0 ? [first] : [second], total: 2 },
  }))
  await openUpcomingEvents(page)
  await expect(eventCard(page, first.name)).toContainText('1 place left')
  await expect(eventCard(page, first.name)).toContainText(
    'Registration closes Tue, 27 Feb 2029, 18:00',
  )
  await expect(page.getByText('Showing 1 of 2 events')).toBeVisible()

  await page.getByRole('button', { name: 'Load more' }).click()

  const card = eventCard(page, second.name)
  await expect(card).toContainText('Venue to be confirmed')
  await expect(card).toContainText('4 places left')
  await expect(card).toContainText('Registration closed Thu, 1 Oct 2026, 18:00')
  await expect(eventCard(page, first.name)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0)
})

test('18.1 AC1: an event pushed onto the next page by one added ahead of it is shown once', async ({
  page,
}) => {
  const alpha = listedEvent('E2E Repeat Alpha')
  const bravo = listedEvent('E2E Repeat Bravo')
  const charlie = listedEvent('E2E Repeat Charlie')
  // Between the two loads an event was added ahead of these, so the second page starts with the
  // last one already shown.
  await stubEventsCall(page, (offset) => ({
    status: 200,
    body: { items: offset === 0 ? [alpha, bravo] : [bravo, charlie], total: 3 },
  }))
  await openUpcomingEvents(page)
  await expect(eventCard(page, bravo.name)).toBeVisible()

  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(eventCard(page, charlie.name)).toBeVisible()
  await expect(eventCard(page, alpha.name)).toHaveCount(1)
  await expect(eventCard(page, bravo.name)).toHaveCount(1)
})

test('18.1 AC1: a next page that fails to load keeps the events already shown', async ({
  page,
}) => {
  const first = listedEvent('E2E Only Page Talk')
  await stubEventsCall(page, (offset) =>
    offset === 0 ? { status: 200, body: { items: [first], total: 2 } } : { status: 500, body: {} },
  )
  await openUpcomingEvents(page)

  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(page.getByRole('alert')).toHaveText(
    'The server hit a problem. Try again in a moment.',
  )
  await expect(eventCard(page, first.name)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load more' })).toBeEnabled()
})

test('18.1 AC1: at phone width the events fit without sideways scrolling', async ({ page }) => {
  await page.setViewportSize(PHONE)
  await openUpcomingEvents(page)

  await expect(eventCard(page, JAZZ_EVENING)).toContainText('120 places left')
  await expectNoSidewaysScroll(page)
})

test("18.1 AC9: at phone width an event's page fits without sideways scrolling, even with a long link in its description, and Register is a full-width button big enough for a thumb", async ({
  page,
}) => {
  await changeEventCall(page, (event) => ({
    ...event,
    description: `${event.description} ${LONG_LINK}`,
  }))
  await page.setViewportSize(PHONE)
  await signIn(page, ACCOUNTS.attendee)
  await openEventPage(page, JAZZ_EVENING)

  const register = registerButton(page, JAZZ_EVENING)
  await expect(register).toBeVisible()
  await expect(page.getByRole('main')).toContainText(LONG_LINK)
  await expectNoSidewaysScroll(page)
  expect(await mainOverflow(page)).toBeLessThanOrEqual(0)
  const button = (await register.boundingBox())!
  expect(button.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
  expect(button.width).toBeGreaterThanOrEqual(PHONE.width * 0.75)
  expect(button.x + button.width).toBeLessThanOrEqual(PHONE.width)
})

test('18.1 AC9: an event with no description has no About section on its page', async ({
  page,
}) => {
  await changeEventCall(page, (event) => ({ ...event, description: null }))
  await signIn(page, ACCOUNTS.attendee)
  await openEventPage(page, JAZZ_EVENING)

  await expect(registerButton(page, JAZZ_EVENING)).toBeVisible()
  await expect(page.getByText('About this event')).toHaveCount(0)
})

// --- AC3: full, closed and not yet open -------------------------------------------------------
test('18.1 AC3: a full event and a closed one stay listed, and Register on their page is disabled', async ({
  page,
}) => {
  await openUpcomingEvents(page)

  const full = eventCard(page, PORTFOLIO_REVIEW)
  await expectBadge(full, 'Full', FULL_BADGE)
  await expect(full).toContainText('0 places left')
  const closed = eventCard(page, WINE_APPRECIATION)
  await expectBadge(closed, 'Closed', CLOSED_BADGE)
  await expect(closed).toContainText('Registration closed Thu, 1 Oct 2026, 18:00')

  await openEventPage(page, PORTFOLIO_REVIEW)
  await expectBadge(registrationSection(page), 'Full', FULL_BADGE)
  await expect(registrationSection(page)).toContainText('0 places left')
  await expect(registerButton(page, PORTFOLIO_REVIEW)).toBeDisabled()

  await page.getByRole('link', { name: BACK_TO_LIST }).click()
  await openEventPage(page, WINE_APPRECIATION)
  await expectBadge(registrationSection(page), 'Closed', CLOSED_BADGE)
  await expect(registrationSection(page)).toContainText(
    'Registration closed Thu, 1 Oct 2026, 18:00',
  )
  await expect(registerButton(page, WINE_APPRECIATION)).toBeDisabled()
})

test('18.1 AC3: an event whose registration has not opened shows when it opens, and its page when it opens and closes, with Register disabled', async ({
  page,
}) => {
  await openUpcomingEvents(page)

  const card = eventCard(page, LUNAR_NEW_YEAR_MARKET)
  await expectBadge(card, 'Not yet open', NOT_YET_OPEN_BADGE)
  await expect(card).toContainText('Registration opens Mon, 10 Jan 2028, 10:00')

  await openEventPage(page, LUNAR_NEW_YEAR_MARKET)
  const box = registrationSection(page)
  await expectBadge(box, 'Not yet open', NOT_YET_OPEN_BADGE)
  await expect(box).toContainText('Registration opens Mon, 10 Jan 2028, 10:00')
  await expect(box).toContainText('Registration closes Mon, 24 Jan 2028, 18:00')
  await expect(registerButton(page, LUNAR_NEW_YEAR_MARKET)).toBeDisabled()
})

// --- AC10: no page for an event that is not listed ---------------------------------------------
test('18.1 AC10: the address of an event that is not open for registration says so', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)

  // Planning, so never listed, and no attendee has registered for it.
  await page.goto(`${UPCOMING_EVENTS_PATH}/${EVENTS.planning}`)

  await expect(page.getByRole('main').getByRole('alert')).toHaveText(NOT_OPEN_MESSAGE)
  await expect(registrationSection(page)).toHaveCount(0)
  await page.getByRole('link', { name: BACK_TO_LIST }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Upcoming events' })).toBeVisible()
})

test("18.1 AC10: an address that is no event's id says the event is not open for registration, as for an unknown one", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)

  await page.goto(`${UPCOMING_EVENTS_PATH}/not-an-event`)

  await expect(page.getByRole('main').getByRole('alert')).toHaveText(NOT_OPEN_MESSAGE)
  await expect(registrationSection(page)).toHaveCount(0)
})

// --- AC11: an event that changes while its page is open ----------------------------------------
test('18.1 AC11: Register on an event that stopped taking registrations while its page was open says so, and the page then says it is not open', async ({
  page,
}) => {
  // The seed cannot unconfirm or cancel an event mid-test, so the server's answers for one that
  // has just stopped taking registrations stand in: the registration is refused, and from then on
  // the event has no page. Nothing is written: the jazz evening stays read-only.
  let hasClosed = false
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH || url.pathname.startsWith(`${EVENTS_API_PATH}/`),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST') hasClosed = true
      if (!hasClosed) return route.fallback()
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify({ detail: NOT_OPEN_MESSAGE }),
      })
    },
  )
  await openUpcomingEvents(page)
  await openEventPage(page, JAZZ_EVENING)

  await registerButton(page, JAZZ_EVENING).click()
  await confirmRegistration(page)

  await expect(page.getByRole('main').getByRole('alert')).toHaveText(NOT_OPEN_MESSAGE)
  await expect(registrationSection(page)).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: NOT_OPEN_MESSAGE })).toContainText(
    'Cannot register',
  )
})

test('18.1 AC11: a refused registration still says why, with the event, when the event cannot be read again after it', async ({
  page,
}) => {
  // The registration is stubbed as refused - the event filled up - and the event's reload after
  // it as a server failure, so nothing is written: the jazz evening stays read-only.
  let hasRefused = false
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH || url.pathname.startsWith(`${EVENTS_API_PATH}/`),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST') {
        hasRefused = true
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ detail: EVENT_FULL_MESSAGE }),
        })
      }
      if (!hasRefused) return route.fallback()
      return route.fulfill({
        status: 500,
        contentType: 'text/plain',
        headers: corsHeaders(request),
        body: 'Internal Server Error',
      })
    },
  )
  await signIn(page, ACCOUNTS.attendee)
  await openEventPage(page, JAZZ_EVENING)

  await registerButton(page, JAZZ_EVENING).click()
  await confirmRegistration(page)

  await expect(
    page.getByRole('main').getByRole('alert').filter({ hasText: 'Internal Server Error' }),
  ).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: JAZZ_EVENING })).toBeVisible()
  const box = registrationSection(page)
  await expect(box.getByRole('alert')).toHaveText(EVENT_FULL_MESSAGE)
  await expectBadge(box, 'Open', OPEN_BADGE)
  await expect(registerButton(page, JAZZ_EVENING)).toBeVisible()
})

// --- AC5: attendees only ------------------------------------------------------------------------
test('18.1 AC5: an organiser who opens Upcoming events is told it is not permitted', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)

  await page.goto(UPCOMING_EVENTS_PATH)

  await expect(page.getByRole('heading', { level: 1, name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: 'Upcoming events' })).toHaveCount(0)
})

test("18.1 AC5: an organiser who opens an event's page is told it is not permitted", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)

  await page.goto(`${UPCOMING_EVENTS_PATH}/${EVENTS.planning}`)

  await expect(page.getByRole('heading', { level: 1, name: 'Not permitted' })).toBeVisible()
  await expect(registrationSection(page)).toHaveCount(0)
})

// --- AC6: one registration each, and one winner for the last place ----------------------------
test.describe('registers for a seeded event once', () => {
  test.describe.configure({ retries: 0 })

  test('18.1 AC6: a double-click on Confirm and register sends one registration', async ({
    page,
  }) => {
    await openUpcomingEvents(page)
    await openEventPage(page, FOUNDERS_FIRESIDE)
    const sent: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === REGISTER_API_PATH) {
        sent.push(request.url())
      }
    })

    await registerButton(page, FOUNDERS_FIRESIDE).click()
    await confirmDetailsDialog(page)
      .getByRole('button', { name: CONFIRM_AND_REGISTER, exact: true })
      .dblclick()

    await expectBadge(registrationSection(page), 'Registered', REGISTERED_BADGE)
    await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0)
    expect(sent).toHaveLength(1)
  })

  test('18.1 AC6/AC11: when another attendee takes the last place first, Register on its page says the event is full, and the page shows it full', async ({
    page,
    browser,
  }) => {
    await openUpcomingEvents(page)
    await openEventPage(page, MENTORING_SLOT)
    await expect(registrationSection(page)).toContainText('1 place left')

    const otherContext = await browser.newContext({ baseURL: new URL(page.url()).origin })
    const other = await otherContext.newPage()
    await openUpcomingEvents(other, ACCOUNTS.attendee2)
    await openEventPage(other, MENTORING_SLOT)
    await registerButton(other, MENTORING_SLOT).click()
    await confirmRegistration(other)
    await expectBadge(registrationSection(other), 'Registered', REGISTERED_BADGE)
    await otherContext.close()

    await registerButton(page, MENTORING_SLOT).click()
    await confirmRegistration(page)

    const box = registrationSection(page)
    await expect(box.getByRole('alert')).toHaveText('This event is full.')
    await expect(page.getByRole('status').filter({ hasText: 'This event is full.' })).toContainText(
      'Cannot register',
    )
    await expectBadge(box, 'Full', FULL_BADGE)
    await expect(box).toContainText('0 places left')
    await expect(registerButton(page, MENTORING_SLOT)).toBeDisabled()
  })
})
