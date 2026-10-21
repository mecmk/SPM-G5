/**
 * 20.2 view and act on notifications
 * Happy path
 * 1. The bell in the main navigation shows the unread count and opens the user's newest 50
 *     notifications, newest first, each with its title, message and time; unread notifications stand
 *     out. Opening a notification goes to its item (the page where the reader acts on it while that
 *     page still holds it, otherwise the event) and marks it read. Notifications can also be marked
 *     read one at a time or all at once; marking all leaves unread any notification that arrived after
 *     the list was opened. The user's own recent actions stay in the same panel, below the
 *     notifications, and are not counted.
 * 2. Read status is stored on the server for each user, and the unread count comes from the server, so
 *     it is the same on every device. The count and the list are fetched again whenever the user opens
 *     another page, opens the notification panel, or comes back to the browser tab.
 * Boundary
 * 3. With 0 unread, no badge is shown. More than 99 unread shows "99+".
 * Edge
 * 4. A notification for an item the user can no longer access shows a message, not an error.
 * Permission
 * 5. Users see only their own notifications.
 * Conflict
 * 6. Marking read in one tab shows on refresh in another. The count never goes below 0.
 *
 * This is the browser's half: the bell, the panel, what a click does, and the count being fetched
 * again. Every rule is a backend case (AC5 wholly, the target each notification has for each role,
 * the 50 limit, the count at 0, 99, 100 and 150, marking again, the order of "mark all as read"):
 * backend/tests/notifications/test_view_and_act_on_notifications.py.
 *
 * Everything here reads Nadia Notice's nine seeded notifications (backend/db/seed/020_sample_data.sql;
 * tests/e2e/support.ts NADIA_NOTICES). No other spec signs in as her and no action reaches her, so
 * her unread count is the spec's own. It walks her notifications in the order below, so the
 * count falls 7 -> 6 -> 5 -> 4 -> 3 -> 2 -> 1 -> 0 and the tests are in that order and run one
 * after another. Each of them reads or consumes her seeded notifications for good, so a retry
 * could only fail on a notification already read and hide the first trace: no retries (the walk is
 * the group "walks Nadia's seeded notifications once"). Specs share one database and run in
 * parallel, so no other account's count is asserted: the count at 0 and above 99 is a stubbed
 * answer, and one test holds a request with `page.route`, both for states the seed cannot reach.
 *
 * Outside the walk, and repeat-safe, are the tests that stub the list the bell reads, every row
 * already read: which page each kind of target opens, and what a notification with no target to
 * open says. They change nothing in the database.
 *
 * What a row offers (the contract the panel is built to): its title is a button that opens the
 * item, an unread row says "Unread" in words, and has a "Mark as read" button; the panel has "Mark
 * all as read"; the log of the user's own recent actions is under the heading "Your recent
 * actions". The panel and its rows carry no role="status" or aria-live, which the toasts own.
 */
import { randomUUID } from 'node:crypto'
import { expect, test, type Locator, type Page } from '@playwright/test'
import {
  ACCOUNTS,
  DESKTOP,
  EVENTS,
  MIN_TOUCH_TARGET,
  NADIA_NOTICES,
  NADIA_NOTICES_NEWEST_FIRST,
  PHONE,
  corsHeaders,
  expectNoSidewaysScroll,
  expectSignedIn,
  signIn,
  uniqueName,
  type SeededNotice,
} from './support'

test.use({ viewport: DESKTOP })

const NO_LONGER_AVAILABLE = 'This is no longer available to you.'
const UNREAD = 'Unread'
const UNREAD_COUNT_PATH = '/notifications/unread-count'
const NOTICES_PATH = '/notifications'
const GALA_PATH = `/events/${EVENTS.noticeGala}`
const GALA_NAME = 'Harbour Lights Gala'
const RECENT_ACTIONS = 'Your recent actions'

const bell = (page: Page) => page.getByRole('button', { name: /^Notifications/ })
const panel = (page: Page) => page.getByRole('region', { name: 'Notifications' })
const rowOf = (page: Page, notice: Pick<SeededNotice, 'title'>) =>
  panel(page).getByRole('listitem').filter({ hasText: notice.title })
const unreadWord = (row: Locator) => row.getByText(UNREAD, { exact: true })
/** The number on the bell: a count, or "99+". Nothing at 0. */
const badge = (page: Page) => bell(page).getByText(/^\d+\+?$/)

async function signInAsNadia(page: Page) {
  await signIn(page, ACCOUNTS.notice)
  await expectSignedIn(page)
}

/** Open the panel unless it is already open (opening a notification may leave it open). */
async function openPanel(page: Page) {
  if (!(await panel(page).isVisible())) await bell(page).click()
  await expect(panel(page)).toBeVisible()
}

async function expectUnreadCount(page: Page, count: number) {
  await expect(bell(page)).toHaveAccessibleName(`Notifications, ${count} unread`)
  await expect(badge(page)).toHaveText(String(count))
}

test.describe("walks Nadia's seeded notifications once", () => {
  test.describe.configure({ mode: 'serial', retries: 0 })

  // --- AC1: the bell and the list ----------------------------------------------------------------
  test('20.2 AC1: the bell shows the unread count and the panel lists the newest first', async ({
    page,
  }) => {
    await signInAsNadia(page)

    await expect(bell(page)).toHaveAccessibleName('Notifications, 7 unread')
    await expect(badge(page)).toHaveText('7')
    await openPanel(page)
    const rows = panel(page).getByRole('listitem')
    await expect(rows).toHaveCount(NADIA_NOTICES_NEWEST_FIRST.length)
    for (const [position, notice] of NADIA_NOTICES_NEWEST_FIRST.entries()) {
      await expect(rows.nth(position)).toContainText(notice.title)
      await expect(rows.nth(position)).toContainText(notice.message)
      await expect(rows.nth(position)).toContainText(notice.time)
    }
  })

  test('20.2 AC1: unread notifications are marked in words, not only colour', async ({ page }) => {
    await signInAsNadia(page)
    await openPanel(page)

    for (const notice of NADIA_NOTICES_NEWEST_FIRST) {
      await expect(unreadWord(rowOf(page, notice))).toHaveCount(notice.isRead ? 0 : 1)
    }
  })

  test('20.2 AC1: opening a notification goes to its item and marks it read', async ({ page }) => {
    await signInAsNadia(page)
    await openPanel(page)

    await rowOf(page, NADIA_NOTICES.approved)
      .getByRole('button', { name: NADIA_NOTICES.approved.title })
      .click()

    await expect(page).toHaveURL(new RegExp(`${GALA_PATH}$`))
    await expect(page.getByRole('heading', { name: GALA_NAME }).first()).toBeVisible()
    await expect(bell(page)).toHaveAccessibleName('Notifications, 6 unread')
    await openPanel(page)
    await expect(unreadWord(rowOf(page, NADIA_NOTICES.approved))).toHaveCount(0)
  })

  test('20.2 AC2: read state survives a reload', async ({ page }) => {
    await signInAsNadia(page)

    await page.reload()

    await expect(bell(page)).toHaveAccessibleName('Notifications, 6 unread')
    await expect(badge(page)).toHaveText('6')
    await openPanel(page)
    await expect(unreadWord(rowOf(page, NADIA_NOTICES.approved))).toHaveCount(0)
  })

  test('20.2 AC1: a notification can be marked read on its own', async ({ page }) => {
    await signInAsNadia(page)
    await openPanel(page)
    const urlBefore = page.url()
    const row = rowOf(page, NADIA_NOTICES.safetyApproved)

    await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'PATCH'),
      row.getByRole('button', { name: 'Mark as read' }).click(),
    ])

    await expect(unreadWord(row)).toHaveCount(0)
    await expectUnreadCount(page, 5)
    expect(page.url()).toBe(urlBefore)
    // No toast for marking read, and no entry for it in the log of the user's own actions: the
    // panel still holds just the nine notifications.
    await expect(page.getByRole('status')).toHaveCount(0)
    await expect(panel(page).getByRole('listitem')).toHaveCount(NADIA_NOTICES_NEWEST_FIRST.length)
  })

  test('20.2 AC1: the recent actions stay below the notifications and are not counted', async ({
    page,
  }) => {
    await signInAsNadia(page)
    await page.goto('/events/new')
    await page.getByLabel('Event name').fill(uniqueName('Notice'))
    await page.getByRole('button', { name: 'Save draft' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Draft saved' })).toBeVisible()

    await openPanel(page)

    const heading = panel(page).getByRole('heading', { name: RECENT_ACTIONS })
    await expect(heading).toBeVisible()
    const last = await rowOf(page, NADIA_NOTICES.reassigned).boundingBox()
    const headingBox = await heading.boundingBox()
    const entry = await panel(page).getByText('Draft saved').first().boundingBox()
    expect(last && headingBox && entry).toBeTruthy()
    expect(headingBox!.y).toBeGreaterThanOrEqual(last!.y + last!.height)
    expect(entry!.y).toBeGreaterThan(headingBox!.y)
    await expectUnreadCount(page, 5)
  })

  // --- AC4: an item the reader cannot open ----------------------------------------------------------
  test('20.2 AC4: an item the reader cannot open shows a message and is marked read', async ({
    page,
  }) => {
    await signInAsNadia(page)
    await openPanel(page)
    const urlBefore = page.url()
    const row = rowOf(page, NADIA_NOTICES.oliviasDraft)

    await row.getByRole('button', { name: NADIA_NOTICES.oliviasDraft.title }).click()

    await expect(row.getByText(NO_LONGER_AVAILABLE, { exact: true })).toBeVisible()
    expect(page.url()).toBe(urlBefore)
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(unreadWord(row)).toHaveCount(0)
    await expectUnreadCount(page, 4)
  })

  // --- AC2: the count is the server's, fetched again ----------------------------------------------
  test('20.2 AC2: the badge is refetched when the user opens another page', async ({
    page,
    context,
  }) => {
    await signInAsNadia(page)
    await expectUnreadCount(page, 4)
    const other = await context.newPage()
    await other.goto('/')
    await openPanel(other)
    await Promise.all([
      other.waitForResponse((response) => response.request().method() === 'PATCH'),
      rowOf(other, NADIA_NOTICES.venueUnavailable)
        .getByRole('button', { name: 'Mark as read' })
        .click(),
    ])
    await expectUnreadCount(other, 3)
    // Nothing polls: until the user does something, this page still says 4.
    await expect(bell(page)).toHaveAccessibleName('Notifications, 4 unread')

    await page.getByRole('link', { name: 'My events', exact: true }).click()

    await expect(page).toHaveURL(/\/events\/mine$/)
    await expectUnreadCount(page, 3)
  })

  test('20.2 AC2: the badge is refetched when the tab regains focus', async ({ page, context }) => {
    await signInAsNadia(page)
    await expectUnreadCount(page, 3)
    const other = await context.newPage()
    await other.goto('/')
    await openPanel(other)
    await Promise.all([
      other.waitForResponse((response) => response.request().method() === 'PATCH'),
      rowOf(other, NADIA_NOTICES.clarification)
        .getByRole('button', { name: 'Mark as read' })
        .click(),
    ])
    await expectUnreadCount(other, 2)
    await expect(bell(page)).toHaveAccessibleName('Notifications, 3 unread')

    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))

    await expectUnreadCount(page, 2)
  })

  // --- AC6: another tab ------------------------------------------------------------------------------
  test('20.2 AC6: marking read in one tab shows on refresh in another', async ({
    page,
    context,
  }) => {
    await signInAsNadia(page)
    const other = await context.newPage()
    await other.goto('/')
    await expectUnreadCount(other, 2)
    await openPanel(page)
    await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'PATCH'),
      rowOf(page, NADIA_NOTICES.changeApproved)
        .getByRole('button', { name: 'Mark as read' })
        .click(),
    ])
    await expectUnreadCount(page, 1)

    await other.reload()

    await expectUnreadCount(other, 1)
    await openPanel(other)
    await expect(unreadWord(rowOf(other, NADIA_NOTICES.changeApproved))).toHaveCount(0)
  })

  // --- AC3: the badge at 0 and above 99 ---------------------------------------------------------------
  test('20.2 AC3: no badge at 0, and "99+" above 99', async ({ page }) => {
    // The seed holds no account with 0 or 100 unread, so the count is the one stubbed answer.
    let stubbed = 0
    await page.route(
      (url) => url.pathname === UNREAD_COUNT_PATH,
      (route) => {
        const request = route.request()
        if (request.resourceType() !== 'fetch') return route.fallback()
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({ count: stubbed }),
        })
      },
    )
    await signInAsNadia(page)

    await expect(bell(page)).toHaveAccessibleName('Notifications')
    await expect(badge(page)).toHaveCount(0)

    stubbed = 99
    await page.getByRole('link', { name: 'My events', exact: true }).click()
    await expect(bell(page)).toHaveAccessibleName('Notifications, 99 unread')
    await expect(badge(page)).toHaveText('99')

    stubbed = 100
    await page.getByRole('link', { name: 'Home', exact: true }).click()
    await expect(bell(page)).toHaveAccessibleName('Notifications, 100 unread')
    await expect(badge(page)).toHaveText('99+')
  })

  // --- AC1 on a phone -----------------------------------------------------------------------------------
  test('20.2 AC1: the panel is usable on a phone', async ({ page }) => {
    await page.setViewportSize(PHONE)
    await signInAsNadia(page)

    await expectUnreadCount(page, 1)
    await openPanel(page)
    await expectNoSidewaysScroll(page)
    const markAll = await panel(page)
      .getByRole('button', { name: 'Mark all as read' })
      .boundingBox()
    expect(markAll).toBeTruthy()
    expect(markAll!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET)
    await expect(
      rowOf(page, NADIA_NOTICES.confirmed).getByRole('button', {
        name: NADIA_NOTICES.confirmed.title,
      }),
    ).toBeEnabled()
  })

  // --- AC1: opening a notification waits for the server -----------------------------------------------
  test('20.2 AC1: the page changes only after the notification is marked read', async ({
    page,
  }) => {
    const notice = NADIA_NOTICES.confirmed
    // The one unread notification is opened with its request held and then answered by the test, so
    // the database is not changed: the next test still finds it unread.
    let requestIsHeld!: () => void
    const held = new Promise<void>((resolve) => {
      requestIsHeld = resolve
    })
    let release!: () => void
    const released = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route(
      (url) => url.pathname === `${NOTICES_PATH}/${notice.id}`,
      async (route) => {
        const request = route.request()
        if (request.method() !== 'PATCH' || request.resourceType() !== 'fetch')
          return route.fallback()
        requestIsHeld()
        await released
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: corsHeaders(request),
          body: JSON.stringify({
            id: notice.id,
            notification_type: 'EVENT_CONFIRMED',
            title: notice.title,
            message: notice.message,
            event_id: EVENTS.noticeGala,
            related_entity_type: 'event',
            related_entity_id: EVENTS.noticeGala,
            created_at: '2026-10-19T09:45:00+00:00',
            read_at: new Date().toISOString(),
            target: { kind: 'event', id: EVENTS.noticeGala },
          }),
        })
      },
    )
    await signInAsNadia(page)
    await openPanel(page)
    const urlBefore = page.url()

    await rowOf(page, notice).getByRole('button', { name: notice.title }).click()

    await held
    expect(page.url()).toBe(urlBefore)
    await expect(panel(page)).toBeVisible()

    release()

    await expect(page).toHaveURL(new RegExp(`${GALA_PATH}$`))
    await expect(page.getByRole('heading', { name: GALA_NAME }).first()).toBeVisible()
  })

  // --- AC2: opening the bell ----------------------------------------------------------------------------
  test('20.2 AC2: opening the bell reads the notifications again', async ({ page }) => {
    await signInAsNadia(page)
    await page.waitForLoadState('networkidle')
    function isReadOf(path: string) {
      return page.waitForRequest(
        (request) => request.method() === 'GET' && new URL(request.url()).pathname === path,
        { timeout: 5000 },
      )
    }
    const countIsRead = isReadOf(UNREAD_COUNT_PATH)
    const listIsRead = isReadOf(NOTICES_PATH)

    await bell(page).click()

    await Promise.all([countIsRead, listIsRead])
    await expect(panel(page)).toBeVisible()
  })

  // --- AC1: mark all as read (last: it empties the count) -----------------------------------------------
  test('20.2 AC1: mark all as read clears everything and sends the newest id it loaded', async ({
    page,
  }) => {
    await signInAsNadia(page)
    await openPanel(page)
    const request = page.waitForRequest(
      (sent) => sent.method() === 'PATCH' && new URL(sent.url()).pathname === NOTICES_PATH,
    )

    await panel(page).getByRole('button', { name: 'Mark all as read' }).click()

    expect((await request).postDataJSON()).toEqual({
      is_read: true,
      through_id: NADIA_NOTICES.confirmed.id,
    })
    await expect(unreadWord(panel(page))).toHaveCount(0)
    await expect(badge(page)).toHaveCount(0)
    await expect(bell(page)).toHaveAccessibleName('Notifications')
  })
})

// --- AC1, AC4: where each kind of target goes ---------------------------------------------------------
// These stub the list the bell reads (the only call stubbed), every row already read, so opening one
// sends no request to mark it read and nothing in the database changes: they are repeat-safe, and
// sit outside the walk above. Nadia is an organiser who may open few of these pages, but
// RequirePermission answers in place, so the address the click lands on is the same.

const STUBBED_TIME = '2026-10-19T09:00:00+00:00'

interface StubbedTarget {
  kind: string
  id: string | null
}

function stubbedRow(title: string, target: StubbedTarget | null) {
  return {
    id: randomUUID(),
    notification_type: 'EVENT_APPROVED',
    title,
    message: `${title}, from the stub.`,
    event_id: null,
    related_entity_type: null,
    related_entity_id: null,
    created_at: STUBBED_TIME,
    read_at: STUBBED_TIME,
    target,
  }
}

async function stubNotificationList(page: Page, rows: ReturnType<typeof stubbedRow>[]) {
  await page.route(
    (url) => url.pathname === NOTICES_PATH,
    (route) => {
      const request = route.request()
      if (request.method() !== 'GET' || request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: corsHeaders(request),
        body: JSON.stringify(rows),
      })
    },
  )
}

/** Each kind of target, how the title names it, and the address it opens (frontend/src/routes.ts),
 * pinned here as the other specs pin theirs. `takesId` kinds are sent a made-up id, which the
 * address carries. */
const TARGET_PAGES = [
  { kind: 'event', label: 'event', takesId: true, path: (id: string) => `/events/${id}` },
  {
    kind: 'booking_request',
    label: 'booking request',
    takesId: true,
    path: (id: string) => `/venue-staff/booking-requests/${id}`,
  },
  {
    kind: 'equipment_requests',
    label: 'equipment requests',
    takesId: false,
    path: () => '/equipment/requests',
  },
  {
    kind: 'safety_check',
    label: 'safety check',
    takesId: true,
    path: (id: string) => `/safety-checks/${id}`,
  },
  { kind: 'registrations', label: 'registrations', takesId: false, path: () => '/registrations' },
  {
    kind: 'unassigned_events',
    label: 'unassigned events',
    takesId: false,
    path: () => '/events/unassigned',
  },
  {
    kind: 'change_request_queue',
    label: 'change request queue',
    takesId: false,
    path: () => '/change-requests/review',
  },
]

for (const { kind, label, takesId, path } of TARGET_PAGES) {
  test(`20.2 AC1: the ${label} target opens ${path('<id>')}`, async ({ page }) => {
    const id = takesId ? randomUUID() : null
    const row = stubbedRow(`Stub ${kind}`, { kind, id })
    await stubNotificationList(page, [row])
    await signInAsNadia(page)
    await openPanel(page)

    await rowOf(page, row).getByRole('button', { name: row.title }).click()

    await expect(page).toHaveURL((url) => url.pathname === path(id ?? '') && url.search === '')
  })
}

test('20.2 AC4: a notification with no target, or a kind the app does not know, shows the message', async ({
  page,
}) => {
  const noTarget = stubbedRow('Stub no target', null)
  const unknownKind = stubbedRow('Stub unknown kind', { kind: 'teleporter', id: null })
  await stubNotificationList(page, [noTarget, unknownKind])
  await signInAsNadia(page)
  await openPanel(page)
  const urlBefore = page.url()

  for (const row of [noTarget, unknownKind]) {
    await rowOf(page, row).getByRole('button', { name: row.title }).click()

    await expect(rowOf(page, row).getByText(NO_LONGER_AVAILABLE, { exact: true })).toBeVisible()
    expect(page.url()).toBe(urlBefore)
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
})
