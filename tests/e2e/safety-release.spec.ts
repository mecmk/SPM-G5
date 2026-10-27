/**
 * Story 21.3 - fe/be: release the venue bookings a safety finding names.
 * AC1 the review page lists each approved booking with its venue, its requirement (or "Additional
 *     venue") and its date, and under it the event page booking card's setup line, to choose
 *     from - and offers them only on a finding about venue bookings. Which bookings may be named
 *     is a backend case.
 * AC2 recording the decision releases each named booking, and the event page shows it as released
 *     by the safety review with the finding's required change as the reason.
 * AC5 the requirement that lost its booking needs a venue again, so the review cannot be sent.
 * AC8 Venue Staff find the released booking under Cancelled and All, read-only, with the same line
 *     and reason.
 * AC9 the officer's Previous reviews and the event page name what the round released.
 * Every other AC (AC3, AC4, AC6, AC7, AC10, AC11) is a backend case:
 * backend/tests/safety/test_release_flagged_bookings.py.
 *
 * The four tests run in order on one seeded event, the venue safety walkthrough, which the first
 * sends for its safety review (the coordinator clicks, as in safety-decision.spec.ts) and the
 * second moves on for good by releasing a booking. Each reads what the one before did, and a
 * retry could only fail on the moved event and hide the first trace: serial, no retries.
 */
import { expect, test, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

test.describe.configure({ mode: 'serial', retries: 0 })

const EVENT_NAME = 'Venue Safety Walkthrough'
const CHANGE = 'Book a room with a second exit.'
const RELEASED_LINE = 'Released by the safety review'
const RELEASED_MESSAGE =
  'The Safety Officer released this booking, so the venue is free for other events.'
const SEMINAR_CHOICE = 'Seminar Room 2.1 · Main hall · 10 Apr 2029'
const FOYER_CHOICE = 'Exhibition Foyer · Additional venue · 10 Apr 2029'
const SEMINAR_SETUP = 'Setup: 30 min · Event: 09:00–17:00 · Teardown: None'
const FOYER_SETUP = 'Setup: None · Event: 09:00–17:00 · Teardown: None'
const SEMINAR_BOOKING = '44444444-0000-0000-0000-000000021303'

function section(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true })
}

function statusShown(page: Page, label: string) {
  return page.getByRole('main').getByText(label, { exact: true }).first()
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click()
}

test('21.3 AC1: the review page lists each approved booking, and offers them only on a venue-bookings finding', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.safetyRelease}`)
  await section(page, 'Safety review')
    .getByRole('button', { name: 'Request safety review' })
    .click()
  await expect(statusShown(page, 'Awaiting safety check')).toBeVisible()
  await signOut(page)

  await signIn(page, ACCOUNTS.safetyOfficer)
  await page.goto(`/safety-checks/${EVENTS.safetyRelease}`)
  const decision = section(page, 'Decision')
  await decision.getByRole('radio', { name: 'Request changes' }).check()
  const finding = decision.getByRole('group', { name: 'Finding 1' })
  const bookings = finding.getByRole('group', { name: 'Bookings to release' })

  await expect(bookings).toHaveCount(0)
  await finding.getByLabel('Arrangement to rebook').selectOption({ label: 'Equipment' })
  await expect(bookings).toHaveCount(0)

  await finding.getByLabel('Arrangement to rebook').selectOption({ label: 'Venue bookings' })
  await expect(bookings).toBeVisible()
  await expect(bookings.getByRole('checkbox', { name: SEMINAR_CHOICE, exact: true })).toBeVisible()
  await expect(bookings.getByRole('checkbox', { name: FOYER_CHOICE, exact: true })).toBeVisible()
  await expect(bookings.getByText(SEMINAR_SETUP, { exact: true })).toBeVisible()
  await expect(bookings.getByText(FOYER_SETUP, { exact: true })).toBeVisible()

  await bookings.getByRole('checkbox', { name: SEMINAR_CHOICE, exact: true }).check()
  await finding.getByLabel('Arrangement to rebook').selectOption({ label: 'None' })
  await expect(bookings).toHaveCount(0)
  await finding.getByLabel('Arrangement to rebook').selectOption({ label: 'Venue bookings' })
  await expect(
    bookings.getByRole('checkbox', { name: SEMINAR_CHOICE, exact: true }),
  ).not.toBeChecked()
})

test('21.3 AC2/AC9: the officer releases a booking, and Previous reviews names what the round released', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.safetyOfficer)
  await page.goto(`/safety-checks/${EVENTS.safetyRelease}`)
  const decision = section(page, 'Decision')
  await decision.getByRole('radio', { name: 'Request changes' }).check()
  const finding = decision.getByRole('group', { name: 'Finding 1' })
  await finding.getByLabel('Factor').selectOption({ label: 'Venue capacity and layout' })
  await finding.getByLabel('What must change').fill(CHANGE)
  await finding.getByLabel('Arrangement to rebook').selectOption({ label: 'Venue bookings' })
  await finding
    .getByRole('group', { name: 'Bookings to release' })
    .getByRole('checkbox', { name: SEMINAR_CHOICE, exact: true })
    .check()
  await decision.getByRole('button', { name: 'Record decision' }).click()

  const reviews = section(page, 'Previous reviews')
  await expect(reviews).toContainText('Changes requested')
  await expect(reviews).toContainText(CHANGE)
  await expect(reviews).toContainText('Released: Seminar Room 2.1 (Main hall)')
  await expect(reviews).not.toContainText('Released: Exhibition Foyer')
  await expect(section(page, 'Decision')).toHaveCount(0)
})

test('21.3 AC2/AC5/AC9: the event page shows the booking released by the safety review, and the requirement needs a venue again', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.safetyRelease}`)

  const bookings = section(page, 'Venue booking')
  await expect(bookings.getByText(RELEASED_LINE, { exact: true })).toHaveCount(1)
  await expect(bookings).toContainText(RELEASED_MESSAGE)
  await expect(bookings).toContainText('Cancelled')
  await expect(bookings.getByText('Reason', { exact: true })).toBeVisible()
  await expect(bookings).toContainText(CHANGE)
  await expect(bookings).toContainText('Exhibition Foyer')

  const safety = section(page, 'Safety review')
  await expect(safety).toContainText('Released: Seminar Room 2.1 (Main hall)')
  await expect(safety).toContainText('Main hall has no approved venue booking.')
  await expect(page.getByText('All required venues booked')).toHaveCount(0)
  await page.getByRole('link', { name: 'Find a venue' }).click()
  const main = page
    .getByRole('region', { name: `Finding a venue for ${EVENT_NAME}` })
    .getByRole('listitem')
    .filter({ hasText: 'Main hall' })
  await expect(main).toContainText('Needs a venue')
})

test('21.3 AC8: Venue Staff find the released booking under Cancelled and All, read-only', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.venueStaff)
  await page.goto('/venue-staff/booking-requests')
  const released = page
    .getByRole('listitem')
    .filter({ hasText: EVENT_NAME })
    .filter({ hasText: 'Seminar Room 2.1' })

  await page.getByRole('tab', { name: /^Cancelled/ }).click()
  await expect(released.getByRole('heading', { name: EVENT_NAME })).toBeVisible()
  await expect(released.getByText(RELEASED_LINE, { exact: true })).toBeVisible()
  await expect(released.getByText('Approved at', { exact: true })).toBeVisible()
  await expect(released.getByText('Cancelled at', { exact: true })).toBeVisible()
  await expect(released.getByText('Reason', { exact: true })).toBeVisible()
  await expect(released).toContainText(CHANGE)
  await expect(released.getByRole('button')).toHaveCount(0)

  await page.getByRole('tab', { name: /^All/ }).click()
  await page
    .getByRole('navigation', { name: 'Pages' })
    .getByRole('button', { name: /^\d+$/ })
    .last()
    .click()
  await expect(released.getByText(RELEASED_LINE, { exact: true })).toBeVisible()
  await expect(released.getByRole('button')).toHaveCount(0)

  await page.goto(`/venue-staff/booking-requests/${SEMINAR_BOOKING}`)
  await expect(page.getByText(RELEASED_LINE, { exact: true })).toBeVisible()
  await expect(page.getByText('Reason', { exact: true })).toBeVisible()
  await expect(page.getByText(CHANGE)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})
