import { expect, test, type Page, type Request } from '@playwright/test'
import {
  ACCOUNTS,
  CONFIRM_AND_REGISTER,
  confirmDetailsDialog,
  confirmRegistration,
  corsHeaders,
  signIn,
} from './support'

/**
 * Story 18.1 - browse and register for an event. END-TO-END tests: what an attendee clicks.
 *
 * Level: e2e. Each test drives the real app and API in a browser. The rules behind what it shows -
 * the last place, the closing and opening times, which events are listed, who may register, the
 * races - are proven in backend/tests/registrations/ (unit and integration), not repeated here.
 *
 * AC1 Confirmed, Public events with registration enabled that have not started are listed
 *     soonest first, a page at a time, with name, description, date, time, each booked venue's
 *     name and location, the places left and the registration state. Registering - Register,
 *     then confirming the attendee's details (story 18.4) - shows a confirmation with its time;
 *     the event then shows as Registered.
 * AC3 Full, closed and not-yet-open events stay listed, with Register disabled.
 * AC4 An event no longer open to attendees refuses registration, and the page says so, naming
 *     the event, once the reloaded list no longer shows it.
 * AC5 Only attendees can open Upcoming events (the API's 401/403 are backend cases).
 * AC6 A second registration is refused, also when both arrive at once; of two attendees competing
 *     for the last place, one succeeds and the other is told the event is full. No Register can be
 *     pressed while a registration is being sent, and a double-click on Confirm and register (story
 *     18.4) sends one.
 * AC8 (fix f18.1.1, proposed, waiting on the backlog's Change Log) Each event shows its cover
 *     picture (2.1 AC14), or the placeholder when it has none or its picture can't be loaded. An
 *     uploaded picture is loaded from the API. What the list sends is a backend case.
 *
 * Every test is independent: each case that registers has a seeded event of its own
 * (backend/db/seed/020_sample_data.sql, 3333..39-45), so tests running in parallel never share a
 * place, and every other case only reads. Those three never retry: a retry could only fail on
 * what the first attempt changed, and would hide that attempt's trace. States the seed cannot
 * reach - no events at all, a failed load, a second page, an event closed mid-visit, a slow
 * answer - stub the calls with `page.route`, answering as the server would.
 */

const UPCOMING_EVENTS_PATH = '/browse'
const EVENTS_API_PATH = '/registrations/events'
// AC8: a card's picture is decorative - no alt text, hidden from assistive technology - so it has
// no role or name, and is found by its tag. The jazz evening has the seeded one; an uploaded one
// is served by the API (mediaUrl).
const JAZZ_PICTURE = '/images/events/cat.jpg'
const UPLOADED_PICTURE_PATH = '/uploads/events/e2e-pictured-gala.png'
const REGISTER_API_PATH = '/registrations'

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

function registerButton(page: Page, name: string) {
  return eventCard(page, name).getByRole('button', { name: `Register for ${name}` })
}

async function openUpcomingEvents(page: Page, account: string = ACCOUNTS.attendee) {
  await signIn(page, account)
  await page.goto(UPCOMING_EVENTS_PATH)
  await expect(page.getByRole('heading', { level: 1, name: 'Upcoming events' })).toBeVisible()
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

/** A listed event as the API sends it, for a stubbed list. */
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
test('18.1 AC1: an attendee finds an open event under Upcoming events, with its date, time, venues and places left', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Upcoming events' })
    .click()

  await expect(page).toHaveURL(new RegExp(`${UPCOMING_EVENTS_PATH}$`))
  const card = eventCard(page, JAZZ_EVENING)
  await expect(card).toContainText('Live jazz on the waterfront, with food stalls in the foyer.')
  await expect(card).toContainText('Sat, 7 Oct 2028 · 19:00–22:00')
  await expect(card).toContainText('Grand Hall, Tower A, Level 1')
  await expect(card).toContainText('Exhibition Foyer, Tower B, Level 1')
  await expect(card).toContainText('120 places left')
  await expect(card).toContainText('Registration closes Thu, 5 Oct 2028, 18:00')
  await expect(card.getByText('Open', { exact: true })).toBeVisible()
  await expect(registerButton(page, JAZZ_EVENING)).toBeEnabled()
})

test.describe('registers for a seeded event once', () => {
  test.describe.configure({ retries: 0 })

  test('18.1 AC1: registering shows a confirmation with its time at once, and the event stays Registered after a reload', async ({
    page,
  }) => {
    await openUpcomingEvents(page)
    const card = eventCard(page, DESIGN_MASTERCLASS)
    await expect(card).toContainText('60 places left')

    // The list loaded again after registering is held back until the card has been checked, so
    // what the card shows comes from the registration's own answer, as soon as it arrives.
    let hasRegistered = false
    let releaseReload: () => void = () => {}
    const reloadHeld = new Promise<void>((resolve) => {
      releaseReload = resolve
    })
    await page.route(
      (url) => url.pathname === REGISTER_API_PATH || url.pathname === EVENTS_API_PATH,
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
    await expect(card.getByText('Registered', { exact: true })).toBeVisible()
    await expect(card).toContainText(registeredToday(before, after))
    await expect(card).toContainText('59 places left')
    await expect(card.getByRole('button')).toHaveCount(0)
    releaseReload()

    await page.reload()
    await expect(card.getByText('Registered', { exact: true })).toBeVisible()
    await expect(card).toContainText(registeredToday(before, after))
    await expect(card).toContainText('59 places left')
  })
})

test('18.1 AC8: an event with a cover picture shows it on its card', async ({ page }) => {
  await openUpcomingEvents(page)

  const picture = eventCard(page, JAZZ_EVENING).locator('img')
  await expect(picture).toHaveAttribute('src', JAZZ_PICTURE)
  // Loaded, not only asked for: a picture that fails to load gives way to the placeholder.
  await expect
    .poll(() => picture.evaluate((img: HTMLImageElement) => img.naturalWidth))
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

test('18.1 AC1: a failed next page is no longer reported once the list is loaded again after registering', async ({
  page,
}) => {
  const first = listedEvent('E2E Retry Page Talk')
  await stubEventsCall(page, (offset) =>
    offset === 0 ? { status: 200, body: { items: [first], total: 2 } } : { status: 500, body: {} },
  )
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH,
    async (route) => {
      const request: Request = route.request()
      if (request.method() !== 'POST') return route.fallback()
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify({
          id: '00000000-0000-4000-8000-000000000181',
          event_id: first.id,
          status: 'REGISTERED',
          registered_at: '2026-10-15T02:00:00Z',
          guests: [],
        }),
      })
    },
  )
  await openUpcomingEvents(page)
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(page.getByRole('alert')).toHaveText(
    'The server hit a problem. Try again in a moment.',
  )

  await registerButton(page, first.name).click()
  await confirmRegistration(page)

  await expect(page.getByRole('alert')).toHaveCount(0)
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

test('18.1 AC1: at phone width the events fit without sideways scrolling, and Register is a full-width button big enough for a thumb', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openUpcomingEvents(page)

  const register = registerButton(page, JAZZ_EVENING)
  await expect(register).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)

  // The card's own control, below its details on a phone (story 5.4's card layout), as wide as
  // the card's text and at least 44px tall.
  const button = await register.boundingBox()
  const title = await eventCard(page, JAZZ_EVENING).getByRole('heading', { level: 3 }).boundingBox()
  if (button === null || title === null) throw new Error('the card is not laid out')
  expect(button.height).toBeGreaterThanOrEqual(44)
  expect(button.y).toBeGreaterThan(title.y)
  expect(button.width).toBeGreaterThanOrEqual(title.width)
})

// --- AC3: full, closed and not yet open -------------------------------------------------------
test('18.1 AC3: a full event and a closed one stay listed, with Register disabled', async ({
  page,
}) => {
  await openUpcomingEvents(page)

  const full = eventCard(page, PORTFOLIO_REVIEW)
  await expect(full.getByText('Full', { exact: true })).toBeVisible()
  await expect(full).toContainText('0 places left')
  await expect(registerButton(page, PORTFOLIO_REVIEW)).toBeDisabled()

  const closed = eventCard(page, WINE_APPRECIATION)
  await expect(closed.getByText('Closed', { exact: true })).toBeVisible()
  await expect(closed).toContainText('Registration closed Thu, 1 Oct 2026, 18:00')
  await expect(registerButton(page, WINE_APPRECIATION)).toBeDisabled()
})

test('18.1 AC3: an event whose registration has not opened shows when it opens, with Register disabled', async ({
  page,
}) => {
  await openUpcomingEvents(page)

  const card = eventCard(page, LUNAR_NEW_YEAR_MARKET)
  await expect(card.getByText('Not yet open', { exact: true })).toBeVisible()
  await expect(card).toContainText('Registration opens Mon, 10 Jan 2028, 10:00')
  await expect(registerButton(page, LUNAR_NEW_YEAR_MARKET)).toBeDisabled()
})

// --- AC4: an event that stops taking registrations ---------------------------------------------
test('18.1 AC4: Register on an event that stopped taking registrations while the page was open says so', async ({
  page,
}) => {
  // The seed cannot unconfirm or cancel an event mid-test, so the server's answers for one that
  // has just stopped taking registrations stand in: the registration is refused, and from then on
  // the list leaves the event out. Nothing is written: the jazz evening stays read-only.
  let hasClosed = false
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH || url.pathname === EVENTS_API_PATH,
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST') {
        hasClosed = true
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ detail: 'This event is not open for registration.' }),
        })
      }
      if (!hasClosed) return route.fallback()
      const response = await route.fetch()
      const listing = (await response.json()) as { items: { name: string }[]; total: number }
      return route.fulfill({
        response,
        json: {
          items: listing.items.filter((event) => event.name !== JAZZ_EVENING),
          total: listing.total - 1,
        },
      })
    },
  )
  await openUpcomingEvents(page)

  await registerButton(page, JAZZ_EVENING).click()
  await confirmRegistration(page)

  await expect(eventCard(page, JAZZ_EVENING)).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveText(
    `${JAZZ_EVENING}: This event is not open for registration.`,
  )
  await expect(
    page.getByRole('status').filter({ hasText: 'This event is not open for registration.' }),
  ).toContainText('Cannot register')
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

// --- AC6: one registration each, and one winner for the last place ----------------------------
test('18.1 AC6: while one registration is being sent, no other Register can be pressed', async ({
  page,
}) => {
  const sending = listedEvent('E2E Sending Talk')
  const waiting = listedEvent('E2E Waiting Fair')
  let hasRegistered = false
  await stubEventsCall(page, () => ({
    status: 200,
    body: {
      items: [
        hasRegistered
          ? {
              ...sending,
              state: 'REGISTERED',
              registered_at: '2026-10-15T02:00:00Z',
              places_left: 9,
            }
          : sending,
        waiting,
      ],
      total: 2,
    },
  }))
  let releaseRegistration: () => void = () => {}
  const registrationHeld = new Promise<void>((resolve) => {
    releaseRegistration = resolve
  })
  await page.route(
    (url) => url.pathname === REGISTER_API_PATH,
    async (route) => {
      const request: Request = route.request()
      if (request.method() !== 'POST') return route.fallback()
      await registrationHeld
      hasRegistered = true
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify({
          id: '00000000-0000-4000-8000-000000000182',
          event_id: sending.id,
          status: 'REGISTERED',
          registered_at: '2026-10-15T02:00:00Z',
          guests: [],
        }),
      })
    },
  )
  await openUpcomingEvents(page)

  await registerButton(page, sending.name).click()
  await confirmRegistration(page)

  await expect(registerButton(page, sending.name)).toBeDisabled()
  await expect(registerButton(page, waiting.name)).toBeDisabled()
  releaseRegistration()
  await expect(eventCard(page, sending.name).getByText('Registered', { exact: true })).toBeVisible()
  await expect(registerButton(page, waiting.name)).toBeEnabled()
})

test.describe('registers for a seeded event once', () => {
  test.describe.configure({ retries: 0 })

  test('18.1 AC6: a double-click on Confirm and register sends one registration', async ({
    page,
  }) => {
    await openUpcomingEvents(page)
    const sent: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === REGISTER_API_PATH) {
        sent.push(request.url())
      }
    })
    const card = eventCard(page, FOUNDERS_FIRESIDE)

    await registerButton(page, FOUNDERS_FIRESIDE).click()
    await confirmDetailsDialog(page)
      .getByRole('button', { name: CONFIRM_AND_REGISTER, exact: true })
      .dblclick()

    await expect(card.getByText('Registered', { exact: true })).toBeVisible()
    await expect(card.getByRole('alert')).toHaveCount(0)
    expect(sent).toHaveLength(1)
  })

  test('18.1 AC6: when another attendee takes the last place first, Register says the event is full', async ({
    page,
    browser,
  }) => {
    await openUpcomingEvents(page)
    const card = eventCard(page, MENTORING_SLOT)
    await expect(card).toContainText('1 place left')

    const otherContext = await browser.newContext({ baseURL: new URL(page.url()).origin })
    const other = await otherContext.newPage()
    await openUpcomingEvents(other, ACCOUNTS.attendee2)
    await registerButton(other, MENTORING_SLOT).click()
    await confirmRegistration(other)
    await expect(
      eventCard(other, MENTORING_SLOT).getByText('Registered', { exact: true }),
    ).toBeVisible()
    await otherContext.close()

    await registerButton(page, MENTORING_SLOT).click()
    await confirmRegistration(page)

    await expect(card.getByRole('alert')).toHaveText('This event is full.')
    await expect(page.getByRole('status').filter({ hasText: 'This event is full.' })).toContainText(
      'Cannot register',
    )
    await expect(card.getByText('Full', { exact: true })).toBeVisible()
    await expect(card).toContainText('0 places left')
    await expect(registerButton(page, MENTORING_SLOT)).toBeDisabled()
  })
})
