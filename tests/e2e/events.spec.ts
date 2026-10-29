/**
 * Story 7.1 - fe: display full event details.
 * AC1 the detail view shows core event details, venue requirements, accessibility requirements,
 *     equipment requirements, status and assigned coordinator.
 * AC2 users see the detail view only for events they are related to.
 * AC3 fields the user's role may not edit are shown read-only rather than hidden.
 * Which event a signed-in user may open is enforced by story 2.1 AC8's `GET /events/{id}`:
 * backend/tests/events/test_event_request_details.py already covers the 403/404 refusals this
 * relies on (an attendee, another organiser's request, a draft that is not the viewer's own).
 * This spec covers the flows a user actually clicks through, plus the one refusal that is purely
 * a frontend rendering concern: what a blocked direct URL shows.
 *
 * f7.1.1 (AC1): an event that runs over more than one day names both dates in its heading line,
 * rather than reading as its first day.
 *
 * f7.1.2 (AC1): the organiser sees their event's approved and pending venue bookings, read-only.
 * Which bookings, and that only the event's own organiser gets them, is proven in
 * backend/tests/bookings/test_organiser_bookings.py.
 *
 * Story 2.1 AC8/AC19: the registration choice/dates and visibility, already returned by the API
 * to the reviewing Event Coordinator (backend/tests/events/test_event_request_registration.py,
 * test_event_request_visibility.py), also render on this page.
 */
import { expect, test } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test('7.1 AC1: a coordinator opens an event from the review queue and sees its full details', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await page.getByRole('link', { name: 'Data Literacy Workshop' }).click()

  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Under review')).toBeVisible()
  await expect(page.getByText('Classroom')).toBeVisible()
  await expect(page.getByText('Projector & screen')).toBeVisible()
  await expect(page.getByText('Wi-Fi')).toBeVisible()
  await expect(page.getByText('No accessibility needs recorded.')).toBeVisible()
  await expect(page.getByText('Portable projector')).toBeVisible()
  await expect(page.getByText('Room already has one; spare requested')).toBeVisible()
  await expect(page.locator('img').first()).toHaveAttribute('src', '/images/events/cat.jpg')
})

test('7.1: the back link returns to wherever the event was opened from', async ({ page }) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto('/events/inbox')

  await page.getByRole('link', { name: 'Data Literacy Workshop' }).click()
  await expect(
    page.getByRole('heading', { name: 'Data Literacy Workshop', level: 1 }),
  ).toBeVisible()

  await page.getByRole('link', { name: '← Events inbox' }).click()
  await expect(page.getByRole('heading', { name: 'Events inbox', level: 1 })).toBeVisible()
})

test('7.1 AC1: the organiser who owns the event sees its venue, accessibility and equipment requirements', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(
    page.getByRole('heading', { name: 'Nimbus Developer Conference', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Planning').first()).toBeVisible()
  // exact: story 2.7 AC4 also lists the Main venue's "350 people" on this page.
  await expect(page.getByText('350', { exact: true })).toBeVisible()
  await expect(page.getByText('Chloe Coordinator').first()).toBeVisible()

  await expect(page.getByText('Theatre')).toBeVisible()
  await expect(page.getByText('Sound system')).toBeVisible()
  await expect(page.getByText('Stage')).toBeVisible()

  await expect(page.getByText('Wheelchair access')).toBeVisible()
  await expect(page.getByText('Two wheelchair users expected')).toBeVisible()
  await expect(page.getByText('Hearing loop')).toBeVisible()

  await expect(page.getByText('Wireless microphone')).toBeVisible()
  await expect(page.getByText('Two per breakout room')).toBeVisible()
  await expect(page.getByText('Presentation laptop')).toBeVisible()

  // AC3: this page only ever renders fields, it never edits them.
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
})

test("7.1 AC1: the organiser sees their event's approved and pending venue bookings, read-only", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser2)
  await page.goto(`/events/${EVENTS.approved}`)

  // f7.1.2: the seeded Grand Hall booking is approved; Seminar Room 2.1's is pending, unless
  // bookings.spec.ts approves it first - either way it is still the organiser's to see.
  const bookings = page.getByRole('region', { name: 'Venue bookings' })
  const grandHall = bookings.getByRole('listitem').filter({ hasText: 'Grand Hall' })
  await expect(grandHall).toContainText('Tower A, Level 1')
  await expect(grandHall).toContainText('Main venue')
  await expect(grandHall).toContainText('25 Nov 2026')
  await expect(grandHall).toContainText('09:00–18:00')
  await expect(grandHall).toContainText('Approved')
  const seminarRoom = bookings.getByRole('listitem').filter({ hasText: 'Seminar Room 2.1' })
  await expect(seminarRoom).toContainText('Tower A, Level 2')
  await expect(seminarRoom).toContainText('Breakout room')
  await expect(seminarRoom).toContainText('25 Nov 2026')
  await expect(seminarRoom).toContainText('13:00–18:00')

  // Read-only: none of the coordinator's booking actions.
  await expect(bookings.getByRole('button')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Venue booking', exact: true })).toHaveCount(0)
})

test('7.1 AC1: a draft with no dates or attendance shows clear empty states', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.draft}`)

  await expect(
    page.getByRole('heading', { name: 'Q1 Sales Kick-off (draft)', level: 1 }),
  ).toBeVisible()
  await expect(page.getByText('Not yet scheduled · Organised by Olivia Organiser')).toBeVisible()
  // Story 2.6 AC13: a draft has no coordinator to show yet, so the stat is left out entirely -
  // "Not yet assigned" is reserved for a submitted request nobody has assigned yet.
  await expect(page.getByText('Assigned coordinator')).toHaveCount(0)
  await expect(page.getByText('Not yet assigned')).toHaveCount(0)
  // AC1: no recorded image falls back to the placeholder rather than a broken or empty image.
  await expect(page.locator('img')).toHaveCount(0)
})

test("7.1 AC1: a two-day event's heading line shows both dates", async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.planning}`)

  await expect(
    page.getByRole('heading', { name: 'Regional Sales Summit', level: 1 }),
  ).toBeVisible()
  // The seeded summit runs 15 Dec 09:00 to 16 Dec 17:00. Matched with the organiser's name, as
  // only the heading line has it: the Main venue's line below shows the same period.
  await expect(
    page.getByText(
      'Tue, 15 Dec 2026, 09:00 – Wed, 16 Dec 2026, 17:00 · Organised by Olivia Organiser',
    ),
  ).toBeVisible()
})

test('2.1 AC8/AC19: the coordinator sees the registration choice, closing date and visibility of a submitted request', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  // Nimbus Developer Conference: registration_required = TRUE, registration_closes_at =
  // 2026-11-20 18:00+08, registration_opens_at left unset, is_public left at its default (false).
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('heading', { name: 'Registration' })).toBeVisible()
  await expect(page.getByText('Required', { exact: true })).toBeVisible()
  await expect(page.getByText('Yes', { exact: true })).toBeVisible()
  await expect(page.getByText('Immediately once approved')).toBeVisible()
  await expect(page.getByText('20 Nov 2026, 18:00')).toBeVisible()
  await expect(page.getByText('Visibility', { exact: true })).toBeVisible()
  await expect(page.getByText('Private', { exact: true })).toBeVisible()
})

test('2.1 AC8: the coordinator sees a request with no registration requirement as such', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  // Data Literacy Workshop: registration_required = FALSE (the seeded default).
  await page.goto(`/events/${EVENTS.submitted}`)

  await expect(page.getByRole('heading', { name: 'Registration' })).toBeVisible()
  await expect(page.getByText('No', { exact: true })).toBeVisible()
  await expect(page.getByText('Opens', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Closes', { exact: true })).toHaveCount(0)
})

test("7.1 AC2: an organiser cannot open another organiser's event by direct URL", async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.approved}`)

  await expect(page.getByRole('alert')).toContainText('Event not found.')
})
