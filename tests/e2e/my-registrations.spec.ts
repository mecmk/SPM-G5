import { expect, test, type Page, type Request } from '@playwright/test'
import { ACCOUNTS, corsHeaders, signIn } from './support'

/**
 * Story 18.2 - view and withdraw my registrations. END-TO-END tests: what an attendee clicks.
 *
 * Level: e2e. Each test drives the real app and API in a browser. The rules behind what it shows -
 * which status a registration takes, the event's start as the last moment to withdraw, one active
 * registration at a time, whose registrations the API sends, the races - are proven in
 * backend/tests/registrations/ (unit and integration), not repeated here.
 *
 * AC1 The attendee sees their registrations with event name, date and status. An active
 *     registration can be withdrawn after confirmation, and the place returns to capacity.
 * AC3 A registration for an event that has started offers no Withdraw; a withdrawal refused
 *     because the event started meanwhile says so.
 * AC4 After withdrawing, the attendee can register again from Upcoming events, and the event is
 *     listed once, as Registered.
 * AC5 Attendees see only their own registrations, and only attendees can open the page (the API's
 *     401/403 are backend cases).
 * AC6 A withdrawal answered "not found" says so (whose registrations the API answers for is a
 *     backend case).
 * AC7 A double-click withdraws once.
 * AC8 A registration for a cancelled event shows as Event cancelled, with no Withdraw.
 *
 * Every test is independent: each case that withdraws has a seeded registration of its own
 * (backend/db/seed/020_sample_data.sql, 1818..02-08 for events 3333..70-76), so tests running in
 * parallel never share one, and every other case only reads. Those that withdraw never retry: a
 * retry could only fail on what the first attempt changed, and would hide that attempt's trace.
 * States the seed cannot reach - no registrations at all, a slow or failed load, an event starting
 * mid-visit, a registration gone mid-visit - stub the one call with `page.route`.
 */

const MY_REGISTRATIONS_PATH = '/registrations'
const UPCOMING_EVENTS_PATH = '/browse'
const MINE_API_PATH = '/registrations'
const WITHDRAW_API_PATH = /^\/registrations\/[^/]+\/withdraw$/

const POETRY_NIGHT = 'Riverside Poetry Night' // one place, Aiden's; withdrawn once, and it returns
const SKETCHING_WALK = 'Urban Sketching Walk' // withdrawn and registered for again
const BOARD_GAMES_SOCIAL = 'Board Games Social' // Withdraw double-clicked once
const SUNSET_YOGA = 'Sunset Yoga by the Bay' // only read
const HERITAGE_TRAIL = 'Heritage Trail Tour' // Aiden withdrew
const CHARITY_FUN_RUN = 'Charity Fun Run' // cancelled, Aiden's registration still active
const BOOK_SWAP = 'Autumn Book Swap' // started on 3 Oct 2026
const PORTFOLIO_REVIEW = 'Portfolio Review Slot' // Bella's (story 18.1), never Aiden's

const EVENT_STARTED_MESSAGE = 'This event has started, so you can no longer withdraw.'
const NOT_FOUND_MESSAGE = 'This registration was not found.'
const UNREACHABLE_MESSAGE = 'The server could not be reached. Check your connection and try again.'
const STARTED_NOTE = 'This event has started, so it can no longer be withdrawn.'
// The yoga's cover picture (2.1 AC14). A card's picture is decorative - no alt text, hidden
// from assistive technology - so it has no role or name, and is found by its tag.
const YOGA_PICTURE = '/images/events/cat.jpg'
const LOADING_LABEL = 'Loading your registrations…'
const EMPTY_MESSAGE = 'You have not registered for any events yet.'

/** A registration's card, found by its event's name. Upcoming events (18.1) uses the same card. */
function eventCard(page: Page, name: string) {
  return page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
}

function withdrawButton(page: Page, name: string) {
  return eventCard(page, name).getByRole('button', { name: `Withdraw from ${name}` })
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

/** "You withdrew on <today>, HH:MM", allowing for midnight passing while the test runs. */
function withdrewToday(before: string, after: string): RegExp {
  const days = [...new Set([before, after])].map(escapeForRegExp).join('|')
  return new RegExp(`You withdrew on (${days}), \\d{2}:\\d{2}`)
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

// --- AC1: the list, and withdrawing ----------------------------------------------------------
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
  await expect(withdrawButton(page, SUNSET_YOGA)).toBeEnabled()

  const trail = eventCard(page, HERITAGE_TRAIL)
  await expect(trail.getByText('Withdrawn', { exact: true })).toBeVisible()
  await expect(trail.getByText('Withdrawn', { exact: true })).toHaveClass(/\bbadge-withdrawn\b/)
  await expect(trail).toContainText('Sat, 3 Apr 2027 · 09:00–12:00')
  await expect(trail).toContainText('You withdrew on Thu, 8 Oct 2026, 20:45')
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

test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test('18.2 AC1: withdrawing after confirming marks the registration Withdrawn, and Upcoming events has the place back', async ({
    page,
  }) => {
    await openMyRegistrations(page)
    const card = eventCard(page, POETRY_NIGHT)
    await expect(card.getByText('Registered', { exact: true })).toBeVisible()

    await withdrawButton(page, POETRY_NIGHT).click()
    const dialog = withdrawDialog(page, POETRY_NIGHT)
    await expect(dialog).toContainText('you may not be able to register again')
    const before = todayInSingapore()
    await dialog.getByRole('button', { name: 'Withdraw', exact: true }).click()
    const after = todayInSingapore()

    await expect(dialog).toHaveCount(0)
    await expect(
      page.getByRole('status').filter({ hasText: `You have withdrawn from ${POETRY_NIGHT}.` }),
    ).toContainText('Withdrawn')
    await expect(card.getByText('Withdrawn', { exact: true })).toBeVisible()
    await expect(card).toContainText(withdrewToday(before, after))
    await expect(card.getByRole('button')).toHaveCount(0)

    await page.reload()
    await expect(card.getByText('Withdrawn', { exact: true })).toBeVisible()

    await page.goto(UPCOMING_EVENTS_PATH)
    const upcoming = eventCard(page, POETRY_NIGHT)
    await expect(upcoming).toContainText('1 place left')
    await expect(upcoming.getByText('Open', { exact: true })).toBeVisible()
  })
})

test('18.2 AC1: cancelling the confirmation keeps the registration and sends nothing', async ({
  page,
}) => {
  await openMyRegistrations(page)
  const sent = trackWithdrawals(page)

  await withdrawButton(page, SUNSET_YOGA).click()
  await withdrawDialog(page, SUNSET_YOGA).getByRole('button', { name: 'Cancel' }).click()
  await expect(withdrawDialog(page, SUNSET_YOGA)).toHaveCount(0)
  await withdrawButton(page, SUNSET_YOGA).click()
  await page.keyboard.press('Escape')
  await expect(withdrawDialog(page, SUNSET_YOGA)).toHaveCount(0)

  await expect(eventCard(page, SUNSET_YOGA).getByText('Registered', { exact: true })).toBeVisible()
  await expect(withdrawButton(page, SUNSET_YOGA)).toBeEnabled()
  expect(sent).toHaveLength(0)
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

test('18.2 AC1: at phone width the registrations fit without sideways scrolling, and Withdraw is big enough for a thumb', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openMyRegistrations(page)

  const withdraw = withdrawButton(page, SUNSET_YOGA)
  await expect(withdraw).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const button = await withdraw.boundingBox()
  if (button === null) throw new Error('the card is not laid out')
  expect(button.height).toBeGreaterThanOrEqual(44)

  // The picture stays beside the details, as on a card with no button; Withdraw goes below both.
  const picture = await eventCard(page, SUNSET_YOGA).locator('img').boundingBox()
  const title = await eventCard(page, SUNSET_YOGA).getByRole('heading', { level: 3 }).boundingBox()
  if (picture === null || title === null) throw new Error('the card is not laid out')
  expect(title.x).toBeGreaterThanOrEqual(picture.x + picture.width)
  expect(title.y).toBeLessThan(picture.y + picture.height)
  expect(button.y).toBeGreaterThanOrEqual(picture.y + picture.height)
})

// --- AC3: until the event starts -------------------------------------------------------------
test('18.2 AC3: a registration for an event that has started offers no Withdraw', async ({
  page,
}) => {
  await openMyRegistrations(page)

  const card = eventCard(page, BOOK_SWAP)
  await expect(card.getByText('Registered', { exact: true })).toBeVisible()
  await expect(card).toContainText('Sat, 3 Oct 2026 · 10:00–13:00')
  await expect(card).toContainText(STARTED_NOTE)
  await expect(card.getByRole('button')).toHaveCount(0)
})

test('18.2 AC3: a withdrawal refused because the event started meanwhile says why, and the card then offers no Withdraw', async ({
  page,
}) => {
  // The yoga "starts" as Withdraw is confirmed: the withdrawal is refused, and from then on the
  // list says what the server would - it can no longer be withdrawn. Nothing is written.
  let hasStarted = false
  await page.route(
    (url) => url.pathname === MINE_API_PATH || WITHDRAW_API_PATH.test(url.pathname),
    async (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      if (request.method() === 'POST' && WITHDRAW_API_PATH.test(new URL(request.url()).pathname)) {
        hasStarted = true
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ detail: EVENT_STARTED_MESSAGE }),
        })
      }
      if (request.method() !== 'GET' || !hasStarted) return route.fallback()
      const response = await route.fetch()
      const registrations = (await response.json()) as { event_name: string }[]
      return route.fulfill({
        response,
        json: registrations.map((registration) =>
          registration.event_name === SUNSET_YOGA
            ? { ...registration, can_withdraw: false }
            : registration,
        ),
      })
    },
  )
  await openMyRegistrations(page)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(EVENT_STARTED_MESSAGE)
  await expect(page.getByRole('status').filter({ hasText: EVENT_STARTED_MESSAGE })).toContainText(
    'Cannot withdraw',
  )
  // Refused for good, so Withdraw is no longer offered: only Close.
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(eventCard(page, SUNSET_YOGA).getByText('Registered', { exact: true })).toBeVisible()
  await expect(eventCard(page, SUNSET_YOGA)).toContainText(STARTED_NOTE)
  await expect(withdrawButton(page, SUNSET_YOGA)).toHaveCount(0)
})

test('18.2 AC1: a withdrawal that cannot reach the server says so, and can be tried again', async ({
  page,
}) => {
  await page.route(
    (url) => WITHDRAW_API_PATH.test(url.pathname),
    (route) =>
      route.request().resourceType() === 'fetch'
        ? route.abort('connectionrefused')
        : route.fallback(),
  )
  await openMyRegistrations(page)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(UNREACHABLE_MESSAGE)
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toBeEnabled()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible()
})

// --- AC4: registering again ------------------------------------------------------------------
test.describe('withdraws its seeded registration once', () => {
  test.describe.configure({ retries: 0 })

  test('18.2 AC4: after withdrawing, registering again from Upcoming events makes the registration active again', async ({
    page,
  }) => {
    await openMyRegistrations(page)
    await confirmWithdrawal(page, SKETCHING_WALK)
    await expect(
      eventCard(page, SKETCHING_WALK).getByText('Withdrawn', { exact: true }),
    ).toBeVisible()

    await page.goto(UPCOMING_EVENTS_PATH)
    await eventCard(page, SKETCHING_WALK)
      .getByRole('button', { name: `Register for ${SKETCHING_WALK}` })
      .click()
    await expect(
      eventCard(page, SKETCHING_WALK).getByText('Registered', { exact: true }),
    ).toBeVisible()

    await page.goto(MY_REGISTRATIONS_PATH)
    await expect(eventCard(page, SKETCHING_WALK)).toHaveCount(1)
    await expect(
      eventCard(page, SKETCHING_WALK).getByText('Registered', { exact: true }),
    ).toBeVisible()
    await expect(withdrawButton(page, SKETCHING_WALK)).toBeEnabled()
  })
})

// --- AC5: only the attendee's own ------------------------------------------------------------
test("18.2 AC5: an attendee does not see another attendee's registrations", async ({ page }) => {
  await openMyRegistrations(page)

  await expect(eventCard(page, SUNSET_YOGA)).toBeVisible()
  await expect(eventCard(page, PORTFOLIO_REVIEW)).toHaveCount(0)
})

test('18.2 AC6: a withdrawal of a registration that is no longer found says so', async ({
  page,
}) => {
  // The page only offers the attendee's own registrations, so a 404 means it went meanwhile.
  await stubCall(page, 'POST', (pathname) => WITHDRAW_API_PATH.test(pathname), {
    status: 404,
    body: { detail: NOT_FOUND_MESSAGE },
  })
  await openMyRegistrations(page)

  await confirmWithdrawal(page, SUNSET_YOGA)

  const dialog = withdrawDialog(page, SUNSET_YOGA)
  await expect(dialog.getByRole('alert')).toHaveText(NOT_FOUND_MESSAGE)
  await expect(dialog.getByRole('button', { name: 'Withdraw', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: NOT_FOUND_MESSAGE })).toContainText(
    'Cannot withdraw',
  )
})

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
    await openMyRegistrations(page)
    const sent = trackWithdrawals(page)

    await withdrawButton(page, BOARD_GAMES_SOCIAL).click()
    await withdrawDialog(page, BOARD_GAMES_SOCIAL)
      .getByRole('button', { name: 'Withdraw', exact: true })
      .dblclick()

    await expect(
      eventCard(page, BOARD_GAMES_SOCIAL).getByText('Withdrawn', { exact: true }),
    ).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(sent).toHaveLength(1)
  })
})

// --- AC8: a cancelled event ------------------------------------------------------------------
test('18.2 AC8: a registration for a cancelled event shows Event cancelled, with no Withdraw', async ({
  page,
}) => {
  await openMyRegistrations(page)

  const card = eventCard(page, CHARITY_FUN_RUN)
  await expect(card.getByText('Event cancelled', { exact: true })).toBeVisible()
  await expect(card.getByText('Event cancelled', { exact: true })).toHaveClass(
    /\bbadge-cancelled\b/,
  )
  await expect(card).toContainText('Sat, 10 Apr 2027 · 07:00–10:00')
  await expect(card.getByRole('button')).toHaveCount(0)
})
