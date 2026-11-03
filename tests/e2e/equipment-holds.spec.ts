/**
 * Story 17.3 - fe/be: view the equipment holds schedule as Technical Support.
 * AC1 the Equipment holds page groups every current hold by equipment type; under each type, each
 *     hold shows its event, quantity, from and to, and whether it is not yet sent, Pending or
 *     Accepted. Every type's grouping and the soonest-first order are backend cases.
 * AC2 a hold on an item not yet sent is listed (the seeded presentation laptops).
 * AC3 filtered by type and by either end of a date range, just the filters set kept in the page
 *     address; a range starting before today, an end before the start or before today, a
 *     five-digit year, a date left half typed and an address date no picker can hold (a time, or a
 *     day its month does not have) are refused on the page before anything is sent. A type in the
 *     address the server refuses stays in the type box. Changed filters hide the old holds while
 *     they load, and a refusal with no sentence of its own (stubbed) names the filters. The range's
 *     own edges, Singapore days and the server's refusals are backend cases.
 * AC4 a sent hold opens its equipment request page, whose back link returns to the schedule as it
 *     was filtered, or unfiltered; a hold not yet sent has no page to open, and the schedule offers
 *     no Accept or Decline. The request page opened by its address leads back to the queue, and
 *     opened from the queue it still does: proved by equipment-queue.spec.ts's "15.2 AC1: View
 *     details opens the request…".
 * AC5 is a backend case: e2e cannot make time pass, and which items hold nothing is the server's
 *     to decide. Here the seeded declined camera is not listed.
 * AC6 a type with no holds says so: in a range, from the seeded data; with no range, or either end
 *     of one, from a stubbed answer, since some seeded hold of every type is still to come.
 * AC7 another role is told the page is not permitted; the API's 401 and 403 are backend cases.
 * A failed load says why (stubbed 500), and on a phone the page does not scroll sideways.
 *
 * Every flow reads the seeded Bayfront Product Showcase (backend/db/seed/020_sample_data.sql) on
 * 9 April 2031, which no other spec changes: three wireless microphones accepted, a speaker set
 * pending, two presentation laptops not yet sent, and a video camera declined. Other specs hold
 * equipment as this one runs, so rows are found by event name, never by how many a type has.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  corsHeaders,
  expectNoSidewaysScroll,
  mainOverflow,
  MIN_TOUCH_TARGET,
  signIn,
} from './support'

const HOLDS_PATH = '/equipment/holds'
const HOLDS_API_PATH = '/equipment-holds'
const SHOWCASE = 'Bayfront Product Showcase'
const SHOWCASE_DAY = '2031-04-09'
const SHOWCASE_FROM = 'Wed, 9 Apr 2031, 09:00'
const SHOWCASE_TO = 'Wed, 9 Apr 2031, 17:00'
// A range ending the day before leaves the showcase out.
const BEFORE_SHOWCASE_DAY = '2031-04-08'
// The seeded roadshow's microphones, accepted, in June 2027: outside the showcase's day.
const ROADSHOW = 'Regional Partner Roadshow'

const START_BEFORE_TODAY = 'The start date cannot be before today.'
const END_BEFORE_START = 'The end date cannot be before the start date.'
const END_BEFORE_TODAY = 'The end date cannot be before today.'
const DATE_INVALID = 'Enter a valid date, with a four-digit year.'
const DATE_INCOMPLETE = 'Finish entering the date'

/** Singapore's clock, which the page's dates read (frontend/src/shared/format.ts). */
const SINGAPORE_OFFSET_MS = 8 * 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000

/** A date `days` from today in Singapore, as a date picker's value. */
function singaporeDay(days: number): string {
  return new Date(Date.now() + SINGAPORE_OFFSET_MS + days * DAY_MS).toISOString().slice(0, 10)
}

function group(page: Page, typeName: string) {
  return page.getByRole('main').getByRole('region', { name: typeName, exact: true })
}

function showcaseRow(page: Page, typeName: string) {
  return group(page, typeName).getByRole('row').filter({ hasText: SHOWCASE })
}

function roadshowMics(page: Page) {
  return group(page, 'Wireless microphone').getByRole('row').filter({ hasText: ROADSHOW })
}

function filters(page: Page) {
  return page.getByRole('form', { name: 'Filter holds' })
}

async function openHolds(page: Page, query = '') {
  await page.goto(`${HOLDS_PATH}${query}`)
  await expect(page.getByRole('heading', { name: 'Equipment holds', level: 1 })).toBeVisible()
  await expect(page.getByRole('main').getByRole('region').first()).toBeVisible()
}

/** Show holds, and wait for the schedule it loads. The page hides the holds it showed before it
 *  asks, so what is checked next is the new schedule. */
async function showHolds(page: Page) {
  const loaded = page.waitForResponse(
    (response) => new URL(response.url()).pathname === HOLDS_API_PATH,
  )
  await filters(page).getByRole('button', { name: 'Show holds' }).click()
  await loaded
}

/** Every load of the schedule the page asks for from now on. */
function trackLoads(page: Page): string[] {
  const loads: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === HOLDS_API_PATH) loads.push(request.url())
  })
  return loads
}

/** Answer the schedule's load with `status` and `body` instead of the server. */
async function stubSchedule(page: Page, status: number, body: unknown) {
  await page.route(
    (url) => url.pathname === HOLDS_API_PATH,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers: corsHeaders(request),
      })
    },
  )
}

test('17.3 AC1/AC2: Technical Support opens the schedule and sees the showcase held under each type', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Equipment holds', exact: true })
    .click()

  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}$`))
  await expect(page.getByRole('heading', { name: 'Equipment holds', level: 1 })).toBeVisible()

  await expect(
    group(page, 'Wireless microphone').getByRole('table', {
      name: 'Wireless microphone holds',
    }),
  ).toBeVisible()
  // Cell by cell - event, quantity, from, to, status, link - so each is read from its own column.
  await expect(showcaseRow(page, 'Wireless microphone').getByRole('cell')).toHaveText([
    SHOWCASE,
    '3',
    SHOWCASE_FROM,
    SHOWCASE_TO,
    'Accepted (reserved)',
    'View request →',
  ])
  await expect(showcaseRow(page, 'Portable speaker set').getByRole('cell')).toHaveText([
    SHOWCASE,
    '1',
    SHOWCASE_FROM,
    SHOWCASE_TO,
    'Pending',
    'View request →',
  ])
  await expect(showcaseRow(page, 'Presentation laptop').getByRole('cell')).toHaveText([
    SHOWCASE,
    '2',
    SHOWCASE_FROM,
    SHOWCASE_TO,
    'Not yet sent',
    '',
  ])
  // AC5: Technical Support declined the camera, so it holds nothing.
  await expect(group(page, 'Video camera')).toBeVisible()
  await expect(showcaseRow(page, 'Video camera')).toHaveCount(0)
})

test('17.3 AC3: filtering by type and by either end of a range keeps just those filters in the address, and Clear filters shows every hold again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)
  const form = filters(page)
  await expect(roadshowMics(page)).toHaveCount(1)
  // The end's picker starts from today, and from the start once one is chosen.
  await expect(form.getByLabel('To date')).toHaveAttribute('min', singaporeDay(0))

  await form.getByLabel('Equipment type').selectOption({ label: 'Wireless microphone' })
  await showHolds(page)
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}\\?type=WIRELESS_MIC$`))
  await expect(roadshowMics(page)).toHaveCount(1)
  await expect(showcaseRow(page, 'Wireless microphone')).toBeVisible()
  await expect(group(page, 'Presentation laptop')).toHaveCount(0)

  await form.getByLabel('To date').fill(BEFORE_SHOWCASE_DAY)
  await showHolds(page)
  await expect(page).toHaveURL(new RegExp(`\\?type=WIRELESS_MIC&to=${BEFORE_SHOWCASE_DAY}$`))
  await expect(roadshowMics(page)).toHaveCount(1)
  await expect(showcaseRow(page, 'Wireless microphone')).toHaveCount(0)

  await form.getByLabel('To date').fill('')
  await form.getByLabel('From date').fill(SHOWCASE_DAY)
  await expect(form.getByLabel('To date')).toHaveAttribute('min', SHOWCASE_DAY)
  await showHolds(page)
  await expect(page).toHaveURL(new RegExp(`\\?type=WIRELESS_MIC&from=${SHOWCASE_DAY}$`))
  await expect(showcaseRow(page, 'Wireless microphone')).toContainText('Accepted (reserved)')
  await expect(roadshowMics(page)).toHaveCount(0)

  await form.getByLabel('To date').fill(SHOWCASE_DAY)
  await showHolds(page)
  await expect(page).toHaveURL(
    new RegExp(`\\?type=WIRELESS_MIC&from=${SHOWCASE_DAY}&to=${SHOWCASE_DAY}$`),
  )
  await expect(showcaseRow(page, 'Wireless microphone')).toBeVisible()
  await expect(roadshowMics(page)).toHaveCount(0)

  await page.reload()
  // The type list offers the types once the schedule has loaded, so wait for it first.
  await expect(showcaseRow(page, 'Wireless microphone')).toBeVisible()
  await expect(group(page, 'Presentation laptop')).toHaveCount(0)
  await expect(form.getByLabel('Equipment type')).toHaveValue('WIRELESS_MIC')
  await expect(form.getByLabel('From date')).toHaveValue(SHOWCASE_DAY)
  await expect(form.getByLabel('To date')).toHaveValue(SHOWCASE_DAY)

  await form.getByRole('button', { name: 'Clear filters' }).click()

  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}$`))
  await expect(form.getByLabel('From date')).toHaveValue('')
  await expect(roadshowMics(page)).toHaveCount(1)
  await expect(showcaseRow(page, 'Presentation laptop')).toBeVisible()
})

test('17.3 AC3: a range reaching before today is refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)
  const loads = trackLoads(page)
  const form = filters(page)
  const show = form.getByRole('button', { name: 'Show holds' })

  // The range is checked when Show holds is pressed, not while it is typed.
  await form.getByLabel('From date').fill(singaporeDay(-1))
  await expect(form.getByRole('alert')).toHaveCount(0)
  // An end on the start is no problem of its own, even when the start is.
  await form.getByLabel('To date').fill(singaporeDay(-1))
  await show.click()
  await expect(form.getByRole('alert')).toHaveText([START_BEFORE_TODAY])
  await expect(form.getByLabel('From date')).toBeFocused()
  await expect(form.getByLabel('From date')).toHaveAttribute('aria-invalid', 'true')
  await expect(form.getByLabel('From date')).toHaveAccessibleDescription(START_BEFORE_TODAY)

  await form.getByLabel('From date').fill(singaporeDay(2))
  await form.getByLabel('To date').fill(singaporeDay(1))
  await show.click()
  await expect(form.getByRole('alert')).toHaveText([END_BEFORE_START])
  await expect(form.getByLabel('To date')).toBeFocused()
  await expect(form.getByLabel('To date')).toHaveAttribute('aria-invalid', 'true')
  await expect(form.getByLabel('To date')).toHaveAccessibleDescription(END_BEFORE_START)

  await form.getByLabel('From date').fill('')
  await form.getByLabel('To date').fill(singaporeDay(-1))
  await show.click()
  await expect(form.getByRole('alert')).toHaveText([END_BEFORE_TODAY])
  await expect(form.getByLabel('To date')).toBeFocused()
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}$`))
  expect(loads).toHaveLength(0)

  // Today itself is a range the page sends, as an end alone and as a start.
  await form.getByLabel('To date').fill(singaporeDay(0))
  await show.click()
  await expect(form.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => loads.length).toBe(1)
  await form.getByLabel('From date').fill(singaporeDay(0))
  await show.click()
  await expect(form.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => loads.length).toBe(2)
})

test('17.3 AC3: a year of five digits, or a date left half typed, in either box is refused before anything is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)
  const loads = trackLoads(page)
  const form = filters(page)
  const show = form.getByRole('button', { name: 'Show holds' })

  await form.getByLabel('From date').fill('20310-04-09')
  await show.click()
  await expect(form.getByRole('alert').filter({ hasText: DATE_INVALID })).toBeVisible()
  await expect(form.getByLabel('From date')).toBeFocused()

  // A date started but not finished reads as blank, which would mean no end to the range.
  await form.getByLabel('From date').fill(SHOWCASE_DAY)
  await form.getByLabel('To date').focus()
  await page.keyboard.type('0409')
  await show.click()
  await expect(form.getByRole('alert').filter({ hasText: DATE_INCOMPLETE })).toBeVisible()
  await expect(form.getByLabel('To date')).toBeFocused()

  await form.getByLabel('To date').fill('20310-04-10')
  await show.click()
  await expect(form.getByRole('alert').filter({ hasText: DATE_INVALID })).toBeVisible()
  await expect(form.getByLabel('To date')).toBeFocused()

  await form.getByLabel('To date').fill('')
  await form.getByLabel('From date').fill('')
  await form.getByLabel('From date').focus()
  await page.keyboard.type('0409')
  await show.click()
  await expect(form.getByRole('alert').filter({ hasText: DATE_INCOMPLETE })).toBeVisible()
  await expect(form.getByLabel('From date')).toBeFocused()
  // Changing the other date leaves the unfinished one still named.
  await form.getByLabel('To date').fill(SHOWCASE_DAY)
  await expect(form.getByRole('alert').filter({ hasText: DATE_INCOMPLETE })).toBeVisible()
  expect(loads).toHaveLength(0)
})

test('17.3 AC3: a date in the address that no picker can hold is named when Show holds is pressed', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  const form = filters(page)

  // A date with a time, and a day the month does not have.
  for (const from of [`${SHOWCASE_DAY}T09:00`, '2032-02-30']) {
    await page.goto(`${HOLDS_PATH}?from=${from}`)
    await form.getByRole('button', { name: 'Show holds' }).click()

    await expect(form.getByRole('alert').filter({ hasText: DATE_INVALID })).toBeVisible()
    await expect(form.getByLabel('From date')).toBeFocused()
  }
})

test('17.3 AC3: a type in the address the server refuses stays in the type box, so what it shows is what is sent', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(`${HOLDS_PATH}?type=NO_SUCH_KIT`)
  const type = filters(page).getByLabel('Equipment type')

  await expect(page.getByRole('alert')).toHaveText('Unknown equipment type: NO_SUCH_KIT.')
  await expect(type).toHaveValue('NO_SUCH_KIT')

  await type.selectOption({ label: 'All types' })
  await showHolds(page)
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}$`))
  await expect(roadshowMics(page)).toHaveCount(1)
})

test('17.3 AC4: a sent hold opens its request, which leads back to the schedule as filtered; one not yet sent has no page', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)
  await showcaseRow(page, 'Wireless microphone').getByRole('link', { name: 'View request' }).click()
  await expect(page.getByRole('heading', { name: 'Wireless microphone', level: 2 })).toBeVisible()
  const requestUrl = page.url()
  await page.getByRole('link', { name: '← Equipment holds' }).click()
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}$`))
  // Opened by its address, the request page leads back to the queue, as before 17.3 (13.3 AC7).
  await page.goto(requestUrl)
  await expect(page.getByRole('link', { name: '← Equipment Requests' })).toHaveAttribute(
    'href',
    '/equipment/requests',
  )

  const filtered = `?from=${SHOWCASE_DAY}&to=${SHOWCASE_DAY}`
  await openHolds(page, filtered)

  await expect(page.getByRole('button', { name: /^(Accept|Decline)$/ })).toHaveCount(0)
  await expect(showcaseRow(page, 'Presentation laptop')).toContainText('Not yet sent')
  await expect(showcaseRow(page, 'Presentation laptop').getByRole('link')).toHaveCount(0)

  await showcaseRow(page, 'Wireless microphone').getByRole('link', { name: 'View request' }).click()
  await expect(page).toHaveURL(/\/equipment\/requests\/[^/]+$/)
  await expect(page.getByRole('heading', { name: SHOWCASE, level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Wireless microphone', level: 2 })).toBeVisible()
  await expect(page.getByText('Accepted', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: '← Equipment holds' }).click()
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}\\${filtered}$`))
  await expect(filters(page).getByLabel('From date')).toHaveValue(SHOWCASE_DAY)

  await showcaseRow(page, 'Portable speaker set')
    .getByRole('link', { name: 'View request' })
    .click()
  await expect(page.getByRole('heading', { name: 'Portable speaker set', level: 2 })).toBeVisible()
  await page.getByRole('link', { name: '← Equipment holds' }).click()
  await expect(page).toHaveURL(new RegExp(`${HOLDS_PATH}\\${filtered}$`))
})

test('17.3 AC6: in a range, a type with no holds says so', async ({ page }) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page, `?from=${SHOWCASE_DAY}&to=${SHOWCASE_DAY}`)

  await expect(group(page, 'Video camera')).toContainText('No holds in this range.')
  await expect(showcaseRow(page, 'Wireless microphone')).toBeVisible()
})

test('17.3 AC6: with no range, a type with no holds still to come says so; with either end of a range set, it names the range', async ({
  page,
}) => {
  const kind = { code: 'CONF_PHONE', name: 'Conference phone' }
  await stubSchedule(page, 200, {
    types: [kind],
    groups: [
      {
        equipment_type_code: kind.code,
        equipment_type_name: kind.name,
        holds: [],
      },
    ],
  })
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)

  await expect(group(page, 'Conference phone')).toContainText('No current holds.')

  await openHolds(page, `?from=${SHOWCASE_DAY}`)
  await expect(group(page, 'Conference phone')).toContainText('No holds in this range.')
  await openHolds(page, `?to=${SHOWCASE_DAY}`)
  await expect(group(page, 'Conference phone')).toContainText('No holds in this range.')
})

test('17.3: a schedule that fails to load says why and shows no types', async ({ page }) => {
  await stubSchedule(page, 500, {
    detail: 'The server hit a problem. Try again in a moment.',
  })
  await signIn(page, ACCOUNTS.techSupport)
  await page.goto(HOLDS_PATH)

  await expect(page.getByRole('alert')).toHaveText(
    'The server hit a problem. Try again in a moment.',
  )
  await expect(page.getByRole('main').getByRole('region')).toHaveCount(0)
  await expect(filters(page).getByLabel('Equipment type').getByRole('option')).toHaveText([
    'All types',
  ])
})

test('17.3 AC3: changed filters hide the holds shown before while they load, and a refusal that gives no reason names the filters', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page)
  const loading = page.getByRole('main').getByRole('status')
  await expect(roadshowMics(page)).toHaveCount(1)
  await expect(loading).toHaveCount(0)

  // The next load waits until the test lets it answer, then is refused with no sentence of its own.
  let answer = () => {}
  const answered = new Promise<void>((resolve) => {
    answer = resolve
  })
  await page.route(
    (url) => url.pathname === HOLDS_API_PATH,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      await answered
      return route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: '{}',
        headers: corsHeaders(request),
      })
    },
  )
  await filters(page).getByLabel('Equipment type').selectOption({ label: 'Wireless microphone' })
  await filters(page).getByRole('button', { name: 'Show holds' }).click()

  await expect(loading).toHaveText('Loading equipment holds…')
  await expect(page.getByRole('main').getByRole('region')).toHaveCount(0)

  answer()
  await expect(page.getByRole('alert')).toHaveText('These filters cannot be shown.')
  await expect(loading).toHaveCount(0)
  await expect(page.getByRole('main').getByRole('region')).toHaveCount(0)
})

test('17.3 AC7: another role is refused the schedule page', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(HOLDS_PATH)

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Equipment holds' })).toHaveCount(0)
})

test('17.3: on a phone the schedule does not scroll sideways, and its filters are thumb-sized', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, ACCOUNTS.techSupport)
  await openHolds(page, `?from=${SHOWCASE_DAY}&to=${SHOWCASE_DAY}`)
  await expect(showcaseRow(page, 'Wireless microphone')).toBeVisible()

  expect(await mainOverflow(page)).toBeLessThanOrEqual(0)
  await expectNoSidewaysScroll(page)
  const show = await filters(page).getByRole('button', { name: 'Show holds' }).boundingBox()
  expect(show?.height ?? 0).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
})
