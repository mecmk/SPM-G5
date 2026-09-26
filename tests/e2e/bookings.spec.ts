/**
 * Story 13.1 - fe/be: display the venue staff booking requests queue.
 * AC1 the queue lists all requests for venues the staff member is responsible for.
 * AC2 each entry shows event name, requested venue, period, expected attendance and stated
 *     requirements.
 * AC3 decided requests appear too, with their decision reason, filterable through the
 *     All / Pending / Approved / Rejected tabs (the same tab pattern as the coordinator's
 *     Events inbox, story 6.1).
 * Entry shape across several rows, malformed input and 401/403 refusals are backend cases:
 * backend/tests/bookings/test_list_bookings.py.
 *
 * Story 13.2 - fe: an Approve action on the queue card and the detail page.
 * AC1 approving sets the request to Approved and moves it to the Approved tab.
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
 *     preserves a typed reason on failure, and marking it rejected / showing the outcome
 *     mirrors Approve - the card stays in the queue (now under the Rejected tab) with its
 *     reason shown, rather than disappearing.
 * AC4 the requesting coordinator reaches the outcome through normal navigation (Events inbox ->
 *     event -> its venue booking) and the same page hides decide actions from them; the booking
 *     card there reads as a history (every booking ever raised, most recent first), not just the
 *     current one - a rejected request stays visible once a fresh one is raised. (Not a numbered
 *     backlog AC of its own - it is how AC4's "reaches the outcome" is satisfied once an event can
 *     carry more than one booking - see backend/tests/bookings/test_booking_for_event.py.)
 * The reject validation matrix, permission refusals, 409s and audit behaviour are backend cases:
 * backend/tests/bookings/test_reject_booking.py. Each mutating test here uses its own dedicated
 * seeded booking, same reasoning as 13.2's.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, signIn } from './support'

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

test('13.1 AC3: the Approved tab shows a decided booking; the Rejected tab does not', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Booking Requests' })).toBeVisible()
  // The APPROVED Nimbus/Grand Hall booking, even though a different, PENDING request
  // (Product Roadmap Townhall) also books Grand Hall.
  const decidedCard = page
    .getByRole('listitem')
    .filter({ hasText: 'Nimbus Developer Conference' })
    .filter({ hasText: 'Grand Hall' })

  await page.getByRole('tab', { name: /^Approved/ }).click()
  await expect(decidedCard).toBeVisible()

  await page.getByRole('tab', { name: /^Rejected/ }).click()
  await expect(decidedCard).toHaveCount(0)
})

test('13.1: a coordinator cannot open the booking requests queue', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/venue-staff/booking-requests')

  await expect(page.getByRole('heading', { name: 'Not permitted' })).toBeVisible()
})

test('13.2 AC1: approving from the queue card marks it approved and hides its decide buttons', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Founders Day Fireside Chat' })
  await card.getByRole('button', { name: 'Approve' }).click()

  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await dialog.getByRole('button', { name: 'Approve' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(card.getByText('Approved', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Reject' })).toHaveCount(0)
})

test('13.2 AC1: approving from the detail page shows the request as approved', async ({ page }) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')

  const card = page.getByRole('listitem').filter({ hasText: 'Investor Demo Day' })
  await card.getByRole('link', { name: 'View details' }).click()

  // The queue card's own event name is also a heading, so wait for the URL - the only
  // unambiguous sign navigation to the detail page actually finished.
  await expect(page).toHaveURL(/\/venue-staff\/booking-requests\/[^/]+$/)
  await expect(page.getByRole('heading', { name: 'Investor Demo Day' })).toBeVisible()
  await page.getByRole('button', { name: 'Approve' }).click()

  const dialog = page.getByRole('dialog', { name: 'Approve this booking?' })
  await dialog.getByRole('button', { name: 'Approve' }).click()

  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('Approved', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('13.2.1 AC2/AC3: the reject dialog requires a reason, can be cancelled, and rejecting marks the card rejected with its reason', async ({
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
  const reopenedDialog = page.getByRole('dialog', { name: 'Reject this booking?' })
  await reopenedDialog
    .getByLabel('Reason for rejecting')
    .fill('Budget was reallocated to another event.')

  // AC3: duplicate submission is prevented - hold the request in flight (same trick as
  // booking-requests.spec.ts's b1.1.1 case) and confirm the button disables rather than
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
        headers: {
          'access-control-allow-origin': request.headers()['origin'] ?? '*',
          'access-control-allow-credentials': 'true',
        },
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
  await expect(page.getByRole('heading', { name: 'Alumni Homecoming Weekend' })).toBeVisible()
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
  await expect(page.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(page.getByText('The venue is unavailable that weekend.')).toBeVisible()

  // AC4 continued: raising a fresh request for the same event does not replace the rejected one
  // - both show up on the event page's history, the new request first.
  await page.goto('/bookings/new')
  await page.getByLabel('Event').selectOption({ label: 'Alumni Homecoming Weekend' })
  await page.getByLabel('Venue').selectOption({ label: 'Boardroom 3.4' })
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByRole('region', { name: 'Request sent' })).toBeVisible()

  await page.goto('/events/inbox')
  await page.getByRole('link', { name: 'Alumni Homecoming Weekend' }).click()
  const bookingSection = page.getByRole('region', { name: 'Venue booking' })
  await expect(bookingSection.getByText('Boardroom 3.4')).toBeVisible()
  await expect(bookingSection.getByText('Pending', { exact: true })).toBeVisible()
  await expect(bookingSection.getByText('Rejected', { exact: true })).toBeVisible()
  await expect(bookingSection.getByText('The venue is unavailable that weekend.')).toBeVisible()
  await expect(bookingSection).toContainText(/Pending[\s\S]*Rejected/)
})
