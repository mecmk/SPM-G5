/**
 * Story 5.5 - fe: the Event Coordinator Lead's overview of coordinators' assignments.
 *
 * AC1 the overview lists active events with their coordinator (or "Not yet assigned") and the Lead
 *     who assigned them, and narrows by status tab, by coordinator and to "Assigned by me"; the
 *     filters live in the page address, so they survive a reload and a filter with no match says
 *     so.
 * AC2 the per-coordinator view lists each coordinator with their number of active events and the
 *     events themselves.
 * AC3 an event opens from the overview read-only: no Approve, Reject or Reassign.
 * AC4 a coordinator with no active events shows 0.
 * AC5 after the Lead assigns an event, a reload shows its coordinator; a deactivated coordinator
 *     is flagged.
 * AC6 only the Lead's sidebar offers the page, and a coordinator opening its address is refused.
 * Responsive: both views at a phone (375 x 667), a tablet (768 x 1024) and a desktop (1280 x 800):
 *     no sideways page scroll, cards inside the screen, the tabs and filters inside their own box,
 *     44px touch targets on the phone, and "Not yet assigned" and "Deactivated" shown in full.
 *
 * The rules - which events and coordinators are listed, the counts, the filters' logic, the
 * refusals (401/403/422) and fresh reads after a reassignment - are backend cases:
 * backend/tests/coordination/test_assignment_overview.py.
 *
 * Other specs submit requests too, so lists are asserted by name, never by length. Some states are
 * ones the seed cannot reach, so those tests answer a fetch themselves, as tests/CLAUDE.md allows:
 * an idle and a deactivated coordinator (the workloads fetch), the responsive checks (both
 * fetches, so every flag is on the page), a slow coordinator list, and a failed load.
 */
import { expect, test, type Locator, type Page, type Request } from '@playwright/test'
import {
  ACCOUNTS,
  COORDINATORS,
  EVENTS,
  corsHeaders,
  createAndSubmitRequest,
  signIn,
  uniqueName,
} from './support'

const PAGE_PATH = '/events/assignments'
const OVERVIEW_API = '/coordination/active-events'
const WORKLOADS_API = '/coordination/workloads'
const PAGE_TITLE = 'Assignments'
const OVERVIEW_LABEL = 'Active events'
const COORDINATORS_LABEL = 'Coordinators'
const OVERVIEW_VIEW = 'All active events'
const COORDINATORS_VIEW = 'By coordinator'
const NOT_YET_ASSIGNED = 'Not yet assigned'
const DEACTIVATED = 'Deactivated'
const NO_MATCH_MESSAGE = 'No active events match these filters.'
const LOADING_COORDINATORS = 'Loading coordinators…'
const UNKNOWN_COORDINATOR = 'Unknown coordinator'
const SELECTED_COORDINATOR = 'Selected coordinator'
const LOADING_EVENTS = 'Loading active events…'
const UNLISTED_ID = '00000000-0000-0000-0000-000000000559'
// Chloe's, Planning; only read, here and by the 8.4 spec.
const SMART_CITIES_EXPO = 'Smart Cities Expo'
// Carl's, self-assigned (so not assigned by the Lead), Awaiting Safety Check; only read, here and
// by the 21.1 and 7.2 specs.
const HARBOUR_LIGHTS = 'Harbour Lights Concert'
const [CHLOE, CARL] = COORDINATORS
const PHONE = { width: 375, height: 667 }
const TABLET = { width: 768, height: 1024 }
const DESKTOP = { width: 1280, height: 800 }
const MIN_TOUCH_TARGET = 44

function overviewItem(page: Page, eventName: string) {
  return page
    .getByRole('list', { name: OVERVIEW_LABEL })
    .getByRole('listitem')
    .filter({ has: page.getByRole('link', { name: eventName, exact: true }) })
}

function coordinatorItem(page: Page, coordinatorName: string) {
  return page
    .getByRole('list', { name: COORDINATORS_LABEL })
    .getByRole('listitem')
    .filter({ has: page.getByRole('heading', { name: coordinatorName, exact: true }) })
}

async function openAsLead(page: Page, query = '') {
  await signIn(page, ACCOUNTS.lead)
  await page.goto(`${PAGE_PATH}${query}`)
  await expect(page.getByRole('heading', { name: PAGE_TITLE, level: 1 })).toBeVisible()
}

/** The organiser submits a request now, so it is active and unassigned; returns its name. */
async function submitRequest(page: Page, label: string): Promise<string> {
  const name = uniqueName(label)
  await signIn(page, ACCOUNTS.organiser)
  await createAndSubmitRequest(page, name)
  await page.getByRole('button', { name: 'Sign out' }).click()
  return name
}

/** As the signed-in Lead, assign a queued request from 5.4's unassigned queue. */
async function assignFromQueue(page: Page, name: string, coordinatorId: string) {
  await page.goto('/events/unassigned')
  const queued = page
    .getByRole('list', { name: 'Unassigned events' })
    .getByRole('listitem')
    .filter({ hasText: name })
  await queued.getByRole('button', { name: 'Assign' }).click()
  const dialog = page.getByRole('dialog', { name: `Assign "${name}"?` })
  await dialog.getByLabel('Coordinator').selectOption(coordinatorId)
  await dialog.getByRole('button', { name: 'Assign' }).click()
  await expect(queued).toHaveCount(0)
}

/**
 * Change a filter with `action`, then wait until the overview has been fetched with `sent` in its
 * query and its fresh result is on the page. A filter the page fails to send never gets that
 * response. Only then is it safe to check what the filter removed: while new results load, the
 * page hides the old ones, so "not listed" would be true of anything during that gap.
 */
async function refilter(page: Page, action: () => Promise<unknown>, sent: string) {
  await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === OVERVIEW_API && response.url().includes(sent),
    ),
    action(),
  ])
  await expect(
    page.getByRole('list', { name: OVERVIEW_LABEL }).or(page.getByText(NO_MATCH_MESSAGE)),
  ).toBeVisible()
}

/** Serve one API path with a fixed JSON body, for states the seed cannot reach. */
async function stubFetch(page: Page, path: string, body: unknown) {
  await page.route(
    (url) => url.pathname === path,
    (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers: corsHeaders(request),
      })
    },
  )
}

/** Fail one API path's fetches with a 500, or only those whose query includes `when`. */
async function failFetch(page: Page, path: string, when = '') {
  await page.route(
    (url) => url.pathname === path && url.search.includes(when),
    (route) => {
      const request: Request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal Server Error' }),
        headers: corsHeaders(request),
      })
    },
  )
}

const IDLE_ID = '00000000-0000-0000-0000-000000000551'
const GONE_ID = '00000000-0000-0000-0000-000000000552'
const STRANDED_EVENT = {
  id: '00000000-0000-0000-0000-000000000553',
  name: 'Stranded Lantern Parade With A Rather Long Name For Narrow Screens',
  starts_at: '2027-07-01T01:00:00Z',
  ends_at: '2027-07-01T09:00:00Z',
  status: 'PLANNING',
}
const WAITING_EVENT = {
  id: '00000000-0000-0000-0000-000000000554',
  name: 'Waiting Harbour Showcase',
  starts_at: '2027-07-02T01:00:00Z',
  ends_at: '2027-07-02T09:00:00Z',
  status: 'UNDER_REVIEW',
}
const STUB_WORKLOADS = [
  {
    coordinator_id: IDLE_ID,
    coordinator_name: 'Idle Coordinator',
    is_active: true,
    active_event_count: 0,
    events: [],
  },
  {
    coordinator_id: GONE_ID,
    coordinator_name: 'Departed Coordinator',
    is_active: false,
    active_event_count: 1,
    events: [STRANDED_EVENT],
  },
]
const STUB_OVERVIEW = [
  {
    ...STRANDED_EVENT,
    coordinator_id: GONE_ID,
    coordinator_name: 'Departed Coordinator',
    coordinator_is_active: false,
    assigned_by_name: 'Lena Lead',
  },
  {
    ...WAITING_EVENT,
    coordinator_id: null,
    coordinator_name: null,
    coordinator_is_active: null,
    assigned_by_name: null,
  },
]

/** A flag shown whole: its text on one line, not wrapped onto a second. */
async function expectOnOneLine(flag: Locator) {
  const lineCount = await flag.evaluate((el) => {
    const text = document.createRange()
    text.selectNodeContents(el)
    return new Set([...text.getClientRects()].map((rect) => Math.round(rect.top))).size
  })
  expect(lineCount).toBe(1)
}

async function expectNoSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )
  expect(fits).toBe(true)
}

test('5.5 AC1/AC5: the overview shows a new event’s coordinator and who assigned it', async ({
  page,
}) => {
  test.setTimeout(60_000)
  const name = await submitRequest(page, 'Overseen')
  await openAsLead(page)

  // AC1: not assigned yet, so nobody assigned it either.
  await expect(overviewItem(page, name)).toContainText(NOT_YET_ASSIGNED)
  await expect(overviewItem(page, name)).not.toContainText('Assigned by')

  // AC5: once the Lead assigns it, a reload shows the coordinator and who assigned it.
  await assignFromQueue(page, name, CHLOE.id)
  await page.goto(PAGE_PATH)
  await page.reload()
  const item = overviewItem(page, name)
  await expect(item).toContainText(CHLOE.name)
  await expect(item).toContainText('Lena Lead')
  await expect(item).not.toContainText(NOT_YET_ASSIGNED)
  // AC5's flag is for a deactivated coordinator only; Chloe is active.
  await expect(item.getByText(DEACTIVATED, { exact: true })).toHaveCount(0)
})

test('5.5 AC1: the filters narrow the overview and survive a reload', async ({ page }) => {
  test.setTimeout(90_000)
  // Two requests this Lead assigns: one to Carl (the one followed), one to Chloe.
  const name = await submitRequest(page, 'Filtered')
  const chloes = await submitRequest(page, 'Filtered for Chloe')
  await signIn(page, ACCOUNTS.lead)
  await assignFromQueue(page, name, CARL.id)
  await assignFromQueue(page, chloes, CHLOE.id)
  await page.goto(PAGE_PATH)
  await expect(overviewItem(page, name)).toBeVisible()

  // Each filter is proven by what it removes, checked once the filtered result is on the page
  // (see refilter). Waiting for the request also proves the page sends the filter.

  // By coordinator: Chloe's events go (this Lead's and her seeded one); Carl's stay, including his
  // self-assigned seeded event.
  await refilter(
    page,
    () => page.getByLabel('Coordinator').selectOption(CARL.id),
    `coordinator=${CARL.id}`,
  )
  await expect(overviewItem(page, name)).toBeVisible()
  await expect(overviewItem(page, HARBOUR_LIGHTS)).toBeVisible()
  await expect(overviewItem(page, chloes)).toHaveCount(0)
  await expect(overviewItem(page, SMART_CITIES_EXPO)).toHaveCount(0)

  // Assigned by me: Carl's self-assigned event goes; the one this Lead assigned stays.
  await refilter(page, () => page.getByLabel('Assigned by me').check(), 'assigned_by=me')
  await expect(overviewItem(page, name)).toBeVisible()
  await expect(overviewItem(page, HARBOUR_LIGHTS)).toHaveCount(0)

  // The filters are in the address, so a reload shows them and applies them: Chloe's event
  // proves the coordinator filter, Carl's self-assigned one proves "Assigned by me". The request
  // being listed first means the fresh result is on the page.
  await expect(page).toHaveURL(/assigned=me/)
  await page.reload()
  await expect(page.getByLabel('Coordinator')).toHaveValue(CARL.id)
  await expect(page.getByLabel('Assigned by me')).toBeChecked()
  await expect(overviewItem(page, name)).toBeVisible()
  await expect(overviewItem(page, chloes)).toHaveCount(0)
  await expect(overviewItem(page, HARBOUR_LIGHTS)).toHaveCount(0)

  // By status: the request is Under Review, so the Planning tab leaves it out and Under Review
  // keeps it; the tab survives a reload too.
  await refilter(
    page,
    () => page.getByRole('tab', { name: /^Planning/ }).click(),
    'status=PLANNING',
  )
  await expect(overviewItem(page, name)).toHaveCount(0)
  await refilter(
    page,
    () => page.getByRole('tab', { name: /^Under Review/ }).click(),
    'status=UNDER_REVIEW',
  )
  await expect(overviewItem(page, name)).toBeVisible()
  await expect(page).toHaveURL(/status=UNDER_REVIEW/)
  await page.reload()
  await expect(page.getByRole('tab', { name: /^Under Review/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(overviewItem(page, name)).toBeVisible()
})

test('5.5 AC1: filters with no match say so', async ({ page }) => {
  // Nothing unassigned is ever Confirmed: approving needs a coordinator.
  await openAsLead(page, '?coordinator=unassigned&status=CONFIRMED')

  await expect(page.getByText(NO_MATCH_MESSAGE)).toBeVisible()
})

test('5.5 AC1: a coordinator filter the list does not offer is named, not shown as all', async ({
  page,
}) => {
  // A deactivated coordinator with no events left drops off the list (P4), so a bookmark to them
  // names nobody the dropdown offers; an id nobody holds stands in for them. The coordinator list
  // is held back first, as it is for a moment on any reload.
  let releaseWorkloads = () => {}
  const isWorkloadsHeld = new Promise<void>((resolve) => {
    releaseWorkloads = resolve
  })
  await page.route(
    (url) => url.pathname === WORKLOADS_API,
    async (route) => {
      if (route.request().resourceType() === 'fetch') await isWorkloadsHeld
      return route.fallback()
    },
  )
  await openAsLead(page, `?coordinator=${UNLISTED_ID}`)
  const filter = page.getByLabel('Coordinator')

  await expect(filter).toHaveValue(UNLISTED_ID)
  await expect(filter.getByRole('option', { selected: true })).toHaveText(LOADING_COORDINATORS)

  releaseWorkloads()
  await expect(filter.getByRole('option', { selected: true })).toHaveText(UNKNOWN_COORDINATOR)
  await expect(filter).toHaveValue(UNLISTED_ID)
  await expect(page.getByText(NO_MATCH_MESSAGE)).toBeVisible()
})

test('5.5 AC1: a coordinator list that fails to load is said on the overview, not taken for an unknown coordinator', async ({
  page,
}) => {
  // The overview still loads Carl's events; only the list that names the coordinators fails, so
  // the filter keeps Carl as the one chosen without claiming he is unknown.
  await failFetch(page, WORKLOADS_API)
  await openAsLead(page, `?coordinator=${CARL.id}`)
  const filter = page.getByLabel('Coordinator')

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(filter).toHaveValue(CARL.id)
  await expect(filter.getByRole('option', { selected: true })).toHaveText(SELECTED_COORDINATOR)
})

test('5.5 AC1: a coordinator in the address that cannot be anyone matches no event', async ({
  page,
}) => {
  // Not an id at all - a mangled bookmark - so nobody holds it: the same as an id nobody holds.
  await openAsLead(page, '?coordinator=not-an-id')

  await expect(page.getByText(NO_MATCH_MESSAGE)).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByLabel('Coordinator').getByRole('option', { selected: true })).toHaveText(
    UNKNOWN_COORDINATOR,
  )
})

test('5.5 AC1: a filter whose events fail to load says so, with no loader left spinning', async ({
  page,
}) => {
  await failFetch(page, OVERVIEW_API, 'status=PLANNING')
  await openAsLead(page)
  await expect(page.getByRole('list', { name: OVERVIEW_LABEL })).toBeVisible()

  await page.getByRole('tab', { name: /^Planning/ }).click()

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText(LOADING_EVENTS)).toHaveCount(0)
})

test('5.5 AC2: the per-coordinator view lists each coordinator’s active events', async ({
  page,
}) => {
  await openAsLead(page)

  await page.getByRole('link', { name: COORDINATORS_VIEW }).click()

  await expect(page).toHaveURL(/view=coordinators/)
  const chloe = coordinatorItem(page, CHLOE.name)
  await expect(chloe).toContainText(/\d+ active events?/)
  await expect(chloe.getByRole('link', { name: SMART_CITIES_EXPO })).toBeVisible()
  await expect(coordinatorItem(page, CARL.name)).toContainText(/\d+ active events?/)
})

test('5.5 AC4/AC5: an idle coordinator shows 0 and a deactivated one is flagged', async ({
  page,
}) => {
  await stubFetch(page, WORKLOADS_API, STUB_WORKLOADS)
  await openAsLead(page, '?view=coordinators')

  const idle = coordinatorItem(page, 'Idle Coordinator')
  await expect(idle.getByText('0 active events', { exact: true })).toBeVisible()
  await expect(idle.getByText(DEACTIVATED, { exact: true })).toHaveCount(0)
  const gone = coordinatorItem(page, 'Departed Coordinator')
  await expect(gone.getByText(DEACTIVATED, { exact: true })).toBeVisible()
  await expect(gone.getByRole('link', { name: STRANDED_EVENT.name })).toBeVisible()
})

test('5.5 AC3: an event opens read-only from the overview', async ({ page }) => {
  await openAsLead(page)

  await overviewItem(page, SMART_CITIES_EXPO).getByRole('link', { name: SMART_CITIES_EXPO }).click()

  await expect(page).toHaveURL(new RegExp(`/events/${EVENTS.smartCitiesExpo}$`))
  await expect(page.getByRole('heading', { name: SMART_CITIES_EXPO, level: 1 })).toBeVisible()
  for (const action of ['Approve', 'Reject', 'Reassign']) {
    await expect(page.getByRole('button', { name: action })).toHaveCount(0)
  }
})

test('5.5 AC3: the way back from an event keeps the view and filters', async ({ page }) => {
  await openAsLead(page, '?status=PLANNING')

  await overviewItem(page, SMART_CITIES_EXPO).getByRole('link', { name: SMART_CITIES_EXPO }).click()
  await expect(page).toHaveURL(new RegExp(`/events/${EVENTS.smartCitiesExpo}$`))
  await page.getByRole('link', { name: `← ${PAGE_TITLE}` }).click()

  await expect(page).toHaveURL(/\/events\/assignments\?status=PLANNING$/)
  await expect(page.getByRole('tab', { name: /^Planning/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
})

test('5.5 AC6: only the Lead reaches the overview', async ({ page }) => {
  await signIn(page, ACCOUNTS.lead)
  const nav = page.getByRole('navigation', { name: 'Main' })
  await expect(nav.getByRole('link', { name: PAGE_TITLE })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()

  await signIn(page, ACCOUNTS.coordinator)
  // The coordinator's own section shows first, so the sidebar has drawn before checking what it
  // leaves out.
  await expect(nav.getByRole('link', { name: 'Events inbox' })).toBeVisible()
  await expect(nav.getByRole('link', { name: PAGE_TITLE })).toHaveCount(0)
  await page.goto(PAGE_PATH)
  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
  await expect(page.getByRole('list', { name: OVERVIEW_LABEL })).toHaveCount(0)
})

for (const { device, viewport } of [
  { device: 'a phone', viewport: PHONE },
  { device: 'a tablet', viewport: TABLET },
  { device: 'a desktop', viewport: DESKTOP },
]) {
  test(`5.5 responsive: the overview fits ${device}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await stubFetch(page, OVERVIEW_API, STUB_OVERVIEW)
    await stubFetch(page, WORKLOADS_API, STUB_WORKLOADS)
    await openAsLead(page)

    // The overview: cards inside the screen, the flags in full, tabs and filters in their box.
    const stranded = overviewItem(page, STRANDED_EVENT.name)
    const waiting = overviewItem(page, WAITING_EVENT.name)
    await expect(stranded).toBeVisible()
    await expectNoSidewaysScroll(page)
    for (const card of [stranded, waiting]) {
      const box = (await card.boundingBox())!
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    }
    for (const flag of [
      stranded.getByText(DEACTIVATED, { exact: true }),
      waiting.getByText(NOT_YET_ASSIGNED, { exact: true }),
    ]) {
      await expect(flag).toBeVisible()
      await expectOnOneLine(flag)
    }
    const tabs = (await page.getByRole('tablist').boundingBox())!
    expect(tabs.x + tabs.width).toBeLessThanOrEqual(viewport.width)

    if (viewport === PHONE) {
      for (const target of [
        page.getByRole('link', { name: OVERVIEW_VIEW }),
        page.getByRole('link', { name: COORDINATORS_VIEW }),
        page.getByRole('tab', { name: /^Planning/ }),
        page.getByLabel('Coordinator'),
        stranded.getByRole('link', { name: STRANDED_EVENT.name }),
      ]) {
        expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
      }
    }

    // The per-coordinator view: stacked cards, the flag in full.
    await page.getByRole('link', { name: COORDINATORS_VIEW }).click()
    const gone = coordinatorItem(page, 'Departed Coordinator')
    await expect(gone).toBeVisible()
    await expectNoSidewaysScroll(page)
    const card = (await gone.boundingBox())!
    expect(card.x + card.width).toBeLessThanOrEqual(viewport.width)
    await expect(gone.getByText(DEACTIVATED, { exact: true })).toBeVisible()
    await expectOnOneLine(gone.getByText(DEACTIVATED, { exact: true }))
  })
}
