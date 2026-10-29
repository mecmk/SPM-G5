import { expect, test, type Page, type Request } from '@playwright/test'
import { ACCOUNTS, confirmRegistration, corsHeaders, signIn } from './support'

/**
 * Story 18.2 - view and withdraw my registrations. END-TO-END tests: what an attendee clicks.
 *
 * Level: e2e. Each test drives the real app and API in a browser. The rules behind what it shows -
 * which status a registration takes, the event's start as the last moment to withdraw, one active
 * registration at a time, whose registrations the API sends, which events have a page, the races
 * - are proven in backend/tests/registrations/ (unit and integration), not repeated here.
 *
 * AC1 The attendee sees their registrations, each card with its event's name, picture, date and
 *     status, and when they registered while they still are - no history of when they withdrew.
 *     An active registration is withdrawn from its event's page (AC9) after confirmation, and the
 *     place returns to capacity.
 * AC3 Once the event has started, its page offers no Withdraw and says why; a withdrawal refused
 *     because the event started meanwhile says so.
 * AC4 After withdrawing, the attendee can register again from the event's page, and the event is
 *     listed once, as Registered.
 * AC5 Only attendees can open the page. Whose registrations the API sends, and its 401/403, are
 *     backend cases: the page shows what it is sent and filters nothing itself.
 * AC6 A withdrawal answered "not found" says so (whose registrations the API answers for is a
 *     backend case).
 * AC7 A double-click withdraws once.
 * AC8 A registration for a cancelled event shows as Event cancelled, with no Withdraw.
 * AC9 (fix f18.2.1) Clicking anywhere on a registration's card opens its event's page (18.1
 *     AC9), which also shows where the attendee stands - one badge - and when they registered,
 *     while they still are. Withdraw is only on this page, and red; once withdrawn, the page shows
 *     where registration stands, as for an attendee who never registered - Open, say - and offers
 *     Register again. A back link returns to My registrations.
 * AC10 (fix f18.2.1) The page of an event the attendee registered for opens even once it is no
 *     longer listed - here, started or cancelled - with no places left or Register. Which events
 *     those are is a backend case.
 * AC11 (fix f18.2.1) A withdrawal refused because the event started or was cancelled while its
 *     page was open says why, and the page then shows where the attendee stands.
 *
 * Every test is independent: each case that withdraws has a seeded registration of its own
 * (backend/db/seed/020_sample_data.sql, 1818..02-09 for events 3333..70-77), so tests running in
 * parallel never withdraw the same one, and every other case only reads. Those that withdraw
 * never retry: a retry could only fail on what the first attempt changed, and would hide that
 * attempt's trace. States the seed cannot reach - no registrations at all, a slow or failed load,
 * an event starting or cancelled mid-visit, a registration gone mid-visit - stub the calls with
 * `page.route`.
 */

const MY_REGISTRATIONS_PATH = '/registrations'
const UPCOMING_EVENTS_PATH = '/browse'
const MINE_API_PATH = '/registrations'
const PAGE_API_PATH = /^\/registrations\/events\/[^/]+$/
const WITHDRAW_API_PATH = /^\/registrations\/[^/]+\/withdraw$/
const BACK_TO_LIST = '← My registrations'

const POETRY_NIGHT = 'Riverside Poetry Night' // one place, Aiden's; withdrawn once, and it returns
const SKETCHING_WALK = 'Urban Sketching Walk' // withdrawn and registered for again
const BOARD_GAMES_SOCIAL = 'Board Games Social' // Withdraw double-clicked once
const SUNSET_YOGA = 'Sunset Yoga by the Bay' // only read
const LANTERN_PAINTING = 'Lantern Painting Workshop' // withdrawn once the server answers again
const HERITAGE_TRAIL = 'Heritage Trail Tour' // Aiden withdrew
const CHARITY_FUN_RUN = 'Charity Fun Run' // cancelled, Aiden's registration still active
const BOOK_SWAP = 'Autumn Book Swap' // started on 3 Oct 2026

const EVENT_STARTED_MESSAGE = 'This event has started, so you can no longer withdraw.'
const EVENT_CANCELLED_MESSAGE = 'This event was cancelled, so there is nothing to withdraw from.'
const NOT_FOUND_MESSAGE = 'This registration was not found.'
const UNREACHABLE_MESSAGE = 'The server could not be reached. Check your connection and try again.'
const STARTED_NOTE = 'This event has started, so it can no longer be withdrawn.'
// A picture (2.1 AC14) is decorative - no alt text, hidden from assistive technology - so it has
// no role or name, and is found by its tag. The yoga has the seeded one; an uploaded one is served
// by the API (mediaUrl).
const YOGA_PICTURE = '/images/events/cat.jpg'
const UPLOADED_PICTURE_PATH = '/uploads/events/e2e-harbourfront.png'
const PNG_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)
const LOADING_LABEL = 'Loading your registrations…'
const EMPTY_MESSAGE = 'You have not registered for any events yet.'
const PHONE_WIDTH = 390

/** A registration's card, found by its event's name. Upcoming events (18.1) uses the same card. */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

/** AC9: where an event's page says where the attendee stands, and offers Withdraw. */
function registration(page: Page) {
  return page.getByRole('region', { name: 'Registration', exact: true })
}

function withdrawButton(page: Page, name: string) {
  return registration(page).getByRole('button', { name: `Withdraw from ${name}` })
}

function withdrawDialog(page: Page, name: string) {
  return page.getByRole('dialog', { name: `Withdraw from ${name}?` })
}

async function confirmWithdrawal(page: Page, name: string) {
  await withdrawButton(page, name).click()
  await withdrawDialog(page, name).getByRole('button', { name: 'Withdraw', exact: true }).click()
}

async function openMyRegistrations(page: Page, account: string = ACCOUNTS.attendee) {
  await signIn(page, account)
  await page.goto(MY_REGISTRATIONS_PATH)
  await expect(page.getByRole('heading', { level: 1, name: 'My registrations' })).toBeVisible()
}

/** AC9: from My registrations, open a registration's event page by its card's link, its title. */
async function openEventPage(page: Page, name: string) {
  await eventCard(page, name).getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

async function openRegisteredEvent(page: Page, name: string) {
  await openMyRegistrations(page)
  await openEventPage(page, name)
}

/** Every withdrawal the page sends from now on. */
function trackWithdrawals(page: Page): string[] {
  const sent: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && WITHDRAW_API_PATH.test(new URL(request.url()).pathname)) {
      sent.push(request.url())
    }
  })
  return sent
}

async function expectNoSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

/**
 * Answer the page's `method` call to a path matching `isPath` with `status` and `body` instead of
 * the API. Only the `fetch` is stubbed; the CORS headers go with it, since the app and the API run
 * on different ports.
 */
async function stubCall(
  page: Page,
  method: string,
  isPath: (pathname: string) => boolean,
  answer: { status: number; body: unknown },
) {
  await page.route(
    (url) => isPath(url.pathname),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== method) {
        return route.fallback()
      }
      return route.fulfill({
        status: answer.status,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify(answer.body),
      })
    },
  )
}

/** An event's page as the API sends it: here only what the stubs below change. */
interface EventPageBody {
  listing: unknown
  registration: { status: string; can_withdraw: boolean }
}

/**
 * AC11: the server's answers once the yoga has changed while its page was open - withdrawing it is
 * refused with `refusal`, and from then on its page is the server's, changed by `change`. Nothing
 * is written: the yoga stays read-only.
 */
async function stubChangedMeanwhile(
  page: Page,
  refusal: string,
  change: (body: EventPageBody) => EventPageBody,
) {
  let hasChanged = false
  await page.route(
    (url) => PAGE_API_PATH.test(url.pathname) || WITHDRAW_API_PATH.test(url.pathname),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST') {
        hasChanged = true
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ detail: refusal }),
        })
      }
      if (!hasChanged) return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, json: change((await response.json()) as EventPageBody) })
    },
  )
}

// --- AC1: the list -----------------------------------------------------------------------------
test('18.2 AC1: an attendee opens My registrations from the sidebar and sees each registration with its event, date and status', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.attendee)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'My registrations' })
    .click()

  await expect(page).toHaveURL(new RegExp(`${MY_REGISTRATIONS_PATH}$`))
  const yoga = eventCard(page, SUNSET_YOGA)
  await expect(yoga.getByText('Registered', { exact: true })).toBeVisible()
  // Each status keeps the badge colour it has everywhere else (App.css).
  await expect(yoga.getByText('Registered', { exact: true })).toHaveClass(/\bbadge-registered\b/)
  await expect(yoga).toContainText('Sat, 27 Mar 2027 · 18:00–19:00')
  await expect(yoga).toContainText('You registered on Sun, 11 Oct 2026, 10:15')
  await expect(yoga.locator('img')).toHaveAttribute('src', YOGA_PICTURE)
  // AC9: Withdraw is on the event's page, not its card.
  await expect(yoga.getByRole('button')).toHaveCount(0)

  const trail = eventCard(page, HERITAGE_TRAIL)
  await expect(trail.getByText('Withdrawn', { exact: true })).toBeVisible()
  await expect(trail.getByText('Withdrawn', { exact: true })).toHaveClass(/\bbadge-withdrawn\b/)
  await expect(trail).toContainText('Sat, 3 Apr 2027 · 09:00–12:00')
  // Where the attendee stands now, not a history: no longer registered, so no time is given.
  await expect(trail).not.toContainText('You withdrew on')
  await expect(trail).not.toContainText('You registered on')
  await expect(trail.getByRole('button')).toHaveCount(0)

  // With registrations to show, neither the loading state nor the empty one is left on the page.
  await expect(page.getByRole('status').filter({ hasText: LOADING_LABEL })).toHaveCount(0)
  await expect(page.getByText(EMPTY_MESSAGE)).toHaveCount(0)
})

test('18.2 AC1: while the registrations load, the page says so', async ({ page }) => {
  // Hold the list back until the loading state has been seen, then let the real answer through.
  let releaseList: () => void = () => {}
  const listHeld = new Promise<void>((resolve) => {
    releaseList = resolve
  })
  await page.route(
    (url) => url.pathname === MINE_API_PATH,
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() === 'fetch' && request.method() === 'GET') await listHeld
      return route.fallback()
    },
  )

  await openMyRegistrations(page)

  const loading = page.getByRole('status').filter({ hasText: LOADING_LABEL })
  await expect(loading).toBeVisible()
  releaseList()
  await expect(eventCard(page, SUNSET_YOGA)).toBeVisible()
  await expect(loading).toHaveCount(0)
})

test('18.2 AC1: with no registrations, the page says so and points to Upcoming events', async ({
  page,
}) => {
  await stubCall(page, 'GET', (pathname) => pathname === MINE_API_PATH, { status: 200, body: [] })

  await openMyRegistrations(page)

  await expect(page.getByText(EMPTY_MESSAGE)).toHaveText(`${EMPTY_MESSAGE} Browse upcoming events`)
  await expect(page.getByRole('heading', { level: 3 })).toHaveCount(0)
  await expect(page.getByRole('main').getByRole('list')).toHaveCount(0)
  await page.getByRole('link', { name: 'Browse upcoming events' }).click()
  await expect(page).toHaveURL(new RegExp(`${UPCOMING_EVENTS_PATH}$`))
})

test('18.2 AC1: a list that fails to load says why', async ({ page }) => {
  await stubCall(page, 'GET', (pathname) => pathname === MINE_API_PATH, { status: 500, body: {} })

  await openMyRegistrations(page)

  await expect(page.getByRole('alert')).toHaveText(
    'The server hit a problem. Try again in a moment.',
  )
})

// --- AC9: the event's page ---------------------------------------------------------------------
test("18.2 AC9: clicking anywhere on a registration's card opens its event's page, with where the attendee stands and Withdraw, and the back link returns to My registrations", async ({
  page,
}) => {
  await openMyRegistrations(page)

  // Not the title, which is the card's link: anywhere else on the card opens the event too.
  await eventCard(page, SUNSET_YOGA).getByText('You registered on Sun, 11 Oct 2026, 10:15').click()

  await expect(page).toHaveURL(new RegExp(`${UPCOMING_EVENTS_PATH}/[0-9a-f-]{36}$`))
  await expect(page.getByRole('heading', { level: 1, name: SUNSET_YOGA })).toBeVisible()
  const main = page.getByRole('main')
  await expect(main).toContainText('An hour of gentle yoga as the sun goes down.')
  await expect(main).toContainText('Sat, 27 Mar 2027 · 18:00–19:00')
  await expect(main.locator('img')).toHaveAttribute('src', YOGA_PICTURE)
  const box = registration(page)
  await expect(box.getByText('Registered', { exact: true })).toHaveClass(/\bbadge-registered\b/)
  await expect(box).toContainText('You registered on Sun, 11 Oct 2026, 10:15')
  await expect(withdrawButton(page, SUNSET_YOGA)).toBeEnabled()
  // Withdraw is red, as giving up a place is - its confirmation's button too.
  await expect(withdrawButton(page, SUNSET_YOGA)).toHaveClass(/\bdanger\b/)

  await page.getByRole('link', { name: BACK_TO_LIST }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'My registrations' })).toBeVisible()
  await expect(eventCard(page, SUNSET_YOGA)).toBeVisible()
})

test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test("18.2 AC1/AC9: withdrawing on the event's page after confirming shows it open again with Register, the card Withdrawn, and Upcoming events has the place back", async ({
    page,
  }) => {
    await openRegisteredEvent(page, POETRY_NIGHT)
    const box = registration(page)
    await expect(box.getByText('Registered', { exact: true })).toBeVisible()

    await withdrawButton(page, POETRY_NIGHT).click()
    const dialog = withdrawDialog(page, POETRY_NIGHT)
    await expect(dialog).toContainText('you may not be able to register again')
    await dialog.getByRole('button', { name: 'Withdraw', exact: true }).click()

    await expect(dialog).toHaveCount(0)
    await expect(
      page.getByRole('status').filter({ hasText: `You have withdrawn from ${POETRY_NIGHT}.` }),
    ).toContainText('Withdrawn')
    // The page shows where registration stands, as for an attendee who never registered: one
    // badge, Open, and when registration closes - not Withdrawn, nor when they registered and
    // withdrew.
    await expect(box.getByText('Open', { exact: true })).toBeVisible()
    await expect(box.getByText('Withdrawn', { exact: true })).toHaveCount(0)
    await expect(box).toContainText('Registration closes')
    await expect(box).not.toContainText('You registered on')
    await expect(box).not.toContainText('You withdrew on')
    await expect(withdrawButton(page, POETRY_NIGHT)).toHaveCount(0)
    // AC4: its one place is free again, so it can be registered for again here.
    await expect(box).toContainText('1 place left')
    const register = box.getByRole('button', { name: `Register for ${POETRY_NIGHT}` })
    await expect(register).toBeEnabled()
    // Register is the brand colour, apart from the page's other buttons (18.1, fix f18.1.2).
    await expect(register).toHaveClass(/\bbrand\b/)

    await page.reload()
    await expect(box.getByText('Open', { exact: true })).toBeVisible()
    await expect(box.getByText('Withdrawn', { exact: true })).toHaveCount(0)

    // My registrations is the attendee's registrations, so there the card says Withdrawn.
    await page.getByRole('link', { name: BACK_TO_LIST }).click()
    const card = eventCard(page, POETRY_NIGHT)
    await expect(card.getByText('Withdrawn', { exact: true })).toBeVisible()
    await expect(card).not.toContainText('You withdrew on')
    await expect(card).not.toContainText('You registered on')

    await page.goto(UPCOMING_EVENTS_PATH)
    const upcoming = eventCard(page, POETRY_NIGHT)
    await expect(upcoming).toContainText('1 place left')
    await expect(upcoming.getByText('Open', { exact: true })).toBeVisible()
  })
})

test('18.2 AC1: cancelling the confirmation keeps the registration and sends nothing', async ({
  page,
}) => {
  await openRegisteredEvent(page, SUNSET_YOGA)
  const sent = trackWithdrawals(page)

  await withdrawButton(page, SUNSET_YOGA).click()
  await withdrawDialog(page, SUNSET_YOGA).getByRole('button', { name: 'Cancel' }).click()
  await expect(withdrawDialog(page, SUNSET_YOGA)).toHaveCount(0)
  await withdrawButton(page, SUNSET_YOGA).click()
  await page.keyboard.press('Escape')
  await expect(withdrawDialog(page, SUNSET_YOGA)).toHaveCount(0)

  await expect(registration(page).getByText('Registered', { exact: true })).toBeVisible()
  await expect(withdrawButton(page, SUNSET_YOGA)).toBeEnabled()
  expect(sent).toHaveLength(0)
})

// The DoD's phone: an iPhone 12 Pro, emulated - its width alone lays text out narrower than the
// phone does, and hides a card whose details no longer fit beside its picture.
test.describe('on an iPhone 12 Pro', () => {
  test.use({
    viewport: { width: PHONE_WIDTH, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  })

  test('18.2 AC1: at phone width the registrations fit without sideways scrolling', async ({
    page,
  }) => {
    await openMyRegistrations(page)

    await expect(eventCard(page, SUNSET_YOGA)).toBeVisible()
    await expectNoSidewaysScroll(page)
  })

  test('18.2 AC1: on a phone, a registration with wide details keeps its picture beside them', async ({
    page,
  }) => {
    // Wider details than any seeded registration has: a card whose details no longer fit beside
    // its picture is where the layout would break. The list call is stubbed, and so is its
    // uploaded picture, which the API would serve.
    await page.route(
      (url) => url.pathname === UPLOADED_PICTURE_PATH,
      (route) => route.fulfill({ status: 200, contentType: 'image/png', body: PNG_BYTES }),
    )
    const listRequest = page.waitForRequest(
      (request) =>
        request.resourceType() === 'fetch' &&
        request.method() === 'GET' &&
        new URL(request.url()).pathname === MINE_API_PATH,
    )
    await stubCall(page, 'GET', (pathname) => pathname === MINE_API_PATH, {
      status: 200,
      body: [
        {
          id: '00000000-0000-4000-8000-000000000183',
          event_id: '00000000-0000-4000-8000-000000000184',
          event_name: 'E2E Harbourfront Jazz and Food Festival Evening',
          cover_image_url: UPLOADED_PICTURE_PATH,
          starts_at: '2029-03-01T11:00:00Z',
          ends_at: '2029-03-01T14:00:00Z',
          status: 'REGISTERED',
          registered_at: '2026-10-11T02:00:00Z',
          withdrawn_at: null,
          can_withdraw: true,
          guest_name: null,
        },
      ],
    })
    await openMyRegistrations(page)

    const card = eventCard(page, 'E2E Harbourfront Jazz and Food Festival Evening')
    // An uploaded picture comes from the API, not the app's own origin.
    const apiOrigin = new URL((await listRequest).url()).origin
    await expect(card.locator('img')).toHaveAttribute('src', `${apiOrigin}${UPLOADED_PICTURE_PATH}`)
    const picture = await card.locator('img').boundingBox()
    const title = await card.getByRole('heading', { level: 3 }).boundingBox()
    if (picture === null || title === null) throw new Error('the card is not laid out')
    expect(title.x).toBeGreaterThanOrEqual(picture.x + picture.width)
    expect(title.y).toBeLessThan(picture.y + picture.height)
    await expectNoSidewaysScroll(page)
  })

  test("18.2 AC9: on a phone, an event's page fits without sideways scrolling, and Withdraw is full width and big enough for a thumb", async ({
    page,
  }) => {
    await openRegisteredEvent(page, SUNSET_YOGA)

    const withdraw = withdrawButton(page, SUNSET_YOGA)
    await expect(withdraw).toBeVisible()
    await expectNoSidewaysScroll(page)
    const button = (await withdraw.boundingBox())!
    expect(button.height).toBeGreaterThanOrEqual(44)
    expect(button.width).toBeGreaterThanOrEqual(PHONE_WIDTH * 0.75)
  })
})

// --- AC3 / AC10 / AC11: until the event starts -------------------------------------------------
test('18.2 AC3/AC10: a registration for an event that has started opens its page, which offers no Withdraw and says why', async ({
  page,
}) => {
  await openMyRegistrations(page)
  const card = eventCard(page, BOOK_SWAP)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
  await expect(card).toContainText('Sat, 3 Oct 2026 · 10:00–13:00')

  await openEventPage(page, BOOK_SWAP)

  const box = registration(page)
  await expect(box.getByText('Registered', { exact: true })).toBeVisible()
  await expect(box).toContainText(STARTED_NOTE)
  // AC10: no longer listed, so nothing about places or registering.
  await expect(box).not.toContainText('places left')
  await expect(box.getByRole('button')).toHaveCount(0)
})

test('18.2 AC3/AC11: a withdrawal refused because the event started meanwhile says why, and the page then offers no Withdraw', async ({
  page,
}) => {
  await stubChangedMeanwhile(page, EVENT_STARTED_MESSAGE, (body) => ({
    ...body,
    listing: null,
    registration: { ...body.registration, can_withdraw: false },
  }))
  await openRegisteredEvent(page, SUNSET_YOGA)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(EVENT_STARTED_MESSAGE)
  await expect(page.getByRole('status').filter({ hasText: EVENT_STARTED_MESSAGE })).toContainText(
    'Cannot withdraw',
  )
  // Refused for good, so Withdraw is no longer offered: only Close, which has the focus, so the
  // keyboard is still in the dialog and Escape closes it.
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  const box = registration(page)
  await expect(box.getByText('Registered', { exact: true })).toBeVisible()
  await expect(box).toContainText(STARTED_NOTE)
  await expect(withdrawButton(page, SUNSET_YOGA)).toHaveCount(0)
})

test('18.2 AC8/AC11: a withdrawal refused because the event was cancelled meanwhile says why, and the page then shows Event cancelled', async ({
  page,
}) => {
  await stubChangedMeanwhile(page, EVENT_CANCELLED_MESSAGE, (body) => ({
    ...body,
    listing: null,
    registration: { ...body.registration, status: 'EVENT_CANCELLED', can_withdraw: false },
  }))
  await openRegisteredEvent(page, SUNSET_YOGA)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(EVENT_CANCELLED_MESSAGE)
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toHaveCount(0)
  const box = registration(page)
  await expect(box.getByText('Event cancelled', { exact: true })).toBeVisible()
  await expect(box).not.toContainText('places left')
  await expect(box.getByRole('button')).toHaveCount(0)
})

test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test('18.2 AC1: a withdrawal that cannot reach the server says so, and can be tried again', async ({
    page,
  }) => {
    await openRegisteredEvent(page, LANTERN_PAINTING)
    const box = registration(page)
    await expect(box.getByText('Registered', { exact: true })).toBeVisible()

    // The first two withdrawals never reach the server; the third does. Each one loads the page
    // again: the first reload fails too, and the second reads the event before the third
    // withdrawal and answers only after it, as a slow connection would.
    let withdrawals = 0
    let reloads = 0
    let markStalePageRead: () => void = () => {}
    const stalePageRead = new Promise<void>((resolve) => {
      markStalePageRead = resolve
    })
    let releaseStalePage: () => void = () => {}
    const stalePageHeld = new Promise<void>((resolve) => {
      releaseStalePage = resolve
    })
    await page.route(
      (url) => PAGE_API_PATH.test(url.pathname) || WITHDRAW_API_PATH.test(url.pathname),
      async (route) => {
        const request: Request = route.request()
        if (request.resourceType() !== 'fetch') return route.fallback()
        if (request.method() === 'POST') {
          withdrawals += 1
          return withdrawals <= 2 ? route.abort('connectionrefused') : route.fallback()
        }
        if (request.method() !== 'GET') return route.fallback()
        reloads += 1
        if (reloads === 1) return route.abort('connectionrefused')
        if (reloads > 2) return route.fallback()
        const response = await route.fetch()
        markStalePageRead()
        await stalePageHeld
        return route.fulfill({ response })
      },
    )

    await confirmWithdrawal(page, LANTERN_PAINTING)
    const dialog = withdrawDialog(page, LANTERN_PAINTING)
    const withdraw = dialog.getByRole('button', { name: 'Withdraw', exact: true })
    await expect(dialog.getByRole('alert')).toHaveText(UNREACHABLE_MESSAGE)
    // The reload failed as well, so the page says so behind the dialog, still showing the event.
    await expect(page.getByRole('alert').filter({ hasText: UNREACHABLE_MESSAGE })).toHaveCount(2)
    await expect(box.getByText('Registered', { exact: true })).toBeVisible()
    await expect(withdraw).toBeEnabled()
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible()

    await withdraw.click()
    await expect(withdraw).toBeEnabled()
    await stalePageRead

    await withdraw.click()
    await expect(dialog).toHaveCount(0)
    await expect(
      page.getByRole('status').filter({ hasText: `You have withdrawn from ${LANTERN_PAINTING}.` }),
    ).toContainText('Withdrawn')
    await expect(box.getByText('Open', { exact: true })).toBeVisible()
    // The page loaded after the withdrawal that went through clears the earlier failure.
    await expect(page.getByRole('alert')).toHaveCount(0)

    // The slow answer, read before that withdrawal, lands last, and changes nothing.
    const stalePageAnswered = page.waitForEvent(
      'requestfinished',
      (request) =>
        request.resourceType() === 'fetch' &&
        request.method() === 'GET' &&
        PAGE_API_PATH.test(new URL(request.url()).pathname),
    )
    releaseStalePage()
    await stalePageAnswered
    await page.evaluate(
      () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
    )
    await expect(box.getByText('Open', { exact: true })).toBeVisible()
    await expect(withdrawButton(page, LANTERN_PAINTING)).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(withdrawals).toBe(3)
  })
})

// --- AC4: registering again --------------------------------------------------------------------
test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test("18.2 AC4: after withdrawing, registering again on the event's page makes the registration active again", async ({
    page,
  }) => {
    await openRegisteredEvent(page, SKETCHING_WALK)
    await confirmWithdrawal(page, SKETCHING_WALK)
    const box = registration(page)
    await expect(box.getByText('Open', { exact: true })).toBeVisible()

    await box.getByRole('button', { name: `Register for ${SKETCHING_WALK}` }).click()
    await confirmRegistration(page)
    await expect(box.getByText('Registered', { exact: true })).toBeVisible()
    await expect(withdrawButton(page, SKETCHING_WALK)).toBeEnabled()

    await page.getByRole('link', { name: BACK_TO_LIST }).click()
    await expect(eventCard(page, SKETCHING_WALK)).toHaveCount(1)
    await expect(
      eventCard(page, SKETCHING_WALK).getByText('Registered', { exact: true }),
    ).toBeVisible()
  })
})

test('18.2 AC6: a withdrawal of a registration that is no longer found says so', async ({
  page,
}) => {
  // The page only offers the attendee's own registration, so a 404 means it went meanwhile.
  await stubCall(page, 'POST', (pathname) => WITHDRAW_API_PATH.test(pathname), {
    status: 404,
    body: { detail: NOT_FOUND_MESSAGE },
  })
  await openRegisteredEvent(page, SUNSET_YOGA)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(NOT_FOUND_MESSAGE)
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: NOT_FOUND_MESSAGE })).toContainText(
    'Cannot withdraw',
  )

  // The refusal was for that attempt: Withdraw opens the dialog afresh, with no message and its
  // own Withdraw. (The reload shows the yoga still registered, since only the call was stubbed.)
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toHaveCount(0)
  await withdrawButton(page, SUNSET_YOGA).click()
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toBeEnabled()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible()
})

// --- AC5: attendees only -----------------------------------------------------------------------
test('18.2 AC5: an organiser who opens My registrations is told it is not permitted', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)

  await page.goto(MY_REGISTRATIONS_PATH)

  await expect(page.getByRole('heading', { level: 1, name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: 'My registrations' })).toHaveCount(0)
})

// --- AC7: a double-click withdraws once ------------------------------------------------------
test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test('18.2 AC7: a double-click on Withdraw sends one withdrawal', async ({ page }) => {
    await openRegisteredEvent(page, BOARD_GAMES_SOCIAL)
    const sent = trackWithdrawals(page)

    await withdrawButton(page, BOARD_GAMES_SOCIAL).click()
    await withdrawDialog(page, BOARD_GAMES_SOCIAL)
      .getByRole('button', { name: 'Withdraw', exact: true })
      .dblclick()

    await expect(registration(page).getByText('Open', { exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(sent).toHaveLength(1)
  })
})

// --- AC8 / AC10: a cancelled event -------------------------------------------------------------
test('18.2 AC8/AC10: a registration for a cancelled event shows Event cancelled, and its page offers no Withdraw', async ({
  page,
}) => {
  await openMyRegistrations(page)

  const card = eventCard(page, CHARITY_FUN_RUN)
  await expect(card.getByText('Event cancelled', { exact: true })).toBeVisible()
  // A cancelled event's colour, as every event status shows it - not a cancelled booking's.
  await expect(card.getByText('Event cancelled', { exact: true })).toHaveClass(
    /\bbadge-event_cancelled\b/,
  )
  await expect(card).toContainText('Sat, 10 Apr 2027 · 07:00–10:00')
  await expect(card.getByRole('button')).toHaveCount(0)

  await openEventPage(page, CHARITY_FUN_RUN)

  const box = registration(page)
  await expect(box.getByText('Event cancelled', { exact: true })).toBeVisible()
  await expect(box).not.toContainText(STARTED_NOTE)
  await expect(box).not.toContainText('places left')
  await expect(box.getByRole('button')).toHaveCount(0)
})
