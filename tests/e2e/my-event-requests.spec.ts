/**
 * Story 2.6 - fe/be: list my event requests.
 * AC1 the list shows every request the signed-in organiser owns, with name, proposed date and
 *     current status.
 * AC2 selecting an entry - its title or anywhere else on the card - opens its full details: a
 *     draft opens in the story 2.1 editor, and every other status on story 7.1's read-only event
 *     details page. Selecting text on a card, or using something inside it, must not open it.
 * AC3 the list contains no requests belonging to other organisers.
 * AC4 a draft with no proposed date says so.
 * AC5 with no requests the page says so and offers a way to raise one.
 * AC7 only an organiser can open the list.
 * AC8 the list offers a "New event request" action.
 * AC9 a long list loads a page at a time: it says how much is left, "Load more" adds the next
 *     page, a page that fails keeps what is shown, and nothing appears twice.
 * Ordering, the empty list as the API returns it, every status, the 401/403 refusals and
 * other-organiser leaks (the same organisation, a query parameter) are backend cases:
 * backend/tests/events/test_my_event_requests.py.
 *
 * No seeded organiser has zero requests or a hundred, and a loading or failing list cannot be had
 * from real data, so those states are reached by stubbing the list call with `page.route` (the
 * only specs that do; see stubMyEventsCall). Everything else here runs on real seed data. One spec
 * (a button inside a linked card) uses the development-only component gallery at /dev/components,
 * which the e2e runner serves because it starts the Vite dev server.
 *
 * Specs share one database and run in parallel, and other specs raise requests as these same
 * organisers, so the list is asserted by request name, never by how many there are.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

const MY_EVENTS_PATH = '/events/mine'
const EDIT_PATH = /\/events\/[0-9a-f-]{36}\/edit$/
/** Story 7.1's event details page: the event's id and nothing after it. */
const DETAILS_PATH = /\/events\/[0-9a-f-]{36}$/

const OLIVIA_REQUESTS = [
  'Q1 Sales Kick-off (draft)',
  'Data Literacy Workshop',
  'Diversity & Inclusion Forum',
  'Wellness Week Kickoff',
  'Regional Sales Summit',
  'New Year Town Hall',
]
const OMAR_REQUESTS = [
  'Nimbus Developer Conference',
  'Rooftop Networking Night',
  'Nimbus Leadership Offsite',
  'Partner Appreciation Dinner',
  'Summer Rooftop Mixer',
]

function uniqueName(label: string): string {
  return `E2E ${label} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

/** A `datetime-local` value (Singapore time) `days` from today, safely in the future. */
function inFuture(days: number, hour = 9): string {
  const day = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
  const date = day.toISOString().slice(0, 10)
  return `${date}T${String(hour).padStart(2, '0')}:00`
}

/** The "← My events" / "← Home" link above the title of the request page. */
function backLink(page: Page) {
  return page.getByRole('main').getByRole('link', { name: /^← / })
}

function requestCard(page: Page, name: string) {
  return page.getByRole('main').getByRole('listitem').filter({ hasText: name })
}

/**
 * Reach the list the way a person does, through the sidebar menu. The main page has a tile of the
 * same name, so the link is looked up inside the navigation, not taken as the first match.
 */
async function openMyEventsFromMenu(page: Page) {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'My events', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'My events' })).toBeVisible()
}

async function openMyEvents(page: Page) {
  await page.goto(MY_EVENTS_PATH)
  await expect(page.getByRole('heading', { name: 'My events' })).toBeVisible()
}

test('2.6 AC1: an organiser sees their requests with name, proposed date and status', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEventsFromMenu(page)

  const underReview = requestCard(page, 'Data Literacy Workshop')
  await expect(underReview).toContainText('Proposed date:')
  await expect(underReview).toContainText('18 Nov 2026 · 09:00–17:00')
  await expect(underReview).toContainText('Under review')

  await expect(requestCard(page, 'Diversity & Inclusion Forum')).toContainText(
    'Clarification requested',
  )
  await expect(requestCard(page, 'Q1 Sales Kick-off (draft)')).toContainText('Draft')
  for (const name of OLIVIA_REQUESTS) await expect(requestCard(page, name)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0)
})

test('6.1: a status tab shows only requests in that status', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  // Specs share one database and run in parallel, so tab counts are not asserted - only which
  // named requests appear under which tab.
  await expect(page.getByRole('tab', { name: 'All', exact: false })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(requestCard(page, 'Data Literacy Workshop')).toBeVisible()

  await page.getByRole('tab', { name: /^Draft/ }).click()
  await expect(requestCard(page, 'Q1 Sales Kick-off (draft)')).toBeVisible()
  await expect(requestCard(page, 'Data Literacy Workshop')).toHaveCount(0)

  await page.getByRole('tab', { name: /^Under Review/ }).click()
  await expect(requestCard(page, 'Data Literacy Workshop')).toContainText('Under review')
  await expect(requestCard(page, 'Wellness Week Kickoff')).toContainText('Under review')

  await page.getByRole('tab', { name: /^Clarification Requested/ }).click()
  await expect(requestCard(page, 'Diversity & Inclusion Forum')).toBeVisible()

  await page.getByRole('tab', { name: /^Planning/ }).click()
  await expect(requestCard(page, 'Regional Sales Summit')).toBeVisible()

  await page.getByRole('tab', { name: /^Completed/ }).click()
  await expect(requestCard(page, 'New Year Town Hall')).toBeVisible()
})

test('2.6 AC1: a request raised just now is in the list as a draft', async ({ page }) => {
  const name = uniqueName('Listed')
  await signIn(page, ACCOUNTS.organiser)
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  await openMyEvents(page)

  await expect(requestCard(page, name)).toContainText('Draft')
})

test('2.6 AC4: a draft with no proposed date says so', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  await expect(requestCard(page, 'Q1 Sales Kick-off (draft)')).toContainText('Not set')
})

test('2.6 AC4: a draft with a start but no end says the end is not set', async ({ page }) => {
  const name = uniqueName('Start only')
  await signIn(page, ACCOUNTS.organiser)
  await page.goto('/events/new')
  await page.getByLabel('Event name').fill(name)
  await page.getByLabel('Proposed start').fill(inFuture(30, 9))
  await page.getByRole('button', { name: 'Save draft' }).click()
  await expect(page).toHaveURL(EDIT_PATH)

  await openMyEvents(page)

  const card = requestCard(page, name)
  await expect(card).toContainText('Proposed date:')
  await expect(card).toContainText('end not set')
})

test('2.6 AC2: a request opened from My events goes back to My events, even after a reload', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)
  await requestCard(page, 'Data Literacy Workshop').click({ position: { x: 8, y: 8 } })
  await expect(page).toHaveURL(DETAILS_PATH)
  await expect(backLink(page)).toHaveText('← My events')

  await page.reload()

  await expect(backLink(page)).toHaveText('← My events')
})

test('2.6 AC2: a request opened by its address goes back to the home page', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)
  await requestCard(page, 'Data Literacy Workshop').click({ position: { x: 8, y: 8 } })
  await expect(page).toHaveURL(DETAILS_PATH)

  // A new tab in the same signed-in session: going to the page's own URL would count as a reload,
  // which keeps the history state, so it would not be opening the address afresh.
  const freshTab = await page.context().newPage()
  await freshTab.goto(page.url())

  await expect(backLink(freshTab)).toHaveText('← Home')
})

test('2.6 AC8: the form opened from My events goes back to My events, before and after saving', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)
  await page.getByRole('main').getByRole('link', { name: 'New event request' }).click()
  await expect(page).toHaveURL(/\/events\/new$/)
  await expect(backLink(page)).toHaveText('← My events')

  await page.getByLabel('Event name').fill(uniqueName('Back to list'))
  await page.getByRole('button', { name: 'Save draft' }).click()

  await expect(page).toHaveURL(EDIT_PATH)
  await expect(backLink(page)).toHaveText('← My events')
})

test('2.6 AC2: selecting a submitted request opens its details, read-only, and back returns', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  await requestCard(page, 'Data Literacy Workshop')
    .getByRole('link', { name: 'Data Literacy Workshop' })
    .click()

  await expect(page).toHaveURL(DETAILS_PATH)
  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save draft' })).toHaveCount(0)

  await page
    .getByRole('main')
    .getByRole('link', { name: /My events/ })
    .click()
  await expect(page.getByRole('heading', { name: 'My events' })).toBeVisible()
})

test('2.6 AC2: clicking anywhere on the card opens the request, not just its title', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  // The top-left corner of the card: its padding, well clear of the title link.
  await requestCard(page, 'Data Literacy Workshop').click({ position: { x: 8, y: 8 } })

  await expect(page).toHaveURL(DETAILS_PATH)
  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
})

test('2.6 AC2: a request that is not a draft opens the event details page, whatever its status', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)

  for (const [name, status] of [
    ['Nimbus Developer Conference', 'Planning'],
    ['Rooftop Networking Night', 'Rejected'],
    ['Nimbus Leadership Offsite', 'Under review'],
  ] as const) {
    await openMyEvents(page)
    await requestCard(page, name).click({ position: { x: 8, y: 8 } })

    await expect(page).toHaveURL(DETAILS_PATH)
    await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
    await expect(page.getByText(status, { exact: true }).first()).toBeVisible()
  }
})

test('2.6 AC2: selecting a draft opens it for editing', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  await requestCard(page, 'Q1 Sales Kick-off (draft)')
    .getByRole('link', { name: 'Q1 Sales Kick-off (draft)' })
    .click()

  await expect(page).toHaveURL(EDIT_PATH)
  await expect(page.getByLabel('Event name')).toHaveValue('Q1 Sales Kick-off (draft)')
  await expect(page.getByLabel('Event name')).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Save draft' })).toBeVisible()
  await expect(backLink(page)).toHaveText('← My events')
})

test('2.6 AC3: an organiser sees none of another organiser’s requests', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)
  await expect(requestCard(page, 'Data Literacy Workshop')).toBeVisible()

  for (const name of OMAR_REQUESTS) await expect(requestCard(page, name)).toHaveCount(0)
})

test('2.6 AC3: the other organiser sees theirs, and none of the first organiser’s', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await openMyEvents(page)

  await expect(requestCard(page, 'Nimbus Developer Conference')).toContainText('Planning')
  await expect(requestCard(page, 'Rooftop Networking Night')).toContainText('Rejected')
  await expect(requestCard(page, 'Nimbus Leadership Offsite')).toContainText('Under review')
  for (const name of OLIVIA_REQUESTS) await expect(requestCard(page, name)).toHaveCount(0)
})

type StubbedResponse = { status: number; body: unknown }

/**
 * Answer the page's calls for the list, once `gate` (if given) resolves. `respond` is given the
 * `offset` the page asked for, so a test can serve a different page each time. `page.route` sees
 * the page's own navigation to /events/mine as well as the API calls that share its path, so only
 * the `fetch` is stubbed; the URL is matched on its path because the calls carry a query string.
 * A stubbed response still needs the CORS headers, as the app and the API are on different ports.
 */
async function stubMyEventsCall(
  page: Page,
  respond: (offset: number) => StubbedResponse,
  gate?: Promise<void>,
) {
  await page.route(
    (url) => url.pathname === MY_EVENTS_PATH,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      await gate
      const offset = Number(new URL(request.url()).searchParams.get('offset') ?? 0)
      const { status, body } = respond(offset)
      return route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers: {
          'access-control-allow-origin': request.headers()['origin'] ?? '*',
          'access-control-allow-credentials': 'true',
        },
      })
    },
  )
}

const NO_REQUESTS: StubbedResponse = { status: 200, body: { items: [], total: 0 } }

/** One row of the API's list, with an id and dates that are fixed, for the stubbed pages. */
function stubbedEntry(number: number, name: string) {
  return {
    id: `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`,
    name,
    starts_at: '2026-12-01T01:00:00Z',
    ends_at: '2026-12-01T09:00:00Z',
    status: 'UNDER_REVIEW',
    cover_image_url: null,
  }
}

test('2.6 AC5: with no requests the page says so and offers a way to raise one', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, () => NO_REQUESTS)

  await openMyEvents(page)

  await expect(page.getByText('You have not raised any event requests yet.')).toBeVisible()
  await expect(page.getByRole('main').getByRole('listitem')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)

  await page.getByRole('link', { name: 'Raise your first request' }).click()
  await expect(page).toHaveURL(/\/events\/new$/)
})

test('2.6 AC1: while the list loads the page says so, then shows what came back', async ({
  page,
}) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, () => NO_REQUESTS, gate)

  await page.goto(MY_EVENTS_PATH)

  await expect(page.getByText('Loading your event requests…')).toBeVisible()
  await expect(page.getByText('You have not raised any event requests yet.')).toHaveCount(0)

  release()

  await expect(page.getByText('Loading your event requests…')).toHaveCount(0)
  await expect(page.getByText('You have not raised any event requests yet.')).toBeVisible()
})

test('2.6 AC1: a list that fails to load shows the error, not an empty list', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, () => ({
    status: 500,
    body: { detail: 'Your requests could not be loaded.' },
  }))

  await page.goto(MY_EVENTS_PATH)

  await expect(page.getByRole('alert')).toContainText('Your requests could not be loaded.')
  await expect(page.getByText('You have not raised any event requests yet.')).toHaveCount(0)
  await expect(page.getByText('Loading your event requests…')).toHaveCount(0)
})

test('2.6 AC2: selecting text on a card does not open it', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)
  const line = requestCard(page, 'Data Literacy Workshop').getByText('Proposed date:')
  const box = await line.boundingBox()
  expect(box).not.toBeNull()

  // Drag across the line of text, as a person does to copy it.
  await page.mouse.move(box!.x + 2, box!.y + box!.height / 2)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width - 2, box!.y + box!.height / 2, { steps: 8 })
  await page.mouse.up()

  expect(await page.evaluate(() => window.getSelection()?.toString() ?? '')).toContain(
    'Proposed date',
  )
  await expect(page).toHaveURL(/\/events\/mine$/)
})

test('2.6 AC2: clicking the title opens the request once, not twice', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  await requestCard(page, 'Data Literacy Workshop')
    .getByRole('link', { name: 'Data Literacy Workshop' })
    .click()
  await expect(page).toHaveURL(DETAILS_PATH)

  // One step back is the list: a click that opened it twice would leave the request open.
  await page.goBack()
  await expect(page).toHaveURL(/\/events\/mine$/)
})

test('2.6 AC2: a button inside a linked card gets its own click and does not open the card', async ({
  page,
}) => {
  await page.goto('/dev/components')
  const card = page
    .getByRole('main')
    .getByRole('listitem')
    .filter({ hasText: 'Linked card with an action' })

  await card.getByRole('button', { name: 'Mark as seen' }).click()

  await expect(card.getByText('Marked as seen')).toBeVisible()
  await expect(page).toHaveURL(/\/dev\/components$/)

  // The card itself still opens: the link goes to the main page, which sends a signed-out
  // visitor on to the sign-in page.
  await card.click({ position: { x: 8, y: 8 } })
  await expect(page).not.toHaveURL(/\/dev\/components$/)
})

test('2.6 AC9: a long list loads a page at a time and says how much is left', async ({ page }) => {
  const asked: number[] = []
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, (offset) => {
    asked.push(offset)
    return {
      status: 200,
      body:
        offset === 0
          ? { items: [stubbedEntry(1, 'Stub one'), stubbedEntry(2, 'Stub two')], total: 3 }
          : { items: [stubbedEntry(3, 'Stub three')], total: 3 },
    }
  })

  await openMyEvents(page)

  await expect(requestCard(page, 'Stub two')).toBeVisible()
  await expect(requestCard(page, 'Stub three')).toHaveCount(0)
  await expect(page.getByText('Showing 2 of 3 requests')).toBeVisible()

  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(requestCard(page, 'Stub three')).toBeVisible()
  await expect(requestCard(page, 'Stub one')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0)
  await expect(page.getByText(/^Showing \d+ of \d+ requests$/)).toHaveCount(0)
  // The dev server's StrictMode loads the first page twice, so only what came after it is exact.
  expect(asked.filter((offset) => offset > 0)).toEqual([2])
})

test('2.6 AC9: a page that fails to load keeps what is shown and can be tried again', async ({
  page,
}) => {
  let isNextPageFailing = true
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, (offset) => {
    if (offset === 0) {
      return {
        status: 200,
        body: { items: [stubbedEntry(1, 'Stub one'), stubbedEntry(2, 'Stub two')], total: 3 },
      }
    }
    if (isNextPageFailing) {
      return { status: 500, body: { detail: 'More requests could not be loaded.' } }
    }
    return { status: 200, body: { items: [stubbedEntry(3, 'Stub three')], total: 3 } }
  })
  await openMyEvents(page)

  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(page.getByRole('alert')).toContainText('More requests could not be loaded.')
  await expect(requestCard(page, 'Stub one')).toBeVisible()
  await expect(requestCard(page, 'Stub two')).toBeVisible()

  isNextPageFailing = false
  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(requestCard(page, 'Stub three')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('2.6 AC9: a request that moved between pages is not shown twice', async ({ page }) => {
  // Editing a request moves it to the front, so a later page can repeat one already shown.
  await signIn(page, ACCOUNTS.organiser)
  await stubMyEventsCall(page, (offset) => ({
    status: 200,
    body:
      offset === 0
        ? { items: [stubbedEntry(1, 'Stub one'), stubbedEntry(2, 'Stub two')], total: 3 }
        : { items: [stubbedEntry(2, 'Stub two'), stubbedEntry(3, 'Stub three')], total: 3 },
  }))
  await openMyEvents(page)

  await page.getByRole('button', { name: 'Load more' }).click()

  await expect(requestCard(page, 'Stub three')).toBeVisible()
  await expect(requestCard(page, 'Stub two')).toHaveCount(1)
})

test('2.6 AC7: a coordinator cannot open the list', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(MY_EVENTS_PATH)

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})

test('2.6 AC8: the list offers a way to raise a new request', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await openMyEvents(page)

  await page.getByRole('main').getByRole('link', { name: 'New event request' }).click()

  await expect(page).toHaveURL(/\/events\/new$/)
  await expect(page.getByRole('heading', { name: 'New event request' })).toBeVisible()
})
