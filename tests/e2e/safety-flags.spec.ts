/**
 * Fix f21.2.1 (story 21.2) - the safety review flags the venue bookings it was about, not the
 * whole Venue booking section.
 * AC22 a booking a finding about venue bookings named - which the review released (21.3) - is
 *      highlighted and says "Flagged by the safety review" on its card.
 * AC23 a finding about venue bookings that names none flags the bookings pending or approved when
 *      the review was made.
 * AC24 a booking requested after the review is never flagged.
 * AC25 the section keeps its "Flagged by the safety review" line, but is not highlighted itself.
 * AC26 the coordinator's Venue booking and the organiser's Venue bookings show the same flags.
 * AC27 (nothing is flagged once the event leaves Planning or a review approves it) is the rule
 *      21.2 AC4's specs already prove: e2e/safety-decision.spec.ts.
 * That both booking lists say when each booking was requested is a backend case:
 * backend/tests/bookings/test_safety_flag_bookings.py.
 *
 * Every test only reads EVENTS.studioShowcase or EVENTS.makersFair, which no other spec uses.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { ACCOUNTS, EVENTS, signIn } from './support'

const FLAGGED = 'Flagged by the safety review'

function section(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true })
}

function bookingCard(bookings: Locator, venue: string) {
  return bookings.getByRole('listitem').filter({ hasText: venue })
}

function background(locator: Locator) {
  return locator.evaluate((element) => getComputedStyle(element).backgroundColor)
}

/** The named or reviewed Seminar Room 2.1 booking is flagged; the Exhibition Foyer request made
 * after the review is not; the section keeps its line but not the highlight. */
async function expectOnlySeminarRoomFlagged(page: Page, bookings: Locator) {
  const seminarRoom = bookingCard(bookings, 'Seminar Room 2.1')
  const foyer = bookingCard(bookings, 'Exhibition Foyer')
  await expect(seminarRoom).toContainText(FLAGGED)
  await expect(foyer).toBeVisible()
  await expect(foyer).not.toContainText(FLAGGED)

  await expect(bookings.getByText(FLAGGED, { exact: true }).first()).toBeVisible()
  expect(await background(bookings)).toBe(await background(section(page, 'Safety review')))
}

test('21.2 AC22/AC24/AC25: the coordinator sees the booking the review named flagged, not the one requested after it', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.studioShowcase}`)

  await expectOnlySeminarRoomFlagged(page, section(page, 'Venue booking'))
})

test('21.2 AC22/AC24/AC26: the organiser sees the same flags on their Venue bookings', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.studioShowcase}`)

  await expectOnlySeminarRoomFlagged(page, section(page, 'Venue bookings'))
})

test('21.2 AC23/AC24: a finding that names no booking flags the bookings the review saw', async ({
  page,
}) => {
  await signIn(page, ACCOUNTS.coordinator)
  await page.goto(`/events/${EVENTS.makersFair}`)

  await expectOnlySeminarRoomFlagged(page, section(page, 'Venue booking'))
})

test('21.2 AC23/AC26: the organiser sees the bookings the review saw flagged', async ({ page }) => {
  await signIn(page, ACCOUNTS.organiser)
  await page.goto(`/events/${EVENTS.makersFair}`)

  await expectOnlySeminarRoomFlagged(page, section(page, 'Venue bookings'))
})
