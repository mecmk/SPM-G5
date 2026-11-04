/**
 * Story 13.1 - fe/be: display the venue staff booking requests queue.
 * AC1 the queue lists all pending requests for venues the staff member is responsible for.
 * AC2 each entry shows event name, requested venue, period, expected attendance and stated
 *     requirements.
 * AC3 decided requests do not appear in the pending queue.
 * Entry shape across several rows, malformed input and 401/403 refusals are backend cases:
 * backend/tests/bookings/test_list_bookings.py.
 *
 * Story 13.1.2 - fe/be: booking status tabs and decision timing.
 * AC1 the queue opens on Pending, and All / Approved / Rejected tabs show the rest, each with
 *     how many requests it holds (the same tab pattern as the coordinator's Events inbox, story
 *     6.1). Which statuses each tab returns, and the counts, are backend cases.
 * AC2/AC3 (when a request was raised and decided) are backend cases, except how a card labels
 *     a request nobody on staff decided (CANCELLED / WITHDRAWN): "Closed at" and "Note" rather
 *     than "Decided at" and "Reason".
 * AC4 the queue shows ten requests a page, with Previous / numbered pages / Next. The seed holds
 *     fewer than ten per tab, so the paging tests fake a longer queue; the limit/offset rules
 *     themselves are backend cases. The old page is hidden while the next one loads, and a page
 *     left past the end (requests decided elsewhere) gives way to the last page that has any.
 *
 * Story 13.2 - fe: an Approve action on the queue card and the detail page.
 * AC1 approving sets the request to Approved: it leaves the Pending tab and shows under
 *     Approved.
 * The approve/conflict rules themselves (already-decided, double-booking) are backend cases,
 * proven end to end in backend/tests/bookings/test_approve_booking.py; these two tests only
 * prove the button correctly drives that endpoint and the page reflects the result. Each uses
 * its own dedicated seeded booking (see backend/db/seed/020_sample_data.sql's note) so
 * approving it cannot affect story 13.1's own assertions in a fullyParallel run.
 *
 * Story 13.2.1 - fe: a Reject action, mirroring Approve, plus the reason it requires and the
 * requesting coordinator's read access to the outcome.
 * AC2 an empty/whitespace-only reason blocks submission client-side (no request fires).
 * AC3 the reject dialog names the booking, can be cancelled, prevents duplicate submission,
 *     preserves a typed reason on failure, and the card leaves the Pending tab the way Approve's
 *     does, showing under Rejected with its reason.
 * AC4 the requesting coordinator reaches the outcome through normal navigation (Events inbox ->
 *     event -> its venue booking) and the same page hides decide actions from them; the booking
 *     card there reads as a history (every booking ever raised, most recent first), not just the
 *     current one - a rejected request stays visible once a fresh one is raised. (Not a numbered
 *     backlog AC of its own - it is how AC4's "reaches the outcome" is satisfied once an event can
 *     carry more than one booking - see backend/tests/bookings/test_booking_for_event.py.)
 * The reject validation matrix, permission refusals, 409s and audit behaviour are backend cases:
 * backend/tests/bookings/test_reject_booking.py. Each mutating test here uses its own dedicated
 * seeded booking, same reasoning as 13.2's.
 *
 * Story 13.1.3 - fe: the requested venue's availability calendar on the request detail page.
 * AC1 the detail page shows the venue's availability calendar - story 9.1's, with its legend,
 *     Previous / Next and day list.
 * AC2 it opens on the month the request starts in, with that day's list already open, so staff
 *     see what else is on that day.
 * AC3 a calendar that fails to load shows availability as unknown, and the request can still be
 *     decided.
 * AC4 a decision made on the page reloads the calendar in place, keeping its month and open day,
 *     so the request's day shows it booked (or gone, once rejected). The approve and reject calls
 *     are faked, so the seeded request stays pending for the other tests that read it in a
 *     fullyParallel run.
 * What the calendar returns, and who may read it, are story 9.1's backend cases:
 * backend/tests/venues/test_venue_calendar.py.
 *
 * Story 13.2.2 - fe: the event page shows when Venue Staff decided a booking.
 * AC1 an approved or rejected booking's card shows its decision time; a pending one shows none;
 *     a withdrawn or cancelled one shows when it was closed, with the queue's "Closed at" / "Note".
 * That the API returns `decided_at` at all (null while pending, set once decided) is a backend
 * case: backend/tests/bookings/test_booking_decided_at.py.
 *
 * Story 15.2.1 - fe: say what each tab holds.
 * AC2 the booking queue's subtitle says what the selected tab holds, as the equipment queue's
 *     does (AC1, in equipment-queue.spec.ts): Expired and Cancelled say why a booking ended up
 *     there. Purely client-side text, so there is no backend case.
 *
 * f13.1.5 (13.1 AC2, 13.2 AC1): a booking over more than one day names both dates of its own
 * period on the queue card, in the Approve dialog, on the request's page and in its approve
 * notice, so Venue Staff never approve one seeing a single date; a one-day booking reads as
 * before. The two-day test raises its own request through the UI, on a fresh two-day event, and
 * closes each dialog without approving it. The one-day test reads the seeded Community Choir
 * Showcase request, which no spec decides, and closes each dialog too.
 */
import { expect, test, type Page, type Route } from '@playwright/test'
import {
  ACCOUNTS,
  approvedEvent,
  corsHeaders,
  EVENTS,
  inFuture,
  signIn,
  venueCard,
} from './support'

const QUEUE_PAGE_SIZE = 10
const FAKE_QUEUE_LENGTH = 25
// Story 12.7: the hold's expiry Venue Staff give as they approve, before either approved request's
// booked period starts.
const HOLD_EXPIRES = '2027-05-01T09:00'

/** One fake queue entry, numbered so each page's rows can be told apart. */
function fakeQueueEntry(index: number) {
  const number = String(index + 1).padStart(2, '0')
  return {
    id: `00000000-0000-0000-0000-0000000000${number}`,
    event_id: '33333333-0000-0000-0000-000000000003',
    event_name: `Paged Request ${number}`,
    venue_id: '22222222-0000-0000-0000-000000000001',
    venue_name: 'Grand Hall',
    venue_location: 'Tower A',
    starts_at: '2027-03-01T01:00:00Z',
    ends_at: '2027-03-01T03:00:00Z',
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
    // Story 12.6: the queue entry's fields for a replacement and a released original, none set
    // here; story 9.5's, for a request or booking a venue closure ended, likewise.
    replaces_venue_name: null,
    approval_releases_venue_name: null,
    released_at: null,
    closure_reason: null,
    closure_description: null,
  }
}

/**
 * A pending request's card, by the short id shown on it (the seeded row's last 8 hex characters,
 * uppercased - the `#XXXXXXXX` badge `BookingRequestsPage` renders). Filtering by event name
 * alone is not safe for these two tests: story 12.1's `booking-requests.spec.ts` can raise its
 * own live request against this same seeded event while this spec runs in parallel, and that
 * request carries *the event's own* attendance and layout, not this booking's overridden ones
 * (60 / Classroom / "Breakout track B." here, vs. the event's 350 / Theatre) - so an event-name
 * match is not interchangeable the way a plain `.first()` would assume.
 */
function pendingCard(page: Page, shortId: string) {
  return page.getByRole('listitem').filter({ hasText: `#${shortId}` })
}

test('13.1 AC1/AC2: venue staff see a pending request with its summary', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Booking Requests' })).toBeVisible()
  const card = pendingCard(page, '00000002')
  await expect(card).toContainText('Nimbus Developer Conference')
  await expect(card).toContainText('Seminar Room 2.1')
  await expect(card).toContainText('60')
  await expect(card).toContainText('Breakout track B.')
})

test('13.1 AC2: the request detail page shows the event, booking and requirements', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = pendingCard(page, '00000002')
  await card.getByRole('link', { name: 'View details' }).click()

  // The queue card's own event name is also a heading, so wait for the URL - the only
  // unambiguous sign navigation to the detail page actually finished.
  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByText('Omar Organiser')).toBeVisible()
  await expect(page.getByText('Annual customer conference')).toBeVisible()
  await expect(page.getByText('Seminar Room 2.1')).toBeVisible()
  await expect(page.getByText('Classroom')).toBeVisible()
  await expect(page.getByText('Breakout track B.')).toBeVisible()
  await expect(page.getByText('Projector & screen')).toBeVisible()
  await expect(page.getByText('Wheelchair access')).toBeVisible()
})

test('13.1 AC1: the queue shows requests across different events, venues and dates', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(pendingCard(page, '00000002')).toBeVisible()
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Annual Wellness Summit' }),
  ).toBeVisible()
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Product Roadmap Townhall' }),
  ).toBeVisible()
})

/** The seeded APPROVED Nimbus/Grand Hall booking. A different, PENDING request (Product
 * Roadmap Townhall) also books Grand Hall, so the venue alone does not identify it. */
function approvedGrandHallCard(page: Page) {
  return page
    .getByRole('listitem')
    .filter({ hasText: 'Nimbus Developer Conference' })
    .filter({ hasText: 'Grand Hall' })
}

test('13.1 AC3: an approved booking does not appear in the pending queue', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('tab', { name: /^Pending/ })).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Product Roadmap Townhall' }),
  ).toBeVisible()
  await expect(approvedGrandHallCard(page)).toHaveCount(0)
})

test('13.1.2 AC1: the queue opens on Pending, and the Approved tab shows a decided booking', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('tab', { name: /^Pending/ })).toHaveAttribute('aria-selected', 'true')

  await page.getByRole('tab', { name: /^Approved/ }).click()
  await expect(approvedGrandHallCard(page)).toBeVisible()
  await expect(approvedGrandHallCard(page).getByRole('button', { name: 'Approve' })).toHaveCount(0)

  await page.getByRole('tab', { name: /^Rejected/ }).click()
  await expect(approvedGrandHallCard(page)).toHaveCount(0)
  // Fewer than ten requests: one page, so no page controls. Checked on Rejected: All gains a
  // request from every spec that sends one, and Approved holds the seeded approvals of several
  // stories (story 12.6's seed alone approves a dozen and more), so either can pass ten, while
  // Rejected holds none seeded and at most the two 13.2.1's tests reject.
  await expect(page.getByRole('navigation', { name: 'Pages' })).toHaveCount(0)

  // A pending card first: only All's own answer holds one, so the approved card checked after it
  // cannot be one left over from an earlier tab.
  await page.getByRole('tab', { name: /^All/ }).click()
  await expect(pendingCard(page, '00000002')).toBeVisible()
  await expect(approvedGrandHallCard(page)).toBeVisible()
})

test('15.2.1 AC2: the subtitle says what the selected tab holds', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const pendingHint = page.getByText(
    'Waiting for a decision. A pending request already holds its venue.',
  )
  await expect(pendingHint).toBeVisible()

  await page.getByRole('tab', { name: /^Expired/ }).click()
  await expect(
    page.getByText(
      'Approved, but the hold expired before the event was confirmed, so the venue was ' +
        'released. Read-only.',
    ),
  ).toBeVisible()
  await expect(pendingHint).toHaveCount(0)

  await page.getByRole('tab', { name: /^Cancelled/ }).click()
  await expect(
    page.getByText(
      'Released because the event was cancelled, a change to it no longer fit, a replacement ' +
        'venue was approved, a safety review released it, the coordinator cancelled it, or the ' +
        'venue closed. Read-only.',
    ),
  ).toBeVisible()

  await page.goto('/venue-staff/booking-requests?search=no-such-request')
  await expect(page.getByRole('tab', { name: 'Pending (0)' })).toBeVisible()
  await expect(pendingHint).toBeVisible()
})

test('13.1.2 AC3: a cancelled request shows when it was closed, not when staff decided it', async ({
  page,
}) => {
  // Migration 010 cancelled some pending requests itself, stamping decided_at and a system note.
  // The seed holds no cancelled booking, so fake one next to a staff-approved one.
  const approved = {
    ...fakeQueueEntry(0),
    event_name: 'Staff Approved Request',
    status: 'APPROVED',
    decided_at: '2026-09-21T02:00:00Z',
  }
  const cancelled = {
    ...fakeQueueEntry(1),
    event_name: 'System Cancelled Request',
    status: 'CANCELLED',
    decided_at: '2026-09-22T02:00:00Z',
    decision_reason: 'Cancelled when pending requests began to hold their venue.',
  }
  await page.route(
    (url) => url.pathname === '/bookings',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [approved, cancelled],
          total: 2,
          counts: {
            pending: 0,
            approved: 1,
            rejected: 0,
            withdrawn: 0,
            cancelled: 1,
            expired: 0,
          },
        }),
        headers: corsHeaders(request),
      })
    },
  )

  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('tab', { name: /^All/ }).click()
  // A cancelled request has no tab of its own, but still counts towards All.
  await expect(page.getByRole('tab', { name: 'All (2)', exact: true })).toBeVisible()

  const approvedCard = page.getByRole('listitem').filter({ hasText: 'Staff Approved Request' })
  await expect(approvedCard.getByText('Decided at', { exact: true })).toBeVisible()

  const cancelledCard = page.getByRole('listitem').filter({ hasText: 'System Cancelled Request' })
  await expect(cancelledCard.getByText('Closed at', { exact: true })).toBeVisible()
  await expect(cancelledCard.getByText('Note', { exact: true })).toBeVisible()
  await expect(cancelledCard.getByText('Decided at', { exact: true })).toHaveCount(0)
  await expect(cancelledCard.getByText('Reason', { exact: true })).toHaveCount(0)
})

test('13.1.2 AC4: the queue shows ten requests a page, with numbered pages', async ({ page }) => {
  const askedFor: URLSearchParams[] = []
  await page.route(
    (url) => url.pathname === '/bookings',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const params = new URL(request.url()).searchParams
      askedFor.push(params)
      const offset = Number(params.get('offset'))
      const limit = Number(params.get('limit'))
      const every = Array.from({ length: FAKE_QUEUE_LENGTH }, (_, index) => fakeQueueEntry(index))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: every.slice(offset, offset + limit),
          total: FAKE_QUEUE_LENGTH,
          counts: {
            pending: FAKE_QUEUE_LENGTH,
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

  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const pager = page.getByRole('navigation', { name: 'Pages' })
  const cards = page.getByRole('listitem').filter({ hasText: 'Paged Request' })
  await expect(cards).toHaveCount(QUEUE_PAGE_SIZE)
  await expect(page.getByText('Showing 1–10 of 25 requests')).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Pending (25)', exact: true })).toBeVisible()
  await expect(pager.getByRole('button', { name: 'Previous' })).toBeDisabled()
  await expect(pager.getByRole('button', { name: '1', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  )

  await pager.getByRole('button', { name: '2', exact: true }).click()
  await expect(page.getByText('Showing 11–20 of 25 requests')).toBeVisible()
  await expect(cards.filter({ hasText: 'Paged Request 11' })).toBeVisible()
  await expect(cards.filter({ hasText: 'Paged Request 01' })).toHaveCount(0)

  await pager.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByText('Showing 21–25 of 25 requests')).toBeVisible()
  await expect(cards).toHaveCount(FAKE_QUEUE_LENGTH - 2 * QUEUE_PAGE_SIZE)
  await expect(pager.getByRole('button', { name: 'Next' })).toBeDisabled()

  const last = askedFor.at(-1)
  expect(last?.get('limit')).toBe(String(QUEUE_PAGE_SIZE))
  expect(last?.get('offset')).toBe(String(2 * QUEUE_PAGE_SIZE))
  expect(last?.get('status')).toBe('PENDING')
})

/** Answer the queue's GETs with `every` paged by limit/offset, `total` as the tab's size, and
 * `hold` deciding whether one offset waits before it is answered. */
async function fakeQueue(
  page: Page,
  every: ReturnType<typeof fakeQueueEntry>[],
  total: (offset: number) => number,
  hold: (offset: number) => Promise<void> = async () => {},
) {
  await page.route(
    (url) => url.pathname === '/bookings',
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch' || request.method() !== 'GET') {
        return route.fallback()
      }
      const params = new URL(request.url()).searchParams
      const offset = Number(params.get('offset'))
      const limit = Number(params.get('limit'))
      await hold(offset)
      const size = total(offset)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: every.slice(0, size).slice(offset, offset + limit),
          total: size,
          counts: {
            pending: size,
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
}

test('13.1.2 AC4: while the next page loads, the previous page is not shown', async ({ page }) => {
  let release = () => {}
  const secondPageHeld = new Promise<void>((resolve) => {
    release = resolve
  })
  const every = Array.from({ length: FAKE_QUEUE_LENGTH }, (_, index) => fakeQueueEntry(index))
  await fakeQueue(
    page,
    every,
    () => FAKE_QUEUE_LENGTH,
    (offset) => (offset === QUEUE_PAGE_SIZE ? secondPageHeld : Promise.resolve()),
  )

  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  const cards = page.getByRole('listitem').filter({ hasText: 'Paged Request' })
  await expect(cards).toHaveCount(QUEUE_PAGE_SIZE)

  await page
    .getByRole('navigation', { name: 'Pages' })
    .getByRole('button', { name: '2', exact: true })
    .click()
  await expect(page.getByText('Loading booking requests…')).toBeVisible()
  await expect(cards).toHaveCount(0)

  release()
  await expect(page.getByText('Showing 11–20 of 25 requests')).toBeVisible()
  await expect(cards.filter({ hasText: 'Paged Request 11' })).toBeVisible()
})

test('13.1.2 AC4: a page emptied by decisions made elsewhere shows the last page instead', async ({
  page,
}) => {
  // Twelve wait when the queue opens; by the time page 2 is asked for, two were decided elsewhere,
  // so ten remain and page 2 is past the end.
  let remaining = 12
  const every = Array.from({ length: remaining }, (_, index) => fakeQueueEntry(index))
  await fakeQueue(page, every, (offset) => {
    if (offset === QUEUE_PAGE_SIZE) remaining = QUEUE_PAGE_SIZE
    return remaining
  })

  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await expect(page.getByText('Showing 1–10 of 12 requests')).toBeVisible()

  await page
    .getByRole('navigation', { name: 'Pages' })
    .getByRole('button', { name: '2', exact: true })
    .click()

  const cards = page.getByRole('listitem').filter({ hasText: 'Paged Request' })
  await expect(cards).toHaveCount(QUEUE_PAGE_SIZE)
  await expect(cards.filter({ hasText: 'Paged Request 01' })).toBeVisible()
  await expect(page.getByText('No requests waiting. You are up to date.')).toHaveCount(0)
})

test('13.1: a coordinator cannot open the booking requests queue', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})

test('13.2 AC1: approving from the queue card moves it from Pending to Approved', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Founders Day Fireside Chat' })
  await card.getByRole('button', { name: 'Approve' }).click()

  // Story 12.7: Venue Staff give the hold its expiry as they approve, before the 1 Jun 2027 chat.
  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await dialog.getByLabel('Hold expires').fill(HOLD_EXPIRES)
  await dialog.getByRole('button', { name: 'Approve' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(card).toHaveCount(0)

  // The Approved tab runs to several pages of seeded bookings, so the card is searched for.
  await page.getByRole('tab', { name: /^Approved/ }).click()
  await page.getByRole('searchbox', { name: 'Search requests' }).fill('Founders Day Fireside Chat')
  await expect(card.getByText('Approved', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Reject' })).toHaveCount(0)
})

test('13.2 AC1: approving from the detail page shows the request as approved', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Investor Demo Day' })
  await card.getByRole('link', { name: 'View details' }).click()

  // The URL changes before the detail page renders, and the queue card's event name is an h3, so
  // only the detail page's level-1 title shows the queue's Approve buttons are gone.
  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Investor Demo Day', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()

  // Story 12.7: Venue Staff give the hold its expiry as they approve, before the 1 Jul 2027 day.
  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await dialog.getByLabel('Hold expires').fill(HOLD_EXPIRES)
  await dialog.getByRole('button', { name: 'Approve' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('13.2.1 AC2/AC3: the reject dialog requires a reason, can be cancelled, and rejecting moves the card to Rejected with its reason', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Winter Charity Gala' })
  await card.getByRole('button', { name: 'Reject' }).click()

  const dialog = page.getByRole('dialog', { name: 'Reject this booking?' })
  await expect(dialog).toContainText('Winter Charity Gala')

  // AC2: an empty reason blocks submission client-side - no request fires, dialog stays open.
  await dialog.getByRole('button', { name: 'Reject' }).click()
  await expect(dialog.getByRole('alert')).toHaveText('Enter a reason for rejecting this request.')
  await expect(dialog).toBeVisible()

  // AC3: Cancel makes no change - the card is still there, still pending.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(card).toBeVisible()

  await card.getByRole('button', { name: 'Reject' }).click()
  const reopenedDialog = page.getByRole('dialog', {
    name: 'Reject this booking?',
  })
  await reopenedDialog
    .getByLabel('Reason for rejecting')
    .fill('Budget was reallocated to another event.')

  // AC3: duplicate submission is prevented - hold the request in flight (same trick as
  // booking-requests.spec.ts's f1.1.1 case) and confirm the button disables rather than
  // accepting a second click.
  await page.route(
    (url) => /\/bookings\/[^/]+\/reject$/.test(url.pathname),
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    },
  )
  const confirmButton = reopenedDialog.getByRole('button', { name: 'Reject' })
  await confirmButton.click()
  await expect(confirmButton).toBeDisabled()

  await expect(reopenedDialog).not.toBeVisible()
  await expect(card).toHaveCount(0)

  await page.getByRole('tab', { name: /^Rejected/ }).click()
  await expect(card.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(card).toContainText('Budget was reallocated to another event.')
  await expect(card.getByRole('button', { name: 'Reject' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('13.2.1 AC3: a failed rejection preserves the typed reason', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await page.route(
    (url) => /\/bookings\/[^/]+\/reject$/.test(url.pathname),
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'This request is already APPROVED, so it cannot be rejected.',
        }),
        headers: corsHeaders(request),
      })
    },
  )

  const card = pendingCard(page, '00000002')
  await card.getByRole('button', { name: 'Reject' }).click()

  const dialog = page.getByRole('dialog', { name: 'Reject this booking?' })
  const reason = 'Double booked in error.'
  await dialog.getByLabel('Reason for rejecting').fill(reason)
  await dialog.getByRole('button', { name: 'Reject' }).click()

  await expect(dialog.getByRole('alert')).toContainText('cannot be rejected')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('Reason for rejecting')).toHaveValue(reason)
})

test('13.2.1 AC3/AC4: rejecting from the detail page shows the outcome to venue staff and the requesting coordinator', async ({
  page,
}) => {
  // Three full sign-in cycles (coordinator, venue staff, coordinator again), plus raising a
  // second request afterward, genuinely take longer than the default per-test budget.
  test.setTimeout(75_000)

  // Before any decision: the requesting coordinator can already reach the booking's outcome
  // through normal navigation - the event page itself, no click-through needed.
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto('/events/inbox')
  await page.getByRole('link', { name: 'Alumni Homecoming Weekend' }).click()
  await expect(page.getByRole('heading', { name: 'Alumni Homecoming Weekend' })).toBeVisible()
  await expect(page.getByText('Pending', { exact: true })).toBeVisible()
  await expect(page.getByText('Awaiting review by Venue Staff.')).toBeVisible()

  // Venue staff rejects it from the detail page.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  const card = page.getByRole('listitem').filter({ hasText: 'Alumni Homecoming Weekend' })
  await card.getByRole('link', { name: 'View details' }).click()

  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  // level 1 is the detail page's own title; the queue card it came from carries the same name as
  // an h3, so without it this passes before the detail page has rendered.
  await expect(
    page.getByRole('heading', { name: 'Alumni Homecoming Weekend', level: 1 }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Reject' }).click()

  const dialog = page.getByRole('dialog', { name: 'Reject this booking?' })
  await dialog.getByLabel('Reason for rejecting').fill('The venue is unavailable that weekend.')
  await dialog.getByRole('button', { name: 'Reject' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(page.getByText('The venue is unavailable that weekend.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)

  // The requesting coordinator revisits and reads the persisted outcome.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.coordinator2)
  await page.goto('/events/inbox')
  await page.getByRole('link', { name: 'Alumni Homecoming Weekend' }).click()
  // The booking's own status: the seed gives this event a rejected change request too (c14), whose
  // badge also reads Rejected.
  const bookingSection = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookingSection.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(page.getByText('The venue is unavailable that weekend.')).toBeVisible()

  // AC4 continued: raising a fresh request for the same event does not replace the rejected one
  // - both show up on the event page's history, the new request first. Since f12.1.1 a request
  // starts from the event: Find a venue, then Request this venue in the catalogue. Since s8.1 the
  // catalogue lists only venues that fit the event and are free, so the fresh request goes to
  // Exhibition Foyer, which the rejection above has just freed.
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await venueCard(page, 'Exhibition Foyer')
    .getByRole('link', { name: 'Request this venue' })
    .click()
  await page.getByRole('button', { name: 'Send request' }).click()
  // Story 12.5 AC6: the event has one venue requirement, so sending opens its page.
  await expect(
    page.getByRole('heading', { name: 'Alumni Homecoming Weekend', level: 1 }),
  ).toBeVisible()

  await page.goto('/events/inbox')
  await page.getByRole('link', { name: 'Alumni Homecoming Weekend' }).click()
  // The rejected request and the fresh one are both for Exhibition Foyer.
  await expect(bookingSection.getByText('Exhibition Foyer', { exact: true })).toHaveCount(2)
  await expect(bookingSection.getByText('Pending', { exact: true })).toBeVisible()
  await expect(bookingSection.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(bookingSection.getByText('The venue is unavailable that weekend.')).toBeVisible()
  await expect(bookingSection).toContainText(/Pending[\s\S]*Rejected/)
})

test('13.2.2 AC1: the event page shows when Venue Staff decided a booking', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.approved}`)

  // The seeded Grand Hall booking was approved at 2026-09-04 10:00+08; format.ts pins en-SG and
  // Asia/Singapore, so the rendered time is fixed. The seeded Seminar Room 2.1 booking, and any
  // request booking-requests.spec.ts raises on this event in parallel, are still pending, so
  // the approved card is the only one with the line.
  const bookingSection = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookingSection.getByText('Approved', { exact: true })).toBeVisible()
  await expect(bookingSection.getByText('Decided at')).toHaveCount(1)
  await expect(bookingSection.getByText('Fri, 4 Sept 2026, 10:00')).toBeVisible()
})

test('13.2.2 AC1: withdrawn and cancelled bookings show when they were closed, not decided', async ({
  page,
}) => {
  // No seeded event has a withdrawn and a cancelled booking side by side, so stub the one call
  // the card list reads. A withdrawal and a system cancellation both stamp `decided_at`, but
  // nobody on Venue Staff decided them, so they take the booking queue's "Closed at" / "Note".
  const booking = {
    venue_id: '00000000-0000-0000-0000-000000000000',
    venue_location: 'Level 1',
    venue_cover_image_url: null,
    starts_at: '2026-11-20T01:00:00Z',
    ends_at: '2026-11-20T09:00:00Z',
    setup_minutes: 60,
    teardown_minutes: 60,
    cancelled_at: null,
    // Story 12.6 and 9.5: the fields every outcome now carries, none of them set for these three.
    closure_reason: null,
    closure_description: null,
    replaces_booking_id: null,
    replaced_by_booking_id: null,
    replaces_venue_name: null,
    replaced_by_venue_name: null,
    pending_replacement_venue_name: null,
    released_at: null,
  }
  const outcomes = [
    {
      ...booking,
      id: 'rejected',
      venue_name: 'Rejected Hall',
      status: 'REJECTED',
      decided_at: '2026-09-01T02:00:00Z',
      decision_reason: 'The hall is closed for maintenance.',
    },
    {
      ...booking,
      id: 'withdrawn',
      venue_name: 'Withdrawn Hall',
      status: 'WITHDRAWN',
      decided_at: '2026-09-02T02:00:00Z',
      decision_reason: null,
    },
    {
      ...booking,
      id: 'cancelled',
      venue_name: 'Cancelled Hall',
      status: 'CANCELLED',
      decided_at: '2026-09-03T02:00:00Z',
      decision_reason: 'Cancelled when pending requests began to hold their venue.',
    },
  ]
  await page.route(
    (url) => url.pathname === `/bookings/for-event/${EVENTS.approved}`,
    async (route) => {
      const request = route.request()
      if (request.resourceType() !== 'fetch') return route.fallback()
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(outcomes),
        headers: corsHeaders(request),
      })
    },
  )

  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.approved}`)

  const bookingSection = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookingSection.getByText('Cancelled Hall', { exact: true })).toBeVisible()

  // Only the rejected booking was decided; the other two were closed, each with its own time.
  await expect(bookingSection.getByText('Decided at', { exact: true })).toHaveCount(1)
  await expect(bookingSection.getByText('Closed at', { exact: true })).toHaveCount(2)
  await expect(bookingSection.getByText('Tue, 1 Sept 2026, 10:00')).toBeVisible()
  await expect(bookingSection.getByText('Wed, 2 Sept 2026, 10:00')).toBeVisible()
  await expect(bookingSection.getByText('Thu, 3 Sept 2026, 10:00')).toBeVisible()

  // The system's cancellation note is not a Venue Staff reason.
  await expect(bookingSection.getByText('Reason', { exact: true })).toHaveCount(1)
  await expect(bookingSection.getByText('Note', { exact: true })).toHaveCount(1)
})

/** Nimbus Developer Conference's pending request for Seminar Room 2.1, 25 Nov 2026 13:00-18:00. */
const NIMBUS_SEMINAR_REQUEST_ID = '44444444-0000-0000-0000-000000000002'
// Story 12.7: the hold's expiry Venue Staff give it as they approve, before its 25 Nov start.
const NIMBUS_SEMINAR_HOLD_EXPIRES = '2026-11-20T09:00'

/** The request detail page's calendar card - a region via its `aria-labelledby`. */
function venueAvailability(page: Page) {
  return page.getByRole('region', { name: 'Venue availability' })
}

/** Stubs every `/calendar` fetch the page makes (tests/CLAUDE.md's exception for a state the
 *  seed cannot reach), leaving its own navigation and every other call on the real network. */
async function stubCalendar(page: Page, fulfill: (route: Route) => Promise<void>) {
  await page.route(
    (url) => /\/venues\/[^/]+\/calendar$/.test(url.pathname),
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      await fulfill(route)
    },
  )
}

test("13.1.3 AC1/AC2: the request detail page opens the venue calendar on the request's own day", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${NIMBUS_SEMINAR_REQUEST_ID}`)

  const calendar = venueAvailability(page)
  // AC2: the request's month, not today's.
  await expect(calendar.getByText('November 2026')).toBeVisible()
  await expect(calendar.getByText('Loading availability…')).toHaveCount(0)
  // AC1: story 9.1's legend, and the rest of the month - here, the room's seeded closure.
  await expect(calendar.getByText('Unavailable', { exact: true })).toBeVisible()
  await expect(
    calendar.getByRole('button', { name: /^2 November 2026.*Maintenance/ }),
  ).toBeVisible()

  // AC2: the request's own day is already open, listing the request as a hold.
  await expect(calendar.getByRole('button', { name: /25 November 2026/ })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
  const dayList = calendar.getByRole('region', { name: /25 Nov 2026/ })
  await expect(dayList).toContainText('Nimbus Developer Conference')
  await expect(dayList).toContainText('13:00–18:00')
  await expect(dayList).toContainText('Held – pending')

  // AC1: Next moves on a month and keeps the calendar.
  await calendar.getByRole('button', { name: 'Next →' }).click()
  await expect(calendar.getByText('December 2026')).toBeVisible()
  await expect(calendar.getByRole('button', { name: '← Prev' })).toBeVisible()
})

test("13.1.3 AC2: another booking on the request's day is listed beside it", async ({ page }) => {
  // The seed has nothing else in Seminar Room 2.1 on 25 Nov, so the calendar answer is faked.
  await stubCalendar(page, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: corsHeaders(route.request()),
      body: JSON.stringify([
        {
          starts_at: '2026-11-25T00:30:00Z',
          ends_at: '2026-11-25T04:15:00Z',
          booking_starts_at: '2026-11-25T01:00:00Z',
          booking_ends_at: '2026-11-25T04:00:00Z',
          reason: 'BOOKED',
          label: 'Morning Leadership Workshop',
        },
        {
          starts_at: '2026-11-25T04:30:00Z',
          ends_at: '2026-11-25T10:15:00Z',
          booking_starts_at: '2026-11-25T05:00:00Z',
          booking_ends_at: '2026-11-25T10:00:00Z',
          reason: 'HELD',
          label: 'Nimbus Developer Conference',
        },
      ]),
    }),
  )
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${NIMBUS_SEMINAR_REQUEST_ID}`)

  const dayList = venueAvailability(page).getByRole('region', { name: /25 Nov 2026/ })
  await expect(dayList).toContainText('Morning Leadership Workshop')
  await expect(dayList).toContainText('09:00–12:00')
  await expect(dayList).toContainText('Booked')
  await expect(dayList).toContainText(
    /Morning Leadership Workshop[\s\S]*Nimbus Developer Conference/,
  )
})

test('13.1.3 AC3: a calendar that fails to load shows availability as unknown, and the request can still be decided', async ({
  page,
}) => {
  await stubCalendar(page, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      headers: corsHeaders(route.request()),
      body: JSON.stringify({ detail: null }),
    }),
  )
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${NIMBUS_SEMINAR_REQUEST_ID}`)

  const calendar = venueAvailability(page)
  await expect(calendar.getByRole('status')).toHaveText(/Availability unknown/)
  await expect(calendar.getByRole('alert')).toContainText('The server hit a problem')
  await expect(page.getByRole('heading', { name: 'Nimbus Developer Conference' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Reject' })).toBeEnabled()
})

/** The request under review on the calendar: 13:00-18:00 with its setup and teardown. */
function nimbusWindow(reason: 'HELD' | 'BOOKED') {
  return {
    starts_at: '2026-11-25T04:30:00Z',
    ends_at: '2026-11-25T10:15:00Z',
    booking_starts_at: '2026-11-25T05:00:00Z',
    booking_ends_at: '2026-11-25T10:00:00Z',
    reason,
    label: 'Nimbus Developer Conference',
  }
}

/** Another event booked in the room that morning, so the day still has a row once Nimbus goes. */
const MORNING_WORKSHOP_WINDOW = {
  starts_at: '2026-11-25T00:30:00Z',
  ends_at: '2026-11-25T04:15:00Z',
  booking_starts_at: '2026-11-25T01:00:00Z',
  booking_ends_at: '2026-11-25T04:00:00Z',
  reason: 'BOOKED',
  label: 'Morning Leadership Workshop',
}

/**
 * Story 13.1.3 AC4: fakes the request's approve or reject call, answering with the request as the
 * page read it but decided, so the seeded request stays pending for the other tests in a
 * fullyParallel run. `isDecided` says whether the decision has been sent.
 */
async function fakeDecision(page: Page, action: 'approve' | 'reject', decided: object) {
  const requestPath = `/bookings/${NIMBUS_SEMINAR_REQUEST_ID}`
  let pendingBooking: object = {}
  let hasDecided = false
  // The page's own read of the request goes through, and is kept to answer the faked decision.
  await page.route(
    (url) => url.pathname === requestPath,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      const response = await route.fetch()
      pendingBooking = await response.json()
      await route.fulfill({ response })
    },
  )
  await page.route(
    (url) => url.pathname === `${requestPath}/${action}`,
    async (route) => {
      if (route.request().resourceType() !== 'fetch') return route.fallback()
      hasDecided = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: corsHeaders(route.request()),
        body: JSON.stringify({ ...pendingBooking, decided_at: '2026-10-07T02:00:00Z', ...decided }),
      })
    },
  )
  return { isDecided: () => hasDecided }
}

function calendarAnswer(route: Route, windows: object[]) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers: corsHeaders(route.request()),
    body: JSON.stringify(windows),
  })
}

test('13.1.3 AC4: approving on the detail page reloads the calendar in place, showing the request booked', async ({
  page,
}) => {
  const decision = await fakeDecision(page, 'approve', { status: 'APPROVED' })
  // The answer after the approval is held back, so the test can see the calendar while it reloads.
  let releaseReload: () => void = () => {}
  const reloadGate = new Promise<void>((resolve) => {
    releaseReload = resolve
  })
  await stubCalendar(page, async (route) => {
    if (!decision.isDecided()) return calendarAnswer(route, [nimbusWindow('HELD')])
    await reloadGate
    return calendarAnswer(route, [nimbusWindow('BOOKED')])
  })
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${NIMBUS_SEMINAR_REQUEST_ID}`)

  const calendar = venueAvailability(page)
  const dayList = calendar.getByRole('region', { name: /25 Nov 2026/ })
  await expect(dayList).toContainText('Held – pending')

  await page.getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  // Story 12.7: the hold's expiry, before the breakout track's booked period starts on 25 Nov.
  await dialog.getByLabel('Hold expires').fill(NIMBUS_SEMINAR_HOLD_EXPIRES)
  await dialog.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).not.toBeVisible()

  // Reloaded in place: the month and the open day stay on screen while the new answer comes.
  await expect(calendar.getByText('Loading availability…')).toBeVisible()
  await expect(calendar.getByText('November 2026')).toBeVisible()
  await expect(dayList).toContainText('Nimbus Developer Conference')

  releaseReload()
  await expect(dayList).toContainText('Booked')
  await expect(dayList).not.toContainText('Held – pending')
})

test('13.1.3 AC4: rejecting on the detail page reloads the calendar, and the request leaves its day', async ({
  page,
}) => {
  const decision = await fakeDecision(page, 'reject', {
    status: 'REJECTED',
    decision_reason: 'The room is needed for the morning workshop overrun.',
  })
  await stubCalendar(page, (route) =>
    calendarAnswer(
      route,
      decision.isDecided()
        ? [MORNING_WORKSHOP_WINDOW]
        : [MORNING_WORKSHOP_WINDOW, nimbusWindow('HELD')],
    ),
  )
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto(`/venue-staff/booking-requests/${NIMBUS_SEMINAR_REQUEST_ID}`)

  const dayList = venueAvailability(page).getByRole('region', { name: /25 Nov 2026/ })
  await expect(dayList).toContainText('Nimbus Developer Conference')

  await page.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog', { name: 'Reject this booking?' })
  await dialog
    .getByLabel('Reason for rejecting')
    .fill('The room is needed for the morning workshop overrun.')
  await dialog.getByRole('button', { name: 'Reject' }).click()
  await expect(dialog).not.toBeVisible()

  await expect(dayList).not.toContainText('Nimbus Developer Conference')
  await expect(dayList).toContainText('Morning Leadership Workshop')
})

// --- f13.1.5: both dates of a multi-day booking, in Venue Staff's views ---------------------------

const SUNRISE_STUDIO = 'Sunrise Studio'
const DAY_MS = 24 * 60 * 60 * 1000
/** The seeded Smart Cities Expo's first day, 14 Mar 2028: venue-requirement-search.spec.ts needs
 *  its venues free on it and the day after. */
const EXPO_STARTS = Date.parse('2028-03-14T00:00:00+08:00')
/** What the booking says under the venue: the request step opens at Sunrise Studio's own setup
 *  and teardown times (12.1 AC18), so Venue Staff see them around the event's times. */
const TWO_DAY_SETUP_LINE = 'Setup: 15 min · Event: 09:00–17:00 · Teardown: 15 min'

/**
 * The first day of a two-day event that books Sunrise Studio: a slot between 400 and 520 days
 * ahead, two days wide, that the Expo's days do not touch. Each attempt of the test draws from
 * its own share of the slots - every `attempts`th one, from its retry number - so a CI retry,
 * which keeps the database its first attempt booked in, can never take that attempt's slot,
 * whatever the time. Within an attempt the slot follows the minute. No seeded booking and no
 * other spec holds Sunrise Studio then: the seed's holds are in Oct 2028 and 2029, and 9.4's
 * closures are in Oct 2028 and now.
 */
function twoDayEventStart(): number {
  const expo = Math.floor((EXPO_STARTS - Date.now()) / DAY_MS)
  const slots: number[] = []
  for (let day = 400; day < 520; day += 2) {
    if (day + 1 < expo - 8 || day > expo + 3) slots.push(day)
  }
  const { retry, project } = test.info()
  const attempts = Math.max(project.retries, retry) + 1
  const own = slots.filter((_, index) => index % attempts === retry)
  return own[Math.floor(Date.now() / 60_000) % own.length]
}

/** The day and year `inFuture(days)` names, as the pages print them ("9", "2029"). */
function dayAndYear(days: number): { day: string; year: string } {
  const [year, , day] = inFuture(days).slice(0, 10).split('-')
  return { day: String(Number(day)), year }
}

/** The text of a period over two days, "Wed, 9 May 2029, 09:00 – Thu, 10 May 2029, 17:00", as a
 *  pattern of the days the event runs on: a month reads "May" or "Sept". */
function twoDaySchedule(startDays: number): string {
  const first = dayAndYear(startDays)
  const last = dayAndYear(startDays + 1)
  const when = (each: { day: string; year: string }, time: string) =>
    `[A-Z][a-z]{2}, ${each.day} [A-Za-z]{3,4} ${each.year}, ${time}`
  return `${when(first, '09:00')} – ${when(last, '17:00')}`
}

/** The Date tile of that period, "9 May 2029 – 10 May 2029". */
function twoDayTile(startDays: number): RegExp {
  const first = dayAndYear(startDays)
  const last = dayAndYear(startDays + 1)
  return new RegExp(
    `^${first.day} [A-Za-z]{3,4} ${first.year} – ${last.day} [A-Za-z]{3,4} ${last.year}$`,
  )
}

test('13.1 AC2/13.2 AC1: Venue Staff see both dates of a multi-day booking before approving it', async ({
  page,
}) => {
  test.setTimeout(150_000)
  const start = twoDayEventStart()
  const { eventId, name, coordinator } = await approvedEvent(
    page,
    'Two-day booking',
    start,
    start + 1,
  )

  // As the coordinator, through story 12.5's own steps: Sunrise Studio for the Main venue.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, coordinator)
  await page.goto(`/events/${eventId}`)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  await expect(page.getByRole('region', { name: `Finding a venue for ${name}` })).toBeVisible()
  await venueCard(page, SUNRISE_STUDIO).getByRole('link', { name: 'Request this venue' }).click()
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()

  // As Venue Staff, the queue card, found by the event's own name.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('searchbox', { name: 'Search requests' }).fill(name)
  const card = page.getByRole('listitem').filter({ hasText: name })
  const schedule = twoDaySchedule(start)
  const sentence = new RegExp(`^${SUNRISE_STUDIO} will be booked for ${name} from ${schedule}\\.$`)
  await expect(card.getByText(new RegExp(`^${schedule}$`))).toBeVisible()
  await expect(card.getByText(TWO_DAY_SETUP_LINE, { exact: true })).toBeVisible()

  // The queue's Approve dialog names both dates, and is closed without approving.
  await card.getByRole('button', { name: 'Approve' }).click()
  const queueDialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await expect(queueDialog.getByText(sentence)).toBeVisible()
  await queueDialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(queueDialog).toHaveCount(0)

  // The request's page: the Date tile names both days, the Time tile is as before, and the setup
  // and teardown line shows.
  await card.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
  await expect(page.getByText(twoDayTile(start))).toBeVisible()
  await expect(page.getByText('09:00 – 17:00', { exact: true })).toBeVisible()
  await expect(page.getByText(TWO_DAY_SETUP_LINE, { exact: true })).toBeVisible()

  // Its approve notice names both dates, and is closed without approving.
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  const pageDialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await expect(pageDialog.getByText(sentence)).toBeVisible()
  await pageDialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(pageDialog).toHaveCount(0)
})

const CHOIR_SHOWCASE = 'Community Choir Showcase'
const CHOIR_DATE = 'Sat, 14 Oct 2028'
const CHOIR_SENTENCE = `Harbour Pavilion will be booked for ${CHOIR_SHOWCASE} from ${CHOIR_DATE}, 18:00–21:00.`
/** What a two-date line looks like: a second date after the first. */
const SECOND_DATE = /^[A-Z][a-z]{2}, \d{1,2} [A-Za-z]{3,4} \d{4}, \d{2}:\d{2} – /

test('13.1 AC2/13.2 AC1: a one-day booking reads as before in the Venue Staff views', async ({
  page,
}) => {
  // The seeded Community Choir Showcase request (14 Oct 2028, 18:00-21:00, Harbour Pavilion) is
  // pending, and no spec approves, rejects, withdraws or closes over it.
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  await page.getByRole('searchbox', { name: 'Search requests' }).fill(CHOIR_SHOWCASE)
  const card = page.getByRole('listitem').filter({ hasText: CHOIR_SHOWCASE })
  await expect(card.getByText(CHOIR_DATE, { exact: true })).toBeVisible()
  await expect(card.getByText('18:00–21:00', { exact: true })).toBeVisible()
  await expect(card.getByText(SECOND_DATE)).toHaveCount(0)

  await card.getByRole('button', { name: 'Approve' }).click()
  const queueDialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await expect(queueDialog.getByText(CHOIR_SENTENCE, { exact: true })).toBeVisible()
  await queueDialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(queueDialog).toHaveCount(0)

  await card.getByRole('link', { name: CHOIR_SHOWCASE }).click()
  await expect(page.getByRole('heading', { name: CHOIR_SHOWCASE, level: 1 })).toBeVisible()
  // The Date tile, in the booking summary: the day panel of Venue availability, once its calendar
  // has loaded, heads itself with the same date.
  const summary = page.getByRole('region', { name: 'Booking summary' })
  await expect(summary.getByText(CHOIR_DATE, { exact: true })).toBeVisible()
  await expect(page.getByText('18:00 – 21:00', { exact: true })).toBeVisible()
  await expect(page.getByText(SECOND_DATE)).toHaveCount(0)

  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  const pageDialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await expect(pageDialog.getByText(CHOIR_SENTENCE, { exact: true })).toBeVisible()
  await pageDialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(pageDialog).toHaveCount(0)
})
